"""Unit tests for the Kotak Neo mapping additions (full v2 parity surface).

Covers the AMO variety, the full modify param surface, margin legs, the NEO
error envelopes, order-history unwrapping, limits/scrip-master/depth
normalisation and the HSM market-feed + HSI order-feed decoders — all against
synthetic frames shaped per ``.local/reference/broker-docs/kotak-neo/sdk-docs``
and the v2 SDK (``settings.py`` / ``NeoWebSocket.py``).
"""

from __future__ import annotations

import json

import pytest

from flinttrade_core.models import Order
from flinttrade_gateway.brokers.kotakneo_mapping import (
    KotakNeoMappingError,
    decode_kotak_feed,
    decode_kotak_order_feed,
    ensure_ok,
    from_kotak_depth,
    from_kotak_order,
    from_kotak_position,
    from_kotak_scrip_master,
    is_index_name,
    order_history_rows,
    subscription_flags,
    to_limits_params,
    to_margin_params,
    to_modify_order_params,
    to_place_order_params,
    to_quote_tokens,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Place: AMO variety
# ---------------------------------------------------------------------------

def test_place_order_amo_variety_sets_flag():
    order = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="CNC", quantity="10", price="9.4", variety="amo")
    p = to_place_order_params(order, "IDEA-EQ")
    assert p["amo"] == "YES"
    assert p["product"] == "CNC"  # AMO is a flag, not a product override


def test_place_order_regular_defaults_amo_no():
    order = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="CNC", quantity="10", price="9.4")
    assert to_place_order_params(order, "IDEA-EQ")["amo"] == "NO"


# ---------------------------------------------------------------------------
# Place: validity pass-through (Order.validity)
# ---------------------------------------------------------------------------

def test_place_order_validity_defaults_to_day_when_unset():
    order = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="CNC", quantity="10", price="9.4")
    assert to_place_order_params(order, "IDEA-EQ")["validity"] == "DAY"


def test_place_order_validity_passes_through_when_set():
    order = Order(symbol="GOLDPETAL25JUNFUT", action="BUY", exchange="MCX",
                  pricetype="LIMIT", product="NRML", quantity="1", price="7000",
                  validity="GTC")
    assert to_place_order_params(order, "GOLDPETAL25JUNFUT")["validity"] == "GTC"


def test_place_order_validity_invalid_raises():
    order = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="CNC", quantity="10", price="9.4", validity="FOREVER")
    with pytest.raises(KotakNeoMappingError, match="validity"):
        to_place_order_params(order, "IDEA-EQ")


@pytest.mark.parametrize(("exchange", "expected"), [("BCD", "bcs-fo"), ("MCX", "mcx_fo")])
def test_place_order_maps_documented_derivative_segments(exchange, expected):
    order = Order(
        symbol="SENSEX25JULFUT",
        action="BUY",
        exchange=exchange,
        pricetype="LIMIT",
        product="NRML",
        quantity="1",
        price="7000",
    )
    assert to_place_order_params(order, "SENSEX25JULFUT")["exchange_segment"] == expected


# ---------------------------------------------------------------------------
# Modify: full documented param surface
# ---------------------------------------------------------------------------

def test_modify_full_surface_quick_method():
    p = to_modify_order_params("250122000624384", {
        "pricetype": "SL", "price": 9.5, "quantity": 20, "trigger_price": 9.45,
        "instrument_token": "14366", "exchange_segment": "NSE", "product": "MIS",
        "trading_symbol": "IDEA-EQ", "transaction_type": "BUY",
        "amo": True, "filled_quantity": 5, "market_protection": "0", "dd": "NA",
    })
    assert p["order_id"] == "250122000624384"
    assert p["order_type"] == "SL" and p["trigger_price"] == "9.45"
    assert p["instrument_token"] == "14366"
    assert p["exchange_segment"] == "nse_cm"   # FlintTrade exchange mapped to NEO segment
    assert p["product"] == "MIS"
    assert p["trading_symbol"] == "IDEA-EQ"
    assert p["transaction_type"] == "B"        # BUY mapped to NEO single letter
    assert p["amo"] == "YES"                    # bool True normalised
    assert p["filled_quantity"] == "5"
    assert p["market_protection"] == "0" and p["dd"] == "NA"


