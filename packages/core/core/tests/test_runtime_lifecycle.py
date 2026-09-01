"""Regression coverage for process-wide startup and shutdown ownership."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
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
    app.safety_config_ready = True
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
    app._orderflow_checkpoint_owner = None
    app._tick_storage_close_worker = None
    app._flask_app = None
    app._flask_server_owner = None
    app._reconciliation_runner = None
    app._reconciliation_task = None
    app._stop_started = False
    app._stop_completed = False
    app._shutdown_task = None
    app._shutdown_request_task = None
    app._holiday_refresh_task = None
    app._start_claimed = False
    app._start_claim_lock = threading.Lock()
    app._calendar_loaded = False
    app._calendar_runtime_ready = False
    app._calendar_schedulers_started = False
    app._strategy_cron_started = False
    app._cron_jobs_registered = False
    app._cron_started = False
    app._stop_event = asyncio.Event()
    app._shutdown_failed_event = asyncio.Event()
    app._startup_recovery_pending = False
    app._startup_owner_ledger = None
    app._startup_rollback_in_progress = False
    app._active_shutdown_deadline = None
    app._shutdown_sync_workers = {}
    app._shutdown_async_tasks = {}
    app._recovery_loop = None
    app._retained_backend_lease = None
    return app


def _set_calendar_load(
    app: object,
    *,
    payload: object,
    year: int,
) -> None:
    """Configure a CronManager-shaped authoritative calendar refresh double."""
    app.cron.holiday_payload = payload
    app.cron.holiday_year = year
    app.cron.holiday_generation = 0

    async def load_holidays() -> set[str]:
        app.cron.holiday_generation += 1
        return set()

    app.cron.load_holidays = load_holidays


def test_owned_schedulers_start_under_a_fail_closed_calendar() -> None:
    """Calendar-independent jobs and Practice scheduling must survive OpenAlgo outage."""
    app = _runtime_app()
    app._calendar_loaded = False

    app._start_calendar_schedulers()

    app.strategy_cron_scheduler.start.assert_called_once_with()
    app.cron.register_builtin_jobs.assert_called_once_with()
    app.cron.start.assert_called_once_with()
    assert app._calendar_schedulers_started is True


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


def test_runtime_admission_closure_does_not_wait_for_generation_lease() -> None:
    from flinttrade_core.app import _close_runtime_request_admission

    app = Flask("request-admission-generation-contention")
    tracker = MagicMock()
    rebuild_lock = threading.RLock()
    holder_ready = threading.Event()
    release_holder = threading.Event()
    app.config.update(
        RUNTIME_ACCEPTING_REQUESTS=True,
        RUNTIME_REQUEST_TRACKER=tracker,
        BROKER_ROUTER_REBUILD_LOCK=rebuild_lock,
    )

    def hold_generation() -> None:
        with rebuild_lock:
            holder_ready.set()
            release_holder.wait(timeout=2.0)

    holder = threading.Thread(target=hold_generation, daemon=True)
    holder.start()
    assert holder_ready.wait(timeout=1.0)
    try:
        started = time.monotonic()
        assert _close_runtime_request_admission(app) is tracker
        elapsed = time.monotonic() - started
    finally:
        release_holder.set()
        holder.join(timeout=1.0)

    # Non-blocking is the contract: the holder keeps the rebuild lock for
    # 2.0s, so any wait on it dwarfs this bound. Kept well above scheduler
    # noise — a 0.1s bound flaked on loaded CI runners.
    assert elapsed < 0.5
    tracker.stop_admitting.assert_called_once_with()
    assert app.config["RUNTIME_ACCEPTING_REQUESTS"] is False


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
    runtime.scheduler.stop_all.assert_awaited_once_with()
    rejected = flask_app.test_client().get("/blocking")
    assert rejected.status_code == 503

    release_request.set()
    await asyncio.wait_for(stop_task, timeout=1.0)
    request_thread.join(timeout=1.0)

    assert response_status == [200]
    assert runtime.scheduler.stop_all.await_count == 2
    runtime.client.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_shutdown_closes_rag_vector_store() -> None:
    """Persistent RAG WAL state is checkpointed before process shutdown completes."""
    runtime = _runtime_app()
    runtime.rag = MagicMock()

    await runtime.stop()

    runtime.rag.close.assert_called_once_with()
    runtime.client.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_shutdown_joins_rag_indexer_before_closing_store() -> None:
    """The auto-index daemon must finish before the vector store handle is closed."""
    runtime = _runtime_app()
    started = threading.Event()
    release = threading.Event()
    close_while_alive: list[bool] = []

    def indexer_body() -> None:
        started.set()
        release.wait(timeout=2.0)

    indexer = threading.Thread(target=indexer_body, name="rag-indexer", daemon=True)
    rag = MagicMock()
    rag._indexer_thread = indexer

    def close_store() -> None:
        close_while_alive.append(indexer.is_alive())

    rag.close.side_effect = close_store
    runtime.rag = rag
    indexer.start()
    assert started.wait(timeout=1.0)

    async def finish_indexer() -> None:
        await asyncio.sleep(0.05)
        assert rag.close.call_count == 0
        release.set()

    await asyncio.gather(runtime.stop(), finish_indexer())

    assert close_while_alive == [False]
    rag.close.assert_called_once_with()
    runtime.client.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_shutdown_stops_uploaded_strategies_before_each_router_retirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Existing and late-admitted children must stop before router retirement."""
    import importlib

    import flinttrade_engine.strategy_routes as strategy_routes

    app_module = importlib.import_module("flinttrade_core.app")
    runtime = _runtime_app()
    flask_app = Flask("uploaded-strategy-shutdown")
    events: list[str] = []
    tracker = MagicMock()

    def requests_drained(_timeout: float) -> bool:
        assert events == [
            "cron-stopped",
            "uploaded-stopped",
            "registered-stopped",
            "router-retired",
        ]
        events.append("requests-drained")
        return True

    tracker.wait_for_idle.side_effect = requests_drained
    flask_app.config["RUNTIME_REQUEST_TRACKER"] = tracker
    runtime._flask_app = flask_app

    def stop_uploaded(app: Flask) -> list[str]:
        assert app is flask_app
        events.append("uploaded-stopped")
        return ["strategy-1"]

    def retire_router(app: Flask, *, timeout: float) -> bool:
        assert app is flask_app
        assert 0.0 <= timeout <= 10.0
        assert events[-1] == "registered-stopped"
        events.append("router-retired")
        return True

    async def stop_registered() -> None:
        assert events[-1] == "uploaded-stopped"
        events.append("registered-stopped")

    monkeypatch.setattr(strategy_routes, "shutdown_strategy_runtime", stop_uploaded)
    monkeypatch.setattr(app_module, "retire_broker_router_generation", retire_router)
    runtime.strategy_cron_scheduler.stop.side_effect = lambda: events.append("cron-stopped")
    runtime.scheduler.stop_all.side_effect = stop_registered

    await runtime.stop()

    assert events == [
        "cron-stopped",
        "uploaded-stopped",
        "registered-stopped",
        "router-retired",
        "requests-drained",
        "uploaded-stopped",
        "registered-stopped",
        "router-retired",
    ]


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

    runtime.scheduler.stop_all.assert_awaited_once_with()
    runtime.client.close.assert_not_awaited()
    assert runtime._stop_event.is_set() is False
    release_request.set()
    request_thread.join(timeout=1.0)

    await runtime.stop()
    assert runtime.scheduler.stop_all.await_count == 3
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
async def test_shutdown_wakes_sse_streams_before_waiting_on_flask_listener() -> None:
    """Waitress workers must see stream shutdown before their owner joins them."""
    runtime = _runtime_app()
    flask_app = Flask("shutdown-stream-listener-order")
    log_shutdown = threading.Event()
    signal_shutdown = threading.Event()
    flask_app.config.update(
        LOG_STREAM_SHUTDOWN_EVENT=log_shutdown,
        SIGNAL_STREAM_SHUTDOWN_EVENT=signal_shutdown,
    )
    runtime._flask_app = flask_app
    listener = MagicMock()

    def stop_listener(*, timeout: float) -> bool:
        assert timeout >= 0.0
        assert log_shutdown.is_set()
        assert signal_shutdown.is_set()
        return True

    listener.stop.side_effect = stop_listener
    runtime._flask_server_owner = listener

    await runtime.stop()

    listener.stop.assert_called_once()


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
async def test_shutdown_quiesces_smart_jobs_before_router_retirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.smart_order_routes as smart_routes

    runtime = _runtime_app()
    flask_app = Flask("shutdown-smart-order-owner")
    events: list[str] = []
    router = MagicMock()

    def stop_smart_jobs(*, timeout: float) -> bool:
        assert timeout == 30.0
        events.append("smart-jobs")
        return True

    def retire_router(*, timeout: float) -> bool:
        assert timeout == 10.0
        assert events == ["smart-jobs"]
        return True

    router.revoke_and_drain.side_effect = retire_router
    flask_app.config["BROKER_ROUTER"] = router
    runtime._flask_app = flask_app
    monkeypatch.setattr(smart_routes, "shutdown_smart_order_jobs", stop_smart_jobs)

    await runtime.stop()

    assert events == ["smart-jobs"]
    router.revoke_and_drain.assert_called_once_with(timeout=10.0)


