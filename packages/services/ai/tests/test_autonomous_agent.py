"""Tests for AutonomousTrader agent.

All tests are offline — no real LLM or broker connections.
LLM and broker are mocked to test the agent's logic in isolation.
"""

from __future__ import annotations

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


def make_agent(
    symbols: list[str] | None = None,
    llm_response: str = "BUY",
    order_status: str = "success",
    quotes_ltp: float = 100.0,
) -> AutonomousTrader:
    """Build an AutonomousTrader with fully mocked LLM and broker."""
    symbols = symbols or ["RELIANCE"]
    config = AgentConfig(
        symbols=symbols,
        exchange="NSE",
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
    mock_broker.place_order = AsyncMock(return_value={
        "status": order_status,
        "data": {"price": quotes_ltp, "orderid": "ORD001"},
    })
    mock_broker.close_position = AsyncMock(return_value={"status": "success"})

    return AutonomousTrader(llm_client=mock_llm, openalgo_client=mock_broker, config=config)


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


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def test_initial_status_idle() -> None:
    agent = make_agent()
    assert agent.status == AgentStatus.IDLE


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
    monkeypatch.setattr(agent, "_is_market_open", lambda: True)

    await agent.run_cycle()

    agent.vault.append_note.assert_called()
    _, content = agent.vault.append_note.call_args.args
    assert "RELIANCE" in content
