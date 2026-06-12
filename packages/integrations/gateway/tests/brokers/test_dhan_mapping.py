"""Tests for the canonical-to-Dhan mapping tables.

Values are checked against the official DhanHQ Agent Skill / v2 SDK constants,
and a drift invariant asserts the mapping covers every exchange Dhan advertises
in BROKER_CATALOG.
"""

from __future__ import annotations

import json
import struct

import pytest

from flinttrade_core.models import Order
from flinttrade_gateway.adapter import BROKER_CATALOG
from flinttrade_gateway.brokers import dhan_mapping as m

pytestmark = pytest.mark.unit


def test_order_type_map_matches_dhan_sdk_constants() -> None:
    assert m.ORDER_TYPE_MAP == {
        "MARKET": "MARKET",
        "LIMIT": "LIMIT",
        "SL": "STOP_LOSS",
        "SLM": "STOP_LOSS_MARKET",
    }


def test_product_map_uses_dhan_names() -> None:
    # Dhan uses INTRADAY/MARGIN, not the MIS/NRML canonical names.
    assert m.PRODUCT_MAP["MIS"] == "INTRADAY"
    assert m.PRODUCT_MAP["NRML"] == "MARGIN"
    assert m.PRODUCT_MAP["CNC"] == "CNC"
    assert m.PRODUCT_MAP["MTF"] == "MTF"


def test_validity_map_routes_gtt_to_forever() -> None:
    assert m.VALIDITY_MAP["GTT"] == "FOREVER"
    assert m.VALIDITY_MAP["DAY"] == "DAY"
    assert m.VALIDITY_MAP["IOC"] == "IOC"


def test_exchange_segment_map_values() -> None:
    assert m.EXCHANGE_SEGMENT_MAP["NSE"] == "NSE_EQ"
    assert m.EXCHANGE_SEGMENT_MAP["NFO"] == "NSE_FNO"
    assert m.EXCHANGE_SEGMENT_MAP["BFO"] == "BSE_FNO"
    assert m.EXCHANGE_SEGMENT_MAP["MCX"] == "MCX_COMM"
    assert m.EXCHANGE_SEGMENT_MAP["CDS"] == "NSE_CURRENCY"
    assert m.EXCHANGE_SEGMENT_MAP["NSE_INDEX"] == "IDX_I"


def test_to_dhan_segment_is_case_insensitive_and_raises_on_unknown() -> None:
    assert m.to_dhan_segment("nse") == "NSE_EQ"
    assert m.to_dhan_segment("Nfo") == "NSE_FNO"
    with pytest.raises(KeyError):
        m.to_dhan_segment("NASDAQ")


def test_index_security_ids_match_skill_table() -> None:
    # From the DhanHQ skill "Instrument Resolution Rules" quick-reference table.
    assert m.INDEX_SECURITY_IDS["NIFTY 50"] == ("13", "IDX_I")
    assert m.INDEX_SECURITY_IDS["BANKNIFTY"] == ("25", "IDX_I")
    assert m.INDEX_SECURITY_IDS["FINNIFTY"] == ("27", "IDX_I")
    assert m.INDEX_SECURITY_IDS["MIDCPNIFTY"] == ("442", "IDX_I")
    assert m.INDEX_SECURITY_IDS["SENSEX"] == ("51", "IDX_I")


def test_every_advertised_dhan_exchange_has_a_segment_mapping() -> None:
    """Drift guard: each exchange Dhan advertises in BROKER_CATALOG must map.

    Without this, the catalog could advertise an exchange the adapter cannot
    actually route an order to.
    """
    advertised = BROKER_CATALOG["dhan"].exchanges
    missing = [e for e in advertised if e not in m.EXCHANGE_SEGMENT_MAP]
    assert not missing, f"Dhan exchanges with no segment mapping: {missing}"


# ---------------------------------------------------------------------------
# Subscribe modes (live market feed)
# ---------------------------------------------------------------------------


def test_subscribe_mode_maps_to_sdk_request_codes() -> None:
    # marketfeed.py constants: Ticker=15, Quote=17, Full=21.
    assert m.subscribe_mode_to_request_code("TICKER") == 15
    assert m.subscribe_mode_to_request_code("ltp") == 15
    assert m.subscribe_mode_to_request_code("quote") == 17
    assert m.subscribe_mode_to_request_code("FULL") == 21


