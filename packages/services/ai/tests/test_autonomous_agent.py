"""Tests for AutonomousTrader agent.

All tests are offline — no real LLM or broker connections.
LLM and broker are mocked to test the agent's logic in isolation.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from flinttrade_ai.autonomous_agent import (
    AgentConfig,
    AgentState,
    AgentStatus,
    AutonomousTrader,
    MarketData,
    RiskAssessment,
    TradeSignal,
    _ema,
    _macd,
    _rsi,
    _supertrend_signal,
    _vwap,
    _build_signal_prompt,
    _to_float_list,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class StubDecision:
    """Decision shape the gated executor returns (passed/order_response/error)."""

    def __init__(self, passed: bool = True, orderid: str = "ORD001", error: str = "") -> None:
        self.passed = passed
        self.order_response = MagicMock(orderid=orderid) if passed else None
        self.error = error


def make_gated_executor(passed: bool = True, error: str = "") -> MagicMock:
    """Stub of the injected gated order executor (route_order coroutine)."""
    executor = MagicMock()
    executor.route_order = AsyncMock(return_value=StubDecision(passed=passed, error=error))
    return executor


def make_agent(
    symbols: list[str] | None = None,
    llm_response: str = "BUY",
    order_status: str = "success",
    quotes_ltp: float = 100.0,
    with_executor: bool = True,
    exchange: str = "NSE",
    market_session_provider: Any | None = None,
    clock: Any | None = None,
    entry_intent_sink: Any | None = None,
    memory: Any | None = None,
) -> AutonomousTrader:
    """Build an AutonomousTrader with fully mocked LLM, broker, and executor."""
    symbols = symbols or ["RELIANCE"]
    config = AgentConfig(
        symbols=symbols,
        exchange=exchange,
        product="MIS",
        max_position_size=1,
        stop_loss_pct=2.0,
        take_profit_pct=4.0,
        daily_stop_loss=-5000.0,
        max_trades_per_symbol=3,
        cycle_interval_sec=1,
    )

    # Mock LLM
    mock_llm = MagicMock()
    mock_resp = MagicMock()
    mock_resp.content = llm_response
    mock_llm.chat.return_value = mock_resp

    # Mock broker — all methods are async, so use AsyncMock
    mock_broker = MagicMock()
    mock_broker.quotes = AsyncMock(return_value={
        "status": "success",
        "data": {
            "ltp": quotes_ltp,
            "open": quotes_ltp * 0.99,
            "high": quotes_ltp * 1.01,
            "low": quotes_ltp * 0.98,
            "volume": 100_000,
            "prev_close": quotes_ltp * 0.995,
        },
    })
    mock_broker.depth = AsyncMock(return_value={
        "status": "success",
        "data": {
            "bids": [{"quantity": 500}],
            "asks": [{"quantity": 400}],
        },
    })
    mock_broker.history = AsyncMock(return_value={
        "status": "error",
        "message": "no data",
    })
    # The broker mock exposes NO order-write methods — the agent's only order
    # path is the injected gated executor; a regression that reaches for
    # broker.place_order would AttributeError loudly here.
    del mock_broker.place_order
    del mock_broker.close_position

    executor = make_gated_executor(passed=(order_status == "success")) if with_executor else None
    return AutonomousTrader(
        llm_client=mock_llm,
        openalgo_client=mock_broker,
        config=config,
        order_executor=executor,
        entry_intent_sink=entry_intent_sink,
        market_session_provider=market_session_provider,
        clock=clock,
        memory=memory,
    )


# ---------------------------------------------------------------------------
# MarketData
# ---------------------------------------------------------------------------


def test_market_data_valid() -> None:
    md = MarketData(symbol="NIFTY", ltp=22000.0)
    assert md.is_valid


def test_market_data_invalid_ltp_zero() -> None:
    md = MarketData(symbol="NIFTY", ltp=0.0)
    assert not md.is_valid


def test_market_data_invalid_error() -> None:
    md = MarketData(symbol="NIFTY", ltp=22000.0, error="fetch failed")
    assert not md.is_valid


# ---------------------------------------------------------------------------
# Risk assessment
# ---------------------------------------------------------------------------


def test_risk_hold_signal_blocked() -> None:
    agent = make_agent()
    md = MarketData(symbol="RELIANCE", ltp=2500.0)
    risk = agent._assess_risk(TradeSignal.HOLD, md)
    assert not risk.allowed
    assert "HOLD" in risk.reason


def test_risk_daily_sl_hit() -> None:
    agent = make_agent()
    agent.state.stop_loss_hit = True
    md = MarketData(symbol="RELIANCE", ltp=2500.0)
    risk = agent._assess_risk(TradeSignal.BUY, md)
    assert not risk.allowed
    assert "stop-loss" in risk.reason.lower()


def test_risk_already_squared_off() -> None:
    agent = make_agent()
    agent.state.squared_off = True
    md = MarketData(symbol="RELIANCE", ltp=2500.0)
    risk = agent._assess_risk(TradeSignal.BUY, md)
    assert not risk.allowed


def test_risk_daily_pnl_breaches_limit() -> None:
    agent = make_agent()
    agent.state.daily_pnl = -6000.0  # Below -5000 limit
    md = MarketData(symbol="RELIANCE", ltp=2500.0)
    risk = agent._assess_risk(TradeSignal.BUY, md)
    assert not risk.allowed
    assert agent.state.stop_loss_hit  # Side effect: marks stop_loss_hit


def test_risk_max_trades_reached() -> None:
    agent = make_agent()
    agent.state.trade_counts["RELIANCE"] = 3  # max is 3
    md = MarketData(symbol="RELIANCE", ltp=2500.0)
    risk = agent._assess_risk(TradeSignal.BUY, md)
    assert not risk.allowed
    assert "Max trades" in risk.reason


def test_risk_existing_position_blocked() -> None:
    agent = make_agent()
    agent.state.active_positions["RELIANCE"] = 2450.0
    md = MarketData(symbol="RELIANCE", ltp=2500.0)
    risk = agent._assess_risk(TradeSignal.BUY, md)
    assert not risk.allowed


def test_risk_ltp_zero_blocked() -> None:
    agent = make_agent()
    md = MarketData(symbol="RELIANCE", ltp=0.0)
    risk = agent._assess_risk(TradeSignal.BUY, md)
    assert not risk.allowed


def test_risk_allowed_buy() -> None:
    agent = make_agent()
    md = MarketData(symbol="RELIANCE", ltp=2500.0)
    risk = agent._assess_risk(TradeSignal.BUY, md)
    assert risk.allowed
    assert risk.position_qty == 1
    assert risk.stop_loss == pytest.approx(2500.0 * 0.98, rel=1e-4)
    assert risk.take_profit == pytest.approx(2500.0 * 1.04, rel=1e-4)


def test_risk_allowed_sell() -> None:
    agent = make_agent()
    md = MarketData(symbol="RELIANCE", ltp=2500.0)
    risk = agent._assess_risk(TradeSignal.SELL, md)
    assert risk.allowed
    assert risk.stop_loss == pytest.approx(2500.0 * 1.02, rel=1e-4)
    assert risk.take_profit == pytest.approx(2500.0 * 0.96, rel=1e-4)


# ---------------------------------------------------------------------------
# Execute (async)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_blocked_when_not_allowed() -> None:
    agent = make_agent()
    risk = RiskAssessment(allowed=False, reason="test block")
    result = await agent.execute(TradeSignal.BUY, "RELIANCE", risk)
    assert result["status"] == "blocked"
    assert result["reason"] == "test block"


@pytest.mark.asyncio
async def test_execute_places_order_on_success() -> None:
    agent = make_agent(order_status="success")
    risk = RiskAssessment(allowed=True, position_qty=1, stop_loss=2450.0, take_profit=2600.0)
    result = await agent.execute(TradeSignal.BUY, "RELIANCE", risk)
    assert result.get("status") == "success"
    assert "RELIANCE" in agent.state.active_positions
    assert agent.state.trade_counts["RELIANCE"] == 1


@pytest.mark.asyncio
async def test_execute_updates_last_signal() -> None:
    agent = make_agent(order_status="success")
    risk = RiskAssessment(allowed=True, position_qty=1)
    await agent.execute(TradeSignal.SELL, "RELIANCE", risk)
    assert agent.state.last_signals["RELIANCE"] == TradeSignal.SELL


@pytest.mark.asyncio
async def test_execute_fails_closed_without_executor() -> None:
    """No gated executor wired → the agent must NOT place an order anywhere."""
    agent = make_agent(with_executor=False)
    risk = RiskAssessment(allowed=True, position_qty=1)
    result = await agent.execute(TradeSignal.BUY, "RELIANCE", risk)
    assert result["status"] == "blocked"
    assert "gated" in result["reason"]
    assert "RELIANCE" not in agent.state.active_positions
    assert agent.state.trade_counts["RELIANCE"] == 0


@pytest.mark.asyncio
async def test_execute_dispatches_typed_order_via_executor() -> None:
    """The executor receives a typed Order — the shape gate_order HMACs."""
    agent = make_agent(order_status="success")
    risk = RiskAssessment(allowed=True, position_qty=2, stop_loss=2450.0, take_profit=2600.0)
    await agent.execute(TradeSignal.BUY, "RELIANCE", risk, entry_price=2500.0)

    agent.order_executor.route_order.assert_awaited_once()
    order = agent.order_executor.route_order.await_args.args[0]
    assert order.symbol == "RELIANCE"
    assert order.action.value == "BUY"
    assert order.quantity == "2"
    assert order.strategy == "AutonomousAgent"
    # SL/TP monitoring context recorded for the in-cycle monitor.
    details = agent.state.position_details["RELIANCE"]
    assert details["stop_loss"] == 2450.0
    assert details["take_profit"] == 2600.0
    assert details["entry_price"] == 2500.0


@pytest.mark.asyncio
async def test_execute_refused_decision_is_an_error_not_a_position() -> None:
    """A gate/router refusal records nothing and surfaces the error."""
    agent = make_agent()
    agent.order_executor = make_gated_executor(passed=False, error="Blocked by safety system [L2]")
    risk = RiskAssessment(allowed=True, position_qty=1)
    result = await agent.execute(TradeSignal.BUY, "RELIANCE", risk)
    assert result["status"] == "error"
    assert "L2" in result["error"]
    assert "RELIANCE" not in agent.state.active_positions


@pytest.mark.asyncio
async def test_execute_queues_entry_intent_without_dispatching_or_inventing_position() -> None:
    sink = AsyncMock(return_value={"id": "intent-1", "status": "pending"})
    agent = make_agent(entry_intent_sink=sink)
    risk = RiskAssessment(
        allowed=True,
        position_qty=2,
        stop_loss=2450.0,
        take_profit=2600.0,
    )

    result = await agent.execute(TradeSignal.BUY, "RELIANCE", risk, entry_price=2500.0)

    assert result == {"status": "pending_approval", "data": {"request_id": "intent-1"}}
    sink.assert_awaited_once()
    queued_order, queued_context = sink.await_args.args
    assert queued_order.symbol == "RELIANCE"
    assert queued_order.action.value == "BUY"
    assert queued_context == {
        "entry_price": 2500.0,
        "stop_loss": 2450.0,
        "take_profit": 2600.0,
        "signal": "BUY",
    }
    agent.order_executor.route_order.assert_not_awaited()
    assert "RELIANCE" not in agent.state.active_positions
    assert agent.state.trade_counts["RELIANCE"] == 0


@pytest.mark.asyncio
async def test_protective_exit_never_enters_approval_queue() -> None:
    sink = AsyncMock()
    agent = make_agent(quotes_ltp=90.0, entry_intent_sink=sink)
    agent.state.active_positions["RELIANCE"] = 100.0
    position = {
        "symbol": "RELIANCE",
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "action": "BUY",
        "quantity": 1,
    }

    await agent.monitor(position)

    sink.assert_not_awaited()
    agent.order_executor.route_order.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_approved_entry_updates_monitoring_state_once() -> None:
    agent = make_agent(entry_intent_sink=AsyncMock())

    await agent.record_approved_entry(
        symbol="RELIANCE",
        action="BUY",
        quantity=2,
        entry_price=2500.0,
        stop_loss=2450.0,
        take_profit=2600.0,
    )
    await agent.record_approved_entry(
        symbol="RELIANCE",
        action="BUY",
        quantity=2,
        entry_price=2500.0,
        stop_loss=2450.0,
        take_profit=2600.0,
    )

    assert agent.state.active_positions == {"RELIANCE": 2500.0}
    assert agent.state.trade_counts["RELIANCE"] == 1
    assert agent.state.position_details["RELIANCE"]["quantity"] == 2


# ---------------------------------------------------------------------------
# Decide (async)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decide_returns_buy() -> None:
    agent = make_agent(llm_response="BUY")
    md = MarketData(symbol="RELIANCE", ltp=2500.0)
    result = await agent.decide(md)
    assert result == TradeSignal.BUY


@pytest.mark.asyncio
async def test_decide_returns_sell() -> None:
    agent = make_agent(llm_response="SELL")
    md = MarketData(symbol="RELIANCE", ltp=2500.0)
    result = await agent.decide(md)
    assert result == TradeSignal.SELL


@pytest.mark.asyncio
async def test_decide_hold_on_invalid_data() -> None:
    agent = make_agent(llm_response="BUY")
    md = MarketData(symbol="RELIANCE", ltp=0.0)
    result = await agent.decide(md)
    assert result == TradeSignal.HOLD


@pytest.mark.asyncio
async def test_decide_hold_on_unexpected_llm_output() -> None:
    agent = make_agent(llm_response="MAYBE")
    md = MarketData(symbol="RELIANCE", ltp=2500.0)
    result = await agent.decide(md)
    assert result == TradeSignal.HOLD


@pytest.mark.asyncio
async def test_decide_hold_on_llm_error() -> None:
    agent = make_agent()
    agent.llm.chat.side_effect = RuntimeError("LLM timeout")
    md = MarketData(symbol="RELIANCE", ltp=2500.0)
    result = await agent.decide(md)
    assert result == TradeSignal.HOLD


# ---------------------------------------------------------------------------
# Analyze
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_returns_market_data() -> None:
    agent = make_agent()
    result = await agent.analyse("RELIANCE")
    assert isinstance(result, MarketData)
    assert result.symbol == "RELIANCE"
    assert result.ltp == 100.0


@pytest.mark.asyncio
async def test_analyze_bid_ask_ratio() -> None:
    agent = make_agent()
    result = await agent.analyse("RELIANCE")
    assert result.bid_ask_ratio == pytest.approx(500 / 400)


@pytest.mark.asyncio
async def test_analyze_all_returns_all_symbols() -> None:
    agent = make_agent(symbols=["RELIANCE", "ICICIBANK"])
    results = await agent.analyze_all()
    assert "RELIANCE" in results
    assert "ICICIBANK" in results


@pytest.mark.asyncio
async def test_fetch_works_with_TYPED_openalgo_client() -> None:
    """The agent must parse the modern OpenAlgoClient's TYPED Pydantic models
    (Quote/Depth/list[OHLCV]) — not just dict envelopes. Before the fix it
    only handled dicts, so the live-wired agent set data.error on every
    symbol and could never trade (the control plane was dead on arrival)."""
    from types import SimpleNamespace

    # Typed Quote/Depth/OHLCV stand-ins (attribute access, NOT dicts).
    quote = SimpleNamespace(ltp=2500.0, open=2480.0, high=2520.0, low=2470.0,
                            volume=100000, prev_close=2490.0)
    level = SimpleNamespace(price=2500.0, quantity=300)
    depth = SimpleNamespace(bids=[level], asks=[SimpleNamespace(price=2501.0, quantity=200)])
    bars = [
        SimpleNamespace(close=2500.0 + i, high=2505.0 + i, low=2495.0 + i, volume=1000.0)
        for i in range(40)
    ]

    agent = make_agent()
    agent.broker.quotes = AsyncMock(return_value=quote)
    agent.broker.depth = AsyncMock(return_value=depth)
    agent.broker.history = AsyncMock(return_value=bars)

    data = await agent.analyse("RELIANCE")
    assert data.error == ""           # NOT "quotes failed: ..."
    assert data.is_valid              # would be False if parsing failed
    assert data.ltp == 2500.0
    assert data.prev_close == 2490.0
    assert data.bid_ask_ratio == pytest.approx(300 / 200)
    # Indicators computed from the typed OHLCV bars (40 >= 30 minimum).
    assert data.rsi is not None


# ---------------------------------------------------------------------------
# Monitor (async)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_monitor_closes_on_stop_loss() -> None:
    agent = make_agent(quotes_ltp=90.0)  # LTP dropped to 90
    agent.state.active_positions["RELIANCE"] = 100.0
    position = {
        "symbol": "RELIANCE",
        "entry_price": 100.0,
        "stop_loss": 95.0,   # SL at 95, current LTP 90 → should close
        "take_profit": 110.0,
        "action": "BUY",
        "quantity": 1,
    }
    await agent.monitor(position)
    assert "RELIANCE" not in agent.state.active_positions
    assert agent.state.daily_pnl == pytest.approx(-10.0)


@pytest.mark.asyncio
async def test_monitor_closes_on_stop_loss_with_TYPED_quote() -> None:
    """monitor() must read a TYPED Quote (the production client), not just a
    dict envelope — else SL/TP is dead on arrival against the live client."""
    from types import SimpleNamespace

    agent = make_agent()
    agent.broker.quotes = AsyncMock(return_value=SimpleNamespace(ltp=90.0, prev_close=100.0))
    agent.state.active_positions["RELIANCE"] = 100.0
    position = {
        "symbol": "RELIANCE", "entry_price": 100.0, "stop_loss": 95.0,
        "take_profit": 110.0, "action": "BUY", "quantity": 1,
    }
    await agent.monitor(position)
    # SL hit (LTP 90 ≤ 95) → the gated reverse order fired and the position closed.
    agent.order_executor.route_order.assert_awaited_once()
    assert "RELIANCE" not in agent.state.active_positions


@pytest.mark.asyncio
async def test_monitor_closes_on_take_profit() -> None:
    agent = make_agent(quotes_ltp=112.0)
    agent.state.active_positions["RELIANCE"] = 100.0
    position = {
        "symbol": "RELIANCE",
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,  # TP at 110, current LTP 112 → should close
        "action": "BUY",
        "quantity": 1,
    }
    await agent.monitor(position)
    assert "RELIANCE" not in agent.state.active_positions
    assert agent.state.daily_pnl == pytest.approx(12.0)


@pytest.mark.asyncio
async def test_monitor_no_close_within_range() -> None:
    agent = make_agent(quotes_ltp=102.0)
    agent.state.active_positions["RELIANCE"] = 100.0
    position = {
        "symbol": "RELIANCE",
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "action": "BUY",
        "quantity": 1,
    }
    await agent.monitor(position)
    # Position should remain open
    assert "RELIANCE" in agent.state.active_positions


@pytest.mark.asyncio
async def test_monitor_square_off_goes_through_gated_executor() -> None:
    """The SL exit is a gated reverse order, not a raw broker write."""
    agent = make_agent(quotes_ltp=90.0)
    agent.state.active_positions["RELIANCE"] = 100.0
    position = {
        "symbol": "RELIANCE",
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "action": "BUY",
        "quantity": 1,
    }
    await agent.monitor(position)
    agent.order_executor.route_order.assert_awaited_once()
    order = agent.order_executor.route_order.await_args.args[0]
    assert order.action.value == "SELL"  # reverse of the BUY position


@pytest.mark.asyncio
async def test_monitor_fails_closed_without_executor() -> None:
    """SL hit but no executor → the position stays tracked, P&L untouched."""
    agent = make_agent(quotes_ltp=90.0, with_executor=False)
    agent.state.active_positions["RELIANCE"] = 100.0
    position = {
        "symbol": "RELIANCE",
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "action": "BUY",
        "quantity": 1,
    }
    await agent.monitor(position)
    assert "RELIANCE" in agent.state.active_positions
    assert agent.state.daily_pnl == 0.0


@pytest.mark.asyncio
async def test_monitor_refused_square_off_keeps_position() -> None:
    """A refused exit order must NOT mark the position closed."""
    agent = make_agent(quotes_ltp=90.0)
    agent.order_executor = make_gated_executor(passed=False, error="kill switch")
    agent.state.active_positions["RELIANCE"] = 100.0
    position = {
        "symbol": "RELIANCE",
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "action": "BUY",
        "quantity": 1,
    }
    await agent.monitor(position)
    assert "RELIANCE" in agent.state.active_positions
    assert agent.state.daily_pnl == 0.0


@pytest.mark.asyncio
async def test_square_off_all_places_gated_reverse_orders() -> None:
    """End-of-day square-off exits each position through the gate."""
    agent = make_agent()
    agent.state.active_positions["RELIANCE"] = 100.0
    agent.state.position_details["RELIANCE"] = {
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "action": "BUY",
        "quantity": 1,
    }
    result = await agent._square_off_all()
    agent.order_executor.route_order.assert_awaited_once()
    order = agent.order_executor.route_order.await_args.args[0]
    assert order.action.value == "SELL"
    assert "RELIANCE" not in agent.state.active_positions
    assert "RELIANCE" not in agent.state.position_details
    assert result is True  # genuinely flat


@pytest.mark.asyncio
async def test_square_off_all_returns_false_when_an_exit_is_refused() -> None:
    """A refused exit leaves the position tracked and must report NOT-flat —
    run_session relies on this to avoid a false squared_off state."""
    agent = make_agent()
    agent.order_executor = make_gated_executor(passed=False, error="kill switch")
    agent.state.active_positions["RELIANCE"] = 100.0
    agent.state.position_details["RELIANCE"] = {
        "entry_price": 100.0, "stop_loss": 95.0, "take_profit": 110.0,
        "action": "BUY", "quantity": 1,
    }
    result = await agent._square_off_all()
    assert result is False
    assert "RELIANCE" in agent.state.active_positions  # still open


@pytest.mark.asyncio
async def test_square_off_abort_stops_and_keeps_remaining_positions() -> None:
    """A SmartRouteAbort (session revoked) mid-square-off stops the loop and
    leaves remaining positions tracked — never a false flat."""

    class _Abort(Exception):
        pass

    _Abort.__name__ = "SmartRouteAbort"  # matched by class name in the agent

    executor = MagicMock()
    executor.route_order = AsyncMock(side_effect=_Abort("session revoked"))
    agent = make_agent()
    agent.order_executor = executor
    agent.state.active_positions = {"RELIANCE": 100.0, "TCS": 50.0}
    agent.state.position_details = {
        "RELIANCE": {"action": "BUY", "quantity": 1},
        "TCS": {"action": "BUY", "quantity": 1},
    }
    result = await agent._square_off_all()
    assert result is False
    # The abort stopped after the first attempt — both positions remain.
    assert agent.state.active_positions
    assert executor.route_order.await_count == 1


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def test_initial_status_idle() -> None:
    agent = make_agent()
    assert agent.status == AgentStatus.IDLE


def test_market_open_fails_closed_without_effective_session_provider() -> None:
    agent = make_agent(
        clock=lambda: datetime(2026, 7, 10, 10, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))),
    )

    assert agent._is_market_open("RELIANCE") is False


def test_market_open_resolves_cross_midnight_session_by_exchange_and_symbol() -> None:
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime(2026, 4, 18, 0, 20, tzinfo=ist)
    calls: list[tuple[str, str, date]] = []

    def session_for(exchange: str, symbol: str, on: date):
        calls.append((exchange, symbol, on))
        if on == date(2026, 4, 17):
            return time(18, 0), time(0, 45)
        return None

    agent = make_agent(
        symbols=["GOLDM"],
        exchange="MCX",
        market_session_provider=session_for,
        clock=lambda: now,
    )

    assert agent._is_market_open("GOLDM") is True
    assert calls == [
        ("MCX", "GOLDM", date(2026, 4, 18)),
        ("MCX", "GOLDM", date(2026, 4, 17)),
    ]


def test_stop_square_off_intent_is_monotonic() -> None:
    agent = make_agent()

    agent.request_stop(square_off=True)
    agent.request_stop(square_off=False)

    assert agent._stop_requested is True
    assert agent._square_off_on_stop is True
    assert agent.status == AgentStatus.STOPPING


@pytest.mark.asyncio
async def test_stop_after_analysis_prevents_symbol_decisions_and_execution(monkeypatch) -> None:
    agent = make_agent()
    monkeypatch.setattr(agent, "_is_market_open", lambda *_args: True)

    async def analyse_then_stop(*_args: Any) -> dict[str, MarketData]:
        agent.request_stop(square_off=False)
        return {"RELIANCE": MarketData(symbol="RELIANCE", ltp=100.0)}

    agent.analyze_all = AsyncMock(side_effect=analyse_then_stop)
    agent.decide = AsyncMock(return_value="BUY")

    result = await agent.run_cycle()

    assert result["stopped"] is True
    assert result["reason"] == "stop_requested"
    agent.decide.assert_not_awaited()
    agent.order_executor.route_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_during_decision_is_rechecked_immediately_before_execution(monkeypatch) -> None:
    agent = make_agent()
    monkeypatch.setattr(agent, "_is_market_open", lambda *_args: True)
    agent.analyze_all = AsyncMock(
        return_value={"RELIANCE": MarketData(symbol="RELIANCE", ltp=100.0)}
    )

    async def decide_then_stop(_market_data: MarketData) -> str:
        agent.request_stop(square_off=False)
        return "BUY"

    agent.decide = AsyncMock(side_effect=decide_then_stop)

    result = await agent.run_cycle()

    assert result["stopped"] is True
    assert result["reason"] == "stop_requested"
    agent.order_executor.route_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_between_symbols_prevents_later_symbol_execution(monkeypatch) -> None:
    agent = make_agent(symbols=["RELIANCE", "TCS"])
    monkeypatch.setattr(agent, "_is_market_open", lambda *_args: True)
    agent.analyze_all = AsyncMock(
        return_value={
            "RELIANCE": MarketData(symbol="RELIANCE", ltp=100.0),
            "TCS": MarketData(symbol="TCS", ltp=200.0),
        }
    )
    agent.decide = AsyncMock(return_value="BUY")

    async def execute_then_stop(*_args: Any, **_kwargs: Any) -> dict[str, str]:
        agent.request_stop(square_off=False)
        return {"status": "blocked"}

    agent.execute = AsyncMock(side_effect=execute_then_stop)

    result = await agent.run_cycle()

    assert result["stopped"] is True
    assert result["reason"] == "stop_requested"
    assert agent.execute.await_count == 1
    assert agent.execute.await_args.args[1] == "RELIANCE"


@pytest.mark.asyncio
async def test_direct_execution_fails_closed_after_stop_request() -> None:
    agent = make_agent()
    agent.request_stop(square_off=False)

    result = await agent.execute(
        "BUY",
        "RELIANCE",
        RiskAssessment(allowed=True, position_qty=1),
        entry_price=100.0,
    )

    assert result == {"status": "blocked", "reason": "stop_requested"}
    agent.order_executor.route_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_during_order_construction_is_checked_before_gated_dispatch() -> None:
    agent = make_agent()

    def build_then_stop(*_args: Any) -> object:
        agent.request_stop(square_off=False)
        return object()

    agent._build_market_order = MagicMock(side_effect=build_then_stop)

    result = await agent.execute(
        "BUY",
        "RELIANCE",
        RiskAssessment(allowed=True, position_qty=1),
        entry_price=100.0,
    )

    assert result == {"status": "blocked", "reason": "stop_requested"}
    agent.order_executor.route_order.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_stop_square_off_remains_observable_as_stop_failed(monkeypatch) -> None:
    agent = make_agent()
    monkeypatch.setattr(agent, "_is_market_open", lambda *_args: True)
    agent.order_executor = make_gated_executor(passed=False, error="kill switch")
    agent.state.active_positions["RELIANCE"] = 100.0
    agent.state.position_details["RELIANCE"] = {
        "action": "BUY",
        "quantity": 1,
    }
    agent.request_stop(square_off=True)

    await agent.run_session()

    assert agent.status == AgentStatus.STOP_FAILED
    assert agent.shutdown_complete is False
    assert "RELIANCE" in agent.stop_failure
    assert "RELIANCE" in agent.state.active_positions


@pytest.mark.asyncio
async def test_market_close_with_tracked_position_attempts_square_off_and_preserves_failure(monkeypatch) -> None:
    agent = make_agent()
    monkeypatch.setattr(agent, "_is_market_open", lambda *_args: False)
    agent.order_executor = make_gated_executor(passed=False, error="market exit refused")
    agent.state.active_positions["RELIANCE"] = 100.0
    agent.state.position_details["RELIANCE"] = {
        "action": "BUY",
        "quantity": 1,
    }

    await agent.run_session()

    agent.order_executor.route_order.assert_awaited_once()
    assert agent.status == AgentStatus.STOP_FAILED
    assert agent.shutdown_complete is False


@pytest.mark.asyncio
async def test_scheduled_square_off_failure_is_not_retried_during_same_unwind(monkeypatch) -> None:
    agent = make_agent()
    monkeypatch.setattr(agent, "_is_market_open", lambda *_args: True)
    monkeypatch.setattr(agent, "_is_square_off_time", lambda *_args: True)
    agent.order_executor = make_gated_executor(passed=False, error="scheduled exit refused")
    agent.state.active_positions["RELIANCE"] = 100.0
    agent.state.position_details["RELIANCE"] = {
        "action": "BUY",
        "quantity": 1,
    }

    await agent.run_session()

    agent.order_executor.route_order.assert_awaited_once()
    assert agent.status == AgentStatus.STOP_FAILED


@pytest.mark.asyncio
async def test_stop_requested_before_session_entry_prevents_live_cycle(monkeypatch) -> None:
    agent = make_agent()
    monkeypatch.setattr(agent, "_is_market_open", lambda *_args: True)

    async def stop_after_first_cycle() -> None:
        agent.request_stop(square_off=False)

    agent.run_cycle = AsyncMock(side_effect=stop_after_first_cycle)
    agent.request_stop(square_off=False)

    await agent.run_session()

    agent.run_cycle.assert_not_awaited()
    assert agent.state.cycle_count == 0


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def test_build_signal_prompt_contains_symbol() -> None:
    md = MarketData(symbol="NIFTY25JULFUT", ltp=24500.0, rsi=55.0)
    state = AgentState()
    config = AgentConfig(exchange="NFO")
    prompt = _build_signal_prompt(md, state, config)
    assert "NIFTY25JULFUT" in prompt
    assert "55.0" in prompt
    assert "BUY, SELL, or HOLD" in prompt


def test_build_signal_prompt_shows_daily_pnl() -> None:
    md = MarketData(symbol="TEST", ltp=100.0)
    state = AgentState(daily_pnl=-2500.0)
    config = AgentConfig()
    prompt = _build_signal_prompt(md, state, config)
    assert "-2500" in prompt


# ---------------------------------------------------------------------------
# Technical indicator helpers
# ---------------------------------------------------------------------------


def test_ema_basic() -> None:
    data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    result = _ema(data, period=3)
    assert len(result) > 0
    assert result[0] == pytest.approx(2.0)  # SMA of first 3


def test_ema_insufficient_data() -> None:
    assert _ema([1.0, 2.0], period=5) == []


def test_rsi_basic() -> None:
    prices = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.15,
              43.61, 44.33, 44.83, 45.10, 45.15, 43.61, 44.33]
    result = _rsi(prices, period=5)
    assert len(result) > 0
    assert 0.0 <= result[-1] <= 100.0


def test_rsi_insufficient_data() -> None:
    assert _rsi([1.0, 2.0, 3.0], period=14) == []


def test_macd_returns_two_series() -> None:
    prices = [float(i) for i in range(100)]
    macd_line, signal_line = _macd(prices, fast=3, slow=6, signal=3)
    assert len(macd_line) > 0
    assert len(signal_line) > 0


def test_macd_insufficient_data() -> None:
    macd, sig = _macd([1.0, 2.0], fast=12, slow=26, signal=9)
    assert macd == [] or sig == []


def test_vwap_basic() -> None:
    highs = [102.0, 103.0, 104.0]
    lows = [98.0, 99.0, 100.0]
    closes = [100.0, 101.0, 102.0]
    vols = [1000.0, 2000.0, 1500.0]
    result = _vwap(highs, lows, closes, vols)
    assert result is not None
    assert result > 0


def test_vwap_zero_volume() -> None:
    result = _vwap([100.0], [98.0], [99.0], [0.0])
    assert result is None


def test_supertrend_returns_valid_string() -> None:
    highs = [102.0 + i * 0.1 for i in range(20)]
    lows = [98.0 + i * 0.1 for i in range(20)]
    closes = [100.0 + i * 0.1 for i in range(20)]
    result = _supertrend_signal(highs, lows, closes, period=7, multiplier=3.0)
    assert result in ("bullish", "bearish", "neutral")


def test_supertrend_insufficient_data() -> None:
    result = _supertrend_signal([100.0], [98.0], [99.0])
    assert result == "neutral"


def test_to_float_list_plain() -> None:
    assert _to_float_list([1, 2, 3]) == [1.0, 2.0, 3.0]


def test_to_float_list_empty() -> None:
    assert _to_float_list([]) == []


def test_to_float_list_none() -> None:
    assert _to_float_list(None) == []


# ---------------------------------------------------------------------------
# Obsidian vault integration
#
# The agent reads operator notes as decision context and journals each decision
# back. Both are pure vault I/O, off the order path — and a vault error must
# never disrupt a decision or a cycle.
# ---------------------------------------------------------------------------


def _vault_mock(snippet: str | None = None, available: bool = True) -> MagicMock:
    vault = MagicMock()
    vault.available = available
    vault.search.return_value = (
        [{"path": "ideas/nifty.md", "snippet": snippet}] if snippet else []
    )
    vault.append_note.return_value = "FlintTrade/Journal/2026-06-06.md"
    return vault


@pytest.mark.asyncio
async def test_decide_injects_obsidian_context_into_the_prompt() -> None:
    agent = make_agent(llm_response="HOLD")
    agent.vault = _vault_mock(snippet="NIFTY: bullish above 22000, watch breakout")

    await agent.decide(MarketData(symbol="NIFTY", ltp=22000.0))

    agent.vault.search.assert_called_once()
    assert agent.vault.search.call_args.args[0] == "NIFTY"
    messages = agent.llm.chat.call_args.args[0]
    user_content = messages[1].content
    assert "Operator notes (from your Obsidian vault):" in user_content
    assert "bullish above 22000" in user_content


@pytest.mark.asyncio
async def test_decide_without_a_vault_omits_the_notes_block() -> None:
    agent = make_agent(llm_response="HOLD")  # no vault configured (default None)

    await agent.decide(MarketData(symbol="NIFTY", ltp=22000.0))

    messages = agent.llm.chat.call_args.args[0]
    assert "Operator notes" not in messages[1].content


@pytest.mark.asyncio
async def test_vault_failure_never_breaks_a_decision() -> None:
    agent = make_agent(llm_response="BUY")
    agent.vault = MagicMock()
    agent.vault.available = True
    agent.vault.search.side_effect = RuntimeError("vault offline")

    signal = await agent.decide(MarketData(symbol="NIFTY", ltp=22000.0))

    assert signal in ("BUY", "SELL", "HOLD")  # degraded to no-context, still decided
    assert "Operator notes" not in agent.llm.chat.call_args.args[0][1].content


def test_journal_decision_appends_to_the_vault() -> None:
    agent = make_agent()
    agent.vault = _vault_mock(snippet="x")

    agent._journal_decision(
        "RELIANCE", "BUY",
        RiskAssessment(allowed=True, reason="ok", position_qty=1),
        {"status": "success"},
    )

    agent.vault.append_note.assert_called_once()
    note_path, content = agent.vault.append_note.call_args.args
    assert note_path.startswith("FlintTrade/Journal/")
    assert "RELIANCE" in content
    assert "signal=BUY" in content
    assert "order=success" in content


def test_journal_decision_noops_without_an_available_vault() -> None:
    agent = make_agent()
    agent.vault = MagicMock()
    agent.vault.available = False

    agent._journal_decision("RELIANCE", "HOLD", RiskAssessment(), {"status": "n/a"})

    agent.vault.append_note.assert_not_called()


@pytest.mark.asyncio
async def test_run_cycle_journals_each_decision(monkeypatch) -> None:
    agent = make_agent(llm_response="HOLD")
    agent.vault = _vault_mock(snippet="note")
    monkeypatch.setattr(agent, "_is_market_open", lambda *_args: True)

    await agent.run_cycle()

    agent.vault.append_note.assert_called()
    _, content = agent.vault.append_note.call_args.args
    assert "RELIANCE" in content


class _RaisingAvailableVault:
    """A vault whose ``available`` property raises — simulates a vault that does
    real I/O in its availability check and fails. Must never break the agent."""

    @property
    def available(self) -> bool:
        raise RuntimeError("vault availability check did I/O and failed")

    def search(self, *_a: object, **_k: object) -> list:
        raise AssertionError("search must not be reached when available raises")

    def append_note(self, *_a: object, **_k: object) -> str:
        raise AssertionError("append_note must not be reached when available raises")


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_return", [None, 42, ["just a string"], [None], {"snippet": "x"}])
async def test_malformed_vault_search_return_never_breaks_a_decision(bad_return) -> None:
    # The adversarial-verification finding: a malformed search() RETURN (not a
    # raise) must still degrade to no-context, never propagate out of decide().
    agent = make_agent(llm_response="BUY")
    agent.vault = MagicMock()
    agent.vault.available = True
    agent.vault.search.return_value = bad_return

    signal = await agent.decide(MarketData(symbol="NIFTY", ltp=22000.0))

    assert signal in ("BUY", "SELL", "HOLD")  # decided, did not raise
    assert "Operator notes" not in agent.llm.chat.call_args.args[0][1].content


@pytest.mark.asyncio
async def test_raising_available_property_never_breaks_a_decision() -> None:
    agent = make_agent(llm_response="HOLD")
    agent.vault = _RaisingAvailableVault()

    signal = await agent.decide(MarketData(symbol="NIFTY", ltp=22000.0))

    assert signal in ("BUY", "SELL", "HOLD")
    assert "Operator notes" not in agent.llm.chat.call_args.args[0][1].content


def test_journal_decision_swallows_a_raising_available_property() -> None:
    agent = make_agent()
    agent.vault = _RaisingAvailableVault()

    # Must not raise — journalling can never disrupt the cycle.
    agent._journal_decision(
        "RELIANCE", "BUY", RiskAssessment(allowed=True, reason="ok"), {"status": "success"},
    )


# ---------------------------------------------------------------------------
# Learning loop — closed-trade recording, post-session reflection, prompt
# context. Pure learning I/O: every test also proves the fail-safe posture.
# ---------------------------------------------------------------------------


class StubMemory:
    """Minimal MemoryBackend double recording adds and serving context."""

    def __init__(self, context: str = "") -> None:
        self.added: list[dict[str, Any]] = []
        self.context = context

    def add(self, content: str, category: str, importance=None, metadata=None, *, symbol: str = "") -> str:
        self.added.append({
            "content": content,
            "category": category,
            "metadata": metadata or {},
            "symbol": symbol,
        })
        return f"mem-{len(self.added)}"

    def retrieve(self, query: str, top_k: int = 5, *, symbol=None):
        return []

    def summarise_context(self, symbol: str, query: str, max_tokens: int = 2000) -> str:
        return self.context

    def clear(self, symbol=None) -> None:
        self.added.clear()


@pytest.mark.asyncio
async def test_monitor_records_a_closed_trade_on_sl_exit() -> None:
    agent = make_agent(quotes_ltp=95.0)  # LTP below the SL below
    agent.state.active_positions["RELIANCE"] = 100.0
    position = {
        "symbol": "RELIANCE",
        "entry_price": 100.0,
        "stop_loss": 98.0,
        "take_profit": 104.0,
        "action": "BUY",
        "quantity": 2,
    }

    await agent.monitor(position)

    assert len(agent.state.closed_trades) == 1
    record = agent.state.closed_trades[0]
    assert record["symbol"] == "RELIANCE"
    assert record["action"] == "BUY"
    assert record["entry_price"] == 100.0
    assert record["exit_price"] == 95.0
    assert record["quantity"] == 2
    assert record["pnl"] == pytest.approx(-10.0)
    assert record["pnl_pct"] == pytest.approx(-5.0)
    assert record["exit_reason"] == "sl_tp"


@pytest.mark.asyncio
async def test_square_off_all_records_closed_trades_with_estimated_exit() -> None:
    agent = make_agent(quotes_ltp=110.0)
    agent.state.active_positions["RELIANCE"] = 100.0
    agent.state.position_details["RELIANCE"] = {
        "entry_price": 100.0,
        "action": "BUY",
        "quantity": 3,
        "stop_loss": 90.0,
        "take_profit": 120.0,
    }

    flat = await agent._square_off_all()

    assert flat is True
    assert len(agent.state.closed_trades) == 1
    record = agent.state.closed_trades[0]
    assert record["exit_reason"] == "square_off"
    assert record["exit_price_estimated"] is True
    assert record["exit_price"] == 110.0
    assert record["pnl"] == pytest.approx(30.0)


@pytest.mark.asyncio
async def test_post_session_learning_persists_rule_based_lessons() -> None:
    memory = StubMemory()
    agent = make_agent(memory=memory)
    agent.llm = None  # rule-based fallback — the loop needs no LLM at all
    agent.state.closed_trades = [
        {"symbol": "RELIANCE", "action": "BUY", "entry_price": 100.0,
         "exit_price": 95.0, "quantity": 2, "pnl": -10.0, "pnl_pct": -5.0},
        {"symbol": "RELIANCE", "action": "BUY", "entry_price": 100.0,
         "exit_price": 108.0, "quantity": 1, "pnl": 8.0, "pnl_pct": 8.0},
    ]

    await agent._run_post_session_learning()

    assert memory.added, "reflection lessons were not persisted"
    for entry in memory.added:
        assert entry["category"] == "reflection"
        assert entry["metadata"]["source"] == "autonomous-agent-session"
        assert entry["metadata"]["trades_analysed"] == 2
        assert entry["symbol"] == "RELIANCE"


@pytest.mark.asyncio
async def test_post_session_learning_skips_without_memory_or_trades() -> None:
    # No memory backend: nothing happens even with trades.
    agent = make_agent()
    agent.state.closed_trades = [{"symbol": "X", "pnl": 1.0}]
    await agent._run_post_session_learning()

    # Memory but no trades: nothing persisted.
    memory = StubMemory()
    agent2 = make_agent(memory=memory)
    await agent2._run_post_session_learning()
    assert memory.added == []


@pytest.mark.asyncio
async def test_post_session_learning_never_raises() -> None:
    class ExplodingMemory(StubMemory):
        def add(self, *args: Any, **kwargs: Any) -> str:
            raise RuntimeError("memory backend down")

    agent = make_agent(memory=ExplodingMemory())
    agent.llm = None
    agent.state.closed_trades = [
        {"symbol": "RELIANCE", "action": "BUY", "entry_price": 100.0,
         "exit_price": 95.0, "quantity": 1, "pnl": -5.0, "pnl_pct": -5.0},
    ]

    # Must not raise — learning can never disrupt session shutdown.
    await agent._run_post_session_learning()


@pytest.mark.asyncio
async def test_decide_includes_memory_lessons_in_the_prompt() -> None:
    memory = StubMemory(context="- Avoid chasing gap-ups after 10:30 IST")
    agent = make_agent(llm_response="HOLD", memory=memory)

    signal = await agent.decide(MarketData(symbol="RELIANCE", ltp=100.0))

    assert signal in ("BUY", "SELL", "HOLD")
    prompt = agent.llm.chat.call_args.args[0][1].content
    assert "Lessons from previous sessions" in prompt
    assert "Avoid chasing gap-ups" in prompt


@pytest.mark.asyncio
async def test_decide_without_memory_omits_the_lessons_block() -> None:
    agent = make_agent(llm_response="HOLD")

    await agent.decide(MarketData(symbol="RELIANCE", ltp=100.0))

    prompt = agent.llm.chat.call_args.args[0][1].content
    assert "Lessons from previous sessions" not in prompt


@pytest.mark.asyncio
async def test_memory_failure_never_breaks_a_decision() -> None:
    class ExplodingContext(StubMemory):
        def summarise_context(self, symbol: str, query: str, max_tokens: int = 2000) -> str:
            raise RuntimeError("chroma offline")

    agent = make_agent(llm_response="HOLD", memory=ExplodingContext())

    signal = await agent.decide(MarketData(symbol="RELIANCE", ltp=100.0))

    assert signal in ("BUY", "SELL", "HOLD")
    assert "Lessons from previous sessions" not in agent.llm.chat.call_args.args[0][1].content


# ---------------------------------------------------------------------------
# Compressed full-session proof (Phase 4): pre-open → cycles → square-off →
# post-session reflection, with the gated executor as the only order path.
# The real wall-clock Practice-day run remains a separate market-day check;
# this pins the runtime chain end-to-end on a synthetic clock.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compressed_full_session_trades_squares_off_and_learns() -> None:
    import asyncio

    ist = timezone(timedelta(hours=5, minutes=30))

    # Synthetic clock: starts mid-session, advances ~95 minutes per completed
    # cycle so the session crosses the close after a handful of cycles.
    current = {"now": datetime(2026, 7, 20, 10, 0, tzinfo=ist)}

    def clock() -> datetime:
        return current["now"]

    def session_for(exchange: str, symbol: str, on: date):
        return time(9, 15), time(15, 30)

    memory = StubMemory()
    agent = make_agent(
        llm_response="BUY",
        market_session_provider=session_for,
        clock=clock,
        memory=memory,
    )
    original_run_cycle = agent.run_cycle

    async def advancing_cycle() -> dict[str, Any]:
        result = await original_run_cycle()
        current["now"] = current["now"] + timedelta(minutes=95)
        return result

    agent.run_cycle = advancing_cycle  # type: ignore[method-assign]

    await asyncio.wait_for(agent.run_session(), timeout=30)

    # Session ended flat with an explicit terminal state.
    assert agent.state.squared_off is True
    assert agent.status == AgentStatus.STOPPED
    # The BUY entry opened through the gated executor and was closed at the
    # session end, so the learning tier had a round trip to reflect over.
    assert agent.state.closed_trades
    assert agent.state.closed_trades[0]["exit_reason"] == "square_off"
    assert memory.added, "post-session reflection persisted no lessons"
    # The gated executor was the ONLY order path: one entry + one exit.
    assert agent.order_executor.route_order.await_count >= 2
