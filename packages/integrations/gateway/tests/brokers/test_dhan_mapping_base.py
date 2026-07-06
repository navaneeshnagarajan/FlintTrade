"""Unit tests for the FlintTrade <-> Dhan mapping layer."""

from __future__ import annotations

import struct

import pytest

from flinttrade_core.models import Order
from flinttrade_gateway.brokers.dhan_mapping import (
    DhanMappingError,
    decode_dhan_tick,
    extract_order_id,
    from_dhan_funds,
    from_dhan_order,
    from_dhan_position,
    from_dhan_quote,
    from_dhan_trade,
    interval_to_dhan,
    quote_from_feed,
    to_candles_dict,
    from_dhan_expiry_list,
    from_dhan_margin,
    from_dhan_statement_list,
    to_amo_order_payload,
    to_margin_kwargs,
    to_forever_kwargs,
    to_modify_order_kwargs,
    to_option_chain_dict,
    to_place_order_kwargs,
    to_slice_order_kwargs,
    to_super_order_kwargs,
    unwrap,
)

pytestmark = pytest.mark.unit


def test_place_order_market_buy():
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS", quantity="10")
    kw = to_place_order_kwargs(order, "11536", tag="ALGO1")
    assert kw["security_id"] == "11536"
    assert kw["exchange_segment"] == "NSE_EQ"
    assert kw["transaction_type"] == "BUY"
    assert kw["order_type"] == "MARKET"
    assert kw["product_type"] == "INTRADAY"
    assert kw["quantity"] == 10
    assert kw["tag"] == "ALGO1"


def test_place_order_sl_m_and_fno():
    order = Order(
        symbol="NIFTY25JUN24000CE", action="SELL", exchange="NFO",
        pricetype="SL-M", product="NRML", quantity="75", trigger_price="120.5",
    )
    kw = to_place_order_kwargs(order, "49081")
    assert kw["exchange_segment"] == "NSE_FNO"
    assert kw["transaction_type"] == "SELL"
    assert kw["order_type"] == "STOP_LOSS_MARKET"
    assert kw["product_type"] == "MARGIN"
    assert kw["trigger_price"] == 120.5


def test_place_order_unmapped_exchange_raises():
    order = Order(symbol="X", action="BUY", exchange="NCDEX", pricetype="MARKET", product="MIS")
    with pytest.raises(DhanMappingError, match="segment"):
        to_place_order_kwargs(order, "1")


def test_place_order_maps_ioc_validity():
    """Regression: order.validity must reach the place_order kwargs, otherwise an
    IOC order silently rests as the SDK default DAY."""
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="MIS", quantity="10", price="2900", validity="IOC")
    kw = to_place_order_kwargs(order, "11536")
    assert kw["validity"] == "IOC"


def test_place_order_validity_defaults_to_day_and_rejects_unknown():
    # None keeps the broker default (DAY).
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="MARKET",
                  product="MIS", quantity="10")
    assert to_place_order_kwargs(order, "11536")["validity"] == "DAY"
    # GTC/GTD are not valid on the Dhan place surface (DAY/IOC only) — fail closed.
    bad = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="MARKET",
                product="MIS", quantity="10", validity="GTC")
    with pytest.raises(DhanMappingError, match="DAY or IOC"):
        to_place_order_kwargs(bad, "11536")


def test_amo_order_payload_sets_after_market_and_time():
    """An ``amo`` order builds a /orders REST payload with afterMarketOrder=True
    + an amoTime window (orders.md); camelCase field names, amoTime carried on
    the wire (the SDK drops it, so we POST the payload directly)."""
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="CNC", quantity="10", price="2900", variety="amo")
    p = to_amo_order_payload(order, "11536", tag="A1")
    assert p["afterMarketOrder"] is True
    assert p["amoTime"] == "OPEN"  # default pump window
    assert p["orderType"] == "LIMIT" and p["productType"] == "CNC" and p["correlationId"] == "A1"
    assert p["securityId"] == "11536" and p["transactionType"] == "BUY"


