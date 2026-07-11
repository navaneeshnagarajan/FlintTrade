"""Desktop sidecar tick-capture lifecycle tests.

These tests keep the synchronous Waitress boundary and asynchronous recorder
loop honest without opening a real WebSocket or DuckDB database.
"""

from __future__ import annotations

import asyncio
import builtins
import logging
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from flask import Flask

from flinttrade_core import desktop


_CAPTURE_CONFIG_KEYS = {
    "ORDERFLOW_AGGREGATOR",
    "TICK_RECORDER",
    "TICK_STORAGE",
    "TICK_STORAGE_LOCK",
}


class _FakeStorage:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self.initialised = False
        self.closed = False

    def initialise(self) -> None:
        self.initialised = True

    def close(self) -> None:
        self.closed = True


class _RetryingCloseStorage(_FakeStorage):
    def __init__(self, db_path: str, failures: int) -> None:
        super().__init__(db_path)
        self.failures = failures
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        if self.close_calls <= self.failures:
            raise RuntimeError("transient close failure")
        super().close()


class _FakeRecorder:
    def __init__(self) -> None:
        self.run_started = threading.Event()
        self.run_finished = threading.Event()
        self.stop_calls = 0

    async def run(self) -> None:
        self.run_started.set()
        try:
            await asyncio.Future()
        finally:
            self.run_finished.set()

    def stop(self) -> None:
        self.stop_calls += 1


class _SlowCleanupRecorder(_FakeRecorder):
    def __init__(self) -> None:
        super().__init__()
        self.cancel_seen = threading.Event()
        self.release_cleanup = threading.Event()

    async def run(self) -> None:
        self.run_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancel_seen.set()
            while not self.release_cleanup.is_set():
                await asyncio.sleep(0.005)
        finally:
            self.run_finished.set()


class _UnexpectedFailureRecorder(_FakeRecorder):
    def __init__(self, api_key: str) -> None:
        super().__init__()
        self.release_failure = threading.Event()
        self.api_key = api_key

    async def run(self) -> None:
        self.run_started.set()
        while not self.release_failure.is_set():
            await asyncio.sleep(0.005)
        raise RuntimeError(f"recorder stopped with {self.api_key}")


@pytest.mark.unit
def test_runtime_redacts_original_and_hot_reloaded_api_keys() -> None:
    runtime = desktop._DesktopTickCaptureRuntime(
        _FakeRecorder(),
        _FakeStorage("unused"),
        "old-secret",
    )
    runtime.update_api_key("new-secret")

    diagnostic = runtime.sanitise_error("old-secret then new-secret")

    assert diagnostic == "[redacted] then [redacted]"


