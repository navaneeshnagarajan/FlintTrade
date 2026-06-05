"""Unit tests for the FlintTrade <-> Kotak Neo (NEO OMS) mapping layer."""

from __future__ import annotations

import pytest

from flinttrade_core.models import Order
from flinttrade_gateway.brokers.kotakneo_mapping import (
    KotakNeoMappingError,
    extract_order_id,
    from_kotak_funds,
    from_kotak_order,
    from_kotak_position,
    from_kotak_quote,
    from_kotak_trade,
    to_modify_order_params,
    to_place_order_params,
    to_quote_tokens,
)

pytestmark = pytest.mark.unit


def test_place_order_market_buy():
    order = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS", quantity="10")
    p = to_place_order_params(order, "IDEA-EQ", tag="ALGO1")
    assert p["trading_symbol"] == "IDEA-EQ"
    assert p["exchange_segment"] == "nse_cm"
    assert p["transaction_type"] == "B"
    assert p["order_type"] == "MKT"
    assert p["product"] == "MIS"
    assert p["quantity"] == "10"  # NEO wants strings
    assert p["tag"] == "ALGO1"


def test_place_order_sl_m_fno_and_string_coercion():
    order = Order(
        symbol="NIFTY", action="SELL", exchange="NFO", pricetype="SL-M",
        product="NRML", quantity="75", trigger_price="120.5",
    )
    p = to_place_order_params(order, "NIFTY25JUN24000CE")
    assert p["order_type"] == "SL-M"
    assert p["exchange_segment"] == "nse_fo"
    assert p["product"] == "NRML"
    assert p["trigger_price"] == "120.5"
    assert p["transaction_type"] == "S"
    assert "tag" not in p  # no tag passed → key omitted


def test_place_order_unmapped_product_raises():
    order = Order(symbol="X", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS")
    object.__setattr__(order, "product", "ZZZ")
    with pytest.raises(KotakNeoMappingError, match="product"):
        to_place_order_params(order, "X-EQ")


def test_place_order_unmapped_exchange_raises():
    order = Order(symbol="X", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS")
    object.__setattr__(order, "exchange", "XXX")
    with pytest.raises(KotakNeoMappingError, match="exchange"):
        to_place_order_params(order, "X-EQ")


def test_modify_order_params():
    p = to_modify_order_params("250122000612876", {"pricetype": "LIMIT", "quantity": 50, "price": 101.25})
    assert p["order_id"] == "250122000612876"
    assert p["order_type"] == "L"
    assert p["quantity"] == "50"
    assert p["price"] == "101.25"


def test_extract_order_id_flat_and_nested():
    assert extract_order_id({"stat": "Ok", "nOrdNo": "250122000612876", "stCode": 200}) == "250122000612876"
    assert extract_order_id({"data": {"nOrdNo": "999"}}) == "999"
    with pytest.raises(KotakNeoMappingError):
        extract_order_id({"stat": "Ok", "stCode": 200})


def test_from_kotak_order_reverse_maps_neo_keys():
    order = from_kotak_order({
        "nOrdNo": "250122000612876", "ordSt": "open", "trdSym": "IDEA-EQ", "sym": "IDEA",
        "exSeg": "nse_cm", "trnsTp": "B", "prcTp": "L", "prod": "NRML",
        "qty": 1, "prc": "9.39", "trgPrc": "0.00", "fldQty": 0, "avgPrc": "0.00",
    })
    assert order["orderid"] == "250122000612876"
    assert order["exchange"] == "NSE"
    assert order["action"] == "BUY"
    assert order["pricetype"] == "LIMIT"
    assert order["product"] == "NRML"
    assert order["symbol"] == "IDEA-EQ"


def test_from_kotak_trade():
    trade = from_kotak_trade({
        "nOrdNo": "250122000612876", "trdSym": "IDEA-EQ", "exSeg": "nse_cm",
        "trnsTp": "S", "fldQty": 5, "avgPrc": "9.50", "prod": "MIS", "flDtTm": "22-Jan-2025 14:28:16",
    })
    assert trade["action"] == "SELL" and trade["quantity"] == "5" and trade["price"] == "9.50"
    assert trade["product"] == "MIS" and trade["exchange"] == "NSE"


def test_from_kotak_position_derives_net_and_pnl():
    # Bought 10 @ 100 (cost 1000), sold 4 @ 110 (proceeds 440): net long 6.
    pos = from_kotak_position({
        "trdSym": "IDEA-EQ", "exSeg": "nse_cm", "prod": "CNC",
        "cfBuyQty": 0, "flBuyQty": 10, "cfSellQty": 0, "flSellQty": 4,
        "buyAmt": 1000, "sellAmt": 440, "cfBuyAmt": 0, "cfSellAmt": 0,
    })
    assert pos["symbol"] == "IDEA-EQ"
    assert pos["exchange"] == "NSE"
    assert pos["product"] == "CNC"
    assert pos["quantity"] == "6"          # 10 buy - 4 sell
    assert pos["average_price"] == "100.00"  # buy_amt / buy_qty
    assert pos["pnl"] == "-560.00"         # 440 sell - 1000 buy (booked component)
    assert pos["buy_quantity"] == "10" and pos["sell_quantity"] == "4"


def test_from_kotak_funds():
    funds = from_kotak_funds({"data": {
        "avlCash": "38.190000", "totMrgnUsd": "34.280000", "mrgnUsd": "18.780000", "stat": "Ok", "stCode": 200,
    }})
    assert funds["available_balance"] == "38.19"
    assert funds["used_margin"] == "34.28"
    assert funds["total_balance"] == "72.47"


def test_to_quote_tokens_maps_segments():
    tokens = to_quote_tokens([("IDEA-EQ", "NSE"), ("NIFTY25JUN24000CE", "NFO")])
    assert tokens[0] == {"instrument_token": "IDEA-EQ", "exchange_segment": "nse_cm"}
    assert tokens[1] == {"instrument_token": "NIFTY25JUN24000CE", "exchange_segment": "nse_fo"}


def test_from_kotak_quote_long_keys():
    q = from_kotak_quote({
        "trading_symbol": "IDEA-EQ", "exchange_segment": "nse_cm", "last_traded_price": 9.4,
        "open": 9.2, "high": 9.6, "low": 9.1, "close": 9.3, "volume": 1_000_000,
        "buy_price": 9.39, "sell_price": 9.41, "open_interest": 0,
    })
    assert q["symbol"] == "IDEA-EQ" and q["exchange"] == "NSE"
    assert q["ltp"] == 9.4 and q["bid"] == 9.39 and q["ask"] == 9.41 and q["volume"] == 1_000_000


def test_from_kotak_quote_terse_feed_keys():
    # REST may echo the streaming-feed abbreviations — both must parse.
    q = from_kotak_quote({"ts": "NIFTY", "e": "nse_fo", "ltp": 24050.5, "h": 24100, "lo": 24000, "v": 500, "oi": 12345})
    assert q["symbol"] == "NIFTY" and q["exchange"] == "NFO"
    assert q["ltp"] == 24050.5 and q["high"] == 24100.0 and q["oi"] == 12345
