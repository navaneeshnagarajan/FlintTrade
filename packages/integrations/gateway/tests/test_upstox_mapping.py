"""Unit tests for the FlintTrade <-> Upstox mapping layer."""

from __future__ import annotations

import pytest

from flinttrade_core.models import Order
from flinttrade_gateway.brokers.upstox_mapping import (
    UpstoxMappingError,
    extract_order_id,
    from_upstox_candles,
    from_upstox_funds,
    from_upstox_margin,
    from_upstox_order,
    from_upstox_position,
    from_upstox_quote,
    to_history_params,
    to_margin_instrument,
    to_modify_order_params,
    to_option_chain_dict,
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


def test_margin_instrument_and_parse():
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="MIS", quantity="10", price="2900")
    inst = to_margin_instrument(order, "NSE_EQ|INE002A01018")
    assert inst["instrument_key"] == "NSE_EQ|INE002A01018" and inst["product"] == "I"
    assert inst["transaction_type"] == "BUY" and inst["quantity"] == 10
    margin = from_upstox_margin({"status": "success", "data": {"required_margin": 14500, "final_margin": 14000}})
    assert margin["required_margin"] == "14500" and margin["final_margin"] == "14000"
    # Upstox's margin response carries no balance — documented as 0, merged from funds().
    assert margin["available_balance"] == "0"


def test_place_order_advanced_variety_refused():
    # Upstox must refuse a bracket/cover/iceberg variety, not silently place a
    # plain order that drops the protective legs.
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="MIS", quantity="5", price="2900", variety="bracket", stop_loss_price="2870")
    with pytest.raises(UpstoxMappingError, match="variety"):
        to_place_order_params(order, "NSE_EQ|X")


def test_place_order_unmapped_product_raises():
    order = Order(symbol="X", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS")
    object.__setattr__(order, "product", "ZZZ")  # force an invalid product
    with pytest.raises(UpstoxMappingError, match="product"):
        to_place_order_params(order, "NSE_EQ|X")


def test_capabilities_do_not_advertise_a_variety_the_mapping_refuses():
    # Capability honesty: Upstox must NOT advertise an advanced order type as
    # native while the adapter refuses to place it (the recommendation engine
    # scores on these flags). Cover was retired by Upstox, so it stays False
    # AND the regular-order mapping refuses it.
    from flinttrade_gateway.brokers.upstox import UPSTOX_CAPABILITIES

    assert UPSTOX_CAPABILITIES.cover_order_native is False
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="MIS", quantity="5", price="2900", variety="cover")
    with pytest.raises(UpstoxMappingError, match="variety"):
        to_place_order_params(order, "NSE_EQ|X")


def test_capabilities_advertise_wired_varieties():
    # The other half of capability honesty: GTT (v3 /order/gtt/*) and sliced
    # orders (v3 slice=true, our iceberg) ARE dispatched by the gated
    # place_order, so the adapter must advertise them (under-advertising would
    # make the recommendation engine under-credit Upstox).
    from flinttrade_gateway.brokers.upstox import UPSTOX_CAPABILITIES

    assert UPSTOX_CAPABILITIES.gtt_native is True
    assert UPSTOX_CAPABILITIES.iceberg_native is True


def test_capabilities_do_not_advertise_cover_or_bracket_order_type():
    # cover_order_native is False and the mapping refuses variety "cover", so the
    # order_types flag set must NOT advertise CO/BO (routers key off this set —
    # advertising it would contradict the refusal).
    from flinttrade_gateway.brokers.upstox import UPSTOX_CAPABILITIES
    from flinttrade_gateway.capabilities import OrderTypes

    assert not (UPSTOX_CAPABILITIES.order_types & OrderTypes.CO)
    assert not (UPSTOX_CAPABILITIES.order_types & OrderTypes.BO)
    # The wired varieties stay advertised.
    assert UPSTOX_CAPABILITIES.order_types & OrderTypes.GTT
    assert UPSTOX_CAPABILITIES.order_types & OrderTypes.ICEBERG