@pytest.mark.unit
def test_enabled_desktop_builds_one_runtime_with_existing_hub_and_settings(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    flask_app = Flask("desktop-capture")
    signal_hub = object()
    flask_app.config["SIGNAL_HUB"] = signal_hub
    settings = SimpleNamespace(openalgo_api_key="workspace-key")
    storage = _FakeStorage("unused")
    storage_paths: list[str] = []
    recorder = _FakeRecorder()
    orderflow = object()
    watchlist = [{"exchange": "NSE_INDEX", "symbol": "NIFTY"}]
    build_calls: list[dict[str, object]] = []

    monkeypatch.setattr(desktop, "_tick_capture_enabled", lambda: True)
    monkeypatch.setattr(desktop, "_workspace_dir", lambda: tmp_path)
    monkeypatch.setattr(desktop, "_tick_capture_watchlist", lambda: watchlist)
    monkeypatch.setattr(desktop, "_tick_capture_mode", lambda: "depth")

    def build_recorder(**kwargs):
        build_calls.append(kwargs)
        return recorder

    runtime = desktop._configure_tick_capture(
        flask_app,
        settings,
        storage_factory=lambda path: storage_paths.append(path) or storage,
        recorder_factory=object(),
        orderflow_factory=lambda: orderflow,
        build_recorder=build_recorder,
    )
    assert runtime is flask_app.config["DESKTOP_TICK_CAPTURE_RUNTIME"]
    assert runtime._thread.daemon is False
    assert recorder.run_started.wait(1)
    assert len(build_calls) == 1
    call = build_calls[0]
    assert call["signal_hub"] is signal_hub
    assert call["settings"] is settings
    assert call["storage"] is storage
    assert call["storage_lock"] is flask_app.config["TICK_STORAGE_LOCK"]
    assert call["orderflow"] is orderflow
    assert call["watchlist"] is watchlist
    assert call["mode"] == "depth"
    assert storage.db_path == "unused"
    assert storage_paths == [str(tmp_path / "ticks.duckdb")]
    assert storage.initialised is True
    assert flask_app.config["TICK_CAPTURE_ENABLED"] is True
    assert flask_app.config["TICK_CAPTURE_ERROR"] == ""
    assert flask_app.config["TICK_RECORDER"] is recorder
    assert flask_app.config["TICK_STORAGE"] is storage
    assert flask_app.config["ORDERFLOW_AGGREGATOR"] is orderflow

    runtime.stop(timeout=1)
    assert recorder.stop_calls == 1
    assert recorder.run_finished.wait(1)
    assert storage.closed is True
    assert "DESKTOP_TICK_CAPTURE_RUNTIME" not in flask_app.config
    assert _CAPTURE_CONFIG_KEYS.isdisjoint(flask_app.config)


@pytest.mark.unit
def test_failed_storage_close_remains_retryable_and_unpublished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flask_app = Flask("desktop-capture-close-retry")
    recorder = _FakeRecorder()
    storage = _RetryingCloseStorage("unused", failures=2)
    monkeypatch.setattr(desktop, "_tick_capture_enabled", lambda: True)

    runtime = desktop._configure_tick_capture(
        flask_app,
        SimpleNamespace(openalgo_api_key=""),
        storage_factory=lambda _path: storage,
        recorder_factory=object(),
        orderflow_factory=object,
        build_recorder=lambda **_kwargs: recorder,
    )
    assert runtime is not None
    assert recorder.run_started.wait(1)

    runtime.stop(timeout=1)

    assert storage.close_calls == 2
    assert storage.closed is False
    assert runtime._storage_closed is False
    assert flask_app.config["DESKTOP_TICK_CAPTURE_RUNTIME"] is runtime
    assert _CAPTURE_CONFIG_KEYS.isdisjoint(flask_app.config)

    runtime.stop(timeout=1)

    assert storage.close_calls == 3
    assert storage.closed is True
    assert runtime._storage_closed is True
    assert "DESKTOP_TICK_CAPTURE_RUNTIME" not in flask_app.config


@pytest.mark.unit
def test_disabled_desktop_capture_opens_no_runtime_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    flask_app = Flask("desktop-capture-disabled")
    monkeypatch.setattr(desktop, "_tick_capture_enabled", lambda: False)
    storage_factory = MagicMock(side_effect=AssertionError("storage must stay closed"))

    runtime = desktop._configure_tick_capture(
        flask_app,
        SimpleNamespace(openalgo_api_key=""),
        storage_factory=storage_factory,
        recorder_factory=object(),
        orderflow_factory=MagicMock(side_effect=AssertionError("aggregator must stay absent")),
        build_recorder=MagicMock(side_effect=AssertionError("recorder must stay absent")),
    )

    assert runtime is None
    assert flask_app.config["TICK_CAPTURE_ENABLED"] is False
    assert flask_app.config["TICK_CAPTURE_ERROR"] == ""
    assert "DESKTOP_TICK_CAPTURE_RUNTIME" not in flask_app.config
    assert _CAPTURE_CONFIG_KEYS.isdisjoint(flask_app.config)
    storage_factory.assert_not_called()


@pytest.mark.unit
def test_configured_capture_failure_is_redacted_and_leaves_no_partial_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flask_app = Flask("desktop-capture-failure")
    api_key = "top-secret-workspace-key"
    storage = _FakeStorage("unused")
    monkeypatch.setattr(desktop, "_tick_capture_enabled", lambda: True)

    def fail_build(**_kwargs):
        raise RuntimeError(f"OpenAlgo rejected {api_key}")

    runtime = desktop._configure_tick_capture(
        flask_app,
        SimpleNamespace(openalgo_api_key=api_key),
        storage_factory=lambda _path: storage,
        recorder_factory=object(),
        orderflow_factory=object,
        build_recorder=fail_build,
    )

    assert runtime is None
    assert flask_app.config["TICK_CAPTURE_ENABLED"] is True
    assert flask_app.config["TICK_CAPTURE_ERROR"] == "OpenAlgo rejected [redacted]"
    assert api_key not in flask_app.config["TICK_CAPTURE_ERROR"]
    assert "DESKTOP_TICK_CAPTURE_RUNTIME" not in flask_app.config
    assert _CAPTURE_CONFIG_KEYS.isdisjoint(flask_app.config)
    assert storage.closed is True


@pytest.mark.unit
def test_stop_never_closes_storage_while_recorder_thread_is_still_flushing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flask_app = Flask("desktop-capture-slow-stop")
    recorder = _SlowCleanupRecorder()
    storage = _FakeStorage("unused")
    monkeypatch.setattr(desktop, "_tick_capture_enabled", lambda: True)

    runtime = desktop._configure_tick_capture(
        flask_app,
        SimpleNamespace(openalgo_api_key=""),
        storage_factory=lambda _path: storage,
        recorder_factory=object(),
        orderflow_factory=object,
        build_recorder=lambda **_kwargs: recorder,
    )
    assert runtime is not None
    assert recorder.run_started.wait(1)

    runtime.stop(timeout=0.01)

    assert recorder.cancel_seen.wait(1)
    assert runtime._thread.is_alive()
    assert storage.closed is False

    recorder.release_cleanup.set()
    runtime._thread.join(timeout=1)
    assert not runtime._thread.is_alive()
    assert recorder.run_finished.is_set()
    assert storage.closed is True


@pytest.mark.unit
def test_unexpected_recorder_death_is_redacted_and_removes_closed_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flask_app = Flask("desktop-capture-runtime-failure")
    api_key = "runtime-secret-key"
    recorder = _UnexpectedFailureRecorder(api_key)
    storage = _FakeStorage("unused")
    monkeypatch.setattr(desktop, "_tick_capture_enabled", lambda: True)

    runtime = desktop._configure_tick_capture(
        flask_app,
        SimpleNamespace(openalgo_api_key=api_key),
        storage_factory=lambda _path: storage,
        recorder_factory=object(),
        orderflow_factory=object,
        build_recorder=lambda **_kwargs: recorder,
    )
    assert runtime is not None
    assert _CAPTURE_CONFIG_KEYS.issubset(flask_app.config)

    recorder.release_failure.set()
    runtime._thread.join(timeout=1)

    assert not runtime._thread.is_alive()
    assert storage.closed is True
    assert _CAPTURE_CONFIG_KEYS.isdisjoint(flask_app.config)
    assert flask_app.config["TICK_CAPTURE_ENABLED"] is True
    assert flask_app.config["TICK_CAPTURE_ERROR"] == "recorder stopped with [redacted]"
    assert api_key not in flask_app.config["TICK_CAPTURE_ERROR"]


@pytest.mark.unit
def test_missing_frozen_capture_dependency_records_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    flask_app = Flask("desktop-capture-import-failure")
    monkeypatch.setattr(desktop, "_tick_capture_enabled", lambda: True)
    real_import = builtins.__import__

    def fail_storage_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "flinttrade_data.storage":
            raise ImportError("tick storage was not bundled")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fail_storage_import)

    runtime = desktop._configure_tick_capture(
        flask_app,
        SimpleNamespace(openalgo_api_key=""),
    )

    assert runtime is None
    assert flask_app.config["TICK_CAPTURE_ENABLED"] is True
    assert flask_app.config["TICK_CAPTURE_ERROR"] == "tick storage was not bundled"
    assert _CAPTURE_CONFIG_KEYS.isdisjoint(flask_app.config)


