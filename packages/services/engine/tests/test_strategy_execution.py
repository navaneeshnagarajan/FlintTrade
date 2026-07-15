"""Regression tests for scheduled-strategy execution contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from flinttrade_core.models import Order
from flinttrade_engine.request_context import RequestContext
from flinttrade_engine.safety import SafetyConfig, SafetySystem, set_safety_gate_secret
from flinttrade_engine.strategy_execution import GatedStrategyDispatcher
from flinttrade_gateway.brokers._base import ROUTER_TOKEN, Session
from flinttrade_gateway.router import BrokerRouter


def _passing_safety() -> SafetySystem:
    return SafetySystem(SafetyConfig(check_market_hours=False))


class _TokenCheckingAdapter:
    def __init__(self) -> None:
        self.orders: list[Order] = []

    async def place_order(self, _session, order, *, _router_token=None):
        assert _router_token is ROUTER_TOKEN
        self.orders.append(order)
        return f"order-{len(self.orders)}"


async def _portfolio_state(_order: Order, _reservations: tuple[object, ...]):
    return SimpleNamespace(
        positions=[],
        used_margin=0.0,
        total_balance=100000.0,
        daily_pnl=0.0,
        starting_capital=100000.0,
        net_delta=0.0,
        net_vega=0.0,
        reconciled_reservation_ids=(),
        ltp_for=lambda _candidate: None,
        admission_for=lambda _index: SimpleNamespace(
            positions=[],
            used_margin=0.0,
            net_delta=0.0,
            net_vega=0.0,
        ),
    )


@pytest.mark.asyncio
async def test_live_dispatch_mints_a_fresh_safety_context_for_every_order() -> None:
    set_safety_gate_secret(b"strategy-execution-test-secret-32")
    consumed_gate_ids: list[str] = []
    adapter = _TokenCheckingAdapter()

    def session_provider(_ctx, adapter_id: str, account_id: str) -> Session:
        return Session(
            access_token="token",
            expires_at=datetime.now(tz=timezone.utc).timestamp() + 60,
            account_id=account_id,
            adapter_id=adapter_id,
        )

    def consume_gate(gate_id: str) -> bool:
        consumed_gate_ids.append(gate_id)
        return True

    router = BrokerRouter(
        {"openalgo": adapter},
        session_provider,
        consume_gate=consume_gate,
    )
    request_ctx = RequestContext(
        jti="strategy-jti",
        actor_type="agent",
        actor_id="strategy:ema",
        mode="live",
        selector="openalgo:default",
    )
    dispatcher = GatedStrategyDispatcher(
        safety=_passing_safety(),
        request_context_provider=lambda: request_ctx,
        router_provider=lambda: router,
        adapter_id="openalgo",
        account_id="default",
        portfolio_state_provider=_portfolio_state,
    )
    order = Order(symbol="RELIANCE", action="BUY", quantity="1")

    assert await dispatcher.dispatch_order(order) == "order-1"
    assert await dispatcher.dispatch_order(order) == "order-2"

    assert adapter.orders == [order, order]
    assert len(consumed_gate_ids) == 2
    assert consumed_gate_ids[0] != consumed_gate_ids[1]


@pytest.mark.asyncio
async def test_live_dispatch_without_selector_fails_with_typed_runtime_error() -> None:
    request_ctx = RequestContext(
        jti="missing-selector",
        actor_type="agent",
        actor_id="strategy:test",
        mode="live",
    )
    dispatcher = GatedStrategyDispatcher(
        safety=_passing_safety(),
        request_context_provider=lambda: request_ctx,
        router_provider=MagicMock(),
        adapter_id="openalgo",
        account_id="default",
        portfolio_state_provider=_portfolio_state,
    )

    with pytest.raises(RuntimeError, match="selector"):
        await dispatcher.dispatch_order(Order(symbol="RELIANCE", action="BUY", quantity="1"))


@pytest.mark.asyncio
async def test_live_dispatch_checks_prospective_greeks_before_router() -> None:
    class _BlockingSafety:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def check_order(self, _order: Order, **kwargs: object) -> list[object]:
            self.calls.append(kwargs)
            return [SimpleNamespace(
                passed=False,
                layer="L3_PORTFOLIO",
                reason="prospective delta exceeds limit",
            )]

    async def _prospective_state(_order: Order, _reservations: tuple[object, ...]) -> object:
        return SimpleNamespace(
            positions=[],
            used_margin=0.0,
            total_balance=100000.0,
            daily_pnl=0.0,
            starting_capital=100000.0,
            net_delta=0.0,
            net_vega=0.0,
            reconciled_reservation_ids=(),
            ltp_for=lambda _candidate: None,
            admission_for=lambda _index: SimpleNamespace(
                positions=[],
                used_margin=0.0,
                net_delta=750.0,
                net_vega=12000.0,
            ),
        )

    request_ctx = RequestContext(
        jti="strategy-greeks",
        actor_type="agent",
        actor_id="strategy:greeks",
        mode="live",
        selector="openalgo:default",
    )
    recorder = _BlockingSafety()
    safety = _passing_safety()
    safety.check_order = recorder.check_order
    dispatcher = GatedStrategyDispatcher(
        safety=safety,
        request_context_provider=lambda: request_ctx,
        router_provider=MagicMock(),
        adapter_id="openalgo",
        account_id="default",
        portfolio_state_provider=_prospective_state,
    )

    with pytest.raises(RuntimeError, match="L3_PORTFOLIO"):
        await dispatcher.dispatch_order(Order(symbol="RELIANCE", action="BUY", quantity="1"))

    assert recorder.calls[0]["net_delta"] == 750.0
    assert recorder.calls[0]["net_vega"] == 12000.0


def test_live_dispatch_contract_rejects_arbitrary_dispatcher() -> None:
    from flinttrade_engine.strategy_execution import StrategyExecutionContract

    with pytest.raises(ValueError, match="canonical gated dispatcher"):
        StrategyExecutionContract.live(MagicMock())


def test_live_dispatch_contract_rejects_dispatcher_subclasses() -> None:
    from flinttrade_engine.strategy_execution import StrategyExecutionContract

    class LookalikeDispatcher(GatedStrategyDispatcher):
        pass

    with pytest.raises(ValueError, match="canonical gated dispatcher"):
        StrategyExecutionContract.live(object.__new__(LookalikeDispatcher))
