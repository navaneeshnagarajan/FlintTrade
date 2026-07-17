"""FlintTrade application entry point — wires all packages together.

Includes a lightweight Flask API server (port 5100) for FlintTrade-specific
endpoints that are separate from the OpenAlgo API (port 5000).

Usage:
    python packages/core/core/src/app.py
    # or: make start
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# UTF-8 stdout/stderr reconfigure — must happen BEFORE any import that may
# emit to the console (structlog, Flask, etc.).  On Windows the default
# console encoding is cp1252, which crashes when log records contain emojis
# or ANSI colour codes.  We flip stdout/stderr to UTF-8 early; if the
# attribute is not available (Python <3.7 / non-stream stdout) we fall back
# silently so this never breaks startup.
# ---------------------------------------------------------------------------
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

import asyncio
import json
import logging
import os
import secrets
import signal
import threading
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextlib import nullcontext
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any, ContextManager

# Frozen-mode detection — when packaged by PyInstaller for the native desktop
# app, every ``flinttrade_*`` package is collected into the bundle, so the
# source-tree ``sys.path`` wiring below is both unnecessary and wrong (the
# ``packages/<group>/<pkg>/src`` directories do not exist inside the bundle).
# ``sys.frozen`` is set by PyInstaller; ``sys._MEIPASS`` points at the unpacked
# bundle root.  See ``flinttrade_core.desktop`` for the desktop entry point.
_FROZEN = bool(getattr(sys, "frozen", False))
_BUNDLE_DIR = getattr(sys, "_MEIPASS", None)

# Ensure repo root is on sys.path for cross-package imports (source runs only).
_REPO_ROOT = str(Path(__file__).resolve().parents[5]) if not _FROZEN else (_BUNDLE_DIR or "")
if not _FROZEN:
    if _REPO_ROOT not in sys.path:
        sys.path.insert(0, _REPO_ROOT)

    # Add sibling package ``src`` directories after the stdlib/site paths.  Keeping
    # these as appends avoids local modules such as ``statistics.py`` shadowing
    # Python's standard library while still supporting non-installed source runs.
    for _package_src in [
        "packages/core/data/src",
        "packages/core/historical/src",
        "packages/core/indicators/src",
        "packages/core/ticks/python",
        "packages/services/engine/src",
        "packages/services/screener/src",
        "packages/services/backtest/src",
        "packages/services/ai/src",
        "packages/services/ditto/src",
        "packages/services/automation/src",
        "packages/services/journal/src",
        "packages/integrations/gateway/src",
        "packages/integrations/webhooks/src",
    ]:
        _src_path = str(Path(_REPO_ROOT) / _package_src)
        if _src_path not in sys.path:
            sys.path.append(_src_path)

import hmac  # noqa: E402
import time  # noqa: E402

import structlog  # noqa: E402
from flask import Flask, g as _flask_g, jsonify, request  # noqa: E402
from flask_cors import CORS  # noqa: E402
from flask_limiter import Limiter  # noqa: E402
from flask_limiter.util import get_remote_address  # noqa: E402
import sentry_sdk  # noqa: E402
from sentry_sdk.integrations.flask import FlaskIntegration  # noqa: E402

from .backend_instance import (  # noqa: E402
    acquire_backend_instance_lease,
    release_retained_backend_instance_lease,
    retain_backend_instance_lease,
)
from .config import DEFAULT_OPENALGO_PORT, DEFAULT_OPENALGO_WS_PORT, Settings, openalgo_ws_base_url  # noqa: E402
from .csp import (  # noqa: E402
    build_csp_header as _build_csp_header,
    csp_report_bp as _csp_report_bp,
    generate_nonce as _generate_csp_nonce,
    inject_csp_nonce as _inject_csp_nonce,
)
from .openalgo_client import OpenAlgoClient  # noqa: E402
from .secure_file import write_secret_text as _write_secret_text  # noqa: E402
from .version import APP_VERSION_TAG  # noqa: E402
from .workspace import workspace_dir as _workspace_dir  # noqa: E402
from flinttrade_data.audit_logger import AuditLogger  # noqa: E402
# engine imports are deferred into FlintTradeApp.__init__() to break the
# core↔engine circular import.  See PLC0415 comments throughout this file.
# Heavy optional modules are imported lazily inside FlintTradeApp.__init__()
# to avoid a 2-5 s startup penalty when ChromaDB / LLM / Telegram deps load.
# CronManager, TelegramBot, LLMClient, LLMConfig, RAGPipeline

# Ensure the gateway src directory is on sys.path so bare gateway imports resolve.
_GATEWAY_SRC = str(Path(_REPO_ROOT) / "packages" / "integrations" / "gateway" / "src")
if _GATEWAY_SRC not in sys.path:
    sys.path.append(_GATEWAY_SRC)

from flinttrade_gateway.registry import BrokerRegistry  # noqa: E402
from flinttrade_gateway.credentials import CredentialStore  # noqa: E402
from flinttrade_gateway.auth import gateway_bp  # noqa: E402
from flinttrade_gateway.contracts import ContractManager  # noqa: E402

logger = logging.getLogger("flinttrade")

DEFAULT_BACKEND_PORT = 5100


def _resolve_backend_port() -> int:
    """Resolve the standalone backend loopback port from env, then default.

    ``make start`` and ``make dev`` expose ``FLINTTRADE_BACKEND_PORT`` to let a
    contributor run FlintTrade beside another local backend. The serve path must
    honour the same contract the Makefile prints.
    """
    raw = os.environ.get("FLINTTRADE_BACKEND_PORT", "").strip()
    if not raw:
        return DEFAULT_BACKEND_PORT
    try:
        port = int(raw)
    except ValueError:
        logger.warning("Ignoring non-integer FLINTTRADE_BACKEND_PORT=%r", raw)
        return DEFAULT_BACKEND_PORT
    # Out-of-range ports would make waitress raise inside the daemon serve
    # thread AFTER the "started on" log line — the app keeps running with no
    # API server and no visible error. (Port 0 is desktop.py's ephemeral-port
    # contract; the standalone serve path has no way to discover the real port.)
    if not 1 <= port <= 65535:
        logger.warning("Ignoring out-of-range FLINTTRADE_BACKEND_PORT=%r", raw)
        return DEFAULT_BACKEND_PORT
    return port


def _resolve_backend_host() -> str:
    """Resolve the standalone backend bind host from env, then loopback.

    ``FLINTTRADE_BACKEND_HOST`` lets the operator expose the web surface on a
    routable interface (for example a Tailscale tailnet IP) so a browser on
    another machine is a full client. The desktop sidecar serve path
    (``flinttrade_core.desktop``) does not read this and stays loopback-only.
    """
    return os.environ.get("FLINTTRADE_BACKEND_HOST", "").strip() or "127.0.0.1"


class _RuntimeRequestAdmission:
    """One idempotently releasable request admitted by the runtime tracker."""

    def __init__(self, tracker: _RuntimeRequestTracker) -> None:
        self._tracker = tracker
        self._lock = threading.Lock()
        self._released = False

    def release(self) -> None:
        """Release this admission exactly once, including response-close races."""
        with self._lock:
            if self._released:
                return
            self._released = True
        self._tracker._release()  # noqa: SLF001 - admission is the tracker's token


class _RuntimeRequestTracker:
    """Serialise shutdown admission with draining of already-running requests."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._accepting = True
        self._active = 0

    def try_admit(self) -> _RuntimeRequestAdmission | None:
        """Admit one request unless shutdown has closed the admission gate."""
        with self._condition:
            if not self._accepting:
                return None
            self._active += 1
        return _RuntimeRequestAdmission(self)

    def stop_admitting(self) -> None:
        """Atomically close admission before shutdown begins waiting."""
        with self._condition:
            self._accepting = False

    def wait_for_idle(self, timeout: float) -> bool:
        """Wait up to ``timeout`` seconds for every admitted request to leave."""
        deadline = time.monotonic() + max(0.0, timeout)
        with self._condition:
            while self._active:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(remaining)
            return True

    def _release(self) -> None:
        with self._condition:
            if self._active <= 0:  # pragma: no cover - defensive token invariant
                return
            self._active -= 1
            if self._active == 0:
                self._condition.notify_all()


def _install_runtime_request_tracking(app: Flask) -> _RuntimeRequestTracker:
    """Install request admission/draining hooks and return their shared tracker."""
    tracker = _RuntimeRequestTracker()
    app.config["RUNTIME_ACCEPTING_REQUESTS"] = True
    app.config["RUNTIME_REQUEST_TRACKER"] = tracker

    @app.before_request
    def _require_running_runtime() -> Any:
        """Reject every request before it can touch dependencies being closed."""
        admission = tracker.try_admit() if app.config.get("RUNTIME_ACCEPTING_REQUESTS", True) else None
        if admission is not None:
            _flask_g._runtime_request_admission = admission
            return None
        response = jsonify(
            {
                "status": "error",
                "message": "Application is shutting down",
            }
        )
        response.status_code = 503
        response.headers["Retry-After"] = "1"
        return response

    @app.after_request
    def _release_completed_runtime_request(response: Any) -> Any:
        admission = getattr(_flask_g, "_runtime_request_admission", None)
        if admission is None:
            return response
        if response.is_streamed:
            # SSE/file iterators may outlive Flask's request dispatch. Their
            # dependencies remain owned until the WSGI server closes the body.
            response.call_on_close(admission.release)
            _flask_g._runtime_request_release_deferred = True
        else:
            admission.release()
        return response

    @app.teardown_request
    def _release_failed_runtime_request(_error: BaseException | None) -> None:
        admission = getattr(_flask_g, "_runtime_request_admission", None)
        if admission is not None and not getattr(_flask_g, "_runtime_request_release_deferred", False):
            admission.release()

    return tracker


def _close_runtime_request_admission(app: Flask) -> Any:
    """Close HTTP admission without waiting for routing-generation ownership."""
    tracker = app.config.get("RUNTIME_REQUEST_TRACKER")
    stop_admitting = getattr(tracker, "stop_admitting", None)
    app.config["RUNTIME_ACCEPTING_REQUESTS"] = False
    try:
        if callable(stop_admitting):
            stop_admitting()
    finally:
        # The Flask flag is the outer fail-closed barrier. Tracker diagnostics
        # must never reopen admission or prevent later teardown attempts.
        app.config["RUNTIME_ACCEPTING_REQUESTS"] = False
    return tracker