def test_amo_order_payload_honours_explicit_time_incl_pre_open_and_rejects_bad():
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="CNC", quantity="10", price="2900", variety="amo")
    object.__setattr__(order, "amo_time", "OPEN_30")
    assert to_amo_order_payload(order, "11536")["amoTime"] == "OPEN_30"
    # PRE_OPEN is documented (orders.md/annexure.md) and reaches the broker via
    # the direct payload, even though the SDK's place_order would reject it.
    object.__setattr__(order, "amo_time", "PRE_OPEN")
    assert to_amo_order_payload(order, "11536")["amoTime"] == "PRE_OPEN"
    object.__setattr__(order, "amo_time", "MIDNIGHT")
    with pytest.raises(DhanMappingError, match="amo_time"):
        to_amo_order_payload(order, "11536")


def test_super_order_bracket_carries_both_legs():
    order = Order(
        symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT", product="MIS",
        quantity="5", price="2900", variety="bracket", target_price="2950",
        stop_loss_price="2870", trailing_jump="5",
    )
    kw = to_super_order_kwargs(order, "11536", tag="A1")
    assert kw["security_id"] == "11536" and kw["transaction_type"] == "BUY"
    assert kw["targetPrice"] == 2950.0 and kw["stopLossPrice"] == 2870.0 and kw["trailingJump"] == 5.0
    assert kw["tag"] == "A1"


def test_super_order_cover_drops_target():
    order = Order(
        symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT", product="MIS",
        quantity="5", price="2900", variety="cover", target_price="2950", stop_loss_price="2870",
    )
    kw = to_super_order_kwargs(order, "11536")
    assert kw["stopLossPrice"] == 2870.0 and kw["targetPrice"] == 0.0


def test_super_order_without_legs_raises():
    order = Order(symbol="X", action="BUY", exchange="NSE", pricetype="LIMIT", product="MIS",
                  quantity="5", price="2900", variety="bracket")
    with pytest.raises(DhanMappingError, match="target_price or stop_loss_price"):
        to_super_order_kwargs(order, "1")


def test_super_order_market_unsupported():
    # Dhan rejects price<=0 for super orders, so a MARKET bracket must fail closed.
    order = Order(symbol="X", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS",
                  quantity="5", variety="bracket", stop_loss_price="2870")
    with pytest.raises(DhanMappingError, match="limit entry price"):
        to_super_order_kwargs(order, "1")


def test_super_order_cover_with_only_target_raises():
    # A cover order drops the target, so a cover with ONLY a target (no stop-loss)
    # must fail closed — never reach the broker with a phantom target + no SL.
    order = Order(symbol="X", action="BUY", exchange="NSE", pricetype="LIMIT", product="MIS",
                  quantity="5", price="2900", variety="cover", target_price="2950")
    with pytest.raises(DhanMappingError, match="target_price or stop_loss_price"):
        to_super_order_kwargs(order, "1")


def test_super_order_rejects_sl_order_type():
    """Super orders are LIMIT/MARKET only (super-order.md); an SL entry fails
    closed as a mapped error, not a broker DH reject."""
    order = Order(symbol="X", action="BUY", exchange="NSE", pricetype="SL", product="MIS",
                  quantity="5", price="2900", variety="bracket", trigger_price="2890",
                  target_price="2950", stop_loss_price="2870")
    with pytest.raises(DhanMappingError, match="LIMIT or MARKET"):
        to_super_order_kwargs(order, "1")


def test_super_order_buy_bad_bracket_fails_as_mapped_error():
    """A BUY bracket whose target sits below the entry must fail as a mapped
    DhanMappingError (mirrors the SDK directional rule) — not a raw ValueError."""
    order = Order(symbol="X", action="BUY", exchange="NSE", pricetype="LIMIT", product="MIS",
                  quantity="5", price="2900", variety="bracket", target_price="2800",
                  stop_loss_price="2870")
    with pytest.raises(DhanMappingError, match="target_price must be above"):
        to_super_order_kwargs(order, "1")


def test_super_order_sell_bad_bracket_fails_as_mapped_error():
    """A SELL bracket whose stop-loss sits below the entry must fail closed."""
    order = Order(symbol="X", action="SELL", exchange="NSE", pricetype="LIMIT", product="MIS",
                  quantity="5", price="2900", variety="bracket", target_price="2850",
                  stop_loss_price="2870")
    with pytest.raises(DhanMappingError, match="stop_loss_price must be above"):
        to_super_order_kwargs(order, "1")


