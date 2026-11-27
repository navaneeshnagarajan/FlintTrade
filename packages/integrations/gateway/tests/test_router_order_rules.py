"""The router refuses rule-blocked writes before any adapter call.

Every place and modify, whatever its caller (ticket, Scalper, Automate, AI or
webhook), reaches an adapter only through BrokerRouter. These tests use a fake
adapter; no broker is contacted.
"""

from __future__ import annotations

import pytest

from flinttrade_core.exceptions import BrokerError
from flinttrade_core.models import Action, Exchange, Order, Position, PriceType, Product
from flinttrade_core.order_rules import OrderBudgetExceeded, OrderRuleRefused
from flinttrade_engine.safety import SafetyContext, set_safety_gate_secret
from flinttrade_gateway.router import BrokerRouter

from .test_router import SECRET, _FakeAdapter, _request_ctx, _session

NIFTY_CE = "NIFTY25NOV2624000CE"


@pytest.fixture(autouse=True)
def _bind_secret() -> None:
    set_safety_gate_secret(SECRET)


def _router(adapter: _FakeAdapter, adapter_id: str, backend_lease_factory) -> BrokerRouter:
    return BrokerRouter(
        {adapter_id: adapter},
        lambda _ctx, _aid, _acct: _session(),
        backend_lease_proof=backend_lease_factory(),
    )


def _mint(order, adapter_id: str, backend_lease_factory) -> SafetyContext:
    return SafetyContext.mint(
        order,
        mode="live",
        user_jti="jti-1",
        adapter_id=adapter_id,
        account_id="acct-1",
        actor_type="human",
        backend_lease_proof=backend_lease_factory(),
    )


def _order(symbol: str, exchange: Exchange, pricetype: PriceType, **extra: str) -> Order:
    return Order(
        symbol=symbol,
        action=Action.BUY,
        exchange=exchange,
        product=Product.MIS,
        pricetype=pricetype,
        quantity="75",
        **extra,
    )


@pytest.mark.parametrize("adapter_id", ["dhan", "kotakneo", "upstox", "groww", "indmoney", "deltaexchange"])
@pytest.mark.parametrize(
    ("pricetype", "extra"),
    [(PriceType.MARKET, {}), (PriceType.SL_M, {"trigger_price": "80"})],
)
async def test_no_market_or_stop_market_option_order_reaches_any_adapter(
    adapter_id: str, pricetype: PriceType, extra: dict, *, backend_lease_factory
) -> None:
    adapter = _FakeAdapter()
    router = _router(adapter, adapter_id, backend_lease_factory)
    order = _order(NIFTY_CE, Exchange.NFO, pricetype, **extra)
    with pytest.raises(OrderRuleRefused) as excinfo:
        await router.place_order(
            _request_ctx(),
            adapter_id=adapter_id,
            account_id="acct-1",
            order=order,
            safety_ctx=_mint(order, adapter_id, backend_lease_factory),
        )
    assert adapter.placed == []
    assert excinfo.value.results[0].level == "block"


async def test_out_of_range_bse_stop_limit_never_reaches_the_adapter(*, backend_lease_factory) -> None:
    adapter = _FakeAdapter()
    router = _router(adapter, "dhan", backend_lease_factory)
    order = _order("SENSEX27NOV2680000CE", Exchange.BFO, PriceType.SL, price="39.95", trigger_price="50")
    with pytest.raises(OrderRuleRefused, match="Stop-loss limit must be within ₹10 of trigger"):
        await router.place_order(
            _request_ctx(),
            adapter_id="dhan",
            account_id="acct-1",
            order=order,
            safety_ctx=_mint(order, "dhan", backend_lease_factory),
        )
    assert adapter.placed == []


async def test_option_limit_order_still_dispatches(*, backend_lease_factory) -> None:
    adapter = _FakeAdapter()
    router = _router(adapter, "dhan", backend_lease_factory)
    order = _order(NIFTY_CE, Exchange.NFO, PriceType.LIMIT, price="100")
    result = await router.place_order(
        _request_ctx(),
        adapter_id="dhan",
        account_id="acct-1",
        order=order,
        safety_ctx=_mint(order, "dhan", backend_lease_factory),
    )
    assert result == "BROKER-OID-1"
    assert adapter.placed == [order]


