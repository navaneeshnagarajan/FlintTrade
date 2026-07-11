"""Regression coverage for process-wide startup and shutdown ownership."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import MethodType
from unittest.mock import AsyncMock, MagicMock

from flask import Flask
import pytest


pytestmark = pytest.mark.unit


def _runtime_app() -> object:
    """Build the lifecycle shell without running the heavyweight constructor."""
    from flinttrade_core.app import FlintTradeApp

    app = FlintTradeApp.__new__(FlintTradeApp)
    app.safety = MagicMock()
    app.scheduler = MagicMock(stop_all=AsyncMock())
    app.time_scheduler = MagicMock()
    app.cron = MagicMock()
    app.audit = MagicMock()
    app.client = MagicMock(close=AsyncMock(), ping=AsyncMock(return_value={}))
    app.registry = MagicMock()
    app.credential_store = MagicMock()
    app.contract_manager = MagicMock()
    app.rag = None
    app.telegram = None
    app.settings = MagicMock(openalgo_host="http://127.0.0.1", openalgo_api_key="")
    app.version = "test"
    app._tick_recorder = None
    app._tick_recorder_task = None
    app._tick_storage = None
    app._tick_storage_lock = None
    app._flask_app = None
    app._reconciliation_runner = None
    app._reconciliation_task = None
    app._stop_started = False
    app._stop_completed = False
    app._shutdown_task = None
    app._shutdown_request_task = None
    app._stop_event = asyncio.Event()
    return app


@pytest.mark.asyncio
async def test_stop_during_holiday_load_prevents_startup_from_resuming(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A stop that wins an await boundary must own the rest of the lifecycle."""
    import flinttrade_core.app as app_module

    app = _runtime_app()
    holiday_load_started = asyncio.Event()
    release_holiday_load = asyncio.Event()

    async def load_holidays() -> set[str]:
        holiday_load_started.set()
        await release_holiday_load.wait()
        return set()

    app.cron.load_holidays = load_holidays
    app.cron.register_builtin_jobs = MagicMock(
        side_effect=AssertionError("startup resumed after shutdown")
    )
    flask_app = Flask("startup-stop-race")
    flask_app.config["RUNTIME_ACCEPTING_REQUESTS"] = True

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(app_module, "create_flask_app", lambda **_kwargs: flask_app)
    monkeypatch.setattr(app_module, "_run_flask_server", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_module, "_tick_capture_enabled", lambda: False)
    monkeypatch.setattr(app_module, "_auto_sync_enabled", lambda: False)
    monkeypatch.setattr(app_module, "_wire_ml_signal_runtime", lambda *_args: None)

    start_task = asyncio.create_task(app.start())
    await asyncio.wait_for(holiday_load_started.wait(), timeout=1.0)
    await app.stop()
    release_holiday_load.set()
    await asyncio.wait_for(start_task, timeout=1.0)

    app.cron.register_builtin_jobs.assert_not_called()
    app.time_scheduler.set_holidays.assert_not_called()
    assert flask_app.config["RUNTIME_ACCEPTING_REQUESTS"] is False


def test_runtime_admission_closes_before_authentication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """No route may touch closing dependencies once process teardown starts."""
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setenv("FLINTTRADE_API_KEY", "configured-key")
    monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
    password = tmp_path / "master_password"
    password.write_text("runtime-lifecycle-test-password", encoding="utf-8")
    password.chmod(0o600)

    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True
    app.config["RUNTIME_ACCEPTING_REQUESTS"] = False

    response = app.test_client().get("/v1/sandbox/capital")

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert response.get_json() == {
        "status": "error",
        "message": "Application is shutting down",
    }