def test_modify_minimal_omits_optional_keys():
    p = to_modify_order_params("1", {"quantity": 4, "price": 9.5})
    for key in ("instrument_token", "exchange_segment", "product", "trading_symbol",
                "transaction_type", "amo", "filled_quantity", "market_protection", "dd"):
        assert key not in p
    assert p["validity"] == "DAY"


def test_modify_amo_string_passthrough():
    assert to_modify_order_params("1", {"amo": "yes"})["amo"] == "YES"


def test_modify_validity_validated():
    assert to_modify_order_params("1", {"validity": "GTC"})["validity"] == "GTC"
    with pytest.raises(KotakNeoMappingError, match="validity"):
        to_modify_order_params("1", {"validity": "FOREVER"})


# ---------------------------------------------------------------------------
# Margin: trigger + variety legs
# ---------------------------------------------------------------------------

def test_margin_params_carry_trigger_price():
    order = Order(symbol="IDEA", action="SELL", exchange="NSE", pricetype="SL",
                  product="MIS", quantity="10", price="9.3", trigger_price="9.35")
    p = to_margin_params(order, "14366")
    assert p["trigger_price"] == "9.35"


def test_margin_params_bracket_legs_mirror_place():
    order = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="MIS", quantity="10", price="9.4", variety="bracket",
                  target_price="9.8", stop_loss_price="9.1", trailing_jump="0.1")
    p = to_margin_params(order, "14366")
    assert p["product"] == "BO"
    assert p["stop_loss_value"] == "9.1" and p["stop_loss_type"] == "Absolute"
    assert p["square_off_value"] == "9.8" and p["square_off_type"] == "Absolute"
    assert p["trailing_stop_loss"] == "Y" and p["trailing_sl_value"] == "0.1"


def test_margin_params_cover_uses_co():
    order = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="MIS", quantity="10", price="9.4", variety="cover",
                  stop_loss_price="9.1")
    p = to_margin_params(order, "14366")
    assert p["product"] == "CO" and "square_off_value" not in p


# ---------------------------------------------------------------------------
# Finding #1 — margin keys the scrip by numeric instrument_token (pSymbol),
# trading symbol rides its own field (Margin_Required.md:35).
# ---------------------------------------------------------------------------

def test_margin_params_use_numeric_instrument_token_and_trading_symbol():
    order = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="MIS", quantity="10", price="9.4")
    p = to_margin_params(order, "IDEA-EQ", instrument_token="14366")
    # instrument_token = numeric pSymbol; trading_symbol = pTrdSymbol — NOT the
    # trading symbol packed into instrument_token (the pre-fix bug).
    assert p["instrument_token"] == "14366"
    assert p["trading_symbol"] == "IDEA-EQ"


def test_margin_params_fall_back_to_symbol_when_token_unresolved():
    order = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="MIS", quantity="10", price="9.4")
    p = to_margin_params(order, "IDEA-EQ")  # no numeric token resolvable
    assert p["instrument_token"] == "IDEA-EQ" and p["trading_symbol"] == "IDEA-EQ"


# ---------------------------------------------------------------------------
# Finding #2 — quote token builder is numeric-token-shaped (indexes by name).
# ---------------------------------------------------------------------------

def test_to_quote_tokens_packs_resolved_token():
    tokens = to_quote_tokens([("14366", "NSE"), ("Nifty 50", "NSE")])
    assert tokens == [
        {"instrument_token": "14366", "exchange_segment": "nse_cm"},
        {"instrument_token": "Nifty 50", "exchange_segment": "nse_cm"},
    ]


def test_is_index_name_detects_indexes():
    assert is_index_name("Nifty 50") and is_index_name("NIFTY BANK") and is_index_name("sensex")
    assert not is_index_name("IDEA") and not is_index_name("RELIANCE")


# ---------------------------------------------------------------------------
# Finding #3 — cover order: stop level → trigger_price, NO bracket-only legs.
# ---------------------------------------------------------------------------

