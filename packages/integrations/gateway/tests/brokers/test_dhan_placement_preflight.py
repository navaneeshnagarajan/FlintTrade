"""Ordinary Dhan builders must refuse protection they cannot put on the wire."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from flinttrade_gateway.brokers import dhan_mapping as mapping

pytestmark = pytest.mark.unit


def _order(**fields):
    return SimpleNamespace(symbol="INFY", action="SELL", exchange="NSE", product="MIS", pricetype="LIMIT",
                           quantity="2", price="100", trigger_price="0", disclosed_quantity="0", validity="DAY",
                           variety="regular", **fields)


@pytest.mark.parametrize("builder", [mapping.to_place_order_kwargs, mapping.to_amo_order_payload, mapping.to_slice_order_kwargs])
@pytest.mark.parametrize("field,value", [("trailing_jump", "5"), ("stop_loss_price", "105"), ("target_price", "95"),
                                        ("trailing_jump", "1e-9999")])
def test_ordinary_amo_and_slice_builders_refuse_active_unconsumed_protection(builder, field, value):
    with pytest.raises(mapping.DhanMappingError, match=field):
        builder(_order(**{field: value}), "fixture-security")


@pytest.mark.parametrize("field", ["trailing_jump", "stop_loss_price", "target_price"])
@pytest.mark.parametrize("value", [True, False, None, "", "NaN", "Infinity", -1, {}, []])
def test_ordinary_protection_domain_cannot_turn_malformed_values_into_inactive_zero(field, value):
    with pytest.raises(mapping.DhanMappingError, match=field):
        mapping.to_place_order_kwargs(_order(**{field: value}), "fixture-security")


@pytest.mark.parametrize("fields", [{}, {"trailing_jump": 0, "stop_loss_price": "0", "target_price": 0.0},
                                    {"trailing_jump": "0e9", "stop_loss_price": "0.00", "target_price": "0"}])
def test_omitted_and_exact_zero_controls_keep_ordinary_kwargs(fields):
    assert mapping.to_place_order_kwargs(_order(**fields), "fixture-security") == {
        "security_id": "fixture-security", "exchange_segment": "NSE_EQ", "transaction_type": "SELL",
        "quantity": 2, "order_type": "LIMIT", "product_type": "INTRADAY", "price": 100.0, "trigger_price": 0.0,
        "disclosed_quantity": 0, "validity": "DAY",
    }


async def test_actual_dhan_adapter_keeps_builder_defence_before_installed_sdk_transport():
    from flinttrade_core.models import Order
    from flinttrade_gateway.brokers._base import Session
    from flinttrade_gateway.brokers.dhan import DhanAdapter
    from flinttrade_gateway.router import _ROUTER_TOKEN
    from packages.core.core.tests.test_ingress_safety_runtime import DispatchHTTP, DispatchSDK

    wire = DispatchHTTP("ack")
    adapter = DhanAdapter(client_factory=lambda _s: DispatchSDK(wire), security_resolver=lambda _s, _e: "fixture-security")
    order = Order(symbol="INFY", action="SELL", exchange="NSE", product="MIS", pricetype="LIMIT",
                  quantity="2", price="100", trailing_jump="5")
    session = Session("synthetic", 4102444800.0, "synthetic-account", "dhan")
    with pytest.raises(mapping.DhanMappingError, match="trailing_jump"):
        await adapter.place_order(session, order, _router_token=_ROUTER_TOKEN)
    assert wire.calls == []
