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
    app.strategy_cron_scheduler = MagicMock(running=False)
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
    app._holiday_refresh_task = None
    app._stop_event = asyncio.Event()
    app._shutdown_failed_event = asyncio.Event()
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
    assert runtime._stop_event.is_set() is False
    release_request.set()
    request_thread.join(timeout=1.0)

    await runtime.stop()
    runtime.scheduler.stop_all.assert_awaited_once_with()
    runtime.client.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_shutdown_quiesces_stream_agent_and_rotation_before_request_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Long-lived/background writers stop before admitted requests are drained."""
    import flinttrade_core.agent_routes as agent_routes

    runtime = _runtime_app()
    flask_app = Flask("shutdown-quiesce-order")
    stream_shutdown = threading.Event()
    events: list[str] = []
    rotation = MagicMock(running=True)
    rotation.shutdown.side_effect = lambda **_kwargs: events.append("rotation")
    tracker = MagicMock()

    def wait_for_idle(_timeout: float) -> bool:
        assert stream_shutdown.is_set()
        assert events == ["agent", "rotation"]
        return True

    tracker.wait_for_idle.side_effect = wait_for_idle
    flask_app.config.update(
        RUNTIME_REQUEST_TRACKER=tracker,
        SIGNAL_STREAM_SHUTDOWN_EVENT=stream_shutdown,
        ROTATION_SCHEDULER=rotation,
    )
    runtime._flask_app = flask_app
    monkeypatch.setattr(
        agent_routes,
        "shutdown_agent_runtime",
        lambda _app, **_kwargs: events.append("agent") or True,
        raising=False,
    )

    await runtime.stop()

    rotation.shutdown.assert_called_once_with(wait=False)
    tracker.wait_for_idle.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown_retires_router_before_dependencies_close() -> None:
    runtime = _runtime_app()
    flask_app = Flask("shutdown-router-retirement")
    router = MagicMock()
    router.revoke_and_drain.side_effect = (
        lambda **_kwargs: flask_app.config.get("BROKER_ROUTER") is None
    )
    flask_app.config["BROKER_ROUTER"] = router
    runtime._flask_app = flask_app

    await runtime.stop()

    router.revoke_and_drain.assert_called_once_with(timeout=10.0)
    assert flask_app.config["BROKER_ROUTER"] is None
    assert flask_app.config["BROKER_ROUTER_DRAINING"] is None
    runtime.client.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_shutdown_retires_router_published_by_an_admitted_request() -> None:
    """A request that started before shutdown cannot leave a fresh router live."""
    runtime = _runtime_app()
    flask_app = Flask("shutdown-router-request-race")
    first_router = MagicMock()
    replacement_router = MagicMock()
    first_router.revoke_and_drain.return_value = True
    replacement_router.revoke_and_drain.return_value = True
    tracker = MagicMock()

    def drain_request(_timeout: float) -> bool:
        flask_app.config["BROKER_ROUTER"] = replacement_router
        return True

    tracker.wait_for_idle.side_effect = drain_request
    flask_app.config.update(
        BROKER_ROUTER=first_router,
        RUNTIME_REQUEST_TRACKER=tracker,
    )
    runtime._flask_app = flask_app

    await runtime.stop()

    first_router.revoke_and_drain.assert_called_once_with(timeout=10.0)
    replacement_router.revoke_and_drain.assert_called_once_with(timeout=10.0)
    assert flask_app.config["BROKER_ROUTER"] is None
    assert flask_app.config["BROKER_ROUTER_DRAINING"] is None


@pytest.mark.asyncio
async def test_shutdown_revokes_router_before_stopping_rotation_scheduler() -> None:
    """A blocked SDK refresh must not keep a published write router reachable."""
    runtime = _runtime_app()
    flask_app = Flask("shutdown-router-before-rotation")
    router = MagicMock()
    router.revoke_and_drain.return_value = True
    rotation = MagicMock(running=True)

    def stop_rotation(*, wait: bool) -> None:
        assert wait is False
        assert flask_app.config["BROKER_ROUTER"] is None

    rotation.shutdown.side_effect = stop_rotation
    flask_app.config.update(
        BROKER_ROUTER=router,
        ROTATION_SCHEDULER=rotation,
    )
    runtime._flask_app = flask_app

    await runtime.stop()

    router.revoke_and_drain.assert_called_once_with(timeout=10.0)
    rotation.shutdown.assert_called_once_with(wait=False)


@pytest.mark.asyncio
async def test_agent_shutdown_failure_preserves_dependencies_for_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.agent_routes as agent_routes

    runtime = _runtime_app()
    flask_app = Flask("agent-shutdown-failure")
    tracker = MagicMock()
    flask_app.config["RUNTIME_REQUEST_TRACKER"] = tracker
    runtime._flask_app = flask_app
    monkeypatch.setattr(
        agent_routes,
        "shutdown_agent_runtime",
        lambda _app, **_kwargs: False,
        raising=False,
    )

    with pytest.raises(RuntimeError, match="autonomous agent"):
        await runtime.stop()

    tracker.wait_for_idle.assert_not_called()
    runtime.client.close.assert_not_awaited()
    assert runtime._stop_event.is_set() is False


@pytest.mark.asyncio
async def test_failed_tick_finalisation_retries_retained_buffer_before_closing() -> None:
    runtime = _runtime_app()
    flush_pending = MagicMock()
    runtime._tick_recorder = MagicMock(
        stop=MagicMock(),
        flush_pending=flush_pending,
        sanitise_error=lambda exc: type(exc).__name__,
    )

    async def failed_finalisation() -> None:
        raise RuntimeError("final flush failed")

    runtime._tick_recorder_task = asyncio.create_task(failed_finalisation())
    await asyncio.sleep(0)

    await runtime.stop()

    flush_pending.assert_called_once_with()
    runtime.client.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_start_injects_and_starts_shared_strategy_cron_scheduler(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Strategy schedules use the same live calendar owner as the app runtime."""
    import flinttrade_core.app as app_module

    app = _runtime_app()
    app.cron.load_holidays = AsyncMock(return_value=set())
    app.cron.holiday_payload = []
    flask_app = Flask("shared-strategy-cron")
    captured_factory_args: dict[str, object] = {}

    def create_app(**kwargs: object) -> Flask:
        captured_factory_args.update(kwargs)
        flask_app.config["CRON_SCHEDULER"] = kwargs["cron_strategy_scheduler"]
        return flask_app

    def start_strategy_cron() -> None:
        assert flask_app.config["CRON_SCHEDULER"] is app.strategy_cron_scheduler

    app.strategy_cron_scheduler.start.side_effect = start_strategy_cron
    app.cron.start.side_effect = app._stop_event.set
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(app_module, "create_flask_app", create_app)
    monkeypatch.setattr(app_module, "_run_flask_server", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_module, "_tick_capture_enabled", lambda: False)

    await app.start()

    assert captured_factory_args["cron_strategy_scheduler"] is app.strategy_cron_scheduler
    app.strategy_cron_scheduler.start.assert_called_once_with()


