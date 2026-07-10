"""Native-desktop backend entry point.

This is the process the Tauri desktop shell launches as a bundled *sidecar*.
It serves the full FlintTrade backend — the gated order path, every REST
blueprint, and the built React terminal — on a loopback port, then blocks
until the parent process terminates it.

Design goals (distinct from :func:`flinttrade_core.app.FlintTradeApp.run`):

* **Lean and resilient when frozen.** PyInstaller bundles only what the
  serving path needs; the heavy automation loops (cron scheduler, Telegram
  bot, overnight optimiser) are deliberately *not* started here, so the
  packaged binary stays small and never fails to boot because an optional
  ML dependency could not be collected. Those features remain reachable
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
  Tauri shell waits for that line (and/or polls the health endpoint) before
  pointing its window at ``http://127.0.0.1:<port>``.

Usage::

    python -m flinttrade_core.desktop            # serve on the default port
    python -m flinttrade_core.desktop --port 0   # ask the OS for a free port
    FLINTTRADE_BACKEND_PORT=5123 flinttrade-desktop-backend
"""

from __future__ import annotations

import argparse
import _thread
import asyncio
import logging
import os
import sys
import threading
from collections.abc import Callable
from typing import Any, Protocol

# Importing the app module first applies the UTF-8 stdout reconfigure and the
# frozen-mode sys.path / dist-path wiring (see ``flinttrade_core.app``).
from .app import (
    _build_tick_recorder,
    _record_tick_capture_failure,
    _sanitise_tick_capture_error,
    _set_tick_capture_intent,
    _tick_capture_enabled,
    _tick_capture_lifecycle_lock,
    _tick_capture_mode,
    _tick_capture_watchlist,
    _workspace_dir,
    create_flask_app,
)
from .workspace import Workspace

logger = logging.getLogger("flinttrade.desktop")

#: Default loopback port for the desktop backend. Kept distinct from OpenAlgo's
#: 5000-5009 range (see CLAUDE.md). Overridable via ``--port`` or the
#: ``FLINTTRADE_BACKEND_PORT`` environment variable.
DEFAULT_PORT = 5100

#: Stdout sentinel the Tauri shell waits for before loading the UI.
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


class _ShutdownSignal(Protocol):
    """Cross-process shutdown coordinator supplied by the desktop wrapper."""

    def install(self, callback: Callable[[], None]) -> None: ...

    def uninstall(self, callback: Callable[[], None]) -> None: ...