def test_place_cover_maps_stop_to_trigger_and_drops_bracket_fields():
    order = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="MIS", quantity="10", price="9.4", variety="cover",
                  stop_loss_price="9.1")
    p = to_place_order_params(order, "IDEA-EQ")
    assert p["product"] == "CO"
    assert p["trigger_price"] == "9.1"   # stop level rides trigger_price (CO-required)
    # Bracket-only fields MUST NOT be present on a cover order (Place_Order.md:88-93).
    for field in ("stop_loss_value", "stop_loss_type", "square_off_value",
                  "square_off_type", "trailing_stop_loss", "trailing_sl_value"):
        assert field not in p


def test_place_cover_falls_back_to_trigger_price_when_only_trigger_set():
    order = Order(symbol="IDEA", action="SELL", exchange="NSE", pricetype="SL-M",
                  product="MIS", quantity="10", price="0", variety="cover",
                  trigger_price="9.55")
    p = to_place_order_params(order, "IDEA-EQ")
    assert p["product"] == "CO" and p["trigger_price"] == "9.55"
    assert "stop_loss_value" not in p


def test_place_cover_without_stop_level_raises():
    order = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="MARKET",
                  product="MIS", quantity="10", price="0", variety="cover")
    with pytest.raises(KotakNeoMappingError, match="stop level"):
        to_place_order_params(order, "IDEA-EQ")


# ---------------------------------------------------------------------------
# Finding #4 — avg price denominator includes multiplier (Positions.md:110-112).
# ---------------------------------------------------------------------------

def test_position_avg_price_includes_multiplier():
    # Currency-derivative style row: multiplier = 1000, buy leg only.
    # Avg = amount / (qty * multiplier) = 105000 / (1 * 1000 * 1 * 1) = 105.00,
    # NOT 105000 (the pre-fix value with multiplier omitted).
    row = {
        "trdSym": "USDINR-FUT", "sym": "USDINR", "exSeg": "cde_fo", "prod": "NRML",
        "cfBuyQty": "1", "cfBuyAmt": "105000", "cfSellQty": "0", "cfSellAmt": "0",
        "flBuyQty": "0", "flSellQty": "0",
        "genNum": "1", "genDen": "1", "prcNum": "1", "prcDen": "1",
        "multiplier": "1000", "precision": "2",
    }
    pos = from_kotak_position(row)
    assert pos["average_price"] == "105.00"
    assert pos["quantity"] == "1"


def test_position_realised_pnl_amount_consistent_with_multiplier():
    # Fully matched buy 1 @105.00 / sell 1 @106.00, multiplier 1000.
    # Realised = matched * (sell_avg - buy_avg) * unit_factor = 1 * 1.00 * 1000 = 1000.00
    # = sell amount − buy amount (106000 − 105000), i.e. amount-consistent.
    row = {
        "trdSym": "USDINR-FUT", "sym": "USDINR", "exSeg": "cde_fo", "prod": "NRML",
        "cfBuyQty": "1", "cfBuyAmt": "105000", "cfSellQty": "1", "cfSellAmt": "106000",
        "flBuyQty": "0", "flSellQty": "0",
        "genNum": "1", "genDen": "1", "prcNum": "1", "prcDen": "1",
        "multiplier": "1000", "precision": "2",
    }
    pos = from_kotak_position(row)
    assert pos["pnl"] == "1000.00"


def test_position_avg_price_multiplier_one_unchanged():
    # Equity (multiplier 1) must be unaffected by the fix.
    row = {
        "trdSym": "IDEA-EQ", "sym": "IDEA", "exSeg": "nse_cm", "prod": "CNC",
        "cfBuyQty": "100", "cfBuyAmt": "939", "cfSellQty": "0", "cfSellAmt": "0",
        "multiplier": "1", "precision": "2",
    }
    pos = from_kotak_position(row)
    assert pos["average_price"] == "9.39"


# ---------------------------------------------------------------------------
# Finding #5 — modify quick-method fields are all-or-nothing.
# ---------------------------------------------------------------------------

