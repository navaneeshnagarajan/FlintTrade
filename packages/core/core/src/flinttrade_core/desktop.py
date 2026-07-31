"""Electron-desktop backend serving entry point.

The Electron source guardian calls this module from the active source checkout.
It serves the full FlintTrade backend — the gated order path, every REST
blueprint, and the built React terminal — on a loopback port, then blocks until
the desktop parent terminates it.

Design goals (distinct from :func:`flinttrade_core.app.FlintTradeApp.run`):

* **Lean and resilient.** The heavy automation loops (cron scheduler,
  Telegram bot, overnight optimiser) are deliberately *not* started here, so
  the daily-driver backend never fails to boot because an optional ML
  dependency is unavailable. Those features remain reachable
  per-request through their blueprints, which lazy-import their own deps and
  degrade gracefully when unavailable.
* **No ``.env`` dependency.** Configuration comes from ``workspace.json``
  under ``~/.flinttrade/`` (auto-created on first launch). Infrastructure
  defaults (OpenAlgo on ``127.0.0.1:5000``, empty API key) are baked into
  :class:`flinttrade_core.config.Settings`, so a fresh install runs with no
  files to edit — the user configures OpenAlgo, if they want it, from the
  in-app Settings panel.
* **Loopback only.** The server always binds ``127.0.0.1`` — never a routable
  interface — so the desktop backend is unreachable from the network.
* **Lifecycle handshake.** Once the listening socket is bound, a single
  ``FLINTTRADE_BACKEND_READY port=<port>`` line is written to stdout. The
  desktop shell waits for that line (and/or polls the health endpoint) before
  pointing its window at ``http://127.0.0.1:<port>``.

Usage::

    python -m flinttrade_core.desktop            # serve on the default port
    python -m flinttrade_core.desktop --port 0   # ask the OS for a free port
    FLINTTRADE_BACKEND_PORT=5123 flinttrade-desktop-backend
"""

from __future__ import annotations

import _thread
import argparse
import asyncio
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

# Importing the app module first applies its UTF-8 stdout configuration.
from .app import (
    _bind_runtime_emergency_dispatcher,
    _build_tick_recorder,
    _close_runtime_request_admission,
    _OrderFlowCheckpointOwner,
    _pending_tick_count,
    _prepare_tick_orderflow_state,
    _record_tick_capture_failure,
    _sanitise_tick_capture_error,
    _set_tick_capture_intent,
    _shutdown_rotation_scheduler,
    _start_rotation_scheduler,
    _tick_capture_enabled,
    _tick_capture_lifecycle_lock,
    _tick_capture_mode,
    _tick_capture_watchlist,
    _workspace_dir,
    configure_broker_router,
    create_flask_app,
    retire_broker_router_generation,
    shutdown_ditto_runtime,
)
from .backend_instance import (
    BackendInstanceAlreadyRunning,
    acquire_backend_instance_lease,
    release_retained_backend_instance_lease,
    retain_backend_instance_lease,
)
from .openalgo_client import client_close_sync
from .workspace import Workspace

logger = logging.getLogger("flinttrade.desktop")


class DesktopBackendShutdownIncomplete(RuntimeError):
    """Raised when process-owned services could not be proved quiescent."""

    def __init__(self, message: str, *, recovery_owner: Any | None = None) -> None:
        super().__init__(message)
        self.recovery_owner = recovery_owner

#: Default loopback port for the desktop backend. Kept distinct from OpenAlgo's
#: 5000-5009 range (see CLAUDE.md). Overridable via ``--port`` or the
#: ``FLINTTRADE_BACKEND_PORT`` environment variable.
DEFAULT_PORT = 5100

#: Stdout sentinel the desktop shell waits for before loading the UI.
READY_SENTINEL = "FLINTTRADE_BACKEND_READY"

_CAPTURE_RUNTIME_CONFIG = "DESKTOP_TICK_CAPTURE_RUNTIME"
_CAPTURE_CONFIG_KEYS = (
    "TICK_RECORDER",
    "TICK_STORAGE",
    "TICK_STORAGE_LOCK",
    "ORDERFLOW_AGGREGATOR",
)
_CAPTURE_THREAD_START_TIMEOUT = 2.0
_CAPTURE_THREAD_STOP_TIMEOUT = 3.0
_CAPTURE_RETAINED_FLUSH_STOP_ATTEMPTS = 2
_TICK_RETENTION_DAYS = 90
_TICK_RETENTION_INTERVAL_SECONDS = 24 * 60 * 60
_DESKTOP_SAFETY_LOOP_START_TIMEOUT = 2.0
_DESKTOP_SHUTDOWN_TIMEOUT = 60.0


def _remaining_shutdown_budget(deadline: float) -> float:
    """Return the non-negative budget left on one absolute deadline."""
    return max(0.0, deadline - time.monotonic())


def _external_exception_context(error: BaseException) -> str:
    """Return bounded non-payload context for an external failure."""
    class_name = type(error).__name__
    if not class_name.isidentifier():
        return "Exception"
    return class_name[:80]


def _retain_backend_recovery_owner(owner: Any, lease: Any) -> None:
    """Keep executable cleanup authority reachable through the retained lease."""
    retain_owner = getattr(lease, "retain_recovery_owner", None)
    if callable(retain_owner):
        retain_owner(owner)
    else:
        lease._recovery_owner = owner
    retain_backend_instance_lease(lease)


