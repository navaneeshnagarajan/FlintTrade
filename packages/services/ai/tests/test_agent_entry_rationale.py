"""Only an operator's configured rationale accompanies autonomous entry orders."""

from types import SimpleNamespace

import pytest

from flinttrade_ai.autonomous_agent import AgentConfig, AutonomousTrader, RiskAssessment
from flinttrade_core.models import Order

pytestmark = pytest.mark.unit


def test_entry_rationale_is_optional_and_empty_by_default():
    config = AgentConfig(symbols=["RELIANCE"])
    assert config.entry_rationale == ""
    trader = AutonomousTrader(llm_client=None, broker_client=None, config=config)
    assert trader._build_market_order("RELIANCE", "BUY", 1).admission_note == ""


def test_typed_order_preserves_configured_operator_rationale_exactly():
    rationale = "Operator plan: test the opening-range breakout.\nUse the configured stop; ₹ risk stays bounded."
    trader = AutonomousTrader(
        llm_client=None, broker_client=None,
        config=AgentConfig(symbols=["RELIANCE"], entry_rationale=rationale),
    )
    order = trader._build_market_order("RELIANCE", "BUY", 25)
    assert isinstance(order, Order)
    assert order.admission_note == rationale
    assert order.quantity == "25"


@pytest.mark.asyncio
async def test_operator_rationale_does_not_override_entry_admission_refusal():
    submitted = []

    async def route_order(order):
        submitted.append(order)
        return SimpleNamespace(passed=False, error="Laya requires a clamp")

    trader = AutonomousTrader(
        llm_client=None, broker_client=None,
        config=AgentConfig(symbols=["RELIANCE"], entry_rationale="Operator-authored session plan"),
        order_executor=SimpleNamespace(route_order=route_order),
    )
    result = await trader.execute("BUY", "RELIANCE", RiskAssessment(position_qty=25), entry_price=100)
    assert len(submitted) == 1
    assert submitted[0].admission_note == "Operator-authored session plan"
    assert submitted[0].quantity == "25"
    assert result == {"status": "error", "error": "Laya requires a clamp"}
    assert trader.state.active_positions == {}
    assert trader.state.trade_counts["RELIANCE"] == 0
