"""BrokerAdapter ABC enforcement (broker-adapter-contract §5.1).

Every concrete adapter MUST implement the complete async ``BrokerAdapter``
surface — no abstract method left over — so the router can rely on the full
contract. The parametrize list grows as each broker's §9.5 wave lands; today
only DhanAdapter ships, so it is the sole parameter. (upstox / kotakneo /
indmoney / openalgo adapters join here as they are built.)
"""

from __future__ import annotations

import inspect

import pytest

from flinttrade_gateway.brokers import dhan
from flinttrade_gateway.brokers._base import BrokerAdapter

ADAPTERS = [
    (dhan.DhanAdapter, "dhan"),
    # (upstox.UpstoxAdapter, "upstox"),       # §9.5 wave — not yet built
    # (kotakneo.KotakNeoAdapter, "kotakneo"), # §9.5 wave — not yet built
    # (indmoney.IndMoneyAdapter, "indmoney"), # §9.5 wave — not yet built
    # (openalgo.OpenAlgoAdapter, "openalgo"), # §9.5 wave — not yet built
]

# The full abstract surface mandated by contract §5.
EXPECTED_ABSTRACT = {
    "broker_id",
    "capabilities",
    "login",
    "refresh",
    "logout",
    "place_order",
    "modify_order",
    "cancel_order",
    "order_book",
    "trade_book",
    "positions",
    "holdings",
    "funds",
    "quotes",
    "historical",
    "option_chain",
    "stream",
    "subscribe",
    "unsubscribe",
    "reconcile",
}


def test_abc_declares_full_contract_surface() -> None:
    """The ABC itself must declare every §5 method as abstract."""
    declared = {
        name
        for name in dir(BrokerAdapter)
        if getattr(getattr(BrokerAdapter, name, None), "__isabstractmethod__", False)
    }
    assert declared == EXPECTED_ABSTRACT


@pytest.mark.parametrize("cls,expected_id", ADAPTERS)
def test_concrete_adapter_can_instantiate(cls, expected_id) -> None:
    """A fully-implemented adapter has no leftover abstract methods."""
    assert cls.__abstractmethods__ == frozenset(), (
        f"{cls.__name__} leaves abstract: {sorted(cls.__abstractmethods__)}"
    )
    instance = cls()
    assert instance.broker_id == expected_id
    for name in EXPECTED_ABSTRACT:
        assert hasattr(instance, name), f"{cls.__name__} missing {name}"


@pytest.mark.parametrize("cls,_", ADAPTERS)
def test_capabilities_advertises_realistic_values(cls, _) -> None:
    caps = cls().capabilities
    assert caps.segments, "must advertise at least one segment"
    assert caps.order_types, "must advertise at least one order type"


@pytest.mark.parametrize("cls,_", ADAPTERS)
def test_trading_and_data_methods_are_coroutines(cls, _) -> None:
    """Contract §5: every trading/data method is async (the S9 sync→async fix)."""
    instance = cls()
    async_methods = EXPECTED_ABSTRACT - {"broker_id", "capabilities", "stream"}
    for name in async_methods:
        assert inspect.iscoroutinefunction(getattr(instance, name)), (
            f"{cls.__name__}.{name} must be async"
        )