def test_modify_partial_quick_fields_rejected():
    # instrument_token without the rest of the quick-path discriminators is a
    # partial set the SDK would reject with a ValueError — we reject it cleanly.
    with pytest.raises(KotakNeoMappingError, match="quick-method"):
        to_modify_order_params("1", {"instrument_token": "14366", "quantity": 5})


def test_modify_partial_quick_fields_missing_one_rejected():
    with pytest.raises(KotakNeoMappingError, match="trading_symbol"):
        to_modify_order_params("1", {
            "instrument_token": "14366", "exchange_segment": "NSE", "product": "MIS",
            # trading_symbol deliberately omitted
        })


def test_modify_complete_quick_set_accepted():
    p = to_modify_order_params("1", {
        "instrument_token": "14366", "exchange_segment": "NSE", "product": "MIS",
        "trading_symbol": "IDEA-EQ", "quantity": 5,
    })
    assert p["instrument_token"] == "14366" and p["trading_symbol"] == "IDEA-EQ"


def test_modify_order_id_path_no_quick_fields_accepted():
    p = to_modify_order_params("1", {"quantity": 5, "price": 9.5})
    for f in ("instrument_token", "exchange_segment", "product", "trading_symbol"):
        assert f not in p


# ---------------------------------------------------------------------------
# Finding #6 — stock feed sell_quantity is keyed 'sq', not the depth key 'bs'.
# ---------------------------------------------------------------------------

def test_stock_feed_decode_reads_sell_quantity_from_sq():
    tick = decode_kotak_feed([{
        "tk": "11536", "ts": "TCS-EQ", "e": "nse_cm", "name": "sf",
        "ltp": "4000.5", "bq": "10", "sq": "7",
    }])[0]
    assert tick["kind"] == "quote"
    assert tick["sell_quantity"] == 7 and tick["buy_quantity"] == 10


def test_stock_feed_decode_ignores_depth_bs_key_for_sell_quantity():
    # 'bs' is a depth-frame offer-size key; in a stock frame it must NOT be read
    # as sell_quantity (the pre-fix STOCK_FEED_KEYS bug).
    tick = decode_kotak_feed([{
        "tk": "11536", "ts": "TCS-EQ", "e": "nse_cm", "name": "sf",
        "ltp": "4000.5", "bs": "99",
    }])[0]
    assert tick["sell_quantity"] == 0


def test_stock_feed_decode_reads_long_name_sell_quantity():
    # SDK quote_resp_mapper re-keys 'sq' -> 'sell_quantity'; the long name decodes too.
    tick = decode_kotak_feed({"type": "quotes", "data": [{
        "instrument_token": "11536", "trading_symbol": "TCS-EQ", "exchange_segment": "nse_cm",
        "last_traded_price": 4000.5, "sell_quantity": 5, "buy_quantity": 8,
    }]})[0]
    assert tick["sell_quantity"] == 5 and tick["buy_quantity"] == 8


# ---------------------------------------------------------------------------
# Error envelopes
# ---------------------------------------------------------------------------

def test_ensure_ok_passes_ok_envelopes():
    assert ensure_ok({"stat": "Ok", "nOrdNo": "1", "stCode": 200})["nOrdNo"] == "1"
    assert ensure_ok({"stat": "ok", "data": []})  # OMS lower-case variant
    assert ensure_ok([1, 2]) == [1, 2]  # non-dict passes through


def test_ensure_ok_raises_on_each_error_shape():
    with pytest.raises(KotakNeoMappingError, match="error"):
        ensure_ok({"Error": "boom"})
    with pytest.raises(KotakNeoMappingError, match="2fa"):
        ensure_ok({"Error Message": "Complete the 2fa process before accessing this application"})
    with pytest.raises(KotakNeoMappingError, match="Mobile Number"):
        ensure_ok({"error": [{"message": "Any of Mobile Number, UCC or totp is missing"}]})
    with pytest.raises(KotakNeoMappingError, match="rejected"):
        ensure_ok({"stat": "Not_Ok", "errMsg": "Invalid session"})