@pytest.mark.asyncio
async def test_shutdown_quiesces_ditto_before_router_retirement() -> None:
    runtime = _runtime_app()
    flask_app = Flask("shutdown-ditto-owner")
    events: list[str] = []
    router = MagicMock()

    class DittoRuntime:
        def shutdown(self, *, timeout: float) -> bool:
            assert timeout == 5.0
            events.append("ditto")
            return True

    def retire_router(*, timeout: float) -> bool:
        assert timeout == 10.0
        assert events == ["ditto"]
        events.append("router")
        return True

    router.revoke_and_drain.side_effect = retire_router
    flask_app.config.update(
        BROKER_ROUTER=router,
        DITTO_RUNTIME=DittoRuntime(),
    )
    runtime._flask_app = flask_app

    await runtime.stop()

    assert events == ["ditto", "router", "ditto"]
    router.revoke_and_drain.assert_called_once_with(timeout=10.0)


@pytest.mark.asyncio
async def test_shutdown_retains_router_when_ditto_cannot_drain() -> None:
    runtime = _runtime_app()
    flask_app = Flask("shutdown-ditto-timeout")
    router = MagicMock()
    ditto = MagicMock()
    ditto.shutdown.return_value = False
    flask_app.config.update(BROKER_ROUTER=router, DITTO_RUNTIME=ditto)
    runtime._flask_app = flask_app

    with pytest.raises(RuntimeError, match="ditto runtime"):
        await runtime.stop()

    router.revoke_and_drain.assert_not_called()
    assert flask_app.config["BROKER_ROUTER"] is router


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
async def test_shutdown_drains_rotation_before_revoking_router() -> None:
    """A blocked refresh must drain before its router dependencies are retired."""
    runtime = _runtime_app()
    flask_app = Flask("shutdown-router-before-rotation")
    router = MagicMock()
    router.revoke_and_drain.return_value = True
    rotation = MagicMock(running=True)

    def stop_rotation(*, wait: bool) -> None:
        assert wait is False
        assert flask_app.config["BROKER_ROUTER"] is router

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
async def test_rotation_drain_timeout_retains_router_and_retries_truthfully() -> None:
    from flinttrade_core.native_rotation import NativeRotationAdmission

    runtime = _runtime_app()
    flask_app = Flask("shutdown-rotation-drain-timeout")
    router = MagicMock()
    router.revoke_and_drain.return_value = True
    rotation = MagicMock(running=True)
    rotation.shutdown.side_effect = lambda **_kwargs: setattr(rotation, "running", False)
    admission = NativeRotationAdmission()
    generation = admission.acquire()
    flask_app.config.update(
        BROKER_ROUTER=router,
        ROTATION_SCHEDULER=rotation,
        NATIVE_ROTATION_ADMISSION=admission,
        NATIVE_ROTATION_SHUTDOWN_TIMEOUT_SECONDS=0.01,
    )
    runtime._flask_app = flask_app

    with pytest.raises(RuntimeError, match="native session rotation scheduler"):
        await runtime.stop()

    router.revoke_and_drain.assert_not_called()
    assert flask_app.config["BROKER_ROUTER"] is router
    runtime.client.close.assert_not_awaited()
    assert runtime._stop_event.is_set() is False

    admission.release(generation)
    await runtime.stop()

    router.revoke_and_drain.assert_called_once_with(timeout=10.0)
    runtime.client.close.assert_awaited_once_with()
    assert runtime._stop_event.is_set() is True


@pytest.mark.asyncio
async def test_agent_shutdown_failure_preserves_dependencies_for_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.agent_routes as agent_routes

    runtime = _runtime_app()
    flask_app = Flask("agent-shutdown-failure")
    tracker = MagicMock()
    router = MagicMock()
    flask_app.config.update(
        RUNTIME_REQUEST_TRACKER=tracker,
        BROKER_ROUTER=router,
    )
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
    router.revoke_and_drain.assert_not_called()
    assert flask_app.config["BROKER_ROUTER"] is router
    runtime.client.close.assert_not_awaited()
    assert runtime._stop_event.is_set() is False


@pytest.mark.asyncio
async def test_concurrent_start_is_rejected_before_a_second_flask_generation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import flinttrade_core.app as app_module

    runtime = _runtime_app()
    holiday_started = asyncio.Event()
    release_holiday = asyncio.Event()
    factory_calls = 0

    async def load_holidays() -> set[str]:
        holiday_started.set()
        await release_holiday.wait()
        runtime.cron.holiday_payload = []
        runtime.cron.holiday_year = 2026
        runtime.cron.holiday_generation += 1
        return set()

    def create_app(**_kwargs: object) -> Flask:
        nonlocal factory_calls
        factory_calls += 1
        return Flask(f"start-generation-{factory_calls}")

    runtime.cron.holiday_generation = 0
    runtime.cron.holiday_year = None
    runtime.cron.load_holidays = load_holidays
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(app_module, "create_flask_app", create_app)
    monkeypatch.setattr(app_module, "_run_flask_server", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_module, "_tick_capture_enabled", lambda: False)
    monkeypatch.setattr(app_module, "_current_market_calendar_year", lambda: 2026)

    first = asyncio.create_task(runtime.start())
    await asyncio.wait_for(holiday_started.wait(), timeout=1.0)
    second = asyncio.create_task(runtime.start())
    try:
        done, _ = await asyncio.wait({second}, timeout=0.05)
        assert second in done, "a concurrent start waited instead of being rejected"
        with pytest.raises(RuntimeError, match="already started"):
            await second
        assert factory_calls == 1
    finally:
        if not second.done():
            second.cancel()
            await asyncio.gather(second, return_exceptions=True)
        await runtime.stop()
        release_holiday.set()
        await asyncio.wait_for(first, timeout=1.0)


