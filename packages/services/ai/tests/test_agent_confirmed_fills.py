"""Confirmed Practice fills must win over indicative decision-time quotes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from flinttrade_ai.autonomous_agent import AgentConfig, AutonomousTrader, RiskAssessment


def trader(fill_price: float) -> AutonomousTrader:
    broker = SimpleNamespace(quotes=AsyncMock(return_value={"ltp": 90.0}))
    executor = SimpleNamespace(route_order=AsyncMock(return_value=SimpleNamespace(
        passed=True, order_response=SimpleNamespace(orderid="sandbox-1", fill_price=fill_price),
    )))
    return AutonomousTrader(
        llm_client=Mock(), openalgo_client=broker,
        config=AgentConfig(symbols=["RELIANCE"], max_position_size=2),
        order_executor=executor,
    )


def open_position(agent: AutonomousTrader) -> None:
    agent.state.active_positions["RELIANCE"] = 100.0
    agent.state.position_details["RELIANCE"] = {
        "entry_price": 100.0, "stop_loss": 95.0, "take_profit": 110.0,
        "action": "BUY", "quantity": 2,
    }


@pytest.mark.asyncio
async def test_entry_records_confirmed_fill_instead_of_decision_quote():
    agent = trader(101.5)
    result = await agent.execute("BUY", "RELIANCE", RiskAssessment(
        allowed=True, position_qty=2, stop_loss=95.0, take_profit=110.0,
    ), entry_price=100.0)
    assert result["data"]["price"] == 101.5
    assert agent.state.position_details["RELIANCE"]["entry_price"] == 101.5
    assert agent.state.active_positions["RELIANCE"] == 101.5


@pytest.mark.asyncio
async def test_monitor_records_confirmed_exit_price_and_pnl():
    agent = trader(89.0)
    open_position(agent)
    await agent.monitor({"symbol": "RELIANCE", **agent.state.position_details["RELIANCE"]})
    assert agent.state.daily_pnl == -22.0
    assert agent.state.closed_trades[0]["exit_price"] == 89.0
    assert agent.state.closed_trades[0]["exit_price_estimated"] is False
    assert not agent.state.active_positions


@pytest.mark.asyncio
async def test_square_off_preserves_confirmed_fill_without_quote_refinement():
    agent = trader(105.0)
    open_position(agent)
    assert await agent._square_off_all()
    assert agent.state.closed_trades[0]["exit_price"] == 105.0
    assert agent.state.closed_trades[0]["pnl"] == 10.0
    assert agent.state.closed_trades[0]["exit_price_estimated"] is False
    agent.broker.quotes.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirmed_square_off_books_daily_loss_once_and_latches_limit():
    agent = trader(89.0)
    open_position(agent)
    agent.state.daily_pnl = 3.0
    agent.config.daily_stop_loss = -15.0
    assert await agent._square_off_all()
    assert agent.state.daily_pnl == -19.0
    assert agent.state.stop_loss_hit
    assert await agent._square_off_all()
    assert agent.state.daily_pnl == -19.0
    assert len(agent.state.closed_trades) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1.0, 0.0, True])
async def test_invalid_fill_metadata_keeps_existing_estimate(invalid):
    agent = trader(invalid)
    result = await agent.execute("BUY", "RELIANCE", RiskAssessment(
        allowed=True, position_qty=2, stop_loss=95.0, take_profit=110.0,
    ), entry_price=100.0)
    assert result["data"]["price"] == 100.0