class _RetainedBoundedWorker:
    """Run one unbounded owner operation without losing a timed-out attempt."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._done = threading.Event()
        self._result: Any = None
        self._error: BaseException | None = None
        self._result_consumed = True

    def run(
        self,
        operation: Callable[[], Any],
        *,
        deadline: float,
        start_when_expired: bool = False,
    ) -> Any:
        """Run or rejoin the retained attempt within the remaining budget."""
        with self._lock:
            worker = self._thread
            if worker is None or (self._done.is_set() and self._result_consumed):
                if _remaining_shutdown_budget(deadline) <= 0.0 and not start_when_expired:
                    raise TimeoutError("shutdown deadline expired") from None
                self._done.clear()
                self._result = None
                self._error = None
                self._result_consumed = False

                def run_operation() -> None:
                    try:
                        result = operation()
                    except BaseException as exc:  # noqa: BLE001 - relayed to the owner thread
                        with self._lock:
                            self._error = exc
                    else:
                        with self._lock:
                            self._result = result
                    finally:
                        self._done.set()

                worker = threading.Thread(
                    target=run_operation,
                    name=self._name,
                    daemon=True,
                )
                self._thread = worker
                worker.start()
            done = self._done

        if not done.is_set() and not done.wait(_remaining_shutdown_budget(deadline)):
            raise TimeoutError("shutdown deadline expired") from None
        if _remaining_shutdown_budget(deadline) <= 0.0:
            raise TimeoutError("shutdown deadline expired") from None

        with self._lock:
            self._result_consumed = True
            error = self._error
            result = self._result
        if error is not None:
            raise error
        return result


class _ShutdownSignal(Protocol):
    """Cross-process shutdown coordinator supplied by the desktop wrapper."""

    def install(self, callback: Callable[[], None]) -> None: ...

    def uninstall(self, callback: Callable[[], None]) -> None: ...


class _DesktopTickStorageRollbackOwner:
    """Retain storage acquired before a tick runtime could take ownership."""

    _desktop_deadline_aware_shutdown = True

    def __init__(
        self,
        storage: Any,
        api_key: str,
        *,
        storage_lock: Any | None = None,
        on_storage_closed: Callable[[], None] | None = None,
    ) -> None:
        self.storage = storage
        self.api_key = api_key
        self._storage_lock = storage_lock
        self._on_storage_closed = on_storage_closed
        self._state_lock = threading.Lock()
        self._storage_closed = False
        self._owner_released = False
        self._close_worker = _RetainedBoundedWorker(
            "flinttrade-desktop-tick-startup-storage-close"
        )

    def sanitise_error(self, error: Any) -> str:
        """Expose only bounded exception context during construction rollback."""
        if isinstance(error, BaseException):
            return _external_exception_context(error)
        return "Exception"

    def _close_once(self) -> None:
        with self._state_lock:
            if not self._storage_closed:
                if self._storage_lock is None:
                    self.storage.close()
                else:
                    with self._storage_lock:
                        self.storage.close()
                self._storage_closed = True
            if not self._owner_released and self._on_storage_closed is not None:
                self._on_storage_closed()
                self._owner_released = True

    def close_storage(self, *, timeout: float = _CAPTURE_THREAD_STOP_TIMEOUT) -> None:
        """Close or rejoin the exact retained storage attempt within the budget."""
        deadline = time.monotonic() + max(0.0, timeout)
        try:
            self._close_worker.run(self._close_once, deadline=deadline)
        except TimeoutError:
            raise RuntimeError("Desktop tick storage shutdown timed out") from None
        except BaseException as exc:  # noqa: BLE001 - retained for a later retry
            logger.warning(
                "Desktop tick storage rollback failed (%s)",
                _external_exception_context(exc),
            )
            raise RuntimeError("Desktop tick storage shutdown failed") from None

    def stop(
        self,
        *,
        timeout: float = _CAPTURE_THREAD_STOP_TIMEOUT,
        close_storage: bool = True,
    ) -> None:
        """Quiesce the storage-only owner, optionally deferring its close."""
        if close_storage:
            self.close_storage(timeout=timeout)


class _DesktopTickCaptureRuntime:
    """Own the recorder event loop, thread, and tick storage for the sidecar."""

    def __init__(
        self,
        recorder: Any,
        storage: Any,
        api_key: str,
        *,
        storage_lock: Any | None = None,
        checkpoint_owner: _OrderFlowCheckpointOwner | None = None,
        retention_days: int = _TICK_RETENTION_DAYS,
        retention_interval_seconds: float = _TICK_RETENTION_INTERVAL_SECONDS,
        on_failure: Callable[[str], None] | None = None,
        on_unpublish: Callable[[], None] | None = None,
        on_storage_closed: Callable[[], None] | None = None,
    ) -> None:
        self.recorder = recorder
        self.storage = storage
        self.api_key = api_key
        self._storage_lock = storage_lock
        self._checkpoint_owner = checkpoint_owner
        self._retention_days = retention_days
        self._retention_interval_seconds = retention_interval_seconds
        self._retention_stop = threading.Event()
        self._retention_owner_lock = threading.Lock()
        self._retention_pruning = False
        self._retention_started = False
        self._recorder_finished = threading.Event()
        self._redaction_lock = threading.Lock()
        self._redaction_keys = {api_key} if api_key else set()
        self._on_failure = on_failure
        self._on_unpublish = on_unpublish
        self._on_storage_closed = on_storage_closed
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[Any] | None = None
        self._started = threading.Event()
        self._stop_lock = threading.Lock()
        self._stopped = False
        self._startup_error: BaseException | None = None
        self._shutdown_error_lock = threading.Lock()
        self._shutdown_error: BaseException | None = None
        self._shutdown_error_retryable = False
        self._retained_flush_worker_lock = threading.Lock()
        self._retained_flush_worker: threading.Thread | None = None
        self._retained_flush_done = threading.Event()
        self._retained_flush_result: bool | None = None
        self._storage_close_lock = threading.Lock()
        self._storage_closed = False
        self._storage_close_worker_lock = threading.Lock()
        self._storage_close_worker: threading.Thread | None = None
        self._storage_close_done = threading.Event()
        self._storage_close_result: bool | None = None
        self._defer_storage_close = False
        self._unpublish_lock = threading.Lock()
        self._unpublished = False
        self._thread = threading.Thread(
            target=self._run,
            name="flinttrade-desktop-tick-capture",
            daemon=False,
        )
        self._retention_thread = (
            threading.Thread(
                target=self._run_periodic_retention,
                name="flinttrade-desktop-tick-pruning",
                daemon=True,
            )
            if retention_days > 0 and callable(getattr(storage, "prune_ticks", None))
            else None
        )

    def start(self) -> None:
        """Start the recorder loop and its separately owned pruning worker."""
        self._thread.start()
        if not self._started.wait(_CAPTURE_THREAD_START_TIMEOUT):
            raise RuntimeError("Tick capture event loop did not start")
        if self._startup_error is not None:
            raise RuntimeError("Tick capture event loop failed during startup") from None
        if not self._thread.is_alive():
            raise RuntimeError("Tick capture event loop stopped during startup")
        with self._retention_owner_lock:
            if self._retention_thread is not None and not self._retention_stop.is_set():
                self._retention_thread.start()
                self._retention_started = True

    def _is_stopped(self) -> bool:
        with self._stop_lock:
            return self._stopped

    def update_api_key(self, api_key: str) -> None:
        """Add a hot-reloaded key to the runtime's error-redaction set."""
        with self._redaction_lock:
            self.api_key = api_key
            if api_key:
                self._redaction_keys.add(api_key)

    def _sanitise(self, error: Any) -> str:
        with self._redaction_lock:
            keys = tuple(self._redaction_keys)
        diagnostic = _sanitise_tick_capture_error(error, "")
        for key in keys:
            diagnostic = _sanitise_tick_capture_error(diagnostic, key)
        return diagnostic

    def sanitise_error(self, error: Any) -> str:
        """Sanitise a diagnostic with every API key seen by this runtime."""
        return self._sanitise(error)

    def _signal_startup(self, task: asyncio.Task[Any]) -> None:
        """Mark startup only after the recorder task has entered the event loop."""
        if task.done():
            try:
                task.result()
            except BaseException as exc:  # noqa: BLE001 - relayed to the starter thread
                self._startup_error = exc
        self._started.set()

    def _unpublish_once(self) -> None:
        """Remove route-visible handles before recorder or storage teardown."""
        with self._unpublish_lock:
            if self._unpublished:
                return
            self._unpublished = True
        if self._on_unpublish is not None:
            try:
                self._on_unpublish()
            except Exception as exc:  # pragma: no cover - teardown must retain storage ownership
                logger.warning(
                    "Desktop tick runtime unpublish failed (%s)",
                    self._sanitise(exc),
                )

    def _close_storage_once(self) -> bool:
        """Close storage once successfully; a failed close remains retryable."""
        self._retention_stop.set()
        with self._storage_close_lock:
            if self._storage_closed:
                return True
            with self._retention_owner_lock:
                if self._retention_pruning:
                    return False
            try:
                pending_tick_count = _pending_tick_count(self.recorder)
                if pending_tick_count is None:
                    raise RuntimeError("tick recorder pending buffer is unknown")
                if pending_tick_count > 0:
                    for _attempt in range(_CAPTURE_RETAINED_FLUSH_STOP_ATTEMPTS):
                        if self._retry_retained_flush():
                            break
                    pending_tick_count = _pending_tick_count(self.recorder)
                    if pending_tick_count is None:
                        raise RuntimeError("tick recorder pending buffer is unknown")
                    if pending_tick_count > 0:
                        raise RuntimeError("tick recorder still has a retained buffer")
                if self._checkpoint_owner is not None:
                    self._checkpoint_owner.persist(force=True)
                if self._storage_lock is None:
                    self.storage.close()
                else:
                    with self._storage_lock:
                        self.storage.close()
            except Exception as exc:  # pragma: no cover - defensive shutdown
                diagnostic = self._sanitise(exc)
                logger.warning("Desktop tick storage close failed (%s)", diagnostic)
                return False
            self._storage_closed = True
        if self._on_storage_closed is not None:
            try:
                self._on_storage_closed()
            except Exception as exc:  # pragma: no cover - closed storage is still safe
                logger.warning(
                    "Desktop tick runtime owner cleanup failed (%s)",
                    self._sanitise(exc),
                )
        return True

    def _start_storage_close_worker(self) -> bool:
        """Start one close attempt, or retain an attempt that is still running."""
        with self._storage_close_worker_lock:
            if self._storage_closed:
                self._storage_close_result = True
                self._storage_close_done.set()
                return False
            worker = self._storage_close_worker
            if worker is not None and worker.is_alive() and not self._storage_close_done.is_set():
                return False
            self._storage_close_done.clear()
            self._storage_close_result = None

            def close_owned_storage() -> None:
                result = self._close_storage_once()
                with self._storage_close_worker_lock:
                    self._storage_close_result = result
                self._storage_close_done.set()

            worker = threading.Thread(
                target=close_owned_storage,
                name="flinttrade-desktop-tick-storage-close",
                daemon=True,
            )
            self._storage_close_worker = worker
            worker.start()
            return True

    def _report_failure(self, error: BaseException) -> None:
        diagnostic = self._sanitise(error)
        logger.warning("Desktop tick recorder stopped unexpectedly (%s)", diagnostic)
        if self._on_failure is not None:
            try:
                self._on_failure(diagnostic)
            except Exception as exc:  # pragma: no cover - failure reporting must not wedge cleanup
                logger.warning(
                    "Desktop tick failure reporting failed (%s)",
                    self._sanitise(exc),
                )

    def _remember_shutdown_error(
        self,
        error: BaseException,
        *,
        retryable: bool = False,
    ) -> None:
        """Retain the first recorder cleanup error without exposing its payload."""
        with self._shutdown_error_lock:
            if self._shutdown_error is None:
                self._shutdown_error = error
                self._shutdown_error_retryable = retryable
        logger.warning(
            "Desktop tick recorder cleanup failed (%s)",
            self._sanitise(error),
        )

    def _raise_if_shutdown_failed(self) -> None:
        with self._shutdown_error_lock:
            failed = self._shutdown_error is not None
        if failed:
            raise RuntimeError("Desktop tick capture shutdown failed") from None

    def _has_retryable_shutdown_error(self) -> bool:
        with self._shutdown_error_lock:
            return self._shutdown_error is not None and self._shutdown_error_retryable

    def _clear_retryable_shutdown_error(self) -> None:
        with self._shutdown_error_lock:
            if self._shutdown_error_retryable:
                self._shutdown_error = None
                self._shutdown_error_retryable = False

    def _retry_retained_flush(self) -> bool:
        """Retry a recorder finalisation failure while storage is still owned."""
        flush_pending = getattr(self.recorder, "flush_pending", None)
        pending_tick_count = _pending_tick_count(self.recorder)
        if pending_tick_count is None:
            return False
        if pending_tick_count == 0:
            self._clear_retryable_shutdown_error()
            return True
        if not callable(flush_pending):
            return False
        try:
            flush_pending()
        except BaseException as exc:  # noqa: BLE001 - retained for truthful shutdown status
            self._remember_shutdown_error(exc, retryable=True)
            return False
        remaining_tick_count = _pending_tick_count(self.recorder)
        if remaining_tick_count != 0:
            self._remember_shutdown_error(
                RuntimeError("tick recorder still has a retained buffer"),
                retryable=True,
            )
            return False
        self._clear_retryable_shutdown_error()
        return True

    def _start_retained_flush_worker(self) -> bool:
        """Start one bounded retry wave or retain the exact running worker."""
        with self._retained_flush_worker_lock:
            worker = self._retained_flush_worker
            if worker is not None and worker.is_alive() and not self._retained_flush_done.is_set():
                return False
            self._retained_flush_done.clear()
            self._retained_flush_result = None

            def flush_retained_ticks() -> None:
                result = False
                for _attempt in range(_CAPTURE_RETAINED_FLUSH_STOP_ATTEMPTS):
                    if self._retry_retained_flush():
                        result = True
                        break
                with self._retained_flush_worker_lock:
                    self._retained_flush_result = result
                self._retained_flush_done.set()

            worker = threading.Thread(
                target=flush_retained_ticks,
                name="flinttrade-desktop-tick-flush",
                daemon=True,
            )
            self._retained_flush_worker = worker
            worker.start()
            return True

    def _join_retained_flush(self, deadline: float) -> None:
        """Bound retained-buffer finalisation while preserving retry authority."""
        if not self._has_retryable_shutdown_error():
            return
        self._start_retained_flush_worker()
        if not self._retained_flush_done.wait(max(0.0, deadline - time.monotonic())):
            raise RuntimeError("Desktop tick capture shutdown timed out") from None
        with self._retained_flush_worker_lock:
            result = self._retained_flush_result
        if result is not True:
            self._raise_if_shutdown_failed()

    def _run_periodic_retention(self) -> None:
        """Prune old ticks without blocking the recorder's event loop."""
        try:
            interval = max(0.0, self._retention_interval_seconds)
            while not self._retention_stop.wait(interval):
                with self._retention_owner_lock:
                    if self._retention_stop.is_set():
                        return
                    self._retention_pruning = True
                try:
                    if self._storage_lock is None:
                        pruned = self.storage.prune_ticks(self._retention_days)
                    else:
                        with self._storage_lock:
                            pruned = self.storage.prune_ticks(self._retention_days)
                    if pruned:
                        logger.info("Desktop tick retention pruned %d rows", pruned)
                except Exception as exc:  # retention must never stop live capture
                    logger.warning(
                        "Desktop tick retention failed (%s)",
                        self._sanitise(exc),
                    )
                finally:
                    with self._retention_owner_lock:
                        self._retention_pruning = False
        finally:
            if self._recorder_finished.is_set() and not self._is_stopped():
                with self._storage_close_worker_lock:
                    defer_storage_close = self._defer_storage_close
                if not self._has_retryable_shutdown_error() and not defer_storage_close:
                    self._start_storage_close_worker()

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            if self._is_stopped():
                self._started.set()
                return

            task = loop.create_task(self.recorder.run())
            self._task = task
            loop.call_soon(self._signal_startup, task)
            if self._is_stopped():
                task.cancel()

            failure: BaseException | None = None
            try:
                loop.run_until_complete(task)
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # recorder failures are surfaced through Flask status
                failure = exc
            else:
                if not self._is_stopped():
                    failure = RuntimeError("Tick recorder stopped unexpectedly")

            if failure is not None:
                if self._is_stopped():
                    pending_tick_count = _pending_tick_count(self.recorder)
                    if pending_tick_count == 0:
                        self._remember_shutdown_error(failure)
                    elif not self._retry_retained_flush():
                        self._remember_shutdown_error(failure, retryable=True)
                else:
                    self._report_failure(failure)
                    pending_tick_count = _pending_tick_count(self.recorder)
                    if pending_tick_count is None or pending_tick_count > 0:
                        self._remember_shutdown_error(failure, retryable=True)
        finally:
            self._started.set()
            self._retention_stop.set()
            pending = [pending_task for pending_task in asyncio.all_tasks(loop) if not pending_task.done()]
            for pending_task in pending:
                pending_task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._task = None
            self._loop = None
            loop.close()
            self._unpublish_once()
            self._recorder_finished.set()
            with self._storage_close_worker_lock:
                defer_storage_close = self._defer_storage_close
            if not self._has_retryable_shutdown_error() and not defer_storage_close:
                self._start_storage_close_worker()

    def stop(
        self,
        *,
        timeout: float = _CAPTURE_THREAD_STOP_TIMEOUT,
        close_storage: bool = True,
    ) -> None:
        """Stop capture and fail truthfully if cleanup cannot complete."""
        if not close_storage:
            with self._storage_close_worker_lock:
                self._defer_storage_close = True
        with self._stop_lock:
            first_stop = not self._stopped
            if first_stop:
                self._stopped = True

        self._unpublish_once()
        self._retention_stop.set()

        if first_stop:
            loop = self._loop
            task = self._task

            def request_stop() -> None:
                try:
                    self.recorder.stop()
                except Exception as exc:  # pragma: no cover - defensive shutdown
                    self._remember_shutdown_error(exc)
                if task is not None and not task.done():
                    task.cancel()

            if loop is not None and loop.is_running():
                try:
                    loop.call_soon_threadsafe(request_stop)
                except RuntimeError:
                    request_stop()
            else:
                request_stop()

        bounded_timeout = max(0.0, timeout)
        deadline = time.monotonic() + bounded_timeout
        if self._thread.is_alive():
            self._thread.join(timeout=max(0.0, deadline - time.monotonic()))
        with self._retention_owner_lock:
            retention_owner = self._retention_thread if self._retention_started else None
        if retention_owner is not None and retention_owner.is_alive():
            retention_owner.join(timeout=max(0.0, deadline - time.monotonic()))

        recorder_alive = self._thread.is_alive()
        retention_alive = retention_owner is not None and retention_owner.is_alive()
        if recorder_alive:
            logger.warning("Desktop tick recorder did not stop within %.1fs", bounded_timeout)
        if retention_alive:
            logger.warning("Desktop tick pruning did not stop within %.1fs", bounded_timeout)
        if recorder_alive or retention_alive:
            raise RuntimeError("Desktop tick capture shutdown timed out") from None

        self._join_retained_flush(deadline)
        if close_storage:
            self.close_storage(timeout=max(0.0, deadline - time.monotonic()))
        self._raise_if_shutdown_failed()

    def close_storage(self, *, timeout: float = _CAPTURE_THREAD_STOP_TIMEOUT) -> None:
        """Checkpoint and close storage within a bounded, retryable wait."""
        if self._thread.is_alive():
            raise RuntimeError("Desktop tick capture must stop before storage closes")
        deadline = time.monotonic() + max(0.0, timeout)

        def wait_for_close_result() -> bool | None:
            if not self._storage_close_done.wait(max(0.0, deadline - time.monotonic())):
                raise RuntimeError("Desktop tick storage shutdown timed out") from None
            with self._storage_close_worker_lock:
                return self._storage_close_result

        with self._storage_close_worker_lock:
            close_result_ready = self._storage_close_done.is_set()
        if not close_result_ready:
            self._start_storage_close_worker()
        close_result = wait_for_close_result()
        if close_result is not True:
            self._start_storage_close_worker()
            close_result = wait_for_close_result()
        if close_result is not True:
            if self._has_retryable_shutdown_error():
                self._raise_if_shutdown_failed()
            raise RuntimeError("Desktop tick storage shutdown failed") from None