def test_super_order_valid_sell_bracket_passes():
    # SELL: target < price < stop_loss is the correct directional shape.
    order = Order(symbol="X", action="SELL", exchange="NSE", pricetype="LIMIT", product="MIS",
                  quantity="5", price="2900", variety="bracket", target_price="2850",
                  stop_loss_price="2950")
    kw = to_super_order_kwargs(order, "1")
    assert kw["targetPrice"] == 2850.0 and kw["stopLossPrice"] == 2950.0


def test_slice_order_mirrors_place_order():
    order = Order(symbol="RELIANCE", action="SELL", exchange="NSE", pricetype="LIMIT",
                  product="MIS", quantity="5000", price="2900", variety="iceberg")
    assert to_slice_order_kwargs(order, "11536") == to_place_order_kwargs(order, "11536")


def test_forever_gtt_kwargs():
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="CNC", quantity="5", price="2900", trigger_price="2890", variety="gtt")
    kw = to_forever_kwargs(order, "11536", tag="G1")
    assert kw["order_flag"] == "SINGLE" and kw["trigger_Price"] == 2890.0
    assert kw["price"] == 2900.0 and kw["product_type"] == "CNC" and kw["tag"] == "G1"


def test_forever_without_trigger_raises():
    order = Order(symbol="X", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="CNC", quantity="5", price="2900", variety="gtt")
    with pytest.raises(DhanMappingError, match="trigger_price"):
        to_forever_kwargs(order, "1")


def test_forever_oco_kwargs_carries_second_leg():
    """The OCO leg trio on the Order flips order_flag to OCO and maps to the
    forever.md ``price1`` / ``triggerPrice1`` / ``quantity1`` fields."""
    order = Order(
        symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT",
        product="CNC", quantity="5", price="2900", trigger_price="2890", variety="gtt",
        price1="2800", trigger_price1="2805", quantity1="5",
    )
    kw = to_forever_kwargs(order, "11536")
    assert kw["order_flag"] == "OCO"
    assert kw["price1"] == 2800.0
    assert kw["trigger_Price1"] == 2805.0
    assert kw["quantity1"] == 5
    # The first leg is unchanged.
    assert kw["price"] == 2900.0 and kw["trigger_Price"] == 2890.0


def test_forever_partial_oco_leg_raises():
    """A partial OCO leg must fail closed — never place SINGLE silently when the
    operator asked for a protective second leg."""
    order = Order(
        symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT",
        product="CNC", quantity="5", price="2900", trigger_price="2890", variety="gtt",
        price1="2800",  # trigger_price1 + quantity1 missing
    )
    with pytest.raises(DhanMappingError, match="OCO"):
        to_forever_kwargs(order, "11536")


def test_forever_without_oco_fields_stays_single():
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="CNC", quantity="5", price="2900", trigger_price="2890", variety="gtt")
    kw = to_forever_kwargs(order, "11536")
    assert kw["order_flag"] == "SINGLE"
    assert "price1" not in kw and "trigger_Price1" not in kw and "quantity1" not in kw


def test_margin_kwargs_and_parse():
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="MIS", quantity="10", price="2900")
    kw = to_margin_kwargs(order, "11536")
    assert kw["security_id"] == "11536" and kw["quantity"] == 10 and kw["price"] == 2900.0
    margin = from_dhan_margin({"status": "success", "data": {"totalMargin": 14500, "spanMargin": 12000}})
    assert margin["total_margin"] == "14500" and margin["span_margin"] == "12000"


def test_expiry_list_parse():
    assert from_dhan_expiry_list({"status": "success", "data": {"data": ["2026-06-26", "2026-07-31"]}}) == \
        ["2026-06-26", "2026-07-31"]
    assert from_dhan_expiry_list({"status": "success", "data": []}) == []


def test_statement_list_parse():
    rows = from_dhan_statement_list({"status": "success", "data": [{"a": 1}, "junk", {"b": 2}]})
    assert rows == [{"a": 1}, {"b": 2}]  # only dict rows survive
    assert from_dhan_statement_list({"status": "success", "data": []}) == []
    assert from_dhan_statement_list({"status": "error"}) == []