@pytest.mark.asyncio
async def test_shutdown_drains_admitted_request_before_closing_dependencies() -> None:
    """An admitted handler retains dependency ownership until it returns."""
    from flinttrade_core.app import _install_runtime_request_tracking

    runtime = _runtime_app()
    flask_app = Flask("request-drain")
    _install_runtime_request_tracking(flask_app)
    runtime._flask_app = flask_app
    request_started = threading.Event()
    release_request = threading.Event()
    response_status: list[int] = []

    @flask_app.get("/blocking")
    def blocking_request() -> tuple[str, int]:
        request_started.set()
        release_request.wait(timeout=2.0)
        return "done", 200

    def make_request() -> None:
        response = flask_app.test_client().get("/blocking")
        response_status.append(response.status_code)

    request_thread = threading.Thread(target=make_request, daemon=True)
    request_thread.start()
    assert await asyncio.to_thread(request_started.wait, 1.0)

    stop_task = asyncio.create_task(runtime.stop())
    await asyncio.sleep(0.05)
    runtime.scheduler.stop_all.assert_not_awaited()
    rejected = flask_app.test_client().get("/blocking")
    assert rejected.status_code == 503

    release_request.set()
    await asyncio.wait_for(stop_task, timeout=1.0)
    request_thread.join(timeout=1.0)

    assert response_status == [200]
    runtime.scheduler.stop_all.assert_awaited_once_with()
    runtime.client.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_request_drain_timeout_leaves_dependencies_open_for_retry() -> None:
    """A stuck request fails shutdown without tearing down state beneath it."""
    from flinttrade_core.app import _install_runtime_request_tracking

    runtime = _runtime_app()
    flask_app = Flask("request-drain-timeout")
    _install_runtime_request_tracking(flask_app)
    flask_app.config["RUNTIME_REQUEST_DRAIN_TIMEOUT_SECONDS"] = 0.02
    runtime._flask_app = flask_app
    request_started = threading.Event()
    release_request = threading.Event()

    @flask_app.get("/blocking")
    def blocking_request() -> tuple[str, int]:
        request_started.set()
        release_request.wait(timeout=2.0)
        return "done", 200

    request_thread = threading.Thread(
        target=lambda: flask_app.test_client().get("/blocking"),
        daemon=True,
    )
    request_thread.start()
    assert await asyncio.to_thread(request_started.wait, 1.0)

    with pytest.raises(RuntimeError, match="active requests"):
        await runtime.stop()

    runtime.scheduler.stop_all.assert_not_awaited()
    runtime.client.close.assert_not_awaited()
    release_request.set()
    request_thread.join(timeout=1.0)

    await runtime.stop()
    runtime.scheduler.stop_all.assert_awaited_once_with()
    runtime.client.close.assert_awaited_once_with()


def test_run_propagates_background_shutdown_failure() -> None:
    """The process must not exit successfully after a failed signal shutdown."""
    from flinttrade_core.app import FlintTradeApp

    app = FlintTradeApp.__new__(FlintTradeApp)
    app._shutdown_task = None
    app._shutdown_request_task = None

    async def start(_self: object) -> None:
        async def fail_shutdown() -> None:
            await asyncio.sleep(0)
            raise RuntimeError("shutdown encountered errors: tick recorder")

        app._shutdown_task = asyncio.create_task(fail_shutdown())
        await asyncio.sleep(0)

    app.start = MethodType(start, app)

    with pytest.raises(RuntimeError, match="tick recorder"):
        app.run()


@pytest.mark.asyncio
async def test_shutdown_cancels_retraining_before_waiting_for_cron() -> None:
    """Cron's blocking shutdown must see cooperative ML cancellation first."""
    app = _runtime_app()
    cancel_event = threading.Event()
    flask_app = Flask("retrain-cancellation")
    flask_app.config["ML_SIGNAL_RETRAIN_CANCEL_EVENT"] = cancel_event
    app._flask_app = flask_app

    def stop_cron() -> None:
        assert cancel_event.is_set()

    app.cron.stop = MagicMock(side_effect=stop_cron)

    await app.stop()

    app.cron.stop.assert_called_once_with()


@pytest.mark.asyncio
async def test_start_applies_cron_holidays_to_time_scheduler(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The market-hours owner receives the calendar fetched at startup."""
    import flinttrade_core.app as app_module

    app = _runtime_app()
    holidays = {"2026-01-26", "2026-08-15"}
    app.cron.load_holidays = AsyncMock(return_value=holidays)
    flask_app = Flask("holiday-runtime-wiring")

    def apply_holidays(values: set[str]) -> None:
        assert values == holidays
        app._stop_started = True
        app._stop_event.set()

    app.time_scheduler.set_holidays = MagicMock(side_effect=apply_holidays)
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(app_module, "create_flask_app", lambda **_kwargs: flask_app)
    monkeypatch.setattr(app_module, "_run_flask_server", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_module, "_tick_capture_enabled", lambda: False)

    await app.start()

    app.time_scheduler.set_holidays.assert_called_once_with(holidays)
