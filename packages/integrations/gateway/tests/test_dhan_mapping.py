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
    to_modify_order_kwargs,
    to_option_chain_dict,
    to_place_order_kwargs,
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