def _configure_tick_capture(
    flask_app: Any,
    settings: Any,
    *,
    storage_factory: Callable[[str], Any] | None = None,
    recorder_factory: Callable[..., Any] | None = None,
    orderflow_factory: Callable[[], Any] | None = None,
    build_recorder: Callable[..., Any] = _build_tick_recorder,
) -> _DesktopTickCaptureRuntime | None:
    """Apply capture intent and start the desktop recorder when configured."""
    enabled = _tick_capture_enabled()
    _set_tick_capture_intent(flask_app, enabled)
    if not enabled:
        return None

    storage: Any | None = None
    storage_lock: Any | None = None
    runtime: _DesktopTickCaptureRuntime | None = None
    checkpoint_owner: _OrderFlowCheckpointOwner | None = None
    api_key = str(getattr(settings, "openalgo_api_key", "") or "")
    try:
        if storage_factory is None:
            from flinttrade_data.storage import StorageManager  # noqa: PLC0415

            storage_factory = StorageManager
        if recorder_factory is None:
            from flinttrade_data.tick_recorder import TickRecorder  # noqa: PLC0415

            recorder_factory = TickRecorder
        if orderflow_factory is None:
            from flinttrade_data.orderflow_aggregator import (  # noqa: PLC0415
                create_live_market_orderflow_aggregator,
            )

            orderflow_factory = create_live_market_orderflow_aggregator

        storage = storage_factory(str(_workspace_dir() / "ticks.duckdb"))
        storage.initialise()
        storage_lock = threading.Lock()
        orderflow = orderflow_factory()
        watchlist = _tick_capture_watchlist()
        if callable(getattr(storage, "get_tick_replay_cursor", None)) and callable(
            getattr(orderflow, "export_state", None)
        ):
            checkpoint_owner = _OrderFlowCheckpointOwner(
                storage,
                orderflow,
                workspace_dir=_workspace_dir(),
                storage_lock=storage_lock,
            )
        restore_summary = _prepare_tick_orderflow_state(
            storage,
            orderflow,
            watchlist,
            storage_lock=storage_lock,
            retention_days=_TICK_RETENTION_DAYS,
            checkpoint_owner=checkpoint_owner,
        )
        recorder = build_recorder(
            recorder_factory=recorder_factory,
            signal_hub=flask_app.config.get("SIGNAL_HUB"),
            sandbox_engine=flask_app.config.get("DATA_SANDBOX_ENGINE"),
            settings=settings,
            storage=storage,
            storage_lock=storage_lock,
            orderflow=orderflow,
            watchlist=watchlist,
            mode=_tick_capture_mode(),
            post_flush_callback=(
                checkpoint_owner.persist_locked
                if checkpoint_owner is not None
                else None
            ),
        )

        def capture_failed(diagnostic: str) -> None:
            with _tick_capture_lifecycle_lock(flask_app):
                if flask_app.config.get("TICK_RECORDER") is not recorder:
                    return
                for key in _CAPTURE_CONFIG_KEYS:
                    flask_app.config.pop(key, None)
                flask_app.config["TICK_CAPTURE_ERROR"] = diagnostic

        def unpublish_runtime() -> None:
            with _tick_capture_lifecycle_lock(flask_app):
                if flask_app.config.get(_CAPTURE_RUNTIME_CONFIG) is not runtime:
                    return
                for key in _CAPTURE_CONFIG_KEYS:
                    flask_app.config.pop(key, None)

        def release_runtime_owner() -> None:
            with _tick_capture_lifecycle_lock(flask_app):
                if flask_app.config.get(_CAPTURE_RUNTIME_CONFIG) is runtime:
                    flask_app.config.pop(_CAPTURE_RUNTIME_CONFIG, None)

        runtime = _DesktopTickCaptureRuntime(
            recorder,
            storage,
            api_key,
            storage_lock=storage_lock,
            checkpoint_owner=checkpoint_owner,
            retention_days=_TICK_RETENTION_DAYS,
            on_failure=capture_failed,
            on_unpublish=unpublish_runtime,
            on_storage_closed=release_runtime_owner,
        )
        flask_app.config.update(
            {
                "ORDERFLOW_AGGREGATOR": orderflow,
                "TICK_RECORDER": recorder,
                "TICK_STORAGE": storage,
                "TICK_STORAGE_LOCK": storage_lock,
                _CAPTURE_RUNTIME_CONFIG: runtime,
            }
        )
        runtime.start()
        logger.info(
            "Desktop tick capture prepared (pruned=%d restored=%d restore_failures=%d)",
            restore_summary["pruned_ticks"],
            restore_summary["restored_ticks"],
            restore_summary["restore_failures"],
        )
        return runtime
    except Exception as exc:
        rollback_incomplete = False
        if runtime is not None:
            try:
                runtime.stop()
            except Exception as cleanup_exc:  # noqa: BLE001 - retain original startup failure
                rollback_incomplete = True
                logger.warning(
                    "Desktop tick runtime rollback failed (%s)",
                    _external_exception_context(cleanup_exc),
                )
        elif storage is not None:
            rollback_owner: _DesktopTickStorageRollbackOwner | None = None

            def release_rollback_owner() -> None:
                with _tick_capture_lifecycle_lock(flask_app):
                    if flask_app.config.get(_CAPTURE_RUNTIME_CONFIG) is rollback_owner:
                        flask_app.config.pop(_CAPTURE_RUNTIME_CONFIG, None)

            rollback_owner = _DesktopTickStorageRollbackOwner(
                storage,
                api_key,
                storage_lock=storage_lock,
                on_storage_closed=release_rollback_owner,
            )
            flask_app.config[_CAPTURE_RUNTIME_CONFIG] = rollback_owner
            try:
                rollback_owner.stop()
            except Exception as cleanup_exc:  # pragma: no cover - defensive rollback
                rollback_incomplete = True
                logger.warning(
                    "Desktop tick storage rollback failed (%s)",
                    _external_exception_context(cleanup_exc),
                )
        for key in _CAPTURE_CONFIG_KEYS:
            flask_app.config.pop(key, None)
        if runtime is not None:
            if rollback_incomplete:
                flask_app.config.setdefault(_CAPTURE_RUNTIME_CONFIG, runtime)
            elif flask_app.config.get(_CAPTURE_RUNTIME_CONFIG) is runtime:
                flask_app.config.pop(_CAPTURE_RUNTIME_CONFIG, None)
        _record_tick_capture_failure(
            flask_app,
            _external_exception_context(exc),
            "",
        )
        return None


