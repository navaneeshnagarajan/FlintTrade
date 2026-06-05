"""Unit tests for the FlintTrade <-> Upstox mapping layer."""

from __future__ import annotations

import pytest

from flinttrade_core.models import Order
from flinttrade_gateway.brokers.upstox_mapping import (
    UpstoxMappingError,
    extract_order_id,
    from_upstox_funds,
    from_upstox_order,
    from_upstox_position,
    to_modify_order_params,
    to_place_order_params,
)

pytestmark = pytest.mark.unit


def test_place_order_market_buy():
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS", quantity="10")
    p = to_place_order_params(order, "NSE_EQ|INE002A01018", tag="ALGO1")
    assert p["instrument_token"] == "NSE_EQ|INE002A01018"
    assert p["transaction_type"] == "BUY"
    assert p["order_type"] == "MARKET"
    assert p["product"] == "I"   # MIS → Intraday
    assert p["quantity"] == 10
    assert p["tag"] == "ALGO1"


def test_place_order_sl_m_and_fno_product():
    order = Order(symbol="NIFTY", action="SELL", exchange="NFO", pricetype="SL-M", product="NRML", quantity="75", trigger_price="120.5")
    p = to_place_order_params(order, "NSE_FO|12345")
    assert p["order_type"] == "SL-M"
    assert p["product"] == "D"    # NRML → Delivery/carry-forward
    assert p["trigger_price"] == 120.5


def test_place_order_unmapped_product_raises():
    order = Order(symbol="X", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS")
    object.__setattr__(order, "product", "ZZZ")  # force an invalid product
    with pytest.raises(UpstoxMappingError, match="product"):
        to_place_order_params(order, "NSE_EQ|X")


def test_modify_order_params():
    p = to_modify_order_params("OID1", {"pricetype": "LIMIT", "quantity": 50, "price": 101.25})
    assert p["order_id"] == "OID1" and p["order_type"] == "LIMIT" and p["quantity"] == 50


def test_extract_order_id_list_and_singular():
    assert extract_order_id({"status": "success", "data": {"order_ids": ["112233"]}}) == "112233"
    assert extract_order_id({"data": {"order_id": "445566"}}) == "445566"
    with pytest.raises(UpstoxMappingError):
        extract_order_id({"data": {}})


def test_from_upstox_order_position_funds():
    order = from_upstox_order({
        "order_id": "9", "status": "open", "trading_symbol": "TCS", "instrument_token": "NSE_EQ|INE467B01029",
        "transaction_type": "BUY", "order_type": "LIMIT", "product": "D", "quantity": 5, "price": 3500,
    })
    assert order["orderid"] == "9" and order["exchange"] == "NSE" and order["product"] == "CNC"

    pos = from_upstox_position({
        "trading_symbol": "INFY", "instrument_token": "NSE_EQ|INE009A01021", "product": "I",
        "quantity": 20, "average_price": 1500, "last_price": 1520, "pnl": 400,
    })
    assert pos["symbol"] == "INFY" and pos["exchange"] == "NSE" and pos["product"] == "MIS" and pos["pnl"] == "400"

    funds = from_upstox_funds({"status": "success", "data": {"equity": {"available_margin": 50000, "used_margin": 12000}}})
    assert funds["available_balance"] == "50000" and funds["used_margin"] == "12000"