def test_subscribe_mode_unknown_raises() -> None:
    with pytest.raises(m.DhanMappingError, match="feed mode"):
        m.subscribe_mode_to_request_code("DEPTH99")


# ---------------------------------------------------------------------------
# Forever (GTT) management
# ---------------------------------------------------------------------------


def test_modify_forever_kwargs() -> None:
    kw = m.to_modify_forever_kwargs(
        "GTT1",
        {"pricetype": "SL", "leg_name": "TARGET_LEG", "quantity": 10, "price": 101.5,
         "trigger_price": 100.0, "order_flag": "oco", "validity": "DAY"},
    )
    assert kw["order_id"] == "GTT1"
    assert kw["order_flag"] == "OCO"
    assert kw["order_type"] == "STOP_LOSS"
    assert kw["leg_name"] == "TARGET_LEG"
    assert kw["quantity"] == 10 and kw["price"] == 101.5 and kw["trigger_price"] == 100.0
    assert kw["validity"] == "DAY"


def test_modify_forever_invalid_flag_raises() -> None:
    with pytest.raises(m.DhanMappingError, match="SINGLE or OCO"):
        m.to_modify_forever_kwargs("GTT1", {"order_flag": "TRIPLE"})


def test_from_dhan_forever_order() -> None:
    rec = m.from_dhan_forever_order({
        "orderId": "5132208051112", "orderStatus": "PENDING", "orderFlag": "SINGLE",
        "tradingSymbol": "HDFCBANK", "exchangeSegment": "NSE_EQ", "transactionType": "BUY",
        "orderType": "LIMIT", "productType": "CNC", "quantity": 5, "price": 1428,
        "triggerPrice": 1427, "legName": "ENTRY_LEG", "createTime": "2026-06-01 10:00:00",
    })
    assert rec["orderid"] == "5132208051112" and rec["status"] == "PENDING"
    assert rec["exchange"] == "NSE" and rec["product"] == "CNC"
    assert rec["trigger_price"] == "1427" and rec["order_flag"] == "SINGLE"


# ---------------------------------------------------------------------------
# Super order management
# ---------------------------------------------------------------------------


def test_modify_super_order_kwargs_entry_leg() -> None:
    kw = m.to_modify_super_order_kwargs(
        "SUP1",
        {"leg_name": "entry_leg", "pricetype": "LIMIT", "quantity": 5, "price": 2900,
         "target_price": 2950, "stop_loss_price": 2870, "trailing_jump": 5},
    )
    assert kw["order_id"] == "SUP1" and kw["leg_name"] == "ENTRY_LEG"
    assert kw["targetPrice"] == 2950.0 and kw["stopLossPrice"] == 2870.0 and kw["trailingJump"] == 5.0


def test_modify_super_order_kwargs_target_and_sl_legs() -> None:
    target = m.to_modify_super_order_kwargs("SUP1", {"leg_name": "TARGET_LEG", "target_price": 2960})
    assert target["leg_name"] == "TARGET_LEG" and target["targetPrice"] == 2960.0
    sl = m.to_modify_super_order_kwargs("SUP1", {"leg_name": "STOP_LOSS_LEG", "stop_loss_price": 2860})
    assert sl["leg_name"] == "STOP_LOSS_LEG" and sl["stopLossPrice"] == 2860.0


def test_modify_super_order_invalid_leg_raises() -> None:
    with pytest.raises(m.DhanMappingError, match="leg_name"):
        m.to_modify_super_order_kwargs("SUP1", {"leg_name": "MIDDLE_LEG"})


def test_from_dhan_super_order_includes_legs() -> None:
    rec = m.from_dhan_super_order({
        "orderId": "5925022734212", "orderStatus": "PENDING", "tradingSymbol": "RELIANCE",
        "exchangeSegment": "NSE_EQ", "transactionType": "BUY", "orderType": "LIMIT",
        "productType": "INTRADAY", "quantity": 5, "price": 2900, "targetPrice": 2950,
        "stopLossPrice": 2870, "trailingJump": 5, "filledQty": 0, "averageTradedPrice": 0,
        "legDetails": [{"orderId": "5925022734213", "legName": "STOP_LOSS_LEG"}, "junk"],
    })
    assert rec["orderid"] == "5925022734212" and rec["exchange"] == "NSE" and rec["product"] == "MIS"
    assert rec["target_price"] == "2950" and rec["stop_loss_price"] == "2870"
    assert rec["legs"] == [{"orderId": "5925022734213", "legName": "STOP_LOSS_LEG"}]