def _ensure_workspace() -> Workspace:
    """Create ``~/.flinttrade/`` with defaults on first launch.

    A freshly installed desktop app has no workspace yet. Initialising it here
    means the very first boot writes ``workspace.json`` and the data/log/archive
    directories, so every downstream component (config, vault, audit log) finds
    the layout it expects without the user running any CLI command.

    Returns:
        The initialised :class:`Workspace`.
    """
    ws = Workspace()
    if not ws.config_path.exists():
        ws.initialise()
    return ws


def _bind_desktop_safety_runtime(flask_app: Any, safety: Any, client: Any) -> Any:
    """Bind desktop MTM checks to the shared broker loop and current dispatcher.

    The packaged desktop deliberately does not start the full async application
    runtime. It must therefore reuse the OpenAlgo client's persistent owner
    loop rather than creating a second safety monitor or per-request loop.
    """
    if safety is None or client is None:
        raise RuntimeError("desktop safety runtime requires both SafetySystem and broker-loop owner")
    owner_loop = getattr(client, "_ensure_owner_loop", None)
    if not callable(owner_loop):
        raise RuntimeError("desktop broker client has no persistent owner loop")

    loop = None
    try:
        loop = owner_loop()
        deadline = time.monotonic() + _DESKTOP_SAFETY_LOOP_START_TIMEOUT
        while not loop.is_running() and time.monotonic() < deadline:
            time.sleep(0.01)
        if loop.is_closed() or not loop.is_running():
            raise RuntimeError("desktop broker owner loop did not start")
        safety.bind_runtime_loop(loop)
        dispatcher = _bind_runtime_emergency_dispatcher(flask_app, safety, None, client)
        configure_broker_router(
            flask_app,
            flask_app.config.get("REGISTRY"),
            flask_app.config.get("CREDENTIAL_STORE"),
            client,
        )
    except Exception:
        safety.bind_emergency_dispatcher(None)
        unbind_runtime_loop = getattr(safety, "unbind_runtime_loop", None)
        if callable(unbind_runtime_loop) and loop is not None:
            unbind_runtime_loop(loop)
        flask_app.config["EMERGENCY_RUNTIME_READY"] = False
        flask_app.config.pop("EMERGENCY_DISPATCHER", None)
        raise
    return dispatcher


def _close_desktop_build_dependencies(client: Any, audit: Any) -> bool:
    """Close unpublished build dependencies without abandoning either owner."""
    complete = True
    if client is not None:
        try:
            client_close_sync(client)
        except Exception as exc:  # noqa: BLE001 - retain the exact client for recovery
            complete = False
            logger.warning("Desktop startup client rollback failed (%s)", type(exc).__name__)
    close_audit = getattr(audit, "close", None)
    if callable(close_audit):
        try:
            close_audit()
        except Exception as exc:  # noqa: BLE001 - retain the exact audit owner for recovery
            complete = False
            logger.warning("Desktop startup audit rollback failed (%s)", type(exc).__name__)
    return complete