@pytest.mark.unit
def test_build_app_configures_capture_with_the_same_settings_and_hub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flask_app = Flask("desktop-build")
    signal_hub = object()
    flask_app.config["SIGNAL_HUB"] = signal_hub
    settings = SimpleNamespace(openalgo_api_key="workspace-key")
    configured: list[tuple[Flask, object, object]] = []

    monkeypatch.setattr("flinttrade_core.config.Settings.from_env", lambda: settings)
    monkeypatch.setattr("flinttrade_core.openalgo_client.OpenAlgoClient", lambda value: ("client", value))
    monkeypatch.setattr("flinttrade_data.audit_logger.AuditLogger", MagicMock)
    monkeypatch.setattr(desktop, "create_flask_app", lambda **_kwargs: flask_app)

    def configure(app, active_settings, **_kwargs):
        configured.append((app, active_settings, app.config["SIGNAL_HUB"]))
        return object()

    monkeypatch.setattr(desktop, "_configure_tick_capture", configure)

    assert desktop._build_app() is flask_app
    assert configured == [(flask_app, settings, signal_hub)]


@pytest.mark.unit
def test_serve_announces_ready_after_capture_start_and_stops_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    runtime = SimpleNamespace(stop=lambda **_kwargs: events.append("capture-stop"))
    flask_app = Flask("desktop-serve")
    flask_app.config["DESKTOP_TICK_CAPTURE_RUNTIME"] = runtime

    class FakeServer:
        effective_port = 5199

        def run(self) -> None:
            events.append("server-run")

    def build_app():
        events.append("capture-start")
        return flask_app

    monkeypatch.setattr(desktop, "_build_app", build_app)
    monkeypatch.setattr("waitress.server.create_server", lambda *_args, **_kwargs: FakeServer())

    desktop.serve(0, ready_writer=lambda _message: events.append("ready"))

    assert events == ["capture-start", "ready", "server-run", "capture-stop"]


