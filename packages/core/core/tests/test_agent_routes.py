"""Tests for the autonomous-agent control plane (/api/v1/ai/agent/*).

The critical property: the route is the ONLY place an order executor is
wired into the AutonomousTrader, and it wires a GatedChildExecutor bound to
an AGENT principal — so agent orders cannot exist outside the gated path,
and cannot pass the router ACL unless the operator explicitly granted the
agent actor id in workspace.json.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time as wall_time
import threading
import time
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import Flask

import flinttrade_core.agent_routes as mod
import flinttrade_core.order_routes as order_routes_mod
from flinttrade_core.smart_order_routes import GatedChildExecutor
from flinttrade_engine.safety import SafetyConfig, SafetySystem, set_safety_gate_secret

pytestmark = pytest.mark.unit

SECRET = b"0123456789abcdef0123456789abcdef"
_ORIGINAL_BUILD_VAULT = mod._build_vault  # noqa: SLF001


class _FakeTrader:
    """Stands in for AutonomousTrader: records ctor kwargs, runs briefly."""

    instances: list["_FakeTrader"] = []

    def __init__(self, **kwargs: Any) -> None:
        from flinttrade_ai.autonomous_agent import AgentState, AgentStatus

        self.kwargs = kwargs
        self.state = AgentState()
        self.status = AgentStatus.RUNNING
        self.stop_calls: list[bool] = []
        self._running = True
        _FakeTrader.instances.append(self)

    def request_stop(self, square_off: bool = True) -> None:
        self.stop_calls.append(square_off)
        self._running = False

    @property
    def shutdown_complete(self) -> bool:
        return not self._running

    @property
    def stop_failure(self) -> str:
        return ""

    async def run_session(self) -> None:
        import asyncio

        while self._running:
            await asyncio.sleep(0.02)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    set_safety_gate_secret(SECRET)
    mod._reset_runner_for_tests()  # noqa: SLF001
    _FakeTrader.instances = []
    monkeypatch.setattr(mod, "_agent_flag_enabled", lambda: True)
    monkeypatch.setattr(mod, "_acl_grants_agent", lambda a, b: True)
    monkeypatch.setattr(mod, "_build_llm", lambda: object())
    monkeypatch.setattr(mod, "_build_vault", lambda: None)
    monkeypatch.setattr(mod, "_trader_factory", _FakeTrader)
    yield
    # Stop any session the test left running so threads do not leak.
    for trader in _FakeTrader.instances:
        trader._running = False  # noqa: SLF001
    with mod._RUNNER_LOCK:  # noqa: SLF001
        thread = mod._RUNNER.get("thread")  # noqa: SLF001
    if thread is not None and thread.is_alive():
        thread.join(timeout=2.0)
    mod._reset_runner_for_tests()  # noqa: SLF001


@pytest.fixture()
def live_auth(monkeypatch):
    monkeypatch.setattr(
        order_routes_mod,
        "_decode_request_payload",
        lambda: {"mode": "live", "sub": "user-1", "jti": "jti-1"},
    )
    monkeypatch.setattr(order_routes_mod, "_is_live_mode_unlocked", lambda: True)


def _make_app(broker_router: object | None = None) -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["BROKER_ROUTER"] = broker_router if broker_router is not None else object()
    app.config["OPENALGO_CLIENT"] = object()
    app.config["SAFETY"] = SafetySystem(SafetyConfig(check_market_hours=False))
    app.config["SAFETY_CONFIG_READY"] = True
    app.config["PENDING_ORDER_QUEUE"] = MagicMock()
    app.config["TIME_SCHEDULER"] = type(
        "_TimeScheduler",
        (),
        {
            "now_ist": staticmethod(
                lambda: datetime.fromisoformat("2026-07-13T10:00:00+05:30")
            ),
            "get_market_session": staticmethod(
                lambda exchange, *, on, symbol: (
                    (wall_time(9, 15), wall_time(15, 30))
                    if exchange == "NSE" and symbol == "RELIANCE" and on == date(2026, 7, 13)
                    else None
                )
            ),
        },
    )()
    app.register_blueprint(mod.agent_bp)
    return app


def _start_body() -> dict:
    return {"symbols": ["RELIANCE"], "exchange": "NSE", "cycle_interval_sec": 1}


# ---------------------------------------------------------------------------
# Optional context builders
# ---------------------------------------------------------------------------


def test_build_vault_uses_configured_path(monkeypatch, tmp_path):
    monkeypatch.setenv("FLINTTRADE_OBSIDIAN_VAULT", str(tmp_path))

    vault = _ORIGINAL_BUILD_VAULT()

    assert vault is not None
    assert vault.root == tmp_path


# ---------------------------------------------------------------------------
# Fail-closed preconditions
# ---------------------------------------------------------------------------


def test_disabled_flag_403(monkeypatch, live_auth):
    monkeypatch.setattr(mod, "_agent_flag_enabled", lambda: False)
    resp = _make_app().test_client().post("/api/v1/ai/agent/start", json=_start_body())
    assert resp.status_code == 403
    assert "autonomous_agent.enabled" in resp.get_json()["message"]


def test_no_jwt_401(monkeypatch):
    monkeypatch.setattr(order_routes_mod, "_decode_request_payload", lambda: None)
    resp = _make_app().test_client().post("/api/v1/ai/agent/start", json=_start_body())
    assert resp.status_code == 401


def test_practice_mode_403(monkeypatch):
    monkeypatch.setattr(
        order_routes_mod,
        "_decode_request_payload",
        lambda: {"mode": "practice", "sub": "user-1", "jti": "jti-1"},
    )
    resp = _make_app().test_client().post("/api/v1/ai/agent/start", json=_start_body())
    assert resp.status_code == 403


def test_missing_acl_grant_403_with_instruction(monkeypatch, live_auth):
    """The agent is its own principal — an ungrated actor must fail fast with
    the exact workspace.json fix, not start a session whose every order is
    refused downstream."""
    monkeypatch.setattr(mod, "_acl_grants_agent", lambda a, b: False)
    resp = _make_app().test_client().post("/api/v1/ai/agent/start", json=_start_body())
    assert resp.status_code == 403
    msg = resp.get_json()["message"]
    assert "autonomous-trader" in msg
    assert "account_acls" in msg


def test_empty_symbols_400(live_auth):
    resp = _make_app().test_client().post("/api/v1/ai/agent/start", json={"symbols": []})
    assert resp.status_code == 400


def test_router_unavailable_503(live_auth):
    app = _make_app()
    app.config["BROKER_ROUTER"] = None
    resp = app.test_client().post("/api/v1/ai/agent/start", json=_start_body())
    assert resp.status_code == 503


def test_unvalidated_safety_runtime_503(live_auth):
    app = _make_app()
    app.config["SAFETY_CONFIG_READY"] = False

    response = app.test_client().post("/api/v1/ai/agent/start", json=_start_body())

    assert response.status_code == 503
    assert mod._RUNNER == {}


def test_start_refuses_while_runtime_is_shutting_down(live_auth):
    app = _make_app()
    app.config["AUTONOMOUS_AGENT_SHUTDOWN_EVENT"] = __import__("threading").Event()
    app.config["AUTONOMOUS_AGENT_SHUTDOWN_EVENT"].set()

    resp = app.test_client().post("/api/v1/ai/agent/start", json=_start_body())

    assert resp.status_code == 503
    assert "shutting down" in resp.get_json()["message"].lower()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def test_start_wires_gated_executor_with_agent_principal(live_auth):
    """The trader receives a GatedChildExecutor bound to actor_type='agent'."""
    app = _make_app()
    resp = app.test_client().post("/api/v1/ai/agent/start", json=_start_body())
    assert resp.status_code == 202

    trader = _FakeTrader.instances[-1]
    executor = trader.kwargs["order_executor"]
    assert isinstance(executor, GatedChildExecutor)
    ctx = executor._request_ctx  # noqa: SLF001
    assert ctx.actor_type == "agent"
    assert ctx.actor_id == "autonomous-trader"
    assert ctx.mode == "live"
    assert ctx.selector == "openalgo:default"
    # The mid-flight revocation brake is wired.
    assert executor._pre_dispatch_check is not None  # noqa: SLF001
    assert callable(executor._router_provider)  # noqa: SLF001
    assert callable(trader.kwargs["entry_intent_sink"])
    assert trader.kwargs["clock"]() == datetime.fromisoformat(
        "2026-07-13T10:00:00+05:30"
    )
    assert trader.kwargs["market_session_provider"](
        "NSE",
        "RELIANCE",
        date(2026, 7, 13),
    ) == (wall_time(9, 15), wall_time(15, 30))

    snap = resp.get_json()["data"]
    assert snap["running"] is True
    assert snap["actor_id"] == "autonomous-trader"


@pytest.mark.asyncio
async def test_agent_entry_sink_persists_only_order_target_and_session_metadata(live_auth):
    app = _make_app()
    queue = app.config["PENDING_ORDER_QUEUE"]
    queue.enqueue.return_value = type("_Request", (), {"id": "intent-1", "status": "pending"})()
    response = app.test_client().post("/api/v1/ai/agent/start", json=_start_body())
    assert response.status_code == 202
    trader = _FakeTrader.instances[-1]

    from flinttrade_core.models import Action, Exchange, Order, PriceType, Product

    order = Order(
        symbol="RELIANCE",
        exchange=Exchange.NSE,
        action=Action.BUY,
        pricetype=PriceType.MARKET,
        product=Product.MIS,
        quantity="1",
        strategy="AutonomousAgent",
    )
    result = await trader.kwargs["entry_intent_sink"](
        order,
        {
            "entry_price": 2500.0,
            "stop_loss": 2450.0,
            "take_profit": 2600.0,
            "signal": "BUY",
        },
    )

    assert result == {"id": "intent-1", "status": "pending"}
    _, kwargs = queue.enqueue.call_args
    assert kwargs["adapter_id"] == "openalgo"
    assert kwargs["account_id"] == "default"
    assert kwargs["source"] == "autonomous-agent"
    assert kwargs["intent_type"] == "entry"
    assert kwargs["producer_ref"]
    assert "jti" not in kwargs["order_params"]
    assert "token" not in kwargs["order_params"]


def test_start_uses_configured_execution_default_when_target_omitted(live_auth):
    """Direct agent starts inherit brokers.execution.default when no target is sent."""

    class _Execution:
        default = "upstox:U1"

    class _Config:
        execution = _Execution()

    class _Router:
        _config = _Config()
        default_selector = "upstox:U1"  # public accessor the routes now read

    app = _make_app(broker_router=_Router())
    resp = app.test_client().post("/api/v1/ai/agent/start", json=_start_body())
    assert resp.status_code == 202

    executor = _FakeTrader.instances[-1].kwargs["order_executor"]
    assert executor._request_ctx.selector == "upstox:U1"  # noqa: SLF001


def test_double_start_409(live_auth):
    app = _make_app()
    client = app.test_client()
    assert client.post("/api/v1/ai/agent/start", json=_start_body()).status_code == 202
    resp = client.post("/api/v1/ai/agent/start", json=_start_body())
    assert resp.status_code == 409


def test_start_claims_slot_atomically(live_auth, monkeypatch):
    """A second /start that races in while the first is still constructing
    (the 'starting' sentinel set, runner not yet registered) is refused —
    not allowed to spawn a second live agent that orphans the first."""
    # Simulate the in-construction window: claim the slot via the sentinel.
    with mod._RUNNER_LOCK:  # noqa: SLF001
        mod._RUNNER["starting"] = True  # noqa: SLF001
    try:
        resp = _make_app().test_client().post("/api/v1/ai/agent/start", json=_start_body())
        assert resp.status_code == 409
        assert _FakeTrader.instances == []  # no trader was constructed
    finally:
        mod._reset_runner_for_tests()  # noqa: SLF001


def test_failed_construction_releases_the_slot(live_auth, monkeypatch):
    """If trader construction raises, the 'starting' sentinel is rolled back so
    the slot is not wedged forever."""
    monkeypatch.setattr(
        mod, "_trader_factory",
        lambda **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    resp = _make_app().test_client().post("/api/v1/ai/agent/start", json=_start_body())
    assert resp.status_code == 500
    with mod._RUNNER_LOCK:  # noqa: SLF001
        assert not mod._RUNNER.get("starting")  # noqa: SLF001
    # A subsequent valid start is accepted (slot was released).
    monkeypatch.setattr(mod, "_trader_factory", _FakeTrader)
    assert _make_app().test_client().post("/api/v1/ai/agent/start", json=_start_body()).status_code == 202


def test_stop_requests_square_off_and_status_reflects(live_auth):
    app = _make_app()
    client = app.test_client()
    client.post("/api/v1/ai/agent/start", json=_start_body())

    resp = client.post("/api/v1/ai/agent/stop", json={})
    assert resp.status_code == 200
    trader = _FakeTrader.instances[-1]
    assert trader.stop_calls == [True]  # square-off is the safe default

    # The session thread exits once the fake trader stops.
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        status = client.get("/api/v1/ai/agent/status").get_json()["data"]
        if not status["running"]:
            break
        time.sleep(0.02)
    assert status["running"] is False


def test_stop_after_thread_start_before_coroutine_entry_runs_no_live_cycle(
    live_auth,
    monkeypatch,
):
    from flinttrade_ai.autonomous_agent import AutonomousTrader

    app = _make_app()
    coroutine_waiting = threading.Event()
    allow_coroutine_entry = threading.Event()
    cycles: list[int] = []
    traders: list[AutonomousTrader] = []
    real_asyncio_run = asyncio.run

    def build_trader(**kwargs: Any) -> AutonomousTrader:
        trader = AutonomousTrader(**kwargs)
        trader._is_market_open = lambda: True  # noqa: SLF001

        async def live_cycle() -> None:
            cycles.append(1)
            trader.request_stop(square_off=False)

        trader.run_cycle = live_cycle  # type: ignore[method-assign]
        traders.append(trader)
        return trader

    def delayed_asyncio_run(coroutine: Any) -> Any:
        coroutine_waiting.set()
        if not allow_coroutine_entry.wait(2.0):
            coroutine.close()
            raise TimeoutError("test did not release coroutine entry")
        return real_asyncio_run(coroutine)

    monkeypatch.setattr(mod, "_trader_factory", build_trader)
    monkeypatch.setattr(mod.asyncio, "run", delayed_asyncio_run)
    client = app.test_client()

    started = client.post("/api/v1/ai/agent/start", json=_start_body())
    assert started.status_code == 202
    assert coroutine_waiting.wait(1.0)
    try:
        stopped = client.post("/api/v1/ai/agent/stop", json={})
        assert stopped.status_code == 200
    finally:
        allow_coroutine_entry.set()

    with mod._RUNNER_LOCK:  # noqa: SLF001
        thread = mod._RUNNER["thread"]  # noqa: SLF001
    thread.join(2.0)

    assert thread.is_alive() is False
    assert cycles == []
    assert traders[0].state.cycle_count == 0


def test_stop_without_session_404(live_auth):
    resp = _make_app().test_client().post("/api/v1/ai/agent/stop", json={})
    assert resp.status_code == 404


def test_runtime_shutdown_requests_square_off_and_joins_agent(live_auth):
    app = _make_app()
    client = app.test_client()
    assert client.post("/api/v1/ai/agent/start", json=_start_body()).status_code == 202

    assert mod.shutdown_agent_runtime(app, timeout=1.0) is True

    trader = _FakeTrader.instances[-1]
    assert trader.stop_calls == [True]
    assert app.config["AUTONOMOUS_AGENT_SHUTDOWN_EVENT"].is_set()
    with mod._RUNNER_LOCK:  # noqa: SLF001
        thread = mod._RUNNER.get("thread")  # noqa: SLF001
    assert thread is not None and not thread.is_alive()


def test_runtime_shutdown_rejects_joined_incomplete_square_off() -> None:
    app = _make_app()

    class _FailedTrader:
        shutdown_complete = False
        stop_failure = "Square-off incomplete"

        def request_stop(self, square_off: bool = True) -> None:
            assert square_off is True

    thread = threading.Thread(target=lambda: None)
    thread.start()
    thread.join()
    with mod._RUNNER_LOCK:  # noqa: SLF001
        mod._RUNNER.update({"trader": _FailedTrader(), "thread": thread})  # noqa: SLF001

    assert mod.shutdown_agent_runtime(app, timeout=1.0) is False


def test_runtime_shutdown_cannot_finish_before_registered_thread_starts(
    live_auth,
    monkeypatch,
):
    """Shutdown must not report success before a published thread can start."""
    app = _make_app()
    real_thread_type = threading.Thread
    agent_start_entered = threading.Event()
    allow_agent_start = threading.Event()
    shutdown_event_set = threading.Event()
    shutdown_finished = threading.Event()
    started_after_shutdown: list[bool] = []
    start_status: list[int] = []
    shutdown_result: list[bool] = []

    class _ObservedShutdownEvent(threading.Event):
        def set(self) -> None:
            super().set()
            shutdown_event_set.set()

    class _ControlledAgentThread(real_thread_type):
        def start(self) -> None:
            agent_start_entered.set()
            if not allow_agent_start.wait(timeout=5.0):
                raise AssertionError("test did not release the agent thread start")
            started_after_shutdown.append(shutdown_finished.is_set())
            super().start()

    app.config["AUTONOMOUS_AGENT_SHUTDOWN_EVENT"] = _ObservedShutdownEvent()
    monkeypatch.setattr(mod.threading, "Thread", _ControlledAgentThread)

    def issue_start() -> None:
        start_status.append(
            app.test_client().post("/api/v1/ai/agent/start", json=_start_body()).status_code
        )

    def issue_shutdown() -> None:
        shutdown_result.append(mod.shutdown_agent_runtime(app, timeout=1.0))
        shutdown_finished.set()

    start_request = real_thread_type(target=issue_start, name="test-agent-start-request")
    start_request.start()
    assert agent_start_entered.wait(timeout=5.0)

    # A fixed start holds the runner lock across Thread.start(), forcing this
    # shutdown to wait. On the buggy path the lock is already free, so wait for
    # shutdown to return before releasing the delayed thread and expose the race.
    acquired_runner_lock = mod._RUNNER_LOCK.acquire(blocking=False)  # noqa: SLF001
    start_holds_runner_lock = not acquired_runner_lock
    if acquired_runner_lock:
        mod._RUNNER_LOCK.release()  # noqa: SLF001
    shutdown_request = real_thread_type(target=issue_shutdown, name="test-agent-shutdown-request")
    shutdown_request.start()
    assert shutdown_event_set.wait(timeout=5.0)
    if not start_holds_runner_lock:
        assert shutdown_finished.wait(timeout=5.0)

    allow_agent_start.set()
    start_request.join(timeout=5.0)
    shutdown_request.join(timeout=5.0)
    assert not start_request.is_alive()
    assert not shutdown_request.is_alive()

    # Clean up the deliberately delayed legacy path before asserting red.
    assert mod.shutdown_agent_runtime(app, timeout=1.0) is True
    assert start_status == [202]
    assert shutdown_result == [True]
    assert started_after_shutdown == [False]


def test_status_idle_shape(live_auth):
    resp = _make_app().test_client().get("/api/v1/ai/agent/status")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["running"] is False
    assert data["enabled"] is True


def test_stop_and_status_require_auth(monkeypatch):
    """Snapshot exposes live positions; stop is an operator action — both
    need a JWT (parity with the smart-route read endpoints)."""
    monkeypatch.setattr(order_routes_mod, "_decode_request_payload", lambda: None)
    client = _make_app().test_client()
    assert client.get("/api/v1/ai/agent/status").status_code == 401
    assert client.post("/api/v1/ai/agent/stop", json={}).status_code == 401
