"""Tests for the canonical-to-IndMoney (INDstocks) mapping tables.

Values are checked against the official INDstocks API docs (captured into
``.local/reference/broker-docs/indmoney/`` on 2026-06-12), and a drift invariant
asserts the mapping covers every exchange IndMoney advertises in BROKER_CATALOG.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from flinttrade_core.exceptions import (
    AuthError,
    BrokerError,
    BrokerInternal,
    BrokerTimeout,
    DataError,
    InsufficientFunds,
    NetworkError,
    OrderError,
    OrderRejectedByBroker,
    RateLimitError,
    SessionExpired,
)
from flinttrade_gateway.adapter import BROKER_CATALOG
from flinttrade_gateway.brokers import indmoney_mapping as m

pytestmark = pytest.mark.unit


def _order(**overrides):
    """A minimal duck-typed order (the mapping reads attributes, not types)."""
    base = {
        "symbol": "RELIANCE",
        "action": "BUY",
        "exchange": "NSE",
        "pricetype": "LIMIT",
        "product": "CNC",
        "quantity": "1",
        "price": "2450",
        "trigger_price": "0",
        "variety": "regular",
        "target_price": "0",
        "stop_loss_price": "0",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Static tables
# ---------------------------------------------------------------------------


def test_order_type_map_has_only_documented_types() -> None:
    # Normal orders accept ONLY LIMIT/MARKET (normal-orders doc) — no SL/SL-M.
    assert m.ORDER_TYPE_MAP == {"MARKET": "MARKET", "LIMIT": "LIMIT"}


def test_product_map_uses_indmoney_names() -> None:
    assert m.PRODUCT_MAP == {"MIS": "INTRADAY", "CNC": "CNC", "NRML": "MARGIN"}


def test_validity_map_values() -> None:
    assert m.VALIDITY_MAP == {"DAY": "DAY", "IOC": "IOC"}


def test_exchange_segment_map_covers_orderable_exchanges_only() -> None:
    assert m.EXCHANGE_SEGMENT_MAP == {
        "NSE": ("NSE", "EQUITY"),
        "BSE": ("BSE", "EQUITY"),
        "NFO": ("NSE", "DERIVATIVE"),
        "BFO": ("BSE", "DERIVATIVE"),
    }


def test_scrip_segment_map_uses_nidx_bidx_for_indices() -> None:
    assert m.SCRIP_SEGMENT_MAP["NSE_INDEX"] == "NIDX"
    assert m.SCRIP_SEGMENT_MAP["BSE_INDEX"] == "BIDX"
    assert m.SCRIP_SEGMENT_MAP["NFO"] == "NFO"


def test_every_advertised_indmoney_exchange_has_a_scrip_mapping() -> None:
    """Drift guard: each exchange in BROKER_CATALOG must be quotable."""
    advertised = BROKER_CATALOG["indmoney"].exchanges
    missing = [e for e in advertised if e not in m.SCRIP_SEGMENT_MAP]
    assert not missing, f"IndMoney exchanges with no scrip-segment mapping: {missing}"


def test_default_algo_id_per_exchange() -> None:
    # 99999 for NSE-family, 9999999999999999 for BSE-family (normal-orders doc).
    assert m.default_algo_id("NSE") == "99999"
    assert m.default_algo_id("NFO") == "99999"
    assert m.default_algo_id("BSE") == "9999999999999999"
    assert m.default_algo_id("BFO") == "9999999999999999"


def test_to_exchange_segment_is_case_insensitive_and_raises_on_unknown() -> None:
    assert m.to_exchange_segment("nfo") == ("NSE", "DERIVATIVE")
    with pytest.raises(m.IndMoneyMappingError, match="NSE/BSE/NFO/BFO"):
        m.to_exchange_segment("MCX")


def test_scrip_code_round_trip() -> None:
    assert m.to_scrip_code("NSE", "2885") == "NSE_2885"
    assert m.to_scrip_code("NSE_INDEX", "26000") == "NIDX_26000"
    assert m.from_scrip_code("NIDX_26000") == ("NSE_INDEX", "26000")
    with pytest.raises(m.IndMoneyMappingError):
        m.to_scrip_code("NASDAQ", "1")


def test_ws_instrument_format() -> None:
    assert m.ws_instrument("NSE", "2885") == "NSE:2885"
    assert m.ws_instrument("NSE_INDEX", "26000") == "NIDX:26000"


def test_segment_from_order_id_prefixes() -> None:
    assert m.segment_from_order_id("DRV-2049") == "DERIVATIVE"
    assert m.segment_from_order_id("EQ-456") == "EQUITY"
    assert m.segment_from_order_id("GTT-2914581") is None  # not inferable
    assert m.is_smart_order_id("GTT-2914581") is True
    assert m.is_smart_order_id("DRV-2049") is False


def test_resolve_segment_precedence() -> None:
    assert m.resolve_segment("GTT-1", {"segment": "derivative"}) == "DERIVATIVE"
    assert m.resolve_segment("GTT-1", {"exchange": "NFO"}) == "DERIVATIVE"
    assert m.resolve_segment("DRV-1", {}) == "DERIVATIVE"
    assert m.resolve_segment("GTT-1", {}) is None


# ---------------------------------------------------------------------------
# Request building — normal orders
# ---------------------------------------------------------------------------


def test_to_place_order_payload_limit() -> None:
    payload = m.to_place_order_payload(_order(), "2885")
    assert payload == {
        "txn_type": "BUY",
        "exchange": "NSE",
        "segment": "EQUITY",
        "product": "CNC",
        "qty": 1,
        "order_type": "LIMIT",
        "validity": "DAY",
        "security_id": "2885",
        "is_amo": False,
        "algo_id": "99999",
        "limit_price": 2450.0,
    }


def test_to_place_order_payload_market_omits_limit_price() -> None:
    payload = m.to_place_order_payload(_order(pricetype="MARKET", price="0"), "2885")
    assert payload["order_type"] == "MARKET"
    assert "limit_price" not in payload


def test_to_place_order_payload_bse_uses_bse_algo_id() -> None:
    payload = m.to_place_order_payload(_order(exchange="BSE", price="850"), "500112")
    assert payload["exchange"] == "BSE" and payload["algo_id"] == "9999999999999999"


def test_to_place_order_payload_derivative_segment() -> None:
    payload = m.to_place_order_payload(_order(exchange="NFO", product="NRML", quantity="75"), "51011")
    assert payload["segment"] == "DERIVATIVE" and payload["product"] == "MARGIN" and payload["qty"] == 75


def test_to_place_order_payload_amo_variety_sets_flag() -> None:
    payload = m.to_place_order_payload(_order(variety="amo"), "2885")
    assert payload["is_amo"] is True


def test_to_place_order_payload_explicit_algo_id_wins() -> None:
    payload = m.to_place_order_payload(_order(), "2885", algo_id="12345")
    assert payload["algo_id"] == "12345"


def test_to_place_order_payload_rejects_sl_pricetypes() -> None:
    # Fails closed — no silent downgrade of a stop order to LIMIT/MARKET.
    with pytest.raises(m.IndMoneyMappingError, match="trigger"):
        m.to_place_order_payload(_order(pricetype="SL"), "2885")
    with pytest.raises(m.IndMoneyMappingError, match="trigger"):
        m.to_place_order_payload(_order(pricetype="SL-M"), "2885")


def test_to_place_order_payload_validation_failures() -> None:
    with pytest.raises(m.IndMoneyMappingError, match="action"):
        m.to_place_order_payload(_order(action="HOLD"), "2885")
    with pytest.raises(m.IndMoneyMappingError, match="product"):
        m.to_place_order_payload(_order(product="MTF"), "2885")
    with pytest.raises(m.IndMoneyMappingError, match="qty"):
        m.to_place_order_payload(_order(quantity="0"), "2885")
    with pytest.raises(m.IndMoneyMappingError, match="limit price"):
        m.to_place_order_payload(_order(price="0"), "2885")
    with pytest.raises(m.IndMoneyMappingError, match="validity"):
        m.to_place_order_payload(_order(validity="GTC"), "2885")


# ---------------------------------------------------------------------------
# Request building — smart orders (GTT family)
# ---------------------------------------------------------------------------


def test_to_smart_order_payload_gtt_with_both_legs() -> None:
    order = _order(
        exchange="NFO", product="NRML", quantity="75", price="37",
        variety="gtt", stop_loss_price="34", target_price="41",
    )
    payload = m.to_smart_order_payload(order, "51011")
    assert payload["segment"] == "DERIVATIVE" and payload["product"] == "MARGIN"
    assert payload["order_type"] == "LIMIT" and payload["limit_price"] == 37.0
    assert payload["validity"] == "DAY"  # smart orders are DAY-only
    assert payload["sl_trigger_price"] == 34.0
    assert payload["tgt_trigger_price"] == 41.0
    # The broker rejects a leg without its limit price — defaulted to the trigger.
    assert payload["sl_limit_price"] == 34.0 and payload["tgt_limit_price"] == 41.0


def test_to_smart_order_payload_distinct_leg_limit_prices() -> None:
    order = _order(
        exchange="NFO", product="NRML", quantity="75", price="37", variety="oco",
        stop_loss_price="34", target_price="41", sl_limit_price="33", tgt_limit_price="42",
    )
    payload = m.to_smart_order_payload(order, "51011")
    assert payload["sl_limit_price"] == 33.0 and payload["tgt_limit_price"] == 42.0


def test_to_smart_order_payload_requires_a_leg() -> None:
    with pytest.raises(m.IndMoneyMappingError, match="leg"):
        m.to_smart_order_payload(_order(variety="gtt"), "2885")


def test_to_smart_order_payload_trigger_market() -> None:
    order = _order(variety="trigger", pricetype="MARKET", price="0", trigger_price="1520")
    payload = m.to_smart_order_payload(order, "3045")
    assert payload["order_type"] == "TRIGGER" and payload["trigger_price"] == 1520.0
    assert "trigger_limit_price" not in payload and "limit_price" not in payload


def test_to_smart_order_payload_trigger_limit() -> None:
    order = _order(variety="trigger", price="38.75", trigger_price="38.50")
    payload = m.to_smart_order_payload(order, "51011")
    assert payload["trigger_price"] == 38.50 and payload["trigger_limit_price"] == 38.75


def test_to_smart_order_payload_trigger_requires_trigger_price() -> None:
    with pytest.raises(m.IndMoneyMappingError, match="trigger_price"):
        m.to_smart_order_payload(_order(variety="trigger", trigger_price="0"), "3045")


# ---------------------------------------------------------------------------
# Request building — modify / cancel / margin
# ---------------------------------------------------------------------------


def test_to_modify_order_payload_derives_segment_from_prefix() -> None:
    payload = m.to_modify_order_payload("DRV-2049", {"qty": 75, "limit_price": 73})
    assert payload == {"order_id": "DRV-2049", "segment": "DERIVATIVE", "qty": 75, "limit_price": 73.0}


def test_to_modify_order_payload_accepts_canonical_keys() -> None:
    payload = m.to_modify_order_payload("EQ-1", {"quantity": "5", "price": "100.5"})
    assert payload["segment"] == "EQUITY" and payload["qty"] == 5 and payload["limit_price"] == 100.5


def test_to_modify_order_payload_validation() -> None:
    with pytest.raises(m.IndMoneyMappingError, match="segment"):
        m.to_modify_order_payload("GTT-1", {"qty": 5, "limit_price": 10})
    with pytest.raises(m.IndMoneyMappingError, match="qty"):
        m.to_modify_order_payload("DRV-1", {"qty": 0, "limit_price": 10})
    with pytest.raises(m.IndMoneyMappingError, match="limit_price"):
        m.to_modify_order_payload("DRV-1", {"qty": 5})


def test_to_smart_modify_payload_passthrough_fields() -> None:
    payload = m.to_smart_modify_payload(
        "DRV-123",
        {"order_type": "LIMIT", "qty": 20, "limit_price": 0.35, "sl_trigger_price": 0.15,
         "tgt_trigger_price": 41, "sl_limit_price": 0.1, "tgt_limit_price": 42},
    )
    assert payload["order_id"] == "DRV-123" and payload["segment"] == "DERIVATIVE"
    assert payload["algo_id"] == "99999"  # mandatory on smart modify
    assert payload["order_type"] == "LIMIT" and payload["qty"] == 20
    assert payload["limit_price"] == 0.35 and payload["sl_limit_price"] == 0.1
    assert payload["tgt_trigger_price"] == 41.0 and payload["tgt_limit_price"] == 42.0


def test_to_smart_modify_payload_trigger_fields() -> None:
    payload = m.to_smart_modify_payload(
        "EQ-456", {"order_type": "TRIGGER", "qty": 10, "trigger_price": 1530.0, "trigger_limit_price": 1532.0}
    )
    assert payload["order_type"] == "TRIGGER"
    assert payload["trigger_price"] == 1530.0 and payload["trigger_limit_price"] == 1532.0


def test_to_cancel_payload_validates_segment() -> None:
    assert m.to_cancel_payload("DRV-2049", "DERIVATIVE") == {"order_id": "DRV-2049", "segment": "DERIVATIVE"}
    with pytest.raises(m.IndMoneyMappingError, match="segment"):
        m.to_cancel_payload("DRV-2049", "FNO")


def test_to_margin_params_string_typed() -> None:
    order = _order(exchange="NFO", product="NRML", quantity="75", price="10")
    params = m.to_margin_params(order, "40131")
    assert params == {
        "segment": "DERIVATIVE",
        "exchange": "NSE",
        "securityID": "40131",
        "txnType": "BUY",
        "quantity": "75",
        "price": "10.0",
        "product": "MARGIN",
    }


# ---------------------------------------------------------------------------
# Envelope + error mapping
# ---------------------------------------------------------------------------


def test_unwrap_success_and_error() -> None:
    assert m.unwrap({"status": "success", "data": {"x": 1}}) == {"x": 1}
    assert m.unwrap([1, 2]) == [1, 2]
    with pytest.raises(m.IndMoneyMappingError, match="boom"):
        m.unwrap({"status": "error", "message": "boom"})


@pytest.mark.parametrize(
    "etype,status,exc",
    [
        ("TokenException", 403, SessionExpired),
        ("UserException", 403, AuthError),
        ("InputException", 400, OrderError),
        ("DataException", 400, DataError),
        ("NotFoundException", 404, BrokerError),
        ("NetworkException", 503, NetworkError),
        ("ServiceUnavailableException", 503, NetworkError),
        ("GatewayTimeoutException", 504, BrokerTimeout),
        ("GeneralException", 500, BrokerInternal),
    ],
)
def test_map_error_documented_error_types(etype, status, exc) -> None:
    mapped = m.map_error(status, {"status": "error", "message": "x", "error_type": etype})
    assert type(mapped) is exc
    assert mapped.broker_id == "indmoney" and mapped.broker_code == etype


def test_map_error_rate_limit_and_rms() -> None:
    assert isinstance(m.map_error(429, {"message": "slow down"}), RateLimitError)
    margin = m.map_error(400, {"message": "RMS: Margin exceeds available balance", "error_type": "OrderException"})
    assert isinstance(margin, InsufficientFunds)
    other = m.map_error(400, {"message": "RMS: Blocked for surveillance", "error_type": "OrderException"})
    assert type(other) is OrderRejectedByBroker
    # Unknown 5xx without error_type still maps to a transient broker error.
    assert isinstance(m.map_error(502, "Bad Gateway"), BrokerInternal)


def test_extract_order_id() -> None:
    assert m.extract_order_id({"status": "success", "data": {"order_id": "DRV-29301125"}}) == "DRV-29301125"
    with pytest.raises(m.IndMoneyMappingError, match="order id"):
        m.extract_order_id({"status": "success", "data": {}})


def test_extract_smart_order_ids_nested_and_flat() -> None:
    nested = {
        "status": "success",
        "data": {"order_data": [{"order_id": "DRV-28131451", "order_status": "CREATED",
                                 "child_order_details": {"order_id": "GTT-2914581", "order_status": "CREATED"}}]},
    }
    assert m.extract_smart_order_ids(nested) == ("DRV-28131451", "GTT-2914581")
    flat = {"status": "success", "data": {"order_id": "GTT-77"}}
    assert m.extract_smart_order_ids(flat) == ("GTT-77", None)
    with pytest.raises(m.IndMoneyMappingError):
        m.extract_smart_order_ids({"status": "success", "data": {}})


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

DOC_ORDER_ROW = {
    "created_at": "2025-07-02T09:18:40.446948+05:30",
    "user_id": "710354",
    "security_id": "56998",
    "isin": "",
    "name": "NIFTY 3 JUL 25700 CE",
    "id": "DRV-28131451",
    "exch_order_id": "1300000002340881",
    "txn_type": "BUY",
    "exchange": "NSE",
    "segment": "DERIVATIVE",
    "product": "MARGIN",
    "order_type": "MARKET",
    "validity": "DAY",
    "traded_qty": 75,
    "requested_qty": 75,
    "requested_price": "43.55",
    "traded_price": "43.55",
    "sl_trigger_price": "",
    "tgt_trigger_price": "",
    "status": "SUCCESS",
    "extra_info": "",
}


def test_from_indmoney_order_doc_sample() -> None:
    row = m.from_indmoney_order(DOC_ORDER_ROW)
    assert row["orderid"] == "DRV-28131451"
    assert row["exchange"] == "NFO"  # NSE + DERIVATIVE reconstructed
    assert row["product"] == "NRML"  # MARGIN reverse-mapped
    assert row["action"] == "BUY" and row["status"] == "SUCCESS"
    assert row["quantity"] == "75" and row["filled_quantity"] == "75"
    assert row["price"] == "43.55" and row["average_price"] == "43.55"
    assert row["exchange_order_id"] == "1300000002340881"


def test_from_indmoney_order_gtt_row_keeps_leg_prices() -> None:
    gtt = dict(DOC_ORDER_ROW, id="GTT-2914581", order_type="OCO", txn_type="SELL",
               sl_trigger_price="0.3", sl_limit_price="0.2", tgt_trigger_price="0.75", status="CANCELLED")
    row = m.from_indmoney_order(gtt)
    assert row["orderid"] == "GTT-2914581" and row["pricetype"] == "OCO"
    assert row["sl_trigger_price"] == "0.3" and row["sl_limit_price"] == "0.2"
    assert row["tgt_trigger_price"] == "0.75"


def test_from_indmoney_trade_doc_sample() -> None:
    trade = m.from_indmoney_trade({
        "trade_id": "INDT20250512XYZ789",
        "order_id": "INDM20250512ABC123",
        "exchange_segment": "NSE_EQ",
        "security_id": "12345",
        "trading_symbol": "RELIANCE-EQ",
        "transaction_type": "BUY",
        "product_type": "CNC",
        "quantity": 5,
        "price": 2500.45,
        "trade_timestamp": "2025-05-12T10:15:35Z",
    })
    assert trade["orderid"] == "INDM20250512ABC123"
    assert trade["symbol"] == "RELIANCE-EQ" and trade["exchange"] == "NSE"
    assert trade["quantity"] == "5" and trade["price"] == "2500.45"
    assert trade["product"] == "CNC" and trade["timestamp"] == "2025-05-12T10:15:35Z"


def test_from_indmoney_tradebook_row_doc_sample() -> None:
    row = m.from_indmoney_tradebook_row({
        "fill_id": 1020280,
        "exch_order_id": "2400000124991381",
        "quantity": 2425,
        "price": 1.55,
        "trade_date": "2025-11-11T17:48:23+05:30",
        "trade_serial_no": "17628437030186581215",
        "scrip_code": "99133",
    })
    assert row["orderid"] == "2400000124991381" and row["fill_id"] == "1020280"
    assert row["quantity"] == "2425" and row["price"] == "1.55"


def test_from_indmoney_position_doc_sample() -> None:
    pos = m.from_indmoney_position({
        "security_id": "67890",
        "trading_symbol": "NIFTY25MAYFUT",
        "exchange_segment": "NSE_FNO",
        "net_quantity": 100,
        "average_price": 18500.00,
        "last_traded_price": 18550.50,
        "pnl_absolute": 5050.00,
    }, product="NRML")
    assert pos["symbol"] == "NIFTY25MAYFUT" and pos["exchange"] == "NFO"
    assert pos["quantity"] == "100" and pos["product"] == "NRML"
    assert pos["pnl"] == "5050.0"


def test_from_indmoney_holding_doc_sample() -> None:
    h = m.from_indmoney_holding({
        "security_id": "12345",
        "trading_symbol": "RELIANCE-EQ",
        "exchange_segment": "NSE_EQ",
        "isin": "INE002A01018",
        "quantity": 50,
        "average_price": 2200.00,
        "last_traded_price": 2505.10,
        "pnl_absolute": 15255.00,
        "pnl_percent": 13.87,
    })
    assert h["symbol"] == "RELIANCE-EQ" and h["exchange"] == "NSE"
    assert h["quantity"] == "50" and h["isin"] == "INE002A01018"
    assert h["pnl_percent"] == "13.87"


def test_from_indmoney_funds_doc_sample() -> None:
    funds = m.from_indmoney_funds({
        "status": "success",
        "data": {
            "sod_balance": 4996.47,
            "withdrawal_balance": 2983.47,
            "detailed_avl_balance": {"eq_cnc": 2980.40},
            "realized_pnl": -751.92,
        },
    })
    assert funds["available_balance"] == "2983.47"
    assert funds["total_balance"] == "4996.47"
    assert funds["used_margin"] == "2013.0"  # sod - withdrawal
    assert funds["extra"]["detailed_avl_balance"]["eq_cnc"] == 2980.40


def test_from_indmoney_funds_tolerates_garbage() -> None:
    funds = m.from_indmoney_funds("not json")
    assert funds["available_balance"] == "0" and funds["extra"] == {}


def test_from_indmoney_margin_doc_sample() -> None:
    margin = m.from_indmoney_margin({
        "status": "success",
        "data": {
            "total_margin": 750, "span_margin": 0, "exposure_margin": 0,
            "available_balance": 0, "insufficient_balance": 0, "brokerage": 0,
            "charges": {"brokerage": 5, "gst": 0.9, "total_charges": 5.9},
        },
    })
    assert margin["required_margin"] == "750" and margin["total_margin"] == "750"
    assert margin["charges"]["total_charges"] == 5.9


def test_parse_indian_number() -> None:
    assert m.parse_indian_number("5,82,909") == 582909.0
    assert m.parse_indian_number("788.95") == 788.95
    assert m.parse_indian_number(None) == 0.0


DOC_DEPTH = {
    "market_depth": {
        "aggregate": {"total_buy": "5,82,909", "total_sell": "11,01,938"},
        "depth": [
            {"buy": {"quantity": "6.00", "price": "788.95"}, "sell": {"quantity": "21.00", "price": "789.00"}},
            {"buy": {"quantity": "2,318", "price": "788.60"}, "sell": {"quantity": "1,792", "price": "789.15"}},
        ],
    }
}


def test_from_indmoney_depth_parses_indian_grouping() -> None:
    depth = m.from_indmoney_depth(DOC_DEPTH)
    assert depth["total_buy"] == 582909.0 and depth["total_sell"] == 1101938.0
    assert depth["bids"][0] == {"price": 788.95, "quantity": 6}
    assert depth["asks"][1] == {"price": 789.15, "quantity": 1792}


def test_from_indmoney_quote_doc_sample() -> None:
    q = dict(
        live_price=788.8, day_change=-3.5, day_low=788.35, day_high=795.5,
        day_open=792.5, prev_close=792.3, volume=3546732, **DOC_DEPTH,
    )
    quote = m.from_indmoney_quote("RELIANCE", "NSE", q)
    assert quote["ltp"] == 788.8 and quote["open"] == 792.5
    assert quote["high"] == 795.5 and quote["low"] == 788.35
    assert quote["close"] == 792.3 and quote["prev_close"] == 792.3
    assert quote["volume"] == 3546732
    assert quote["bid"] == 788.95 and quote["ask"] == 789.00


# ---------------------------------------------------------------------------
# Historical data
# ---------------------------------------------------------------------------


def test_interval_to_indmoney_canonical_and_raw_labels() -> None:
    assert m.interval_to_indmoney("1m") == ("1minute", 7)
    assert m.interval_to_indmoney("1s") == ("1second", 1)
    assert m.interval_to_indmoney("1h") == ("60minute", 14)
    assert m.interval_to_indmoney("4h") == ("240minute", 14)
    assert m.interval_to_indmoney("D") == ("1day", 365)
    assert m.interval_to_indmoney("1w") == ("1week", 365)
    assert m.interval_to_indmoney("5minute") == ("5minute", 7)  # raw label passthrough
    with pytest.raises(m.IndMoneyMappingError, match="interval"):
        m.interval_to_indmoney("45m")


def test_to_epoch_ms_forms() -> None:
    assert m.to_epoch_ms(1750055540000) == 1750055540000  # ms passthrough
    assert m.to_epoch_ms(1750055540) == 1750055540000  # seconds promoted
    assert m.to_epoch_ms("1750055540000") == 1750055540000
    ist = timezone(timedelta(hours=5, minutes=30))
    expected = int(datetime(2025, 6, 1, tzinfo=ist).timestamp() * 1000)
    assert m.to_epoch_ms("2025-06-01") == expected  # IST midnight (broker convention)
    with pytest.raises(m.IndMoneyMappingError):
        m.to_epoch_ms("yesterday")


def test_validate_history_range() -> None:
    day_ms = 86_400_000
    m.validate_history_range(0, 7 * day_ms, 7)  # exactly at the cap is fine
    with pytest.raises(m.IndMoneyMappingError, match="maximum"):
        m.validate_history_range(0, 8 * day_ms, 7)
    with pytest.raises(m.IndMoneyMappingError, match="after"):
        m.validate_history_range(10, 10, 7)


def test_to_candles_dict_doc_sample() -> None:
    resp = {
        "status": "success",
        "data": {"candles": [
            [1678886400000, 2500.00, 2501.50, 2499.50, 2501.00, 500],
            [1678886460000, 2501.00, 2502.00, 2500.50, 2501.80, 650],
            ["short row"],
        ]},
    }
    cd = m.to_candles_dict("RELIANCE", "NSE", "1m", resp)
    assert cd["symbol"] == "RELIANCE" and len(cd["bars"]) == 2  # short row skipped
    assert cd["bars"][0] == {
        "timestamp": "1678886400000", "open": 2500.0, "high": 2501.5,
        "low": 2499.5, "close": 2501.0, "volume": 500,
    }


def test_parse_instruments_csv() -> None:
    text = (
        "EXCH,SEGMENT,SECURITY_ID,TRADING_SYMBOL,LOT_UNITS,TICK_SIZE\n"
        "NSE,E,2885,RELIANCE-EQ,1,0.05\n"
        "NSE,FNO,51011,NIFTY25JUL25000CE,75,0.05\n"
    )
    rows = m.parse_instruments_csv(text)
    assert len(rows) == 2
    assert rows[0]["SECURITY_ID"] == "2885" and rows[1]["LOT_UNITS"] == "75"


# ---------------------------------------------------------------------------
# WebSocket codecs
# ---------------------------------------------------------------------------


def test_subscribe_message_modes_and_actions() -> None:
    import json

    msg = json.loads(m.subscribe_message(["NSE:2885"], "LTP"))
    assert msg == {"action": "subscribe", "mode": "ltp", "instruments": ["NSE:2885"]}
    msg = json.loads(m.subscribe_message(["NFO:51011"], "FULL", action="unsubscribe"))
    assert msg["mode"] == "quote" and msg["action"] == "unsubscribe"
    with pytest.raises(m.IndMoneyMappingError, match="mode"):
        m.subscribe_message(["NSE:2885"], "DEPTH20")
    with pytest.raises(m.IndMoneyMappingError, match="action"):
        m.subscribe_message(["NSE:2885"], "LTP", action="resubscribe")


def test_order_updates_subscribe_message() -> None:
    import json

    assert json.loads(m.order_updates_subscribe_message()) == {"action": "subscribe", "mode": "order_updates"}


def test_decode_price_frame_doc_sample() -> None:
    raw = '{"mode": "ltp", "instrument": "2885", "timestamp": 1750138351089, "data": {"ltp": 1426}}'
    tick = m.decode_price_frame(raw)
    assert tick == {
        "mode": "ltp", "security_id": "2885", "timestamp": "1750138351089",
        "ltp": 1426.0, "volume": 0,
    }
    # bytes frames decode identically
    assert m.decode_price_frame(raw.encode("utf-8")) == tick


def test_decode_price_frame_skips_noise() -> None:
    assert m.decode_price_frame('{"type": "heartbeat"}') is None  # heartbeat
    assert m.decode_price_frame("not json") is None
    assert m.decode_price_frame("[1,2,3]") is None
    assert m.decode_price_frame(b"\xff\xfe") is None


def test_decode_order_update_doc_sample() -> None:
    raw = (
        '{"type": "order", "order_id": "INDM20250512ABC123", "order_status": "PARTIALLY_EXECUTED",'
        ' "filled_quantity": 5, "remaining_quantity": 5, "average_price": 2500.40, "timestamp": 1678886530456}'
    )
    update = m.decode_order_update(raw)
    assert update == {
        "orderid": "INDM20250512ABC123",
        "status": "PARTIALLY_EXECUTED",
        "filled_quantity": "5",
        "remaining_quantity": "5",
        "average_price": "2500.4",
        "timestamp": "1678886530456",
    }


def test_decode_order_update_skips_non_order_frames() -> None:
    assert m.decode_order_update('{"type": "heartbeat"}') is None
    assert m.decode_order_update("garbage") is None