def _rollback_desktop_build(
    flask_app: Any,
    *,
    client: Any,
    audit: Any,
    smart_order_started: bool,
) -> bool:
    """Quiesce the remaining build owners before abandoning startup."""
    complete = True
    flask_app.config["RUNTIME_ACCEPTING_REQUESTS"] = False
    try:
        _close_runtime_request_admission(flask_app)
    except Exception as exc:  # noqa: BLE001 - continue quiescing independent owners
        complete = False
        logger.warning("Desktop startup admission rollback failed (%s)", type(exc).__name__)

    runtime = flask_app.config.get(_CAPTURE_RUNTIME_CONFIG)
    if runtime is not None:
        try:
            runtime.stop()
        except Exception as exc:  # noqa: BLE001 - retain runtime through the Flask owner
            complete = False
            logger.warning(
                "Desktop startup tick rollback failed (%s)",
                _external_exception_context(exc),
            )

    live_writers_stopped = True
    if smart_order_started:
        try:
            from .smart_order_routes import shutdown_smart_order_jobs  # noqa: PLC0415

            if not shutdown_smart_order_jobs(timeout=30.0):
                live_writers_stopped = False
                complete = False
                logger.warning("Desktop startup smart-order rollback timed out")
        except Exception as exc:  # noqa: BLE001 - retain routing dependencies for recovery
            live_writers_stopped = False
            complete = False
            logger.warning("Desktop startup smart-order rollback failed (%s)", type(exc).__name__)

    try:
        if not shutdown_ditto_runtime(flask_app, timeout=5.0):
            live_writers_stopped = False
            complete = False
            logger.warning("Desktop startup Ditto rollback timed out")
    except Exception as exc:  # noqa: BLE001 - retain routing dependencies for recovery
        live_writers_stopped = False
        complete = False
        logger.warning("Desktop startup Ditto rollback failed (%s)", type(exc).__name__)

    if live_writers_stopped:
        try:
            if not retire_broker_router_generation(flask_app):
                complete = False
                logger.warning("Desktop startup broker-router rollback timed out")
        except Exception as exc:  # noqa: BLE001 - retain routing dependencies for recovery
            complete = False
            logger.warning("Desktop startup broker-router rollback failed (%s)", type(exc).__name__)

    if complete:
        complete = _close_desktop_build_dependencies(client, audit)
    return complete


class _DesktopStartupRollbackRecoveryOwner:
    """Retain and retry the exact owners acquired by an interrupted build."""

    def __init__(
        self,
        flask_app: Any | None,
        *,
        client: Any,
        audit: Any,
        local_ai_attempted: bool,
        smart_order_started: bool,
        startup_error_context: str,
    ) -> None:
        self.app = flask_app
        self._client = client
        self._audit = audit
        self._local_ai_complete = not local_ai_attempted or flask_app is None
        self._owners_complete = False
        self._smart_order_started = smart_order_started
        self._startup_error_context = startup_error_context
        self._rollback_worker = _RetainedBoundedWorker(
            "flinttrade-desktop-startup-rollback"
        )
        self._local_ai_worker = _RetainedBoundedWorker(
            "flinttrade-desktop-startup-local-ai"
        )
        self._lease_worker = _RetainedBoundedWorker(
            "flinttrade-desktop-startup-lease-release"
        )
        self._attempt_lock = threading.Lock()
        self._lease_lock = threading.Lock()
        self._backend_lease: Any = None
        self._rollback_complete = False
        self._released = False

    def _rollback_once(self) -> bool:
        if self.app is None:
            return _close_desktop_build_dependencies(self._client, self._audit)
        return _rollback_desktop_build(
            self.app,
            client=self._client,
            audit=self._audit,
            smart_order_started=self._smart_order_started,
        )

    def attempt_rollback(self, *, deadline: float) -> bool:
        """Run or rejoin rollback without exposing the triggering exception."""
        if self._rollback_complete:
            return True
        expired_at_entry = _remaining_shutdown_budget(deadline) <= 0.0
        if not self._local_ai_complete and self.app is not None:
            self.app.config["RUNTIME_ACCEPTING_REQUESTS"] = False

            def stop_local_ai() -> bool:
                from .local_ai_routes import shutdown_local_ai_runtime  # noqa: PLC0415

                return bool(
                    shutdown_local_ai_runtime(
                        self.app,
                        timeout=min(5.0, _remaining_shutdown_budget(deadline)),
                    )
                )

            try:
                local_ai_complete = bool(
                    self._local_ai_worker.run(
                        stop_local_ai,
                        deadline=deadline,
                        start_when_expired=True,
                    )
                )
            except TimeoutError:
                logger.warning("Desktop startup managed local AI rollback timed out")
                return False
            except BaseException as exc:  # noqa: BLE001 - exact owner remains retryable
                logger.warning(
                    "Desktop startup managed local AI rollback failed (%s)",
                    _external_exception_context(exc),
                )
                local_ai_complete = False
            if expired_at_entry or _remaining_shutdown_budget(deadline) <= 0.0:
                logger.warning("Desktop startup managed local AI rollback timed out")
                return False
            if local_ai_complete:
                self._local_ai_complete = True
            else:
                logger.warning("Desktop startup managed local AI rollback timed out")
        if not self._owners_complete:
            try:
                self._owners_complete = bool(
                    self._rollback_worker.run(self._rollback_once, deadline=deadline)
                )
            except TimeoutError:
                logger.warning("Desktop backend startup rollback timed out")
                return False
            except BaseException as exc:  # noqa: BLE001 - exact owner remains retryable
                logger.warning(
                    "Desktop backend startup rollback failed (%s)",
                    _external_exception_context(exc),
                )
                return False
        complete = bool(self._local_ai_complete and self._owners_complete)
        if complete:
            self._rollback_complete = True
        return complete

    def retain_backend_lease(self, lease: Any) -> None:
        """Attach the lease so one object retains cleanup and retry authority."""
        with self._lease_lock:
            if self._backend_lease is not None and self._backend_lease is not lease:
                raise RuntimeError("desktop startup recovery owner already has a different backend lease")
            if self._released:
                raise RuntimeError("completed desktop startup recovery cannot retain a backend lease")
            self._backend_lease = lease
            _retain_backend_recovery_owner(self, lease)

    def release(self, *, deadline: float) -> None:
        """Finish startup rollback and release the attached lease by the deadline."""
        if self._released:
            return
        remaining = _remaining_shutdown_budget(deadline)
        acquired = (
            self._attempt_lock.acquire(blocking=False)
            if remaining <= 0.0
            else self._attempt_lock.acquire(timeout=remaining)
        )
        if not acquired:
            raise DesktopBackendShutdownIncomplete(
                f"Desktop backend startup rollback failed ({self._startup_error_context})",
                recovery_owner=self,
            ) from None
        try:
            if self.attempt_rollback(deadline=deadline):
                with self._lease_lock:
                    backend_lease = self._backend_lease
                if backend_lease is None:
                    self._released = True
                    return
                try:
                    self._lease_worker.run(
                        lambda: release_retained_backend_instance_lease(backend_lease),
                        deadline=deadline,
                    )
                except TimeoutError:
                    logger.warning("Desktop backend startup lease release timed out")
                except BaseException as exc:  # noqa: BLE001 - lease remains globally retained
                    logger.warning(
                        "Desktop backend startup lease release failed (%s)",
                        _external_exception_context(exc),
                    )
                else:
                    self._released = True
                    return
        finally:
            self._attempt_lock.release()
        raise DesktopBackendShutdownIncomplete(
            f"Desktop backend startup rollback failed ({self._startup_error_context})",
            recovery_owner=self,
        ) from None


def _build_app() -> object:
    """Construct the Flask app with the full safety + order-routing surface.

    Mirrors the wiring :meth:`FlintTradeApp.start` performs, minus the async
    automation loops: a :class:`SafetySystem`, :class:`AuditLogger`, and
    :class:`OpenAlgoClient` are passed in so the gated order path and the
    safety endpoints are fully live. The broker router, credential vault,
    registry, and contract manager are self-bootstrapped inside
    :func:`create_flask_app` when not supplied.

    Each of these is best-effort: if a piece cannot be built (e.g. the engine
    package is unavailable in a stripped build), the app still serves with that
    capability degraded rather than refusing to boot.
    """
    safety = None
    audit = None
    client = None
    settings = None

    try:
        from flinttrade_data.audit_logger import AuditLogger  # noqa: PLC0415

        audit = AuditLogger()
        audit.log_event("DESKTOP_START")
    except Exception as exc:  # pragma: no cover - defensive
        print(
            f"[desktop] audit logger unavailable ({_external_exception_context(exc)})",
            file=sys.stderr,
        )

    try:
        from .config import Settings  # noqa: PLC0415
        from .openalgo_client import OpenAlgoClient  # noqa: PLC0415

        settings = Settings.from_env()
        client = OpenAlgoClient(settings)
    except Exception as exc:  # pragma: no cover - defensive
        print(
            f"[desktop] OpenAlgo client unavailable ({_external_exception_context(exc)})",
            file=sys.stderr,
        )

    flask_app = None
    local_ai_attempted = False
    smart_order_started = False
    try:
        flask_app = create_flask_app(safety=safety, audit=audit, client=client)
        from .local_ai_routes import start_configured_local_ai_runtime  # noqa: PLC0415

        local_ai_attempted = True
        start_configured_local_ai_runtime(flask_app)
        safety = flask_app.config.get("SAFETY")
        if flask_app.config.get("SAFETY_CONFIG_READY") is True and safety is not None and client is not None:
            try:
                _bind_desktop_safety_runtime(flask_app, safety, client)
            except Exception as exc:  # noqa: BLE001 - native MTM writes must fail closed without this binding
                print(
                    f"[desktop] safety runtime unavailable ({_external_exception_context(exc)})",
                    file=sys.stderr,
                )
        from .smart_order_routes import start_smart_order_jobs  # noqa: PLC0415

        smart_order_started = start_smart_order_jobs()
        if not smart_order_started:
            raise RuntimeError("an earlier smart-order runtime still owns a worker")
        if settings is None:
            try:
                from .config import Settings  # noqa: PLC0415

                settings = Settings.from_env()
            except Exception as exc:  # pragma: no cover - defensive
                enabled = _tick_capture_enabled()
                _set_tick_capture_intent(flask_app, enabled)
                if enabled:
                    _record_tick_capture_failure(
                        flask_app,
                        _external_exception_context(exc),
                        "",
                    )
                return flask_app
        _configure_tick_capture(flask_app, settings)
        return flask_app
    except BaseException as startup_error:
        startup_error_context = _external_exception_context(startup_error)
        startup_signal = (
            startup_error
            if isinstance(startup_error, (KeyboardInterrupt, SystemExit))
            else None
        )
        recovery_owner = _DesktopStartupRollbackRecoveryOwner(
            flask_app,
            client=client,
            audit=audit,
            local_ai_attempted=local_ai_attempted,
            smart_order_started=smart_order_started,
            startup_error_context=startup_error_context,
        )
        rollback_complete = recovery_owner.attempt_rollback(
            deadline=time.monotonic() + _DESKTOP_SHUTDOWN_TIMEOUT
        )

    if not rollback_complete:
        raise DesktopBackendShutdownIncomplete(
            f"Desktop backend startup rollback failed ({startup_error_context})",
            recovery_owner=recovery_owner,
        ) from None
    if startup_signal is not None:
        raise startup_signal from None
    raise RuntimeError(
        f"Desktop backend startup failed ({startup_error_context})"
    ) from None


