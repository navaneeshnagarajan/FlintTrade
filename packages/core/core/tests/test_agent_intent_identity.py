"""Entry intention retries and safe generations never create duplicate exposure."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from flask import Flask

import flinttrade_core.agent_routes as routes
import flinttrade_core.order_routes as order_routes
from flinttrade_ai.autonomous_agent import AgentConfig, AgentState, AgentStatus, AutonomousTrader
from flinttrade_core.models import Action, Order
from flinttrade_core.smart_order_routes import _GatedDecision, _GatedOrderResponse
from flinttrade_engine.action_center import ActionCenterError, PendingOrderQueue
from flinttrade_engine.safety import SafetyConfig, SafetySystem, set_safety_gate_secret

pytestmark = pytest.mark.unit


@pytest.fixture
def session(monkeypatch, tmp_path):
    """Start the real route with a durable queue and an inert analysis loop."""
    routes._reset_runner_for_tests()  # noqa: SLF001
    set_safety_gate_secret(b"0123456789abcdef0123456789abcdef")
    stopped = threading.Event()
    captured: dict[str, Any] = {}

    class InertTrader:
        def __init__(self, **kwargs):
            self.state = AgentState()
            self.status = AgentStatus.RUNNING
            self.memory = None
            captured.update(kwargs)
            captured["trader"] = self

        async def run_session(self):
            while not stopped.is_set():
                await asyncio.sleep(0.01)

    for name in ("_build_vault", "_build_learning_memory", "_build_skills_workspace"):
        monkeypatch.setattr(routes, name, lambda: None)
    monkeypatch.setattr(routes, "_agent_flag_enabled", lambda: True)
    monkeypatch.setattr(routes, "_acl_grants_agent", lambda *_: True)
    monkeypatch.setattr(routes, "_build_llm", object)
    monkeypatch.setattr(routes, "_trader_factory", InertTrader)
    monkeypatch.setattr(order_routes, "_decode_request_payload", lambda: {"mode": "live", "jti": "test"})
    monkeypatch.setattr(order_routes, "_is_live_mode_unlocked", lambda: True)
    queue = PendingOrderQueue(tmp_path / "intent-identity.duckdb")
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        # Neither object exposes a broker write method. Tests only persist intents.
        BROKER_ROUTER=object(),
        BROKER_CLIENT=object(),
        SAFETY=SafetySystem(SafetyConfig(check_market_hours=False)),
        SAFETY_CONFIG_READY=True,
        PENDING_ORDER_QUEUE=queue,
        TIME_SCHEDULER=SimpleNamespace(
            now_ist=lambda: datetime.now(UTC),
            get_market_session=lambda *_args, **_kwargs: None,
        ),
    )
    app.register_blueprint(routes.agent_bp)
    try:
        response = app.test_client().post(
            "/api/v1/ai/agent/start", json={"symbols": ["RELIANCE"], "broker": "dhan", "account_id": "primary"}
        )
        assert response.status_code == 202, response.get_json()
        yield SimpleNamespace(queue=queue, sink=captured["entry_intent_sink"], trader=captured["trader"])
    finally:
        stopped.set()
        with routes._RUNNER_LOCK:  # noqa: SLF001
            thread = routes._RUNNER.get("thread")  # noqa: SLF001
        if thread is not None:
            thread.join(timeout=2)
            assert not thread.is_alive()
        routes._reset_runner_for_tests()  # noqa: SLF001
        queue.close()


def _order(**changes):
    return Order(symbol="RELIANCE", action=Action.BUY, strategy="AutonomousAgent").model_copy(update=changes)


def _context(**changes):
    return {"signal": "BUY", "entry_price": 2500.0, "stop_loss": 2450.0, "take_profit": 2600.0, **changes}


@pytest.mark.asyncio
async def test_pending_retries_keep_one_persisted_request(session):
    results = [await session.sink(_order(), _context()) for _ in range(3)]
    assert len({result["id"] for result in results}) == 1
    assert len(session.queue.list_all()) == 1


@pytest.mark.asyncio
async def test_dispatching_retry_cannot_create_another_request(session):
    first = await session.sink(_order(), _context())
    session.queue.claim_for_dispatch(first["id"])
    assert await session.sink(_order(), _context()) == {"id": first["id"], "status": "dispatching"}
    assert len(session.queue.list_all()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("terminal", ["rejected", "expired", "failed"])
async def test_terminal_intention_allows_fresh_same_symbol_generation(session, terminal, monkeypatch):
    first = await session.sink(_order(), _context())
    if terminal == "rejected":
        session.queue.reject(first["id"], "operator declined")
    elif terminal == "expired":
        import flinttrade_engine.action_center as queue_module

        later = datetime.now(UTC) + timedelta(minutes=6)
        with monkeypatch.context() as expiry_patch:
            expiry_patch.setattr(queue_module, "_utc_now_iso", lambda: later.isoformat())
            assert session.queue.get(first["id"]).status == "expired"
    else:
        session.queue.claim_for_dispatch(first["id"])
        session.queue.mark_failed(first["id"], reason="admission denied")
    second = await session.sink(_order(), _context())
    assert second["id"] != first["id"]
    assert second["status"] == "pending"
    assert session.queue.get(first["id"]).status == terminal
    assert len(session.queue.list_all()) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value", [("quantity", "2"), ("action", Action.SELL), ("price", "2499"), ("admission_note", "new rationale")]
)
async def test_changed_order_cannot_silently_reuse_pending_intention(session, field, value):
    first = await session.sink(_order(), _context())
    with pytest.raises(ActionCenterError, match="different|conflict|pending"):
        await session.sink(_order(**{field: value}), _context())
    assert [request.id for request in session.queue.list_pending()] == [first["id"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"stop_loss": 2440.0}, {"signal": "SELL"}, {"rationale": "new thesis"}])
async def test_changed_risk_or_rationale_cannot_silently_reuse_pending_intention(session, changes):
    first = await session.sink(_order(), _context())
    with pytest.raises(ActionCenterError, match="different|conflict|pending"):
        await session.sink(_order(), _context(**changes))
    assert len(session.queue.list_all()) == 1
    assert session.queue.get(first["id"]).intent_context == _context()


@pytest.mark.asyncio
@pytest.mark.parametrize("recorded", [False, True])
async def test_approved_entry_stays_blocked_without_correlated_fill_proof(session, recorded):
    first = await session.sink(_order(), _context())
    session.queue.claim_for_dispatch(first["id"])
    session.queue.mark_approved(first["id"], broker_order_id="test-ack")
    if recorded:
        session.trader.state.trade_counts["RELIANCE"] = 1
        session.trader.state.active_positions["RELIANCE"] = 2500.0
    with pytest.raises(ActionCenterError):
        await session.sink(_order(), _context())
    assert len(session.queue.list_all()) == 1


@pytest.mark.asyncio
async def test_uncertain_dispatch_never_rotates_into_fresh_intention(session):
    first = await session.sink(_order(), _context())
    session.queue.claim_for_dispatch(first["id"])
    session.queue.mark_failed(first["id"], reason="response lost", outcome_uncertain=True)
    with pytest.raises(ActionCenterError):
        await session.sink(_order(), _context())
    assert len(session.queue.list_all()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, ActionCenterError])
async def test_persisted_enqueue_response_loss_reuses_original_identity(session, monkeypatch, error_type):
    enqueue = session.queue.enqueue
    attempts = []

    def lose_first_response(**kwargs):
        attempts.append(kwargs["request_id"])
        result = enqueue(**kwargs)
        if len(attempts) == 1:
            raise error_type("persisted response lost")
        return result

    monkeypatch.setattr(session.queue, "enqueue", lose_first_response)
    try:
        await session.sink(_order(), _context())
    except RuntimeError:
        pass
    retried = await session.sink(_order(), _context())
    assert retried["id"] == attempts[0]
    assert len(session.queue.list_all()) == 1


@pytest.mark.asyncio
async def test_enqueue_failure_before_commit_preserves_retry_identity(session, monkeypatch):
    enqueue = session.queue.enqueue
    attempts = []

    def fail_first_enqueue(**kwargs):
        attempts.append(kwargs["request_id"])
        if len(attempts) == 1:
            raise RuntimeError("storage unavailable")
        return enqueue(**kwargs)

    monkeypatch.setattr(session.queue, "enqueue", fail_first_enqueue)
    with pytest.raises(RuntimeError, match="storage unavailable"):
        await session.sink(_order(), _context())
    await session.sink(_order(), _context())
    assert len(set(attempts)) == 1
    assert len(session.queue.list_all()) == 1


def test_concurrent_event_loops_share_one_fresh_generation_after_rejection(session):
    first = asyncio.run(session.sink(_order(), _context()))
    session.queue.reject(first["id"])
    barrier = threading.Barrier(8)

    def submit():
        barrier.wait(timeout=5)
        return asyncio.run(session.sink(_order(), _context()))

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: submit(), range(8)))
    assert len({result["id"] for result in results}) == 1
    assert results[0]["id"] != first["id"]
    assert len(session.queue.list_pending()) == 1
    assert len(session.queue.list_all()) == 2


@pytest.mark.asyncio
async def test_cancelled_enqueue_keeps_identity_until_worker_finishes(session, monkeypatch):
    enqueue = session.queue.enqueue
    entered = threading.Event()
    release = threading.Event()

    def pause_enqueue(**kwargs):
        entered.set()
        assert release.wait(timeout=5)
        return enqueue(**kwargs)

    monkeypatch.setattr(session.queue, "enqueue", pause_enqueue)
    cancelled = asyncio.create_task(session.sink(_order(), _context()))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        retry = asyncio.create_task(session.sink(_order(), _context()))
    finally:
        release.set()
    result = await retry
    assert [request.id for request in session.queue.list_all()] == [result["id"]]


@pytest.mark.asyncio
async def test_response_loss_then_approval_without_monitoring_cannot_duplicate(session, monkeypatch):
    enqueue = session.queue.enqueue

    def lose_response(**kwargs):
        result = enqueue(**kwargs)
        session.queue.claim_for_dispatch(result.id)
        session.queue.mark_approved(result.id, broker_order_id="test-ack")
        raise RuntimeError("persisted response lost")

    monkeypatch.setattr(session.queue, "enqueue", lose_response)
    with pytest.raises(RuntimeError, match="persisted response lost"):
        await session.sink(_order(), _context())
    with pytest.raises(ActionCenterError):
        await session.sink(_order(), _context())
    assert len(session.queue.list_all()) == 1


@pytest.mark.asyncio
async def test_approved_live_generation_cannot_use_trade_count_as_fill_proof(session):
    first = await session.sink(_order(), _context())
    session.queue.claim_for_dispatch(first["id"])
    session.queue.mark_approved(first["id"], broker_order_id="first-test-ack")
    session.trader.state.trade_counts["RELIANCE"] = 1
    with pytest.raises(ActionCenterError):
        await session.sink(_order(), _context())
    # Neither another entry count nor an unrelated historical learning record
    # proves that this approval's entry has a confirmed, fully filled exit.
    session.trader.state.trade_counts["RELIANCE"] = 2
    session.trader.state.closed_trades.append({"symbol": "RELIANCE", "exit_price_estimated": False})
    with pytest.raises(ActionCenterError):
        await session.sink(_order(), _context())
    assert len(session.queue.list_all()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("exit_path", ["monitor", "square_off"])
async def test_real_live_acknowledged_exit_cannot_create_second_entry_intention(session, exit_path):
    # Match GatedChildExecutor's actual Live response contract: acceptance and
    # an order id, without any execution/fill evidence.
    decision = _GatedDecision(True, _GatedOrderResponse("synthetic-exit-ack"))
    agent = AutonomousTrader(
        llm_client=object(),
        broker_client=SimpleNamespace(quotes=AsyncMock(return_value={"ltp": 90.0})),
        config=AgentConfig(symbols=["RELIANCE"]),
        order_executor=SimpleNamespace(route_order=AsyncMock(return_value=decision)),
    )
    session.trader.state = agent.state
    context = _context(entry_price=100.0, stop_loss=95.0, take_profit=110.0)
    first = await session.sink(_order(), context)
    session.queue.claim_for_dispatch(first["id"])
    session.queue.mark_approved(first["id"], broker_order_id="synthetic-entry-ack")
    await agent.record_approved_entry(
        symbol="RELIANCE",
        action="BUY",
        quantity=1,
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
    )
    if exit_path == "monitor":
        await agent.monitor({"symbol": "RELIANCE", **agent.state.position_details["RELIANCE"]})
    else:
        await agent._square_off_all()  # noqa: SLF001
    assert not agent.state.active_positions
    assert agent.state.trade_counts["RELIANCE"] == 1
    assert agent.state.closed_trades[0]["exit_price_estimated"] is True
    with pytest.raises(ActionCenterError, match="reconcil|fill"):
        await session.sink(_order(), context)
    assert len(session.queue.list_all()) == 1
    assert session.queue.get(first["id"]).status == "approved"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [("account_id", "other"), ("source", "other"), ("intent_type", "exit"), ("order_params", '{"quantity": "2"}')],
)
async def test_conflicting_persisted_payload_cannot_coalesce(session, field, value):
    await session.sink(_order(), _context())
    with session.queue._lock:  # noqa: SLF001
        session.queue._conn.execute(f"UPDATE approval_requests SET {field} = ?", [value])  # noqa: SLF001
    with pytest.raises(ActionCenterError, match="conflict"):
        await session.sink(_order(), _context())
    assert len(session.queue.list_all()) == 1


@pytest.mark.asyncio
async def test_terminal_generation_can_accept_new_order_and_context(session):
    first = await session.sink(_order(), _context())
    session.queue.reject(first["id"])
    second = await session.sink(_order(quantity="2"), _context(stop_loss=2440.0))
    assert second["id"] != first["id"]
    assert session.queue.get(second["id"]).order_params["quantity"] == "2"
    assert session.queue.get(second["id"]).intent_context["stop_loss"] == 2440.0