class _DesktopTickCaptureRuntime:
    """Own the recorder event loop, thread, and tick storage for the sidecar."""

    def __init__(
        self,
        recorder: Any,
        storage: Any,
        api_key: str,
        *,
        storage_lock: Any | None = None,
        on_failure: Callable[[str], None] | None = None,
    ) -> None:
        self.recorder = recorder
        self.storage = storage
        self.api_key = api_key
        self._storage_lock = storage_lock
        self._redaction_lock = threading.Lock()
        self._redaction_keys = {api_key} if api_key else set()
        self._on_failure = on_failure
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task[Any] | None = None
        self._started = threading.Event()
        self._stop_lock = threading.Lock()
        self._stopped = False
        self._startup_error: BaseException | None = None
        self._storage_close_lock = threading.Lock()
        self._storage_closed = False
        self._thread = threading.Thread(
            target=self._run,
            name="flinttrade-desktop-tick-capture",
            daemon=False,
        )

    def start(self) -> None:
        """Start the recorder on its dedicated daemon event-loop thread."""
        self._thread.start()
        if not self._started.wait(_CAPTURE_THREAD_START_TIMEOUT):
            raise RuntimeError("Tick capture event loop did not start")
        if self._startup_error is not None:
            raise RuntimeError("Tick capture event loop failed during startup") from self._startup_error
        if not self._thread.is_alive():
            raise RuntimeError("Tick capture event loop stopped during startup")

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

    def _close_storage_once(self) -> None:
        """Close storage exactly once, and only from a stopped owner thread."""
        with self._storage_close_lock:
            if self._storage_closed:
                return
            self._storage_closed = True
        try:
            if self._storage_lock is None:
                self.storage.close()
            else:
                with self._storage_lock:
                    self.storage.close()
        except Exception as exc:  # pragma: no cover - defensive shutdown
            diagnostic = self._sanitise(exc)
            logger.warning("Desktop tick storage close failed (%s)", diagnostic)

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

            if failure is not None and not self._is_stopped():
                self._report_failure(failure)
        finally:
            self._started.set()
            pending = [pending_task for pending_task in asyncio.all_tasks(loop) if not pending_task.done()]
            for pending_task in pending:
                pending_task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._task = None
            self._loop = None
            loop.close()
            self._close_storage_once()

    def stop(self, *, timeout: float = _CAPTURE_THREAD_STOP_TIMEOUT) -> None:
        """Stop capture, wait briefly for recorder cleanup, and close storage."""
        with self._stop_lock:
            if self._stopped:
                return
            self._stopped = True

        loop = self._loop
        task = self._task

        def request_stop() -> None:
            try:
                self.recorder.stop()
            except Exception as exc:  # pragma: no cover - defensive shutdown
                diagnostic = self._sanitise(exc)
                logger.warning("Desktop tick recorder stop signal failed (%s)", diagnostic)
            if task is not None and not task.done():
                task.cancel()

        if loop is not None and loop.is_running():
            try:
                loop.call_soon_threadsafe(request_stop)
            except RuntimeError:
                request_stop()
        else:
            request_stop()

        if self._thread.is_alive():
            self._thread.join(timeout=max(0.0, timeout))
        if self._thread.is_alive():
            logger.warning("Desktop tick recorder did not stop within %.1fs", timeout)
        else:
            self._close_storage_once()


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
    runtime: _DesktopTickCaptureRuntime | None = None
    api_key = str(getattr(settings, "openalgo_api_key", "") or "")
    try:
        if storage_factory is None:
            from flinttrade_data.storage import StorageManager  # noqa: PLC0415

            storage_factory = StorageManager
        if recorder_factory is None:
            from flinttrade_data.tick_recorder import TickRecorder  # noqa: PLC0415

            recorder_factory = TickRecorder
        if orderflow_factory is None:
            from flinttrade_data.orderflow_aggregator import OrderFlowAggregator  # noqa: PLC0415

            orderflow_factory = OrderFlowAggregator

        storage = storage_factory(str(_workspace_dir() / "ticks.duckdb"))
        storage.initialise()
        storage_lock = threading.Lock()
        orderflow = orderflow_factory()
        recorder = build_recorder(
            recorder_factory=recorder_factory,
            signal_hub=flask_app.config.get("SIGNAL_HUB"),
            settings=settings,
            storage=storage,
            storage_lock=storage_lock,
            orderflow=orderflow,
            watchlist=_tick_capture_watchlist(),
            mode=_tick_capture_mode(),
        )

        def capture_failed(diagnostic: str) -> None:
            with _tick_capture_lifecycle_lock(flask_app):
                if flask_app.config.get("TICK_RECORDER") is not recorder:
                    return
                for key in _CAPTURE_CONFIG_KEYS:
                    flask_app.config.pop(key, None)
                flask_app.config["TICK_CAPTURE_ERROR"] = diagnostic

        runtime = _DesktopTickCaptureRuntime(
            recorder,
            storage,
            api_key,
            storage_lock=storage_lock,
            on_failure=capture_failed,
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
        return runtime
    except Exception as exc:
        if runtime is not None:
            runtime.stop()
        elif storage is not None:
            try:
                storage.close()
            except Exception as cleanup_exc:  # pragma: no cover - defensive rollback
                logger.warning(
                    "Desktop tick storage rollback failed (%s)",
                    _sanitise_tick_capture_error(cleanup_exc, api_key),
                )
        for key in (*_CAPTURE_CONFIG_KEYS, _CAPTURE_RUNTIME_CONFIG):
            flask_app.config.pop(key, None)
        _record_tick_capture_failure(flask_app, exc, api_key)
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
    if not ws.is_initialized:
        ws.initialise()
    return ws


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
        print(f"[desktop] audit logger unavailable: {exc}", file=sys.stderr)

    try:
        from .config import Settings  # noqa: PLC0415
        from .openalgo_client import OpenAlgoClient  # noqa: PLC0415

        settings = Settings.from_env()
        client = OpenAlgoClient(settings)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[desktop] OpenAlgo client unavailable: {exc}", file=sys.stderr)

    try:
        from flinttrade_engine.safety import SafetyConfig, SafetySystem  # noqa: PLC0415

        safety = SafetySystem(SafetyConfig(check_market_hours=True))
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[desktop] safety system unavailable: {exc}", file=sys.stderr)

    flask_app = create_flask_app(safety=safety, audit=audit, client=client)
    if settings is None:
        try:
            from .config import Settings  # noqa: PLC0415

            settings = Settings.from_env()
        except Exception as exc:  # pragma: no cover - defensive
            enabled = _tick_capture_enabled()
            _set_tick_capture_intent(flask_app, enabled)
            if enabled:
                _record_tick_capture_failure(flask_app, exc, "")
            return flask_app
    _configure_tick_capture(flask_app, settings)
    return flask_app


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
) -> None:
    """Bind the loopback socket and serve forever (blocking).

    Uses Waitress — the same production WSGI server the rest of FlintTrade
    runs on — created explicitly so the listening socket is open *before* the
    ready handshake is emitted. This removes the race where the Tauri shell
    would otherwise poll a port that is not yet accepting connections.

    Args:
        port: Loopback port to bind. ``0`` asks the OS for a free port.
    """
    app = _build_app()
    shutdown_callback: Callable[[], None] | None = None
    try:
        from waitress.server import create_server  # noqa: PLC0415

        server = create_server(app, host="127.0.0.1", port=port, ident="FlintTrade", threads=8)
        bound_port = server.effective_port

        if shutdown_signal is not None:
            shutdown_callback = _thread.interrupt_main
            shutdown_signal.install(shutdown_callback)

        # Handshake — one line, flushed, so the parent can read it synchronously.
        ready_message = f"{READY_SENTINEL} port={bound_port}"
        if ready_writer is None:
            print(ready_message, flush=True)
        else:
            ready_writer(ready_message)

        server.run()
    except (KeyboardInterrupt, SystemExit):  # pragma: no cover - signal path
        pass
    finally:
        if shutdown_signal is not None and shutdown_callback is not None:
            shutdown_signal.uninstall(shutdown_callback)
        runtime = app.config.get(_CAPTURE_RUNTIME_CONFIG)
        if runtime is not None:
            try:
                runtime.stop()
            except Exception as exc:  # pragma: no cover - defensive shutdown
                sanitise_error = getattr(runtime, "sanitise_error", None)
                try:
                    diagnostic = sanitise_error(exc) if callable(sanitise_error) else type(exc).__name__
                except Exception:
                    diagnostic = type(exc).__name__
                logger.warning(
                    "Desktop tick capture shutdown failed (%s)",
                    diagnostic,
                )


def main(
    argv: list[str] | None = None,
    *,
    shutdown_signal: _ShutdownSignal | None = None,
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

    _ensure_workspace()
    serve(_resolve_port(args.port), shutdown_signal=shutdown_signal)


if __name__ == "__main__":
    main()