def test_modify_order_kwargs():
    kw = to_modify_order_kwargs("OID1", {"pricetype": "LIMIT", "quantity": 50, "price": 101.25})
    assert kw["order_id"] == "OID1"
    assert kw["order_type"] == "LIMIT"
    assert kw["quantity"] == 50
    assert kw["price"] == 101.25
    assert kw["validity"] == "DAY"


def test_extract_order_id_and_unwrap_failure():
    assert extract_order_id({"status": "success", "data": {"orderId": "112233"}}) == "112233"
    with pytest.raises(DhanMappingError, match="Dhan API error"):
        unwrap({"status": "failure", "remarks": {"error_message": "insufficient funds"}})


def test_from_dhan_order():
    rec = from_dhan_order({
        "orderId": "55", "orderStatus": "PENDING", "tradingSymbol": "TCS",
        "exchangeSegment": "NSE_EQ", "transactionType": "BUY", "orderType": "STOP_LOSS_MARKET",
        "productType": "INTRADAY", "quantity": 5, "price": 0, "triggerPrice": 3500,
    })
    assert rec["orderid"] == "55"
    assert rec["exchange"] == "NSE"
    assert rec["pricetype"] == "SL-M"
    assert rec["product"] == "MIS"


def test_from_dhan_position_and_trade():
    pos = from_dhan_position({
        "tradingSymbol": "INFY", "exchangeSegment": "NSE_EQ", "productType": "CNC",
        "netQty": 20, "costPrice": 1500, "realizedProfit": 100, "unrealizedProfit": 50,
    })
    assert pos["symbol"] == "INFY" and pos["exchange"] == "NSE" and pos["product"] == "CNC"
    assert pos["pnl"] == "150.0"

    trade = from_dhan_trade({
        "orderId": "9", "tradingSymbol": "SBIN", "exchangeSegment": "NSE_EQ",
        "transactionType": "SELL", "tradedQuantity": 100, "tradedPrice": 780.5,
    })
    assert trade["symbol"] == "SBIN" and trade["quantity"] == "100" and trade["price"] == "780.5"


def test_from_dhan_funds():
    funds = from_dhan_funds({"status": "success", "data": {"availabelBalance": 50000, "utilizedAmount": 12000}})
    assert funds["available_balance"] == "50000"
    assert funds["used_margin"] == "12000"


def test_interval_to_dhan():
    assert interval_to_dhan("D") == ("daily", 0)
    assert interval_to_dhan("daily") == ("daily", 0)
    assert interval_to_dhan("5m") == ("intraday", 5)
    assert interval_to_dhan("1h") == ("intraday", 60)
    assert interval_to_dhan("3m") == ("intraday", 5)  # snapped to nearest supported


