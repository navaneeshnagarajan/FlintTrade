"""Tick-capture boot wiring + gate.

Live tick capture (``TickRecorder``) is a complete OpenAlgo-WS → DuckDB recorder
that previously was never launched by the backend. This guards the wiring:

* ``_tick_capture_enabled()`` is OFF unless ``FLINTTRADE_TICK_CAPTURE`` is set
  (the recorder opens a WebSocket on boot, so it must be opt-in).
* ``FlintTradeApp.start()`` constructs a ``TickRecorder`` and launches it as a
  background task, gated by ``_tick_capture_enabled()``.
* ``FlintTradeApp.stop()`` stops the recorder.

The ``start()`` assertions are AST-based so they survive reformatting and do not
require booting the app (which opens sockets and spawns threads).
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from flask import Flask

from flinttrade_core.app import _tick_capture_enabled
from flinttrade_core.config import Settings

APP_PY = Path(__file__).resolve().parents[1] / "src" / "flinttrade_core" / "app.py"


def _find_method(tree: ast.AST, class_name: str, method_name: str) -> ast.AST | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for sub in node.body:
                if (
                    isinstance(sub, (ast.AsyncFunctionDef, ast.FunctionDef))
                    and sub.name == method_name
                ):
                    return sub
    return None


def _calls_named(scope: ast.AST, func_name: str) -> bool:
    """True if `scope` contains a call to a function/attribute named `func_name`."""
    for node in ast.walk(scope):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id == func_name:
                return True
            if isinstance(f, ast.Attribute) and f.attr == func_name:
                return True
    return False


@pytest.mark.unit
def test_tick_capture_disabled_by_default() -> None:
    old = os.environ.pop("FLINTTRADE_TICK_CAPTURE", None)
    try:
        assert _tick_capture_enabled() is False
        for val in ("1", "true", "YES", "on"):
            os.environ["FLINTTRADE_TICK_CAPTURE"] = val
            assert _tick_capture_enabled() is True
        os.environ["FLINTTRADE_TICK_CAPTURE"] = "false"
        assert _tick_capture_enabled() is False
    finally:
        if old is None:
            os.environ.pop("FLINTTRADE_TICK_CAPTURE", None)
        else:
            os.environ["FLINTTRADE_TICK_CAPTURE"] = old


@pytest.mark.unit
def test_tick_capture_explicit_env_false_overrides_workspace_true(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_TICK_CAPTURE", "false")
    (tmp_path / "workspace.json").write_text(
        json.dumps({"data": {"tick_capture": {"enabled": True}}}),
        encoding="utf-8",
    )

    assert _tick_capture_enabled() is False


@pytest.mark.unit
@pytest.mark.parametrize("enabled", [True, "true"])
def test_tick_capture_workspace_true_enables_when_env_is_absent(tmp_path, monkeypatch, enabled) -> None:
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.delenv("FLINTTRADE_TICK_CAPTURE", raising=False)
    (tmp_path / "workspace.json").write_text(
        json.dumps({"data": {"tick_capture": {"enabled": enabled}}}),
        encoding="utf-8",
    )

    assert _tick_capture_enabled() is True


@pytest.mark.unit
def test_start_launches_gated_tick_recorder() -> None:
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    start = _find_method(tree, "FlintTradeApp", "start")
    assert start is not None, "FlintTradeApp.start not found"

    assert _calls_named(start, "_tick_capture_enabled"), (
        "Tick capture must be gated by _tick_capture_enabled() in start()"
    )
    assert _calls_named(start, "_build_tick_recorder"), (
        "start() must construct the recorder through the runtime-tested seam"
    )
    assert _calls_named(start, "create_task"), (
        "start() must launch the recorder via asyncio.create_task so it runs "
        "as a background task on the event loop"
    )
    source_lines = APP_PY.read_text(encoding="utf-8").splitlines()
    start_source = "\n".join(source_lines[start.lineno - 1 : start.end_lineno])
    lifecycle = start_source.index("with _tick_capture_lifecycle_lock(flask_app):")
    refreshed = start_source.index("capture_settings = Settings.from_env()")
    built = start_source.index("settings=capture_settings")
    published = start_source.index('flask_app.config["TICK_RECORDER"] = recorder')
    assert lifecycle < refreshed < built < published


@pytest.mark.unit
def test_build_tick_recorder_uses_exact_settings_watchlist_and_existing_hub() -> None:
    from flinttrade_core.app import _build_tick_recorder

    class FakeHub:
        constructions = 0

        def __init__(self) -> None:
            type(self).constructions += 1
            self.instruments: list[str] = []
            self.ticks: list[tuple[str, str, float, int]] = []

        def update_config(self, *, instruments: list[str]) -> None:
            self.instruments = instruments

        def process_tick(self, exchange: str, symbol: str, ltp: float, volume: int) -> None:
            self.ticks.append((exchange, symbol, ltp, volume))

    class FakeRecorder:
        def __init__(self) -> None:
            self.watchlist = None
            self.mode = None

        def add_symbols(self, watchlist, *, mode: str) -> None:
            self.watchlist = watchlist
            self.mode = mode

    hub = FakeHub()
    storage = object()
    storage_lock = object()
    orderflow = object()
    watchlist = [
        {"exchange": "nse", "symbol": "reliance"},
        {"exchange": "NSE_INDEX", "symbol": "nifty"},
    ]
    settings = Settings(
        openalgo_host="https://openalgo.local:5000",
        openalgo_ws_port=8770,
        openalgo_api_key="workspace-key",
    )
    factory_calls: list[dict] = []

    def recorder_factory(**kwargs):
        factory_calls.append(kwargs)
        return FakeRecorder()

    recorder = _build_tick_recorder(
        recorder_factory=recorder_factory,
        signal_hub=hub,
        settings=settings,
        storage=storage,
        storage_lock=storage_lock,
        orderflow=orderflow,
        watchlist=watchlist,
        mode="depth",
    )

    assert FakeHub.constructions == 1
    assert hub.instruments == ["NSE:RELIANCE", "NSE_INDEX:NIFTY"]
    assert len(factory_calls) == 1
    call = factory_calls[0]
    assert call["storage"] is storage
    assert call["storage_lock"] is storage_lock
    assert call["orderflow_aggregator"] is orderflow
    assert call["ws_url"] == "wss://openalgo.local:8770"
    assert call["api_key"] == "workspace-key"
    assert call["ltp_sink"].__self__ is hub
    assert call["ltp_sink"].__func__ is FakeHub.process_tick
    assert recorder.watchlist is watchlist
    assert recorder.mode == "depth"


@pytest.mark.unit
@pytest.mark.parametrize("failure_stage", ["factory", "watchlist"])
def test_build_tick_recorder_failure_does_not_reconfigure_signal_hub(failure_stage: str) -> None:
    from flinttrade_core.app import _build_tick_recorder

    class FakeHub:
        def __init__(self) -> None:
            self.instruments = ["NSE_INDEX:NIFTY"]

        def update_config(self, *, instruments: list[str]) -> None:
            self.instruments = instruments

        def process_tick(self, exchange: str, symbol: str, ltp: float, volume: int) -> None:
            return None

    class FakeRecorder:
        def add_symbols(self, watchlist, *, mode: str) -> None:
            if failure_stage == "watchlist":
                raise ValueError("watchlist rejected")

    def recorder_factory(**kwargs):
        if failure_stage == "factory":
            raise RuntimeError("recorder construction failed")
        return FakeRecorder()

    hub = FakeHub()
    with pytest.raises((RuntimeError, ValueError)):
        _build_tick_recorder(
            recorder_factory=recorder_factory,
            signal_hub=hub,
            settings=Settings(openalgo_api_key="workspace-key"),
            storage=object(),
            storage_lock=object(),
            orderflow=object(),
            watchlist=[{"exchange": "NSE", "symbol": "RELIANCE"}],
            mode="quote",
        )

    assert hub.instruments == ["NSE_INDEX:NIFTY"]


@pytest.mark.unit
def test_start_sets_capture_intent_before_starting_flask_server() -> None:
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    start = _find_method(tree, "FlintTradeApp", "start")
    assert start is not None
    calls = {
        node.func.id: node.lineno
        for node in ast.walk(start)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"_set_tick_capture_intent", "_run_flask_server"}
    }

    assert calls["_set_tick_capture_intent"] < calls["_run_flask_server"]


@pytest.mark.unit
def test_start_uses_precise_live_market_orderflow_factory() -> None:
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    start = _find_method(tree, "FlintTradeApp", "start")
    assert start is not None

    assert _calls_named(start, "create_live_market_orderflow_aggregator")


@pytest.mark.unit
def test_capture_failure_redacts_api_key_from_status_and_log(caplog) -> None:
    from flinttrade_core.app import _record_tick_capture_failure

    flask_app = Flask("capture_failure")
    api_key = "top-secret-workspace-key"
    caplog.set_level(logging.WARNING, logger="flinttrade")

    _record_tick_capture_failure(
        flask_app,
        RuntimeError(f"OpenAlgo rejected {api_key}"),
        api_key,
    )

    assert flask_app.config["TICK_CAPTURE_ERROR"] == "OpenAlgo rejected [redacted]"
    assert api_key not in flask_app.config["TICK_CAPTURE_ERROR"]
    assert api_key not in caplog.text
    assert "OpenAlgo rejected [redacted]" in caplog.text


@pytest.mark.unit
def test_stop_stops_tick_recorder() -> None:
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    stop_once = _find_method(tree, "FlintTradeApp", "_stop_once")
    assert stop_once is not None, "FlintTradeApp._stop_once not found"
    # The stop path must reference the recorder handle so it is shut down.
    refs = [
        n
        for n in ast.walk(stop_once)
        if isinstance(n, ast.Attribute) and n.attr == "_tick_recorder"
    ]
    assert refs, "_stop_once() must stop/cancel the tick recorder (_tick_recorder)"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_awaits_cancelled_tick_recorder_cleanup() -> None:
    from flinttrade_core.app import FlintTradeApp

    class CancelledTask:
        def __init__(self) -> None:
            self.cancelled = False
            self.awaited = False

        def cancel(self) -> None:
            self.cancelled = True

        def __await__(self):
            async def wait() -> None:
                self.awaited = True
                raise asyncio.CancelledError

            return wait().__await__()

    app = FlintTradeApp.__new__(FlintTradeApp)
    app.scheduler = MagicMock(stop_all=AsyncMock())
    app.cron = MagicMock()
    app.telegram = None
    app._tick_recorder = MagicMock()
    task = CancelledTask()
    app._tick_recorder_task = task
    tick_storage = MagicMock()
    app._tick_storage = tick_storage
    app._tick_storage_lock = __import__("threading").Lock()
    app._reconciliation_runner = None
    app._reconciliation_task = None
    app.audit = MagicMock()
    app.client = MagicMock(close=AsyncMock())
    app.version = "test"
    app._stop_event = MagicMock()

    await app.stop()

    app._tick_recorder.stop.assert_called_once_with()
    assert task.cancelled is True
    assert task.awaited is True
    tick_storage.close.assert_called_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_unpublishes_tick_handles_before_closing_storage() -> None:
    from flinttrade_core.app import FlintTradeApp

    flask_app = Flask("shutdown-tick-capture")
    recorder = MagicMock()
    tick_storage = MagicMock()
    tick_storage_lock = __import__("threading").Lock()
    flask_app.config.update(
        TICK_CAPTURE_LIFECYCLE_LOCK=__import__("threading").RLock(),
        TICK_CAPTURE_ENABLED=True,
        TICK_CAPTURE_ERROR="",
        TICK_RECORDER=recorder,
        TICK_STORAGE=tick_storage,
        TICK_STORAGE_LOCK=tick_storage_lock,
        ORDERFLOW_AGGREGATOR=object(),
    )

    app = FlintTradeApp.__new__(FlintTradeApp)
    app.scheduler = MagicMock(stop_all=AsyncMock())
    app.cron = MagicMock()
    app.telegram = None
    app._flask_app = flask_app
    app._tick_recorder = recorder
    app._tick_recorder_task = None
    app._tick_storage = tick_storage
    app._tick_storage_lock = tick_storage_lock
    app._reconciliation_runner = None
    app._reconciliation_task = None
    app.audit = MagicMock()
    app.client = MagicMock(close=AsyncMock())
    app.version = "test"
    app._stop_event = MagicMock()

    await app.stop()

    assert "TICK_RECORDER" not in flask_app.config
    assert "TICK_STORAGE" not in flask_app.config
    assert "TICK_STORAGE_LOCK" not in flask_app.config
    assert "ORDERFLOW_AGGREGATOR" not in flask_app.config
    tick_storage.close.assert_called_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_awaits_reconciliation_cleanup_before_closing_dependencies() -> None:
    from flinttrade_core.app import FlintTradeApp

    cleanup_finished = asyncio.Event()

    async def run_reconciliation() -> None:
        try:
            await asyncio.Future()
        finally:
            await asyncio.sleep(0)
            cleanup_finished.set()

    reconciliation_task = asyncio.create_task(run_reconciliation())
    await asyncio.sleep(0)

    async def close_client() -> None:
        assert cleanup_finished.is_set()

    app = FlintTradeApp.__new__(FlintTradeApp)
    app.scheduler = MagicMock(stop_all=AsyncMock())
    app.cron = MagicMock()
    app.telegram = None
    app._tick_recorder = None
    app._tick_recorder_task = None
    app._reconciliation_runner = MagicMock()
    app._reconciliation_task = reconciliation_task
    app.audit = MagicMock()
    app.client = MagicMock(close=AsyncMock(side_effect=close_client))
    app.version = "test"
    app._stop_event = MagicMock()

    await app.stop()

    app._reconciliation_runner.stop.assert_called_once_with()
    assert reconciliation_task.cancelled()
    assert cleanup_finished.is_set()
    app.client.close.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failed_reconciliation_task_is_cleared_before_shutdown_retry() -> None:
    from flinttrade_core.app import FlintTradeApp

    class FailedTask:
        def cancel(self) -> None:
            return None

        def __await__(self):
            async def wait() -> None:
                raise RuntimeError("reconciliation cleanup failed")

            return wait().__await__()

    app = FlintTradeApp.__new__(FlintTradeApp)
    app.scheduler = MagicMock(stop_all=AsyncMock())
    app.cron = MagicMock()
    app.telegram = None
    app._tick_recorder = None
    app._tick_recorder_task = None
    app._reconciliation_runner = MagicMock()
    app._reconciliation_task = FailedTask()
    app.audit = MagicMock()
    app.client = MagicMock(close=AsyncMock())
    app.version = "test"
    app._stop_event = MagicMock()

    with pytest.raises(RuntimeError, match="reconciliation task"):
        await app.stop()

    assert app._reconciliation_task is None
    await app.stop()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concurrent_stop_requests_run_shutdown_once() -> None:
    from flinttrade_core.app import FlintTradeApp

    app = FlintTradeApp.__new__(FlintTradeApp)
    app.scheduler = MagicMock(stop_all=AsyncMock())
    app.cron = MagicMock()
    app.telegram = MagicMock()
    app._tick_recorder = None
    app._tick_recorder_task = None
    app._reconciliation_runner = None
    app._reconciliation_task = None
    app.audit = MagicMock()
    app.client = MagicMock(close=AsyncMock())
    app.version = "test"
    app._stop_event = MagicMock()

    await asyncio.gather(app.stop(), app.stop())

    app.scheduler.stop_all.assert_awaited_once_with()
    app.cron.stop.assert_called_once_with()
    app.telegram.stop.assert_called_once_with()
    app.client.close.assert_awaited_once_with()
    app.audit.close.assert_called_once_with()
    app._stop_event.set.assert_called_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_concurrent_stop_caller_waits_for_active_shutdown() -> None:
    from flinttrade_core.app import FlintTradeApp

    shutdown_started = asyncio.Event()
    release_shutdown = asyncio.Event()

    async def blocking_stop_all() -> None:
        shutdown_started.set()
        await release_shutdown.wait()

    app = FlintTradeApp.__new__(FlintTradeApp)
    app.scheduler = MagicMock(stop_all=AsyncMock(side_effect=blocking_stop_all))
    app.cron = MagicMock()
    app.telegram = None
    app._tick_recorder = None
    app._tick_recorder_task = None
    app._reconciliation_runner = None
    app._reconciliation_task = None
    app.audit = MagicMock()
    app.client = MagicMock(close=AsyncMock())
    app.version = "test"
    app._stop_event = MagicMock()

    first = asyncio.create_task(app.stop())
    await shutdown_started.wait()
    second = asyncio.create_task(app.stop())
    await asyncio.sleep(0)

    assert second.done() is False
    release_shutdown.set()
    await asyncio.gather(first, second)
    app.scheduler.stop_all.assert_awaited_once_with()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failed_shutdown_finalises_and_can_be_retried() -> None:
    from flinttrade_core.app import FlintTradeApp

    app = FlintTradeApp.__new__(FlintTradeApp)
    app.scheduler = MagicMock(
        stop_all=AsyncMock(side_effect=[RuntimeError("scheduler failed"), None])
    )
    app.cron = MagicMock()
    app.telegram = MagicMock()
    app._tick_recorder = None
    app._tick_recorder_task = None
    app._reconciliation_runner = None
    app._reconciliation_task = None
    app.audit = MagicMock()
    app.client = MagicMock(close=AsyncMock())
    app.version = "test"
    app._stop_event = MagicMock()

    with pytest.raises(RuntimeError, match="scheduler"):
        await app.stop()

    app.cron.stop.assert_called_once_with()
    app.telegram.stop.assert_called_once_with()
    app.client.close.assert_awaited_once_with()
    app.audit.close.assert_called_once_with()
    app._stop_event.set.assert_called_once_with()

    await app.stop()

    assert app.scheduler.stop_all.await_count == 2
    assert app._stop_event.set.call_count == 2


@pytest.mark.unit
def test_failed_recorder_completion_is_unpublished_and_redacted() -> None:
    from flinttrade_core.app import _handle_tick_recorder_completion

    class FailedTask:
        @staticmethod
        def cancelled() -> bool:
            return False

        @staticmethod
        def exception() -> BaseException:
            return RuntimeError("fatal recorder error with boot-secret and rotated-secret")

    class Recorder:
        @staticmethod
        def sanitise_error(value: object) -> str:
            return str(value).replace("rotated-secret", "[redacted]")

    flask_app = Flask("failed-recorder")
    recorder = Recorder()
    storage = MagicMock()
    flask_app.config.update(
        TICK_CAPTURE_LIFECYCLE_LOCK=__import__("threading").RLock(),
        TICK_RECORDER=recorder,
        TICK_STORAGE=storage,
        TICK_STORAGE_LOCK=__import__("threading").Lock(),
        ORDERFLOW_AGGREGATOR=object(),
    )

    unpublished = _handle_tick_recorder_completion(
        flask_app,
        recorder,
        FailedTask(),
        api_key="boot-secret",
        is_shutting_down=lambda: False,
    )

    assert "TICK_RECORDER" not in flask_app.config
    assert "TICK_STORAGE" not in flask_app.config
    assert "TICK_STORAGE_LOCK" not in flask_app.config
    assert "ORDERFLOW_AGGREGATOR" not in flask_app.config
    assert flask_app.config["TICK_CAPTURE_ERROR"] == "fatal recorder error with [redacted] and [redacted]"
    assert unpublished is True
    storage.close.assert_called_once_with()


@pytest.mark.unit
def test_failed_recorder_completion_retains_storage_owner_when_close_fails() -> None:
    from flinttrade_core.app import _handle_tick_recorder_completion

    class FailedTask:
        @staticmethod
        def cancelled() -> bool:
            return False

        @staticmethod
        def exception() -> BaseException:
            return RuntimeError("recorder failed")

    storage = MagicMock()
    storage.close.side_effect = RuntimeError("close failed")
    owner = {"recorder": object(), "storage": storage}
    flask_app = Flask("failed-storage-close")
    flask_app.config.update(
        TICK_CAPTURE_LIFECYCLE_LOCK=__import__("threading").RLock(),
        TICK_RECORDER=owner["recorder"],
        TICK_STORAGE=storage,
        TICK_STORAGE_LOCK=__import__("threading").Lock(),
        ORDERFLOW_AGGREGATOR=object(),
    )

    handled = _handle_tick_recorder_completion(
        flask_app,
        owner["recorder"],
        FailedTask(),
        api_key="",
        on_unpublished=lambda: owner.__setitem__("recorder", None),
        on_storage_closed=lambda: owner.__setitem__("storage", None),
    )

    assert handled is True
    assert owner["recorder"] is None
    assert owner["storage"] is storage
    assert "TICK_STORAGE" not in flask_app.config


@pytest.mark.unit
def test_normal_recorder_completion_during_shutdown_is_not_reported() -> None:
    from flinttrade_core.app import _handle_tick_recorder_completion

    class CompletedTask:
        @staticmethod
        def cancelled() -> bool:
            return False

        @staticmethod
        def exception() -> None:
            return None

    flask_app = Flask("stopping-recorder")
    recorder = object()
    flask_app.config.update(
        TICK_CAPTURE_LIFECYCLE_LOCK=__import__("threading").RLock(),
        TICK_RECORDER=recorder,
        TICK_CAPTURE_ERROR="",
    )

    unpublished = _handle_tick_recorder_completion(
        flask_app,
        recorder,
        CompletedTask(),
        api_key="boot-secret",
        is_shutting_down=lambda: True,
    )

    assert flask_app.config["TICK_RECORDER"] is recorder
    assert flask_app.config["TICK_CAPTURE_ERROR"] == ""
    assert unpublished is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stop_cancellation_reaches_real_recorder_final_flush(monkeypatch) -> None:
    import flinttrade_data.tick_recorder as recorder_module
    from flinttrade_core.app import FlintTradeApp
    from flinttrade_data.tick_recorder import TickRecorder

    class FakeStorage:
        def __init__(self) -> None:
            self.batches: list[list[tuple]] = []

        def insert_ticks_batch(self, rows) -> None:
            self.batches.append(list(rows))

    class BlockingWebSocket:
        def __init__(self) -> None:
            self.consume_started = asyncio.Event()

        def __aiter__(self):
            return self

        async def send(self, _payload: str) -> None:
            return None

        async def __anext__(self):
            self.consume_started.set()
            await asyncio.Future()

    class WebSocketContext:
        def __init__(self, websocket) -> None:
            self.websocket = websocket

        async def __aenter__(self):
            return self.websocket

        async def __aexit__(self, exc_type, exc, traceback) -> bool:
            return False

    storage = FakeStorage()
    websocket = BlockingWebSocket()
    recorder = TickRecorder(storage=storage, ws_url="ws://openalgo.local:8770")
    recorder.add_symbols([{"exchange": "NSE_INDEX", "symbol": "NIFTY"}])
    recorder._process_tick({
        "exchange": "NSE_INDEX",
        "symbol": "NIFTY",
        "data": {"ltp": 24500.0, "volume": 10},
    })
    monkeypatch.setattr(
        recorder_module.websockets,
        "connect",
        lambda *_args, **_kwargs: WebSocketContext(websocket),
    )
    monkeypatch.setattr(recorder, "_authenticate", AsyncMock())
    recorder_task = asyncio.create_task(recorder.run())
    await asyncio.wait_for(websocket.consume_started.wait(), timeout=1.0)

    app = FlintTradeApp.__new__(FlintTradeApp)
    app.scheduler = MagicMock(stop_all=AsyncMock())
    app.cron = MagicMock()
    app.telegram = None
    app._tick_recorder = recorder
    app._tick_recorder_task = recorder_task
    app._reconciliation_runner = None
    app._reconciliation_task = None
    app.audit = MagicMock()
    app.client = MagicMock(close=AsyncMock())
    app.version = "test"
    app._stop_event = MagicMock()

    await app.stop()

    assert recorder_task.done()
    assert recorder.is_running is False
    assert len(storage.batches) == 1
    assert len(storage.batches[0]) == 1
    assert storage.batches[0][0][1:3] == ("NIFTY", "NSE_INDEX")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failed_tick_task_fails_shutdown_after_cleanup_without_leaking_api_key(caplog) -> None:
    from flinttrade_core.app import FlintTradeApp

    class FailedTask:
        def cancel(self) -> None:
            return None

        def __await__(self):
            async def wait() -> None:
                raise RuntimeError("recorder failed with boot-secret and rotated-secret")

            return wait().__await__()

    class Recorder:
        def stop(self) -> None:
            return None

        def sanitise_error(self, error: object) -> str:
            return str(error).replace("boot-secret", "[redacted]").replace("rotated-secret", "[redacted]")

    app = FlintTradeApp.__new__(FlintTradeApp)
    app.scheduler = MagicMock(stop_all=AsyncMock())
    app.cron = MagicMock()
    app.telegram = None
    app._tick_recorder = Recorder()
    app._tick_recorder_task = FailedTask()
    app._reconciliation_runner = None
    app._reconciliation_task = None
    app.audit = MagicMock()
    app.client = MagicMock(close=AsyncMock())
    app.settings = Settings(openalgo_api_key="boot-secret")
    app.version = "test"
    app._stop_event = MagicMock()
    caplog.set_level(logging.WARNING, logger="flinttrade")

    with pytest.raises(RuntimeError, match="tick recorder task"):
        await app.stop()

    app.client.close.assert_awaited_once_with()
    app.audit.close.assert_called_once_with()
    app._stop_event.set.assert_called_once_with()
    assert "boot-secret" not in caplog.text
    assert "rotated-secret" not in caplog.text
    assert "[redacted]" in caplog.text


@pytest.mark.unit
def test_workspace_config_readers(tmp_path, monkeypatch) -> None:
    """Tick mode + auto-sync flags read from workspace.json with safe defaults."""
    import json

    from flinttrade_core.app import (
        _auto_sync_enabled,
        _auto_sync_lookback_days,
        _tick_capture_mode,
        _tick_capture_watchlist,
    )

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))

    # No workspace.json → safe defaults.
    assert _tick_capture_mode() == "quote"
    assert _auto_sync_enabled() is False
    assert _auto_sync_lookback_days() == 7
    assert len(_tick_capture_watchlist()) == 3  # default index trio

    (tmp_path / "workspace.json").write_text(json.dumps({
        "data": {
            "tick_capture": {
                "mode": "depth",
                "symbols": [
                    {"exchange": "nse", "symbol": "reliance"},
                    {"bogus": True},
                ],
            },
            "auto_sync": {"enabled": True, "lookback_days": 30},
        },
    }), encoding="utf-8")

    assert _tick_capture_mode() == "depth"
    assert _auto_sync_enabled() is True
    assert _auto_sync_lookback_days() == 30
    # Malformed entries skipped; valid ones normalised to upper case.
    assert _tick_capture_watchlist() == [{"exchange": "NSE", "symbol": "RELIANCE"}]

    # Invalid mode falls back to quote, lookback clamps.
    (tmp_path / "workspace.json").write_text(json.dumps({
        "data": {"tick_capture": {"mode": "warp"}, "auto_sync": {"enabled": 1, "lookback_days": 900}},
    }), encoding="utf-8")
    assert _tick_capture_mode() == "quote"
    assert _auto_sync_enabled() is True
    assert _auto_sync_lookback_days() == 90