def _close_waitress_channels(server: Any, socket_map: dict[Any, Any]) -> None:
    """Close a complete or partially constructed Waitress listener set."""
    failures: list[BaseException] = []
    close_server = getattr(server, "close", None)
    if callable(close_server):
        try:
            close_server()
        except BaseException as exc:  # noqa: BLE001 - retry retains the same owner graph
            failures.append(exc)

    seen: set[int] = {id(server)} if server is not None else set()
    for channel in tuple(socket_map.values()):
        identity = id(channel)
        if identity in seen:
            continue
        seen.add(identity)
        close_channel = getattr(channel, "close", None)
        if not callable(close_channel):
            continue
        try:
            close_channel()
        except BaseException as exc:  # noqa: BLE001 - continue closing independent channels
            failures.append(exc)
    if failures:
        raise RuntimeError("Waitress listener cleanup was incomplete") from None


def _shutdown_waitress_dispatcher(dispatcher: Any, timeout: float) -> bool:
    """Stop Waitress workers and prove that no dispatcher thread remains."""
    shutdown = getattr(dispatcher, "shutdown", None)
    if not callable(shutdown):
        return False
    result = shutdown(timeout=timeout)
    threads = getattr(dispatcher, "threads", None)
    if threads is not None:
        return not bool(threads)
    return result is not False