# ---------------------------------------------------------------------------
# Convert position
# ---------------------------------------------------------------------------


def test_convert_position_kwargs() -> None:
    kw = m.to_convert_position_kwargs(
        {"from_product": "MIS", "to_product": "CNC", "position_type": "LONG",
         "exchange": "NSE", "quantity": 40},
        "11536",
    )
    assert kw == {
        "from_product_type": "INTRADAY",
        "exchange_segment": "NSE_EQ",
        "position_type": "LONG",
        "security_id": "11536",
        "convert_qty": 40,
        "to_product_type": "CNC",
    }


def test_convert_position_accepts_dhan_product_names() -> None:
    kw = m.to_convert_position_kwargs(
        {"from_product": "INTRADAY", "to_product": "MARGIN", "position_type": "SHORT",
         "exchange": "NFO", "quantity": 75},
        "49081",
    )
    assert kw["from_product_type"] == "INTRADAY" and kw["to_product_type"] == "MARGIN"
    assert kw["exchange_segment"] == "NSE_FNO"


def test_convert_position_validation_failures() -> None:
    base = {"from_product": "MIS", "to_product": "CNC", "position_type": "LONG",
            "exchange": "NSE", "quantity": 40}
    with pytest.raises(m.DhanMappingError, match="position_type"):
        m.to_convert_position_kwargs({**base, "position_type": "SIDEWAYS"}, "1")
    with pytest.raises(m.DhanMappingError, match="positive quantity"):
        m.to_convert_position_kwargs({**base, "quantity": 0}, "1")
    with pytest.raises(m.DhanMappingError, match="segment"):
        m.to_convert_position_kwargs({**base, "exchange": "NASDAQ"}, "1")
    with pytest.raises(m.DhanMappingError, match="product"):
        m.to_convert_position_kwargs({**base, "to_product": "SUPERSAVER"}, "1")


# ---------------------------------------------------------------------------
# Conditional triggers (v2.5)
# ---------------------------------------------------------------------------

_CONDITION = {
    "comparisonType": "TECHNICAL_WITH_VALUE",
    "exchangeSegment": "NSE_EQ",
    "securityId": "11536",
    "indicatorName": "SMA_5",
    "timeFrame": "DAY",
    "operator": "CROSSING_UP",
    "comparingValue": 250,
    "frequency": "ONCE",
}


def test_conditional_order_leg_uses_doc_field_names() -> None:
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="CNC", quantity="10", price="250")
    leg = m.to_conditional_order_leg(order, "11536")
    # conditional-trigger.md uses discQuantity (not disclosedQuantity) + string prices.
    assert leg["transactionType"] == "BUY" and leg["exchangeSegment"] == "NSE_EQ"
    assert leg["productType"] == "CNC" and leg["orderType"] == "LIMIT"
    assert leg["securityId"] == "11536" and leg["quantity"] == 10
    assert leg["validity"] == "DAY"
    assert leg["price"] == "250.0" and leg["discQuantity"] == "0" and leg["triggerPrice"] == "0.0"


def test_conditional_trigger_payload_roundtrip() -> None:
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="CNC", quantity="10", price="250")
    legs = [m.to_conditional_order_leg(order, "11536")]
    payload = m.to_conditional_trigger_payload(_CONDITION, legs)
    assert payload["condition"]["comparisonType"] == "TECHNICAL_WITH_VALUE"
    assert payload["orders"] == legs


def test_conditional_trigger_payload_fails_closed() -> None:
    order = Order(symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT",
                  product="CNC", quantity="10", price="250")
    legs = [m.to_conditional_order_leg(order, "11536")]
    with pytest.raises(m.DhanMappingError, match="missing required keys"):
        m.to_conditional_trigger_payload({"comparisonType": "PRICE"}, legs)
    with pytest.raises(m.DhanMappingError, match="order leg"):
        m.to_conditional_trigger_payload(_CONDITION, [])
    with pytest.raises(m.DhanMappingError, match="condition dict"):
        m.to_conditional_trigger_payload("not-a-dict", legs)  # type: ignore[arg-type]