def _rag_auto_index_enabled() -> bool:
    """Return whether startup should auto-index docs into the RAG store."""
    raw = os.environ.get("FLINTTRADE_RAG_AUTO_INDEX", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _rag_runtime_enabled() -> bool:
    """Return whether the startup path should construct the RAG runtime."""
    raw = os.environ.get("FLINTTRADE_RAG_ENABLED")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return _rag_auto_index_enabled()


def _tick_capture_enabled() -> bool:
    """Return whether the startup path should launch live tick capture.

    The environment setting is authoritative when present, including explicit
    false. Otherwise, read the UI-owned workspace setting. Capture stays off
    by default because the recorder opens an OpenAlgo WebSocket on boot.
    """
    raw = os.environ.get("FLINTTRADE_TICK_CAPTURE")
    if raw is None:
        raw = _read_workspace_section("data", "tick_capture", "enabled")
    if isinstance(raw, bool):
        return raw
    return str(raw or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


_TICK_CAPTURE_LIFECYCLE_LOCK = "TICK_CAPTURE_LIFECYCLE_LOCK"


def _tick_capture_lifecycle_lock(flask_app: Flask) -> threading.RLock:
    """Return the per-app lock serialising recorder lifecycle transitions."""
    lock = flask_app.config.get(_TICK_CAPTURE_LIFECYCLE_LOCK)
    if lock is None:
        lock = threading.RLock()
        lock = flask_app.config.setdefault(_TICK_CAPTURE_LIFECYCLE_LOCK, lock)
    return lock


def _set_tick_capture_intent(flask_app: Flask, enabled: bool) -> None:
    """Expose capture intent before the API server accepts status requests."""
    with _tick_capture_lifecycle_lock(flask_app):
        flask_app.config["TICK_CAPTURE_ENABLED"] = enabled
        flask_app.config["TICK_CAPTURE_ERROR"] = ""


def _sanitise_tick_capture_error(error: Any, api_key: str) -> str:
    """Return a single-line startup diagnostic without the OpenAlgo API key."""
    diagnostic = str(error).strip() or type(error).__name__
    if api_key:
        diagnostic = diagnostic.replace(api_key, "[redacted]")
    return " ".join(diagnostic.splitlines())


def _record_tick_capture_failure(flask_app: Flask, error: Any, api_key: str) -> None:
    """Persist and log a redacted tick-capture startup failure."""
    diagnostic = _sanitise_tick_capture_error(error, api_key)
    with _tick_capture_lifecycle_lock(flask_app):
        flask_app.config["TICK_CAPTURE_ERROR"] = diagnostic
    logger.warning("Tick capture failed to start (%s); not recording ticks", diagnostic)


def _close_tick_storage(storage: Any, storage_lock: Any | None = None) -> None:
    """Close tick storage after serialising with any in-flight maintenance."""
    if storage is None:
        return
    if storage_lock is None:
        storage.close()
        return
    with storage_lock:
        storage.close()


def _pending_tick_count(recorder: Any) -> int | None:
    """Return an exact retained-buffer count, or ``None`` when unknowable."""
    missing = object()
    raw = getattr(recorder, "pending_tick_count", missing)
    if raw is missing or isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        return None
    return raw


@dataclass(frozen=True, slots=True)
class _LifecycleDeadline:
    """One absolute monotonic deadline shared by a lifecycle attempt."""

    expires_at: float

    @classmethod
    def after(cls, timeout: float) -> _LifecycleDeadline:
        return cls(time.monotonic() + max(0.0, timeout))

    def remaining(self, maximum: float | None = None) -> float:
        remaining = max(0.0, self.expires_at - time.monotonic())
        if maximum is None:
            return remaining
        return min(remaining, max(0.0, maximum))


class _RetainedSyncOwnerWorker:
    """One exact synchronous cleanup operation retained across timeouts."""

    def __init__(self, operation: Callable[[], Any], *, name: str) -> None:
        self._operation = operation
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._result: Any = None
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)

    def _run(self) -> None:
        try:
            result = self._operation()
        except BaseException as exc:  # noqa: BLE001 - reported by lifecycle owner
            with self._lock:
                self._error = exc
        else:
            with self._lock:
                self._result = result
        finally:
            self._done.set()

    def start(self) -> None:
        """Start this cleanup operation exactly once."""
        self._thread.start()

    async def wait(self, deadline: _LifecycleDeadline) -> bool:
        """Wait only within the shared deadline without spawning waiter threads."""
        while not self._done.is_set():
            remaining = deadline.remaining()
            if remaining <= 0.0:
                return False
            await asyncio.sleep(min(remaining, 0.005))
        return True

    def outcome(self) -> tuple[Any, BaseException | None]:
        """Return the completed operation result and error."""
        if not self._done.is_set():
            raise RuntimeError("cleanup operation is still running")
        with self._lock:
            return self._result, self._error


async def _join_cancelled_task(
    task: Any,
    deadline: _LifecycleDeadline,
) -> tuple[bool, BaseException | None]:
    """Cancel and join one task without cancelling it again on timeout."""
    task.cancel()
    if isinstance(task, asyncio.Future):
        waiter = task
    else:
        async def await_owned() -> None:
            await task

        waiter = asyncio.create_task(await_owned())
    done, _ = await asyncio.wait({waiter}, timeout=deadline.remaining())
    if waiter not in done:
        return False, None
    try:
        await waiter
    except asyncio.CancelledError:
        return True, None
    except BaseException as exc:  # noqa: BLE001 - completed owner errors remain observable
        return True, exc
    return True, None


class _BoundedTickStorageCloseWorker:
    """Daemon-owned checkpoint/close attempt with bounded external waits."""

    def __init__(
        self,
        operation: Callable[[], None],
        *,
        on_success: Callable[[], None] | None = None,
        name: str = "flinttrade-tick-storage-close",
    ) -> None:
        self._operation = operation
        self._on_success = on_success
        self._name = name
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._done = threading.Event()
        self._result: bool | None = None

    def start(self) -> bool:
        """Start one attempt unless one is active or has already succeeded."""
        with self._lock:
            if self._result is True:
                return False
            if self._thread is not None and self._thread.is_alive():
                return False
            self._done.clear()
            self._result = None

            def run() -> None:
                result = False
                try:
                    self._operation()
                    if self._on_success is not None:
                        self._on_success()
                    result = True
                except BaseException:  # noqa: BLE001 - surfaced as a fail-closed result
                    result = False
                finally:
                    with self._lock:
                        self._result = result
                    self._done.set()

            self._thread = threading.Thread(target=run, name=self._name, daemon=True)
            self._thread.start()
            return True

    def wait(self, timeout: float) -> bool | None:
        """Return success/failure, or ``None`` when the bounded wait expires."""
        if not self._done.wait(max(0.0, timeout)):
            return None
        with self._lock:
            return self._result


def _build_tick_storage_close_worker(
    recorder: Any,
    storage: Any,
    storage_lock: Any | None,
    checkpoint_owner: Any | None,
    *,
    on_success: Callable[[], None] | None = None,
) -> _BoundedTickStorageCloseWorker:
    """Own an exact, retryable final checkpoint and storage close operation."""

    def close_owned_storage() -> None:
        pending_tick_count = _pending_tick_count(recorder)
        if pending_tick_count is None:
            raise RuntimeError("tick recorder pending buffer is unknown")
        if pending_tick_count > 0:
            flush_pending = getattr(recorder, "flush_pending", None)
            if not callable(flush_pending):
                raise RuntimeError("tick recorder cannot flush its retained buffer")
            flush_pending()
            pending_tick_count = _pending_tick_count(recorder)
        if pending_tick_count != 0:
            raise RuntimeError("tick recorder did not prove an empty pending buffer")
        if checkpoint_owner is not None:
            checkpoint_owner.persist(force=True)
        _close_tick_storage(storage, storage_lock)

    return _BoundedTickStorageCloseWorker(
        close_owned_storage,
        on_success=on_success,
    )


async def _rollback_tick_capture_startup(
    owner: Any,
    flask_app: Flask,
    *,
    recorder: Any | None,
    recorder_task: asyncio.Task[Any] | None,
    storage: Any | None,
    storage_lock: Any | None,
    checkpoint_owner: Any | None,
    close_worker: _BoundedTickStorageCloseWorker | None,
    startup_error: BaseException,
    api_key: str,
    deadline: _LifecycleDeadline | None = None,
) -> bool:
    """Fail capture closed while retaining any storage that still owns ticks."""
    deadline = deadline or _LifecycleDeadline.after(3.0)
    sanitise_error = getattr(recorder, "sanitise_error", None)

    def sanitise(value: Any) -> str:
        try:
            if callable(sanitise_error):
                value = sanitise_error(value)
        except Exception:
            pass
        return _sanitise_tick_capture_error(value, api_key)

    diagnostic = sanitise(startup_error)
    if recorder is not None:
        try:
            recorder.stop()
        except Exception as exc:  # noqa: BLE001 - ownership is retained below
            logger.warning("Tick recorder rollback stop failed (%s)", sanitise(exc))
    task_joined = True
    if recorder_task is not None:
        task_joined, task_error = await _join_cancelled_task(recorder_task, deadline)
        if task_joined and task_error is not None:
            logger.warning("Tick recorder rollback failed (%s)", sanitise(task_error))

    resolved_close_worker = close_worker
    worker_holder: dict[str, _BoundedTickStorageCloseWorker] = {}

    def clear_closed_storage() -> None:
        with _tick_capture_lifecycle_lock(flask_app):
            if owner._tick_storage is storage:
                owner._tick_recorder = None
                owner._tick_recorder_task = None
                owner._tick_storage = None
                owner._tick_storage_lock = None
                owner._orderflow_checkpoint_owner = None
                if owner._tick_storage_close_worker is worker_holder.get("worker"):
                    owner._tick_storage_close_worker = None

    if storage is not None and resolved_close_worker is None:
        if recorder is None:
            resolved_close_worker = _BoundedTickStorageCloseWorker(
                lambda: _close_tick_storage(storage, storage_lock),
                on_success=clear_closed_storage,
            )
        else:
            resolved_close_worker = _build_tick_storage_close_worker(
                recorder,
                storage,
                storage_lock,
                checkpoint_owner,
                on_success=clear_closed_storage,
            )
    if resolved_close_worker is not None:
        worker_holder["worker"] = resolved_close_worker

    with _tick_capture_lifecycle_lock(flask_app):
        owner.cron.tick_storage = None
        owner.cron.tick_storage_lock = None
        owner._tick_recorder_task = None if task_joined else recorder_task
        if storage is None:
            owner._tick_recorder = None
            owner._tick_storage = None
            owner._tick_storage_lock = None
            owner._orderflow_checkpoint_owner = None
            owner._tick_storage_close_worker = None
        else:
            owner._tick_recorder = recorder
            owner._tick_storage = storage
            owner._tick_storage_lock = storage_lock
            owner._orderflow_checkpoint_owner = checkpoint_owner
            owner._tick_storage_close_worker = resolved_close_worker
        for key in (
            "TICK_RECORDER",
            "TICK_STORAGE",
            "TICK_STORAGE_LOCK",
            "ORDERFLOW_AGGREGATOR",
        ):
            flask_app.config.pop(key, None)
        flask_app.config["TICK_CAPTURE_ERROR"] = diagnostic

    close_complete = storage is None
    if storage is not None and task_joined and resolved_close_worker is not None:
        resolved_close_worker.start()
        close_result = await asyncio.to_thread(
            resolved_close_worker.wait,
            deadline.remaining(),
        )
        close_complete = close_result is True
    logger.warning("Tick capture failed to start (%s); not recording ticks", diagnostic)
    return task_joined and close_complete


_ORDERFLOW_CHECKPOINT_INTERVAL_SECONDS = 30.0
_UNBOUND_ORDERFLOW_CHECKPOINT = object()


@dataclass(frozen=True, slots=True)
class _PendingOrderFlowCheckpointPublication:
    """Exact publication retained across an ambiguous post-rename failure."""

    state: Mapping[str, Any]
    cursor: Any
    handoff_from_store_id: str | None
    expected_generation: int


class _OrderFlowCheckpointOwner:
    """Publish cursor-bound order-flow state at recorder consistency barriers."""

    def __init__(
        self,
        storage: Any,
        orderflow: Any,
        *,
        workspace_dir: Path,
        storage_lock: Any | None = None,
        interval_seconds: float = _ORDERFLOW_CHECKPOINT_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.storage = storage
        self.orderflow = orderflow
        self.workspace_dir = workspace_dir
        self.storage_lock = storage_lock
        self.interval_seconds = max(0.0, float(interval_seconds))
        self.clock = clock
        self._last_persisted_at: float | None = None
        self._publication_owner_epoch = str(uuid.uuid4())
        self._publication_generation: int | None = None
        self._published_store_id: str | None = None
        self._handoff_from_store_id: str | None = None
        self._pending_lineage_handoff: Any | None = None
        self._pending_lineage_recovery: Any | None = None
        self._pending_checkpoint_publication: _PendingOrderFlowCheckpointPublication | None = None
        self._lineage_evidence_obligation: Any | None = None

    def _initialise_publication_fence(
        self,
        cursor: Any,
        *,
        checkpoint: Any = _UNBOUND_ORDERFLOW_CHECKPOINT,
    ) -> Any | None:
        """Bind this owner to the durable checkpoint and storage lineage."""
        from flinttrade_data.orderflow_checkpoint import (  # noqa: PLC0415
            load_orderflow_checkpoint,
        )
        from flinttrade_data.storage import (  # noqa: PLC0415
            TickReplayCursor,
            TickReplayLineageHandoff,
            TickReplayLineageRecovery,
        )

        if checkpoint is _UNBOUND_ORDERFLOW_CHECKPOINT:
            checkpoint = load_orderflow_checkpoint(self.workspace_dir)
        get_handoff = getattr(
            self.storage,
            "get_tick_replay_lineage_handoff",
            None,
        )
        handoff = get_handoff() if callable(get_handoff) else None
        if handoff is not None and not isinstance(
            handoff,
            TickReplayLineageHandoff,
        ):
            raise RuntimeError("tick storage lineage handoff is invalid")
        get_recovery = getattr(
            self.storage,
            "get_tick_replay_lineage_recovery",
            None,
        )
        recovery = get_recovery() if callable(get_recovery) else None
        if recovery is not None and not isinstance(
            recovery,
            TickReplayLineageRecovery,
        ):
            raise RuntimeError("tick storage lineage recovery is invalid")
        if recovery is not None and recovery.to_store_id != cursor.store_id:
            raise RuntimeError("tick storage lineage recovery targets a different store")

        handoff_from_store_id: str | None = None
        lineage_evidence_obligation = None
        checkpoint_replay_cursor = None
        if checkpoint is not None:
            if checkpoint.cursor.store_id == cursor.store_id:
                validate_cursor = getattr(
                    self.storage,
                    "validate_tick_replay_cursor",
                    None,
                )
                if not callable(validate_cursor):
                    raise RuntimeError("tick storage cursor validation is unavailable")
                validate_cursor(checkpoint.cursor)
                checkpoint_replay_cursor = checkpoint.cursor
            elif (
                handoff is not None
                and checkpoint.cursor.store_id in handoff.source_store_ids
                and handoff.to_store_id == cursor.store_id
            ):
                handoff_from_store_id = checkpoint.cursor.store_id
                checkpoint_replay_cursor = TickReplayCursor(
                    cursor.store_id,
                    checkpoint.cursor.ingest_seq,
                )
                self.storage.validate_tick_replay_cursor(checkpoint_replay_cursor)
            elif recovery is not None and (
                recovery.reason != "pristine_store_replacement" or cursor.ingest_seq == 0
            ):
                handoff_from_store_id = checkpoint.cursor.store_id
                checkpoint_replay_cursor = TickReplayCursor(
                    cursor.store_id,
                    0 if recovery.reason == "pristine_store_replacement" else checkpoint.cursor.ingest_seq,
                )
                self.storage.validate_tick_replay_cursor(checkpoint_replay_cursor)
            else:
                validate_cursor = getattr(
                    self.storage,
                    "validate_tick_replay_cursor",
                    None,
                )
                if not callable(validate_cursor):
                    raise RuntimeError("tick storage cursor validation is unavailable")
                validate_cursor(checkpoint.cursor)
                raise RuntimeError("checkpoint lineage differs from tick storage")

            if (
                checkpoint.cursor.store_id == cursor.store_id
                and checkpoint.lineage_handoff_evidence is not None
                and (handoff is not None or recovery is not None)
            ):
                if handoff is not None:
                    matching_source = next(
                        (
                            source_store_id
                            for source_store_id in handoff.source_store_ids
                            if checkpoint.has_lineage_handoff_from(source_store_id)
                        ),
                        None,
                    )
                    if matching_source is None:
                        raise RuntimeError("checkpoint lineage evidence does not match tick storage handoff")
                    handoff_from_store_id = matching_source
                lineage_evidence_obligation = checkpoint

        self._publication_generation = 0 if checkpoint is None else checkpoint.publication_generation
        self._published_store_id = cursor.store_id
        self._handoff_from_store_id = handoff_from_store_id
        self._pending_lineage_handoff = handoff
        self._pending_lineage_recovery = recovery
        self._lineage_evidence_obligation = lineage_evidence_obligation
        return checkpoint_replay_cursor

    def _has_pending_lineage_acknowledgement(self) -> bool:
        return self._pending_lineage_handoff is not None or self._pending_lineage_recovery is not None

    def _bind_lineage_evidence_obligation(self, publication: _PendingOrderFlowCheckpointPublication) -> None:
        """Bind acknowledgement to the exact evidence-bearing canonical publication."""
        from flinttrade_data.orderflow_checkpoint import load_orderflow_checkpoint  # noqa: PLC0415

        checkpoint = load_orderflow_checkpoint(self.workspace_dir)
        if (
            checkpoint is None
            or checkpoint.publication_generation != publication.expected_generation + 1
            or checkpoint.publication_owner_epoch != self._publication_owner_epoch
            or checkpoint.cursor != publication.cursor
            or checkpoint.lineage_handoff_evidence is None
            or (
                publication.handoff_from_store_id is not None
                and not checkpoint.has_lineage_handoff_from(publication.handoff_from_store_id)
            )
        ):
            raise RuntimeError("order-flow checkpoint lineage evidence obligation is unavailable")
        self._lineage_evidence_obligation = checkpoint

    def bind_for_restore(self, checkpoint: Any | None) -> Any | None:
        """Bind publication fencing to the exact canonical used for restore."""
        cursor = self.storage.get_tick_replay_cursor()
        return self._initialise_publication_fence(cursor, checkpoint=checkpoint)

    def persist_locked(self, *, force: bool = False) -> bool:
        """Persist while the caller owns the storage/ingestion barrier."""
        now = self.clock()
        from flinttrade_data.orderflow_checkpoint import (  # noqa: PLC0415
            OrderFlowCheckpointDurabilityUncertainError,
            store_orderflow_checkpoint,
        )

        pending = self._pending_checkpoint_publication
        if pending is not None:
            store_orderflow_checkpoint(
                self.workspace_dir,
                pending.state,
                pending.cursor,
                handoff_from_store_id=pending.handoff_from_store_id,
                owner_epoch=self._publication_owner_epoch,
                expected_generation=pending.expected_generation,
            )
            self._publication_generation = pending.expected_generation + 1
            self._published_store_id = pending.cursor.store_id
            if self._has_pending_lineage_acknowledgement():
                if pending.handoff_from_store_id is not None:
                    self._bind_lineage_evidence_obligation(pending)
                self._complete_lineage_handoff()
            self._pending_checkpoint_publication = None
            self._last_persisted_at = now
            return True
        cursor = self.storage.get_tick_replay_cursor()
        if self._publication_generation is None or self._published_store_id != cursor.store_id:
            self._initialise_publication_fence(cursor)
        if self._lineage_evidence_obligation is not None:
            self._complete_lineage_handoff()
        if (
            not force
            and self._last_persisted_at is not None
            and 0 <= now - self._last_persisted_at < self.interval_seconds
        ):
            return False

        if self._publication_generation is None:
            raise RuntimeError("order-flow checkpoint publication fence is unavailable")
        state = self.orderflow.export_state()
        publication = _PendingOrderFlowCheckpointPublication(
            state=state,
            cursor=cursor,
            handoff_from_store_id=self._handoff_from_store_id,
            expected_generation=self._publication_generation,
        )
        try:
            store_orderflow_checkpoint(
                self.workspace_dir,
                publication.state,
                publication.cursor,
                handoff_from_store_id=publication.handoff_from_store_id,
                owner_epoch=self._publication_owner_epoch,
                expected_generation=publication.expected_generation,
            )
        except OrderFlowCheckpointDurabilityUncertainError:
            self._pending_checkpoint_publication = publication
            raise
        self._publication_generation = publication.expected_generation + 1
        self._published_store_id = cursor.store_id
        if self._has_pending_lineage_acknowledgement():
            self._pending_checkpoint_publication = publication
            if publication.handoff_from_store_id is not None:
                self._bind_lineage_evidence_obligation(publication)
            self._complete_lineage_handoff()
            self._pending_checkpoint_publication = None
        self._last_persisted_at = now
        return True

    def _complete_lineage_handoff(self) -> None:
        """Acknowledge storage lineage only after canonical publication."""
        from flinttrade_data.orderflow_checkpoint import (  # noqa: PLC0415
            ensure_orderflow_checkpoint_lineage_evidence,
        )

        if not self._has_pending_lineage_acknowledgement():
            self._handoff_from_store_id = None
            self._lineage_evidence_obligation = None
            return
        obligation = self._lineage_evidence_obligation
        if obligation is not None:
            ensure_orderflow_checkpoint_lineage_evidence(self.workspace_dir, obligation)
        elif self._handoff_from_store_id is not None:
            raise RuntimeError("order-flow checkpoint lineage evidence obligation is unavailable")
        if self._pending_lineage_handoff is not None:
            acknowledge_handoff = getattr(
                self.storage,
                "acknowledge_tick_replay_lineage_handoff",
                None,
            )
            if not callable(acknowledge_handoff):
                raise RuntimeError("tick storage lineage acknowledgement is unavailable")
            acknowledge_handoff(self._pending_lineage_handoff)
            self._pending_lineage_handoff = None
        if self._pending_lineage_recovery is not None:
            acknowledge_recovery = getattr(
                self.storage,
                "acknowledge_tick_replay_lineage_recovery",
                None,
            )
            if not callable(acknowledge_recovery):
                raise RuntimeError("tick storage lineage recovery acknowledgement is unavailable")
            acknowledge_recovery(self._pending_lineage_recovery)
            self._pending_lineage_recovery = None
        self._handoff_from_store_id = None
        self._lineage_evidence_obligation = None

    def persist(self, *, force: bool = False) -> bool:
        """Acquire the storage lock and publish one checkpoint."""
        lock_context = nullcontext() if self.storage_lock is None else self.storage_lock
        with lock_context:
            return self.persist_locked(force=force)


def _checkpoint_identities(state: Mapping[str, Any]) -> set[tuple[str, str]]:
    """Return canonical identities from a validated checkpoint payload."""
    rows = state.get("identities")
    if not isinstance(rows, list):
        return set()
    return {
        (
            str(row.get("exchange") or "").strip().upper(),
            str(row.get("symbol") or "").strip().upper(),
        )
        for row in rows
        if isinstance(row, Mapping)
    }


def _prepare_tick_orderflow_state(
    storage: Any,
    orderflow: Any,
    watchlist: list[dict[str, str]],
    *,
    storage_lock: Any | None = None,
    retention_days: int = 90,
    now: float | None = None,
    workspace_dir: Path | None = None,
    checkpoint_owner: _OrderFlowCheckpointOwner | None = None,
) -> dict[str, int]:
    """Prune ticks and restore only cursor- or complete-prefix-proven state."""
    from datetime import date, datetime, timedelta  # noqa: PLC0415
    from zoneinfo import ZoneInfo  # noqa: PLC0415

    from flinttrade_data.orderflow_aggregator import (  # noqa: PLC0415
        DEFAULT_RESTORE_MAX_TICKS,
        MAX_SOURCE_CLOCK_SKEW_SECONDS,
    )
    from flinttrade_data.orderflow_checkpoint import (  # noqa: PLC0415
        load_orderflow_checkpoint,
    )
    from flinttrade_data.storage import TickReplayCursor  # noqa: PLC0415

    now_timestamp = time.time() if now is None else float(now)
    session = (
        datetime.fromtimestamp(
            now_timestamp,
            tz=ZoneInfo("Asia/Kolkata"),
        )
        .date()
        .isoformat()
    )
    summary = {
        "pruned_ticks": 0,
        "restored_ticks": 0,
        "skipped_ticks": 0,
        "restore_failures": 0,
        "checkpoint_restored": 0,
        "checkpoint_failures": 0,
        "unavailable_identities": 0,
    }

    lock_context = nullcontext() if storage_lock is None else storage_lock
    with lock_context:
        prune_ticks = getattr(storage, "prune_ticks", None)
        if callable(prune_ticks) and retention_days > 0:
            summary["pruned_ticks"] = int(prune_ticks(retention_days))

        replay_tail = getattr(orderflow, "replay_current_session_tail", None)
        restore_checkpoint = getattr(orderflow, "restore_state", None)
        retain_identities = getattr(orderflow, "retain_identities", None)
        reset_identity = getattr(orderflow, "reset", None)
        get_tail = getattr(storage, "get_ticks_after_cursor", None)
        get_cursor = getattr(storage, "get_tick_replay_cursor", None)
        if not callable(get_tail) or not callable(get_cursor) or not callable(replay_tail):
            return summary

        identities = {
            (
                str(instrument.get("exchange") or "").strip().upper(),
                str(instrument.get("symbol") or "").strip().upper(),
            )
            for instrument in watchlist
            if isinstance(instrument, dict)
        }
        valid_identities = {(exchange, symbol) for exchange, symbol in identities if exchange and symbol}
        summary["skipped_ticks"] += len(identities - valid_identities)

        checkpoint = None
        checkpoint_replay_cursor = None
        checkpoint_identities: set[tuple[str, str]] = set()
        try:
            checkpoint = load_orderflow_checkpoint(workspace_dir or _workspace_dir())
            if checkpoint_owner is not None:
                checkpoint_replay_cursor = checkpoint_owner.bind_for_restore(checkpoint)
            if checkpoint is not None:
                validate_cursor = getattr(storage, "validate_tick_replay_cursor", None)
                if not callable(validate_cursor) or not callable(restore_checkpoint):
                    raise RuntimeError("checkpoint restore APIs are unavailable")
                if checkpoint_owner is None:
                    validate_cursor(checkpoint.cursor)
                    checkpoint_replay_cursor = checkpoint.cursor
                restore_checkpoint(checkpoint.orderflow_state, now=now_timestamp)
                checkpoint_identities = _checkpoint_identities(checkpoint.orderflow_state)
                if callable(retain_identities):
                    retain_identities(valid_identities)
                summary["checkpoint_restored"] = 1
        except Exception as exc:  # noqa: BLE001 - invalid restart state fails closed
            summary["checkpoint_failures"] += 1
            checkpoint = None
            checkpoint_identities.clear()
            if callable(reset_identity):
                reset_identity()
            logger.warning(
                "Order-flow checkpoint rejected (%s); requiring complete session prefixes",
                type(exc).__name__,
            )

        def load_cursor_tail(
            replay_cursor: TickReplayCursor,
            symbol: str,
            exchange: str,
            start_session: str | None,
        ) -> list[dict[str, Any]]:
            """Read a globally bounded retained-session tail in commit order."""
            if start_session is None:
                sessions: list[str | None] = [None]
            else:
                start_date = date.fromisoformat(start_session)
                end_date = datetime.fromtimestamp(
                    now_timestamp + MAX_SOURCE_CLOCK_SKEW_SECONDS,
                    tz=ZoneInfo("Asia/Kolkata"),
                ).date()
                if start_date > end_date:
                    start_date = end_date
                sessions = []
                current_date = start_date
                while current_date <= end_date:
                    sessions.append(current_date.isoformat())
                    current_date += timedelta(days=1)
            rows: list[dict[str, Any]] = []
            for source_session in sessions:
                if len(rows) > DEFAULT_RESTORE_MAX_TICKS:
                    break
                remaining = DEFAULT_RESTORE_MAX_TICKS + 1 - len(rows)
                chunk = get_tail(
                    replay_cursor,
                    symbol,
                    exchange,
                    source_session,
                    limit=remaining,
                )
                if not isinstance(chunk, list):
                    raise RuntimeError("cursor-bound tick query returned an invalid result")
                chunk_sequences = [row.get("ingest_seq") for row in chunk]
                if any(isinstance(value, bool) or not isinstance(value, int) for value in chunk_sequences):
                    raise RuntimeError("cursor-bound tick tail has invalid ingest sequences")
                if chunk_sequences != sorted(chunk_sequences) or len(set(chunk_sequences)) != len(chunk_sequences):
                    raise RuntimeError("cursor-bound tick tail is not monotonic within a session")
                rows.extend(chunk)
            if len(rows) > DEFAULT_RESTORE_MAX_TICKS:
                raise RuntimeError("cursor-bound tick tail is incomplete")
            sequences = [int(row["ingest_seq"]) for row in rows]
            if len(set(sequences)) != len(sequences):
                raise RuntimeError("cursor-bound tick tail contains duplicate ingest sequences")
            rows.sort(key=lambda row: int(row["ingest_seq"]))
            return rows

        for exchange, symbol in sorted(valid_identities):
            try:
                if checkpoint is not None and (exchange, symbol) in checkpoint_identities:
                    ticks = load_cursor_tail(
                        checkpoint_replay_cursor,
                        symbol,
                        exchange,
                        None,
                    )
                    result = replay_tail(
                        ticks,
                        now=now_timestamp,
                        max_ticks=DEFAULT_RESTORE_MAX_TICKS,
                        history_complete=True,
                    )
                else:
                    current_cursor = get_cursor()
                    zero_cursor = TickReplayCursor(
                        store_id=current_cursor.store_id,
                        ingest_seq=0,
                    )
                    ticks = load_cursor_tail(
                        zero_cursor,
                        symbol,
                        exchange,
                        session,
                    )
                    if callable(reset_identity):
                        reset_identity(symbol, exchange=exchange)
                    result = replay_tail(
                        ticks,
                        now=now_timestamp,
                        max_ticks=DEFAULT_RESTORE_MAX_TICKS,
                        history_complete=True,
                    )
            except Exception as exc:  # noqa: BLE001 - one instrument must not block capture
                summary["restore_failures"] += 1
                summary["unavailable_identities"] += 1
                if callable(reset_identity):
                    reset_identity(symbol, exchange=exchange)
                logger.warning(
                    "Order-flow restore skipped for %s:%s (%s)",
                    exchange,
                    symbol,
                    type(exc).__name__,
                )
                continue
            summary["restored_ticks"] += int(result.get("restored_ticks", 0))
            summary["skipped_ticks"] += int(result.get("skipped_ticks", 0))

    return summary


def _handle_tick_recorder_completion(
    flask_app: Flask,
    recorder: Any,
    task: Any,
    *,
    api_key: str,
    is_shutting_down: Callable[[], bool] | None = None,
    on_unpublished: Callable[[], None] | None = None,
    before_storage_close: Callable[[], None] | None = None,
    on_storage_closed: Callable[[], None] | None = None,
    close_worker: _BoundedTickStorageCloseWorker | None = None,
) -> bool:
    """Unpublish a full-app recorder that terminated outside normal shutdown."""
    if task.cancelled():
        return False
    try:
        if is_shutting_down is not None and is_shutting_down():
            return False
    except Exception:
        pass
    try:
        error = task.exception()
    except asyncio.CancelledError:
        return False
    failure = error if error is not None else RuntimeError("Tick recorder stopped unexpectedly")
    sanitise_error = getattr(recorder, "sanitise_error", None)
    try:
        diagnostic_source = sanitise_error(failure) if callable(sanitise_error) else failure
    except Exception:
        diagnostic_source = failure
    diagnostic = _sanitise_tick_capture_error(diagnostic_source, api_key)
    storage: Any | None = None
    storage_lock: Any | None = None
    with _tick_capture_lifecycle_lock(flask_app):
        if flask_app.config.get("TICK_RECORDER") is not recorder:
            return False
        flask_app.config.pop("TICK_RECORDER", None)
        storage = flask_app.config.pop("TICK_STORAGE", None)
        storage_lock = flask_app.config.pop("TICK_STORAGE_LOCK", None)
        flask_app.config.pop("ORDERFLOW_AGGREGATOR", None)
        flask_app.config["TICK_CAPTURE_ERROR"] = diagnostic
        if on_unpublished is not None:
            try:
                on_unpublished()
            except Exception as exc:  # noqa: BLE001 - done callbacks must not escape
                logger.warning("Tick runtime unpublish callback failed (%s)", type(exc).__name__)
    pending_tick_count = _pending_tick_count(recorder)
    if pending_tick_count is None:
        logger.warning("Tick storage retained after recorder exit with an unknown pending buffer")
        logger.warning("Tick capture stopped unexpectedly (%s); not recording ticks", diagnostic)
        return True
    if pending_tick_count > 0:
        logger.warning(
            "Tick storage retained after recorder exit with %d unflushed ticks",
            pending_tick_count,
        )
        logger.warning("Tick capture stopped unexpectedly (%s); not recording ticks", diagnostic)
        return True
    if close_worker is None:
        def close_owned_storage() -> None:
            if before_storage_close is not None:
                before_storage_close()
            _close_tick_storage(storage, storage_lock)

        close_worker = _BoundedTickStorageCloseWorker(
            close_owned_storage,
            on_success=on_storage_closed,
        )
    close_worker.start()
    logger.warning("Tick capture stopped unexpectedly (%s); not recording ticks", diagnostic)
    return True


def _build_tick_recorder(
    *,
    recorder_factory: Callable[..., Any],
    signal_hub: Any,
    sandbox_engine: Any | None = None,
    settings: Settings,
    storage: Any,
    storage_lock: Any,
    orderflow: Any,
    watchlist: list[dict[str, str]],
    mode: str,
    post_flush_callback: Callable[[], None] | None = None,
) -> Any:
    """Build a recorder wired to signal generation and Practice fills."""
    signal_sink = getattr(signal_hub, "process_tick", None)
    update_config = getattr(signal_hub, "update_config", None)
    if not callable(signal_sink) or not callable(update_config):
        raise RuntimeError("Signal hub is unavailable; tick capture remains disabled")

    ltp_sink = signal_sink
    sandbox_sink = getattr(sandbox_engine, "process_tick", None)
    if callable(sandbox_sink):
        def composed_ltp_sink(
            exchange: str,
            symbol: str,
            ltp: float,
            volume: int = 0,
            source_timestamp: float | None = None,
        ) -> None:
            signal_sink(exchange, symbol, ltp, volume, source_timestamp)
            sandbox_sink(exchange, symbol, ltp, volume, source_timestamp)

        ltp_sink = composed_ltp_sink

    recorder = recorder_factory(
        storage=storage,
        ws_url=openalgo_ws_base_url(settings),
        storage_lock=storage_lock,
        orderflow_aggregator=orderflow,
        post_flush_callback=post_flush_callback,
        api_key=settings.openalgo_api_key,
        ltp_sink=ltp_sink,
    )
    recorder.add_symbols(watchlist, mode=mode)
    update_config(
        instruments=[f"{instrument['exchange'].upper()}:{instrument['symbol'].upper()}" for instrument in watchlist]
    )
    return recorder


_DEFAULT_TICK_WATCHLIST: list[dict[str, str]] = [
    {"exchange": "NSE_INDEX", "symbol": "NIFTY"},
    {"exchange": "NSE_INDEX", "symbol": "BANKNIFTY"},
    {"exchange": "BSE_INDEX", "symbol": "SENSEX"},
]


def _tick_capture_watchlist() -> list[dict[str, str]]:
    """Resolve the tick-capture watchlist from workspace.json, else defaults.

    workspace.json shape::

        {"data": {"tick_capture": {"symbols": [
            {"exchange": "NSE", "symbol": "RELIANCE"}, ...
        ]}}}

    Malformed entries are skipped; an empty/missing list falls back to the
    default major-index watchlist so enabling capture always records something.
    """
    import json  # noqa: PLC0415

    path = _workspace_dir() / "workspace.json"
    if not path.exists():
        return list(_DEFAULT_TICK_WATCHLIST)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read workspace.json for tick watchlist: %s", exc)
        return list(_DEFAULT_TICK_WATCHLIST)

    raw = (((data.get("data") or {}).get("tick_capture") or {}).get("symbols")) or []
    symbols: list[dict[str, str]] = []
    for inst in raw if isinstance(raw, list) else []:
        if not isinstance(inst, dict):
            continue
        symbol = str(inst.get("symbol", "")).strip().upper()
        exchange = str(inst.get("exchange", "")).strip().upper()
        if symbol and exchange:
            symbols.append({"exchange": exchange, "symbol": symbol})
    return symbols or list(_DEFAULT_TICK_WATCHLIST)


def _read_workspace_section(*keys: str) -> Any:
    """Read a nested section from workspace.json (None when absent/unreadable)."""
    import json  # noqa: PLC0415

    path = _workspace_dir() / "workspace.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            node: Any = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _tick_capture_mode() -> str:
    """Capture mode from workspace.json data.tick_capture.mode (default quote).

    ``depth`` records the full top-5 book; ``ltp`` is the lightest. Invalid
    values fall back to ``quote`` so a typo cannot silently disable capture.
    """
    raw = _read_workspace_section("data", "tick_capture", "mode")
    mode = str(raw or "").strip().lower()
    return mode if mode in ("ltp", "quote", "depth") else "quote"


def _auto_sync_enabled() -> bool:
    """Whether the EOD historical delta-sync cron is enabled (workspace.json)."""
    raw = _read_workspace_section("data", "auto_sync", "enabled")
    if isinstance(raw, bool):
        return raw
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _auto_sync_lookback_days() -> int:
    """Delta-sync lookback window in days (default 7, clamped 1–90)."""
    raw = _read_workspace_section("data", "auto_sync", "lookback_days")
    try:
        days = int(raw) if raw is not None else 7
    except (TypeError, ValueError):
        days = 7
    return max(1, min(90, days))


def _index_rag_docs_safely(rag: Any) -> None:
    """Index docs for RAG without letting background thread errors escape."""
    try:
        count = rag.index_directory("docs/")
        logger.info("RAG background indexing completed (%s document chunks)", count)
    except Exception as exc:
        logger.warning("RAG background indexing failed: %s", exc)


def _initialise_rag_runtime(flinttrade_dir: Path) -> Any | None:
    """Construct the canonical RAG runtime when enabled and installed."""
    if not _rag_runtime_enabled():
        logger.info("RAG runtime disabled (set FLINTTRADE_RAG_ENABLED=true to enable)")
        return None

    rag_dir = flinttrade_dir / "rag"
    rag_dir.mkdir(exist_ok=True)
    try:
        import chromadb  # noqa: F401, PLC0415

        from flinttrade_ai.llm_client import LLMClient, LLMConfig  # noqa: PLC0415
        from flinttrade_ai.rag_pipeline import PipelineConfig, RAGPipeline  # noqa: PLC0415

        try:
            config = LLMConfig.from_env()
            llm_configured = bool(config.provider)
        except Exception:
            llm_configured = False
        llm_client = LLMClient() if llm_configured else None
        rag = RAGPipeline(
            config=PipelineConfig(persist_directory=str(rag_dir)),
            llm_client=llm_client,
        )
        if rag.document_count() == 0:
            if _rag_auto_index_enabled():
                logger.info("RAG database empty — indexing docs/ directory in background...")
                threading.Thread(
                    target=lambda: _index_rag_docs_safely(rag),
                    daemon=True,
                    name="rag-indexer",
                ).start()
            else:
                logger.info(
                    "RAG database empty — automatic docs indexing disabled "
                    "(set FLINTTRADE_RAG_AUTO_INDEX=true to enable)",
                )
        return rag
    except Exception as exc:
        logger.warning("RAG initialisation failed: %s", exc)
        return None


def _reconnect_saved_accounts(
    registry: BrokerRegistry,
    credential_store: CredentialStore,
    reconnect_logger: logging.Logger,
) -> None:
    """Reconnect previously saved broker accounts on startup.

    Iterates over every account persisted in the CredentialStore and attempts
    to re-authenticate each one against the registry.  Failures are logged as
    warnings so that a single bad account does not block the rest.

    Args:
        registry: The live BrokerRegistry to populate with sessions.
        credential_store: The CredentialStore that holds persisted credentials.
        reconnect_logger: Logger instance to use for progress messages.
    """
    from flinttrade_gateway.adapter import BROKER_CATALOG  # noqa: PLC0415
    from flinttrade_gateway.log_safety import account_ref  # noqa: PLC0415
    from flinttrade_gateway.session import BrokerSession  # noqa: PLC0415

    saved = credential_store.list_accounts()
    if not saved:
        reconnect_logger.info("No saved broker accounts to reconnect")
        return

    reconnect_logger.info("Reconnecting %d saved broker account(s)...", len(saved))
    for acct in saved:
        account_id: str = acct["account_id"]
        broker: str = acct["broker"]
        adapter_id = str(acct.get("adapter_id") or broker)
        label: str = acct["label"]
        info = BROKER_CATALOG.get(adapter_id) or BROKER_CATALOG.get(broker)
        safe_account = account_ref(account_id)
        if info is not None and info.native:
            reconnect_logger.info("  Skipped native account: %s (%s)", safe_account, adapter_id)
            continue
        try:
            creds = credential_store.retrieve(account_id)
            session = BrokerSession(account_id, broker, label)
            session.authenticate(creds)
            registry._sessions[account_id] = session
            if acct.get("is_primary"):
                registry._primary = account_id
            reconnect_logger.info("  Connected: %s (%s)", safe_account, broker)
        except Exception as exc:
            reconnect_logger.warning(
                "  Failed: %s (%s; %s)",
                safe_account,
                broker,
                type(exc).__name__,
            )


def _read_version() -> str:
    """Return the central FlintTrade product version tag."""
    return APP_VERSION_TAG


# ---------------------------------------------------------------------------
# Master password — cached module-level so all call-sites share a single
# value within a process.  File-backed so it survives restarts.
# ---------------------------------------------------------------------------

_MASTER_PASSWORD: str | None = None
_API_KEY_PEPPER: str | None = None
_SAFETY_GATE_SECRET: bytes | None = None


def _get_api_key_pepper() -> str:
    """Get or generate the OpenAlgo-compatible ``API_KEY_PEPPER``.

    Source of truth (NO environment variable — secrets out of env):
      1. Persisted hardened secret at ``<workspace>/api_key_pepper``.
      2. Generate a fresh ``secrets.token_urlsafe(64)``, persist it hardened.
    The value is re-exported to ``os.environ`` only as an in-process transport
    for the upstream OpenAlgo modules (their ``utils.config`` reads env).

    Upstream OpenAlgo's v2.0.0.6 hardening rejected the publicly leaked
    placeholder pepper and auto-rotates on first run. FlintTrade's broker
    shim (``packages/integrations/gateway/src/shims/config_shim.py``) re-exports this
    value as ``utils.config.API_KEY_PEPPER`` so the OpenAlgo broker
    modules get the same pepper on both code paths.

    Returns the secret string; subsequent calls within the same process
    return the cached value. A best-effort persist on disk is attempted
    so restarts pick up the same pepper.
    """
    global _API_KEY_PEPPER
    if _API_KEY_PEPPER:
        return _API_KEY_PEPPER

    # Source of truth is the hardened at-rest file — NEVER the API_KEY_PEPPER env
    # var (secrets out of env, decision B/C). The pepper is an app-generated
    # random, so auto-generating it on first run is fine (unlike the operator's
    # master passphrase). It IS re-exported into os.environ below purely as an
    # in-process transport for the upstream OpenAlgo broker modules, whose
    # ``utils.config`` can only read API_KEY_PEPPER from the environment — the
    # value originates from the hardened file, never from a committed .env.
    pepper_file = _workspace_dir() / "api_key_pepper"
    try:
        if pepper_file.exists():
            stored = pepper_file.read_text().strip()
            if stored:
                _API_KEY_PEPPER = stored
                os.environ["API_KEY_PEPPER"] = stored  # in-process OpenAlgo transport
                return _API_KEY_PEPPER
    except OSError:
        pass

    new_pepper = secrets.token_urlsafe(64)
    try:
        pepper_file.parent.mkdir(parents=True, exist_ok=True)
        _write_secret_text(pepper_file, new_pepper)  # SC-04: icacls/0600 owner-only
        logger.info("Generated new API_KEY_PEPPER (hardened) at %s", pepper_file)
    except OSError as exc:
        logger.warning(
            "Could not persist API_KEY_PEPPER to %s: %s — using ephemeral value",
            pepper_file,
            exc,
        )

    _API_KEY_PEPPER = new_pepper
    os.environ["API_KEY_PEPPER"] = new_pepper  # in-process OpenAlgo transport
    return _API_KEY_PEPPER


def _get_safety_gate_secret_bytes() -> bytes:
    """Get or generate the dedicated safety-gate HMAC secret (contract §8.0b).

    Source of truth (NO environment variable — secrets out of env):
      1. Persisted hardened secret at ``<workspace>/safety_gate_secret`` (hex).
      2. Generate a fresh 32 random bytes, persist it hex-encoded and hardened.

    This MUST be a SEPARATE key from jwt_secret / webhook_hmac_secret /
    api_key_pepper: it signs every one-shot :class:`SafetyContext`, so reusing
    another subsystem's secret would let a leak there forge order-gate tickets.
    Like the pepper it is app-generated random (not operator material), so
    auto-generating on first run is safe; an ephemeral fallback is acceptable
    because the short SafetyContext TTL drains in-flight tickets across a restart.
    """
    global _SAFETY_GATE_SECRET
    if _SAFETY_GATE_SECRET is not None:
        return _SAFETY_GATE_SECRET

    key_file = _workspace_dir() / "safety_gate_secret"
    try:
        if key_file.exists():
            stored = key_file.read_text().strip()
            if stored:
                candidate = bytes.fromhex(stored)
                if len(candidate) >= 32:
                    _SAFETY_GATE_SECRET = candidate
                    return _SAFETY_GATE_SECRET
                logger.warning(
                    "Safety-gate key file at %s is too short (<32 bytes) — regenerating",
                    key_file,
                )
    except (OSError, ValueError):
        # Unreadable or non-hex file — regenerate rather than fail closed forever.
        logger.warning("Safety-gate key file at %s unreadable/invalid — regenerating", key_file)

    new_secret = secrets.token_bytes(32)
    try:
        key_file.parent.mkdir(parents=True, exist_ok=True)
        _write_secret_text(key_file, new_secret.hex())  # SC-04: icacls/0600 owner-only
        logger.info("Generated new safety-gate key file (hardened) at %s", key_file)
    except OSError as exc:
        logger.warning(
            "Could not persist safety-gate key file at %s: %s — using ephemeral value",
            key_file,
            exc,
        )

    _SAFETY_GATE_SECRET = new_secret
    return _SAFETY_GATE_SECRET


def set_master_password(password: str) -> None:
    """Inject the master password into the process cache (TTY/fd readers, tests).

    The only supported inputs are an operator-typed passphrase (TTY getpass),
    a file descriptor (``FLINTTRADE_MASTER_PASSWORD_FD``), or the hardened
    at-rest file. NEVER an environment variable or an auto-generated default
    (locked decision #13)."""
    global _MASTER_PASSWORD
    _MASTER_PASSWORD = password


def _read_master_password_interactive() -> str:
    """Read the master passphrase from a pipe FD or a TTY prompt (locked #13).

    NEVER from ``MASTER_PASSWORD`` env var — env leaks to process listings,
    shell history, CI logs, and tracebacks that dump ``os.environ``.
    """
    import getpass  # noqa: PLC0415

    fd_env = os.environ.get("FLINTTRADE_MASTER_PASSWORD_FD")
    if fd_env:
        with os.fdopen(int(fd_env), "r") as fd:
            return fd.readline().rstrip("\n")
    if not sys.stdin.isatty():
        raise RuntimeError(
            "master password required but no TTY available; set the hardened "
            "~/.flinttrade/master_password file or pass FLINTTRADE_MASTER_PASSWORD_FD"
        )
    return getpass.getpass("FlintTrade master password: ")


def _get_master_password() -> str:
    """Return the credential-store master password (locked decision #13).

    Resolution order — NO environment variable, NO auto-generated default:
      1. process cache (set via TTY/fd reader or ``set_master_password``)
      2. the hardened at-rest file ``<workspace>/master_password`` (operator
         material per data-layer §8.1; ACL-hardened via ``secure_file.harden``)
      3. operator prompt — TTY getpass or ``FLINTTRADE_MASTER_PASSWORD_FD`` —
         then persisted to the hardened at-rest file for subsequent starts.
    """
    global _MASTER_PASSWORD
    if _MASTER_PASSWORD:
        return _MASTER_PASSWORD

    store_key_file = _workspace_dir() / "master_password"
    try:
        if store_key_file.exists():
            stored = store_key_file.read_text().strip()
            if stored:
                _MASTER_PASSWORD = stored
                return _MASTER_PASSWORD
    except OSError:
        pass

    password = _read_master_password_interactive()
    if not password:
        raise RuntimeError("master password required (empty input rejected)")

    try:
        _write_secret_text(store_key_file, password)  # SC-04: icacls/0600 owner-only
        logger.info("Persisted credential-store key file (hardened) at %s", store_key_file)
    except OSError as exc:
        logger.warning(
            "Could not persist credential-store key file at %s: %s — using session value",
            store_key_file,
            exc,
        )

    _MASTER_PASSWORD = password
    return _MASTER_PASSWORD


# ---------------------------------------------------------------------------
# workspace.json reader — OpenAlgo overrides from user config
# ---------------------------------------------------------------------------


def _read_openalgo_from_workspace() -> dict[str, Any]:
    """Read OpenAlgo overrides from ``~/.flinttrade/workspace.json``.

    Returns a dict with any of ``api_key``, ``host``, ``port``, ``ws_port`` keys that
    are present and non-empty.  Returns an empty dict if the file is
    missing, unreadable, or doesn't contain an ``openalgo`` section.

    workspace.json wins over .env because it's user-edited through the UI
    (Setup wizard, Settings page) while .env is the dev-machine fallback.
    """
    import json  # noqa: PLC0415

    try:
        from .workspace import Workspace  # noqa: PLC0415

        ws = Workspace()
        path = ws.config_path
    except Exception:
        # Fallback: direct workspace.json path (respects FLINTTRADE_WORKSPACE_DIR)
        path = _workspace_dir() / "workspace.json"

    if not path.exists():
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read workspace.json at %s: %s", path, exc)
        return {}

    openalgo = data.get("openalgo") or {}
    if not isinstance(openalgo, dict):
        return {}

    result: dict[str, Any] = {}
    for key in ("api_key", "host", "port", "ws_port"):
        val = openalgo.get(key)
        if val:
            result[key] = val
    return result


def _log_workspace_openalgo_overrides() -> None:
    """Log UI-owned OpenAlgo overrides available in workspace.json.

    Settings reads these values directly from the workspace. They are no
    longer copied into ``os.environ`` as native-runtime configuration.
    """
    overrides = _read_openalgo_from_workspace()
    if not overrides:
        return

    logger.info(
        "OpenAlgo settings available from workspace.json (%s)",
        ", ".join(sorted(overrides.keys())),
    )


# ---------------------------------------------------------------------------
# DuckDB stale .wal recovery — checkpoint recoverable logs on boot
# ---------------------------------------------------------------------------


def _cleanup_stale_duckdb_wals() -> None:
    """Recover paired ``*.wal`` files and remove only database-less orphans.

    A paired WAL may contain committed rows that have not reached the database
    file. Opening read-write lets DuckDB replay that WAL; an explicit checkpoint
    and clean close then retire it safely. A paired WAL is never unlinked by
    application code. Locked or corrupt databases remain untouched.
    """
    flinttrade_dir = _workspace_dir()
    if not flinttrade_dir.exists():
        return

    try:
        wal_files = list(flinttrade_dir.glob("*.wal"))
    except OSError:
        return

    if not wal_files:
        return

    try:
        import duckdb  # noqa: PLC0415
    except ImportError:
        # DuckDB not installed — nothing to validate against
        return

    recovered = 0
    orphaned = 0
    for wal in wal_files:
        db_file = wal.with_suffix("")  # strip .wal → leaves .db / .duckdb etc.
        # If the .wal pairs with a file that doesn't exist, just clear it.
        if not db_file.exists():
            try:
                wal.unlink()
                orphaned += 1
            except OSError:
                pass
            continue

        # A read-only probe can replay the WAL in memory without checkpointing
        # it, after which deleting the file loses the recovered transaction.
        # Let DuckDB own recovery and WAL retirement through a read-write open.
        try:
            with duckdb.connect(str(db_file)) as conn:
                conn.execute("CHECKPOINT")
        except Exception as exc:
            # Another process holds the lock, or recovery failed. Preserve the
            # paired WAL exactly as-is for a later retry or manual inspection.
            logger.warning(
                "Skipping DuckDB WAL recovery for %s (DB appears locked or broken): %s",
                db_file.name,
                exc,
            )
            continue
        if wal.exists():
            logger.warning(
                "DuckDB checkpoint left paired WAL %s in place; preserving it",
                wal.name,
            )
        else:
            recovered += 1

    if recovered or orphaned:
        logger.info(
            "Recovered %d DuckDB WAL file(s); removed %d database-less orphan(s)",
            recovered,
            orphaned,
        )


# ---------------------------------------------------------------------------
# Broker router wiring (selector-bound principal; contract §13 / §11.4)
# ---------------------------------------------------------------------------


def _read_workspace_brokers() -> dict[str, Any] | None:
    """Return the ``brokers`` block from workspace.json, or ``None`` if absent.

    ``None`` (no real config) lets the caller fall back to the spec defaults
    without writing a rollback snapshot for an empty config.
    """
    try:
        path = _workspace_dir() / "workspace.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        brokers = data.get("brokers")
        return brokers if isinstance(brokers, dict) and brokers else None
    except Exception as exc:
        logger.warning("Could not read brokers from workspace.json (%s)", type(exc).__name__)
        return None


def _snapshot_brokers_bak(brokers_config: dict[str, Any]) -> None:
    """Write the last-known-good brokers config to ``workspace.brokers.bak.json``.

    Atomic (tmp -> fsync -> os.replace, with the same Windows retry as the
    workspace writer) so a crash mid-write can never leave a torn rollback
    artefact: the file is always either the previous-complete or the
    new-complete config — which is exactly when the operator needs it
    (contract §13.3).
    """
    from .workspace_migrations import _atomic_write  # noqa: PLC0415

    bak = _workspace_dir() / "workspace.brokers.bak.json"
    _atomic_write(bak, json.dumps(brokers_config, indent=2))


def _native_activation_checks(
    credential_store: CredentialStore | None,
) -> tuple[Callable[[str], bool], Callable[[str], bool]]:
    """Build the ``(attest_ok, has_credentials)`` gates for native activation.

    ``attest_ok(broker_id)`` is true only when the broker's pinned SDK
    (``brokers.lock``) is installed at the exact pinned version; ``has_credentials``
    is true only when the encrypted vault holds an account for that broker. Both
    fail closed: any error (no lock, no vault) yields ``False`` so a native stays
    dormant. In the default no-SDK / no-creds environment every native is
    correctly skipped.
    """
    from flinttrade_gateway.brokers.native_factory import SDK_PIN_BY_BROKER  # noqa: PLC0415

    try:
        from .broker_sdk_attest import STATUS_OK, attest_all  # noqa: PLC0415

        attest_status = {r.broker: r.status for r in attest_all()}
    except Exception as exc:  # pragma: no cover - attestation must never brick boot
        logger.warning(
            "Native attestation unavailable (%s) — natives stay dormant",
            type(exc).__name__,
        )
        attest_status = {}

    def attest_ok(broker_id: str) -> bool:
        if broker_id not in SDK_PIN_BY_BROKER:
            return False
        pin = SDK_PIN_BY_BROKER[broker_id]
        if pin is None:
            # REST-only native (no third-party SDK, currently INDmoney): nothing to
            # attest — activation is gated by stored credentials alone.
            return True
        return attest_status.get(pin) == STATUS_OK

    credentialled: set[str] = set()
    if credential_store is not None:
        try:
            for account in credential_store.list_accounts():
                adapter_id = account.get("adapter_id") or account.get("broker")
                if adapter_id:
                    credentialled.add(str(adapter_id))
        except Exception as exc:  # pragma: no cover - vault read must never brick boot
            logger.warning(
                "Credential vault read failed (%s) — natives stay dormant",
                type(exc).__name__,
            )

    def has_credentials(broker_id: str) -> bool:
        return broker_id in credentialled

    return attest_ok, has_credentials


def _lazy_dhan_security_resolver() -> Callable[[str, str], str]:
    """Build a Dhan scrip-master resolver on first use.

    Dhan order and market-data calls take numeric security ids. The standalone
    live probe warms this resolver before market reads; the app-activated native
    adapter needs the same behaviour so broker routes and gated writes do not
    fail after a successful connect.
    """
    lock = threading.Lock()
    resolver: Callable[[str, str], str] | None = None

    def _resolve(symbol: str, exchange: str) -> str:
        nonlocal resolver
        if resolver is None:
            with lock:
                if resolver is None:
                    # Reuse the adapter's canonical public fetch+parse helper —
                    # no cross-package reach into module-private symbols and no
                    # second copy of the download+CSV composition to drift.
                    from flinttrade_gateway.brokers import dhan_mapping as dhan_map  # noqa: PLC0415
                    from flinttrade_gateway.brokers.dhan import load_scrip_master_rows  # noqa: PLC0415

                    rows = load_scrip_master_rows("compact")
                    resolver = dhan_map.build_security_resolver(rows)
                    logger.info("Dhan security resolver loaded from compact scrip master rows=%s", len(rows))
        return resolver(symbol, exchange)

    return _resolve


def _native_adapter_kwargs_for(
    local_state_provider: Callable[[Any], Any],
) -> Callable[[str], dict[str, Any]]:
    """Return per-native adapter constructor kwargs for app activation."""
    dhan_security_resolver = _lazy_dhan_security_resolver()

    def _kwargs(broker_id: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"local_state_provider": local_state_provider}
        if broker_id == "dhan":
            kwargs["security_resolver"] = dhan_security_resolver
        return kwargs

    return _kwargs


def _build_reconcile_targets_provider(
    registry: BrokerRegistry,
    active_adapters: dict[str, Any],
    registered_selectors: list[str],
) -> Callable[[], list[tuple[Any, Any]]]:
    """Build the ``(adapter, session)`` enumerator the reconciliation runner polls.

    Resolved AT CALL TIME so natives that authenticate after boot (the
    credential-replay login step) are picked up on the runner's next cycle: a
    registered selector yields a target only when its adapter is active in
    ``active_adapters`` AND the registry holds an adapter-layer session for it.
    OpenAlgo participates through the same adapter contract as native brokers.

    Args:
        registry: The broker registry holding adapter-layer sessions.
        active_adapters: Live ``broker_id -> adapter`` map for this router generation.
        registered_selectors: The workspace ``brokers.registered`` selectors.

    Returns:
        Zero-argument callable returning the current reconcile targets.
    """

    def _targets() -> list[tuple[Any, Any]]:
        from flinttrade_engine.request_context import parse_selector  # noqa: PLC0415

        pairs: list[tuple[Any, Any]] = []
        for selector in registered_selectors:
            try:
                adapter_id, account_id = parse_selector(selector)
            except ValueError:
                continue
            adapter = active_adapters.get(adapter_id)
            if adapter is None:
                continue
            try:
                session = registry.get_session_for(adapter_id, account_id)
            except Exception:
                continue  # no live session yet — not an error, just dormant
            pairs.append((adapter, session))
        return pairs

    return _targets


def _current_reconcile_targets(app: Flask) -> list[tuple[Any, Any]]:
    """Resolve targets from the currently published router generation."""
    provider = app.config.get("RECONCILE_TARGETS")
    targets = list(provider()) if callable(provider) else []
    ditto = app.config.get("DITTO_RUNTIME")
    ditto_provider = getattr(ditto, "reconciliation_targets", None)
    if callable(ditto_provider):
        try:
            targets.extend(ditto_provider())
        except Exception as exc:  # noqa: BLE001 - one optional owner must not hide main targets
            logger.warning("Ditto reconciliation target lookup failed (%s)", type(exc).__name__)
    return targets


def _record_current_reconcile_snapshot(app: Flask, **snapshot: Any) -> int:
    """Record observations in the app-owned ledger current at call time."""
    ledger = app.config.get("ORDER_LIFECYCLE_LEDGER") or app.config.get("LOCAL_STATE_PROVIDER")
    recorder = getattr(ledger, "record_broker_snapshot", None)
    if not callable(recorder):
        raise RuntimeError("order lifecycle ledger is unavailable")
    return recorder(**snapshot)


def build_broker_router(
    registry: BrokerRegistry,
    brokers_config: dict[str, Any],
    *,
    adapters: dict[str, Any] | None = None,
    openalgo_client: Any | None = None,
    native_attest_ok: Callable[[str], bool] | None = None,
    native_has_credentials: Callable[[str], bool] | None = None,
    native_adapter_kwargs: Callable[[str], dict[str, Any]] | None = None,
    on_native_activated: Callable[[dict[str, Any]], None] | None = None,
    on_adapters_activated: Callable[[dict[str, Any]], None] | None = None,
    write_admission: Callable[[bool, str], ContextManager[None]] | None = None,
    lifecycle_store: Any | None = None,
) -> Any:
    """Construct a config-driven :class:`BrokerRouter` (contract §13 / §11.4).

    Parses ``brokers_config`` into a :class:`RoutingConfig` (raising
    ``RoutingConfigError`` on a malformed block), wires an
    :class:`AuthenticatingSessionProvider` over the config's ``account_acls`` and
    a process-local one-shot :class:`SafetyGate`.

    When ``openalgo_client`` is supplied, an :class:`OpenAlgoAdapter` is
    registered under the ``openalgo`` adapter id and a Session is put in the
    registry for every ``openalgo:<account>`` selector in ``registered`` — so the
    gated path can dispatch to ALL of the operator's brokers through OpenAlgo
    (the actor still needs an entry in ``account_acls`` to be authorised).

    Native SDK adapters activate the moment their prerequisites hold: when both
    ``native_attest_ok`` (SDK installed + pinned-match) and
    ``native_has_credentials`` (vault holds creds) are supplied, the native
    selectors in ``registered`` are run through ``build_native_adapters`` and the
    survivors registered alongside OpenAlgo. With either callable omitted — the
    default — no native is constructed, so the natives stay dormant exactly as
    before. ``adapters`` still lets a caller inject adapters directly (and wins
    over the factory for the same id). A registered native has no live Session
    until the credential-replay login step establishes one; an unauthenticated
    native selector simply has no session to dispatch to.

    ``on_native_activated`` (when supplied) is called once with the final
    ``broker_id -> adapter`` map of ACTIVE native adapters (factory-built or
    injected) so the caller can wire engine-side consumers — the reconciliation
    runner — without reaching into the router's internals. Best-effort: a sink
    failure is logged and never bricks routing.

    ``write_admission`` is the process safety admission barrier. The router
    enters it immediately around adapter-write admission so global L5 and
    account-scoped MTM activation are ordered atomically against normal writes.

    Raises:
        RoutingConfigError: If ``brokers_config`` is malformed.
    """
    from flinttrade_engine.request_context import parse_selector  # noqa: PLC0415
    from flinttrade_engine.safety import SafetyGate  # noqa: PLC0415
    from flinttrade_gateway.adapter import BROKER_CATALOG  # noqa: PLC0415
    from flinttrade_gateway.brokers.native_factory import (  # noqa: PLC0415
        build_native_adapters,
        is_native_broker,
    )
    from flinttrade_gateway.router import BrokerRouter  # noqa: PLC0415
    from flinttrade_gateway.routing_config import RoutingConfig  # noqa: PLC0415
    from flinttrade_gateway.session_provider import (  # noqa: PLC0415
        AuthenticatingSessionProvider,
    )

    config = RoutingConfig.from_workspace(brokers_config)
    session_provider = AuthenticatingSessionProvider(registry, config.account_acls)
    gate = SafetyGate()

    resolved_adapters: dict[str, Any] = dict(adapters or {})

    # Native-adapter activation (dormant -> live bridge). Only runs when the
    # caller supplies both prerequisite checks; otherwise natives stay dormant.
    if native_attest_ok is not None and native_has_credentials is not None:
        native_ids: list[str] = []
        for selector in config.registered:
            try:
                adapter_id, _account = parse_selector(selector)
            except ValueError:
                continue
            info = BROKER_CATALOG.get(adapter_id)
            if info is not None and info.native and not info.connectable:
                logger.info("Native adapter %s dormant: coming-soon-activation-blocked", adapter_id)
                continue
            native_ids.append(adapter_id)
        activated = build_native_adapters(
            native_ids,
            attest_ok=native_attest_ok,
            has_credentials=native_has_credentials,
            adapter_kwargs=native_adapter_kwargs,
            on_skip=lambda bid, why: logger.info("Native adapter %s dormant: %s", bid, why),
        )
        for adapter_id, adapter in activated.items():
            resolved_adapters.setdefault(adapter_id, adapter)
        if activated:
            logger.info("Native adapters activated: %s", ", ".join(sorted(activated)))
    if openalgo_client is not None and "openalgo" not in resolved_adapters:
        from flinttrade_gateway.brokers._base import Session as _AdapterSession  # noqa: PLC0415
        from flinttrade_gateway.brokers.openalgo import OpenAlgoAdapter  # noqa: PLC0415

        resolved_adapters["openalgo"] = OpenAlgoAdapter(
            default_client=openalgo_client,
            local_state_provider=lifecycle_store,
        )
        # Register a Session for each openalgo:<account> selector so the
        # AuthenticatingSessionProvider can resolve it (the actor still has to be
        # authorised in account_acls).
        for selector in config.registered:
            try:
                adapter_id, account_id = parse_selector(selector)
            except ValueError:
                continue
            if adapter_id == "openalgo":
                registry.put_session(
                    "openalgo",
                    account_id,
                    _AdapterSession(
                        access_token="",
                        expires_at=4_102_444_800.0,
                        account_id=account_id,
                        adapter_id="openalgo",
                    ),
                )

    # Report the ACTIVE native adapters (factory-built or injected) to the
    # caller's sink so the engine-side reconciliation runner can enumerate them
    # without reaching into the router. The bridge (openalgo) never qualifies.
    if on_native_activated is not None:
        try:
            on_native_activated({aid: adapter for aid, adapter in resolved_adapters.items() if is_native_broker(aid)})
        except Exception as exc:  # pragma: no cover - observability only
            logger.warning("Native-adapter activation sink failed (%s)", type(exc).__name__)
    if on_adapters_activated is not None:
        try:
            on_adapters_activated(dict(resolved_adapters))
        except Exception as exc:  # pragma: no cover - observability only
            logger.warning("Adapter activation sink failed (%s)", type(exc).__name__)

    # Per-broker API rate limiter (DATA & INFRA: customizable rate limits). Built
    # from each registered adapter's capability metadata, with operator overrides
    # from workspace.json brokers.rate_limits[broker_id].{order,data}. A pure
    # below-the-gate throttle — it only delays a dispatch, never bypasses safety.
    rate_limiter = None
    try:
        from flinttrade_gateway.rate_limiter import BrokerRateLimiter  # noqa: PLC0415

        caps = {
            aid: adapter.capabilities for aid, adapter in resolved_adapters.items() if hasattr(adapter, "capabilities")
        }
        overrides = brokers_config.get("rate_limits", {}) if isinstance(brokers_config, dict) else {}
        if caps or overrides:
            rate_limiter = BrokerRateLimiter.from_capabilities(caps, overrides=overrides)
    except Exception as exc:  # pragma: no cover - a bad limit must not brick routing
        logger.warning(
            "Broker rate limiter not built (%s); dispatch will be unthrottled",
            type(exc).__name__,
        )

    # Algo-tag guard (SEBI algo-id relay + per-(broker, exchange) per-second
    # algo-order ceiling) for adapters advertising ``algo_tag_required``
    # (Dhan/IndMoney). Built only when the operator configured their
    # broker-registered algo ids in workspace.json
    # ``brokers.algo_tags[broker_id].{algo_id, max_orders_per_sec}``.
    #
    # Parsed LENIENTLY per-entry: an invalid or unknown-broker entry is dropped
    # with a loud error and the remaining valid entries still apply. A dropped
    # entry is safe — the adapter/mapping retail default takes over (Dhan places
    # untagged, IndMoney injects its per-exchange default id), so no order ever
    # dispatches in a broker-flagging state. Crucially the guard is NOT allowed
    # to brick the whole BrokerRouter: a bad algo_tags block must not take down
    # broker READS, reconciliation, and bridge dispatch (only the custom
    # ceiling/relay is forfeited until the operator fixes workspace.json).
    algo_tag_guard = None
    algo_tags_cfg = brokers_config.get("algo_tags", {}) if isinstance(brokers_config, dict) else {}
    if isinstance(algo_tags_cfg, dict) and algo_tags_cfg:
        from flinttrade_engine.algo_tag_guard import AlgoTagConfig, AlgoTagGuard  # noqa: PLC0415

        # Only adapters that actually consult the guard (algo_tag_required) can
        # be tagged; a typo'd/non-algo broker key is inert, so reject it loudly
        # rather than logging it as "active".
        taggable = {
            aid
            for aid, adapter in resolved_adapters.items()
            if getattr(getattr(adapter, "capabilities", None), "algo_tag_required", False)
        }
        tag_configs: dict[str, AlgoTagConfig] = {}
        for broker_id, spec in algo_tags_cfg.items():
            bid = str(broker_id)
            if not isinstance(spec, dict):
                logger.error("brokers.algo_tags[%r] ignored — must be an object", bid)
                continue
            algo_id = str(spec.get("algo_id", "")).strip()
            try:
                max_per_sec = int(spec.get("max_orders_per_sec", 0) or 0)
            except (TypeError, ValueError):
                max_per_sec = 0
            if not algo_id or max_per_sec <= 0:
                logger.error(
                    "brokers.algo_tags[%r] ignored — needs a non-empty algo_id and a positive max_orders_per_sec",
                    bid,
                )
                continue
            if taggable and bid not in taggable:
                logger.error(
                    "brokers.algo_tags[%r] ignored — %r is not an active algo-tag broker "
                    "(algo_tag_required). Active: %s",
                    bid,
                    bid,
                    sorted(taggable),
                )
                continue
            tag_configs[bid] = AlgoTagConfig(algo_id=algo_id, max_orders_per_sec=max_per_sec)
        if tag_configs:
            algo_tag_guard = AlgoTagGuard(tag_configs)
            logger.info("Algo-tag guard active for: %s", ", ".join(sorted(tag_configs)))

    return BrokerRouter(
        resolved_adapters,
        session_provider,
        consume_gate=gate.consume,
        config=config,
        rate_limiter=rate_limiter,
        algo_tag_guard=algo_tag_guard,
        write_admission=write_admission,
        lifecycle_store=lifecycle_store,
    )


def _broker_router_drain_timeout(app: Flask) -> float:
    """Return the configured bounded generation-drain timeout."""
    raw_timeout = app.config.get("BROKER_ROUTER_DRAIN_TIMEOUT_SECONDS", 10.0)
    try:
        return max(0.0, float(raw_timeout))
    except (TypeError, ValueError):
        return 10.0


def retire_broker_router_generation(app: Flask, *, timeout: float | None = None) -> bool:
    """Unpublish and permanently retire the current routing generation.

    A timed-out generation remains strongly referenced in app config so a
    later rebuild or shutdown retry must finish draining that exact instance
    before any replacement can be published.

    Lock order is generation rebuild lease before router generation condition.
    Safety reset follows the same outer-lease-first order and never acquires
    this lock from inside the kill-switch condition.
    """
    rebuild_lock = app.config.setdefault("BROKER_ROUTER_REBUILD_LOCK", threading.RLock())
    drain_timeout = _broker_router_drain_timeout(app) if timeout is None else max(0.0, timeout)
    if not rebuild_lock.acquire(timeout=drain_timeout):
        logger.critical("BrokerRouter retirement timed out waiting for the routing-generation lease")
        return False
    try:
        active_router = app.config.get("BROKER_ROUTER")
        draining_router = app.config.get("BROKER_ROUTER_DRAINING")
        if active_router is not None:
            if draining_router is not None and draining_router is not active_router:
                app.config["BROKER_ROUTER"] = None
                logger.critical("Multiple BrokerRouter generations require draining; routing is disabled")
                return False
            app.config["BROKER_ROUTER"] = None
            draining_router = active_router
            app.config["BROKER_ROUTER_DRAINING"] = active_router

        if draining_router is None:
            app.config["BROKER_ROUTER_DRAINING"] = None
            return True

        revoke_and_drain = getattr(draining_router, "revoke_and_drain", None)
        if not callable(revoke_and_drain):
            logger.critical("BrokerRouter generation cannot be revoked; routing is disabled")
            return False

        try:
            drained = bool(revoke_and_drain(timeout=drain_timeout))
        except Exception as exc:  # noqa: BLE001 - stale writes fail closed
            logger.critical(
                "BrokerRouter generation revocation failed (%s)",
                type(exc).__name__,
            )
            return False
        if not drained:
            return False

        if app.config.get("BROKER_ROUTER_DRAINING") is draining_router:
            app.config["BROKER_ROUTER_DRAINING"] = None
        return True
    finally:
        rebuild_lock.release()


def configure_broker_router(
    app: Flask,
    registry: Any,
    credential_store: Any,
    openalgo_client: Any,
) -> bool:
    """Build (or rebuild) the BrokerRouter and store it + friends on app.config.

    Extracted from ``create_flask_app`` so it can be re-invoked at runtime after
    the credential vault or the ``brokers.registered``/``account_acls`` config
    changes (an interactive "connect native broker" action) — rebuilding
    re-reads the vault + config, so a native that just gained credentials
    activates. A rebuild publishes one complete routing generation atomically.
    The prior generation is revoked and drained before the candidate becomes
    reachable, so retained background references cannot dispatch through stale
    credentials or ACLs. Any failure leaves routing unavailable.
    """
    rebuild_lock = app.config.setdefault("BROKER_ROUTER_REBUILD_LOCK", threading.RLock())
    rebuild_timeout = _broker_router_drain_timeout(app)
    if not rebuild_lock.acquire(timeout=rebuild_timeout):
        logger.critical("BrokerRouter rebuild timed out waiting for the routing-generation lease")
        return False
    try:
        if not app.config.get("RUNTIME_ACCEPTING_REQUESTS", True):
            logger.warning("BrokerRouter rebuild refused while the runtime is shutting down")
            retire_broker_router_generation(app)
            app.config["SMART_ROUTING"] = {}
            app.config["NATIVE_ADAPTERS"] = {}
            app.config["ACTIVE_BROKER_ADAPTERS"] = {}
            app.config["RECONCILE_TARGETS"] = None
            return False
        if not retire_broker_router_generation(app):
            app.config["NATIVE_ADAPTERS"] = {}
            app.config["ACTIVE_BROKER_ADAPTERS"] = {}
            app.config["RECONCILE_TARGETS"] = None
            logger.critical("BrokerRouter rebuild aborted because the prior generation did not drain")
            return False
        intent_journal = app.config.get("EMERGENCY_INTENT_JOURNAL")
        daily_pnl_state_store = app.config.get("DAILY_PNL_STATE_STORE")
        safety = app.config.get("SAFETY")
        write_admission = getattr(safety, "broker_write_admission", None)
        reservations_durable = getattr(safety, "order_reservations_durable", False)
        if (
            app.config.get("EMERGENCY_INTENT_JOURNAL_READY") is not True
            or app.config.get("DAILY_PNL_STATE_READY") is not True
            or app.config.get("SAFETY_CONFIG_READY") is not True
            or intent_journal is None
            or daily_pnl_state_store is None
            or safety is None
            or not callable(write_admission)
            or reservations_durable is not True
            or app.config.get("EMERGENCY_RUNTIME_READY") is not True
            or app.config.get("EMERGENCY_DISPATCHER") is None
        ):
            app.config["NATIVE_ADAPTERS"] = {}
            app.config["ACTIVE_BROKER_ADAPTERS"] = {}
            app.config["RECONCILE_TARGETS"] = None
            logger.critical(
                "BrokerRouter not built because durable safety configuration/reservations, emergency journal, "
                "dispatcher, runtime, or daily P&L state readiness is incomplete; live routing remains disabled"
            )
            return False

        candidate_router = None
        candidate_smart_routing: dict[str, Any] = {}
        candidate_native_adapters: dict[str, Any] = {}
        candidate_active_adapters: dict[str, Any] = {}
        candidate_reconcile_targets = None
        brokers_cfg: dict[str, Any] | None = None
        build_error: Exception | None = None
        try:
            from .workspace_migrations import default_workspace_config  # noqa: PLC0415
            from flinttrade_engine.local_state_provider import OrderLifecycleLedger  # noqa: PLC0415

            brokers_cfg = _read_workspace_brokers()
            effective_brokers = brokers_cfg or default_workspace_config()["brokers"]
            candidate_smart_routing = dict(effective_brokers.get("smart_routing") or {})
            native_attest_ok, native_has_credentials = _native_activation_checks(credential_store)
            local_state_provider = app.config.get("ORDER_LIFECYCLE_LEDGER")
            if local_state_provider is None:
                local_state_provider = app.config.get("LOCAL_STATE_PROVIDER")
            if local_state_provider is None:
                local_state_provider = OrderLifecycleLedger()
            bind_audit_verifier = getattr(local_state_provider, "set_audit_receipt_verifier", None)
            verify_audit_receipt = getattr(
                app.config.get("AUDIT"),
                "verify_event_receipt",
                None,
            )
            if callable(bind_audit_verifier):
                bind_audit_verifier(
                    verify_audit_receipt if callable(verify_audit_receipt) else None
                )
            app.config["ORDER_LIFECYCLE_LEDGER"] = local_state_provider
            candidate_router = build_broker_router(
                registry,
                effective_brokers,
                openalgo_client=openalgo_client,
                native_attest_ok=native_attest_ok,
                native_has_credentials=native_has_credentials,
                native_adapter_kwargs=_native_adapter_kwargs_for(local_state_provider),
                on_native_activated=candidate_native_adapters.update,
                on_adapters_activated=candidate_active_adapters.update,
                write_admission=write_admission,
                lifecycle_store=local_state_provider,
            )
            candidate_reconcile_targets = _build_reconcile_targets_provider(
                registry,
                candidate_active_adapters,
                [str(s) for s in (effective_brokers.get("registered") or [])],
            )
            if brokers_cfg is not None:
                _snapshot_brokers_bak(brokers_cfg)
        except Exception as exc:  # noqa: BLE001 - malformed routing fails closed
            build_error = exc

        if build_error is not None or candidate_router is None:
            app.config["NATIVE_ADAPTERS"] = {}
            app.config["ACTIVE_BROKER_ADAPTERS"] = {}
            app.config["RECONCILE_TARGETS"] = None
            if build_error is not None:
                logger.critical(
                    "BrokerRouter not built — workspace.json brokers routing is invalid: %s. "
                    "Order routing is unavailable until you fix brokers.routing; the rest of "
                    "the app is up. Last known-good config: "
                    "~/.flinttrade/workspace.brokers.bak.json",
                    build_error,
                )
            return False

        if not app.config.get("RUNTIME_ACCEPTING_REQUESTS", True):
            logger.warning("BrokerRouter candidate discarded because shutdown began during rebuild")
            app.config["NATIVE_ADAPTERS"] = {}
            app.config["ACTIVE_BROKER_ADAPTERS"] = {}
            app.config["RECONCILE_TARGETS"] = None
            return False
        if (
            app.config.get("EMERGENCY_INTENT_JOURNAL_READY") is not True
            or app.config.get("DAILY_PNL_STATE_READY") is not True
            or app.config.get("SAFETY_CONFIG_READY") is not True
            or app.config.get("EMERGENCY_INTENT_JOURNAL") is not intent_journal
            or app.config.get("DAILY_PNL_STATE_STORE") is not daily_pnl_state_store
            or app.config.get("SAFETY") is not safety
            or not callable(getattr(safety, "broker_write_admission", None))
            or app.config.get("EMERGENCY_RUNTIME_READY") is not True
            or app.config.get("EMERGENCY_DISPATCHER") is None
        ):
            app.config["NATIVE_ADAPTERS"] = {}
            app.config["ACTIVE_BROKER_ADAPTERS"] = {}
            app.config["RECONCILE_TARGETS"] = None
            logger.critical("BrokerRouter candidate discarded because safety readiness changed during rebuild")
            return False

        app.config["OPENALGO_CLIENT"] = openalgo_client
        app.config["SMART_ROUTING"] = candidate_smart_routing
        app.config["NATIVE_ADAPTERS"] = candidate_native_adapters
        app.config["ACTIVE_BROKER_ADAPTERS"] = candidate_active_adapters
        app.config["RECONCILE_TARGETS"] = candidate_reconcile_targets
        app.config["ORDER_LIFECYCLE_LEDGER"] = local_state_provider
        app.config["LOCAL_STATE_PROVIDER"] = local_state_provider
        app.config["BROKER_ROUTER"] = candidate_router
        return True
    finally:
        rebuild_lock.release()


def _bind_runtime_emergency_dispatcher(
    app: Flask,
    safety: Any,
    telegram: Any,
    client: Any,
) -> Any:
    """Bind background emergency writes to the current gated router generation.

    Telegram authenticates the human command through its configured chat id,
    but it has no Flask request/JWT context. The application owner therefore
    supplies a fresh command principal using the single operator profile. The
    router still enforces the configured account ACL per write, while every L5
    dispatch snapshots all selectors registered on the current router. This
    keeps unauthorised accounts inside the global latch scope: their writes fail
    closed instead of disappearing from the durable emergency target set. One
    bounded rebuild lease keeps that target snapshot and every dispatched verb
    on the same immutable router generation; each account still receives its
    own fresh selector-bound principal.
    """
    from flinttrade_engine.request_context import RequestContext, parse_selector  # noqa: PLC0415
    from flinttrade_engine.safety import (  # noqa: PLC0415
        EmergencyBrokerTarget,
        GatedEmergencyBrokerDispatcher,
        bounded_generation_lease,
    )

    run_sync = getattr(client, "run_sync", None)
    if not callable(run_sync):
        raise RuntimeError("Emergency dispatcher requires the shared broker event-loop owner")

    def targets_provider() -> tuple[EmergencyBrokerTarget, ...]:
        auth_service = app.config.get("AUTH_SERVICE")
        if auth_service is None:
            raise ValueError("operator profile is unavailable")
        profile = auth_service.get_profile()
        actor_id = str(profile.get("username") or "").strip()
        if not actor_id:
            raise ValueError("operator profile has no ACL identity")

        router = app.config.get("BROKER_ROUTER")
        configured_selectors = getattr(router, "configured_selectors", None)
        if configured_selectors is None:
            raise ValueError("current router cannot resolve configured emergency execution selectors")
        try:
            selector_snapshot = tuple(configured_selectors)
        except TypeError as exc:
            raise ValueError("current router has invalid configured emergency execution selectors") from exc

        targets: list[EmergencyBrokerTarget] = []
        for selector in selector_snapshot:
            adapter_id, account_id = parse_selector(selector)
            request_ctx = RequestContext(
                jti=f"telegram-{secrets.token_urlsafe(24)}",
                actor_type="human",
                actor_id=actor_id,
                mode="live",
                selector=f"{adapter_id}:{account_id}",
            )
            targets.append(
                EmergencyBrokerTarget(
                    request_ctx=request_ctx,
                    adapter_id=adapter_id,
                    account_id=account_id,
                )
            )
        if not targets:
            raise ValueError("current router has no configured emergency execution selectors")
        return tuple(targets)

    def generation_lease_provider() -> ContextManager[None]:
        rebuild_lock = app.config.setdefault("BROKER_ROUTER_REBUILD_LOCK", threading.RLock())
        return bounded_generation_lease(
            rebuild_lock,
            timeout_seconds=_broker_router_drain_timeout(app),
        )

    dispatcher = GatedEmergencyBrokerDispatcher(
        router_provider=lambda: app.config.get("BROKER_ROUTER"),
        targets_provider=targets_provider,
        run_awaitable=run_sync,
        generation_lease_provider=generation_lease_provider,
        intent_journal=(
            app.config.get("EMERGENCY_INTENT_JOURNAL_WRAPPER")
            or app.config.get("EMERGENCY_INTENT_JOURNAL")
        ),
    )
    safety.bind_emergency_dispatcher(dispatcher)
    if telegram is not None:
        telegram.emergency_dispatcher = dispatcher
        telegram.emergency_authority = dispatcher.authority
        telegram.emergency_preflight = None
    app.config["EMERGENCY_DISPATCHER"] = dispatcher
    runtime_ready = getattr(safety, "runtime_loop_ready", None)
    app.config["EMERGENCY_RUNTIME_READY"] = bool(runtime_ready) if runtime_ready is not None else True
    return dispatcher


def _reestablish_native_sessions(app: Flask, *, verify: bool = True) -> dict[str, Any]:
    """Log in every active native selector whose credentials are in the vault.

    Runs the credential-replay login step (G3) for the natives that
    ``configure_broker_router`` just activated. Sync wrapper around the async
    ``establish_native_sessions`` — safe to call from the factory and from a
    Flask route (both run outside an event loop). Never raises.

    ``verify`` probes each freshly-established session with a cheap
    authenticated read so a dead token surfaces honestly as ``needs_relogin``
    instead of a false "connected". Transient broker/service-window failures
    are treated as inconclusive and keep the session.
    """
    import asyncio  # noqa: PLC0415
    import threading  # noqa: PLC0415

    from flinttrade_gateway.native_login import establish_native_sessions  # noqa: PLC0415

    native_adapters = app.config.get("NATIVE_ADAPTERS") or {}
    registry = app.config.get("REGISTRY")
    credential_store = app.config.get("CREDENTIAL_STORE")
    if not native_adapters or registry is None or credential_store is None:
        return {}
    try:
        brokers_cfg = _read_workspace_brokers() or {}
        selectors = [str(s) for s in (brokers_cfg.get("registered") or [])]

        async def _run() -> dict[str, Any]:
            return await establish_native_sessions(
                native_adapters,
                registry,
                credential_store,
                selectors,
                verify=verify,
            )

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            results = asyncio.run(_run())
        else:
            box: dict[str, Any] = {}

            def _thread_run() -> None:
                try:
                    box["results"] = asyncio.run(_run())
                except BaseException as exc:  # noqa: BLE001 - re-raise in caller thread
                    box["error"] = exc

            thread = threading.Thread(target=_thread_run, name="native-session-replay", daemon=True)
            thread.start()
            thread.join()
            if "error" in box:
                raise box["error"]
            results = box.get("results", {})
        # G7 — surface per-selector login outcomes so the accounts list can say
        # "needs fresh login: <reason>" instead of a bare red "no live session".
        # Merged (not replaced) so a boot result survives later partial reruns.
        status: dict[str, Any] = app.config.setdefault("NATIVE_SESSION_STATUS", {})
        status.update(results)
        return results
    except Exception as exc:  # noqa: BLE001 - session establishment must never brick boot/route
        logger.warning("Native session re-establishment failed (%s)", type(exc).__name__)
        return {}


# ---------------------------------------------------------------------------
# Flask API server — FlintTrade-specific endpoints (port 5100)
# ---------------------------------------------------------------------------


def _wire_ml_signal_runtime(
    app: Flask,
    cron: Any,
    time_scheduler: Any,
) -> bool:
    """Register the canonical scheduled ML producer when it was configured."""
    pipeline = app.config.get("ML_SIGNAL_PIPELINE")
    if pipeline is None:
        logger.info("Scheduled ML signals inactive - no OpenAlgo-backed producer")
        return False

    from flinttrade_ai.signal_routes import make_ml_signal_job  # noqa: PLC0415

    def market_session_for(
        exchange: str,
        symbol: str,
        session_date: Any,
    ) -> Any:
        return time_scheduler.get_market_session(
            exchange,
            on=session_date,
            symbol=symbol,
        )

    set_market_session_provider = getattr(
        pipeline,
        "set_market_session_provider",
        None,
    )
    if callable(set_market_session_provider):
        set_market_session_provider(market_session_for)

    cron.register(
        "ml_signal_cycle",
        handler=make_ml_signal_job(
            pipeline,
            lambda exchange, symbol: bool(time_scheduler.is_market_open(exchange, symbol=symbol)),
        ),
        description="Publish scheduled LightGBM signals into the canonical feed",
        trigger_type="interval",
        trigger_args={"minutes": 5},
    )
    app.config["ML_SIGNAL_JOB"] = "ml_signal_cycle"

    try:
        from flinttrade_ai.signal_retraining import (  # noqa: PLC0415
            RetrainConfig,
            SignalRetrainer,
            plan_retraining_roster,
        )

        configured_retrain = app.config.get("ML_SIGNAL_RETRAIN_CONFIG")
        if configured_retrain is None:
            retrain_config = RetrainConfig(model_dir=Path(pipeline.model_path).parent)
        elif isinstance(configured_retrain, RetrainConfig):
            retrain_config = configured_retrain
        elif isinstance(configured_retrain, Mapping):
            config_values = dict(configured_retrain)
            config_values.setdefault("model_dir", Path(pipeline.model_path).parent)
            retrain_config = RetrainConfig(**config_values)
        else:
            raise TypeError("ML_SIGNAL_RETRAIN_CONFIG must be a RetrainConfig or mapping")

        retrain_cancel_event = threading.Event()
        retrainer = SignalRetrainer(
            retrain_config,
            instruments=pipeline.instruments,
            data_fetcher=pipeline.fetch_bars,
            pipeline=pipeline,
            instrument_provider=lambda: pipeline.instruments,
            cancel_requested=retrain_cancel_event.is_set,
            market_session_provider=market_session_for,
        )
        retry_jobs: set[str] = set()

        def _schedule_retrain_retry(retry: Any, *, run_at: Any | None = None) -> None:
            scheduled_at = run_at or retry.retry_at
            job_name = (
                "ml_signal_retrain_retry:"
                f"{retry.target.exchange}:{retry.target.symbol}:"
                f"{retry.session_date.isoformat()}:{int(scheduled_at.timestamp())}"
            )

            def _run_retry() -> list[Any]:
                retry_jobs.discard(job_name)
                if retrain_cancel_event.is_set():
                    return []
                results = retrainer.run_all(
                    instruments=[retry.instrument],
                    session_date=retry.session_date,
                )
                if any(not bool(getattr(result, "completed", True)) for result in results):
                    from datetime import timedelta as _timedelta  # noqa: PLC0415

                    _schedule_retrain_retry(
                        retry,
                        run_at=time_scheduler.now_ist() + _timedelta(minutes=1),
                    )
                return results

            retry_jobs.add(job_name)
            try:
                cron.schedule_once(
                    name=job_name,
                    handler=_run_retry,
                    run_at=scheduled_at,
                    description=("Retry canonical signal training after the dated effective session close"),
                )
            except Exception:
                retry_jobs.discard(job_name)
                raise

        def _run_signal_retrain(*, roster: str = "regular") -> list[Any]:
            try:
                from datetime import time as _wall_time  # noqa: PLC0415
                from datetime import timedelta as _timedelta  # noqa: PLC0415

                now = time_scheduler.now_ist()
                session_date = now.date()
                if roster == "late" and now.time().replace(tzinfo=None) < _wall_time(12):
                    session_date -= _timedelta(days=1)
                plan = plan_retraining_roster(
                    pipeline.instruments,
                    roster=roster,
                    session_date=session_date,
                    run_at=now,
                    is_continuous=lambda exchange: bool(
                        (schedule := time_scheduler.get_schedule(exchange)) and schedule.is_24x7
                    ),
                    session_for=market_session_for,
                )
                for retry in plan.retries:
                    _schedule_retrain_retry(retry)
                results = retrainer.run_all(
                    instruments=plan.ready_instruments,
                    session_date=session_date,
                )
                if any(not bool(getattr(result, "completed", True)) for result in results):
                    logger.info("Signal retraining remains pending on its active fetch owner")
                return results
            except Exception as exc:  # noqa: BLE001 - scheduler and app must remain available
                logger.warning("Scheduled signal retraining failed (%s)", type(exc).__name__)
                return []

        def _run_late_signal_retrain() -> list[Any]:
            return _run_signal_retrain(roster="late")

        cron.register(
            "ml_signal_retrain",
            handler=_run_signal_retrain,
            description="Retrain canonical per-instrument signal models after market close",
            trigger_type="cron",
            trigger_args={
                "hour": 16,
                "minute": 0,
                "timezone": "Asia/Kolkata",
            },
        )
        cron.register(
            "ml_signal_retrain_late",
            handler=_run_late_signal_retrain,
            description="Retrain late-closing and continuous-market signal models",
            trigger_type="cron",
            trigger_args={
                "hour": 0,
                "minute": 30,
                "timezone": "Asia/Kolkata",
            },
        )
    except Exception as exc:  # noqa: BLE001 - optional ML runtime must not prevent app boot
        logger.warning("Scheduled signal retraining not wired (%s)", type(exc).__name__)
    else:
        app.config["ML_SIGNAL_RETRAIN_CONFIG"] = retrain_config
        app.config["ML_SIGNAL_RETRAINER"] = retrainer
        app.config["ML_SIGNAL_RETRAIN_JOB"] = "ml_signal_retrain"
        app.config["ML_SIGNAL_RETRAIN_JOBS"] = (
            "ml_signal_retrain",
            "ml_signal_retrain_late",
        )
        app.config["ML_SIGNAL_RETRAIN_CANCEL_EVENT"] = retrain_cancel_event
        app.config["ML_SIGNAL_RETRAIN_RETRY_JOBS"] = retry_jobs
    return True


def _configure_ditto_runtime(app: Flask, safety: Any) -> None:
    """Configure the process-owned, fail-closed Ditto orchestration runtime."""
    store = app.config.get("DITTO_CREDENTIAL_STORE")
    if store is None:
        app.config["DITTO_RUNTIME"] = None
        return

    try:
        from flinttrade_ditto.account_manager import AccountManager  # noqa: PLC0415
        from flinttrade_ditto.runtime import (  # noqa: PLC0415
            DittoCapabilityUnavailable,
            DittoRouterOwner,
            DittoRuntime,
        )

        def account_provider() -> list[Any]:
            current_store = app.config.get("DITTO_CREDENTIAL_STORE")
            if current_store is None:
                raise DittoCapabilityUnavailable("Ditto credential vault is unavailable")
            with AccountManager(credential_store=current_store) as manager:
                return manager.list_accounts()

        def router_owner_factory(accounts: list[Any], actor_id: str) -> Any:
            journal = app.config.get("EMERGENCY_INTENT_JOURNAL")
            daily_pnl_state = app.config.get("DAILY_PNL_STATE_STORE")
            write_admission = getattr(safety, "broker_write_admission", None)
            if (
                not app.config.get("RUNTIME_ACCEPTING_REQUESTS", True)
                or app.config.get("EMERGENCY_INTENT_JOURNAL_READY") is not True
                or app.config.get("DAILY_PNL_STATE_READY") is not True
                or app.config.get("SAFETY_CONFIG_READY") is not True
                or app.config.get("EMERGENCY_RUNTIME_READY") is not True
                or app.config.get("EMERGENCY_DISPATCHER") is None
                or app.config.get("SAFETY") is not safety
                or journal is None
                or daily_pnl_state is None
                or not callable(write_admission)
                or getattr(safety, "order_reservations_durable", False) is not True
            ):
                raise DittoCapabilityUnavailable("validated safety runtime is unavailable")
            return DittoRouterOwner(
                accounts,
                actor_id,
                write_admission=write_admission,
                intent_journal=journal,
                safety_system=safety,
                time_scheduler=app.config.get("TIME_SCHEDULER"),
                lifecycle_store=app.config.get("ORDER_LIFECYCLE_LEDGER"),
            )

        app.config["DITTO_RUNTIME"] = DittoRuntime(
            account_provider=account_provider,
            router_owner_factory=router_owner_factory,
        )
    except Exception as exc:  # noqa: BLE001 - Ditto remains optional and fail-closed
        app.config["DITTO_RUNTIME"] = None
        logger.warning("Ditto runtime unavailable (%s)", type(exc).__name__)


def shutdown_ditto_runtime(app: Flask, *, timeout: float = 5.0) -> bool:
    """Stop Ditto's watcher and drain its dedicated gated router generation."""
    runtime = app.config.get("DITTO_RUNTIME")
    if runtime is None:
        return True
    shutdown = getattr(runtime, "shutdown", None)
    if not callable(shutdown):
        return False
    return shutdown(timeout=max(0.0, timeout)) is True


def create_flask_app(
    safety: Any | None = None,
    scheduler: Any | None = None,
    cron: Any | None = None,
    audit: AuditLogger | None = None,
    client: OpenAlgoClient | None = None,
    registry: BrokerRegistry | None = None,
    credential_store: CredentialStore | None = None,
    contract_manager: ContractManager | None = None,
    rag: Any | None = None,
    cron_strategy_scheduler: Any | None = None,
    time_scheduler: Any | None = None,
    safety_config_ready: bool | None = None,
) -> Flask:
    """Create the Flask app with FlintTrade API routes.

    Args:
        safety: SafetySystem instance to expose via safety endpoints.
        safety_config_ready: Whether an injected safety system came from valid durable configuration.
        scheduler: StrategyScheduler instance for strategy lifecycle endpoints.
        cron: CronManager instance for cron job management endpoints.
        audit: AuditLogger instance for audit log endpoints.
        client: OpenAlgoClient instance for MCP bridge and backtest data.
        registry: BrokerRegistry for multi-broker account management.
        credential_store: CredentialStore for encrypted credential persistence.
        contract_manager: ContractManager for broker symbol contract data.
        rag: RAGPipeline instance for knowledge base queries.
        cron_strategy_scheduler: Shared market-aware strategy cron scheduler.
        time_scheduler: Shared effective-session calendar owner.

    Returns:
        Flask application with all FlintTrade API endpoints registered.
    """
    if safety is None:
        from flinttrade_engine.safety import SafetyConfig, SafetySystem  # noqa: PLC0415
        from .safety_config import load_workspace_safety_config  # noqa: PLC0415

        try:
            safety = SafetySystem(
                load_workspace_safety_config(_workspace_dir()),
                reservation_db_path=_workspace_dir() / "order_exposure_reservations.sqlite",
            )
        except Exception as exc:  # noqa: BLE001 - management UI stays up; router stays unpublished
            logger.critical(
                "Workspace safety configuration failed strict validation (%s); live routing remains disabled",
                type(exc).__name__,
            )
            safety = SafetySystem(
                SafetyConfig(check_market_hours=True),
                reservation_db_path=_workspace_dir() / "order_exposure_reservations.sqlite",
            )
            safety_config_ready = False
        else:
            safety_config_ready = True
    elif safety_config_ready is None:
        safety_config_ready = getattr(safety, "order_reservations_durable", False) is True

    # ------------------------------------------------------------------
    # Pre-init hygiene:
    #   * Clear stale DuckDB .wal files from a previous crashed process.
    #   * Log workspace.json OpenAlgo overrides when present; Settings reads
    #     those values directly and uses .env only as a fallback.
    # Both are best-effort — failures here must never prevent startup.
    # ------------------------------------------------------------------
    try:
        _cleanup_stale_duckdb_wals()
    except Exception as exc:
        logger.warning("DuckDB WAL cleanup failed (%s)", type(exc).__name__)

    try:
        _log_workspace_openalgo_overrides()
    except Exception as exc:
        logger.warning("workspace.json override failed (%s)", type(exc).__name__)

    # ------------------------------------------------------------------
    # Static frontend — serve the built React bundle from
    # packages/apps/terminal/dist/ with SPA fallback for client-side routes.
    # If the build output is missing we fall back to API-only mode and
    # log a clear warning.
    # ------------------------------------------------------------------
    # Resolve the built React bundle. Three sources, in priority order:
    #   1. ``FLINTTRADE_FRONTEND_DIST`` env override (any deployment).
    #   2. Frozen desktop build — the bundle ships ``frontend/`` alongside the
    #      packaged code (PyInstaller unpacks it under ``sys._MEIPASS``).
    #   3. Source tree — ``packages/apps/terminal/dist``.
    _dist_override = os.environ.get("FLINTTRADE_FRONTEND_DIST")
    if _dist_override:
        _dist_path = Path(_dist_override)
    elif _FROZEN and _BUNDLE_DIR:
        _dist_path = Path(_BUNDLE_DIR) / "frontend"
    else:
        _dist_path = Path(_REPO_ROOT) / "packages" / "apps" / "terminal" / "dist"
    _dist_index = _dist_path / "index.html"
    _frontend_available = _dist_index.exists()

    if _frontend_available:
        # Point Flask's built-in static_folder at the React build.  We use
        # a dedicated static_url_path (``/_static_flask``) so Flask's
        # default catch-all route does not pre-empt the SPA fallback
        # registered later — we serve all of the root-level dist files
        # (assets/, favicon.svg, index.html) through our fallback so
        # the NotFound → index.html redirect can work cleanly.
        app = Flask(
            __name__,
            static_folder=str(_dist_path),
            static_url_path="/_static_flask",
        )
    else:
        app = Flask(__name__)
        logger.warning(
            "Frontend not built — run `npm run build` in packages/apps/terminal. Backend will serve API only."
        )
    app.config["_FRONTEND_AVAILABLE"] = _frontend_available
    app.config["_DIST_PATH"] = _dist_path
    _install_runtime_request_tracking(app)
    app.config["LOG_STREAM_SHUTDOWN_EVENT"] = threading.Event()
    app.config["SIGNAL_STREAM_SHUTDOWN_EVENT"] = threading.Event()
    app.config["AUTONOMOUS_AGENT_SHUTDOWN_EVENT"] = threading.Event()
    _tick_capture_lifecycle_lock(app)

    # ------------------------------------------------------------------
    # Structured logging — ONE pipeline for both structlog calls and
    # stdlib logging calls.  Dual-emit bug (same event logged twice,
    # once pretty + once JSON) was caused by PrintLoggerFactory writing
    # to stdout *and* a bridge handler on root *also* writing to stdout.
    # Fix: route structlog through stdlib (LoggerFactory), then format
    # at the stdlib handler using ProcessorFormatter.  One event → one
    # line.
    #
    # Also disable click's ANSI colouring so Werkzeug's request log
    # doesn't embed escape codes in the log file.  Must be set BEFORE
    # werkzeug's first import triggers click initialisation.
    # ------------------------------------------------------------------
    os.environ.setdefault("ANSI_COLORS_DISABLED", "1")
    os.environ.setdefault("NO_COLOR", "1")

    _render_processor = (
        structlog.dev.ConsoleRenderer(colors=False) if app.debug else structlog.processors.JSONRenderer()
    )

    # Shared pre-chain applied to every event from either source.
    _shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
    ]

    structlog.configure(
        processors=[
            *_shared_processors,
            # Hand off to stdlib's ProcessorFormatter for the final render.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    _sentinel_attr = "_flinttrade_structlog_bridge"
    _root_logger = logging.getLogger()
    # Kill any pre-existing handler (e.g. from an earlier basicConfig call
    # or a previous create_flask_app() invocation) so we can't double-emit.
    for _h in list(_root_logger.handlers):
        _root_logger.removeHandler(_h)

    _formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            # Drop the raw LogRecord and _from_structlog meta keys before
            # rendering, otherwise JSON output leaks the absolute install
            # path (C:\Users\...\app.py, line numbers) into every event.
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            _render_processor,
        ],
        foreign_pre_chain=_shared_processors,
    )
    _handler = logging.StreamHandler()
    _handler.setFormatter(_formatter)
    setattr(_handler, _sentinel_attr, True)
    _root_logger.addHandler(_handler)
    _root_logger.setLevel(logging.INFO)

    # ------------------------------------------------------------------
    # Production-mode path rewrite (WSGI-level, runs before URL dispatch).
    # In dev, Vite strips the `/ft-api` prefix before requests reach us
    # (see packages/apps/terminal/vite.config.ts server.proxy). When the
    # backend serves the built frontend directly, no such proxy exists,
    # so the backend receives the full `/ft-api/v1/...` path while all
    # blueprints are registered under `/v1/...` or `/api/v1/...`.
    # A before_request handler runs AFTER Flask's URL match, so we wrap
    # wsgi_app instead to mutate the environ before routing.
    # ------------------------------------------------------------------
    _inner_wsgi = app.wsgi_app

    def _ft_api_prefix_stripper(environ: dict, start_response: Any) -> Any:
        raw_path = environ.get("PATH_INFO", "") or ""
        if raw_path.startswith("/ft-api/"):
            environ["PATH_INFO"] = raw_path[len("/ft-api") :]
        elif raw_path == "/ft-api":
            environ["PATH_INFO"] = "/"
        return _inner_wsgi(environ, start_response)

    app.wsgi_app = _ft_api_prefix_stripper  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Trusted forwarded-IP handling — gated behind TRUST_PROXY_HEADERS.
    # Without this, deployments behind Nginx see `request.remote_addr ==
    # 127.0.0.1` for every request, which collapses rate-limit buckets,
    # brute-force tracking, and 404 flood guards onto the loopback origin.
    # When the env flag is truthy we wrap wsgi_app with Werkzeug's ProxyFix
    # so `request.remote_addr` reflects the original client IP.
    # Default is FALSE because trusting forwarded headers from an
    # untrusted upstream would let any client spoof its source IP.
    # Mirrors the upstream OpenAlgo behaviour added in v2.0.0.7
    # (see TRUST_PROXY_HEADERS in .local/external/openalgo/utils/ip_helper.py).
    # ------------------------------------------------------------------
    if os.environ.get("TRUST_PROXY_HEADERS", "").lower() in {"1", "true", "yes", "on"}:
        try:
            from werkzeug.middleware.proxy_fix import ProxyFix  # noqa: PLC0415

            _proxy_for = int(os.environ.get("TRUST_PROXY_HEADERS_X_FOR", "1") or "1")
            _proxy_proto = int(os.environ.get("TRUST_PROXY_HEADERS_X_PROTO", "1") or "1")
            _proxy_host = int(os.environ.get("TRUST_PROXY_HEADERS_X_HOST", "0") or "0")
            _proxy_port = int(os.environ.get("TRUST_PROXY_HEADERS_X_PORT", "0") or "0")
            _proxy_prefix = int(os.environ.get("TRUST_PROXY_HEADERS_X_PREFIX", "0") or "0")
            app.wsgi_app = ProxyFix(  # type: ignore[assignment]
                app.wsgi_app,
                x_for=_proxy_for,
                x_proto=_proxy_proto,
                x_host=_proxy_host,
                x_port=_proxy_port,
                x_prefix=_proxy_prefix,
            )
            logger.info(
                "TRUST_PROXY_HEADERS active — ProxyFix: x_for=%d x_proto=%d x_host=%d x_port=%d x_prefix=%d",
                _proxy_for,
                _proxy_proto,
                _proxy_host,
                _proxy_port,
                _proxy_prefix,
            )
        except Exception as exc:  # pragma: no cover - import/config edge case
            logger.warning(
                "TRUST_PROXY_HEADERS requested but ProxyFix could not be installed (%s)",
                type(exc).__name__,
            )

    # ------------------------------------------------------------------
    # CORS — allow requests from the Vite dev server and any origins
    # configured via the CORS_ORIGINS environment variable.
    # ------------------------------------------------------------------
    CORS(
        app,
        origins=os.environ.get("CORS_ORIGINS", "http://127.0.0.1:5173").split(","),
        methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=[
            "Content-Type",
            "X-API-Key",
            "X-FlintTrade-Mode",
            "Authorization",
        ],
    )

    # ------------------------------------------------------------------
    # Rate limiting — 50 req/s default; tighter limits applied per-route
    # via @limiter.limit() on individual blueprints/views.
    # ------------------------------------------------------------------
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["50 per second"],
        storage_uri="memory://",
    )
    app.config["LIMITER"] = limiter

    # Custom token-bucket rate limiter — HTTP-layer DoS / fat-finger guard
    # (429) via ``@rate_limit``; the SEBI per-second broker-submission cap is
    # enforced below the gate by ``BrokerRouter._throttle``, which every gated
    # order traverses. Applied to the core order routes + smart-route start +
    # engine basket/split/bracket + strategy-start (orders 10/s user, 100/s
    # global; smart_orders 2/s, 20/s). Webhooks use WebhookReceiver's limiter.
    from .rate_limiter import RateLimiter as _RateLimiter  # noqa: PLC0415

    _rate_limiter = _RateLimiter(global_rate=100, per_user_rate=10)
    _rate_limiter.set_limit("orders", user_rate=10, global_rate=100)
    _rate_limiter.set_limit("smart_orders", user_rate=2, global_rate=20)
    _rate_limiter.set_limit("webhook", user_rate=5, global_rate=50)
    app.config["RATE_LIMITER"] = _rate_limiter

    # ------------------------------------------------------------------
    # Error tracking — Sentry SDK pointing at a Glitchtip instance (MIT).
    # Only initialised when GLITCHTIP_DSN is set in the environment; safe
    # to leave unset in development.
    # ------------------------------------------------------------------
    _glitchtip_dsn = os.environ.get("GLITCHTIP_DSN", "")
    if _glitchtip_dsn:
        sentry_sdk.init(
            dsn=_glitchtip_dsn,
            integrations=[FlaskIntegration()],
            traces_sample_rate=0.1,
            environment="production" if not app.debug else "development",
        )
        logger.info("Glitchtip error tracking initialised")

    # Store injected instances on app.config so endpoint closures can access them
    app.config["SAFETY"] = safety
    app.config["SAFETY_CONFIG_READY"] = safety_config_ready is True
    app.config["SCHEDULER"] = scheduler
    app.config["CRON"] = cron
    app.config["AUDIT"] = audit
    app.config["CLIENT"] = client
    # Read-only OpenAlgo consumers must remain available even when this process
    # has no emergency runtime and live BrokerRouter publication fails closed.
    app.config["OPENALGO_CLIENT"] = client

    # --- Gateway initialization ---
    if registry is None:
        registry = BrokerRegistry()

    # Ensure API_KEY_PEPPER is set in os.environ BEFORE the OpenAlgo
    # broker modules are imported via the gateway shim. Upstream's
    # ``utils.config.API_KEY_PEPPER`` is captured at import time, so a
    # later os.environ tweak is too late.
    _get_api_key_pepper()

    # Bind the dedicated safety-gate HMAC secret (contract §8.0b) BEFORE the
    # broker router is built and before any SafetyContext can be minted/verified.
    # Without it gate_order() fails closed and every live routed order would 403.
    from flinttrade_engine.safety import set_safety_gate_secret  # noqa: PLC0415

    set_safety_gate_secret(_get_safety_gate_secret_bytes())

    # Emergency writes use a FULL-sync SQLite write-ahead journal. A concrete
    # mutation is reserved here before any broker call and remains unresolved
    # across process restarts until authoritative broker readback is quiet.
    from flinttrade_engine.emergency_intents import (  # noqa: PLC0415
        EmergencyDispatchIntentJournal,
        EmergencyIntentJournal,
    )

    emergency_journal = EmergencyIntentJournal(_workspace_dir() / "emergency_intents.sqlite")
    try:
        emergency_journal.healthcheck()
        bind_emergency_journal = getattr(safety, "bind_emergency_journal", None)
        if not callable(bind_emergency_journal):
            raise RuntimeError("SafetySystem has no durable emergency-journal binding")
        bind_emergency_journal(emergency_journal)
    except Exception as exc:  # noqa: BLE001 - app stays up but live routing remains disabled
        app.config["EMERGENCY_INTENT_JOURNAL"] = None
        app.config["EMERGENCY_INTENT_JOURNAL_READY"] = False
        logger.critical(
            "Emergency intent journal failed startup validation (%s); live routing remains disabled",
            type(exc).__name__,
        )
    else:
        app.config["EMERGENCY_INTENT_JOURNAL"] = emergency_journal
        app.config["EMERGENCY_INTENT_JOURNAL_READY"] = True
        # ONE process-wide degrading wrapper shared by every emergency
        # dispatcher (runtime singleton + per-request HTTP activations): the
        # process-local fallback keeps replay/acknowledgement continuity
        # across activations during a durable-storage outage. Latch reset
        # stays bound to the raw durable journal above.
        app.config["EMERGENCY_INTENT_JOURNAL_WRAPPER"] = EmergencyDispatchIntentJournal(emergency_journal)

    # Layer 4 freezes each execution selector's opening capital and latches its
    # daily-loss state in a separate FULL-sync store. Live routing is withheld
    # if this store cannot be checked or bound; an in-memory fallback would let
    # a restart clear a hard stop.
    from flinttrade_engine.daily_pnl_state import DailyPnLStateStore  # noqa: PLC0415

    try:
        daily_pnl_state_store = DailyPnLStateStore(_workspace_dir() / "daily_pnl_state.sqlite")
        daily_pnl_state_store.healthcheck()
        bind_daily_pnl_state = getattr(safety, "bind_daily_pnl_state_store", None)
        if not callable(bind_daily_pnl_state):
            raise RuntimeError("SafetySystem has no durable daily-P&L state binding")
        bind_daily_pnl_state(daily_pnl_state_store)
    except Exception as exc:  # noqa: BLE001 - app stays up but live routing remains disabled
        app.config["DAILY_PNL_STATE_STORE"] = None
        app.config["DAILY_PNL_STATE_READY"] = False
        logger.critical(
            "Daily P&L state failed startup validation (%s); live routing remains disabled",
            type(exc).__name__,
        )
    else:
        app.config["DAILY_PNL_STATE_STORE"] = daily_pnl_state_store
        app.config["DAILY_PNL_STATE_READY"] = True

    if credential_store is None:
        flinttrade_dir = _workspace_dir()
        master_password = _get_master_password()
        credential_store = CredentialStore(flinttrade_dir / "credentials.db", master_password)

    if contract_manager is None:
        flinttrade_dir = _workspace_dir()
        contracts_dir = flinttrade_dir / "contracts"
        contracts_dir.mkdir(exist_ok=True)
        contract_manager = ContractManager(contracts_dir)

    app.config["REGISTRY"] = registry
    app.config["CREDENTIAL_STORE"] = credential_store
    app.config["CONTRACT_MANAGER"] = contract_manager
    app.config["OAUTH_STATES"] = {}

    # Desired smart-routing settings are configuration, not proof that a live
    # router generation exists. Routes still require BROKER_ROUTER before they
    # can start a job, but read-only WSGI construction must expose the operator's
    # settings instead of silently replacing them with an empty mapping.
    try:
        from .workspace_migrations import default_workspace_config  # noqa: PLC0415

        desired_brokers = _read_workspace_brokers()
        effective_brokers = desired_brokers or default_workspace_config()["brokers"]
        app.config["SMART_ROUTING"] = dict(effective_brokers.get("smart_routing") or {})
    except Exception as exc:  # noqa: BLE001 - malformed settings remain disabled
        app.config["SMART_ROUTING"] = {}
        logger.warning("Smart-routing settings unavailable (%s); feature remains disabled", type(exc).__name__)

    # Ditto multi-account api_keys live in a Ditto-scoped vault (the canonical
    # CredentialStore crypto: per-row salt + PBKDF2 from the master password),
    # NOT the shared native store — whose boot reconnect would otherwise try to
    # authenticate each ditto:openalgo row as a bridge session. Optional: a
    # missing vault must never block startup (Ditto routes 503 without it).
    try:
        app.config["DITTO_CREDENTIAL_STORE"] = CredentialStore(
            _workspace_dir() / "ditto_credentials.db", _get_master_password()
        )
    except Exception as exc:  # noqa: BLE001 - Ditto is optional
        logger.warning("Ditto credential vault unavailable (%s)", type(exc).__name__)
        app.config["DITTO_CREDENTIAL_STORE"] = None
    _configure_ditto_runtime(app, safety)

    # --- Broker router (selector-bound principal; contract §13 / §11.4) ---
    # Best-effort like the other startup steps: a malformed brokers block must
    # NOT brick the app — the operator needs the UI up to fix it. On failure we
    # log loudly and leave BROKER_ROUTER as None so the gated order path returns
    # a clear 503 rather than dispatching. A successfully-parsed config is
    # snapshotted to workspace.brokers.bak.json for operator rollback (§13.3).
    # The dispatcher is bound before publication. For the standalone runtime,
    # ``SafetySystem`` already owns its running loop; desktop binds and rebuilds
    # immediately after its owner loop starts. Bare WSGI construction remains
    # read-only because it has no process-owned emergency runtime.
    if client is not None and callable(getattr(client, "run_sync", None)):
        try:
            _bind_runtime_emergency_dispatcher(app, safety, None, client)
        except Exception as exc:  # noqa: BLE001 - configure below remains fail-closed
            app.config["EMERGENCY_RUNTIME_READY"] = False
            app.config.pop("EMERGENCY_DISPATCHER", None)
            logger.critical(
                "Emergency dispatcher failed startup binding (%s); live routing remains disabled",
                type(exc).__name__,
            )
    configure_broker_router(app, registry, credential_store, client)
    # Re-establish native sessions for any selector whose credentials are
    # already in the vault (a restart after the operator connected a broker
    # earlier). First boot with an empty vault is a no-op. Best-effort — a
    # broker whose token expired overnight is marked as needing re-login while
    # transient service-window/network failures keep the session.
    _reestablish_native_sessions(app, verify=True)

    # Store RAG instance
    app.config["RAG"] = rag
    app.config["RAG_STATUS"] = (
        "ready" if rag is not None else "disabled" if not _rag_runtime_enabled() else "unavailable"
    )
    # Optional zero-argument callable returning a non-empty market-data mapping.
    # The sentiment route degrades to RSS when no provider is installed.
    app.config["MARKET_SENTIMENT_DATA_PROVIDER"] = None

    # Register gateway blueprint (mounts at /v1/)
    app.register_blueprint(gateway_bp)

    # G9 — broker-management write guard: every POST/PUT/DELETE on the gateway
    # blueprint (accounts, credential capture, OAuth start, rate-limit config)
    # must carry a valid operator session JWT. The gateway package cannot
    # import core's JWT machinery, so the guard is injected here.
    from .auth_routes import require_operator_session  # noqa: PLC0415

    app.config["BROKER_MGMT_WRITE_GUARD"] = require_operator_session

    # Native broker account capture + activation (Phase 1 G4) — /api/v1/native/*
    from .native_account_routes import native_accounts_bp  # noqa: PLC0415

    app.register_blueprint(native_accounts_bp)

    # Daily broker session refresh (Phase 1 G5) — rotator + 08:05 IST jobs +
    # /admin/credentials/rotation/* admin routes. The scheduler is created
    # unstarted; _run_flask_server starts it on the serve path only.
    from .native_rotation import configure_session_rotation  # noqa: PLC0415

    rotation_bp = configure_session_rotation(app)
    if rotation_bp is not None:
        app.register_blueprint(rotation_bp)

    # Register analysis blueprint (/api/v1/gex, /api/v1/volsurface, etc.)
    from flinttrade_screener.analysis_routes import analysis_bp  # noqa: PLC0415

    app.register_blueprint(analysis_bp)

    # Register sample-data placeholder blueprint — eight endpoints whose real
    # implementations are not yet built. Each returns is_sample_data=true so
    # widgets show their "Demo" badge instead of 404-ing. See
    # packages/services/screener/src/sample_data_routes.py.
    from flinttrade_screener.sample_data_routes import sample_data_bp  # noqa: PLC0415

    app.register_blueprint(sample_data_bp)

    # Register stock screener blueprint (/v1/stocks/*)
    from flinttrade_screener.stock_routes import stock_bp  # noqa: PLC0415

    app.register_blueprint(stock_bp)

    # Register market scanner blueprint (/v1/scanner/* — external: /ft-api/v1/scanner/*)
    from flinttrade_screener.scanner_routes import scanner_bp  # noqa: PLC0415

    app.register_blueprint(scanner_bp)

    # Register OI analytics blueprint (/v1/oi/* — external: /ft-api/v1/oi/*)
    from flinttrade_screener.oi_analytics_routes import oi_analytics_bp  # noqa: PLC0415

    app.register_blueprint(oi_analytics_bp)

    # Register Mutual Fund NAV blueprint (/api/v1/mf/search, /mf/nav, /mf/categories)
    from flinttrade_screener.mf_routes import mf_bp  # noqa: PLC0415

    app.register_blueprint(mf_bp)

    # Register breadth + volatility cone blueprints (/v1/breadth/*, /v1/analytics/volcone — external: /ft-api/v1/*)
    from flinttrade_screener.breadth_routes import breadth_bp  # noqa: PLC0415

    app.register_blueprint(breadth_bp)

    # Register Action Center blueprint (/api/v1/action-center/*)
    from flinttrade_engine.action_center import PendingOrderQueue  # noqa: PLC0415
    from flinttrade_engine.action_center_routes import action_center_bp  # noqa: PLC0415

    from .agent_routes import (  # noqa: PLC0415
        authorise_action_center_request,
        dispatch_action_center_approval,
    )

    pending_order_queue = PendingOrderQueue(
        _workspace_dir() / "action_center.duckdb"
    )
    app.config["PENDING_ORDER_QUEUE"] = pending_order_queue
    app.config["ACTION_CENTER_AUTHORISER"] = authorise_action_center_request
    app.config["ACTION_CENTER_APPROVAL_DISPATCHER"] = dispatch_action_center_approval
    app.register_blueprint(action_center_bp)

    # Register Security blueprint and middleware (/api/v1/security/*)
    from .security import SecurityMonitor  # noqa: PLC0415
    from .security_routes import register_security_middleware, security_bp  # noqa: PLC0415

    security_monitor = SecurityMonitor()
    app.config["SECURITY_MONITOR"] = security_monitor
    app.register_blueprint(security_bp)
    register_security_middleware(app, security_monitor)

    # Register persistent SecurityTracker (DuckDB-backed 404/IP-ban log)
    from flinttrade_data.security_tracker import SecurityTracker as _SecurityTracker  # noqa: PLC0415

    _security_db = _workspace_dir() / "security.db"
    app.config["SECURITY_TRACKER"] = _SecurityTracker(str(_security_db))

    # Register LoginActivity + SessionTracker (DuckDB-backed)
    from flinttrade_data.activity_log import LoginActivity as _LoginActivity  # noqa: PLC0415
    from flinttrade_data.activity_log import SessionTracker as _SessionTracker  # noqa: PLC0415

    _login_db = _workspace_dir() / "activity.db"
    app.config["LOGIN_ACTIVITY"] = _LoginActivity(str(_login_db))
    app.config["SESSION_TRACKER"] = _SessionTracker(str(_login_db))

    # Shared trade-journal store (DuckDB). The gated order dispatch writes every
    # executed live order here and the /trades/journal route reads the SAME
    # store, so the journal + P&L analytics populate in Live (previously the
    # producer was missing → permanently empty journal). One shared, pre-
    # initialised connection keeps the per-order cost to a single INSERT (latency
    # is paramount). A lock serialises the writer against the route's reads —
    # DuckDB connections are not safe for concurrent use. Best-effort: a storage
    # failure degrades to "no journalling", never blocks boot.
    try:
        from flinttrade_data.storage import StorageManager as _TradeStore  # noqa: PLC0415

        _trade_storage = _TradeStore()
        _trade_storage.initialise()
        app.config["TRADE_STORAGE"] = _trade_storage
        app.config["TRADE_STORAGE_LOCK"] = threading.Lock()
    except Exception:  # pragma: no cover — defensive: never let storage break boot
        logger.warning(
            "Trade journal storage unavailable; live trades will not be journalled",
            exc_info=True,
        )
        app.config["TRADE_STORAGE"] = None
        app.config["TRADE_STORAGE_LOCK"] = None

    # Annotated Trade Journal (SQLite + FTS5, own journal.sqlite). Distinct from
    # the TRADE_STORAGE execution records above: this holds the operator's notes,
    # emotions, quality scores, and tags with full-text search. Best-effort — a
    # storage failure degrades to "journal unavailable" (503s), never blocks boot.
    try:
        from flinttrade_journal.journal_routes import init_journal_routes, journal_bp  # noqa: PLC0415
        from flinttrade_journal.trade_journal import TradeJournal  # noqa: PLC0415

        _journal = TradeJournal()
        _journal.initialise()
        app.config["JOURNAL"] = _journal
        init_journal_routes(_journal)
        app.register_blueprint(journal_bp)
    except Exception:  # pragma: no cover — defensive: never let the journal break boot
        logger.warning("Trade journal unavailable; /api/v1/journal returns 503", exc_info=True)
        app.config["JOURNAL"] = None

    # Register Order Flow blueprint (synthetic footprint data)
    from flinttrade_data.orderflow_routes import orderflow_bp  # noqa: PLC0415

    app.register_blueprint(orderflow_bp)

    # Register Tick Capture blueprint (/api/v1/data/ticks/*) — status, recorded
    # tick queries and runtime watchlist management for the opt-in recorder.
    from flinttrade_data.tick_routes import ticks_bp  # noqa: PLC0415

    app.register_blueprint(ticks_bp)

    # Register Tax Report blueprint (/v1/tax/*)
    from flinttrade_data.tax_routes import tax_bp  # noqa: PLC0415

    app.register_blueprint(tax_bp)

    # Register Historify watchlist blueprint
    from flinttrade_historical.watchlist_routes import historify_bp  # noqa: PLC0415

    app.register_blueprint(historify_bp)

    # Register TradingView signals blueprint (/v1/tv/*)
    from flinttrade_screener.tv_routes import tv_bp  # noqa: PLC0415

    app.register_blueprint(tv_bp)

    # Register monitoring blueprint (/api/v1/traffic/*, /api/v1/latency/*).
    # Aggregated /api/v1/health lives in health_bp (the canonical health surface).
    from .monitoring_routes import monitoring_bp  # noqa: PLC0415

    app.register_blueprint(monitoring_bp)

    # Register frontend error ingestion + changelog reader (/v1/errors, /v1/changelog
    # — external URLs: /ft-api/v1/errors, /ft-api/v1/changelog). Previously referenced
    # by the terminal but not wired, causing 404s on fire-and-forget error reports.
    # Initialise the persistent error log ONCE (always active — not gated by
    # dev mode). The try/except guard means a DuckDB failure degrades to
    # warning-only logging rather than crashing startup. The same instance is
    # stored on app.config (so admin_routes and frontend_errors_bp can reach
    # it) and reused by the global error handler below.
    from .error_log import ErrorLog as _ErrorLog  # noqa: PLC0415
    from .frontend_error_routes import frontend_errors_bp  # noqa: PLC0415

    _error_db = _workspace_dir() / "error_log.duckdb"
    try:
        _error_log = _ErrorLog(db_path=str(_error_db))
    except Exception as exc:
        logger.warning(
            "ErrorLog initialisation failed (%s); /v1/errors will log warnings only",
            type(exc).__name__,
        )
        _error_log = None
    app.config["ERROR_LOG"] = _error_log
    app.register_blueprint(frontend_errors_bp)

    # Operator-controlled diagnostics for Settings -> Report Bug. The route
    # exposes only aggregated, scope-protected metadata from the shared error
    # log; it never returns raw request bodies, messages or tracebacks.
    from .support_routes import support_bp  # noqa: PLC0415

    app.register_blueprint(support_bp)

    # Register Strategy Runner blueprint (/api/v1/strategies/*)
    from flinttrade_engine.strategy_routes import strategy_bp  # noqa: PLC0415

    app.register_blueprint(strategy_bp)

    # Wire the Strategy Runner + Cron scheduler the strategy routes require so
    # upload/start/stop/logs/schedule work in production — without these config
    # keys every /api/v1/strategies write returned 503 "Strategy runner not
    # configured" (feature audit H1/M13). Construction is side-effect-light: the
    # runner only creates its own dirs, and CronStrategyScheduler does not start
    # APScheduler until .start() is called.
    if "STRATEGY_RUNNER" not in app.config:
        try:
            from flinttrade_engine.strategy_runner import UserStrategyRunner  # noqa: PLC0415

            app.config["STRATEGY_RUNNER"] = UserStrategyRunner(_workspace_dir() / "strategies")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Strategy runner wiring failed (%s); /strategies writes will 503",
                type(exc).__name__,
            )
    resolved_time_scheduler = time_scheduler
    if cron_strategy_scheduler is not None:
        resolved_time_scheduler = getattr(cron_strategy_scheduler, "time_scheduler", None) or resolved_time_scheduler
    if resolved_time_scheduler is None:
        try:
            from flinttrade_engine.scheduler import TimeScheduler  # noqa: PLC0415

            resolved_time_scheduler = TimeScheduler(client=client)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Time scheduler wiring failed (%s); market-aware work will 503",
                type(exc).__name__,
            )
    if "CRON_SCHEDULER" not in app.config:
        try:
            from flinttrade_engine.scheduler import CronStrategyScheduler  # noqa: PLC0415

            app.config["CRON_SCHEDULER"] = (
                cron_strategy_scheduler
                if cron_strategy_scheduler is not None
                else CronStrategyScheduler(time_scheduler=resolved_time_scheduler)
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Cron scheduler wiring failed (%s); strategy scheduling will 503",
                type(exc).__name__,
            )
    if resolved_time_scheduler is None:
        resolved_time_scheduler = getattr(
            app.config.get("CRON_SCHEDULER"),
            "time_scheduler",
            None,
        )
    app.config["TIME_SCHEDULER"] = resolved_time_scheduler

    # Execution-quality analytics (POST /api/v1/analytics/execution) and strategy
    # comparison (POST /api/v1/backtest/compare) — both fully built + tested but were
    # never registered (404 in production; feature audit H6/M2). Their blueprints
    # carry no prefix, so register under /api/v1 to match the frontend convention.
    from flinttrade_journal.order_analytics import order_analytics_bp  # noqa: PLC0415

    app.register_blueprint(order_analytics_bp, url_prefix="/api/v1")
    from flinttrade_backtest.strategy_comparison import strategy_comparison_bp  # noqa: PLC0415

    app.register_blueprint(strategy_comparison_bp, url_prefix="/api/v1")

    # Register the sole Practice sandbox blueprint (/v1/sandbox/*).
    from flinttrade_data.sandbox_routes import data_sandbox_bp  # noqa: PLC0415
    from flinttrade_data.sandbox_engine import SandboxEngine as _DataSandboxEngine  # noqa: PLC0415

    app.config["DATA_SANDBOX_ENGINE"] = _DataSandboxEngine()
    app.register_blueprint(data_sandbox_bp)

    # ------------------------------------------------------------------
    # Global unhandled-exception handler — persists errors to DuckDB
    # before re-raising so Flask's default 500 handler takes over.
    # ------------------------------------------------------------------
    @app.errorhandler(Exception)
    def _log_unhandled_exception(exc: Exception) -> Any:
        """Persist every unhandled exception to the structured error log.

        Werkzeug ``HTTPException`` instances (404, 405, 415, …) are not
        real errors — they represent deliberately returned HTTP status
        codes and must be passed straight through with their own payload,
        otherwise a simple 404 bubbles up as a misleading 500.  Real
        exceptions are logged and converted to a plain HTTP 500 JSON
        response so we never leak internal tracebacks to clients.
        """
        from werkzeug.exceptions import HTTPException  # noqa: PLC0415

        if isinstance(exc, HTTPException):
            return exc  # Flask will render the HTTPException normally.

        try:
            if _error_log is not None:
                _error_log.log(
                    route=request.path,
                    method=request.method,
                    status_code=500,
                    request_body=request.get_json(silent=True, force=True),
                    error=exc,
                    user_id=None,  # user context not available at this layer
                )
        except Exception:
            # Never let the error logger itself crash the request.
            pass
        return jsonify({"status": "error", "message": "Internal server error"}), 500

    # Initialise TrafficLogger (DuckDB-backed, always active).
    # @before_request / @after_request hooks record every HTTP request.
    from .traffic_logger import TrafficLogger as _TrafficLogger, should_skip_path as _skip_path  # noqa: PLC0415

    _traffic_log_path = _workspace_dir() / "traffic_log.duckdb"
    _traffic_logger = _TrafficLogger(_traffic_log_path)
    app.config["TRAFFIC_LOGGER"] = _traffic_logger

    @app.before_request
    def _traffic_start() -> None:
        """Record the request start time for traffic duration measurement."""
        import time as _time  # noqa: PLC0415

        _flask_g._traffic_start = _time.monotonic()

    @app.after_request
    def _traffic_log(response: Any) -> Any:
        """Persist request details to TrafficLogger after each response."""
        try:
            if not _skip_path(request.path):
                import time as _time  # noqa: PLC0415

                start = getattr(_flask_g, "_traffic_start", None)
                duration_ms = (_time.monotonic() - start) * 1000 if start is not None else 0.0
                _traffic_logger.log(
                    ip=request.remote_addr or "unknown",
                    method=request.method,
                    path=request.path,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                    user_agent=request.headers.get("User-Agent"),
                    request_size=request.content_length,
                    response_size=response.content_length,
                )
        except Exception as _exc:
            logger.debug("suppressed: %s", _exc)  # Never let traffic logging break the response
        return response

    # Initialise LatencyMonitor (DuckDB-backed, always active).
    # The order router wraps this via monitoring_routes.get_latency_tracker()
    # for in-memory stats; this provides persistent DuckDB-backed storage.
    from flinttrade_engine.latency_monitor import LatencyMonitor as _LatencyMonitor  # noqa: PLC0415

    _latency_log_path = _workspace_dir() / "latency_log.duckdb"
    _latency_monitor = _LatencyMonitor(_latency_log_path)
    app.config["LATENCY_MONITOR"] = _latency_monitor

    # Initialise APIAnalyzer (DuckDB-backed, opt-in via ENABLE_ANALYZER=true).
    _analyzer_enabled = os.environ.get("ENABLE_ANALYZER", "").lower() in ("1", "true", "yes")
    if _analyzer_enabled:
        from .api_analyzer import APIAnalyzer as _APIAnalyzer  # noqa: PLC0415

        _analyzer_path = _workspace_dir() / "api_analyzer.duckdb"
        _api_analyzer = _APIAnalyzer(_analyzer_path)
        app.config["API_ANALYZER"] = _api_analyzer

        @app.after_request
        def _analyzer_log(response: Any) -> Any:
            """Persist full request + response to APIAnalyzer when enabled."""
            try:
                import time as _time  # noqa: PLC0415

                start = getattr(_flask_g, "_traffic_start", None)
                duration_ms = (_time.monotonic() - start) * 1000 if start is not None else 0.0
                _api_analyzer.log_call(
                    route=request.path,
                    method=request.method,
                    request_body=request.get_json(silent=True, force=True),
                    response_status=response.status_code,
                    response_body=None,  # Not parsing response body to avoid re-reading stream
                    duration_ms=duration_ms,
                )
            except Exception as _exc:
                logger.debug("suppressed: %s", _exc)
            return response

        logger.info("API Analyser enabled — capturing all requests")

    # Initialise module-level EventBus singleton.
    from .event_bus import bus as _event_bus  # noqa: PLC0415

    app.config["EVENT_BUS"] = _event_bus
    logger.info("EventBus initialised")

    # Register admin blueprint (dev/debug only)
    if app.debug or os.environ.get("FLINTTRADE_DEV"):
        from .admin_routes import admin_bp  # noqa: PLC0415

        app.register_blueprint(admin_bp)
        # Register infrastructure admin routes (traffic/latency/analyzer)
        from .infra_routes import infra_bp  # noqa: PLC0415

        app.register_blueprint(infra_bp)
        # Workspace backup/restore admin routes (/admin/backup/*)
        from .backup_routes import create_backup_blueprint  # noqa: PLC0415

        app.register_blueprint(create_backup_blueprint(workspace_dir=_workspace_dir()))
        # Runtime analyser toggle + retention clear (/v1/admin/analyzer/
        # {enable,disable,status,clear}) — the write-side companion to
        # infra_bp's read-only /v1/admin/analyzer/{calls,replay} above. Only
        # meaningful when ENABLE_ANALYZER created the capture hook + instance.
        _api_analyzer_instance = app.config.get("API_ANALYZER")
        if _api_analyzer_instance is not None:
            from .analyzer_admin_routes import create_analyzer_admin_blueprint  # noqa: PLC0415

            app.register_blueprint(
                create_analyzer_admin_blueprint(_api_analyzer_instance),
                url_prefix="/v1",
            )
        # Per-user rate-limit override management (/v1/admin/rate-limits/
        # overrides) over the shared token-bucket RateLimiter consulted by
        # @rate_limit on the order routes. Mounted under /v1 so the whole
        # dev-mode admin surface stays in ONE prefix family (/v1/admin/*).
        _rate_limiter_instance = app.config.get("RATE_LIMITER")
        if _rate_limiter_instance is not None:
            from .rate_limit_admin_routes import create_rate_limit_admin_blueprint  # noqa: PLC0415

            app.register_blueprint(
                create_rate_limit_admin_blueprint(_rate_limiter_instance),
                url_prefix="/v1",
            )
        logger.info("Admin endpoints registered (dev mode)")

    # Register Activity Log blueprint (/api/v1/admin/activity)
    # Always registered — audit access is not restricted to dev mode.
    from flinttrade_data.activity_routes import activity_bp  # noqa: PLC0415

    _activity_db = _workspace_dir() / "activity.db"
    from flinttrade_data.activity_log import ActivityLog as _ActivityLog  # noqa: PLC0415

    app.config["ACTIVITY_LOG"] = _ActivityLog(str(_activity_db))
    app.register_blueprint(activity_bp)
    logger.info("Activity log endpoint registered at /api/v1/admin/activity")

    # Register extracted inline-route blueprints
    from .indicators_routes import indicators_bp  # noqa: PLC0415

    app.register_blueprint(indicators_bp)

    from flinttrade_ai.advisor_routes import advisor_bp  # noqa: PLC0415

    app.register_blueprint(advisor_bp)

    from flinttrade_ai.ai_routes import ai_bp  # noqa: PLC0415

    app.register_blueprint(ai_bp)

    from flinttrade_ai.obsidian_routes import obsidian_bp  # noqa: PLC0415

    app.register_blueprint(obsidian_bp)

    from flinttrade_ai.signal_routes import (  # noqa: PLC0415
        configure_signal_sources,
        signal_bp,
    )

    app.register_blueprint(signal_bp)
    configure_signal_sources(app, client)

    from .backtest_routes import backtest_bp  # noqa: PLC0415

    app.register_blueprint(backtest_bp)

    from .operations_routes import operations_bp  # noqa: PLC0415

    app.register_blueprint(operations_bp)

    # Register Order proxy blueprint (/v1/orders/*) — CRITICAL SAFETY LAYER.
    # All order requests from the frontend must pass through here so that
    # mode enforcement (explore/practice/live) is applied before any
    # real-money order reaches OpenAlgo.
    from .order_routes import orders_bp  # noqa: PLC0415

    app.register_blueprint(orders_bp)

    # Register smart-order routing blueprint (/api/v1/orders/smart-route).
    # OFF by default (workspace brokers.smart_routing.enabled); every child
    # order still traverses the full gated path via GatedChildExecutor.
    from .smart_order_routes import smart_order_bp  # noqa: PLC0415

    app.register_blueprint(smart_order_bp)

    # Register the autonomous-agent control plane (/api/v1/ai/agent/*).
    # OFF by default (workspace ai.autonomous_agent.enabled); the agent runs
    # as its own ACL'd principal and orders only via GatedChildExecutor.
    from .agent_routes import agent_bp  # noqa: PLC0415

    app.register_blueprint(agent_bp)

    # Managed local inference runtime. Installation and model pulls are always
    # explicit; app construction only publishes the localhost control plane.
    from .local_ai_routes import local_ai_bp  # noqa: PLC0415
    from .ollama_runtime import OllamaRuntime, OllamaRuntimeError  # noqa: PLC0415

    try:
        app.config["OLLAMA_RUNTIME"] = OllamaRuntime(_workspace_dir())
    except OllamaRuntimeError as exc:
        app.config["OLLAMA_RUNTIME_ERROR"] = str(exc)
        logger.warning("Managed Ollama runtime unavailable (%s)", type(exc).__name__)
    app.register_blueprint(local_ai_bp)

    # Register AI Team blueprint (/api/v1/ai/team/*)
    from flinttrade_ai.team_routes import team_bp  # noqa: PLC0415

    app.register_blueprint(team_bp)

    # Register Fundamental Screener blueprint (/api/v1/fundamentals/*)
    from flinttrade_screener.fundamental_routes import fundamental_bp  # noqa: PLC0415

    app.register_blueprint(fundamental_bp)

    # Register IPO Tracker blueprint (/api/v1/ipo/*)
    from flinttrade_screener.ipo_routes import ipo_bp  # noqa: PLC0415

    app.register_blueprint(ipo_bp)

    # Register Earnings Calendar blueprint (/api/v1/earnings/* — external:
    # /ft-api/api/v1/earnings/*). Prefix flipped 2026-05-19 (was /v1/) so the
    # frontend's ftApi.helpers /api/v1 path lines up with the registered route.
    from flinttrade_screener.earnings_routes import earnings_bp  # noqa: PLC0415

    app.register_blueprint(earnings_bp)

    # Register Pivot Calculator blueprint (/v1/pivots/* — external: /ft-api/v1/pivots/*)
    from flinttrade_screener.pivot_routes import pivot_bp  # noqa: PLC0415

    app.register_blueprint(pivot_bp)

    # Register Economic Calendar blueprint (/v1/economic/* — external: /ft-api/v1/economic/*)
    from flinttrade_screener.economic_routes import economic_bp  # noqa: PLC0415

    app.register_blueprint(economic_bp)

    # Register Audit Trail blueprint (/v1/audit/* — external: /ft-api/v1/audit/*)
    from flinttrade_data.audit_routes import audit_bp  # noqa: PLC0415

    app.register_blueprint(audit_bp)

    # Register Analytics extensions blueprint (/v1/indicators/vwap, /v1/analytics/pairs,
    # /v1/analytics/mtf — external: /ft-api/v1/indicators/*, /ft-api/v1/analytics/*)
    from flinttrade_screener.analytics_routes import analytics_bp  # noqa: PLC0415

    app.register_blueprint(analytics_bp)

    # Register WhatsApp Alerts blueprint (/api/v1/alerts/whatsapp/*)
    from flinttrade_automation.whatsapp_routes import whatsapp_bp  # noqa: PLC0415

    app.register_blueprint(whatsapp_bp)

    # Register Telegram Alerts blueprint (/api/v1/telegram)
    from .telegram_routes import telegram_bp  # noqa: PLC0415

    app.register_blueprint(telegram_bp)

    # Register Historical Expiry Tracker blueprint (/api/v1/historical/*)
    from flinttrade_historical.expiry_tracker_routes import expiry_tracker_bp  # noqa: PLC0415

    app.register_blueprint(expiry_tracker_bp)

    # Register Holidays + Market Timings blueprint (/api/v1/holidays, /api/v1/market/timings)
    from flinttrade_historical.holidays_routes import holidays_bp  # noqa: PLC0415

    app.register_blueprint(holidays_bp)

    # Register Intervals blueprint (/api/v1/intervals)
    from flinttrade_historical.intervals_routes import intervals_bp  # noqa: PLC0415

    app.register_blueprint(intervals_bp)

    # Register Local Data Store blueprint (/v1/historify/bars*, bhavcopy download)
    # — browse locally-downloaded OHLCV and fetch full-market NSE bhavcopies.
    from flinttrade_historical.local_data_routes import local_data_bp  # noqa: PLC0415

    app.register_blueprint(local_data_bp)

    # Register Instruments blueprint (/api/v1/instruments)
    from flinttrade_historical.instruments_routes import instruments_bp  # noqa: PLC0415

    app.register_blueprint(instruments_bp)

    # Register Symbol Search blueprint (/api/v1/search)
    from flinttrade_historical.search_routes import search_bp  # noqa: PLC0415

    app.register_blueprint(search_bp)

    # Register Broker Capabilities blueprint (/api/v1/broker/capabilities)
    from flinttrade_gateway.capabilities_routes import capabilities_bp  # noqa: PLC0415

    app.register_blueprint(capabilities_bp)

    # Register Leverage / Margin blueprint (/api/v1/leverage/margin/current)
    from flinttrade_engine.leverage_routes import leverage_bp  # noqa: PLC0415

    app.register_blueprint(leverage_bp)

    # Register Chart Preferences blueprint (/api/v1/chart)
    from .chart_prefs_routes import chart_prefs_bp  # noqa: PLC0415

    app.register_blueprint(chart_prefs_bp)

    # Register Bracket Order blueprint (/api/v1/orders/bracket*) and construct
    # the service it delegates to. Every bracket leg WRITE traverses the same
    # gated chain as a human /place order — SafetySystem L1-L5 -> gate_order
    # (one-shot HMAC SafetyContext) -> BrokerRouter -> adapter — through the
    # injected dispatchers; the service never holds a raw broker/OpenAlgo
    # client for writes (gateway/tests/test_no_legacy_order_path.py pins it).
    # Practice-mode JWTs are refused 403 practice_unsupported at the route
    # boundary (mode_guard.require_live_unlocked): the sandbox cannot execute
    # multi-leg brackets, so an honest refusal beats a silent live order.
    from flinttrade_engine.bracket_order import (  # noqa: PLC0415
        BracketOrderService,
        build_gated_leg_dispatchers,
    )
    from flinttrade_engine.bracket_routes import bracket_bp  # noqa: PLC0415

    _bracket_place_leg, _bracket_cancel_leg = build_gated_leg_dispatchers(app)
    app.config["BRACKET_SERVICE"] = BracketOrderService(
        place_leg=_bracket_place_leg,
        cancel_leg=_bracket_cancel_leg,
    )
    app.register_blueprint(bracket_bp)

    # Wire the advanced-order executors (basket / split) that back the engine
    # order_bp routes (/api/v1/orders/{basket,split,options-strategy}). Each
    # routes every leg/chunk through the SAME gated dispatcher as a bracket leg
    # (build_gated_leg_dispatchers -> gate_order -> BrokerRouter), so they hold
    # no broker client and no ungated path exists. Pinned by
    # test_executors_stay_gated and gateway/tests/test_no_legacy_order_path.py.
    from flinttrade_engine.basket_orders import BasketOrderExecutor  # noqa: PLC0415
    from flinttrade_engine.split_orders import SplitOrderExecutor  # noqa: PLC0415

    app.config["BASKET_EXECUTOR"] = BasketOrderExecutor(place_leg=_bracket_place_leg)
    app.config["SPLIT_EXECUTOR"] = SplitOrderExecutor(place_leg=_bracket_place_leg)

    # Register Position Sizer blueprint (/api/v1/position/*)
    from flinttrade_engine.position_sizer_routes import position_bp  # noqa: PLC0415

    app.register_blueprint(position_bp)

    # Register Voice Orders blueprint (/api/v1/voice/*)
    from flinttrade_webhooks.voice_orders import voice_bp  # noqa: PLC0415

    app.register_blueprint(voice_bp)

    # Register n8n bridge blueprint (/api/v1/automation/n8n/*)
    from flinttrade_automation.n8n_routes import n8n_bp  # noqa: PLC0415

    app.register_blueprint(n8n_bp)

    # Register QuestDB bridge blueprint (/api/v1/data/questdb/*)
    from flinttrade_data.questdb_routes import questdb_bp  # noqa: PLC0415

    app.register_blueprint(questdb_bp)

    # Register Excel bridge blueprint (/api/v1/integration/excel/*)
    from flinttrade_webhooks.excel_routes import excel_bp  # noqa: PLC0415

    app.register_blueprint(excel_bp)

    # ------------------------------------------------------------------
    # Blueprints discovered as defined-but-not-registered during the
    # 2026-05-19 multi-agent audit (Python audit, API contract audit).
    # Registering them activates their routes:
    #
    #   webhook_bp                — /v1/webhook/<source>, /v1/webhook/log
    #                               (signed alert-format webhook receivers)
    #   payoff_bp                 — /api/v1/payoff/{analyse,curve}, /api/v1/regime/current,
    #                               /api/v1/analytics/correlation
    #                               (prefix flipped 2026-05-19 to align with ftApi.helpers)
    #   health_bp                 — /health, /health/detail, /healthz, /readyz,
    #                               /api/v1/ping, /api/v1/health (K8s + LB probes
    #                               + aggregated subsystem health; canonical health
    #                               surface; /api/v1/ping is already in
    #                               `_PUBLIC_V1_PREFIXES`)
    #   optimiser_bp              — /v1/portfolio/{optimise,frontier}
    #   permutation_bp            — /v1/backtest/{permutation,walkforward}
    #   admin_action_center_bp    — /admin/action-center/{pending,approve,reject,history}
    #                               (separate from `action_center_bp` which lives
    #                               under /api/v1/action-center for normal users)
    #   (the advanced-order routes /api/v1/orders/{basket,split,options-strategy}
    #    were folded into core's orders_bp on 2026-07-09 — one blueprint now owns
    #    the whole /api/v1/orders/* surface.)
    # ------------------------------------------------------------------
    from flinttrade_webhooks.webhook_receiver import WebhookConfig, WebhookReceiver  # noqa: PLC0415
    from flinttrade_webhooks.webhook_routes import init_webhook_routes, webhook_bp  # noqa: PLC0415
    from flinttrade_webhooks.webhook_secret_store import WebhookSecretStore  # noqa: PLC0415
    from .operations_routes import webhook_endpoint_enabled  # noqa: PLC0415
    from .webhook_dispatch import WebhookOrderDispatcher  # noqa: PLC0415

    webhook_secret_store = WebhookSecretStore(_workspace_dir() / "webhook_secrets.db", _get_master_password())
    app.config["WEBHOOK_SECRET_STORE"] = webhook_secret_store
    webhook_order_dispatcher = WebhookOrderDispatcher(app)
    init_webhook_routes(
        WebhookReceiver(
            WebhookConfig(),
            order_dispatcher=webhook_order_dispatcher.place_order,
            cancel_dispatcher=webhook_order_dispatcher.cancel_order,
        ),
        secret_store=webhook_secret_store,
        endpoint_status_provider=webhook_endpoint_enabled,
    )
    app.register_blueprint(webhook_bp)

    from flinttrade_screener.payoff_routes import payoff_bp  # noqa: PLC0415

    app.register_blueprint(payoff_bp)

    from .health_routes import health_bp  # noqa: PLC0415

    app.register_blueprint(health_bp)

    # Backtest route blueprints — imported from the installed flinttrade_backtest
    # package (no sys.path injection: the workspace package is installed editable).
    from flinttrade_backtest.optimiser_routes import optimiser_bp  # noqa: PLC0415

    app.register_blueprint(optimiser_bp)
    from flinttrade_backtest.permutation_routes import permutation_bp  # noqa: PLC0415

    app.register_blueprint(permutation_bp)

    from flinttrade_engine.action_center_routes import admin_action_center_bp  # noqa: PLC0415

    app.register_blueprint(admin_action_center_bp)

    # Register Workspace Preset blueprint (/v1/presets/* — external: /ft-api/v1/presets/*)
    from .preset_routes import preset_bp  # noqa: PLC0415

    app.register_blueprint(preset_bp)

    # Register Log Stream blueprint (/v1/logs/*) — SSE + REST log streaming
    from .log_stream import log_stream_bp  # noqa: PLC0415

    app.register_blueprint(log_stream_bp)

    # Register Keyboard Shortcuts blueprint (/v1/shortcuts/*) — per-user DuckDB persistence
    from .shortcuts_routes import shortcuts_bp  # noqa: PLC0415

    app.register_blueprint(shortcuts_bp)

    # Register Docs Search blueprint (/v1/docs/*) — full-text search + changelog
    from .docs_search_routes import docs_search_bp  # noqa: PLC0415

    app.register_blueprint(docs_search_bp)

    # Register the CSP violation-report endpoint (POST /csp-report; matches the
    # report-uri the nonce-based CSP header declares) — DS-CSP-09.
    app.register_blueprint(_csp_report_bp)

    # Register Auth blueprint (/v1/auth/*) — public endpoints, no API key required
    from .auth_service import AuthService as _AuthService  # noqa: PLC0415
    from .auth_routes import auth_bp, install_auth_rate_limits  # noqa: PLC0415

    _auth_db = _workspace_dir() / "auth.db"
    app.config["AUTH_SERVICE"] = _AuthService(db_path=_auth_db)
    app.register_blueprint(auth_bp)
    # Wire the deferred @_rate_limit limits onto Flask-Limiter AFTER the auth
    # views are registered (they aren't present in view_functions during the
    # blueprint's record hook), so login/PIN/setup brute-force is actually
    # throttled — not merely registered against a discarded wrapper.
    install_auth_rate_limits(app)

    # (Multi-user /api/v1/users/* CRUD removed 2026-06-10 as overscope — FlintTrade
    # is a single-operator tool; operator == user == data principal. Archived to
    # .local/archive/user-multi-2026-06-10/.)

    # Reconnect saved accounts (best-effort, don't block startup)
    try:
        _reconnect_saved_accounts(registry, credential_store, logger)
    except Exception as exc:
        logger.error("Account reconnection failed (%s)", type(exc).__name__)

    # Paths that are legitimately public (no API key needed):
    # - Health check endpoint (also exempted by endpoint name in require_auth)
    # - Admin introspect (already gated by FLINTTRADE_DEV in admin_routes)
    # - OAuth callbacks (browser redirect — no API key in URL)
    # - Frontend error reporting (/api/v1/errors — must be reachable before auth)
    # - Signed external webhook POSTs (/v1/webhook/*) — HMAC/replay/endpoint
    #   state is enforced inside webhook_routes before dispatch.
    _PUBLIC_V1_PREFIXES = (
        "/v1/admin/health",
        "/v1/admin/introspect",
        "/v1/auth/",  # Auth endpoints are public (login, setup, status)
        "/v1/auth/callback",
        "/v1/errors",  # Frontend error reporting — public, rate-limited.
        # Blueprint mounted at /v1/errors (see
        # frontend_error_routes.py:Blueprint(..., url_prefix="/v1")).
        # Persists to ErrorLog (DuckDB) for post-mortem.
        "/api/v1/errors",  # Same purpose, different sink: this path is
        # handled by `operations_bp.receive_frontend_error`
        # which forwards to structlog + Sentry/Glitchtip
        # instead of DuckDB. Kept public so the React app
        # and external automation can fire-and-forget
        # error reports without an API key — neither sink
        # leaks sensitive data
        # back to the caller.
        "/v1/changelog",  # Frontend changelog viewer — public, paired with /v1/errors.
        "/api/v1/ping",  # Liveness probe — no auth required
        "/v1/config/openalgo",  # Localhost-only; self-authenticates after setup
        "/v1/test-connection",  # Setup wizard — public, localhost-only
    )

    @app.before_request
    def _bind_request_context() -> None:
        """Bind per-request fields into the structlog context variable store.

        Attaches a unique request ID (from the X-Request-ID header, or a
        freshly generated hex token), the HTTP method, and the path so that
        every log line emitted during this request carries them automatically.
        """
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request.headers.get("X-Request-ID", secrets.token_hex(8)),
            method=request.method,
            path=request.path,
        )

    @app.after_request
    def _log_request(response: Any) -> Any:
        """Emit a structured log line for every completed HTTP response."""
        _req_log = structlog.get_logger()
        _req_log.info(
            "request",
            status=response.status_code,
            content_length=response.content_length,
        )
        return response

    @app.before_request
    def _set_csp_nonce() -> None:
        """Mint a fresh per-request CSP nonce for the served HTML + CSP header.

        Read by :func:`_add_security_headers` (header) and the SPA fallback
        (``<script nonce>`` injection) so the bootstrap script the gateway serves
        carries the same nonce the policy declares (DS-CSP-09).
        """
        _flask_g.csp_nonce = _generate_csp_nonce()

    @app.after_request
    def _add_security_headers(response: Any) -> Any:
        """Add security headers to every response (only when not already set).

        CSP is delivered here, as a per-request HTTP header carrying a fresh nonce
        (DS-CSP-09). It is an HTTP header — not a <meta> tag — because only the gateway
        can mint a per-render nonce and weave it into both the policy and the served
        index.html's <script> tags. The script directive forbids inline scripts (DS-CSP-01).
        """
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            _build_csp_header(getattr(_flask_g, "csp_nonce", None)),
        )
        return response

    @app.before_request
    def require_auth() -> Any:
        """Require API key authentication on all endpoints.

        Only specific public paths are exempted:
        - Health check and admin introspect (dev-gated)
        - OAuth callback (browser redirect, no API key in URL)
        - Static files and SPA HTML fallback (React bundle)
        All other /v1/ endpoints require the same API key auth.
        """
        # Allow health check, static files, and SPA fallback without auth
        if request.endpoint in ("health_detail.health_aggregated", "static", "_spa_fallback"):
            return None
        # Allow OPTIONS for CORS preflight
        if request.method == "OPTIONS":
            return None
        # External signal providers cannot send the FlintTrade API key. Keep
        # only POST intake public; the route itself enforces HMAC signatures,
        # replay defence, endpoint enabled-state, and fail-closed dispatch.
        if request.method == "POST" and request.path.startswith("/v1/webhook/"):
            return None
        # Allow specific public /v1/ paths only
        if any(request.path.startswith(prefix) for prefix in _PUBLIC_V1_PREFIXES):
            return None

        auth_header = request.headers.get("Authorization", "")
        bearer = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""
        if bearer:
            try:
                from .auth_routes import decode_token  # noqa: PLC0415

                payload = decode_token(bearer)
                if payload.get("type") == "session":
                    return None
            except Exception:
                # Preserve the legacy ``Authorization: Bearer <api-key>`` path
                # below when the bearer is not a FlintTrade session JWT.
                pass

        api_key = request.headers.get("X-API-Key") or bearer

        expected_key = os.environ.get("FLINTTRADE_API_KEY", "") or os.environ.get("OPENALGO_API_KEY", "")
        if not expected_key:
            remote = request.remote_addr or ""
            if remote in ("127.0.0.1", "::1", "localhost"):
                logger.debug(
                    "FLINTTRADE_API_KEY/OPENALGO_API_KEY not set — allowing loopback local request",
                )
                return None
            logger.warning("FLINTTRADE_API_KEY/OPENALGO_API_KEY not set — remote requests will be rejected")
            return jsonify({"status": "error", "message": "Backend API key not configured"}), 503

        if not api_key or not hmac.compare_digest(api_key, expected_key):
            # Record auth failure for brute-force detection
            try:
                sec = app.config.get("SECURITY_MONITOR")
                if sec:
                    sec.record_auth_failure(request.remote_addr or "unknown")
            except Exception as _exc:
                logger.debug("suppressed: %s", _exc)
            return jsonify({"status": "error", "message": "Unauthorized"}), 401

        return None

    @app.before_request
    def _require_json_content_type() -> Any:
        """Reject POST/PUT/PATCH requests that don't send JSON."""
        if request.method in ("POST", "PUT", "PATCH") and request.content_length:
            content_type = request.content_type or ""
            if "json" not in content_type and "text/event-stream" not in content_type:
                return jsonify(
                    {
                        "status": "error",
                        "message": "Content-Type must be application/json",
                    }
                ), 415
        return None

    @app.before_request
    def _record_request_start() -> None:
        """Store request start time for latency calculation."""
        _flask_g._request_start = time.monotonic()

    @app.after_request
    def _record_traffic(response: Any) -> Any:
        """Record method, path, status, and duration in TrafficCounter."""
        try:
            from .monitoring_routes import get_traffic_counter  # noqa: PLC0415

            start = getattr(_flask_g, "_request_start", None)
            duration_ms = (time.monotonic() - start) * 1000 if start is not None else 0.0
            get_traffic_counter().record(
                method=request.method,
                path=request.path,
                status=response.status_code,
                duration_ms=duration_ms,
            )
        except Exception as _exc:
            logger.debug("suppressed: %s", _exc)  # Never let monitoring break the response
        return response

    @app.after_request
    def _track_404s(response: Any) -> Any:
        """Persist 404 events in SecurityTracker for flood detection.

        Runs after the response is built so we know the real status code.
        Best-effort — never disrupts the response pipeline.
        """
        if response.status_code == 404:
            try:
                skt = app.config.get("SECURITY_TRACKER")
                if skt is not None:
                    skt.track_404(request.remote_addr or "unknown", request.path)
            except Exception as _exc:
                logger.debug("suppressed: %s", _exc)
        return response

    @app.before_request
    def _session_heartbeat() -> None:
        """Update last_active for the session carried in the Authorization header.

        Only fires when a valid Bearer token is present AND a SessionTracker
        has been registered.  Best-effort — never blocks the request.
        """
        try:
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return
            token = auth_header.removeprefix("Bearer ").strip()
            if not token:
                return
            st = app.config.get("SESSION_TRACKER")
            if st is not None:
                st.heartbeat(token)
        except Exception as _exc:
            logger.debug("suppressed: %s", _exc)

    # --- inline route handlers extracted to blueprints ---
    # indicators_bp  → packages/core/core/src/indicators_routes.py
    # advisor_bp     → packages/services/ai/src/advisor_routes.py
    # ai_bp          → packages/services/ai/src/ai_routes.py
    # signal_bp      → packages/services/ai/src/signal_routes.py
    # backtest_bp    → packages/core/core/src/backtest_routes.py
    # operations_bp  → packages/core/core/src/operations_routes.py

    # ------------------------------------------------------------------
    # MCP bridge — intentionally NOT wired here.
    #
    # A dormant bridge used to register an UNGATED ``place_order`` handler that
    # built a fresh OpenAlgoClient and submitted live orders without passing
    # through the SafetySystem / gate_order / BrokerRouter and mode guard. It
    # was unreachable today but a latent ungated-order risk, so it has been
    # removed. Any future MCP order path MUST route through the gated execution
    # layer rather than calling OpenAlgoClient.place_order directly.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Config persistence endpoint — /ft-api/v1/config/openalgo
    # Accepts {api_key, host, port, ws_port} from the Setup wizard, persists
    # them to workspace.json, and hot-reloads app.config["CLIENT"] so no
    # process restart is needed.
    # ------------------------------------------------------------------
    # Registered at /v1/... (not /ft-api/v1/...) because the WSGI prefix
    # stripper normalises /ft-api/v1/X → /v1/X before URL dispatch, and the
    # Vite dev proxy does the same rewrite. So a single /v1/... registration
    # is reachable from both environments.
    openalgo_config_lock = threading.RLock()

    def _serialise_openalgo_config(handler: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(handler)
        def serialised(*args: Any, **kwargs: Any) -> Any:
            with openalgo_config_lock:
                return handler(*args, **kwargs)

        return serialised

    def _openalgo_config_request_authenticated() -> bool:
        auth_header = request.headers.get("Authorization", "")
        bearer = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""
        if bearer:
            try:
                from .auth_routes import decode_token  # noqa: PLC0415

                if decode_token(bearer).get("type") == "session":
                    return True
            except Exception:
                pass

        expected = os.environ.get("FLINTTRADE_API_KEY", "") or os.environ.get("OPENALGO_API_KEY", "")
        supplied = request.headers.get("X-API-Key") or bearer
        return bool(expected and supplied and secrets.compare_digest(str(supplied), expected))

    @app.route("/v1/config/openalgo", methods=["GET", "POST"])
    @limiter.limit("10 per minute")
    @_serialise_openalgo_config
    def _set_openalgo_config() -> Any:
        """Persist OpenAlgo connection settings from the UI.

        Security: writes and unauthenticated status probes are loopback-only.
        Before the operator account exists, GET returns redacted metadata and
        POST must carry an explicit OpenAlgo API key. After setup, both
        methods require a session JWT or the configured backend/OpenAlgo API
        key. An authenticated GET may cross the network so a remote web
        terminal (e.g. over Tailscale) can rehydrate its OpenAlgo connection;
        it is the only shape that returns the raw key.

        Request JSON: ``{"api_key": "...", "host": "...", "port": 5000, "ws_port": 8765}``
        """

        def _coerce_port(value: Any, label: str) -> int:
            try:
                port_value = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{label} must be an integer") from exc
            if not 1 <= port_value <= 65535:
                raise ValueError(f"{label} must be between 1 and 65535")
            return port_value

        remote = request.remote_addr or ""
        remote_is_loopback = remote in ("127.0.0.1", "::1", "localhost")
        authenticated = _openalgo_config_request_authenticated()
        if not remote_is_loopback and (request.method != "GET" or not authenticated):
            return jsonify(
                {
                    "status": "error",
                    "message": "Only an authenticated GET may use this endpoint remotely",
                }
            ), 403

        auth_service = app.config.get("AUTH_SERVICE")
        try:
            operator_is_setup = bool(auth_service is None or auth_service.is_setup())
        except Exception:
            operator_is_setup = True
        if operator_is_setup and not authenticated:
            return jsonify({"status": "error", "message": "Authentication required"}), 401

        if request.method == "GET":
            try:
                from .workspace import Workspace  # noqa: PLC0415

                ws = Workspace()
                if not ws.config_path.exists():
                    ws.initialise()
                config = ws.as_dict()
                openalgo = config.get("openalgo") if isinstance(config, dict) else {}
                if not isinstance(openalgo, dict):
                    openalgo = {}
                api_key = str(openalgo.get("api_key", "") or "")
                data = {
                    "api_key_configured": bool(api_key),
                    "api_key_last4": api_key[-4:] if api_key else "",
                    "host": str(openalgo.get("host", "") or ""),
                    "port": openalgo.get("port", DEFAULT_OPENALGO_PORT),
                    "ws_port": openalgo.get("ws_port", DEFAULT_OPENALGO_WS_PORT),
                }
                # The terminal needs the bridge key in memory for its direct
                # OpenAlgo WebSocket. Only an authenticated operator session (or
                # explicit backend API key) may rehydrate it; pre-setup status
                # probes receive redacted metadata only.
                if authenticated:
                    data["api_key"] = api_key
                return jsonify(
                    {
                        "status": "success",
                        "data": data,
                    }
                ), 200
            except Exception as exc:
                logger.error("Failed to read OpenAlgo config from workspace.json: %s", exc)
                return jsonify(
                    {
                        "status": "error",
                        "message": "Could not read config",
                    }
                ), 500

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(
                {
                    "status": "error",
                    "message": "Request body must be a JSON object",
                }
            ), 400
        has_api_key = "api_key" in payload
        has_host = "host" in payload
        has_port = "port" in payload
        has_ws_port = "ws_port" in payload
        api_key = str(payload.get("api_key", "")).strip()
        host = str(payload.get("host", "")).strip()
        port = payload.get("port")
        ws_port = payload.get("ws_port")

        if not authenticated and (not has_api_key or not api_key):
            return jsonify(
                {
                    "status": "error",
                    "message": "Initial OpenAlgo setup must include the API key",
                }
            ), 401

        if not has_api_key and not has_host and not has_port and not has_ws_port:
            return jsonify(
                {
                    "status": "error",
                    "message": "At least one of api_key, host, port, ws_port is required",
                }
            ), 400

        try:
            normalised_port = _coerce_port(port, "port") if has_port else None
            normalised_ws_port = _coerce_port(ws_port, "ws_port") if has_ws_port else None
        except ValueError:
            # Fixed message — never echo exception text into a response.
            return jsonify(
                {
                    "status": "error",
                    "message": "port and ws_port must be integers between 1 and 65535",
                }
            ), 400

        # Persist to workspace.json
        try:
            from .workspace import Workspace  # noqa: PLC0415

            ws = Workspace()

            candidate: dict[str, Settings] = {}

            def update_openalgo(config: dict[str, Any]) -> None:
                current_openalgo = config.get("openalgo")
                openalgo = dict(current_openalgo) if isinstance(current_openalgo, dict) else {}
                if has_api_key:
                    openalgo["api_key"] = api_key
                if has_host:
                    openalgo["host"] = host
                if has_port:
                    openalgo["port"] = normalised_port
                if has_ws_port:
                    openalgo["ws_port"] = normalised_ws_port
                config["openalgo"] = openalgo
                candidate["settings"] = Settings.from_workspace_data(config)

            ws.update(update_openalgo)
            candidate_settings = candidate["settings"]
        except (TypeError, ValueError):
            return jsonify(
                {
                    "status": "error",
                    "message": "OpenAlgo settings are invalid",
                }
            ), 400
        except Exception as exc:
            logger.error("Failed to persist OpenAlgo config to workspace.json: %s", exc)
            return jsonify(
                {
                    "status": "error",
                    "message": "Could not persist config",
                }
            ), 500

        # Settings reads workspace.json directly; log the fresh UI-owned
        # settings for diagnostics without copying secrets into os.environ.
        try:
            _log_workspace_openalgo_overrides()
        except Exception:
            pass

        # Reconfigure the shared client in place. BrokerRouter, schedulers, cron
        # and Telegram all retain this object, so replacing/closing it would
        # strand live callers on stale credentials or a closed HTTP pool.
        old_client = app.config.get("CLIENT")
        old_settings = getattr(old_client, "settings", None)
        old_api_key_value = getattr(old_settings, "openalgo_api_key", "")
        old_api_key = old_api_key_value if isinstance(old_api_key_value, str) else ""
        try:
            new_settings = candidate_settings
            if isinstance(old_client, OpenAlgoClient):
                new_client = old_client.reconfigure(new_settings)
            else:
                new_client = OpenAlgoClient(new_settings)
            app.config["CLIENT"] = new_client
            app.config["OPENALGO_CLIENT"] = new_client
            if old_client is not new_client:
                configure_broker_router(app, registry, credential_store, new_client)
        except Exception as exc:
            diagnostic = _sanitise_tick_capture_error(exc, api_key)
            diagnostic = _sanitise_tick_capture_error(diagnostic, old_api_key)
            logger.warning("OpenAlgo config saved but client reinitialisation failed: %s", diagnostic)
            return jsonify(
                {
                    "status": "partial",
                    "message": "Config saved but client not reloaded",
                }
            ), 200

        # The desktop and full-app boot paths both expose the active recorder on
        # app.config. Reconfigure it only after Settings and the REST client are
        # valid, so one save moves both transports to the same endpoint/key.
        with _tick_capture_lifecycle_lock(app):
            recorder = app.config.get("TICK_RECORDER")
            if recorder is not None:
                capture_reconfigured = False
                try:
                    # Register the new key with the desktop runtime before the
                    # recorder can use it or fail, so every diagnostic is redacted.
                    desktop_runtime = app.config.get("DESKTOP_TICK_CAPTURE_RUNTIME")
                    update_runtime_api_key = getattr(desktop_runtime, "update_api_key", None)
                    if callable(update_runtime_api_key):
                        update_runtime_api_key(new_settings.openalgo_api_key)

                    reconfigure_connection = getattr(recorder, "reconfigure_connection", None)
                    if not callable(reconfigure_connection):
                        raise RuntimeError("Tick recorder does not support connection reconfiguration")
                    reconfigure_connection(
                        ws_url=openalgo_ws_base_url(new_settings),
                        api_key=new_settings.openalgo_api_key,
                    )
                    capture_reconfigured = True
                    if app.config.get("TICK_RECORDER") is not recorder:
                        diagnostic = str(app.config.get("TICK_CAPTURE_ERROR", "") or "").strip()
                        if not diagnostic:
                            diagnostic = "Tick recorder stopped during connection reconfiguration"
                        diagnostic = _sanitise_tick_capture_error(diagnostic, new_settings.openalgo_api_key)
                        diagnostic = _sanitise_tick_capture_error(diagnostic, old_api_key)
                        app.config["TICK_CAPTURE_ERROR"] = diagnostic
                        logger.warning("OpenAlgo config saved after tick recorder stopped (%s)", diagnostic)
                        return jsonify(
                            {
                                "status": "partial",
                                "message": "OpenAlgo config saved and client reloaded, but tick capture reload was incomplete",
                                "data": {
                                    "client_reloaded": True,
                                    "tick_capture_reconfigured": False,
                                },
                            }
                        ), 200
                except Exception as exc:  # noqa: BLE001 - saved REST config remains usable
                    diagnostic = _sanitise_tick_capture_error(exc, new_settings.openalgo_api_key)
                    diagnostic = _sanitise_tick_capture_error(diagnostic, old_api_key)
                    app.config["TICK_CAPTURE_ERROR"] = diagnostic
                    logger.warning("OpenAlgo config saved but tick capture hot-reload failed (%s)", diagnostic)
                    return jsonify(
                        {
                            "status": "partial",
                            "message": "OpenAlgo config saved and client reloaded, but tick capture reload was incomplete",
                            "data": {
                                "client_reloaded": True,
                                "tick_capture_reconfigured": capture_reconfigured,
                            },
                        }
                    ), 200
                app.config["TICK_CAPTURE_ERROR"] = ""
            elif app.config.get("TICK_CAPTURE_ENABLED") and app.config.get("TICK_CAPTURE_ERROR"):
                return jsonify(
                    {
                        "status": "partial",
                        "message": "OpenAlgo config saved and client reloaded, but tick capture requires a restart",
                        "data": {
                            "client_reloaded": True,
                            "tick_capture_reconfigured": False,
                        },
                    }
                ), 200

        return jsonify(
            {
                "status": "ok",
                "message": "OpenAlgo config saved and client reloaded",
            }
        ), 200

    @app.route("/v1/config/llm", methods=["GET", "POST"])
    @limiter.limit("10 per minute")
    def _llm_config() -> Any:
        """Persist redacted LLM settings from the UI."""
        remote = request.remote_addr or ""
        if remote not in ("127.0.0.1", "::1", "localhost"):
            return jsonify(
                {
                    "status": "error",
                    "message": "This endpoint is only reachable from localhost",
                }
            ), 403

        from .local_ai_routes import require_local_control_auth  # noqa: PLC0415

        denied = require_local_control_auth(
            message="LLM configuration requires an authenticated session"
        )
        if denied is not None:
            return denied

        try:
            from .llm_config import read_llm_config  # noqa: PLC0415
            from .local_ai_routes import persist_llm_config_with_runtime  # noqa: PLC0415
            from .ollama_runtime import OllamaRuntimeError  # noqa: PLC0415

            if request.method == "GET":
                return jsonify({"status": "success", "data": read_llm_config()}), 200

            payload = request.get_json(silent=True) or {}
            data = persist_llm_config_with_runtime(app, payload)
            return jsonify(
                {
                    "status": "ok",
                    "message": "LLM config saved",
                    "data": data,
                }
            ), 200
        except OllamaRuntimeError as exc:
            logger.warning("LLM runtime transition rejected (%s)", type(exc).__name__)
            return jsonify({"status": "error", "message": str(exc)}), 409
        except ValueError as exc:
            logger.warning("Invalid LLM config payload (%s)", type(exc).__name__)
            return jsonify(
                {
                    "status": "error",
                    "message": str(exc),
                }
            ), 400
        except Exception as exc:
            logger.error("Failed to persist LLM config (%s)", type(exc).__name__)
            return jsonify(
                {
                    "status": "error",
                    "message": "Could not persist LLM config",
                }
            ), 500

    @app.post("/v1/config/llm/test")
    @limiter.limit("10 per minute")
    def _test_llm_connection() -> Any:
        """Test the effective LLM configuration without exposing its secret."""
        remote = request.remote_addr or ""
        if remote not in ("127.0.0.1", "::1", "localhost"):
            return jsonify(
                {
                    "status": "error",
                    "message": "This endpoint is only reachable from localhost",
                }
            ), 403

        from .local_ai_routes import require_local_control_auth  # noqa: PLC0415

        denied = require_local_control_auth(
            message="LLM configuration requires an authenticated session"
        )
        if denied is not None:
            return denied

        try:
            from flinttrade_ai.llm_client import LLMClient, LLMConfig, LLMMessage  # noqa: PLC0415
            from .llm_config import resolve_llm_test_config  # noqa: PLC0415

            config = LLMConfig.from_env()
            draft = resolve_llm_test_config(
                request.get_json(silent=True) or {},
                effective={
                    "provider": config.provider,
                    "host": config.host,
                    "model": config.model,
                    "api_key": config.api_key,
                },
            )
            config.provider = draft["provider"]
            config.host = draft["host"]
            config.model = draft["model"]
            config.api_key = draft["api_key"]
            config.managed_runtime = config.provider == "ollama"
            config.reasoning_max_tokens = 0
            with LLMClient(config=config, timeout_seconds=15.0) as client:
                response = client.chat(
                    [LLMMessage(role="user", content="Reply with OK.")],
                    temperature=0.0,
                    max_tokens=8,
                )
            if not response.success:
                logger.warning(
                    "LLM connection test rejected (provider=%s)",
                    config.provider or "unconfigured",
                )
                return jsonify({"status": "error", "message": "LLM connection test failed"}), 409
            return jsonify(
                {
                    "status": "success",
                    "data": {
                        "provider": config.provider,
                        "model": response.model or config.model,
                    },
                }
            ), 200
        except ValueError as exc:
            logger.warning("Invalid LLM connection-test payload (%s)", type(exc).__name__)
            return jsonify({"status": "error", "message": str(exc)}), 400
        except Exception as exc:  # noqa: BLE001 - never surface provider or secret details
            logger.warning("LLM connection test failed (%s)", type(exc).__name__)
            return jsonify({"status": "error", "message": "LLM connection test failed"}), 500

    # ------------------------------------------------------------------
    # Connection-test endpoint — /ft-api/v1/test-connection
    # Used by the Setup wizard + Settings › Connection. The browser cannot
    # call OpenAlgo's /api/v1/ping directly because OpenAlgo does not send
    # CORS headers for our origin (and we will not modify OpenAlgo). We
    # proxy the test through our backend so it runs server-to-server with
    # no CORS involvement.
    # ------------------------------------------------------------------
    @app.route("/v1/test-connection", methods=["POST"])
    @limiter.limit("10 per minute")
    def _test_openalgo_connection() -> Any:
        """Server-side OpenAlgo connectivity + auth test.

        Accepts the exact ``{host, api_key}`` the user typed in the wizard,
        pings OpenAlgo, and returns a structured result. HTTP status is
        always 200 — the real outcome lives in the JSON body so the
        frontend can distinguish reachable/unreachable/auth-failed without
        tripping on HTTP error handling.
        """
        remote = request.remote_addr or ""
        if remote not in ("127.0.0.1", "::1", "localhost"):
            return jsonify(
                {
                    "status": "error",
                    "message": "This endpoint is only reachable from localhost",
                }
            ), 403

        payload = request.get_json(silent=True) or {}
        # Strip one or more trailing slashes; setup wizard sometimes posts
        # the host with "/" or "//".
        host = str(payload.get("host", "")).strip().rstrip("/")
        api_key = str(payload.get("api_key", "")).strip()

        if not host or not api_key:
            return jsonify(
                {
                    "status": "error",
                    "message": "host and api_key are required",
                }
            ), 400

        import httpx as _httpx  # noqa: PLC0415

        try:
            resp = _httpx.post(
                f"{host}/api/v1/ping",
                json={"apikey": api_key},
                timeout=5.0,
            )
        except (_httpx.ConnectError, _httpx.ConnectTimeout) as exc:
            logger.warning("OpenAlgo connection test could not reach configured host: %s", exc)
            return jsonify(
                {
                    "status": "error",
                    "reachable": False,
                    "message": "Cannot reach OpenAlgo at the configured host",
                }
            ), 200
        except _httpx.TimeoutException:
            return jsonify(
                {
                    "status": "error",
                    "reachable": False,
                    "message": f"OpenAlgo at {host} did not respond within 5s",
                }
            ), 200
        except Exception:  # noqa: BLE001
            return jsonify(
                {
                    "status": "error",
                    "reachable": False,
                    "message": "Connection test failed",
                }
            ), 200

        if resp.status_code == 200:
            broker = "unknown"
            try:
                data = resp.json()
                if isinstance(data, dict):
                    broker = data.get("data", {}).get("broker") or data.get("broker") or "unknown"
            except Exception:  # noqa: BLE001
                pass
            return jsonify(
                {
                    "status": "ok",
                    "reachable": True,
                    "authenticated": True,
                    "broker": broker,
                    "message": f"Connected — broker: {broker}",
                }
            ), 200

        if resp.status_code in (401, 403):
            msg = "Invalid API key"
            try:
                body = resp.json()
                if isinstance(body, dict):
                    msg = body.get("message", msg)
            except Exception:  # noqa: BLE001
                pass
            return jsonify(
                {
                    "status": "error",
                    "reachable": True,
                    "authenticated": False,
                    "http_status": resp.status_code,
                    "message": f"Reachable but auth failed (HTTP {resp.status_code}): {msg}",
                }
            ), 200

        return jsonify(
            {
                "status": "error",
                "reachable": True,
                "authenticated": False,
                "http_status": resp.status_code,
                "message": f"OpenAlgo returned unexpected HTTP {resp.status_code}",
            }
        ), 200

    # ------------------------------------------------------------------
    # SPA fallback — registered LAST so it only matches unclaimed routes.
    # Returns 404 for API paths (so unknown /api/ or /v1/ endpoints still
    # look like 404s to clients) and serves the React bundle for every
    # other path.  Matches at most one path segment so deep React-router
    # paths like `/trade/scalper` all fall through to index.html.
    # ------------------------------------------------------------------
    if _frontend_available:
        from flask import Response as _Response, send_from_directory  # noqa: PLC0415
        from werkzeug.utils import safe_join as _safe_join  # noqa: PLC0415

        _API_PREFIXES = ("/api/", "/ft-api/", "/v1/")

        def _serve_index_with_nonce() -> Any:
            """Serve index.html with the per-request CSP nonce woven into <script> tags.

            The matching ``'nonce-…'`` is added to the response's CSP header by
            ``_add_security_headers``; together they let the bootstrap script run under a
            nonce-based policy that forbids inline scripts (DS-CSP-01/09).
            """
            html = _dist_index.read_text(encoding="utf-8")
            nonce = getattr(_flask_g, "csp_nonce", None)
            if nonce:
                html = _inject_csp_nonce(html, nonce)
            return _Response(html, mimetype="text/html")

        @app.route("/", defaults={"path": ""}, endpoint="_spa_fallback")
        @app.route("/<path:path>", endpoint="_spa_fallback")
        def _spa_fallback(path: str) -> Any:
            """Serve the React SPA for any non-API path."""
            # API paths must never be intercepted — let Flask 404 them.
            req_path = request.path
            if any(req_path.startswith(p) for p in _API_PREFIXES):
                return jsonify(
                    {
                        "status": "error",
                        "message": "Not found",
                    }
                ), 404

            # If the exact file exists under dist/, serve it (favicon, assets/*).
            if path:
                try:
                    joined = _safe_join(str(_dist_path), path)
                    if joined is None:
                        return jsonify(
                            {
                                "status": "error",
                                "message": "Not found",
                            }
                        ), 404
                    # Guard against path traversal: resolved path must be
                    # inside _dist_path.
                    resolved = Path(joined).resolve()
                    if resolved.is_file() and _dist_path.resolve() in resolved.parents:
                        relative = resolved.relative_to(_dist_path.resolve())
                        return send_from_directory(str(_dist_path), str(relative))
                except Exception:
                    pass

            # Otherwise serve index.html (SPA client-side routing) with the CSP nonce.
            return _serve_index_with_nonce()

    return app


class _FlaskServerOwner:
    """Explicit listener/thread owner returned by the Flask serve path."""

    def __init__(
        self,
        server: Any,
        *,
        run: Callable[[], None],
        close: Callable[[], None],
        dispatcher: Any | None = None,
    ) -> None:
        self._server = server
        self._run = run
        self._close = close
        self._dispatcher = dispatcher
        self._state_lock = threading.Lock()
        self._close_complete = False
        self._dispatcher_shutdown_complete = False
        self._run_error: BaseException | None = None
        self.thread = threading.Thread(
            target=self._serve,
            name="flinttrade-api",
            daemon=False,
        )

    def _serve(self) -> None:
        try:
            self._run()
        except BaseException as exc:  # noqa: BLE001 - observed by stop/recovery
            with self._state_lock:
                self._run_error = exc

    def start(self) -> None:
        """Start the already-bound listener exactly once."""
        self.thread.start()

    def stop(self, *, timeout: float) -> bool:
        """Close the listener, stop Waitress workers, and join its thread."""
        deadline = _LifecycleDeadline.after(timeout)
        with self._state_lock:
            close_complete = self._close_complete
        if not close_complete:
            self._close()
            with self._state_lock:
                self._close_complete = True

        self.thread.join(timeout=deadline.remaining())
        if self.thread.is_alive():
            return False

        dispatcher = self._dispatcher or getattr(self._server, "task_dispatcher", None)
        shutdown_dispatcher = getattr(dispatcher, "shutdown", None)
        with self._state_lock:
            dispatcher_shutdown_complete = self._dispatcher_shutdown_complete
        if callable(shutdown_dispatcher) and not dispatcher_shutdown_complete:
            dispatcher_stopped = shutdown_dispatcher(timeout=deadline.remaining())
            if dispatcher_stopped is False:
                return False
            dispatcher_threads = getattr(dispatcher, "threads", None)
            dispatcher_lock = getattr(dispatcher, "lock", None)
            if dispatcher_threads is not None:
                if dispatcher_lock is not None:
                    with dispatcher_lock:
                        workers_remain = bool(dispatcher_threads)
                else:
                    workers_remain = bool(dispatcher_threads)
                if workers_remain:
                    return False
            with self._state_lock:
                self._dispatcher_shutdown_complete = True

        with self._state_lock:
            run_error = self._run_error
        if run_error is not None:
            raise RuntimeError(f"Flask API listener failed ({type(run_error).__name__})") from run_error
        return True


def _run_flask_server(app: Flask, port: int = 5100, host: str = "127.0.0.1") -> _FlaskServerOwner:
    """Bind and run the Flask API server under an explicit lifecycle owner.

    Uses Waitress — a pure-Python, cross-platform production WSGI server
    (works identically on Windows, macOS, Linux).  Replaces Flask's
    built-in Werkzeug dev server, which emits a loud "this is a
    development server" warning and is not production-safe.

    Args:
        app: Flask application instance.
        port: Port to bind (default 5100).
        host: Interface to bind (default loopback). Non-loopback binds are
            refused unless operator authentication is configured, because
            loopback requests are trusted unauthenticated when no API key is
            set — that trust must never extend to a routable interface.
    """
    if host not in ("127.0.0.1", "::1", "localhost"):
        auth_service = app.config.get("AUTH_SERVICE")
        try:
            operator_ready = bool(auth_service is not None and auth_service.is_setup())
        except Exception:  # noqa: BLE001 - an unreadable auth store fails closed
            operator_ready = False
        if not operator_ready and not os.environ.get("FLINTTRADE_API_KEY", "").strip():
            raise RuntimeError(
                f"Refusing to bind FlintTrade to non-loopback host {host!r} without "
                "authentication: create the operator account first (open the app on "
                "this machine and complete setup) or set FLINTTRADE_API_KEY."
            )
    try:
        from waitress.server import create_server  # noqa: PLC0415
    except ImportError:
        from werkzeug.serving import make_server  # noqa: PLC0415

        logger.warning(
            "Waitress not installed; falling back to Werkzeug dev server. Install with: pip install waitress"
        )
        server = make_server(host, port, app, threaded=True)

        def close_werkzeug() -> None:
            server.shutdown()
            server.server_close()

        owner = _FlaskServerOwner(
            server,
            run=server.serve_forever,
            close=close_werkzeug,
        )
    else:
        from waitress.task import ThreadedTaskDispatcher  # noqa: PLC0415

        # Quiet Waitress's per-request access log — our structlog middleware
        # already logs requests via the traffic logger at a structured level.
        logging.getLogger("waitress").setLevel(logging.WARNING)
        # Waitress normally starts its dispatcher threads before binding. Own an
        # unstarted dispatcher and socket map so setup failures can close every
        # allocated resource before the exception escapes startup.
        dispatcher = ThreadedTaskDispatcher()
        socket_map: dict[Any, Any] = {}
        try:
            server = create_server(
                app,
                map=socket_map,
                _dispatcher=dispatcher,
                host=host,
                port=port,
                ident="FlintTrade",
                threads=8,
            )
            dispatcher.set_thread_count(8)
        except BaseException:
            for channel in tuple(socket_map.values()):
                close_channel = getattr(channel, "close", None)
                if callable(close_channel):
                    try:
                        close_channel()
                    except Exception:  # pragma: no cover - preserve the setup failure
                        logger.warning("Waitress setup resource cleanup failed")
            socket_map.clear()
            try:
                dispatcher.shutdown(timeout=5.0)
            except Exception:  # pragma: no cover - preserve the setup failure
                logger.warning("Waitress dispatcher cleanup failed")
            raise
        owner = _FlaskServerOwner(
            server,
            run=server.run,
            close=server.close,
            dispatcher=dispatcher,
        )

    owner.start()
    logger.info("FlintTrade API server started on http://%s:%d", host, port)

    # Arm the daily session-refresh jobs (G5) on the serve path only, so
    # create_flask_app stays side-effect-light for tests.
    _start_rotation_scheduler(app)
    return owner


def _start_rotation_scheduler(app: Flask, *, fail_closed: bool = False) -> None:
    """Start the configured native-session rotation owner at most once.

    Args:
        app: Application that owns the unstarted scheduler.
        fail_closed: Raise when the scheduler cannot start. The packaged
            desktop uses this before advertising readiness; the legacy
            threaded development server retains its degraded-start behaviour.
    """
    rotation_scheduler = app.config.get("ROTATION_SCHEDULER")
    if rotation_scheduler is None or getattr(rotation_scheduler, "running", False):
        return
    try:
        rotation_scheduler.start()
    except Exception as exc:  # noqa: BLE001 - caller selects fail-closed policy
        if fail_closed:
            raise RuntimeError("session-refresh scheduler failed to start") from exc
        logger.warning("Session-refresh scheduler failed to start (%s)", type(exc).__name__)
        return
    logger.info("Native session-refresh scheduler started (08:05 IST daily)")


def _shutdown_rotation_scheduler(app: Flask, *, timeout: float | None = None) -> None:
    """Stop new refresh jobs, revoke publication, and drain admitted refreshes."""
    rotation_scheduler = app.config.get("ROTATION_SCHEDULER")
    scheduler_error: Exception | None = None
    if rotation_scheduler is not None and getattr(rotation_scheduler, "running", False):
        try:
            rotation_scheduler.shutdown(wait=False)
        except Exception as exc:  # noqa: BLE001 - admission must still be revoked
            scheduler_error = exc

    admission = app.config.get("NATIVE_ROTATION_ADMISSION")
    if admission is not None:
        raw_timeout = (
            app.config.get("NATIVE_ROTATION_SHUTDOWN_TIMEOUT_SECONDS", 30.0)
            if timeout is None
            else timeout
        )
        try:
            drain_timeout = max(0.0, float(raw_timeout))
        except (TypeError, ValueError):
            drain_timeout = 30.0
        close_and_drain = getattr(admission, "close_and_drain", None)
        if not callable(close_and_drain):
            raise RuntimeError("native session rotation admission owner is invalid")
        if not close_and_drain(drain_timeout):
            raise TimeoutError("native session rotation did not drain")
    if scheduler_error is not None:
        raise scheduler_error


def _market_calendar_refresh_delay(*, loaded: bool) -> float:
    """Return seconds until the next calendar refresh or short failure retry."""
    if not loaded:
        return 300.0

    from datetime import datetime, timedelta  # noqa: PLC0415
    from zoneinfo import ZoneInfo  # noqa: PLC0415

    now = datetime.now(ZoneInfo("Asia/Kolkata"))
    refresh_at = now.replace(hour=0, minute=5, second=0, microsecond=0)
    if refresh_at <= now:
        refresh_at += timedelta(days=1)
    return max(1.0, (refresh_at - now).total_seconds())


def _current_market_calendar_year() -> int:
    """Return the current exchange-calendar year in IST."""
    from datetime import datetime  # noqa: PLC0415
    from zoneinfo import ZoneInfo  # noqa: PLC0415

    return datetime.now(ZoneInfo("Asia/Kolkata")).year


@dataclass(slots=True)
class _ShutdownAttempt:
    """One shutdown task paired with immutable failure notification."""

    failed_event: asyncio.Event
    task: asyncio.Task[Any] | None = None


@dataclass(slots=True)
class _AcquiredRuntimeOwner:
    """One startup owner whose rollback remains retryable until proved complete."""

    label: str
    rollback: Callable[[_LifecycleDeadline], Awaitable[bool]]
    task: asyncio.Task[bool] | None = None
    released: bool = False


class _AcquiredOwnerLedger:
    """Record startup owners and roll them back in reverse acquisition order."""

    def __init__(self) -> None:
        self._owners: list[_AcquiredRuntimeOwner] = []

    def acquire(
        self,
        label: str,
        rollback: Callable[[_LifecycleDeadline], Awaitable[bool]],
    ) -> None:
        self._owners.append(_AcquiredRuntimeOwner(label, rollback))

    @property
    def has_unreleased(self) -> bool:
        return any(not owner.released for owner in self._owners)

    def mark_released(self, label: str) -> bool:
        """Mark one uniquely labelled owner released by an equivalent root stop."""
        matches = [owner for owner in self._owners if owner.label == label]
        if not matches:
            return True
        if len(matches) != 1:
            return False
        owner = matches[0]
        if owner.released:
            return True
        if owner.task is not None:
            return False
        owner.released = True
        return True

    async def rollback(self, deadline: _LifecycleDeadline) -> bool:
        for owner in reversed(self._owners):
            if owner.released:
                continue
            task = owner.task
            if task is None:
                task = asyncio.create_task(owner.rollback(deadline))
                owner.task = task
            done, _ = await asyncio.wait({task}, timeout=deadline.remaining())
            if task not in done:
                return False
            try:
                released = bool(task.result())
            except BaseException as exc:  # noqa: BLE001 - rollback remains retryable
                logger.warning("Startup rollback for %s failed (%s)", owner.label, type(exc).__name__)
                released = False
            owner.task = None
            if released:
                owner.released = True
            else:
                return False
        return not self.has_unreleased


class FlintTradeApp:
    """Main application — creates and wires all FlintTrade subsystems.

    Startup is resilient: if OpenAlgo is unreachable or optional services
    (Telegram, AI) are not configured, the app starts with warnings
    instead of crashing.

    Usage::

        app = FlintTradeApp()
        app.run()  # blocking — runs until Ctrl+C or SIGTERM
    """

    def __init__(self) -> None:
        self.version = _read_version()

        # Audit logger first — must be available before anything else
        self.audit = AuditLogger()
        self.audit.log_event("APP_START", version=self.version)

        # Core — settings + API client
        self.settings = Settings.from_env()
        self.client = OpenAlgoClient(self.settings)

        # Engine — safety + scheduler (deferred to avoid circular import
        # between core↔engine at module level). Live order dispatch is the
        # gateway BrokerRouter (gate_order → BrokerRouter → adapter); the legacy
        # ungated OrderRouter was removed 2026-07-09.
        from flinttrade_engine.safety import SafetyConfig, SafetySystem  # noqa: PLC0415
        from .safety_config import load_workspace_safety_config  # noqa: PLC0415
        from flinttrade_engine.scheduler import (  # noqa: PLC0415
            CronStrategyScheduler,
            StrategyScheduler,
            TimeScheduler,
        )

        try:
            self.safety = SafetySystem(
                load_workspace_safety_config(_workspace_dir()),
                reservation_db_path=_workspace_dir() / "order_exposure_reservations.sqlite",
            )
        except Exception as exc:  # noqa: BLE001 - process serves recovery UI without live routing
            logger.critical(
                "Workspace safety configuration failed strict validation (%s); live routing remains disabled",
                type(exc).__name__,
            )
            self.safety = SafetySystem(
                SafetyConfig(check_market_hours=True),
                reservation_db_path=_workspace_dir() / "order_exposure_reservations.sqlite",
            )
            self.safety_config_ready = False
        else:
            self.safety_config_ready = True
        self.time_scheduler = TimeScheduler(client=self.client)
        self.scheduler = StrategyScheduler(
            client=self.client,
            time_scheduler=self.time_scheduler,
        )
        self.strategy_cron_scheduler = CronStrategyScheduler(
            time_scheduler=self.time_scheduler,
        )

        # Automation — cron manager (lazy import avoids loading APScheduler at
        # module level, which accounts for ~0.3 s of the startup penalty).
        from flinttrade_automation.cron_manager import CronManager  # noqa: PLC0415

        self.cron = CronManager(
            openalgo_client=self.client,
            audit_logger=self.audit,
        )

        # Automation — Telegram bot (optional — token may not be set).
        # Lazy import avoids pulling in the python-telegram-bot dependency
        # (and its event-loop initialisation) until it is actually needed.
        from flinttrade_automation.telegram_bot import TelegramBot  # noqa: PLC0415

        self.telegram = TelegramBot(
            client=self.client,
            safety_system=self.safety,
            scheduler=self.scheduler,
            audit_logger=self.audit,
        )
        # Wire Telegram into cron so jobs can send alerts
        self.cron.telegram_bot = self.telegram

        # Gateway — broker registry + credential store + contract manager
        flinttrade_dir = _workspace_dir()
        master_password = _get_master_password()
        self.credential_store = CredentialStore(flinttrade_dir / "credentials.db", master_password)
        contracts_dir = flinttrade_dir / "contracts"
        contracts_dir.mkdir(exist_ok=True)
        self.contract_manager = ContractManager(contracts_dir)
        self.registry = BrokerRegistry()

        # RAG — knowledge base (persistent).
        # LLMClient and RAGPipeline are imported lazily here to avoid loading
        # ChromaDB, sentence-transformers, and the LLM HTTP client at module
        # level, which would add 2-5 s to startup time even when the AI
        # features are not yet used.
        self.rag = _initialise_rag_runtime(flinttrade_dir)

        # Live tick capture (opt-in via FLINTTRADE_TICK_CAPTURE) — wired in start().
        self._tick_recorder: Any | None = None
        self._tick_recorder_task: Any | None = None
        self._tick_storage: Any | None = None
        self._tick_storage_lock: Any | None = None
        self._orderflow_checkpoint_owner: _OrderFlowCheckpointOwner | None = None
        self._tick_storage_close_worker: _BoundedTickStorageCloseWorker | None = None
        self._flask_app: Flask | None = None
        self._flask_server_owner: _FlaskServerOwner | None = None
        self._stop_started = False
        self._stop_completed = False
        self._shutdown_task: asyncio.Task[Any] | None = None
        self._shutdown_request_task: asyncio.Task[Any] | None = None
        self._holiday_refresh_task: asyncio.Task[Any] | None = None
        self._start_claim_lock = threading.Lock()
        self._start_claimed = False
        self._calendar_loaded = False
        self._calendar_runtime_ready = False
        self._calendar_schedulers_started = False
        # The refresh runs every few minutes; in no-broker mode it can never
        # produce an authoritative calendar, so warn once on entry to that
        # state and log subsequent unchanged repeats at DEBUG (avoids flooding
        # the log while a user runs in Explore).
        self._calendar_unauthoritative_warned = False
        self._strategy_cron_started = False
        self._cron_jobs_registered = False
        self._cron_started = False
        self._startup_owner_ledger: _AcquiredOwnerLedger | None = None
        self._startup_rollback_in_progress = False
        self._startup_recovery_pending = False
        self._active_shutdown_deadline: _LifecycleDeadline | None = None
        self._shutdown_sync_workers: dict[str, _RetainedSyncOwnerWorker] = {}
        self._shutdown_async_tasks: dict[str, asyncio.Task[Any]] = {}
        self._recovery_loop: asyncio.AbstractEventLoop | None = None
        self._retained_backend_lease: Any | None = None

        # Broker reconciliation runner (contract §14.2) — wired in start().
        self._reconciliation_runner: Any | None = None
        self._reconciliation_task: Any | None = None

        self._stop_event = asyncio.Event()
        self._shutdown_failed_event = asyncio.Event()
        self._shutdown_attempt = _ShutdownAttempt(self._shutdown_failed_event)

        logger.info("FlintTradeApp initialised — %s", self.version)

    async def _refresh_market_calendar(self) -> bool:
        """Refresh and apply one authoritative market-calendar payload."""
        calendar_year = _current_market_calendar_year()
        before_generation = getattr(self.cron, "holiday_generation", None)
        before_year = getattr(self.cron, "holiday_year", None)
        fail_closed = before_year != calendar_year
        calendar_invalidated = False
        if self._calendar_loaded and fail_closed:
            self._fail_closed_calendar_year(calendar_year)
            calendar_invalidated = True
        try:
            await self.cron.load_holidays()
        except Exception as exc:
            logger.warning(
                "Could not load holidays (OpenAlgo may be starting; %s)",
                type(exc).__name__,
            )
            if fail_closed and not calendar_invalidated:
                self._fail_closed_calendar_year(calendar_year)
            return False

        if self._stop_started:
            return False

        after_generation = getattr(self.cron, "holiday_generation", None)
        loaded_year = getattr(self.cron, "holiday_year", None)
        fresh_generation = (
            isinstance(before_generation, int)
            and isinstance(after_generation, int)
            and after_generation > before_generation
        )
        if not fresh_generation or loaded_year != calendar_year:
            if getattr(self, "_calendar_unauthoritative_warned", False):
                logger.debug(
                    "Market calendar refresh still not authoritative; retaining a fail-closed year"
                )
            else:
                logger.warning(
                    "Market calendar refresh did not produce current-year authority; retaining a fail-closed year"
                )
                self._calendar_unauthoritative_warned = True
            if fail_closed and not calendar_invalidated:
                self._fail_closed_calendar_year(calendar_year)
            return False

        calendar_payload = getattr(self.cron, "holiday_payload", None)
        if not isinstance(calendar_payload, dict | list | tuple | set):
            logger.warning("Market calendar was not returned; retaining the current calendar until retry")
            return False
        try:
            self.time_scheduler.set_holidays(
                calendar_payload,
                year=str(calendar_year),
            )
        except Exception as exc:
            logger.warning("Could not apply loaded market holidays (%s)", type(exc).__name__)
            self._fail_closed_calendar_year(calendar_year)
            return False
        self._calendar_loaded = True
        # Re-arm the one-shot warning so a later fall back to unauthoritative
        # (e.g. a broker disconnect) warns again on the state change.
        self._calendar_unauthoritative_warned = False
        if self._calendar_runtime_ready:
            self._start_calendar_schedulers()
        return True

    def _fail_closed_calendar_year(self, year: int) -> None:
        """Block calendar-gated work until an authoritative year is loaded."""
        blocked_dates = self.cron.fail_closed_calendar_year(year)
        self._calendar_loaded = False
        try:
            self.time_scheduler.set_holidays(blocked_dates, year=str(year))
        except Exception as exc:
            logger.error("Could not apply fail-closed market calendar (%s)", type(exc).__name__)
            if self._strategy_cron_started:
                self.strategy_cron_scheduler.stop()
                self._strategy_cron_started = False
                self._calendar_schedulers_started = False

    def _start_calendar_schedulers(
        self,
        startup_owners: _AcquiredOwnerLedger | None = None,
    ) -> None:
        """Start owned schedulers after calendar state is authoritative or blocked."""
        if self._calendar_schedulers_started:
            return
        if not self._strategy_cron_started:
            if startup_owners is not None:
                async def rollback_strategy_cron(_deadline: _LifecycleDeadline) -> bool:
                    await asyncio.to_thread(self.strategy_cron_scheduler.stop)
                    self._strategy_cron_started = False
                    self._calendar_schedulers_started = False
                    return True

                startup_owners.acquire("strategy cron scheduler", rollback_strategy_cron)
            # Ownership starts before the call: start() may raise after spawning
            # internal scheduler state, and a retry must not spawn a duplicate.
            self._strategy_cron_started = True
            self.strategy_cron_scheduler.start()
        if not self._cron_jobs_registered:
            self.cron.register_builtin_jobs()
            self._cron_jobs_registered = True
        if not self._cron_started:
            if startup_owners is not None:
                async def rollback_cron(_deadline: _LifecycleDeadline) -> bool:
                    await asyncio.to_thread(self.cron.stop)
                    self._cron_started = False
                    self._calendar_schedulers_started = False
                    return True

                startup_owners.acquire("cron scheduler", rollback_cron)
            self._cron_started = True
            self.cron.start()
        self._calendar_schedulers_started = (
            self._strategy_cron_started and self._cron_jobs_registered and self._cron_started
        )

    async def _market_calendar_refresh_loop(self, *, loaded: bool) -> None:
        """Retry failed loads promptly and refresh successful calendars daily."""
        while True:
            delay = _market_calendar_refresh_delay(loaded=loaded)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                return
            except TimeoutError:
                loaded = await self._refresh_market_calendar()

    async def _run_retained_sync_owner(
        self,
        key: str,
        operation: Callable[[], Any],
        deadline: _LifecycleDeadline,
        *,
        require_truthy: bool = False,
        require_live_deadline_for_success: bool = False,
    ) -> tuple[bool, str | None]:
        """Run or rejoin one synchronous owner cleanup within the deadline."""
        deadline_was_live = deadline.remaining() > 0.0
        workers = getattr(self, "_shutdown_sync_workers", None)
        if workers is None:
            workers = {}
            self._shutdown_sync_workers = workers
        worker = workers.get(key)
        if worker is None:
            worker = _RetainedSyncOwnerWorker(
                operation,
                name=f"flinttrade-stop-{key}",
            )
            workers[key] = worker
            try:
                worker.start()
            except BaseException as exc:  # noqa: BLE001 - no worker escaped
                workers.pop(key, None)
                return False, type(exc).__name__

        if not await worker.wait(deadline):
            return False, "TimeoutError"

        result, error = worker.outcome()
        if workers.get(key) is worker:
            workers.pop(key, None)
        if error is not None:
            return False, type(error).__name__
        if require_live_deadline_for_success and (
            not deadline_was_live or deadline.remaining() <= 0.0
        ):
            return False, "TimeoutError"
        if require_truthy and not bool(result):
            return False, "TimeoutError"
        return True, None

    async def _run_retained_async_owner(
        self,
        key: str,
        operation: Callable[[], Awaitable[Any]],
        deadline: _LifecycleDeadline,
        *,
        require_truthy: bool = False,
    ) -> tuple[bool, str | None]:
        """Run or rejoin one exact asyncio cleanup task within the deadline."""
        tasks = getattr(self, "_shutdown_async_tasks", None)
        if tasks is None:
            tasks = {}
            self._shutdown_async_tasks = tasks
        task = tasks.get(key)
        if task is None:
            task = asyncio.create_task(operation())
            tasks[key] = task

        done, _ = await asyncio.wait({task}, timeout=deadline.remaining())
        if task not in done:
            return False, "TimeoutError"

        if tasks.get(key) is task:
            tasks.pop(key, None)
        try:
            result = task.result()
        except BaseException as exc:  # noqa: BLE001 - owner error remains observable
            return False, type(exc).__name__
        if require_truthy and not bool(result):
            return False, "TimeoutError"
        return True, None

    async def _rollback_startup_dependencies(self, deadline: _LifecycleDeadline) -> bool:
        """Release shared dependencies only after every acquired owner quiesces."""
        flask_app = getattr(self, "_flask_app", None)

        async def stop_sync(
            key: str,
            label: str,
            operation: Callable[[], Any],
            *,
            require_truthy: bool = False,
        ) -> bool:
            stopped, error_type = await self._run_retained_sync_owner(
                key,
                operation,
                deadline,
                require_truthy=require_truthy,
            )
            if not stopped:
                logger.warning("Startup rollback for %s failed (%s)", label, error_type)
            return stopped

        async def stop_async(
            key: str,
            label: str,
            operation: Callable[[], Awaitable[Any]],
        ) -> bool:
            stopped, error_type = await self._run_retained_async_owner(
                key,
                operation,
                deadline,
            )
            if not stopped:
                logger.warning("Startup rollback for %s failed (%s)", label, error_type)
            return stopped

        if flask_app is not None:
            tracker = flask_app.config.get("RUNTIME_REQUEST_TRACKER")
            wait_for_idle = getattr(tracker, "wait_for_idle", None)
            if callable(wait_for_idle) and not await stop_sync(
                "startup-request-drain",
                "request drain",
                lambda: wait_for_idle(deadline.remaining()),
                require_truthy=True,
            ):
                return False

            from .agent_routes import shutdown_agent_runtime  # noqa: PLC0415
            from flinttrade_engine.strategy_routes import shutdown_strategy_runtime  # noqa: PLC0415

            if not await stop_sync(
                "startup-uploaded-strategies",
                "uploaded strategy runner",
                lambda: shutdown_strategy_runtime(flask_app),
            ):
                return False
            if not await stop_sync(
                "startup-autonomous-agent",
                "autonomous agent",
                lambda: shutdown_agent_runtime(flask_app, timeout=deadline.remaining()),
                require_truthy=True,
            ):
                return False
            if not await stop_sync(
                "startup-native-session-rotation",
                "native session rotation",
                lambda: _shutdown_rotation_scheduler(flask_app, timeout=deadline.remaining()),
            ):
                return False
            if not await stop_sync(
                "startup-ditto",
                "ditto runtime",
                lambda: shutdown_ditto_runtime(flask_app, timeout=deadline.remaining(5.0)),
                require_truthy=True,
            ):
                return False
            if not await stop_sync(
                "startup-broker-router",
                "broker router",
                lambda: retire_broker_router_generation(
                    flask_app,
                    timeout=deadline.remaining(10.0),
                ),
                require_truthy=True,
            ):
                return False

        if not await stop_async(
            "startup-scheduler",
            "scheduler",
            self.scheduler.stop_all,
        ):
            return False

        async def close_openalgo_client() -> None:
            if isinstance(self.client, OpenAlgoClient):
                await self.client.shutdown()
                return
            await self.client.close()

        client_closed = await stop_async(
            "startup-openalgo-client",
            "OpenAlgo client",
            close_openalgo_client,
        )
        audit_closed = await stop_sync(
            "startup-audit-logger",
            "audit logger",
            self.audit.close,
        )
        if client_closed and audit_closed:
            self._flask_app = None
            self._stop_completed = True
            self._stop_event.set()
            return True
        return False

    async def _recover_startup_rollback(self, deadline: _LifecycleDeadline) -> bool:
        """Retry the exact retained startup owner sequence and dependencies."""
        self._startup_rollback_in_progress = True
        try:
            flask_app = getattr(self, "_flask_app", None)
            ledger = getattr(self, "_startup_owner_ledger", None)
            if flask_app is not None:
                flask_app.config["RUNTIME_ACCEPTING_REQUESTS"] = False
                from .local_ai_routes import shutdown_local_ai_runtime  # noqa: PLC0415

                local_ai_stopped, local_ai_error = await self._run_retained_sync_owner(
                    "startup-managed-local-ai",
                    lambda: shutdown_local_ai_runtime(
                        flask_app,
                        timeout=deadline.remaining(5.0),
                    ),
                    deadline,
                    require_truthy=True,
                    require_live_deadline_for_success=True,
                )
                if local_ai_stopped:
                    local_ai_stopped = ledger is None or ledger.mark_released("managed local AI")
                if not local_ai_stopped:
                    logger.warning(
                        "Startup rollback for managed local AI failed (%s)",
                        local_ai_error or "RuntimeError",
                    )
                admission_closed, error_type = await self._run_retained_sync_owner(
                    "startup-request-admission",
                    lambda: _close_runtime_request_admission(flask_app),
                    deadline,
                )
                if not admission_closed:
                    logger.warning("Startup rollback for request admission failed (%s)", error_type)
                if not local_ai_stopped or not admission_closed:
                    self._startup_recovery_pending = True
                    return False
            owners_released = ledger is None or await ledger.rollback(deadline)
            dependencies_released = (
                await self._rollback_startup_dependencies(deadline)
                if owners_released
                else False
            )
            complete = bool(owners_released and dependencies_released)
            self._startup_recovery_pending = not complete
            if complete:
                self._startup_owner_ledger = None
            return complete
        finally:
            self._startup_rollback_in_progress = False

    async def start(self) -> None:
        """Start transactionally and retain every unproved rollback owner."""
        ledger = _AcquiredOwnerLedger()
        self._startup_owner_ledger = ledger
        try:
            await self._start_owned(ledger)
        except BaseException:
            if self._stop_started:
                raise
            flask_app = getattr(self, "_flask_app", None)
            raw_timeout = (
                flask_app.config.get("RUNTIME_STARTUP_ROLLBACK_TIMEOUT_SECONDS", 10.0)
                if flask_app is not None
                else 10.0
            )
            try:
                rollback_timeout = max(0.0, float(raw_timeout))
            except (TypeError, ValueError):
                rollback_timeout = 10.0
            deadline = _LifecycleDeadline.after(rollback_timeout)
            await self._recover_startup_rollback(deadline)
            raise

    async def _start_owned(self, startup_owners: _AcquiredOwnerLedger) -> None:
        """Start all services and wait until stopped under an owner ledger."""
        start_claim_lock = getattr(self, "_start_claim_lock", None)
        if start_claim_lock is None:
            start_claim_lock = threading.Lock()
            self._start_claim_lock = start_claim_lock
        with start_claim_lock:
            if getattr(self, "_start_claimed", False):
                raise RuntimeError("FlintTrade runtime already started")
            self._start_claimed = True

        if await self._wait_for_shutdown_if_started():
            return

        from .smart_order_routes import (  # noqa: PLC0415
            shutdown_smart_order_jobs,
            start_smart_order_jobs,
        )

        if not start_smart_order_jobs():
            raise RuntimeError("an earlier smart-order runtime still owns a worker")

        async def rollback_smart_orders(deadline: _LifecycleDeadline) -> bool:
            return bool(
                await asyncio.to_thread(
                    shutdown_smart_order_jobs,
                    timeout=deadline.remaining(30.0),
                )
            )

        startup_owners.acquire("smart-order admission", rollback_smart_orders)

        runtime_loop = asyncio.get_running_loop()
        self.scheduler.bind_runtime_loop(runtime_loop)
        self.safety.bind_runtime_loop(runtime_loop)

        # Start FlintTrade API server (Flask, configurable loopback port).
        flask_app = create_flask_app(
            safety=self.safety,
            safety_config_ready=self.safety_config_ready,
            scheduler=self.scheduler,
            cron=self.cron,
            audit=self.audit,
            client=self.client,
            registry=self.registry,
            credential_store=self.credential_store,
            contract_manager=self.contract_manager,
            rag=self.rag,
            cron_strategy_scheduler=self.strategy_cron_scheduler,
            time_scheduler=self.time_scheduler,
        )
        self._flask_app = flask_app
        from .local_ai_routes import (  # noqa: PLC0415
            shutdown_local_ai_runtime,
            start_configured_local_ai_runtime,
        )

        local_ai_started = start_configured_local_ai_runtime(flask_app)
        if local_ai_started:
            async def rollback_local_ai(deadline: _LifecycleDeadline) -> bool:
                return bool(
                    await asyncio.to_thread(
                        shutdown_local_ai_runtime,
                        flask_app,
                        timeout=deadline.remaining(5.0),
                    )
                )

            startup_owners.acquire("managed local AI", rollback_local_ai)
        _bind_runtime_emergency_dispatcher(
            flask_app,
            self.safety,
            self.telegram,
            self.client,
        )
        # Start polling only after /kill owns a current-router dispatcher. This
        # is a no-op unless Telegram has a token and authorised chat id.
        if self.telegram is not None:
            self.telegram.start_background()

            async def rollback_telegram(_deadline: _LifecycleDeadline) -> bool:
                await asyncio.to_thread(self.telegram.stop)
                return True

            startup_owners.acquire("Telegram", rollback_telegram)
        tick_capture_enabled = _tick_capture_enabled()
        _set_tick_capture_intent(flask_app, tick_capture_enabled)
        flask_server_owner = _run_flask_server(
            flask_app,
            port=_resolve_backend_port(),
            host=_resolve_backend_host(),
        )
        self._flask_server_owner = flask_server_owner
        if flask_server_owner is not None:
            async def rollback_flask_listener(deadline: _LifecycleDeadline) -> bool:
                stopped = bool(
                    await asyncio.to_thread(
                        flask_server_owner.stop,
                        timeout=deadline.remaining(),
                    )
                )
                if stopped and self._flask_server_owner is flask_server_owner:
                    self._flask_server_owner = None
                return stopped

            startup_owners.acquire("Flask API listener", rollback_flask_listener)

        # Load the market calendar once, then keep retrying failed loads and
        # refresh it daily so year rollover and newly-published sessions apply.
        calendar_loaded = await self._refresh_market_calendar()

        if await self._wait_for_shutdown_if_started():
            return

        self._holiday_refresh_task = asyncio.create_task(self._market_calendar_refresh_loop(loaded=calendar_loaded))

        async def rollback_holiday_refresh(deadline: _LifecycleDeadline) -> bool:
            task = self._holiday_refresh_task
            if task is None:
                return True
            joined, error = await _join_cancelled_task(task, deadline)
            if not joined:
                return False
            self._holiday_refresh_task = None
            return error is None

        startup_owners.acquire("market calendar refresh", rollback_holiday_refresh)

        # Hand the cron manager the shared trade store (created by the Flask
        # factory above) so the nightly DuckDB maintenance job can CHECKPOINT +
        # ANALYZE the same connection under its lock.
        self.cron.trade_storage = flask_app.config.get("TRADE_STORAGE")
        self.cron.trade_storage_lock = flask_app.config.get("TRADE_STORAGE_LOCK")
        # Post-market daily reports persist to their own DuckDB file — never
        # the trade store's (one read-write connection per DuckDB file).
        self.cron.post_market_report_db = str(_workspace_dir() / "post_market_reports.duckdb")
        webhook_secret_store = flask_app.config.get("WEBHOOK_SECRET_STORE")
        self.cron.webhook_nonce_gc = getattr(webhook_secret_store, "gc_nonces", None)

        # Wire the "optimise overnight" feature to a real engine. The cron slot
        # (make_overnight_optimise_job) existed but nothing injected an optimiser,
        # so the nightly job never ran. Build an OvernightOptimiser over the
        # registered strategies + a rule-based StrategyRefiner and inject its
        # run() as the job. Best-effort: a missing runner/refiner just leaves the
        # job unregistered (as before) rather than failing boot.
        try:
            from flinttrade_ai.optimiser_report_store import OptimiserReportStore  # noqa: PLC0415
            from flinttrade_ai.overnight_optimiser import (  # noqa: PLC0415
                OvernightOptimiser,
                enrich_strategies,
            )
            from flinttrade_ai.strategy_refiner import StrategyRefiner  # noqa: PLC0415
            from flinttrade_backtest.result_store import BacktestResultStore  # noqa: PLC0415

            # The report store is created unconditionally so the Lab UI can read
            # past reports even when the optimiser isn't wired this boot.
            _report_store = OptimiserReportStore(_workspace_dir() / "optimiser-reports")
            flask_app.config["OPTIMISER_REPORT_STORE"] = _report_store

            # Per-strategy backtest-results store: written on every backtest run
            # (backtest_routes), read here so the optimiser refines on REAL
            # metrics instead of an empty dict. Before this the refiner only ever
            # saw {} and produced generic rule-based output (R16).
            _bt_result_store = BacktestResultStore(_workspace_dir() / "backtest-results")
            flask_app.config["BACKTEST_RESULT_STORE"] = _bt_result_store

            _runner = flask_app.config.get("STRATEGY_RUNNER")

            def _strategy_provider() -> list[dict[str, Any]]:
                """Live roster joined to each strategy's latest backtest metrics."""
                roster: list[dict[str, Any]] = []
                if _runner is not None and hasattr(_runner, "list_strategies"):
                    try:
                        roster = _runner.list_strategies()
                    except Exception:  # noqa: BLE001 - a broken runner falls back to stored-only
                        roster = []
                return enrich_strategies(roster, _bt_result_store)

            # Wired unconditionally now: even with no uploaded strategies, any
            # strategy that has been backtested gets refined overnight.
            _optimiser = OvernightOptimiser(
                strategy_provider=_strategy_provider,
                refiner=StrategyRefiner(),  # rule-based by default (no LLM required)
                report_sink=_report_store.write,  # persist each night's report
            )
            self.cron.overnight_optimiser = _optimiser.run
        except Exception as exc:
            logger.warning(
                "Overnight optimiser not wired (%s); nightly optimisation will not run",
                type(exc).__name__,
            )

        # EOD historical-data auto-sync (opt-in via workspace.json
        # data.auto_sync.enabled). Reuses the SAME start_watchlist_download core
        # the Settings download button calls — one download path.
        if _auto_sync_enabled():
            try:
                from datetime import date as _date  # noqa: PLC0415
                from datetime import timedelta as _timedelta  # noqa: PLC0415

                from flinttrade_historical.watchlist_routes import (  # noqa: PLC0415
                    start_watchlist_download,
                )

                lookback = _auto_sync_lookback_days()

                def _start_eod_sync() -> Any:
                    today = _date.today()
                    return start_watchlist_download(today - _timedelta(days=lookback), today)

                self.cron.eod_sync_starter = _start_eod_sync
                logger.info("EOD auto-sync wired (lookback %d days)", lookback)
            except Exception as exc:
                logger.warning(
                    "EOD auto-sync not wired (%s); scheduled sync will not run",
                    type(exc).__name__,
                )

        # Scheduled LightGBM/EMA signal source. The app factory has already
        # connected its output to the canonical rule+ML signal hub. Registering
        # here places the cycle under the same observable CronManager as every
        # other background job and keeps it fail-closed outside NSE hours.
        try:
            _wire_ml_signal_runtime(flask_app, self.cron, self.time_scheduler)
        except Exception as exc:
            logger.warning("Scheduled ML signals not wired (%s)", type(exc).__name__)

        # Register built-in cron jobs AND start the scheduler. Without start()
        # APScheduler never runs, so none of the built-in jobs fire — the
        # nightly DuckDB CHECKPOINT+ANALYZE (db_optimise_job), square-off
        # warning, EOD logout, and health check were all inert. Wrapped so a
        # missing/broken APScheduler degrades to "no cron" instead of failing
        # the whole boot.
        self._calendar_runtime_ready = True
        try:
            self._start_calendar_schedulers(startup_owners)
        except Exception as exc:
            logger.warning(
                "Calendar-owned schedulers failed to start (%s); scheduled jobs will not run",
                type(exc).__name__,
            )
        if not calendar_loaded:
            logger.warning(
                "Market calendar unavailable; schedulers started with the current year blocked until retry"
            )

        # Live tick capture (opt-in). Uses its OWN StorageManager (a separate
        # DuckDB file) so the recorder's async-loop writes never share a
        # connection with the Flask-thread trade journal (DuckDB connections are
        # not safe for concurrent use). Launched as a background task on this
        # loop; auto-reconnects to the OpenAlgo WebSocket.
        if tick_capture_enabled:
            tick_storage: Any | None = None
            tick_lock: Any | None = None
            recorder: Any | None = None
            recorder_task: asyncio.Task[Any] | None = None
            checkpoint_owner: _OrderFlowCheckpointOwner | None = None
            storage_close_worker: _BoundedTickStorageCloseWorker | None = None
            capture_api_key = self.settings.openalgo_api_key
            try:
                from flinttrade_data.storage import StorageManager as _TickStore  # noqa: PLC0415
                from flinttrade_data.tick_recorder import TickRecorder  # noqa: PLC0415

                tick_db = str(_workspace_dir() / "ticks.duckdb")
                tick_storage = _TickStore(tick_db)
                tick_storage.initialise()
                # One lock guards this tick store's single DuckDB connection: the
                # recorder writes on the async loop, the nightly db_optimise job
                # CHECKPOINTs it on the scheduler thread. Both must serialise.
                tick_lock = threading.Lock()
                # Live order-flow aggregator: fed from each tick and exposed to
                # the orderflow route so the footprint widget shows REAL buy/sell
                # delta (not synthetic) while tick capture is running.
                from flinttrade_data.orderflow_aggregator import (  # noqa: PLC0415
                    create_live_market_orderflow_aggregator,
                )

                orderflow = create_live_market_orderflow_aggregator()
                with _tick_capture_lifecycle_lock(flask_app):
                    # The Flask server is already accepting local setup requests.
                    # Refresh inside the lifecycle lock so a concurrent config save
                    # either precedes this build or reconfigures the published recorder.
                    capture_settings = Settings.from_env()
                    capture_api_key = capture_settings.openalgo_api_key
                    watchlist = _tick_capture_watchlist()
                    signal_hub = flask_app.config.get("SIGNAL_HUB")
                    checkpoint_owner = _OrderFlowCheckpointOwner(
                        tick_storage,
                        orderflow,
                        workspace_dir=_workspace_dir(),
                        storage_lock=tick_lock,
                    )
                    restore_summary = _prepare_tick_orderflow_state(
                        tick_storage,
                        orderflow,
                        watchlist,
                        storage_lock=tick_lock,
                        retention_days=90,
                        checkpoint_owner=checkpoint_owner,
                    )
                    recorder = _build_tick_recorder(
                        recorder_factory=TickRecorder,
                        signal_hub=signal_hub,
                        sandbox_engine=flask_app.config.get("DATA_SANDBOX_ENGINE"),
                        settings=capture_settings,
                        storage=tick_storage,
                        storage_lock=tick_lock,
                        orderflow=orderflow,
                        watchlist=watchlist,
                        mode=_tick_capture_mode(),
                        post_flush_callback=checkpoint_owner.persist_locked,
                    )
                    recorder_task = asyncio.create_task(recorder.run())
                    self._tick_recorder = recorder
                    self._tick_recorder_task = recorder_task
                    self._tick_storage = tick_storage
                    self._tick_storage_lock = tick_lock
                    self._orderflow_checkpoint_owner = checkpoint_owner

                    def clear_closed_storage() -> None:
                        with _tick_capture_lifecycle_lock(flask_app):
                            if self._tick_storage is tick_storage:
                                self._tick_recorder = None
                                self._tick_storage = None
                                self._tick_storage_lock = None
                                self._orderflow_checkpoint_owner = None
                                if self._tick_storage_close_worker is storage_close_worker:
                                    self._tick_storage_close_worker = None

                    storage_close_worker = _build_tick_storage_close_worker(
                        recorder,
                        tick_storage,
                        tick_lock,
                        checkpoint_owner,
                        on_success=clear_closed_storage,
                    )
                    self._tick_storage_close_worker = storage_close_worker
                    # Hand the tick store to the cron so nightly maintenance keeps the
                    # highest-volume DuckDB file from growing unbounded. register_
                    # builtin_jobs already ran, but the job resolves this lazily.
                    self.cron.tick_storage = tick_storage
                    self.cron.tick_storage_lock = tick_lock
                    # Keep ~90 days of ticks by default so the store stays bounded;
                    # the nightly tick_retention_job prunes older rows.
                    self.cron.tick_retention_days = 90
                    # Expose the recorder + store to the tick routes (status /
                    # query / watchlist) so the terminal can see and manage capture.
                    flask_app.config["ORDERFLOW_AGGREGATOR"] = orderflow
                    flask_app.config["TICK_RECORDER"] = recorder
                    flask_app.config["TICK_STORAGE"] = tick_storage
                    flask_app.config["TICK_STORAGE_LOCK"] = tick_lock
                    flask_app.config["TICK_CAPTURE_ERROR"] = ""

                    def handle_recorder_completion(
                        completed: Any,
                        active: Any = recorder,
                        key: str = capture_settings.openalgo_api_key,
                    ) -> None:
                        def unpublish_runtime_handles() -> None:
                            self._tick_recorder_task = None
                            self.cron.tick_storage = None
                            self.cron.tick_storage_lock = None

                        _handle_tick_recorder_completion(
                            flask_app,
                            active,
                            completed,
                            api_key=key,
                            is_shutting_down=lambda: (
                                self._stop_started or self._startup_rollback_in_progress
                            ),
                            on_unpublished=unpublish_runtime_handles,
                            close_worker=storage_close_worker,
                        )

                    recorder_task.add_done_callback(handle_recorder_completion)
                logger.info(
                    "Live tick capture started → %s (pruned=%d restored=%d restore_failures=%d)",
                    tick_db,
                    restore_summary["pruned_ticks"],
                    restore_summary["restored_ticks"],
                    restore_summary["restore_failures"],
                )

                async def rollback_tick_capture(deadline: _LifecycleDeadline) -> bool:
                    return await _rollback_tick_capture_startup(
                        self,
                        flask_app,
                        recorder=recorder,
                        recorder_task=recorder_task,
                        storage=tick_storage,
                        storage_lock=tick_lock,
                        checkpoint_owner=checkpoint_owner,
                        close_worker=storage_close_worker,
                        startup_error=RuntimeError("application startup rolled back"),
                        api_key=capture_api_key,
                        deadline=deadline,
                    )

                startup_owners.acquire("tick recorder", rollback_tick_capture)
            except Exception as exc:
                rollback_complete = await _rollback_tick_capture_startup(
                    self,
                    flask_app,
                    recorder=recorder,
                    recorder_task=recorder_task,
                    storage=tick_storage,
                    storage_lock=tick_lock,
                    checkpoint_owner=checkpoint_owner,
                    close_worker=storage_close_worker,
                    startup_error=exc,
                    api_key=capture_api_key,
                )
                if not rollback_complete:
                    raise RuntimeError("tick capture startup rollback incomplete") from exc

        if await self._wait_for_shutdown_if_started():
            return

        # Broker reconciliation runner (contract §14.2): reconciles every ACTIVE
        # native (adapter, session) pair on start and then every
        # Capabilities.reconcile_recommended_seconds — persisting JSONL under
        # <home>/reconciliation/<broker>/<account>.jsonl and auditing
        # RECONCILIATION_MISMATCH on drift. Launched as a background task on
        # this loop (mirrors the tick recorder): never blocks boot, polls so
        # sessions established after boot are picked up, cancelled in stop().
        try:
            if flask_app.config.get("RECONCILE_TARGETS") is not None:
                from flinttrade_engine.reconciliation_runner import ReconciliationRunner  # noqa: PLC0415

                _reconciler = ReconciliationRunner(
                    lambda: _current_reconcile_targets(flask_app),
                    audit_logger=self.audit,
                    state_recorder=lambda **snapshot: _record_current_reconcile_snapshot(
                        flask_app,
                        **snapshot,
                    ),
                )
                self._reconciliation_runner = _reconciler
                self._reconciliation_task = asyncio.create_task(_reconciler.run())
                # Exposed on app.config for observability/manual-trigger routes.
                flask_app.config["RECONCILIATION_RUNNER"] = _reconciler

                async def rollback_reconciliation(deadline: _LifecycleDeadline) -> bool:
                    _reconciler.stop()
                    task = self._reconciliation_task
                    if task is None:
                        return True
                    joined, error = await _join_cancelled_task(task, deadline)
                    if not joined:
                        return False
                    self._reconciliation_task = None
                    self._reconciliation_runner = None
                    flask_app.config.pop("RECONCILIATION_RUNNER", None)
                    return error is None

                startup_owners.acquire("reconciliation", rollback_reconciliation)
            else:
                logger.info("Reconciliation runner inactive — broker routing was not built this boot")
        except Exception as exc:
            logger.warning(
                "Reconciliation runner failed to start (%s); broker reconciliation inactive",
                type(exc).__name__,
            )

        # Broker SDK attestation — log which native broker SDKs match brokers.lock
        # so the operator can see what is / isn't ready to go live. No native
        # adapter is wired into the router yet, so this is informational here;
        # the halt loop (attest_loop + on_failure) is ready for when they are.
        try:
            from .broker_sdk_attest import attest_all, log_report  # noqa: PLC0415

            log_report(attest_all())
        except Exception as exc:  # pragma: no cover - never let attestation break boot
            logger.warning("Broker SDK attestation failed (%s)", type(exc).__name__)

        # Verify OpenAlgo connectivity (non-fatal). Distinguish three
        # cases so the boot log is not misleading: REACHABLE_AUTHENTICATED,
        # REACHABLE_AUTH_FAILED, UNREACHABLE.
        try:
            import httpx  # noqa: PLC0415
            from .exceptions import OpenAlgoAuthError  # noqa: PLC0415

            try:
                result = await self.client.ping()
                broker = result.get("data", {}).get("broker", "unknown") if isinstance(result, dict) else "unknown"
                logger.info(
                    "FlintTrade %s started — OpenAlgo %s REACHABLE, authenticated (broker: %s)",
                    self.version,
                    self.settings.openalgo_host,
                    broker,
                )
            except OpenAlgoAuthError as exc:
                # Server responded but rejected the API key — reachable,
                # auth failed.  Don't confuse users with "UNREACHABLE".
                logger.warning(
                    "FlintTrade %s started — OpenAlgo %s REACHABLE but AUTH FAILED "
                    "(status %d; %s). Configure the API key in /setup or ~/.flinttrade/workspace.json.",
                    self.version,
                    self.settings.openalgo_host,
                    exc.status_code,
                    type(exc).__name__,
                )
            except (httpx.ConnectError, httpx.TimeoutException, OSError) as exc:
                logger.warning(
                    "FlintTrade %s started — OpenAlgo %s UNREACHABLE (%s). "
                    "Start OpenAlgo on that host/port and FlintTrade will reconnect on next call.",
                    self.version,
                    self.settings.openalgo_host,
                    type(exc).__name__,
                )
        except Exception as exc:
            logger.warning(
                "FlintTrade %s started — OpenAlgo %s verification failed (%s).",
                self.version,
                self.settings.openalgo_host,
                type(exc).__name__,
            )

        # Wait for either successful teardown or a fail-closed shutdown error.
        await self._wait_for_shutdown_result()

    async def _wait_for_shutdown_result(self) -> None:
        """Wait for shutdown completion and propagate a failed attempt."""
        failed_event = getattr(self, "_shutdown_failed_event", None)
        if failed_event is None:
            failed_event = asyncio.Event()
            self._shutdown_failed_event = failed_event
        shutdown_task = getattr(self, "_shutdown_task", None)
        attempt = getattr(self, "_shutdown_attempt", None)
        if (
            attempt is None
            or attempt.failed_event is not failed_event
            or (shutdown_task is not None and attempt.task is not shutdown_task)
        ):
            attempt = _ShutdownAttempt(failed_event, shutdown_task)
            self._shutdown_attempt = attempt
        stopped = asyncio.create_task(self._stop_event.wait())
        failed = asyncio.create_task(attempt.failed_event.wait())
        try:
            await asyncio.wait(
                {stopped, failed},
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for waiter in (stopped, failed):
                if not waiter.done():
                    waiter.cancel()
            await asyncio.gather(stopped, failed, return_exceptions=True)
        if attempt.failed_event.is_set():
            if attempt.task is not None:
                await asyncio.shield(attempt.task)
            raise RuntimeError("shutdown failed before completion")

    async def _wait_for_shutdown_if_started(self) -> bool:
        """Let an in-progress stop retain ownership across startup await points."""
        if not self._stop_started:
            return False
        await self._wait_for_shutdown_result()
        return True

    async def _run_shutdown_attempt(
        self,
        attempt: _ShutdownAttempt,
        deadline: _LifecycleDeadline,
    ) -> None:
        """Publish failure from the owned task, independent of awaiting callers."""
        self._active_shutdown_deadline = deadline
        try:
            await self._stop_once()
        except BaseException:
            attempt.failed_event.set()
            raise
        finally:
            if self._active_shutdown_deadline is deadline:
                self._active_shutdown_deadline = None

    async def stop(self, *, timeout: float | None = None) -> None:
        """Gracefully shut down all services, sharing concurrent attempts."""
        if getattr(self, "_stop_completed", False):
            return

        flask_app = getattr(self, "_flask_app", None)
        raw_timeout = (
            flask_app.config.get("RUNTIME_SHUTDOWN_TIMEOUT_SECONDS", 60.0)
            if flask_app is not None
            else 60.0
        )
        if timeout is not None:
            raw_timeout = timeout
        try:
            shutdown_timeout = max(0.0, float(raw_timeout))
        except (TypeError, ValueError):
            shutdown_timeout = 60.0
        caller_deadline = _LifecycleDeadline.after(shutdown_timeout)

        task = getattr(self, "_shutdown_task", None)
        attempt = getattr(self, "_shutdown_attempt", None)
        created_task = False
        if task is None or task.done():
            stop_event = getattr(self, "_stop_event", None)
            clear_stop_event = getattr(stop_event, "clear", None)
            if callable(clear_stop_event):
                clear_stop_event()
            if attempt is None or attempt.task is not None or attempt.failed_event.is_set():
                attempt = _ShutdownAttempt(asyncio.Event())
            task = asyncio.create_task(self._run_shutdown_attempt(attempt, caller_deadline))
            attempt.task = task
            self._shutdown_attempt = attempt
            self._shutdown_failed_event = attempt.failed_event
            self._shutdown_task = task
            created_task = True
        elif attempt is None or attempt.task is not task:
            failed_event = getattr(self, "_shutdown_failed_event", None)
            if failed_event is None:
                failed_event = asyncio.Event()
                self._shutdown_failed_event = failed_event
            attempt = _ShutdownAttempt(failed_event, task)
            self._shutdown_attempt = attempt
        if created_task:
            await asyncio.shield(task)
            return
        done, _ = await asyncio.wait({task}, timeout=caller_deadline.remaining())
        if task not in done:
            raise RuntimeError("shutdown exceeded its absolute deadline")
        await asyncio.shield(task)

    async def _stop_once(self) -> None:
        """Run one complete, best-effort shutdown attempt."""
        self._stop_started = True
        flask_app = getattr(self, "_flask_app", None)
        logger.info("FlintTrade shutting down...")
        errors: list[tuple[str, str]] = []
        deferred_errors: list[tuple[str, str]] = []
        deadline = getattr(self, "_active_shutdown_deadline", None)
        if deadline is None:
            deadline = _LifecycleDeadline.after(60.0)
        if getattr(self, "_startup_recovery_pending", False):
            if not await self._recover_startup_rollback(deadline):
                raise RuntimeError("shutdown encountered errors: startup rollback incomplete")
            return

        async def stop_sync(
            key: str,
            label: str,
            operation: Callable[[], Any],
            *,
            require_truthy: bool = False,
            require_live_deadline_for_success: bool = False,
        ) -> bool:
            stopped, error_type = await self._run_retained_sync_owner(
                key,
                operation,
                deadline,
                require_truthy=require_truthy,
                require_live_deadline_for_success=require_live_deadline_for_success,
            )
            if not stopped:
                errors.append((label, error_type or "RuntimeError"))
            return stopped

        async def stop_async(
            key: str,
            label: str,
            operation: Callable[[], Awaitable[Any]],
            *,
            require_truthy: bool = False,
        ) -> bool:
            stopped, error_type = await self._run_retained_async_owner(
                key,
                operation,
                deadline,
                require_truthy=require_truthy,
            )
            if not stopped:
                errors.append((label, error_type or "RuntimeError"))
            return stopped

        def configured_budget(config_key: str, default: float) -> float:
            if flask_app is None:
                return deadline.remaining(default)
            raw_timeout = flask_app.config.get(config_key, default)
            try:
                owner_timeout = max(0.0, float(raw_timeout))
            except (TypeError, ValueError):
                owner_timeout = default
            return deadline.remaining(owner_timeout)

        managed_local_ai_teardown_attempted = False

        async def stop_managed_local_ai() -> None:
            nonlocal managed_local_ai_teardown_attempted
            if flask_app is None or managed_local_ai_teardown_attempted:
                return
            managed_local_ai_teardown_attempted = True
            from .local_ai_routes import shutdown_local_ai_runtime  # noqa: PLC0415

            await stop_sync(
                "managed-local-ai",
                "managed local AI",
                lambda: shutdown_local_ai_runtime(
                    flask_app,
                    timeout=configured_budget("LOCAL_AI_SHUTDOWN_TIMEOUT_SECONDS", 5.0),
                ),
                require_truthy=True,
                require_live_deadline_for_success=True,
            )

        request_tracker = None
        if flask_app is not None:
            # The Flask flag is the synchronous outer fail-closed barrier. The
            # tracker callback may block, so it runs as a retained owner.
            flask_app.config["RUNTIME_ACCEPTING_REQUESTS"] = False
            # Stop the child sidecar before another retained owner can consume
            # its process-tree termination budget. Existing inference receives
            # the runtime's bounded grace period before forced teardown.
            await stop_managed_local_ai()
            request_tracker = flask_app.config.get("RUNTIME_REQUEST_TRACKER")
            await stop_sync(
                "request-admission",
                "request admission",
                lambda: _close_runtime_request_admission(flask_app),
            )

            # Waitress cannot join a worker that is still blocked inside an SSE
            # iterator. Wake both stream families before closing the listener.
            from .log_stream import shutdown_log_streams  # noqa: PLC0415

            await stop_sync(
                "log-streams",
                "log stream",
                lambda: shutdown_log_streams(flask_app),
            )
            for label, config_key in (
                ("signal stream", "SIGNAL_STREAM_SHUTDOWN_EVENT"),
                ("signal retraining cancellation", "ML_SIGNAL_RETRAIN_CANCEL_EVENT"),
            ):
                shutdown_event = flask_app.config.get(config_key)
                set_event = getattr(shutdown_event, "set", None)
                if callable(set_event):
                    try:
                        set_event()
                    except Exception as exc:  # noqa: BLE001 - continue independent owners
                        errors.append((label, type(exc).__name__))

        flask_server_owner = getattr(self, "_flask_server_owner", None)
        if flask_server_owner is not None:
            listener_stopped = await stop_sync(
                "flask-listener",
                "Flask API listener",
                lambda: flask_server_owner.stop(timeout=deadline.remaining()),
                require_truthy=True,
            )
            if listener_stopped and self._flask_server_owner is flask_server_owner:
                self._flask_server_owner = None

        strategy_cron_scheduler = getattr(self, "strategy_cron_scheduler", None)
        strategy_cron_stopped = (
            await stop_sync(
                "strategy-cron",
                "strategy cron scheduler",
                strategy_cron_scheduler.stop,
            )
            if strategy_cron_scheduler is not None
            else True
        )
        cron_stopped = True
        telegram_stopped = True

        # Background writers are not represented by a short request handler.
        # Quiesce them before waiting on the request tracker so a tick recorder
        # cannot miss its final flush on timeout.
        if flask_app is not None:
            retrainer = flask_app.config.get("ML_SIGNAL_RETRAINER")
            wait_for_fetch_owner = getattr(retrainer, "wait_for_fetch_owner", None)
            if callable(wait_for_fetch_owner):
                await stop_sync(
                    "signal-retraining",
                    "signal retraining fetch owner",
                    lambda: wait_for_fetch_owner(
                        timeout=configured_budget(
                            "ML_SIGNAL_RETRAIN_SHUTDOWN_TIMEOUT_SECONDS",
                            30.0,
                        )
                    ),
                    require_truthy=True,
                )

            cron_stopped = await stop_sync("cron", "cron", self.cron.stop)
            telegram = getattr(self, "telegram", None)
            telegram_stopped = (
                await stop_sync("telegram", "telegram", telegram.stop)
                if telegram is not None
                else True
            )

            from .agent_routes import shutdown_agent_runtime  # noqa: PLC0415
            from .smart_order_routes import shutdown_smart_order_jobs  # noqa: PLC0415
            from flinttrade_engine.strategy_routes import (  # noqa: PLC0415
                shutdown_strategy_runtime,
            )

            uploaded_strategies_stopped = await stop_sync(
                "uploaded-strategies-quiesce",
                "uploaded strategy runner",
                lambda: shutdown_strategy_runtime(flask_app),
            )
            registered_strategies_stopped = await stop_async(
                "scheduler-quiesce",
                "scheduler",
                self.scheduler.stop_all,
            )
            live_write_owners_stopped = (
                strategy_cron_stopped
                and cron_stopped
                and telegram_stopped
                and uploaded_strategies_stopped
                and registered_strategies_stopped
            )
            smart_stopped = await stop_sync(
                "smart-orders",
                "smart-order jobs",
                lambda: shutdown_smart_order_jobs(
                    timeout=configured_budget("SMART_ORDER_SHUTDOWN_TIMEOUT_SECONDS", 30.0)
                ),
                require_truthy=True,
            )
            live_write_owners_stopped = live_write_owners_stopped and smart_stopped

            agent_stopped = await stop_sync(
                "autonomous-agent",
                "autonomous agent",
                lambda: shutdown_agent_runtime(
                    flask_app,
                    timeout=configured_budget(
                        "AUTONOMOUS_AGENT_SHUTDOWN_TIMEOUT_SECONDS",
                        30.0,
                    ),
                ),
                require_truthy=True,
            )
            live_write_owners_stopped = live_write_owners_stopped and agent_stopped

            rotation_stopped = await stop_sync(
                "native-session-rotation",
                "native session rotation scheduler",
                lambda: _shutdown_rotation_scheduler(
                    flask_app,
                    timeout=configured_budget(
                        "NATIVE_ROTATION_SHUTDOWN_TIMEOUT_SECONDS",
                        30.0,
                    ),
                ),
            )
            live_write_owners_stopped = live_write_owners_stopped and rotation_stopped

            ditto_stopped = await stop_sync(
                "ditto-quiesce",
                "ditto runtime",
                lambda: shutdown_ditto_runtime(
                    flask_app,
                    timeout=configured_budget("DITTO_SHUTDOWN_TIMEOUT_SECONDS", 5.0),
                ),
                require_truthy=True,
            )
            live_write_owners_stopped = live_write_owners_stopped and ditto_stopped

            if live_write_owners_stopped:
                await stop_sync(
                    "broker-router-quiesce",
                    "broker router",
                    lambda: retire_broker_router_generation(
                        flask_app,
                        timeout=deadline.remaining(10.0),
                    ),
                    require_truthy=True,
                )

        else:
            cron_stopped = await stop_sync("cron", "cron", self.cron.stop)
            telegram = getattr(self, "telegram", None)
            telegram_stopped = (
                await stop_sync("telegram", "telegram", telegram.stop)
                if telegram is not None
                else True
            )
            await stop_async("scheduler-quiesce", "scheduler", self.scheduler.stop_all)

        tick_recorder = self._tick_recorder
        tick_task = self._tick_recorder_task
        tick_storage = getattr(self, "_tick_storage", None)
        tick_storage_lock = getattr(self, "_tick_storage_lock", None)
        checkpoint_owner = getattr(self, "_orderflow_checkpoint_owner", None)
        tick_storage_close_worker = getattr(self, "_tick_storage_close_worker", None)

        holiday_refresh_task = getattr(self, "_holiday_refresh_task", None)
        if holiday_refresh_task is not None:
            joined, task_error = await _join_cancelled_task(holiday_refresh_task, deadline)
            if not joined:
                errors.append(("market calendar refresh", "TimeoutError"))
            else:
                self._holiday_refresh_task = None
                if task_error is not None:
                    errors.append(("market calendar refresh", type(task_error).__name__))

        if tick_recorder is not None:
            await stop_sync("tick-recorder", "tick recorder", tick_recorder.stop)
        if tick_task is not None:
            joined, task_error = await _join_cancelled_task(tick_task, deadline)
            if not joined:
                errors.append(("tick recorder task", "TimeoutError"))
            else:
                self._tick_recorder_task = None
            if joined and task_error is not None:
                sanitise_error = getattr(tick_recorder, "sanitise_error", None)
                try:
                    diagnostic = (
                        sanitise_error(task_error)
                        if callable(sanitise_error)
                        else type(task_error).__name__
                    )
                except Exception:  # pragma: no cover - diagnostics must not block shutdown
                    diagnostic = type(task_error).__name__
                logger.warning(
                    "Tick recorder task ended with an error during shutdown (%s)",
                    diagnostic,
                )
                if tick_storage is None:
                    deferred_errors.append(("tick recorder task", type(task_error).__name__))

        # Reconciliation is an independent producer. Always quiesce it even if
        # request-admission tracking failed, but retain its exact task on timeout.
        reconciliation_runner = self._reconciliation_runner
        reconciliation_task = self._reconciliation_task
        reconciliation_stopped = True
        if reconciliation_runner is not None:
            reconciliation_stopped = await stop_sync(
                "reconciliation-runner",
                "reconciliation runner",
                reconciliation_runner.stop,
            )
        if reconciliation_stopped and reconciliation_task is not None:
            joined, task_error = await _join_cancelled_task(reconciliation_task, deadline)
            if not joined:
                errors.append(("reconciliation task", "TimeoutError"))
            else:
                if self._reconciliation_task is reconciliation_task:
                    self._reconciliation_task = None
                if self._reconciliation_runner is reconciliation_runner:
                    self._reconciliation_runner = None
                if (
                    flask_app is not None
                    and flask_app.config.get("RECONCILIATION_RUNNER") is reconciliation_runner
                ):
                    flask_app.config.pop("RECONCILIATION_RUNNER", None)
                if task_error is not None:
                    errors.append(("reconciliation task", type(task_error).__name__))
        elif reconciliation_stopped and reconciliation_runner is not None:
            if self._reconciliation_runner is reconciliation_runner:
                self._reconciliation_runner = None
            if (
                flask_app is not None
                and flask_app.config.get("RECONCILIATION_RUNNER") is reconciliation_runner
            ):
                flask_app.config.pop("RECONCILIATION_RUNNER", None)

        if errors:
            await stop_managed_local_ai()
            summary = ", ".join(f"{label} ({error_type})" for label, error_type in errors)
            logger.error("FlintTrade shutdown quiesce failed: %s", summary)
            raise RuntimeError(f"shutdown encountered errors: {summary}")

        if request_tracker is not None:
            wait_for_idle = getattr(request_tracker, "wait_for_idle", None)
            drained = (
                await stop_sync(
                    "request-drain",
                    "active requests",
                    lambda: wait_for_idle(
                        configured_budget("RUNTIME_REQUEST_DRAIN_TIMEOUT_SECONDS", 60.0)
                    ),
                    require_truthy=True,
                )
                if callable(wait_for_idle)
                else True
            )
            if not drained:
                # Do not close any dependency while a handler still owns it. A
                # later stop() retry can complete teardown after the request
                # leaves; the process exits non-zero if it never does.
                logger.error("FlintTrade shutdown timed out draining active requests")

        if errors:
            await stop_managed_local_ai()
            summary = ", ".join(f"{label} ({error_type})" for label, error_type in errors)
            logger.error("FlintTrade shutdown request drain failed: %s", summary)
            raise RuntimeError(f"shutdown encountered errors: {summary}")

        if flask_app is not None:
            from flinttrade_engine.strategy_routes import (  # noqa: PLC0415
                shutdown_strategy_runtime,
            )

            uploaded_stopped = await stop_sync(
                "uploaded-strategies-drained",
                "uploaded strategy runner after request drain",
                lambda: shutdown_strategy_runtime(flask_app),
            )
            registered_stopped = await stop_async(
                "scheduler-drained",
                "scheduler after request drain",
                self.scheduler.stop_all,
            )
            ditto_stopped = await stop_sync(
                "ditto-drained",
                "ditto runtime after request drain",
                lambda: shutdown_ditto_runtime(
                    flask_app,
                    timeout=configured_budget("DITTO_SHUTDOWN_TIMEOUT_SECONDS", 5.0),
                ),
                require_truthy=True,
            )
            if uploaded_stopped and registered_stopped and ditto_stopped:
                await stop_sync(
                    "broker-router-drained",
                    "broker router after request drain",
                    lambda: retire_broker_router_generation(
                        flask_app,
                        timeout=deadline.remaining(10.0),
                    ),
                    require_truthy=True,
                )

        if errors:
            await stop_managed_local_ai()
            summary = ", ".join(f"{label} ({error_type})" for label, error_type in errors)
            logger.error("FlintTrade shutdown request drain failed: %s", summary)
            raise RuntimeError(f"shutdown encountered errors: {summary}")

        # The recorder was stopped and flushed before request draining;
        # unpublish and close its storage only after admitted handlers left.
        if flask_app is not None:
            with _tick_capture_lifecycle_lock(flask_app):
                published_recorder = flask_app.config.get("TICK_RECORDER")
                published_storage = flask_app.config.get("TICK_STORAGE")
                if published_recorder is tick_recorder or published_storage is tick_storage:
                    for key in (
                        "TICK_RECORDER",
                        "TICK_STORAGE",
                        "TICK_STORAGE_LOCK",
                        "ORDERFLOW_AGGREGATOR",
                    ):
                        flask_app.config.pop(key, None)
                    flask_app.config["TICK_CAPTURE_ERROR"] = "Application is shutting down"
        if tick_storage is not None:
            self.cron.tick_storage = None
            self.cron.tick_storage_lock = None
            if tick_storage_close_worker is None:
                def clear_closed_storage() -> None:
                    if self._tick_storage is tick_storage:
                        self._tick_recorder = None
                        self._tick_storage = None
                        self._tick_storage_lock = None
                        self._orderflow_checkpoint_owner = None

                tick_storage_close_worker = _build_tick_storage_close_worker(
                    tick_recorder,
                    tick_storage,
                    tick_storage_lock,
                    checkpoint_owner,
                    on_success=clear_closed_storage,
                )
                self._tick_storage_close_worker = tick_storage_close_worker
            tick_storage_close_worker.start()
            raw_close_timeout = (
                flask_app.config.get("TICK_STORAGE_CLOSE_TIMEOUT_SECONDS", 3.0)
                if flask_app is not None
                else 3.0
            )
            try:
                close_timeout = max(0.0, float(raw_close_timeout))
            except (TypeError, ValueError):
                close_timeout = 3.0

            def wait_for_tick_storage_close() -> bool:
                close_result = tick_storage_close_worker.wait(deadline.remaining(close_timeout))
                if close_result is None:
                    raise TimeoutError("tick storage close timed out")
                if close_result is not True:
                    raise RuntimeError("tick storage close failed")
                return True

            storage_closed, close_error_type = await self._run_retained_sync_owner(
                "tick-storage-finalisation",
                wait_for_tick_storage_close,
                deadline,
                require_truthy=True,
            )
            if not storage_closed:
                errors.append(("tick storage", close_error_type or "RuntimeError"))
            else:
                self._tick_storage_close_worker = None

        if errors:
            await stop_managed_local_ai()
            summary = ", ".join(f"{label} ({error_type})" for label, error_type in errors)
            logger.error("FlintTrade shutdown finalisation failed: %s", summary)
            raise RuntimeError(f"shutdown encountered errors: {summary}")

        await stop_managed_local_ai()

        if errors:
            summary = ", ".join(f"{label} ({error_type})" for label, error_type in errors)
            logger.error("FlintTrade shutdown dependency finalisation failed: %s", summary)
            raise RuntimeError(f"shutdown encountered errors: {summary}")

        # Log shutdown to audit before closing.
        await stop_sync(
            "audit-stop-event",
            "audit event",
            lambda: self.audit.log_event("APP_STOP", version=self.version),
        )

        if errors:
            summary = ", ".join(f"{label} ({error_type})" for label, error_type in errors)
            logger.error("FlintTrade shutdown audit finalisation failed: %s", summary)
            raise RuntimeError(f"shutdown encountered errors: {summary}")

        # Close API client and audit logger independently.
        async def close_openalgo_client() -> None:
            if isinstance(self.client, OpenAlgoClient):
                await self.client.shutdown()
                return
            await self.client.close()

        await stop_async("openalgo-client", "OpenAlgo client", close_openalgo_client)
        await stop_sync("audit-logger", "audit logger", self.audit.close)
        errors.extend(deferred_errors)
        if errors:
            summary = ", ".join(f"{label} ({error_type})" for label, error_type in errors)
            logger.error("FlintTrade shutdown encountered errors: %s", summary)
            raise RuntimeError(f"shutdown encountered errors: {summary}")

        self._stop_completed = True
        self._stop_event.set()
        logger.info("FlintTrade %s stopped", self.version)

    def _requires_runtime_recovery(self) -> bool:
        """Return whether backend authority must stay attached to this runtime."""
        if getattr(self, "_recovery_loop", None) is not None:
            return True
        if getattr(self, "_startup_recovery_pending", False):
            return True
        if getattr(self, "_stop_started", False) and not getattr(self, "_stop_completed", False):
            return True
        return getattr(self, "_flask_app", None) is not None and not getattr(self, "_stop_completed", False)

    def _retain_backend_recovery(self, backend_lease: Any) -> None:
        """Retain the lease and the runtime owning its exact recovery loop."""
        self._retained_backend_lease = backend_lease
        retain_owner = getattr(backend_lease, "retain_recovery_owner", None)
        if callable(retain_owner):
            retain_owner(self)
        else:
            setattr(backend_lease, "_recovery_owner", self)
        retain_backend_instance_lease(backend_lease)

    def retry_recovery(self, *, timeout: float | None = None) -> None:
        """Retry incomplete cleanup on the exact event loop that owns it."""
        loop = getattr(self, "_recovery_loop", None)
        if loop is None or loop.is_closed():
            raise RuntimeError("no live backend recovery loop is retained")
        if loop.is_running():
            raise RuntimeError("backend recovery loop is already running")

        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.stop(timeout=timeout))
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            if pending:
                raise RuntimeError("backend recovery still owns pending asyncio tasks")
            if getattr(self, "_startup_recovery_pending", False) or not getattr(self, "_stop_completed", False):
                raise RuntimeError("backend recovery did not complete runtime shutdown")

            backend_lease = getattr(self, "_retained_backend_lease", None)
            if backend_lease is not None:
                release_retained_backend_instance_lease(backend_lease)
                self._retained_backend_lease = None
            self._recovery_loop = None
            loop.close()
        finally:
            asyncio.set_event_loop(None)

    def run(self) -> None:
        """Run the application while owning this workspace's backend lease."""
        backend_lease = acquire_backend_instance_lease()
        try:
            self._run_owned()
        except BaseException:
            if self._requires_runtime_recovery():
                self._retain_backend_recovery(backend_lease)
            else:
                backend_lease.release()
            raise
        if self._requires_runtime_recovery():
            self._retain_backend_recovery(backend_lease)
            raise RuntimeError("backend runtime exited before owned services completed shutdown")
        backend_lease.release()

    def _run_owned(self) -> None:
        """Run the blocking event loop after backend ownership is established."""
        # NOTE: stdlib logging is already configured by create_flask_app()
        # with a structlog-backed formatter. Calling basicConfig() here
        # would add a second root handler and re-introduce the dual-emit
        # bug. Don't do it.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Handle signals
        def request_stop() -> None:
            task = getattr(self, "_shutdown_request_task", None)
            if task is None or task.done():
                task = loop.create_task(self.stop())
                self._shutdown_request_task = task

                def observe_shutdown(completed: asyncio.Task[Any]) -> None:
                    try:
                        completed.result()
                    except asyncio.CancelledError:
                        pass
                    except Exception as exc:  # noqa: BLE001 - consume signal-task failure
                        logger.error("FlintTrade shutdown failed (%s)", type(exc).__name__)

                task.add_done_callback(observe_shutdown)

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, request_stop)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass

        try:
            loop.run_until_complete(self.start())
            shutdown_task = getattr(self, "_shutdown_task", None)
            if shutdown_task is not None:
                loop.run_until_complete(asyncio.shield(shutdown_task))
        except KeyboardInterrupt:
            loop.run_until_complete(self.stop())
        finally:
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            runtime_incomplete = bool(pending) or getattr(self, "_startup_recovery_pending", False) or (
                getattr(self, "_stop_started", False)
                and not getattr(self, "_stop_completed", False)
            ) or (
                getattr(self, "_flask_app", None) is not None
                and not getattr(self, "_stop_completed", False)
            )
            asyncio.set_event_loop(None)
            if runtime_incomplete:
                self._recovery_loop = loop
            else:
                self._recovery_loop = None
                loop.close()