class _DesktopShutdownRecoveryOwner:
    """Retain every desktop owner and unfinished cleanup attempt across retries."""

    def __init__(
        self,
        app: Any,
        *,
        server: Any = None,
        waitress_dispatcher: Any = None,
        waitress_socket_map: dict[Any, Any] | None = None,
        shutdown_signal: _ShutdownSignal | None = None,
        shutdown_callback: Callable[[], None] | None = None,
    ) -> None:
        self.app = app
        self.server = server
        self.waitress_dispatcher = waitress_dispatcher
        self.waitress_socket_map = (
            waitress_socket_map if waitress_socket_map is not None else {}
        )
        self.shutdown_signal = shutdown_signal
        self.shutdown_callback = shutdown_callback
        self._tracker = app.config.get("RUNTIME_REQUEST_TRACKER")
        self._capture_runtime = app.config.get(_CAPTURE_RUNTIME_CONFIG)
        self._deferred_capture_storage: Callable[..., Any] | None = None
        self._capture_deadline_aware = False
        self._workers: dict[str, _RetainedBoundedWorker] = {}
        self._completed: set[str] = set()
        self._attempt_lock = threading.Lock()
        self._lease_lock = threading.Lock()
        self._backend_lease: Any = None
        self._backend_lease_retained = False
        self._released = False

    def retain_backend_lease(self, lease: Any) -> None:
        """Attach and retain the exact lease that protects this recovery owner."""
        with self._lease_lock:
            if self._backend_lease is not None and self._backend_lease is not lease:
                raise RuntimeError("desktop recovery owner already has a different backend lease")
            self._backend_lease = lease
            if self._backend_lease_retained:
                return
            _retain_backend_recovery_owner(self, lease)
            self._backend_lease_retained = True

    def _complete_without_work(self, key: str) -> bool:
        self._completed.add(key)
        return True

    def _run_worker(
        self,
        key: str,
        operation: Callable[[], Any],
        *,
        deadline: float,
        failure_message: str,
        timeout_message: str,
        require_truthy: bool = False,
        start_when_expired: bool = False,
        require_live_deadline_for_success: bool = False,
        error_context: Callable[[BaseException], str] = _external_exception_context,
    ) -> bool:
        if key in self._completed:
            return True
        deadline_was_live = _remaining_shutdown_budget(deadline) > 0.0
        worker = self._workers.setdefault(
            key,
            _RetainedBoundedWorker(f"flinttrade-desktop-shutdown-{key}"),
        )
        try:
            result = worker.run(
                operation,
                deadline=deadline,
                start_when_expired=start_when_expired,
            )
        except TimeoutError:
            logger.warning(timeout_message)
            return False
        except BaseException as exc:  # noqa: BLE001 - exact owner remains retryable
            logger.warning(failure_message, error_context(exc))
            return False
        if require_live_deadline_for_success and (
            not deadline_was_live or _remaining_shutdown_budget(deadline) <= 0.0
        ):
            logger.warning(timeout_message)
            return False
        if require_truthy and not result:
            logger.warning(timeout_message)
            return False
        self._completed.add(key)
        return True

    def _run_native(
        self,
        key: str,
        operation: Callable[[float], Any],
        *,
        deadline: float,
        failure_message: str,
        timeout_message: str,
        require_truthy: bool = False,
        error_context: Callable[[BaseException], str] = _external_exception_context,
    ) -> bool:
        if key in self._completed:
            return True
        remaining = _remaining_shutdown_budget(deadline)
        if remaining <= 0.0:
            logger.warning(timeout_message)
            return False
        try:
            result = operation(remaining)
        except BaseException as exc:  # noqa: BLE001 - exact owner remains retryable
            logger.warning(failure_message, error_context(exc))
            return False
        if _remaining_shutdown_budget(deadline) <= 0.0:
            logger.warning(timeout_message)
            return False
        if require_truthy and not result:
            logger.warning(timeout_message)
            return False
        self._completed.add(key)
        return True

    def _runtime_error_context(self, error: BaseException) -> str:
        sanitise_error = getattr(self._capture_runtime, "sanitise_error", None)
        if callable(sanitise_error):
            try:
                return str(sanitise_error(error))
            except Exception:
                pass
        return _external_exception_context(error)

    def _shutdown(self, deadline: float) -> bool:
        app = self.app
        app.config["RUNTIME_ACCEPTING_REQUESTS"] = False

        def stop_local_ai() -> bool:
            from .local_ai_routes import shutdown_local_ai_runtime  # noqa: PLC0415

            return bool(
                shutdown_local_ai_runtime(
                    app,
                    timeout=_remaining_shutdown_budget(deadline),
                )
            )

        local_ai_stopped = self._run_worker(
            "local-ai",
            stop_local_ai,
            deadline=deadline,
            failure_message="Desktop managed local AI shutdown failed (%s)",
            timeout_message="Desktop managed local AI shutdown timed out",
            require_truthy=True,
            start_when_expired=True,
            require_live_deadline_for_success=True,
        )

        close_server = getattr(self.server, "close", None)
        server_closed = (
            self._run_worker(
                "http-server",
                lambda: _close_waitress_channels(
                    self.server,
                    self.waitress_socket_map,
                ),
                deadline=deadline,
                failure_message="Desktop HTTP server shutdown failed (%s)",
                timeout_message="Desktop HTTP server shutdown timed out",
            )
            if callable(close_server) or self.waitress_socket_map
            else self._complete_without_work("http-server")
        )

        uninstall = getattr(self.shutdown_signal, "uninstall", None)
        callback_uninstalled = (
            self._run_worker(
                "shutdown-callback",
                lambda: uninstall(self.shutdown_callback),
                deadline=deadline,
                failure_message="Desktop shutdown callback cleanup failed (%s)",
                timeout_message="Desktop shutdown callback cleanup timed out",
            )
            if callable(uninstall) and self.shutdown_callback is not None
            else self._complete_without_work("shutdown-callback")
        )

        def close_request_admission() -> None:
            self._tracker = _close_runtime_request_admission(app)

        admission_closed = self._run_worker(
            "request-admission",
            close_request_admission,
            deadline=deadline,
            failure_message="Desktop request admission shutdown failed (%s)",
            timeout_message="Desktop request admission shutdown timed out",
        )

        def stop_log_streams() -> None:
            from .log_stream import shutdown_log_streams  # noqa: PLC0415

            shutdown_log_streams(app)

        logs_stopped = self._run_worker(
            "log-streams",
            stop_log_streams,
            deadline=deadline,
            failure_message="Desktop log stream shutdown failed (%s)",
            timeout_message="Desktop log stream shutdown timed out",
        )

        event_results: list[bool] = []
        for label, config_key, step_key in (
            ("signal stream", "SIGNAL_STREAM_SHUTDOWN_EVENT", "signal-stream"),
            ("signal retraining", "ML_SIGNAL_RETRAIN_CANCEL_EVENT", "signal-retraining"),
        ):
            set_event = getattr(app.config.get(config_key), "set", None)
            if not callable(set_event):
                event_results.append(self._complete_without_work(step_key))
                continue
            event_results.append(
                self._run_worker(
                    step_key,
                    set_event,
                    deadline=deadline,
                    failure_message=f"Desktop {label} shutdown failed (%s)",
                    timeout_message=f"Desktop {label} shutdown timed out",
                )
            )

        def stop_smart_orders(timeout: float) -> bool:
            from .smart_order_routes import shutdown_smart_order_jobs  # noqa: PLC0415

            return bool(shutdown_smart_order_jobs(timeout=timeout))

        smart_orders_stopped = self._run_native(
            "smart-orders",
            stop_smart_orders,
            deadline=deadline,
            failure_message="Desktop smart-order shutdown failed (%s)",
            timeout_message="Desktop smart-order shutdown timed out",
            require_truthy=True,
        )

        def stop_agent(timeout: float) -> bool:
            from .agent_routes import shutdown_agent_runtime  # noqa: PLC0415

            return bool(shutdown_agent_runtime(app, timeout=timeout))

        agent_stopped = self._run_native(
            "agent-runtime",
            stop_agent,
            deadline=deadline,
            failure_message="Desktop autonomous agent shutdown failed (%s)",
            timeout_message="Desktop autonomous agent shutdown timed out",
            require_truthy=True,
        )

        def stop_strategies() -> None:
            from flinttrade_engine.strategy_routes import (  # noqa: PLC0415
                shutdown_strategy_runtime,
            )

            shutdown_strategy_runtime(app)

        strategies_stopped = self._run_worker(
            "uploaded-strategies",
            stop_strategies,
            deadline=deadline,
            failure_message="Desktop uploaded-strategy shutdown failed (%s)",
            timeout_message="Desktop uploaded-strategy shutdown timed out",
        )
        rotation_stopped = self._run_worker(
            "session-rotation",
            lambda: _shutdown_rotation_scheduler(app),
            deadline=deadline,
            failure_message="Desktop session rotation shutdown failed (%s)",
            timeout_message="Desktop session rotation shutdown timed out",
        )
        ditto_stopped = self._run_native(
            "ditto-runtime",
            lambda timeout: shutdown_ditto_runtime(app, timeout=timeout),
            deadline=deadline,
            failure_message="Desktop Ditto shutdown failed (%s)",
            timeout_message="Desktop Ditto shutdown timed out",
            require_truthy=True,
        )

        live_writers_stopped = all(
            (
                smart_orders_stopped,
                agent_stopped,
                strategies_stopped,
                rotation_stopped,
                ditto_stopped,
            )
        )
        router_retired = (
            self._run_worker(
                "broker-router",
                lambda: retire_broker_router_generation(app),
                deadline=deadline,
                failure_message="Desktop broker-router retirement failed (%s)",
                timeout_message="Desktop broker-router retirement timed out",
                require_truthy=True,
            )
            if live_writers_stopped
            else False
        )

        runtime = self._capture_runtime
        if runtime is None:
            capture_stopped = self._complete_without_work("tick-capture")
            capture_storage_known = self._complete_without_work("tick-storage")
        else:
            close_storage = getattr(runtime, "close_storage", None)
            self._capture_deadline_aware = (
                isinstance(runtime, _DesktopTickCaptureRuntime)
                or getattr(runtime, "_desktop_deadline_aware_shutdown", False) is True
            )
            if self._capture_deadline_aware:
                if callable(close_storage):
                    capture_stopped = self._run_native(
                        "tick-capture",
                        lambda timeout: runtime.stop(timeout=timeout, close_storage=False),
                        deadline=deadline,
                        failure_message="Desktop tick capture shutdown failed (%s)",
                        timeout_message="Desktop tick capture shutdown timed out",
                        error_context=self._runtime_error_context,
                    )
                    self._deferred_capture_storage = close_storage
                else:
                    capture_stopped = False
                    logger.warning("Desktop tick capture has no retryable storage owner")
            else:
                capture_stopped = self._run_worker(
                    "tick-capture",
                    runtime.stop,
                    deadline=deadline,
                    failure_message="Desktop tick capture shutdown failed (%s)",
                    timeout_message="Desktop tick capture shutdown timed out",
                    error_context=self._runtime_error_context,
                )
            capture_storage_known = not self._capture_deadline_aware or callable(
                self._deferred_capture_storage
            )

        owner_quiesced = all(
            (
                admission_closed,
                logs_stopped,
                *event_results,
                live_writers_stopped,
                router_retired,
                capture_stopped,
                capture_storage_known,
            )
        )

        wait_for_idle = getattr(self._tracker, "wait_for_idle", None)
        requests_drained = (
            self._run_native(
                "request-drain",
                lambda timeout: wait_for_idle(timeout),
                deadline=deadline,
                failure_message="Desktop active-request drain failed (%s)",
                timeout_message="Desktop shutdown timed out draining active requests",
                require_truthy=True,
            )
            if callable(wait_for_idle)
            else self._complete_without_work("request-drain")
        )

        dispatcher_shutdown = getattr(self.waitress_dispatcher, "shutdown", None)
        dispatcher_stopped = (
            self._run_native(
                "waitress-dispatcher",
                lambda timeout: _shutdown_waitress_dispatcher(
                    self.waitress_dispatcher,
                    timeout,
                ),
                deadline=deadline,
                failure_message="Desktop Waitress dispatcher shutdown failed (%s)",
                timeout_message="Desktop Waitress dispatcher shutdown timed out",
                require_truthy=True,
            )
            if callable(dispatcher_shutdown)
            else self._complete_without_work("waitress-dispatcher")
        )

        post_strategies_stopped = False
        post_ditto_stopped = False
        post_router_retired = False
        if requests_drained and dispatcher_stopped and owner_quiesced:
            post_strategies_stopped = self._run_worker(
                "post-drain-uploaded-strategies",
                stop_strategies,
                deadline=deadline,
                failure_message="Desktop post-drain uploaded-strategy shutdown failed (%s)",
                timeout_message="Desktop post-drain uploaded-strategy shutdown timed out",
            )
            post_ditto_stopped = self._run_native(
                "post-drain-ditto",
                lambda timeout: shutdown_ditto_runtime(app, timeout=timeout),
                deadline=deadline,
                failure_message="Desktop post-drain Ditto shutdown failed (%s)",
                timeout_message="Desktop post-drain Ditto shutdown timed out",
                require_truthy=True,
            )
            if post_strategies_stopped and post_ditto_stopped:
                post_router_retired = self._run_worker(
                    "post-drain-broker-router",
                    lambda: retire_broker_router_generation(app),
                    deadline=deadline,
                    failure_message="Desktop post-drain broker-router retirement failed (%s)",
                    timeout_message="Desktop post-drain broker-router retirement timed out",
                    require_truthy=True,
                )

        post_drain_quiesced = all(
            (post_strategies_stopped, post_ditto_stopped, post_router_retired)
        )
        if requests_drained and owner_quiesced and post_drain_quiesced:
            if self._deferred_capture_storage is None:
                capture_storage_closed = self._complete_without_work("tick-storage")
            elif self._capture_deadline_aware:
                capture_storage_closed = self._run_native(
                    "tick-storage",
                    lambda timeout: self._deferred_capture_storage(timeout=timeout),
                    deadline=deadline,
                    failure_message="Desktop tick storage shutdown failed (%s)",
                    timeout_message="Desktop tick storage shutdown timed out",
                    error_context=self._runtime_error_context,
                )
            else:
                capture_storage_closed = self._run_worker(
                    "tick-storage",
                    self._deferred_capture_storage,
                    deadline=deadline,
                    failure_message="Desktop tick storage shutdown failed (%s)",
                    timeout_message="Desktop tick storage shutdown timed out",
                    error_context=self._runtime_error_context,
                )
        else:
            capture_storage_closed = "tick-storage" in self._completed

        dependency_shutdown_ready = all(
            (
                requests_drained,
                dispatcher_stopped,
                owner_quiesced,
                post_drain_quiesced,
                capture_storage_closed,
            )
        )
        client_closed = False
        audit_closed = False
        if dependency_shutdown_ready:
            client = app.config.get("CLIENT")
            client_closed = (
                self._run_worker(
                    "openalgo-client",
                    lambda: client_close_sync(client),
                    deadline=deadline,
                    failure_message="Desktop OpenAlgo client shutdown failed (%s)",
                    timeout_message="Desktop OpenAlgo client shutdown timed out",
                )
                if client is not None
                else self._complete_without_work("openalgo-client")
            )

            audit = app.config.get("AUDIT")
            close_audit = getattr(audit, "close", None)
            audit_closed = (
                self._run_worker(
                    "audit",
                    close_audit,
                    deadline=deadline,
                    failure_message="Desktop audit shutdown failed (%s)",
                    timeout_message="Desktop audit shutdown timed out",
                )
                if callable(close_audit)
                else self._complete_without_work("audit")
            )

        return all(
            (
                server_closed,
                callback_uninstalled,
                dependency_shutdown_ready,
                local_ai_stopped,
                client_closed,
                audit_closed,
            )
        )

    def release(self, *, deadline: float) -> None:
        """Finish retained cleanup and release its backend lease by the deadline."""
        if self._released:
            return
        remaining = _remaining_shutdown_budget(deadline)
        acquired = (
            self._attempt_lock.acquire(blocking=False)
            if remaining <= 0.0
            else self._attempt_lock.acquire(timeout=remaining)
        )
        if not acquired:
            raise DesktopBackendShutdownIncomplete(
                "Desktop backend shutdown failed",
                recovery_owner=self,
            ) from None
        try:
            shutdown_complete = self._shutdown(deadline)
            if shutdown_complete:
                with self._lease_lock:
                    backend_lease = self._backend_lease
                lease_released = (
                    self._run_worker(
                        "backend-lease",
                        lambda: release_retained_backend_instance_lease(backend_lease),
                        deadline=deadline,
                        failure_message="Desktop backend lease release failed (%s)",
                        timeout_message="Desktop backend lease release timed out",
                    )
                    if backend_lease is not None
                    else self._complete_without_work("backend-lease")
                )
                if lease_released:
                    self._released = True
                    return
        finally:
            self._attempt_lock.release()
        raise DesktopBackendShutdownIncomplete(
            "Desktop backend shutdown failed",
            recovery_owner=self,
        ) from None


