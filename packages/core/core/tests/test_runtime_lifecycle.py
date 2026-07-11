"""Regression coverage for process-wide startup and shutdown ownership."""

from __future__ import annotations

import asyncio
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