if __name__ == "__main__":
    FlintTradeApp().run()


# ---------------------------------------------------------------------------
# Module-level ``app`` for gunicorn / WSGI servers.
#   Usage: ``gunicorn 'flinttrade_core.app:app'``
#
# The Flask app is created LAZILY the first time ``app`` is imported from
# this module.  We avoid eagerly building it at module import because
# running ``python -m flinttrade_core.app`` would create one instance
# here and another inside ``FlintTradeApp.start()``, printing every
# startup log line twice and tripping the CPython "RuntimeWarning: ...
# found in sys.modules after import of package ..." warning.
#
# Python 3.7+ supports module-level ``__getattr__`` (PEP 562) which gives
# us lazy attribute access with no change to the consumer API — WSGI
# servers do ``from flinttrade_core.app import app`` and still get a
# real Flask instance on first use.
# ---------------------------------------------------------------------------

_APP_CACHE: Flask | None = None
_APP_CACHE_PID: int | None = None
_WSGI_BACKEND_LEASE: Any | None = None
_WSGI_STARTUP_RECOVERY: _WSGIStartupRecovery | None = None
_WSGI_APP_LOCK = threading.Lock()


class _WSGIStartupRecovery:
    """Retain exact cleanup authority when WSGI startup fails after its factory."""

    def __init__(self, candidate: Flask, backend_lease: Any) -> None:
        self._candidate = candidate
        self._backend_lease = backend_lease
        self._lock = threading.Lock()
        self._complete = False

    def retain(self) -> None:
        """Attach this recovery owner before preserving the failed lease."""
        global _WSGI_STARTUP_RECOVERY
        retain_owner = getattr(self._backend_lease, "retain_recovery_owner", None)
        if callable(retain_owner):
            retain_owner(self)
        else:
            setattr(self._backend_lease, "_recovery_owner", self)
        retain_backend_instance_lease(self._backend_lease)
        _WSGI_STARTUP_RECOVERY = self

    def retry_recovery(self) -> None:
        """Stop factory-owned runtimes, then release the retained lease."""
        global _WSGI_STARTUP_RECOVERY
        with self._lock:
            if self._complete:
                return
            from .local_ai_routes import shutdown_local_ai_runtime  # noqa: PLC0415

            self._candidate.config["RUNTIME_ACCEPTING_REQUESTS"] = False
            failures: list[str] = []
            try:
                if not shutdown_local_ai_runtime(self._candidate, timeout=5.0):
                    failures.append("managed local AI")
            except BaseException as exc:  # noqa: BLE001 - retain authority for retry
                failures.append(f"managed local AI ({type(exc).__name__})")
            try:
                if not shutdown_ditto_runtime(self._candidate, timeout=5.0):
                    failures.append("ditto runtime")
            except BaseException as exc:  # noqa: BLE001 - retain authority for retry
                failures.append(f"ditto runtime ({type(exc).__name__})")
            if failures:
                raise RuntimeError("WSGI startup recovery incomplete: " + ", ".join(failures))
            release_retained_backend_instance_lease(self._backend_lease)
            self._complete = True
            if _WSGI_STARTUP_RECOVERY is self:
                _WSGI_STARTUP_RECOVERY = None