@pytest.mark.asyncio
async def test_a_rejected_duplicate_start_never_rolls_back_the_running_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A duplicate start acquired nothing, so it must not tear the live runtime down.

    The rejected caller used to install its own empty owner ledger before the
    claim was tested, then run the startup-rollback path on the way out — which
    released the winning start's owners, closed the live OpenAlgo client and
    audit logger, and latched ``_stop_completed`` so the operator's later stop
    became a no-op. A duplicate start request must be inert.
    """
    import flinttrade_core.app as app_module

    runtime = _runtime_app()
    holiday_started = asyncio.Event()
    release_holiday = asyncio.Event()

    async def load_holidays() -> set[str]:
        holiday_started.set()
        await release_holiday.wait()
        return set()

    runtime.cron.load_holidays = load_holidays
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(app_module, "create_flask_app", lambda **_kwargs: Flask("duplicate-start"))
    monkeypatch.setattr(app_module, "_run_flask_server", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_module, "_tick_capture_enabled", lambda: False)

    first = asyncio.create_task(runtime.start())
    await asyncio.wait_for(holiday_started.wait(), timeout=1.0)
    winning_ledger = runtime._startup_owner_ledger
    assert winning_ledger is not None, "the winning start must have retained an owner ledger"

    try:
        with pytest.raises(RuntimeError, match="already started"):
            await runtime.start()

        assert runtime._startup_owner_ledger is winning_ledger, "the rejected start replaced the live ledger"
        assert runtime._startup_recovery_pending is False
        assert runtime._stop_completed is False, "a rejected start marked the live runtime stopped"
        assert runtime._stop_event.is_set() is False, "a rejected start signalled shutdown to the live start"
        runtime.client.close.assert_not_awaited()
        runtime.audit.close.assert_not_called()
    finally:
        await runtime.stop()
        release_holiday.set()
        await asyncio.wait_for(first, timeout=5.0)


@pytest.mark.asyncio
async def test_failed_tick_finalisation_retries_retained_buffer_before_closing() -> None:
    runtime = _runtime_app()
    events: list[str] = []

    class Recorder:
        pending_tick_count = 1

        def stop(self) -> None:
            events.append("stop")

        def flush_pending(self) -> None:
            events.append("flush")
            self.pending_tick_count = 0

        @staticmethod
        def sanitise_error(exc: BaseException) -> str:
            return type(exc).__name__

    class Storage:
        def close(self) -> None:
            events.append("close")

    runtime._tick_recorder = Recorder()
    runtime._tick_storage = Storage()
    runtime._tick_storage_lock = threading.Lock()

    async def failed_finalisation() -> None:
        raise RuntimeError("final flush failed")

    runtime._tick_recorder_task = asyncio.create_task(failed_finalisation())
    await asyncio.sleep(0)

    await runtime.stop()

    assert events == ["stop", "flush", "close"]
    assert runtime._tick_recorder is None
    assert runtime._tick_storage is None
    runtime.client.close.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_tick_storage_finalisation_does_not_use_the_default_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    runtime = _runtime_app()
    storage_closed = threading.Event()
    runtime._tick_recorder = MagicMock(pending_tick_count=0)
    runtime._tick_storage = MagicMock()
    runtime._tick_storage.close.side_effect = storage_closed.set
    runtime._tick_storage_lock = threading.Lock()

    async def reject_default_executor(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("tick finalisation used asyncio's default executor")

    monkeypatch.setattr(app_module.asyncio, "to_thread", reject_default_executor)

    await runtime.stop()

    assert storage_closed.is_set()
    assert runtime._tick_storage is None
    assert runtime._shutdown_sync_workers == {}


@pytest.mark.asyncio
async def test_start_injects_and_starts_shared_strategy_cron_scheduler(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Strategy schedules use the same live calendar owner as the app runtime."""
    import flinttrade_core.app as app_module

    app = _runtime_app()
    _set_calendar_load(app, payload=[], year=2026)
    flask_app = Flask("shared-strategy-cron")
    captured_factory_args: dict[str, object] = {}

    def create_app(**kwargs: object) -> Flask:
        captured_factory_args.update(kwargs)
        flask_app.config["CRON_SCHEDULER"] = kwargs["cron_strategy_scheduler"]
        flask_app.config["TIME_SCHEDULER"] = kwargs["time_scheduler"]
        return flask_app

    def start_strategy_cron() -> None:
        assert flask_app.config["CRON_SCHEDULER"] is app.strategy_cron_scheduler

    app.strategy_cron_scheduler.start.side_effect = start_strategy_cron
    app.cron.start.side_effect = app._stop_event.set
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(app_module, "create_flask_app", create_app)
    monkeypatch.setattr(app_module, "_run_flask_server", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_module, "_tick_capture_enabled", lambda: False)
    monkeypatch.setattr(app_module, "_current_market_calendar_year", lambda: 2026)

    await app.start()

    assert captured_factory_args["cron_strategy_scheduler"] is app.strategy_cron_scheduler
    assert captured_factory_args["time_scheduler"] is app.time_scheduler
    assert flask_app.config["TIME_SCHEDULER"] is app.time_scheduler
    app.safety.bind_runtime_loop.assert_called_once_with(asyncio.get_running_loop())
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
    app.cron.holiday_generation = 0
    app.cron.holiday_year = None
    blocked_dates = {"2026-01-01", "2026-12-31"}
    app.cron.fail_closed_calendar_year.return_value = blocked_dates
    flask_app = Flask("failed-calendar-load")

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(app_module, "create_flask_app", lambda **_kwargs: flask_app)
    monkeypatch.setattr(app_module, "_run_flask_server", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_module, "_tick_capture_enabled", lambda: False)
    monkeypatch.setattr(app_module, "_current_market_calendar_year", lambda: 2026)

    start_task = asyncio.create_task(app.start())
    await asyncio.sleep(0.05)

    app.strategy_cron_scheduler.start.assert_called_once_with()
    app.cron.register_builtin_jobs.assert_called_once_with()
    app.cron.start.assert_called_once_with()
    assert app._calendar_loaded is False

    await app.stop()
    await asyncio.wait_for(start_task, timeout=1.0)

    app.cron.fail_closed_calendar_year.assert_called_once_with(2026)
    app.time_scheduler.set_holidays.assert_called_once_with(
        blocked_dates,
        year="2026",
    )


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
        app.cron.holiday_year = 2027
        app.cron.holiday_generation += 1
        return {"2027-01-26"}

    def apply_holidays(payload: object, *, year: str | None = None) -> None:
        assert payload == calendar_payload
        assert year == "2027"
        applied.set()

    app.cron.holiday_generation = 0
    app.cron.holiday_year = None
    app.cron.load_holidays = load_holidays
    app.time_scheduler.set_holidays.side_effect = apply_holidays
    monkeypatch.setattr(
        app_module,
        "_market_calendar_refresh_delay",
        lambda **_kwargs: 0.001,
    )
    monkeypatch.setattr(app_module, "_current_market_calendar_year", lambda: 2027)

    refresh_task = asyncio.create_task(
        app._market_calendar_refresh_loop(loaded=False)
    )
    await asyncio.wait_for(applied.wait(), timeout=1.0)
    app._stop_event.set()
    await asyncio.wait_for(refresh_task, timeout=1.0)

    app.time_scheduler.set_holidays.assert_called()