async def test_dhan_order_budget_refuses_the_eleventh_order_in_a_second(*, backend_lease_factory, monkeypatch) -> None:
    import flinttrade_gateway.router as router_module

    monkeypatch.setattr(router_module.time, "monotonic", lambda: 1000.0)
    adapter = _FakeAdapter()
    router = _router(adapter, "dhan", backend_lease_factory)
    for _ in range(10):
        order = _order("RELIANCE", Exchange.NSE, PriceType.LIMIT, price="100")
        await router.place_order(
            _request_ctx(),
            adapter_id="dhan",
            account_id="acct-1",
            order=order,
            safety_ctx=_mint(order, "dhan", backend_lease_factory),
        )
    order = _order("RELIANCE", Exchange.NSE, PriceType.LIMIT, price="100")
    with pytest.raises(OrderBudgetExceeded, match=r"Wait 1 second\. The limit is 10 orders per second\."):
        await router.place_order(
            _request_ctx(),
            adapter_id="dhan",
            account_id="acct-1",
            order=order,
            safety_ctx=_mint(order, "dhan", backend_lease_factory),
        )
    assert len(adapter.placed) == 10


class _PositionsAdapter(_FakeAdapter):
    def __init__(self, positions: list | Exception) -> None:
        super().__init__()
        self._positions = positions

    async def positions(self, session):
        if isinstance(self._positions, Exception):
            raise self._positions
        return self._positions


def _exit(quantity: str, action: Action = Action.SELL) -> Order:
    return Order(
        symbol=NIFTY_CE,
        action=action,
        exchange=Exchange.NFO,
        product=Product.NRML,
        pricetype=PriceType.LIMIT,
        price="40",
        quantity=quantity,
        exit_only=True,
    )


def _held(quantity: str) -> list[Position]:
    return [Position(symbol=NIFTY_CE, exchange="NFO", product="NRML", quantity=quantity)]


async def _place_exit(adapter, order, backend_lease_factory, adapter_id: str = "dhan"):
    router = _router(adapter, adapter_id, backend_lease_factory)
    return await router.place_order(
        _request_ctx(),
        adapter_id=adapter_id,
        account_id="acct-1",
        order=order,
        safety_ctx=_mint(order, adapter_id, backend_lease_factory),
    )


@pytest.mark.parametrize("adapter_id", ["dhan", "kotakneo", "upstox"])
async def test_exit_quantity_above_the_live_position_is_cut_before_dispatch(
    adapter_id: str, *, backend_lease_factory
) -> None:
    adapter = _PositionsAdapter(_held("75"))
    await _place_exit(adapter, _exit("150"), backend_lease_factory, adapter_id)
    assert [order.quantity for order in adapter.placed] == ["75"]


async def test_exit_within_the_position_dispatches_unchanged(*, backend_lease_factory) -> None:
    adapter = _PositionsAdapter(_held("-150"))
    order = _exit("75", Action.BUY)
    await _place_exit(adapter, order, backend_lease_factory)
    assert adapter.placed == [order]


@pytest.mark.parametrize("held", [[], _held("0"), _held("75")])
async def test_exit_on_a_closed_or_same_side_position_never_reaches_the_adapter(
    held: list, *, backend_lease_factory
) -> None:
    adapter = _PositionsAdapter(held)
    with pytest.raises(OrderRuleRefused, match="Position is closed. Order not sent."):
        await _place_exit(adapter, _exit("75", Action.BUY), backend_lease_factory)
    assert adapter.placed == []


async def test_exit_is_refused_when_positions_cannot_be_read(*, backend_lease_factory) -> None:
    adapter = _PositionsAdapter(RuntimeError("book down"))
    with pytest.raises(BrokerError, match="Open position could not be read"):
        await _place_exit(adapter, _exit("75"), backend_lease_factory)
    assert adapter.placed == []


async def test_an_ordinary_order_does_not_read_positions(*, backend_lease_factory) -> None:
    adapter = _PositionsAdapter(RuntimeError("not called"))
    order = _order(NIFTY_CE, Exchange.NFO, PriceType.LIMIT, price="100")
    await _place_exit(adapter, order, backend_lease_factory)
    assert adapter.placed == [order]