# ---------------------------------------------------------------------------
# Order history + order-report enrichment
# ---------------------------------------------------------------------------

_HISTORY_ROW = {
    "trdSym": "IDEA-EQ", "prc": "9.39", "qty": 1, "ordSt": "complete", "trnsTp": "B",
    "prcTp": "L", "exSeg": "nse_cm", "exchTmstp": "22-Jan-2025 14:32:53", "nOrdNo": "250122000624384",
    "avgPrc": "9.39", "trgPrc": "0.00", "dclQty": "0", "exchOrdId": "1100000060414692",
    "rejRsn": "--", "ordDur": "DAY", "prod": "NRML", "fldQty": 1, "GuiOrdId": "",
}


def test_order_history_rows_unwraps_double_nesting():
    resp = {"data": {"stat": "Ok", "stCode": 200, "data": [_HISTORY_ROW, {**_HISTORY_ROW, "ordSt": "open"}]}}
    rows = order_history_rows(resp)
    assert len(rows) == 2 and rows[0]["ordSt"] == "complete"


def test_order_history_rows_tolerates_single_nesting_and_garbage():
    assert order_history_rows({"stat": "Ok", "data": [_HISTORY_ROW]}) == [_HISTORY_ROW]
    assert order_history_rows({"Error": "boom"}) == []
    assert order_history_rows("garbage") == []


def test_from_kotak_order_history_row_normalises():
    o = from_kotak_order(_HISTORY_ROW)
    assert o["orderid"] == "250122000624384" and o["status"] == "complete"
    assert o["timestamp"] == "22-Jan-2025 14:32:53"   # history rows use exchTmstp
    assert o["validity"] == "DAY"                       # falls back to ordDur
    assert o["rejection_reason"] == ""                  # "--" sentinel scrubbed
    assert o["exchange_order_id"] == "1100000060414692"


def test_from_kotak_order_report_extras():
    o = from_kotak_order({
        "nOrdNo": "1", "ordSt": "rejected", "trdSym": "IDEA-EQ", "exSeg": "nse_cm",
        "trnsTp": "B", "prcTp": "L", "prod": "NRML", "qty": 1, "prc": "9.39",
        "ordDtTm": "22-Jan-2025 14:28:01", "vldt": "DAY", "dscQty": 0,
        "rejRsn": "RMS check failed", "exOrdId": "NA", "GuiOrdId": "FLINT1",
    })
    assert o["timestamp"] == "22-Jan-2025 14:28:01" and o["validity"] == "DAY"
    assert o["rejection_reason"] == "RMS check failed"
    assert o["exchange_order_id"] == ""                 # "NA" sentinel scrubbed
    assert o["tag"] == "FLINT1"


# ---------------------------------------------------------------------------
# Limits filters
# ---------------------------------------------------------------------------

def test_limits_params_defaults_and_normalisation():
    assert to_limits_params() == {"segment": "ALL", "exchange": "ALL", "product": "ALL"}
    assert to_limits_params("cash", "nse", "mis") == {"segment": "CASH", "exchange": "NSE", "product": "MIS"}


def test_limits_params_validation():
    with pytest.raises(KotakNeoMappingError, match="segment"):
        to_limits_params(segment="EQUITY")
    with pytest.raises(KotakNeoMappingError, match="exchange"):
        to_limits_params(exchange="MCX")  # limits exchange filter is NSE/BSE/ALL only
    with pytest.raises(KotakNeoMappingError, match="product"):
        to_limits_params(product="BO")


# ---------------------------------------------------------------------------
# Scrip master
# ---------------------------------------------------------------------------

def test_scrip_master_full_response():
    out = from_kotak_scrip_master({
        "filesPaths": [
            "https://lapi.kotaksecurities.com/wso2-scripmaster/v1/prod/2025-01-22/transformed/nse_cm.csv",
            "https://lapi.kotaksecurities.com/wso2-scripmaster/v1/prod/2025-01-22/transformed/nse_fo.csv",
        ],
        "baseFolder": "https://lapi.kotaksecurities.com/wso2-scripmaster/v1/prod",
    })
    assert len(out["files"]) == 2 and out["base_folder"].endswith("/prod")