@pytest.mark.asyncio
async def test_failed_year_rollover_refresh_marks_current_year_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale prior-year payload must never authorise the new trading year."""
    import flinttrade_core.app as app_module

    app = _runtime_app()
    app._calendar_loaded = True
    app.cron.holiday_generation = 4
    app.cron.holiday_year = 2026
    app.cron.holiday_payload = {"status": "success", "year": 2026, "data": []}
    app.cron.load_holidays = AsyncMock(return_value=set())
    blocked_dates = {"2027-01-01", "2027-12-31"}
    app.cron.fail_closed_calendar_year.return_value = blocked_dates
    monkeypatch.setattr(app_module, "_current_market_calendar_year", lambda: 2027)

    loaded = await app._refresh_market_calendar()

    assert loaded is False
    assert app._calendar_loaded is False
    app.cron.fail_closed_calendar_year.assert_called_once_with(2027)
    app.time_scheduler.set_holidays.assert_called_once_with(
        blocked_dates,
        year="2027",
    )


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


@pytest.mark.asyncio
async def test_shutdown_retry_clears_stale_completion_before_waiters_resume() -> None:
    runtime = _runtime_app()
    retry_started = asyncio.Event()
    release_retry = asyncio.Event()
    attempts = 0

    async def stop_once() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            runtime._stop_event.set()
            raise RuntimeError("first shutdown attempt failed after signalling")
        retry_started.set()
        await release_retry.wait()
        runtime._stop_completed = True
        runtime._stop_event.set()

    runtime._stop_once = stop_once
    with pytest.raises(RuntimeError, match="first shutdown attempt"):
        await runtime.stop()
    assert runtime._stop_event.is_set()

    retry = asyncio.create_task(runtime.stop())
    await retry_started.wait()
    waiter = asyncio.create_task(runtime._wait_for_shutdown_result())
    done, _ = await asyncio.wait({waiter}, timeout=0.05)

    assert waiter not in done
    release_retry.set()
    await retry
    await waiter


@pytest.mark.asyncio
async def test_shutdown_waiter_keeps_failed_attempt_when_concurrent_retry_starts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    runtime = _runtime_app()
    waiter_started = asyncio.Event()
    failed_attempt_observed = asyncio.Event()
    release_waiter = asyncio.Event()
    retry_started = asyncio.Event()
    release_retry = asyncio.Event()
    attempts = 0

    async def stop_once() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("first shutdown attempt failed")
        retry_started.set()
        await release_retry.wait()
        runtime._stop_completed = True
        runtime._stop_event.set()

    real_wait = asyncio.wait

    async def pause_failed_waiter(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        waiter_started.set()
        result = await real_wait(*args, **kwargs)
        failed_attempt_observed.set()
        await release_waiter.wait()
        return result

    runtime._stop_once = stop_once
    monkeypatch.setattr(app_module.asyncio, "wait", pause_failed_waiter)
    waiter = asyncio.create_task(runtime._wait_for_shutdown_result())
    await asyncio.wait_for(waiter_started.wait(), timeout=1.0)
    with pytest.raises(RuntimeError, match="first shutdown attempt failed"):
        await runtime.stop()
    await asyncio.wait_for(failed_attempt_observed.wait(), timeout=1.0)
    retry = asyncio.create_task(runtime.stop())
    await asyncio.wait_for(retry_started.wait(), timeout=1.0)
    release_waiter.set()
    try:
        with pytest.raises(RuntimeError, match="first shutdown attempt failed"):
            await asyncio.wait_for(waiter, timeout=1.0)
        assert retry.done() is False
    finally:
        release_retry.set()
        await retry


@pytest.mark.asyncio
async def test_cancelled_stop_caller_cannot_suppress_later_attempt_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    runtime = _runtime_app()
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    waiter_started = asyncio.Event()
    failed_attempt_observed = asyncio.Event()
    release_waiter = asyncio.Event()
    retry_started = asyncio.Event()
    release_retry = asyncio.Event()
    attempts = 0

    async def stop_once() -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            first_started.set()
            await release_first.wait()
            raise RuntimeError("orphaned shutdown attempt failed")
        retry_started.set()
        await release_retry.wait()
        runtime._stop_completed = True
        runtime._stop_event.set()

    real_wait = asyncio.wait

    async def pause_failed_waiter(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        waiter_started.set()
        result = await real_wait(*args, **kwargs)
        failed_attempt_observed.set()
        await release_waiter.wait()
        return result

    runtime._stop_once = stop_once
    monkeypatch.setattr(app_module.asyncio, "wait", pause_failed_waiter)
    cancelled_caller = asyncio.create_task(runtime.stop())
    waiter = None
    retry = None
    failed_attempt = None
    try:
        await asyncio.wait_for(first_started.wait(), timeout=1.0)
        failed_attempt = runtime._shutdown_attempt
        cancelled_caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled_caller

        waiter = asyncio.create_task(runtime._wait_for_shutdown_result())
        await asyncio.wait_for(waiter_started.wait(), timeout=1.0)
        release_first.set()
        await asyncio.wait_for(failed_attempt_observed.wait(), timeout=1.0)

        retry = asyncio.create_task(runtime.stop())
        await asyncio.wait_for(retry_started.wait(), timeout=1.0)
        release_waiter.set()
        with pytest.raises(RuntimeError, match="orphaned shutdown attempt failed"):
            await asyncio.wait_for(waiter, timeout=1.0)
        assert failed_attempt.failed_event.is_set()
        assert retry.done() is False
    finally:
        release_first.set()
        release_waiter.set()
        release_retry.set()
        cleanup = [task for task in (cancelled_caller, waiter, retry) if task is not None]
        if failed_attempt is not None and failed_attempt.task is not None:
            cleanup.append(failed_attempt.task)
        for task in cleanup:
            if not task.done() and task is waiter:
                task.cancel()
        await asyncio.gather(*cleanup, return_exceptions=True)


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
    retrainer = MagicMock()
    retrainer.wait_for_fetch_owner.return_value = True
    flask_app = Flask("retrain-cancellation")
    flask_app.config["ML_SIGNAL_RETRAIN_CANCEL_EVENT"] = cancel_event
    flask_app.config["ML_SIGNAL_RETRAINER"] = retrainer
    app._flask_app = flask_app

    def stop_cron() -> None:
        assert cancel_event.is_set()

    app.cron.stop = MagicMock(side_effect=stop_cron)

    await app.stop()

    retrainer.wait_for_fetch_owner.assert_called_once_with(timeout=30.0)
    app.cron.stop.assert_called_once_with()


@pytest.mark.asyncio
async def test_shutdown_retains_dependencies_while_retraining_fetch_is_alive() -> None:
    app = _runtime_app()
    flask_app = Flask("retrain-owner-timeout")
    retrainer = MagicMock()
    retrainer.wait_for_fetch_owner.return_value = False
    flask_app.config.update(
        ML_SIGNAL_RETRAIN_CANCEL_EVENT=threading.Event(),
        ML_SIGNAL_RETRAINER=retrainer,
        ML_SIGNAL_RETRAIN_SHUTDOWN_TIMEOUT_SECONDS=0.01,
    )
    app._flask_app = flask_app

    with pytest.raises(RuntimeError, match="signal retraining fetch owner"):
        await app.stop()

    retrainer.wait_for_fetch_owner.assert_called_once_with(timeout=0.01)
    app.client.close.assert_not_awaited()
    app.audit.close.assert_not_called()


@pytest.mark.asyncio
async def test_shutdown_stops_managed_local_ai_before_another_quiesce_owner_can_consume_its_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.local_ai_routes as local_ai_routes

    app = _runtime_app()
    flask_app = Flask("local-ai-shutdown-after-failure")
    app._flask_app = flask_app
    calls: list[tuple[Flask, float]] = []
    events: list[str] = []

    def shutdown_local_ai(runtime_app: Flask, *, timeout: float) -> bool:
        events.append("local-ai")
        calls.append((runtime_app, timeout))
        return True

    def fail_quiesce() -> None:
        events.append("strategy-cron")
        raise RuntimeError("injected cron stop failure")

    monkeypatch.setattr(local_ai_routes, "shutdown_local_ai_runtime", shutdown_local_ai)
    app.strategy_cron_scheduler.stop.side_effect = fail_quiesce

    with pytest.raises(RuntimeError, match="strategy cron scheduler"):
        await app.stop()

    assert len(calls) == 1
    assert calls[0][0] is flask_app
    assert 0.0 < calls[0][1] <= 5.0
    assert events == ["local-ai", "strategy-cron"]
    app.client.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_applies_cron_holidays_to_time_scheduler(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The market-hours owner receives the calendar fetched at startup."""
    import flinttrade_core.app as app_module

    app = _runtime_app()
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
    _set_calendar_load(app, payload=calendar_payload, year=2026)
    flask_app = Flask("holiday-runtime-wiring")

    def apply_holidays(values: object, *, year: str | None = None) -> None:
        try:
            assert values == calendar_payload
            assert year == "2026"
        finally:
            app._stop_started = True
            app._stop_event.set()

    app.time_scheduler.set_holidays = MagicMock(side_effect=apply_holidays)
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(app_module, "create_flask_app", lambda **_kwargs: flask_app)
    monkeypatch.setattr(app_module, "_run_flask_server", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_module, "_tick_capture_enabled", lambda: False)
    monkeypatch.setattr(app_module, "_current_market_calendar_year", lambda: 2026)

    await app.start()

    app.time_scheduler.set_holidays.assert_called_once_with(
        calendar_payload,
        year="2026",
    )