def test_to_candles_dict():
    resp = {"status": "success", "data": {
        "open": [100, 101], "high": [102, 103], "low": [99, 100],
        "close": [101, 102], "volume": [1000, 1500], "timestamp": [1, 2],
    }}
    cd = to_candles_dict("RELIANCE", "NSE", "5m", resp)
    assert cd["symbol"] == "RELIANCE" and len(cd["bars"]) == 2
    assert cd["bars"][0] == {"timestamp": "1", "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 1000}


def test_quote_mapping():
    feed = {"status": "success", "data": {"NSE_EQ": {"11536": {
        "last_price": 2901.5, "ohlc": {"open": 2890, "high": 2910, "low": 2885, "close": 2888},
        "volume": 1_200_000,
    }}}}
    rec = quote_from_feed("NSE_EQ", "11536", feed)
    assert rec is not None
    q = from_dhan_quote("RELIANCE", "NSE", rec)
    assert q["ltp"] == 2901.5 and q["open"] == 2890.0 and q["volume"] == 1_200_000


def test_quote_from_feed_peels_double_nested_data():
    """Regression: the live SDK transport double-wraps the body and
    /marketfeed/quote nests under a second ``data`` (market-quote.md), so the
    real shape is data.data.<SEGMENT>. quote_from_feed must peel the inner data."""
    # doc-exact /marketfeed/quote body after dhan_http wraps it under `data`.
    feed = {"status": "success", "data": {"data": {"NSE_FNO": {"49081": {
        "last_price": 368.15,
        "ohlc": {"open": 0, "close": 368.15, "high": 0, "low": 0},
        "oi": 0, "volume": 0,
    }}}, "status": "success"}}
    rec = quote_from_feed("NSE_FNO", "49081", feed)
    assert rec is not None and rec["last_price"] == 368.15


def test_to_option_chain_dict():
    resp = {"status": "success", "data": {"last_price": 24000, "oc": {
        "24100.000000": {"ce": {"last_price": 100}, "pe": {"last_price": 180}},
        "24000.000000": {
            "ce": {"last_price": 150, "oi": 10000, "volume": 500, "implied_volatility": 12.5,
                   "greeks": {"delta": 0.5, "gamma": 0.01, "theta": -5, "vega": 8},
                   "top_bid_price": 149, "top_ask_price": 151},
            "pe": {"last_price": 140, "oi": 12000, "greeks": {"delta": -0.5}},
        },
    }}}
    oc = to_option_chain_dict("NIFTY", "NSE_INDEX", resp)
    assert oc["underlying"] == "NIFTY" and len(oc["strikes"]) == 2
    # sorted ascending by strike
    assert oc["strikes"][0]["strike_price"] == 24000.0
    assert oc["strikes"][1]["strike_price"] == 24100.0
    s0 = oc["strikes"][0]
    assert s0["ce_ltp"] == 150.0 and s0["ce_delta"] == 0.5 and s0["pe_oi"] == 12000


def test_to_option_chain_dict_peels_double_nested_data():
    """Regression: the live /optionchain body is data.{last_price, oc} and the
    SDK transport wraps it under another ``data`` (option-chain.md). The mapper
    must peel the inner data before reading ``oc`` or strikes come back empty."""
    resp = {"status": "success", "data": {"data": {"last_price": 25642.8, "oc": {
        "25650.000000": {
            "ce": {"last_price": 134, "oi": 3786445, "implied_volatility": 9.78,
                   "greeks": {"delta": 0.53871, "gamma": 0.00132, "theta": -15.15, "vega": 12.18},
                   "top_bid_price": 133.55, "top_ask_price": 134},
            "pe": {"last_price": 132.8, "oi": 3096145, "greeks": {"delta": -0.46732}},
        },
    }}, "status": "success"}}
    oc = to_option_chain_dict("NIFTY", "NSE_INDEX", resp)
    assert len(oc["strikes"]) == 1
    assert oc["strikes"][0]["strike_price"] == 25650.0
    assert oc["strikes"][0]["ce_ltp"] == 134.0 and oc["strikes"][0]["pe_oi"] == 3096145


def test_decode_dhan_ticker_packet():
    # <BHBIfI: code=15 (Ticker), msglen, seg=1 (NSE), security_id=11536, ltp, ltt
    data = struct.pack("<BHBIfI", 15, 16, 1, 11536, 2901.5, 123456)
    tick = decode_dhan_tick(data)
    assert tick is not None
    assert tick["code"] == 15
    assert tick["security_id"] == "11536"
    assert tick["ltp"] == 2901.5
    assert tick["exchange"] == "NSE"


def test_decode_dhan_quote_packet():
    data = struct.pack(
        "<BHBIfHIfIIIffff",
        17, 50, 2, 49081, 150.5, 10, 111, 149.0, 5000, 100, 200, 148.0, 145.0, 152.0, 144.0,
    )
    tick = decode_dhan_tick(data)
    assert tick is not None
    assert tick["code"] == 17 and tick["security_id"] == "49081"
    assert tick["ltp"] == 150.5 and tick["volume"] == 5000
    assert tick["exchange"] == "NFO"


def test_decode_dhan_rejects_short_or_unknown():
    assert decode_dhan_tick(b"\x00\x01") is None  # too short
    unknown = struct.pack("<BHBIfI", 99, 16, 1, 1, 1.0, 1)  # unknown response code
    assert decode_dhan_tick(unknown) is None