def test_scrip_master_filtered_string_and_garbage():
    url = "https://lapi.kotaksecurities.com/wso2-scripmaster/v1/prod/2025-01-22/transformed/nse_cm.csv"
    assert from_kotak_scrip_master(url) == {"base_folder": "", "files": [url]}
    assert from_kotak_scrip_master(None) == {"base_folder": "", "files": []}


# ---------------------------------------------------------------------------
# Depth
# ---------------------------------------------------------------------------

def test_depth_from_preshaped_sdk_record():
    rec = {
        "instrument_token": "11536", "trading_symbol": "TCS-EQ", "exchange_segment": "nse_cm",
        "depth": {
            "buy": [{"price": 4000.0, "quantity": 10, "orders": 2}],
            "sell": [{"price": 4001.0, "quantity": 5, "orders": 1}],
        },
    }
    d = from_kotak_depth(rec)
    assert d["symbol"] == "TCS-EQ" and d["exchange"] == "NSE" and d["token"] == "11536"
    assert d["bids"][0]["price"] == 4000.0 and d["asks"][0]["quantity"] == 5


def test_depth_from_terse_frame_keys():
    # Raw HSM depth frame vocabulary (webSocket.md "For Depth"): bp..bp4 bids,
    # sp..sp4 offers, bq../bs.. sizes, bno/sno order counts.
    rec = {
        "tk": "11536", "ts": "TCS-EQ", "e": "nse_cm", "name": "dp",
        "bp": "4000", "bp1": "3999.5", "bq": "10", "bq1": "20", "bno1": "2", "bno2": "3",
        "sp": "4001", "sp1": "4001.5", "bs": "5", "bs1": "8", "sno1": "1", "sno2": "4",
    }
    d = from_kotak_depth(rec)
    assert len(d["bids"]) == 5 and len(d["asks"]) == 5
    assert d["bids"][0] == {"price": 4000.0, "quantity": 10, "orders": 2}
    assert d["bids"][1] == {"price": 3999.5, "quantity": 20, "orders": 3}
    assert d["asks"][0] == {"price": 4001.0, "quantity": 5, "orders": 1}
    assert d["asks"][1] == {"price": 4001.5, "quantity": 8, "orders": 4}
    assert d["bids"][4] == {"price": 0.0, "quantity": 0, "orders": 0}  # absent levels zeroed


# ---------------------------------------------------------------------------
# Subscription flags
# ---------------------------------------------------------------------------

def test_subscription_flags_modes():
    assert subscription_flags("LTP") == (False, False)
    assert subscription_flags("quote") == (False, False)
    assert subscription_flags("FULL") == (False, True)
    assert subscription_flags("DEPTH") == (False, True)
    assert subscription_flags("INDEX") == (True, False)
    with pytest.raises(KotakNeoMappingError, match="mode"):
        subscription_flags("GREEKS")


# ---------------------------------------------------------------------------
# HSM market-feed decode
# ---------------------------------------------------------------------------

_STOCK_TICK = {
    "tk": "11536", "ts": "TCS-EQ", "e": "nse_cm", "ltp": "4000.5", "v": "120000",
    "bp": "4000.0", "sp": "4001.0", "oi": "0", "ltt": "22/01/2025 14:28:16", "name": "sf",
}


def test_decode_feed_stock_frame_wrapped_and_bare():
    wrapped = {"type": "stock_feed", "data": [_STOCK_TICK]}
    for frame in (wrapped, [_STOCK_TICK]):
        ticks = decode_kotak_feed(frame)
        assert len(ticks) == 1
        t = ticks[0]
        assert t["kind"] == "quote" and t["symbol"] == "TCS-EQ" and t["exchange"] == "NSE"
        assert t["ltp"] == 4000.5 and t["volume"] == 120000
        assert t["bid"] == 4000.0 and t["ask"] == 4001.0
        assert t["timestamp"] == "22/01/2025 14:28:16"