@pytest.mark.asyncio
async def test_admission_close_failure_is_fail_closed_retriable_and_quiesces_independent_owners() -> None:
    runtime = _runtime_app()
    flask_app = Flask("full-app-admission-close-failure")
    tracker = MagicMock()
    tracker.stop_admitting.side_effect = [
        RuntimeError("tracker close failed"),
        None,
    ]
    tracker.wait_for_idle.return_value = True
    flask_app.config.update(
        RUNTIME_ACCEPTING_REQUESTS=True,
        RUNTIME_REQUEST_TRACKER=tracker,
    )
    runtime._flask_app = flask_app
    reconciliation_cancelled = asyncio.Event()

    async def reconciliation() -> None:
        try:
            await asyncio.Future()
        finally:
            reconciliation_cancelled.set()

    reconciliation_runner = MagicMock()
    runtime._reconciliation_runner = reconciliation_runner
    runtime._reconciliation_task = asyncio.create_task(reconciliation())

    with pytest.raises(RuntimeError, match="request admission"):
        await runtime.stop()

    assert flask_app.config["RUNTIME_ACCEPTING_REQUESTS"] is False
    runtime.cron.stop.assert_called_once_with()
    runtime.scheduler.stop_all.assert_awaited_once_with()
    reconciliation_runner.stop.assert_called_once_with()
    assert reconciliation_cancelled.is_set()
    runtime.client.close.assert_not_awaited()
    runtime.audit.close.assert_not_called()

    await runtime.stop()

    assert tracker.stop_admitting.call_count == 2
    runtime.client.close.assert_awaited_once_with()
    runtime.audit.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_reconciliation_stop_failure_retains_runner_task_and_config_for_retry() -> None:
    runtime = _runtime_app()
    flask_app = Flask("reconciliation-stop-failure")
    runner = MagicMock()
    runner.stop.side_effect = RuntimeError("injected reconciliation stop failure")
    task_ready = asyncio.Event()

    async def reconcile() -> None:
        task_ready.set()
        await asyncio.Future()

    task = asyncio.create_task(reconcile())
    await task_ready.wait()
    runtime._flask_app = flask_app
    runtime._reconciliation_runner = runner
    runtime._reconciliation_task = task
    flask_app.config["RECONCILIATION_RUNNER"] = runner

    try:
        with pytest.raises(RuntimeError, match="reconciliation runner"):
            await runtime.stop()

        assert runtime._reconciliation_runner is runner
        assert runtime._reconciliation_task is task
        assert flask_app.config["RECONCILIATION_RUNNER"] is runner
        assert task.done() is False
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_successful_reconciliation_shutdown_clears_runner_task_and_config() -> None:
    runtime = _runtime_app()
    flask_app = Flask("reconciliation-stop-success")
    runner = MagicMock()

    async def reconcile() -> None:
        await asyncio.Future()

    task = asyncio.create_task(reconcile())
    await asyncio.sleep(0)
    runtime._flask_app = flask_app
    runtime._reconciliation_runner = runner
    runtime._reconciliation_task = task
    flask_app.config["RECONCILIATION_RUNNER"] = runner

    await runtime.stop()

    runner.stop.assert_called_once_with()
    assert task.done()
    assert runtime._reconciliation_runner is None
    assert runtime._reconciliation_task is None
    assert "RECONCILIATION_RUNNER" not in flask_app.config


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("owner_kind", "expected_error"),
    [
        ("holiday", "market calendar refresh"),
        ("tick", "tick recorder task"),
        ("reconciliation", "reconciliation task"),
    ],
)
async def test_shutdown_deadline_retains_cancelled_task_until_ordinary_retry(
    owner_kind: str,
    expected_error: str,
) -> None:
    runtime = _runtime_app()
    ready = asyncio.Event()
    cancellation_started = asyncio.Event()
    release_cleanup = asyncio.Event()

    async def retained_cleanup() -> None:
        ready.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancellation_started.set()
            await release_cleanup.wait()
            raise

    owned_task = asyncio.create_task(retained_cleanup())
    await ready.wait()
    storage = None
    if owner_kind == "holiday":
        runtime._holiday_refresh_task = owned_task
    elif owner_kind == "tick":
        storage = MagicMock()
        runtime._tick_recorder = MagicMock(pending_tick_count=0)
        runtime._tick_recorder_task = owned_task
        runtime._tick_storage = storage
        runtime._tick_storage_lock = threading.Lock()
    else:
        runtime._reconciliation_runner = MagicMock()
        runtime._reconciliation_task = owned_task

    stop_task = asyncio.create_task(runtime.stop(timeout=0.02))
    cancellation_waiter = asyncio.create_task(cancellation_started.wait())
    try:
        done, _ = await asyncio.wait(
            {stop_task, cancellation_waiter},
            timeout=1.0,
            return_when=asyncio.FIRST_COMPLETED,
        )
        assert cancellation_waiter in done, "shutdown returned before cancelling its retained task"
        with pytest.raises(RuntimeError, match=expected_error):
            await asyncio.wait_for(stop_task, timeout=1.0)

        if owner_kind == "holiday":
            assert runtime._holiday_refresh_task is owned_task
        elif owner_kind == "tick":
            assert runtime._tick_recorder_task is owned_task
            assert runtime._tick_storage is storage
            storage.close.assert_not_called()
        else:
            assert runtime._reconciliation_task is owned_task
        runtime.client.close.assert_not_awaited()

        release_cleanup.set()
        await asyncio.gather(owned_task, return_exceptions=True)
        await runtime.stop(timeout=1.0)

        if owner_kind == "holiday":
            assert runtime._holiday_refresh_task is None
        elif owner_kind == "tick":
            assert runtime._tick_recorder_task is None
            storage.close.assert_called_once_with()
        else:
            assert runtime._reconciliation_task is None
    finally:
        release_cleanup.set()
        cancellation_waiter.cancel()
        if not owned_task.done():
            owned_task.cancel()
        await asyncio.gather(cancellation_waiter, owned_task, stop_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_full_app_startup_failure_after_smart_admission_rolls_back_owned_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module
    import flinttrade_core.smart_order_routes as smart_order_routes

    runtime = _runtime_app()
    events: list[str] = []

    monkeypatch.setattr(
        smart_order_routes,
        "start_smart_order_jobs",
        lambda: events.append("smart-start") or True,
    )
    monkeypatch.setattr(
        smart_order_routes,
        "shutdown_smart_order_jobs",
        lambda **_kwargs: events.append("smart-stop") or True,
    )
    monkeypatch.setattr(
        app_module,
        "create_flask_app",
        MagicMock(side_effect=RuntimeError("injected after smart-order admission")),
    )

    async def close_client() -> None:
        events.append("client-close")

    runtime.client.close = AsyncMock(side_effect=close_client)
    runtime.audit.close.side_effect = lambda: events.append("audit-close")

    with pytest.raises(RuntimeError, match="injected after smart-order admission"):
        await runtime.start()

    assert events == ["smart-start", "smart-stop", "client-close", "audit-close"]
    assert runtime._startup_recovery_pending is False


@pytest.mark.asyncio
async def test_startup_rollback_stops_local_ai_immediately_after_closing_outer_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.local_ai_routes as local_ai_routes
    from flinttrade_core.app import _AcquiredOwnerLedger, _LifecycleDeadline

    runtime = _runtime_app()
    events: list[str] = []
    flask_app = Flask("startup-rollback-admission-order")
    tracker = MagicMock()
    tracker.stop_admitting.side_effect = lambda: events.append("admission-closed")
    flask_app.config.update(
        RUNTIME_ACCEPTING_REQUESTS=True,
        RUNTIME_REQUEST_TRACKER=tracker,
    )
    runtime._flask_app = flask_app
    runtime._rollback_startup_dependencies = AsyncMock(return_value=True)
    ledger = _AcquiredOwnerLedger()

    def stop_local_ai(runtime_app: Flask, *, timeout: float) -> bool:
        assert runtime_app.config["RUNTIME_ACCEPTING_REQUESTS"] is False
        assert 0.0 <= timeout <= 5.0
        events.append("local-ai-stopped")
        return True

    monkeypatch.setattr(local_ai_routes, "shutdown_local_ai_runtime", stop_local_ai)

    async def rollback_live_owner(_deadline: _LifecycleDeadline) -> bool:
        assert flask_app.config["RUNTIME_ACCEPTING_REQUESTS"] is False
        assert events == ["local-ai-stopped", "admission-closed"]
        events.append("live-owner-stopped")
        return True

    ledger.acquire("live owner", rollback_live_owner)
    runtime._startup_owner_ledger = ledger

    assert await runtime._recover_startup_rollback(_LifecycleDeadline.after(1.0)) is True
    assert events == ["local-ai-stopped", "admission-closed", "live-owner-stopped"]


@pytest.mark.asyncio
async def test_expired_startup_rollback_invokes_local_ai_without_claiming_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.local_ai_routes as local_ai_routes
    from flinttrade_core.app import _AcquiredOwnerLedger, _LifecycleDeadline

    runtime = _runtime_app()
    flask_app = Flask("expired-startup-local-ai")
    flask_app.config["RUNTIME_ACCEPTING_REQUESTS"] = True
    runtime._flask_app = flask_app
    runtime._rollback_startup_dependencies = AsyncMock(return_value=True)
    ledger = _AcquiredOwnerLedger()
    ledger.acquire("managed local AI", AsyncMock(return_value=True))
    runtime._startup_owner_ledger = ledger
    invoked = threading.Event()
    observed_timeouts: list[float] = []

    def stop_local_ai(_app: Flask, *, timeout: float) -> bool:
        observed_timeouts.append(timeout)
        invoked.set()
        return True

    monkeypatch.setattr(local_ai_routes, "shutdown_local_ai_runtime", stop_local_ai)

    complete = await runtime._recover_startup_rollback(
        _LifecycleDeadline(time.monotonic() - 1.0)
    )

    assert complete is False
    assert await asyncio.to_thread(invoked.wait, 1.0)
    assert observed_timeouts == [0.0]
    assert ledger._owners[0].released is False  # noqa: SLF001
    assert runtime._startup_recovery_pending is True


@pytest.mark.asyncio
async def test_sync_root_stop_finishing_at_the_deadline_remains_unproved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module
    from flinttrade_core.app import _LifecycleDeadline

    runtime = _runtime_app()
    clock = [0.0]
    monkeypatch.setattr(app_module.time, "monotonic", lambda: clock[0])

    def finish_at_deadline() -> bool:
        clock[0] = 1.0
        return True

    stopped, error_type = await runtime._run_retained_sync_owner(
        "deadline-root-stop",
        finish_at_deadline,
        _LifecycleDeadline(1.0),
        require_truthy=True,
        require_live_deadline_for_success=True,
    )

    assert stopped is False
    assert error_type == "TimeoutError"


@pytest.mark.asyncio
async def test_full_app_startup_stops_local_ai_before_reverse_rolling_back_other_owners(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import flinttrade_core.app as app_module
    import flinttrade_core.local_ai_routes as local_ai_routes
    import flinttrade_core.smart_order_routes as smart_order_routes
    import flinttrade_data.orderflow_aggregator as orderflow_module
    import flinttrade_data.storage as storage_module
    import flinttrade_engine.reconciliation_runner as reconciliation_module

    runtime = _runtime_app()
    events: list[str] = []
    flask_app = Flask("transactional-full-app-start")
    flask_app.config["RECONCILE_TARGETS"] = object()
    runtime.telegram = MagicMock()
    runtime.telegram.start_background.side_effect = lambda: events.append("telegram-start")
    runtime.telegram.stop.side_effect = lambda: events.append("telegram-stop")
    runtime._refresh_market_calendar = AsyncMock(return_value=True)
    runtime._wait_for_shutdown_result = AsyncMock(
        side_effect=RuntimeError("injected after reconciliation acquisition")
    )

    class Storage:
        def initialise(self) -> None:
            events.append("tick-storage-start")

        def close(self) -> None:
            events.append("tick-storage-close")

    class Recorder:
        pending_tick_count = 0

        async def run(self) -> None:
            await asyncio.Future()

        def stop(self) -> None:
            events.append("tick-stop")

    class CheckpointOwner:
        def persist(self, *, force: bool) -> None:
            assert force is True
            events.append("tick-checkpoint")

        def persist_locked(self) -> None:
            return None

    class ReconciliationRunner:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            return None

        async def run(self) -> None:
            await asyncio.Future()

        def stop(self) -> None:
            events.append("reconciliation-stop")

    recorder = Recorder()
    checkpoint_owner = CheckpointOwner()
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path))
    monkeypatch.setattr(app_module, "create_flask_app", lambda **_kwargs: flask_app)
    monkeypatch.setattr(app_module, "_run_flask_server", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(app_module, "_bind_runtime_emergency_dispatcher", lambda *_args: None)
    monkeypatch.setattr(app_module, "_tick_capture_enabled", lambda: True)
    monkeypatch.setattr(app_module, "_tick_capture_watchlist", lambda: [])
    monkeypatch.setattr(app_module, "_tick_capture_mode", lambda: "quote")
    monkeypatch.setattr(app_module, "_prepare_tick_orderflow_state", lambda *_args, **_kwargs: {
        "pruned_ticks": 0,
        "restored_ticks": 0,
        "restore_failures": 0,
    })
    monkeypatch.setattr(app_module, "_build_tick_recorder", lambda **_kwargs: recorder)
    monkeypatch.setattr(app_module, "_OrderFlowCheckpointOwner", lambda *_args, **_kwargs: checkpoint_owner)
    monkeypatch.setattr(app_module, "_auto_sync_enabled", lambda: False)
    monkeypatch.setattr(app_module, "_wire_ml_signal_runtime", lambda *_args: None)
    monkeypatch.setattr(app_module.Settings, "from_env", staticmethod(lambda: runtime.settings))
    monkeypatch.setattr(storage_module, "StorageManager", lambda _path: Storage())
    monkeypatch.setattr(orderflow_module, "create_live_market_orderflow_aggregator", lambda: object())
    monkeypatch.setattr(reconciliation_module, "ReconciliationRunner", ReconciliationRunner)
    monkeypatch.setattr(
        smart_order_routes,
        "start_smart_order_jobs",
        lambda: events.append("smart-start") or True,
    )
    monkeypatch.setattr(
        smart_order_routes,
        "shutdown_smart_order_jobs",
        lambda **_kwargs: events.append("smart-stop") or True,
    )
    monkeypatch.setattr(
        local_ai_routes,
        "start_configured_local_ai_runtime",
        lambda _app: events.append("local-ai-start") or True,
    )
    monkeypatch.setattr(
        local_ai_routes,
        "shutdown_local_ai_runtime",
        lambda runtime_app, **_kwargs: (
            runtime_app.config["RUNTIME_ACCEPTING_REQUESTS"] is False
            and not events.append("local-ai-stop")
        ),
    )

    async def close_client() -> None:
        events.append("client-close")

    runtime.client.close = AsyncMock(side_effect=close_client)
    runtime.audit.close.side_effect = lambda: events.append("audit-close")

    try:
        with pytest.raises(RuntimeError, match="injected after reconciliation acquisition"):
            await runtime.start()

        assert events.index("local-ai-stop") < events.index("reconciliation-stop")
        rollback_order = [
            events.index("reconciliation-stop"),
            events.index("tick-stop"),
            events.index("telegram-stop"),
            events.index("smart-stop"),
            events.index("client-close"),
            events.index("audit-close"),
        ]
        assert rollback_order == sorted(rollback_order)
        assert events.count("local-ai-stop") == 1
        assert runtime._startup_recovery_pending is False
    finally:
        remaining_tasks = [
            task
            for task in (
                runtime._holiday_refresh_task,
                runtime._tick_recorder_task,
                runtime._reconciliation_task,
            )
            if isinstance(task, asyncio.Task) and not task.done()
        ]
        for task in remaining_tasks:
            task.cancel()
        await asyncio.gather(*remaining_tasks, return_exceptions=True)


def test_run_retains_backend_lease_when_startup_rollback_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    runtime = _runtime_app()
    runtime._startup_recovery_pending = True
    runtime._run_owned = MagicMock(side_effect=RuntimeError("startup rollback incomplete"))
    lease = MagicMock()
    retain = MagicMock()
    monkeypatch.setattr(app_module, "acquire_backend_instance_lease", lambda: lease)
    monkeypatch.setattr(app_module, "retain_backend_instance_lease", retain)

    with pytest.raises(RuntimeError, match="startup rollback incomplete"):
        runtime.run()

    retain.assert_called_once_with(lease)
    lease.release.assert_not_called()


@pytest.mark.asyncio
async def test_shutdown_uses_one_deadline_and_retains_each_blocking_owner_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tiny timeout bounds the attempt without duplicating live cleanup."""
    import flinttrade_core.agent_routes as agent_routes
    import flinttrade_core.local_ai_routes as local_ai_routes
    import flinttrade_core.smart_order_routes as smart_order_routes
    import flinttrade_engine.strategy_routes as strategy_routes

    runtime = _runtime_app()
    flask_app = Flask("absolute-shutdown-deadline")
    release = threading.Event()
    calls: dict[str, int] = {}
    observed_timeouts: dict[str, list[float]] = {}

    def block(name: str, result: object = None) -> object:
        calls[name] = calls.get(name, 0) + 1
        release.wait(timeout=1.0)
        return result

    def block_with_timeout(name: str, *, timeout: float, result: object) -> object:
        observed_timeouts.setdefault(name, []).append(timeout)
        return block(name, result)

    retrainer = MagicMock()
    retrainer.wait_for_fetch_owner.side_effect = lambda *, timeout: block_with_timeout(
        "retrainer",
        timeout=timeout,
        result=True,
    )
    flask_app.config.update(
        ML_SIGNAL_RETRAINER=retrainer,
        ML_SIGNAL_RETRAIN_CANCEL_EVENT=threading.Event(),
        ML_SIGNAL_RETRAIN_SHUTDOWN_TIMEOUT_SECONDS=1.0,
        SMART_ORDER_SHUTDOWN_TIMEOUT_SECONDS=1.0,
        AUTONOMOUS_AGENT_SHUTDOWN_TIMEOUT_SECONDS=1.0,
    )
    runtime._flask_app = flask_app
    runtime._flask_server_owner = MagicMock()
    runtime._flask_server_owner.stop.side_effect = lambda *, timeout: block_with_timeout(
        "listener",
        timeout=timeout,
        result=True,
    )
    runtime.strategy_cron_scheduler.stop.side_effect = lambda: block("strategy-cron")
    runtime.cron.stop.side_effect = lambda: block("cron")
    runtime.telegram = MagicMock()
    runtime.telegram.stop.side_effect = lambda: block("telegram")

    async def stop_scheduler() -> None:
        calls["scheduler"] = calls.get("scheduler", 0) + 1
        await asyncio.to_thread(release.wait, 1.0)

    runtime.scheduler.stop_all = AsyncMock(side_effect=stop_scheduler)
    monkeypatch.setattr(
        strategy_routes,
        "shutdown_strategy_runtime",
        lambda _app: block("uploaded-strategies"),
    )
    monkeypatch.setattr(
        smart_order_routes,
        "shutdown_smart_order_jobs",
        lambda *, timeout: block_with_timeout("smart-orders", timeout=timeout, result=True),
    )
    monkeypatch.setattr(
        agent_routes,
        "shutdown_agent_runtime",
        lambda _app, *, timeout: block_with_timeout("agents", timeout=timeout, result=True),
    )
    monkeypatch.setattr(
        local_ai_routes,
        "shutdown_local_ai_runtime",
        lambda _app, *, timeout: block_with_timeout("local-ai", timeout=timeout, result=True),
    )

    failsafe_release = threading.Timer(0.5, release.set)
    failsafe_release.start()
    try:
        started = time.monotonic()
        with pytest.raises(RuntimeError):
            await runtime.stop(timeout=0.01)
        elapsed = time.monotonic() - started
        # stop() must honour its single 0.01s deadline instead of waiting on
        # the blocked owners (failsafe release fires at 0.5s; each worker
        # blocks up to 1.0s). The per-owner deadline propagation is pinned by
        # the observed_timeouts assertion below; this wall-clock bound only
        # needs to sit clearly below the failsafe while tolerating loaded-CI
        # scheduler noise — a 0.1s bound flaked at 0.17s on shared runners.
        assert elapsed < 0.35

        first_attempt = runtime._shutdown_task
        if first_attempt is not None:
            await asyncio.gather(first_attempt, return_exceptions=True)
        with pytest.raises(RuntimeError):
            await runtime.stop(timeout=0.01)
        second_attempt = runtime._shutdown_task
        if second_attempt is not None:
            await asyncio.gather(second_attempt, return_exceptions=True)
        await asyncio.sleep(0)

        for owner in (
            "listener",
            "strategy-cron",
            "retrainer",
            "cron",
            "telegram",
            "uploaded-strategies",
            "scheduler",
            "smart-orders",
            "agents",
        ):
            assert calls[owner] == 1, owner
        for values in observed_timeouts.values():
            assert all(0.0 <= value <= 0.01 for value in values)
        runtime.client.close.assert_not_awaited()
        runtime.audit.close.assert_not_called()
    finally:
        release.set()
        failsafe_release.cancel()

    await asyncio.sleep(0.05)
    await runtime.stop(timeout=1.0)


def test_flask_server_propagates_waitress_bind_failure_without_starting_a_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import waitress
    import waitress.server

    import flinttrade_core.app as app_module

    bind_error = OSError("injected bind failure")
    legacy_serve = MagicMock(side_effect=AssertionError("legacy waitress.serve must not run"))
    create_server = MagicMock(side_effect=bind_error)
    monkeypatch.setattr(waitress, "serve", legacy_serve)
    monkeypatch.setattr(waitress.server, "create_server", create_server)

    with pytest.raises(OSError, match="injected bind failure"):
        app_module._run_flask_server(Flask("waitress-bind-failure"), port=0)

    legacy_serve.assert_not_called()


def test_flask_server_cleans_waitress_dispatcher_and_channels_when_setup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import waitress.server
    import waitress.task

    import flinttrade_core.app as app_module

    events: list[str] = []

    class Dispatcher:
        def set_thread_count(self, count: int) -> None:
            events.append(f"threads:{count}")

        def shutdown(self, *, timeout: float) -> bool:
            assert 0.0 <= timeout <= 5.0
            events.append("dispatcher-shutdown")
            return True

    class Channel:
        def close(self) -> None:
            events.append("channel-close")

    dispatcher = Dispatcher()

    def fail_after_allocating_resources(
        _app: Flask,
        *,
        map: dict[object, object],
        _dispatcher: object,
        **_kwargs: object,
    ) -> object:
        assert _dispatcher is dispatcher
        map["allocated-channel"] = Channel()
        raise OSError("injected setup failure")

    monkeypatch.setattr(waitress.task, "ThreadedTaskDispatcher", lambda: dispatcher)
    monkeypatch.setattr(waitress.server, "create_server", fail_after_allocating_resources)

    with pytest.raises(OSError, match="injected setup failure"):
        app_module._run_flask_server(Flask("waitress-setup-cleanup"), port=0)

    assert events == ["channel-close", "dispatcher-shutdown"]


def test_flask_server_owner_closes_and_joins_its_non_daemon_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import waitress
    import waitress.server

    import flinttrade_core.app as app_module

    events: list[str] = []
    running = threading.Event()
    closed = threading.Event()

    class FakeServer:
        effective_port = 5100

        def run(self) -> None:
            events.append("run")
            running.set()
            closed.wait(timeout=1.0)
            events.append("joined")

        def close(self) -> None:
            events.append("close")
            closed.set()

    fake_server = FakeServer()
    monkeypatch.setattr(waitress, "serve", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(waitress.server, "create_server", lambda *_args, **_kwargs: fake_server)

    owner = app_module._run_flask_server(Flask("waitress-owner"), port=5100)

    assert running.wait(timeout=1.0)
    assert owner.thread.daemon is False
    assert owner.stop(timeout=1.0) is True
    assert owner.thread.is_alive() is False
    assert events == ["run", "close", "joined"]


def test_flask_server_owner_does_not_claim_stuck_waitress_workers_are_stopped() -> None:
    import flinttrade_core.app as app_module

    class Dispatcher:
        threads = {0}

        def shutdown(self, *, timeout: float) -> bool:
            assert timeout >= 0.0
            return True

    owner = app_module._FlaskServerOwner(
        object(),
        run=lambda: None,
        close=lambda: None,
        dispatcher=Dispatcher(),
    )
    owner.start()

    assert owner.stop(timeout=0.1) is False


def test_wsgi_post_factory_failure_cleans_runtime_before_releasing_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import atexit

    import flinttrade_core.app as app_module
    import flinttrade_core.local_ai_routes as local_ai_routes

    events: list[str] = []
    flask_app = Flask("wsgi-post-factory-failure")
    lease = MagicMock()
    monkeypatch.setattr(app_module, "_APP_CACHE", None)
    monkeypatch.setattr(app_module, "_APP_CACHE_PID", None)
    monkeypatch.setattr(app_module, "_WSGI_BACKEND_LEASE", None)
    monkeypatch.setattr(app_module, "_WSGI_STARTUP_RECOVERY", None, raising=False)
    monkeypatch.setattr(app_module, "acquire_backend_instance_lease", lambda: lease)
    monkeypatch.setattr(app_module, "create_flask_app", lambda: flask_app)
    monkeypatch.setattr(
        local_ai_routes,
        "start_configured_local_ai_runtime",
        lambda _app: events.append("local-ai-start") or True,
    )
    monkeypatch.setattr(
        local_ai_routes,
        "shutdown_local_ai_runtime",
        lambda _app, **_kwargs: events.append("local-ai-stop") or True,
    )
    monkeypatch.setattr(
        app_module,
        "shutdown_ditto_runtime",
        lambda _app, **_kwargs: events.append("ditto-stop") or True,
    )
    monkeypatch.setattr(
        app_module,
        "retain_backend_instance_lease",
        lambda retained: events.append("lease-retained") if retained is lease else None,
    )
    monkeypatch.setattr(
        app_module,
        "release_retained_backend_instance_lease",
        lambda retained: (events.append("lease-released"), retained.release()),
    )
    monkeypatch.setattr(
        atexit,
        "register",
        MagicMock(side_effect=RuntimeError("injected post-factory failure")),
    )

    with pytest.raises(RuntimeError, match="injected post-factory failure"):
        app_module._get_wsgi_app()

    assert app_module._APP_CACHE is None
    assert app_module._WSGI_BACKEND_LEASE is None
    assert app_module._WSGI_STARTUP_RECOVERY is None
    lease.retain_recovery_owner.assert_called_once()
    lease.release.assert_called_once_with()
    assert events == [
        "local-ai-start",
        "lease-retained",
        "local-ai-stop",
        "ditto-stop",
        "lease-released",
    ]


def test_wsgi_post_factory_cleanup_failure_retains_exact_recovery_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import atexit

    import flinttrade_core.app as app_module
    import flinttrade_core.local_ai_routes as local_ai_routes

    events: list[str] = []
    flask_app = Flask("wsgi-post-factory-recovery")
    lease = MagicMock()
    ditto_results = iter((False, True))
    monkeypatch.setattr(app_module, "_APP_CACHE", None)
    monkeypatch.setattr(app_module, "_APP_CACHE_PID", None)
    monkeypatch.setattr(app_module, "_WSGI_BACKEND_LEASE", None)
    monkeypatch.setattr(app_module, "_WSGI_STARTUP_RECOVERY", None, raising=False)
    monkeypatch.setattr(app_module, "acquire_backend_instance_lease", lambda: lease)
    monkeypatch.setattr(app_module, "create_flask_app", lambda: flask_app)
    monkeypatch.setattr(local_ai_routes, "start_configured_local_ai_runtime", lambda _app: True)
    monkeypatch.setattr(
        local_ai_routes,
        "shutdown_local_ai_runtime",
        lambda _app, **_kwargs: events.append("local-ai-stop") or True,
    )
    monkeypatch.setattr(
        app_module,
        "shutdown_ditto_runtime",
        lambda _app, **_kwargs: events.append("ditto-stop") or next(ditto_results),
    )
    retained: list[object] = []
    monkeypatch.setattr(app_module, "retain_backend_instance_lease", retained.append)
    monkeypatch.setattr(
        app_module,
        "release_retained_backend_instance_lease",
        lambda retained_lease: (events.append("lease-released"), retained_lease.release()),
    )
    monkeypatch.setattr(
        atexit,
        "register",
        MagicMock(side_effect=RuntimeError("injected post-factory failure")),
    )

    with pytest.raises(RuntimeError, match="injected post-factory failure"):
        app_module._get_wsgi_app()

    recovery = app_module._WSGI_STARTUP_RECOVERY
    assert recovery is not None
    assert retained == [lease]
    lease.retain_recovery_owner.assert_called_once_with(recovery)
    lease.release.assert_not_called()
    assert events == ["local-ai-stop", "ditto-stop"]

    recovery.retry_recovery()

    assert app_module._WSGI_STARTUP_RECOVERY is None
    lease.release.assert_called_once_with()
    assert events == [
        "local-ai-stop",
        "ditto-stop",
        "local-ai-stop",
        "ditto-stop",
        "lease-released",
    ]


def test_run_retains_exact_live_loop_and_recovery_owner_until_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_core.app as app_module

    runtime = app_module.FlintTradeApp.__new__(app_module.FlintTradeApp)
    runtime._shutdown_task = None
    runtime._shutdown_request_task = None
    runtime._flask_app = None
    runtime._stop_completed = False
    runtime._startup_recovery_pending = False
    runtime._recovery_loop = None
    runtime._retained_backend_lease = None
    task_holder: dict[str, asyncio.Task[None]] = {}
    release_holder: dict[str, asyncio.Event] = {}

    async def fail_with_live_owner(_self: object) -> None:
        release = asyncio.Event()

        async def retained_owner() -> None:
            await release.wait()

        release_holder["event"] = release
        task_holder["task"] = asyncio.create_task(retained_owner())
        runtime._startup_recovery_pending = True
        raise RuntimeError("startup rollback incomplete")

    async def recover_owner(_self: object, *, timeout: float | None = None) -> None:
        assert timeout == 1.0
        release_holder["event"].set()
        await task_holder["task"]
        runtime._startup_recovery_pending = False
        runtime._stop_completed = True

    runtime.start = MethodType(fail_with_live_owner, runtime)
    runtime.stop = MethodType(recover_owner, runtime)
    lease = MagicMock()
    retained: list[object] = []
    monkeypatch.setattr(app_module, "acquire_backend_instance_lease", lambda: lease)
    monkeypatch.setattr(app_module, "retain_backend_instance_lease", retained.append)

    try:
        with pytest.raises(RuntimeError, match="startup rollback incomplete"):
            runtime.run()

        task = task_holder["task"]
        owner_loop = task.get_loop()
        assert runtime._recovery_loop is owner_loop
        assert owner_loop.is_closed() is False
        assert retained == [lease]
        lease.retain_recovery_owner.assert_called_once_with(runtime)

        runtime.retry_recovery(timeout=1.0)

        assert task.done()
        assert owner_loop.is_closed()
        lease.release.assert_called_once_with()
    finally:
        task = task_holder.get("task")
        if task is not None and not task.done():
            owner_loop = task.get_loop()
            if owner_loop.is_closed():
                task._log_destroy_pending = False  # type: ignore[attr-defined]  # noqa: SLF001
            else:
                release_holder["event"].set()
                owner_loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
                owner_loop.close()
        asyncio.set_event_loop(None)


@pytest.mark.asyncio
async def test_partial_calendar_start_ledgers_each_scheduler_for_reverse_rollback() -> None:
    from flinttrade_core.app import _AcquiredOwnerLedger, _LifecycleDeadline

    runtime = _runtime_app()
    ledger = _AcquiredOwnerLedger()
    events: list[str] = []
    runtime.strategy_cron_scheduler.start.side_effect = lambda: events.append("strategy-start")
    runtime.strategy_cron_scheduler.stop.side_effect = lambda: events.append("strategy-stop")
    runtime.cron.register_builtin_jobs.side_effect = lambda: events.append("cron-register")

    def fail_after_cron_start() -> None:
        events.append("cron-start")
        raise RuntimeError("partially started cron")

    runtime.cron.start.side_effect = fail_after_cron_start
    runtime.cron.stop.side_effect = lambda: events.append("cron-stop")

    with pytest.raises(RuntimeError, match="partially started cron"):
        runtime._start_calendar_schedulers(ledger)

    assert ledger.has_unreleased is True
    assert await ledger.rollback(_LifecycleDeadline.after(1.0)) is True
    assert events == [
        "strategy-start",
        "cron-register",
        "cron-start",
        "cron-stop",
        "strategy-stop",
    ]


@pytest.mark.asyncio
async def test_startup_rollback_stops_at_first_incomplete_reverse_owner() -> None:
    from flinttrade_core.app import _AcquiredOwnerLedger, _LifecycleDeadline

    ledger = _AcquiredOwnerLedger()
    release_latest = asyncio.Event()
    events: list[str] = []

    async def rollback_oldest(_deadline: _LifecycleDeadline) -> bool:
        events.append("oldest")
        return True

    async def rollback_middle(_deadline: _LifecycleDeadline) -> bool:
        events.append("middle")
        return True

    async def rollback_latest(_deadline: _LifecycleDeadline) -> bool:
        events.append("latest-start")
        await release_latest.wait()
        events.append("latest-end")
        return True

    ledger.acquire("oldest", rollback_oldest)
    ledger.acquire("middle", rollback_middle)
    ledger.acquire("latest", rollback_latest)

    try:
        assert await ledger.rollback(_LifecycleDeadline.after(0.01)) is False
        assert events == ["latest-start"]

        assert await ledger.rollback(_LifecycleDeadline.after(0.01)) is False
        assert events == ["latest-start"]

        release_latest.set()
        assert await ledger.rollback(_LifecycleDeadline.after(1.0)) is True
        assert events == ["latest-start", "latest-end", "middle", "oldest"]
    finally:
        release_latest.set()
        pending = [owner.task for owner in ledger._owners if owner.task is not None]  # noqa: SLF001
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_startup_external_failure_logs_class_without_raw_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime = _runtime_app()
    secret = "raw-openalgo-exception-secret"
    runtime.cron.holiday_generation = 0
    runtime.cron.holiday_year = None
    runtime.cron.load_holidays = AsyncMock(side_effect=RuntimeError(secret))
    caplog.set_level(logging.WARNING, logger="flinttrade")

    assert await runtime._refresh_market_calendar() is False

    assert secret not in caplog.text
    assert "RuntimeError" in caplog.text