def test_extract_alert_id_and_normalise() -> None:
    assert m.extract_alert_id({"status": "success", "data": {"alertId": "12345"}}) == "12345"
    with pytest.raises(m.DhanMappingError, match="alert id"):
        m.extract_alert_id({"status": "success", "data": {}})
    rec = m.from_dhan_conditional_trigger({
        "alertId": "12345", "alertStatus": "ACTIVE", "createdTime": "2026-06-01T14:15:22Z",
        "triggeredTime": None, "lastPrice": 245.5, "condition": _CONDITION,
        "orders": [{"transactionType": "BUY"}, "junk"],
    })
    assert rec["alert_id"] == "12345" and rec["status"] == "ACTIVE"
    assert rec["triggered_at"] == "" and rec["condition"]["operator"] == "CROSSING_UP"
    assert rec["orders"] == [{"transactionType": "BUY"}]


# ---------------------------------------------------------------------------
# Trader's Control v2.5 — P&L based exit
# ---------------------------------------------------------------------------


def test_pnl_exit_payload() -> None:
    payload = m.to_pnl_exit_payload(1500, 500, ["MIS", "CNC"], enable_kill_switch=True)
    assert payload == {
        "profitValue": "1500.0",
        "lossValue": "500.0",
        "productType": ["INTRADAY", "DELIVERY"],
        "enableKillSwitch": True,
    }


def test_pnl_exit_payload_fails_closed() -> None:
    with pytest.raises(m.DhanMappingError, match="profit_value or loss_value"):
        m.to_pnl_exit_payload(0, 0)
    with pytest.raises(m.DhanMappingError, match="productType"):
        m.to_pnl_exit_payload(1000, 0, ["NRML"])


# ---------------------------------------------------------------------------
# Expired (rolling) options data
# ---------------------------------------------------------------------------


def test_expired_options_kwargs() -> None:
    kw = m.to_expired_options_kwargs(
        {"exchange": "NFO", "instrument": "OPTIDX", "expiry_flag": "MONTH", "expiry_code": 1,
         "strike": "ATM+1", "option_type": "PUT", "required_data": ["open", "close", "iv"],
         "from_date": "2021-08-01", "to_date": "2021-09-01", "interval": 5},
        "13",
    )
    assert kw["security_id"] == "13" and kw["exchange_segment"] == "NSE_FNO"
    assert kw["expiry_flag"] == "MONTH" and kw["drv_option_type"] == "PUT"
    assert kw["strike"] == "ATM+1" and kw["interval"] == 5
    assert kw["required_data"] == ["open", "close", "iv"]


def test_expired_options_kwargs_defaults_all_fields() -> None:
    kw = m.to_expired_options_kwargs({"from_date": "2025-01-01", "to_date": "2025-01-30"}, "13")
    assert kw["required_data"] == list(m.EXPIRED_OPTIONS_FIELDS)
    assert kw["expiry_flag"] == "WEEK" and kw["drv_option_type"] == "CALL" and kw["strike"] == "ATM"


def test_expired_options_kwargs_validation_failures() -> None:
    base = {"from_date": "2025-01-01", "to_date": "2025-01-30"}
    with pytest.raises(m.DhanMappingError, match="interval"):
        m.to_expired_options_kwargs({**base, "interval": 3}, "13")
    with pytest.raises(m.DhanMappingError, match="expiry_flag"):
        m.to_expired_options_kwargs({**base, "expiry_flag": "FORTNIGHT"}, "13")
    with pytest.raises(m.DhanMappingError, match="option_type"):
        m.to_expired_options_kwargs({**base, "option_type": "STRADDLE"}, "13")
    with pytest.raises(m.DhanMappingError, match="required_data"):
        m.to_expired_options_kwargs({**base, "required_data": ["open", "vibes"]}, "13")