class _ProcessBoundWSGIApp:
    """Reject requests when a preloaded callable crosses a process boundary."""

    def __init__(self, inner: Callable[..., Any], *, owner_pid: int, backend_lease: Any) -> None:
        self._inner = inner
        self._owner_pid = owner_pid
        self._backend_lease = backend_lease

    def __call__(self, environ: Mapping[str, Any], start_response: Callable[..., Any]) -> Any:
        current_pid = os.getpid()
        lease_owner_pid = getattr(self._backend_lease, "owner_pid", self._owner_pid)
        if current_pid != self._owner_pid or lease_owner_pid != current_pid:
            body = b"inherited WSGI app cannot serve from a forked process\n"
            start_response(
                "503 Service Unavailable",
                [
                    ("Content-Type", "text/plain; charset=utf-8"),
                    ("Content-Length", str(len(body))),
                    ("Retry-After", "1"),
                ],
            )
            return [body]
        return self._inner(environ, start_response)


def _get_wsgi_app() -> Flask:
    """Lazily construct (and cache) the WSGI Flask app."""
    global _APP_CACHE, _APP_CACHE_PID, _WSGI_BACKEND_LEASE
    current_pid = os.getpid()
    if _APP_CACHE is not None and _APP_CACHE_PID != current_pid:
        raise RuntimeError("inherited WSGI app cannot serve from a forked process")
    lease_owner_pid = getattr(_WSGI_BACKEND_LEASE, "owner_pid", current_pid)
    if _WSGI_BACKEND_LEASE is not None and lease_owner_pid != current_pid:
        raise RuntimeError("inherited WSGI app cannot serve from a forked process")
    if _APP_CACHE is None:
        with _WSGI_APP_LOCK:
            if _APP_CACHE is not None and _APP_CACHE_PID != current_pid:
                raise RuntimeError("inherited WSGI app cannot serve from a forked process")
            if _APP_CACHE is None:
                recovery = _WSGI_STARTUP_RECOVERY
                if recovery is not None:
                    recovery.retry_recovery()
                backend_lease = acquire_backend_instance_lease()
                try:
                    candidate = create_flask_app()
                except BaseException:
                    backend_lease.release()
                    raise
                try:
                    from .local_ai_routes import start_configured_local_ai_runtime  # noqa: PLC0415

                    start_configured_local_ai_runtime(candidate)
                    import atexit  # noqa: PLC0415
                    from .local_ai_routes import shutdown_local_ai_runtime  # noqa: PLC0415

                    atexit.register(shutdown_ditto_runtime, candidate, timeout=5.0)
                    atexit.register(shutdown_local_ai_runtime, candidate, timeout=5.0)
                    candidate.wsgi_app = _ProcessBoundWSGIApp(  # type: ignore[method-assign]
                        candidate.wsgi_app,
                        owner_pid=current_pid,
                        backend_lease=backend_lease,
                    )
                except BaseException:
                    recovery = _WSGIStartupRecovery(candidate, backend_lease)
                    recovery.retain()
                    try:
                        recovery.retry_recovery()
                    except BaseException as recovery_error:  # noqa: BLE001 - preserve startup failure
                        logger.error(
                            "WSGI post-factory recovery remains incomplete (%s)",
                            type(recovery_error).__name__,
                        )
                    raise
                _APP_CACHE = candidate
                _APP_CACHE_PID = current_pid
                _WSGI_BACKEND_LEASE = backend_lease
    return _APP_CACHE


def __getattr__(name: str) -> Any:
    """PEP 562 module __getattr__ — produce ``app`` on first access only."""
    if name == "app":
        return _get_wsgi_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