def _resolve_port(cli_port: int | None) -> int:
    """Resolve the listen port from the CLI arg, env, then the default.

    Args:
        cli_port: Value of ``--port`` (``None`` when the flag is absent).

    Returns:
        The port to bind. ``0`` means "let the OS choose a free port"; the
        actual bound port is reported in the ready handshake.
    """
    if cli_port is not None:
        return cli_port
    raw = os.environ.get("FLINTTRADE_BACKEND_PORT", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            print(
                f"[desktop] ignoring non-integer FLINTTRADE_BACKEND_PORT={raw!r}",
                file=sys.stderr,
            )
    return DEFAULT_PORT


def serve(
    port: int,
    *,
    ready_writer: Callable[[str], None] | None = None,
    shutdown_signal: _ShutdownSignal | None = None,
    shutdown_deadline: float | None = None,
    guardian_owned_lease: bool = False,
) -> None:
    """Serve while retaining exclusive ownership of the active workspace."""
    if guardian_owned_lease:
        _serve_owned(
            port,
            ready_writer=ready_writer,
            shutdown_signal=shutdown_signal,
            shutdown_deadline=shutdown_deadline,
        )
        return

    lease_failure_context: str | None = None
    try:
        backend_lease = acquire_backend_instance_lease()
    except BackendInstanceAlreadyRunning:
        # Electron reads this sentinel to distinguish "another backend owns
        # the workspace" from a failed source runtime. A lease conflict can be
        # a ``make start`` shell or an earlier desktop session.
        print("FLINTTRADE_BACKEND_BLOCKED reason=instance-lease", flush=True)
        raise
    except Exception as exc:  # noqa: BLE001 - desktop boundary exposes class only
        lease_failure_context = _external_exception_context(exc)
    if lease_failure_context is not None:
        raise RuntimeError(
            f"Desktop backend startup failed ({lease_failure_context})"
        ) from None

    serve_error: BaseException | None = None
    try:
        _serve_owned(
            port,
            ready_writer=ready_writer,
            shutdown_signal=shutdown_signal,
            shutdown_deadline=shutdown_deadline,
        )
    except DesktopBackendShutdownIncomplete as exc:
        recovery_owner = exc.recovery_owner
        retain_recovery = getattr(recovery_owner, "retain_backend_lease", None)
        if callable(retain_recovery):
            retain_recovery(backend_lease)
        else:
            retain_backend_instance_lease(backend_lease)
        raise
    except BaseException as exc:  # noqa: BLE001 - release lease before relaying
        serve_error = exc

    lease_release_context: str | None = None
    try:
        backend_lease.release()
    except Exception as exc:  # noqa: BLE001 - desktop boundary exposes class only
        lease_release_context = _external_exception_context(exc)
    if lease_release_context is not None:
        raise RuntimeError(
            f"Desktop backend lease release failed ({lease_release_context})"
        ) from None
    if serve_error is not None:
        raise serve_error from None


def _serve_owned(
    port: int,
    *,
    ready_writer: Callable[[str], None] | None = None,
    shutdown_signal: _ShutdownSignal | None = None,
    shutdown_deadline: float | None = None,
) -> None:
    """Bind the loopback socket and serve forever (blocking).

    Uses Waitress — the same production WSGI server the rest of FlintTrade
    runs on — created explicitly so the listening socket is open *before* the
    ready handshake is emitted. This removes the race where the Electron shell
    would otherwise poll a port that is not yet accepting connections.

    Args:
        port: Loopback port to bind. ``0`` asks the OS for a free port.
    """
    app = _build_app()
    server = None
    waitress_dispatcher = None
    waitress_socket_map: dict[Any, Any] = {}
    shutdown_callback: Callable[[], None] | None = None
    ready_announced = False
    failure_context: str | None = None
    failure_phase = "startup"
    try:
        from waitress.server import create_server  # noqa: PLC0415
        from waitress.task import ThreadedTaskDispatcher  # noqa: PLC0415

        waitress_dispatcher = ThreadedTaskDispatcher()
        server = create_server(
            app,
            map=waitress_socket_map,
            host="127.0.0.1",
            port=port,
            ident="FlintTrade",
            threads=8,
            _dispatcher=waitress_dispatcher,
        )
        waitress_dispatcher.set_thread_count(8)
        bound_port = server.effective_port

        # Rotation is a process-owned credential lifecycle service. A desktop
        # backend is not ready until its configured 08:05 jobs are armed.
        _start_rotation_scheduler(app, fail_closed=True)

        if shutdown_signal is not None:
            shutdown_callback = _thread.interrupt_main
            shutdown_signal.install(shutdown_callback)

        # Handshake — one line, flushed, so the parent can read it synchronously.
        ready_message = f"{READY_SENTINEL} port={bound_port}"
        if ready_writer is None:
            print(ready_message, flush=True)
        else:
            ready_writer(ready_message)
        ready_announced = True

        server.run()
    except (KeyboardInterrupt, SystemExit):  # pragma: no cover - signal path
        pass
    except BaseException as exc:  # noqa: BLE001 - expose class only after owned cleanup
        failure_context = _external_exception_context(exc)
        failure_phase = "runtime" if ready_announced else "startup"

    if shutdown_deadline is None:
        shutdown_deadline = time.monotonic() + _DESKTOP_SHUTDOWN_TIMEOUT
    recovery_owner = _DesktopShutdownRecoveryOwner(
        app,
        server=server,
        waitress_dispatcher=waitress_dispatcher,
        waitress_socket_map=waitress_socket_map,
        shutdown_signal=shutdown_signal,
        shutdown_callback=shutdown_callback,
    )
    shutdown_failure: DesktopBackendShutdownIncomplete | None = None
    try:
        recovery_owner.release(deadline=shutdown_deadline)
    except DesktopBackendShutdownIncomplete as exc:
        shutdown_failure = exc

    if shutdown_failure is not None:
        raise shutdown_failure from None
    if failure_context is not None:
        raise RuntimeError(
            f"Desktop backend {failure_phase} failed ({failure_context})"
        ) from None


def main(
    argv: list[str] | None = None,
    *,
    shutdown_signal: _ShutdownSignal | None = None,
    guardian_owned_lease: bool = False,
) -> None:
    """CLI entry point — parse args, init workspace, serve.

    Args:
        argv: Argument vector (defaults to ``sys.argv[1:]``).
    """
    parser = argparse.ArgumentParser(
        prog="flinttrade-desktop-backend",
        description="FlintTrade native-desktop backend (loopback API + bundled terminal).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Loopback port to bind (default: $FLINTTRADE_BACKEND_PORT or 5100; 0 = OS-chosen).",
    )
    args = parser.parse_args(argv)

    workspace_failure_context: str | None = None
    try:
        _ensure_workspace()
    except Exception as exc:  # noqa: BLE001 - desktop boundary exposes class only
        workspace_failure_context = _external_exception_context(exc)
    if workspace_failure_context is not None:
        raise RuntimeError(
            f"Desktop backend startup failed ({workspace_failure_context})"
        ) from None
    serve(
        _resolve_port(args.port),
        shutdown_signal=shutdown_signal,
        guardian_owned_lease=guardian_owned_lease,
    )


if __name__ == "__main__":
    main()