def test_decode_feed_json_string_frame():
    ticks = decode_kotak_feed(json.dumps([_STOCK_TICK]))
    assert len(ticks) == 1 and ticks[0]["token"] == "11536"


def test_decode_feed_sdk_long_key_record():
    # The SDK's quote_resp_mapper re-keys records to the long names from
    # settings.stock_key_mapping — both vocabularies must decode.
    ticks = decode_kotak_feed({"type": "quotes", "data": [{
        "instrument_token": "11536", "trading_symbol": "TCS-EQ", "exchange_segment": "nse_cm",
        "last_traded_price": 4000.5, "volume": 120000, "buy_price": 4000.0, "sell_price": 4001.0,
        "open_interest": 0, "last_traded_time": "22/01/2025 14:28:16",
    }]})
    assert len(ticks) == 1
    t = ticks[0]
    assert t["kind"] == "quote" and t["symbol"] == "TCS-EQ" and t["ltp"] == 4000.5
    assert t["volume"] == 120000 and t["bid"] == 4000.0 and t["ask"] == 4001.0


def test_decode_feed_index_frame():
    ticks = decode_kotak_feed([{
        "tk": "Nifty 50", "e": "nse_cm", "name": "if", "iv": "24050.5", "ic": "23990.0",
        "openingPrice": "24000", "highPrice": "24100", "lowPrice": "23950", "tvalue": "1737536296",
    }])
    assert len(ticks) == 1
    t = ticks[0]
    assert t["kind"] == "index" and t["ltp"] == 24050.5 and t["prev_close"] == 23990.0
    assert t["high"] == 24100.0 and t["timestamp"] == "1737536296"


def test_decode_feed_depth_frame_carries_book():
    ticks = decode_kotak_feed([{
        "tk": "11536", "ts": "TCS-EQ", "e": "nse_cm", "name": "dp",
        "bp": "4000", "bq": "10", "bno1": "2", "sp": "4001", "bs": "5", "sno1": "1",
    }])
    assert len(ticks) == 1
    t = ticks[0]
    assert t["kind"] == "depth" and t["bid"] == 4000.0 and t["ask"] == 4001.0
    assert t["depth"]["bids"][0]["quantity"] == 10


def test_decode_feed_acks_and_garbage_are_empty():
    assert decode_kotak_feed(json.dumps([{"type": "cn", "msg": "connected"}])) == []
    assert decode_kotak_feed("Un-Subscribed Successfully!") == []
    assert decode_kotak_feed({"type": "order_feed", "data": "{}"}) == []
    assert decode_kotak_feed(None) == []
    assert decode_kotak_feed([{"request_type": "cn"}]) == []


# ---------------------------------------------------------------------------
# HSI order-feed decode
# ---------------------------------------------------------------------------

_ORDER_UPDATE = {
    "nOrdNo": "250122000624384", "ordSt": "complete", "trdSym": "IDEA-EQ", "exSeg": "nse_cm",
    "trnsTp": "B", "prcTp": "L", "prod": "NRML", "qty": 1, "prc": "9.39",
    "fldQty": 1, "avgPrc": "9.39",
}


def test_decode_order_feed_wrapped_json_string():
    frame = {"type": "order_feed", "data": json.dumps({"data": _ORDER_UPDATE})}
    update = decode_kotak_order_feed(frame)
    assert update is not None
    assert update["orderid"] == "250122000624384" and update["status"] == "complete"
    assert update["action"] == "BUY" and update["exchange"] == "NSE"
    assert update["raw"]["nOrdNo"] == "250122000624384"


def test_decode_order_feed_bare_dict():
    update = decode_kotak_order_feed(_ORDER_UPDATE)
    assert update is not None and update["filled_quantity"] == "1"


def test_decode_order_feed_acks_and_garbage_are_none():
    assert decode_kotak_order_feed({"type": "order_feed", "data": '{"type": "cn"}'}) is None
    assert decode_kotak_order_feed('{"type": "CONNECTION"}') is None
    assert decode_kotak_order_feed("not-json") is None
    assert decode_kotak_order_feed(None) is None
    assert decode_kotak_order_feed({"hello": "world"}) is None