def test_from_dhan_expired_options_unwraps_nested_data() -> None:
    resp = {"status": "success", "data": {"data": {
        "ce": {"open": [354, 360.3], "timestamp": [1756698300, 1756699200]},
        "pe": None,
    }}}
    out = m.from_dhan_expired_options(resp)
    assert out["ce"]["open"] == [354, 360.3]
    assert out["pe"] is None
    assert m.from_dhan_expired_options({"status": "success", "data": ""}) == {"ce": None, "pe": None}


# ---------------------------------------------------------------------------
# Order-update WebSocket decode
# ---------------------------------------------------------------------------

_ORDER_ALERT = {
    "Type": "order_alert",
    "Data": {
        "OrderNo": "1124091136546", "ExchOrderNo": "1400000000404591", "Status": "Pending",
        "Symbol": "IDEA", "Exchange": "NSE", "SecurityId": "14366", "TxnType": "B",
        "OrderType": "LMT", "Product": "C", "Quantity": 10, "TradedQty": 4,
        "RemainingQuantity": 6, "Price": 13, "TriggerPrice": 0, "AvgTradedPrice": 12.95,
        "CorrelationId": "FT-1", "LastUpdatedTime": "2026-06-11 14:39:29",
    },
}


def test_order_update_login_payload_matches_doc() -> None:
    payload = m.order_update_login_payload("1000000001", "JWT")
    assert payload == {
        "LoginReq": {"MsgCode": 42, "ClientId": "1000000001", "Token": "JWT"},
        "UserType": "SELF",
    }


def test_decode_order_update_normalises_alert() -> None:
    update = m.decode_order_update(_ORDER_ALERT)
    assert update is not None
    assert update["orderid"] == "1124091136546" and update["status"] == "Pending"
    assert update["action"] == "BUY" and update["pricetype"] == "LIMIT" and update["product"] == "CNC"
    assert update["quantity"] == "10" and update["filled_quantity"] == "4"
    assert update["remaining_quantity"] == "6" and update["average_price"] == "12.95"
    assert update["correlation_id"] == "FT-1" and update["raw"]["Symbol"] == "IDEA"


def test_decode_order_update_accepts_json_text() -> None:
    update = m.decode_order_update(json.dumps(_ORDER_ALERT))
    assert update is not None and update["symbol"] == "IDEA"


def test_decode_order_update_skips_non_alerts() -> None:
    assert m.decode_order_update({"Type": "heartbeat"}) is None
    assert m.decode_order_update({"Type": "order_alert", "Data": "oops"}) is None
    assert m.decode_order_update("{not json") is None
    assert m.decode_order_update(42) is None


# ---------------------------------------------------------------------------
# Binary depth decode (20 / 200 level)
# ---------------------------------------------------------------------------


def _depth_frame(msg_code: int, security_id: int, rows: list[tuple[float, int, int]], seg: int = 1) -> bytes:
    body = b"".join(struct.pack("<dII", price, qty, orders) for price, qty, orders in rows)
    msg_length = 12 + len(body)
    return struct.pack("<hBBiI", msg_length, msg_code, seg, security_id, len(rows)) + body


def test_iter_dhan_depth_messages_decodes_bid_and_ask() -> None:
    frame = _depth_frame(41, 11536, [(2901.5, 100, 3), (2901.0, 50, 2)]) + _depth_frame(
        51, 11536, [(2902.0, 80, 4)]
    )
    messages = m.iter_dhan_depth_messages(frame)
    assert [msg["side"] for msg in messages] == ["bid", "ask"]
    bid, ask = messages
    assert bid["security_id"] == "11536" and bid["exchange"] == "NSE" and bid["rows"] == 2
    assert bid["depth"][0] == {"price": 2901.5, "quantity": 100, "orders": 3}
    assert ask["depth"] == [{"price": 2902.0, "quantity": 80, "orders": 4}]


def test_iter_dhan_depth_messages_skips_unknown_and_truncated() -> None:
    unknown = _depth_frame(50, 11536, [])  # disconnect packet — skipped, offset advances
    good = _depth_frame(41, 49081, [(150.5, 75, 1)], seg=2)
    messages = m.iter_dhan_depth_messages(unknown + good)
    assert len(messages) == 1 and messages[0]["exchange"] == "NFO"
    assert m.iter_dhan_depth_messages(b"") == []
    assert m.iter_dhan_depth_messages(b"\x01\x02\x03") == []
    truncated = _depth_frame(41, 1, [(1.0, 1, 1)])[:-4]  # msg_length overruns the buffer
    assert m.iter_dhan_depth_messages(truncated) == []