@pytest.mark.asyncio
async def test_failed_initial_calendar_load_does_not_replace_the_calendar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An unauthenticated holiday response is not an authoritative empty year."""
    import flinttrade_core.app as app_module

    app = _runtime_app()
    app.cron.load_holidays = AsyncMock(return_value=set())
    app.cron.holiday_payload = None
    flask_app = Flask("failed-calendar-load")

    app.cron.start.side_effect = app._stop_event.set
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(app_module, "create_flask_app", lambda **_kwargs: flask_app)
    monkeypatch.setattr(app_module, "_run_flask_server", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_module, "_tick_capture_enabled", lambda: False)

    await app.start()

    app.time_scheduler.set_holidays.assert_not_called()


@pytest.mark.asyncio
async def test_calendar_refresh_loop_retries_a_failed_initial_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A boot-time calendar failure is retried without restarting the app."""
    import flinttrade_core.app as app_module

    app = _runtime_app()
    calendar_payload = {"holidays": ["2027-01-26"]}
    applied = asyncio.Event()

    async def load_holidays() -> set[str]:
        app.cron.holiday_payload = calendar_payload
        return {"2027-01-26"}

    def apply_holidays(payload: object) -> None:
        assert payload == calendar_payload
        applied.set()

    app.cron.load_holidays = load_holidays
    app.time_scheduler.set_holidays.side_effect = apply_holidays
    monkeypatch.setattr(
        app_module,
        "_market_calendar_refresh_delay",
        lambda **_kwargs: 0.001,
    )

    refresh_task = asyncio.create_task(
        app._market_calendar_refresh_loop(loaded=False)
    )
    await asyncio.wait_for(applied.wait(), timeout=1.0)
    app._stop_event.set()
    await asyncio.wait_for(refresh_task, timeout=1.0)

    app.time_scheduler.set_holidays.assert_called()


@pytest.mark.asyncio
async def test_failed_shutdown_wakes_start_wait_without_claiming_completion() -> None:
    runtime = _runtime_app()
    runtime._stop_started = True

    async def fail_shutdown() -> None:
        raise RuntimeError("shutdown encountered errors: active requests")

    runtime._shutdown_task = asyncio.create_task(fail_shutdown())
    await asyncio.sleep(0)
    runtime._shutdown_failed_event.set()

    with pytest.raises(RuntimeError, match="active requests"):
        await runtime._wait_for_shutdown_if_started()

    assert runtime._stop_event.is_set() is False


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
    calendar_payload = {
        "data": {
            "holidays": [
                {
                    "date": "2026-08-15",
                    "holiday_type": "SPECIAL_SESSION",
                    "closed_exchanges": ["NSE"],
                    "open_exchanges": [
                        {
                            "exchange": "NSE",
                            "start_time": "18:00:00",
                            "end_time": "19:00:00",
                        }
                    ],
                }
            ]
        }
    }
    app.cron.load_holidays = AsyncMock(return_value=holidays)
    app.cron.holiday_payload = calendar_payload
    flask_app = Flask("holiday-runtime-wiring")

    def apply_holidays(values: object) -> None:
        try:
            assert values == calendar_payload
        finally:
            app._stop_started = True
            app._stop_event.set()

    app.time_scheduler.set_holidays = MagicMock(side_effect=apply_holidays)
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(app_module, "create_flask_app", lambda **_kwargs: flask_app)
    monkeypatch.setattr(app_module, "_run_flask_server", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_module, "_tick_capture_enabled", lambda: False)

    await app.start()

    app.time_scheduler.set_holidays.assert_called_once_with(calendar_payload)