def test_capabilities_intraday_history_metadata_is_honest():
    # Upstox 1-minute intraday history reaches only ~1 month (HistoryApi.md); the
    # 365-day figure was the 30-minute-only bound. The per-request candle cap was
    # fabricated, so it is 0 (unknown), not 2000.
    from flinttrade_gateway.brokers.upstox import UPSTOX_CAPABILITIES

    assert UPSTOX_CAPABILITIES.historical_max_lookback_days_intraday == 31
    assert UPSTOX_CAPABILITIES.historical_max_candles_per_request == 0


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


def test_to_history_params_minutes_named_and_default():
    p = to_history_params({"interval": "15m", "from_date": "2025-01-01", "to_date": "2025-01-04", "instrument_key": "NSE_EQ|X"})
    assert p["unit"] == "minutes" and p["interval"] == "15"
    assert p["instrument_key"] == "NSE_EQ|X" and p["from_date"] == "2025-01-01"
    assert to_history_params({"interval": "day"})["unit"] == "days"
    assert to_history_params({"interval": "1h"})["unit"] == "hours"
    assert to_history_params({})["unit"] == "days"  # default 1d


def test_from_upstox_candles_array_order():
    cd = from_upstox_candles("RELIANCE", "NSE", "1d", {"status": "success", "data": {"candles": [
        ["2025-01-02T00:00:00+05:30", 100.0, 110.0, 95.0, 105.0, 1500, 0],
        ["bad-row"],  # too short → skipped
    ]}})
    assert cd["symbol"] == "RELIANCE" and len(cd["bars"]) == 1
    bar = cd["bars"][0]
    assert bar["open"] == 100.0 and bar["high"] == 110.0 and bar["low"] == 95.0 and bar["close"] == 105.0
    assert bar["volume"] == 1500


def test_from_upstox_quote_uses_record_and_depth():
    q = from_upstox_quote({
        "symbol": "RELIANCE", "instrument_token": "NSE_EQ|INE002A01018", "last_price": 2905.5,
        "volume": 120000, "oi": 0,
        "ohlc": {"open": 2900, "high": 2920, "low": 2890, "close": 2899},
        "depth": {"buy": [{"price": 2905.0, "quantity": 10}], "sell": [{"price": 2906.0, "quantity": 8}]},
    })
    assert q["symbol"] == "RELIANCE" and q["exchange"] == "NSE"
    assert q["ltp"] == 2905.5 and q["bid"] == 2905.0 and q["ask"] == 2906.0
    assert q["open"] == 2900.0 and q["volume"] == 120000


def test_to_option_chain_dict_flattens_legs_and_greeks():
    oc = to_option_chain_dict("NIFTY", "NSE_INDEX", {"status": "success", "data": [
        {
            "strike_price": 24000, "underlying_spot_price": 24050,
            "call_options": {
                "market_data": {"ltp": 120.5, "oi": 30000, "volume": 5000, "bid_price": 120.0, "ask_price": 121.0},
                "option_greeks": {"iv": 13.2, "delta": 0.55, "gamma": 0.002, "theta": -8.1, "vega": 6.4},
            },
            "put_options": {
                "market_data": {"ltp": 95.0, "oi": 28000, "volume": 4200, "bid_price": 94.5, "ask_price": 95.5},
                "option_greeks": {"iv": 12.8, "delta": -0.45, "gamma": 0.002, "theta": -7.5, "vega": 6.1},
            },
        },
    ]})
    assert oc["underlying"] == "NIFTY" and len(oc["strikes"]) == 1
    s = oc["strikes"][0]
    assert s["strike_price"] == 24000.0
    assert s["ce_ltp"] == 120.5 and s["ce_oi"] == 30000 and s["ce_iv"] == 13.2 and s["ce_delta"] == 0.55
    assert s["pe_ltp"] == 95.0 and s["pe_delta"] == -0.45 and s["pe_bid"] == 94.5