# ---------------------------------------------------------------------------
# Live-feed documented response codes (2/4/8)
# ---------------------------------------------------------------------------


def test_decode_dhan_tick_doc_response_codes() -> None:
    # annexure.md feed response codes: 2 Ticker, 4 Quote (legacy 15/17 spellings
    # remain covered by the existing tests above this section).
    ticker = struct.pack("<BHBIfI", 2, 16, 1, 11536, 2901.5, 123456)
    tick = m.decode_dhan_tick(ticker)
    assert tick is not None and tick["code"] == 2 and tick["ltp"] == 2901.5
    quote = struct.pack(
        "<BHBIfHIfIIIffff",
        4, 50, 2, 49081, 150.5, 10, 111, 149.0, 5000, 100, 200, 148.0, 145.0, 152.0, 144.0,
    )
    tick = m.decode_dhan_tick(quote)
    assert tick is not None and tick["code"] == 4 and tick["volume"] == 5000


def test_decode_dhan_tick_full_packet_with_depth() -> None:
    depth_blob = b"".join(
        struct.pack("<IIHHff", 100 + i, 90 + i, 3, 2, 2900.0 - i, 2901.0 + i) for i in range(5)
    )
    frame = struct.pack(
        "<BHBIfHIfIIIIIIffff100s",
        8, 162, 1, 11536, 2901.5, 10, 111, 2900.9, 5000, 100, 200,
        12345, 13000, 12000, 2890.0, 2888.0, 2910.0, 2885.0, depth_blob,
    )
    tick = m.decode_dhan_tick(frame)
    assert tick is not None and tick["code"] == 8
    assert tick["oi"] == 12345 and tick["volume"] == 5000
    assert len(tick["depth"]) == 5
    assert tick["depth"][0]["bid_price"] == 2900.0 and tick["depth"][0]["ask_quantity"] == 90


# ---------------------------------------------------------------------------
# Scrip master -> security resolver
# ---------------------------------------------------------------------------

_SCRIP_ROWS = [
    {"SEM_EXM_EXCH_ID": "NSE", "SEM_SEGMENT": "E", "SEM_SMST_SECURITY_ID": "11536",
     "SEM_TRADING_SYMBOL": "TCS", "SEM_CUSTOM_SYMBOL": "Tata Consultancy Services"},
    {"SEM_EXM_EXCH_ID": "NSE", "SEM_SEGMENT": "D", "SEM_SMST_SECURITY_ID": "49081",
     "SEM_TRADING_SYMBOL": "NIFTY-Jun2026-24000-CE"},
    {"EXCH_ID": "BSE", "SEGMENT": "E", "SECURITY_ID": "532540", "TRADING_SYMBOL": "TCS"},
    {"SEM_EXM_EXCH_ID": "MCX", "SEM_SEGMENT": "M", "SEM_SMST_SECURITY_ID": "428261",
     "SEM_TRADING_SYMBOL": "GOLDPETAL-30Jun2026"},
    {"SEM_EXM_EXCH_ID": "XX", "SEM_SEGMENT": "E", "SEM_SMST_SECURITY_ID": "1"},  # unknown exchange dropped
]


def test_build_security_resolver_resolves_per_exchange() -> None:
    resolve = m.build_security_resolver(_SCRIP_ROWS)
    assert resolve("TCS", "NSE") == "11536"
    assert resolve("tcs", "bse") == "532540"  # detailed-tag row, case-insensitive
    assert resolve("Tata Consultancy Services", "NSE") == "11536"  # display name
    assert resolve("NIFTY-Jun2026-24000-CE", "NFO") == "49081"
    assert resolve("GOLDPETAL-30Jun2026", "MCX") == "428261"


def test_build_security_resolver_fails_closed_on_miss() -> None:
    resolve = m.build_security_resolver(_SCRIP_ROWS)
    with pytest.raises(m.DhanMappingError, match="no security_id"):
        resolve("AAPL", "NSE")
