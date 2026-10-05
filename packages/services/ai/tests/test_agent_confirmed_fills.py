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
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1.0, 0.0, True, None, "105.0"])
async def test_invalid_fill_metadata_keeps_existing_estimate(invalid):
    agent = trader(invalid)
    result = await agent.execute("BUY", "RELIANCE", RiskAssessment(
        allowed=True, position_qty=2, stop_loss=95.0, take_profit=110.0,
    ), entry_price=100.0)
    assert result["data"]["price"] == 100.0
    assert agent.state.position_details["RELIANCE"]["stop_loss"] == 95.0
    assert agent.state.position_details["RELIANCE"]["take_profit"] == 110.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action, stop_loss, take_profit, fill_price, expected_stop, expected_target",
    [
        ("BUY", 98.0, 104.0, 105.0, 102.9, 109.2),
        ("SELL", 102.0, 96.0, 95.0, 96.9, 91.2),
        ("BUY", 98.0, 104.0, 95.0, 93.1, 98.8),
        ("SELL", 102.0, 96.0, 105.0, 107.1, 100.8),
        # Respect the assessed percentages, including tighter custom risk,
        # rather than replacing them with the agent configuration defaults.
        ("BUY", 99.0, 103.0, 105.0, 103.95, 108.15),
        ("SELL", 101.0, 97.0, 95.0, 95.95, 92.15),
        ("BUY", 98.0, 104.0, 105.12345, 103.020981, 109.328388),
        ("SELL", 102.0, 96.0, 95.12345, 97.025919, 91.318512),
    ],
)
async def test_confirmed_entry_rebases_assessed_protection_to_fill(
    action, stop_loss, take_profit, fill_price, expected_stop, expected_target,
):
    agent = trader(fill_price)
    risk = RiskAssessment(
        allowed=True, position_qty=2, stop_loss=stop_loss, take_profit=take_profit,
    )

    result = await agent.execute(action, "RELIANCE", risk, entry_price=100.0)

    assert result["status"] == "success"
    details = agent.state.position_details["RELIANCE"]
    assert details["entry_price"] == fill_price
    assert details["stop_loss"] == pytest.approx(expected_stop)
    assert details["take_profit"] == pytest.approx(expected_target)
    assert abs(fill_price - details["stop_loss"]) / fill_price == pytest.approx(
        abs(100.0 - stop_loss) / 100.0, rel=1e-12,
    )
    assert abs(fill_price - details["take_profit"]) / fill_price == pytest.approx(
        abs(100.0 - take_profit) / 100.0, rel=1e-12,
    )
    assert risk.stop_loss == stop_loss
    assert risk.take_profit == take_profit

    # At the confirmed entry there is no profit or loss. Quote-anchored
    # thresholds used to trigger an immediate, incorrect protective exit.
    agent.broker.quotes.return_value = {"ltp": fill_price}
    await agent.monitor({"symbol": "RELIANCE", **details})
    assert agent.state.active_positions == {"RELIANCE": fill_price}
    assert agent.state.closed_trades == []
    assert agent.state.daily_pnl == 0.0


@pytest.mark.asyncio
@pytest.mark.parametrize("entry_price", [0.0, -1.0, float("nan"), float("inf"), True])
async def test_confirmed_entry_without_valid_decision_quote_keeps_absolute_protection(entry_price):
    agent = trader(105.0)
    risk = RiskAssessment(allowed=True, position_qty=2, stop_loss=98.0, take_profit=104.0)

    result = await agent.execute("BUY", "RELIANCE", risk, entry_price=entry_price)

    assert result["data"]["price"] == 105.0
    details = agent.state.position_details["RELIANCE"]
    assert details["entry_price"] == 105.0
    assert details["stop_loss"] == 98.0
    assert details["take_profit"] == 104.0


@pytest.mark.asyncio
@pytest.mark.parametrize("stop_loss, take_profit", [(0.0, 104.0), (98.0, 0.0), (0.0, 0.0)])
async def test_confirmed_entry_does_not_invent_unset_protection(stop_loss, take_profit):
    agent = trader(105.0)
    risk = RiskAssessment(allowed=True, position_qty=2, stop_loss=stop_loss, take_profit=take_profit)

    await agent.execute("BUY", "RELIANCE", risk, entry_price=100.0)

    details = agent.state.position_details["RELIANCE"]
    assert details["stop_loss"] == pytest.approx(102.9 if stop_loss else 0.0)
    assert details["take_profit"] == pytest.approx(109.2 if take_profit else 0.0)


@pytest.mark.asyncio
async def test_legacy_response_without_fill_keeps_quote_and_assessed_protection():
    agent = trader(105.0)
    del agent.order_executor.route_order.return_value.order_response.fill_price
    risk = RiskAssessment(allowed=True, position_qty=2, stop_loss=98.0, take_profit=104.0)

    result = await agent.execute("BUY", "RELIANCE", risk, entry_price=100.0)

    assert result["data"]["price"] == 100.0
    assert agent.state.position_details["RELIANCE"] == {
        "entry_price": 100.0, "stop_loss": 98.0, "take_profit": 104.0,
        "action": "BUY", "quantity": 2,
    }