@pytest.mark.unit
def test_serve_stops_capture_when_waitress_bind_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = MagicMock()
    flask_app = Flask("desktop-bind-failure")
    flask_app.config["DESKTOP_TICK_CAPTURE_RUNTIME"] = runtime
    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)

    def fail_bind(*_args, **_kwargs):
        raise OSError("port unavailable")

    monkeypatch.setattr("waitress.server.create_server", fail_bind)

    with pytest.raises(OSError, match="port unavailable"):
        desktop.serve(5100)

    runtime.stop.assert_called_once_with()


@pytest.mark.unit
def test_serve_installs_and_removes_graceful_shutdown_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    runtime = SimpleNamespace(stop=lambda **_kwargs: events.append("capture-stop"))
    flask_app = Flask("desktop-shutdown-signal")
    flask_app.config["DESKTOP_TICK_CAPTURE_RUNTIME"] = runtime

    class ShutdownSignal:
        callback = None

        def install(self, callback) -> None:
            self.callback = callback
            events.append("shutdown-install")

        def uninstall(self, callback) -> None:
            assert callback is self.callback
            events.append("shutdown-uninstall")
            self.callback = None

    shutdown_signal = ShutdownSignal()
    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)
    monkeypatch.setattr(
        "waitress.server.create_server",
        lambda *_args, **_kwargs: SimpleNamespace(
            effective_port=5100,
            run=lambda: events.append("server-run"),
        ),
    )

    desktop.serve(
        5100,
        ready_writer=lambda _message: events.append("ready"),
        shutdown_signal=shutdown_signal,
    )

    assert events == [
        "shutdown-install",
        "ready",
        "server-run",
        "shutdown-uninstall",
        "capture-stop",
    ]


@pytest.mark.unit
def test_graceful_shutdown_request_unwinds_server_and_flushes_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    runtime = SimpleNamespace(stop=lambda **_kwargs: events.append("capture-stop"))
    flask_app = Flask("desktop-graceful-stop")
    flask_app.config["DESKTOP_TICK_CAPTURE_RUNTIME"] = runtime

    class ShutdownSignal:
        callback = None

        def install(self, callback) -> None:
            self.callback = callback

        def uninstall(self, callback) -> None:
            assert callback is self.callback
            self.callback = None

        def request(self) -> None:
            assert self.callback is not None
            self.callback()

    shutdown_signal = ShutdownSignal()

    def run_server() -> None:
        events.append("server-run")
        request_thread = threading.Thread(target=shutdown_signal.request)
        request_thread.start()
        request_thread.join(timeout=1)
        threading.Event().wait(1)

    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)
    monkeypatch.setattr(
        "waitress.server.create_server",
        lambda *_args, **_kwargs: SimpleNamespace(effective_port=5100, run=run_server),
    )

    desktop.serve(5100, ready_writer=lambda _message: None, shutdown_signal=shutdown_signal)

    assert events == ["server-run", "capture-stop"]


@pytest.mark.unit
def test_serve_redacts_capture_shutdown_failure(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_api_key = "old-workspace-key"
    new_api_key = "rotated-workspace-key"

    def fail_stop() -> None:
        raise RuntimeError(f"close rejected {old_api_key} then {new_api_key}")

    def sanitise_error(error: object) -> str:
        return str(error).replace(old_api_key, "[redacted]").replace(new_api_key, "[redacted]")

    runtime = SimpleNamespace(stop=fail_stop, sanitise_error=sanitise_error)
    flask_app = Flask("desktop-stop-failure")
    flask_app.config["DESKTOP_TICK_CAPTURE_RUNTIME"] = runtime
    monkeypatch.setattr(desktop, "_build_app", lambda: flask_app)
    monkeypatch.setattr(
        "waitress.server.create_server",
        lambda *_args, **_kwargs: SimpleNamespace(effective_port=5100, run=lambda: None),
    )
    caplog.set_level(logging.WARNING, logger="flinttrade.desktop")

    desktop.serve(5100, ready_writer=lambda _message: None)

    assert old_api_key not in caplog.text
    assert new_api_key not in caplog.text
    assert "close rejected [redacted] then [redacted]" in caplog.text
