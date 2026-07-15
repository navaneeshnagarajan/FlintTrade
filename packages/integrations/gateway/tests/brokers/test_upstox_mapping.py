"""Unit tests for the full FlintTrade <-> Upstox v2/v3 mapping surface.

Covers every mapping function added in the parity wave: OAuth helpers, the v3
place/multi-order/GTT builders, convert-position, brokerage, v3 quote parsing,
reports, market information, feed-authorisation and decoded-feed-tick parsing.
The original v2 order/read mappings are covered by
``tests/brokers/test_upstox_mapping_base.py``; the request-building assertions here are
verified against the staged SDK models in
``.local/reference/broker-sdks/upstox-python/docs/``.
"""

from __future__ import annotations

import json

import pytest

from flinttrade_core.exceptions import (
    BrokerError,
    InsufficientFunds,
    InvalidPrice,
    InvalidQuantity,
    OrderRejectedByBroker,
    RateLimitError,
    SessionExpired,
)
from flinttrade_core.models import Order
from flinttrade_gateway.brokers import upstox_mapping as m

pytestmark = pytest.mark.unit


class _StandInApiException(Exception):
    """ApiException-shaped stand-in (the upstox-python SDK is not installed).

    Mirrors ``upstox_client.rest.ApiException``: same class name + ``status`` /
    ``reason`` / ``body`` attribute shape, so ``is_api_exception`` duck-types it.
    """

    def __init__(self, status, body=None, reason=""):
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.body = body
        self.headers = None


# Rename so duck-typing by class name (``ApiException``) matches the real SDK.
_StandInApiException.__name__ = "ApiException"


def _err_body(error_code: str, message: str) -> bytes:
    """Build an ApiGatewayErrorResponse-shaped JSON error body (as bytes).

    Uses the REAL wire key ``errorCode`` (camelCase) — ``ApiException.body`` is
    the raw HTTP data and the SDK ``Problem`` model maps ``error_code ->
    "errorCode"``. A snake_case fixture would not exercise the parser honestly.
    """
    return json.dumps({"status": "error", "errors": [{"errorCode": error_code, "message": message}]}).encode("utf-8")


def _order(**kw) -> Order:
    base = dict(
        symbol="RELIANCE", action="BUY", exchange="NSE", pricetype="LIMIT", product="MIS", quantity="10", price="2900"
    )
    base.update(kw)
    return Order(**base)


# ---------------------------------------------------------------------------
# Auth: login URL + token exchange
# ---------------------------------------------------------------------------


def test_build_login_url_encodes_required_params():
    url = m.build_login_url("api-key-1", "https://app.local/cb")
    assert url.startswith(m.UPSTOX_LOGIN_DIALOG_URL + "?")
    assert "response_type=code" in url
    assert "client_id=api-key-1" in url
    assert "redirect_uri=https%3A%2F%2Fapp.local%2Fcb" in url
    assert "state=" not in url


def test_build_login_url_with_state_and_missing_args():
    assert "state=xyz" in m.build_login_url("k", "https://r", "xyz")
    with pytest.raises(m.UpstoxMappingError, match="client_id"):
        m.build_login_url("", "https://r")


def test_to_token_request_params_builds_grant_form():
    p = m.to_token_request_params(
        {
            "code": "mk404x",
            "api_key": "K1",
            "api_secret": "S1",
            "redirect_uri": "https://r",
        }
    )
    assert p == {
        "code": "mk404x",
        "client_id": "K1",
        "client_secret": "S1",
        "redirect_uri": "https://r",
        "grant_type": "authorization_code",
    }


def test_to_token_request_params_accepts_client_id_aliases_and_raises_when_incomplete():
    p = m.to_token_request_params(
        {
            "code": "c",
            "client_id": "K",
            "client_secret": "S",
            "redirect_uri": "https://r",
        }
    )
    assert p["client_id"] == "K" and p["client_secret"] == "S"
    with pytest.raises(m.UpstoxMappingError, match="token exchange"):
        m.to_token_request_params({"code": "c", "api_key": "K"})


def test_extract_access_token():
    assert m.extract_access_token({"access_token": "T1"}) == "T1"
    assert m.extract_access_token({"data": {"access_token": "T2"}}) == "T2"
    with pytest.raises(m.UpstoxMappingError, match="access_token"):
        m.extract_access_token({"data": {}})


# ---------------------------------------------------------------------------
# Orders: v2 AMO + v3 slice + multi-order builders
# ---------------------------------------------------------------------------


def test_place_order_amo_variety_sets_is_amo():
    p = m.to_place_order_params(_order(variety="amo"), "NSE_EQ|X", tag="A1")
    assert p["is_amo"] is True and p["tag"] == "A1"
    regular = m.to_place_order_params(_order(), "NSE_EQ|X")
    assert regular["is_amo"] is False


# ---------------------------------------------------------------------------
# Validity pass-through (PlaceOrderRequest.validity: DAY | IOC)
# ---------------------------------------------------------------------------


def test_place_order_validity_defaults_to_day_and_maps_ioc():
    # None / unset → DAY (Upstox default); explicit IOC survives the build.
    assert m.to_place_order_params(_order(), "NSE_EQ|X")["validity"] == "DAY"
    assert m.to_place_order_params(_order(validity="IOC"), "NSE_EQ|X")["validity"] == "IOC"
    # Lower-case is normalised.
    assert m.to_place_order_params(_order(validity="ioc"), "NSE_EQ|X")["validity"] == "IOC"


def test_place_order_ioc_survives_v3_and_multi_builders():
    assert m.to_place_order_v3_params(_order(validity="IOC"), "NSE_EQ|X")["validity"] == "IOC"
    payloads = m.to_multi_order_params([(_order(validity="IOC"), "NSE_EQ|A")])
    assert payloads[0]["validity"] == "IOC"


def test_place_order_rejects_unsupported_validity():
    # Upstox place accepts only DAY/IOC; GTC/GTD/EOS must be refused, not
    # silently coerced to DAY.
    with pytest.raises(m.UpstoxMappingError, match="DAY/IOC"):
        m.to_place_order_params(_order(validity="GTC"), "NSE_EQ|X")


def test_modify_order_validity_validated():
    assert m.to_modify_order_params("OID1", {"validity": "IOC"})["validity"] == "IOC"
    assert m.to_modify_order_params("OID1", {})["validity"] == "DAY"
    with pytest.raises(m.UpstoxMappingError, match="DAY/IOC"):
        m.to_modify_order_params("OID1", {"validity": "GTD"})


def test_place_order_v3_params_slices_iceberg():
    p = m.to_place_order_v3_params(_order(variety="iceberg", quantity="50000"), "NSE_EQ|X", tag="B")
    assert p["slice"] is True and p["is_amo"] is False
    assert p["quantity"] == 50000 and p["instrument_token"] == "NSE_EQ|X"
    assert p["order_type"] == "LIMIT" and p["transaction_type"] == "BUY" and p["product"] == "I"
    assert p["validity"] == "DAY" and p["tag"] == "B"


def test_place_order_v3_params_regular_amo_and_refusals():
    assert m.to_place_order_v3_params(_order(), "NSE_EQ|X")["slice"] is False
    assert m.to_place_order_v3_params(_order(variety="amo"), "NSE_EQ|X")["is_amo"] is True
    for variety in ("gtt", "bracket", "cover"):
        with pytest.raises(m.UpstoxMappingError, match="variety"):
            m.to_place_order_v3_params(_order(variety=variety), "NSE_EQ|X")


def test_to_multi_order_params_assigns_correlation_ids():
    orders = [(_order(), "NSE_EQ|A"), (_order(action="SELL", quantity="5"), "NSE_EQ|B")]
    payloads = m.to_multi_order_params(orders, tag="BATCH")
    assert [p["correlation_id"] for p in payloads] == ["1", "2"]
    assert payloads[0]["instrument_token"] == "NSE_EQ|A"
    assert payloads[1]["transaction_type"] == "SELL" and payloads[1]["quantity"] == 5
    assert all(p["tag"] == "BATCH" for p in payloads)


def test_to_multi_order_params_rejects_empty_and_bad_variety():
    with pytest.raises(m.UpstoxMappingError, match="at least one"):
        m.to_multi_order_params([])
    with pytest.raises(m.UpstoxMappingError, match="variety"):
        m.to_multi_order_params([(_order(variety="gtt"), "NSE_EQ|X")])


def test_from_upstox_multi_order_collects_ids_errors_and_summary():
    out = m.from_upstox_multi_order(
        {
            "status": "partial_success",
            "data": [{"order_id": "O1", "correlation_id": "1"}],
            "errors": [{"error_code": "E1", "correlation_id": "2"}],
            "summary": {"total": 2, "success": 1},
        }
    )
    assert out["order_ids"] == ["O1"] and out["total"] == 2 and out["success"] == 1
    assert out["order_results"] == [{"order_id": "O1", "correlation_id": "1"}]
    assert out["errors"][0]["error_code"] == "E1"
    with pytest.raises(m.UpstoxMappingError):
        m.from_upstox_multi_order(None)  # type: ignore[arg-type]


def test_from_upstox_cancel_exit_parses_order_ids():
    out = m.from_upstox_cancel_exit(
        {
            "status": "success",
            "data": {"order_ids": ["C1", "C2"]},
            "errors": None,
            "summary": {"total": 2, "success": 2, "error": 0},
        }
    )
    assert out["order_ids"] == ["C1", "C2"] and out["success"] == 2


def test_from_upstox_cancel_exit_accepts_printable_nfc_order_id():
    out = m.from_upstox_cancel_exit(
        {
            "status": "success",
            "data": {"order_ids": ["\u0106-1"]},
            "errors": None,
            "summary": {"total": 1, "success": 1, "error": 0},
        }
    )

    assert out["order_ids"] == ["\u0106-1"]


def test_from_upstox_cancel_exit_accepts_explicit_empty_success_batch():
    out = m.from_upstox_cancel_exit(
        {
            "status": "success",
            "data": {"order_ids": []},
            "errors": None,
            "summary": {"total": 0, "success": 0, "error": 0},
        }
    )

    assert out == {"order_ids": [], "errors": [], "total": 0, "success": 0}


def test_from_upstox_cancel_exit_accepts_structurally_valid_partial_success():
    out = m.from_upstox_cancel_exit(
        {
            "status": "partial_success",
            "data": {"order_ids": ["C1"]},
            "errors": [{"error_code": "UDAPI1113", "message": "market closed"}],
            "summary": {"total": 2, "success": 1, "error": 1},
        }
    )

    assert out["order_ids"] == ["C1"]
    assert out["total"] == 2
    assert out["success"] == 1
    assert len(out["errors"]) == 1


@pytest.mark.parametrize(
    "response",
    [
        {"status": "error", "message": "sweep refused"},
        {"status": "success"},
        {"status": "success", "data": {}, "summary": {"total": 0, "success": 0, "error": 0}},
        {"status": "success", "data": {"order_ids": []}, "summary": {}},
        {
            "status": "success",
            "data": {"order_ids": []},
            "summary": {"total": 1, "success": 1, "error": 0},
        },
        {
            "status": "success",
            "data": {"order_ids": ["C1"]},
            "summary": {"total": 1.5, "success": 1, "error": 0},
        },
        {
            "status": "success",
            "data": {"order_ids": ["   "]},
            "summary": {"total": 1, "success": 1, "error": 0},
        },
        {
            "status": "success",
            "data": {"order_ids": [" C1 "]},
            "summary": {"total": 1, "success": 1, "error": 0},
        },
        {
            "status": "success",
            "data": {"order_ids": ["C1", "C1"]},
            "summary": {"total": 2, "success": 2, "error": 0},
        },
        {
            "status": "success",
            "data": {"order_ids": ["C1\u200b"]},
            "summary": {"total": 1, "success": 1, "error": 0},
        },
        {
            "status": "success",
            "data": {"order_ids": ["C1\x00"]},
            "summary": {"total": 1, "success": 1, "error": 0},
        },
        {
            "status": "success",
            "data": {"order_ids": ["C\u0301"]},
            "summary": {"total": 1, "success": 1, "error": 0},
        },
    ],
)
def test_from_upstox_cancel_exit_rejects_error_or_invalid_batch(response):
    with pytest.raises(m.UpstoxMappingError, match="cancel/exit"):
        m.from_upstox_cancel_exit(response)


# ---------------------------------------------------------------------------
# GTT builders + parsing
# ---------------------------------------------------------------------------


def test_to_gtt_place_params_single_entry_rule():
    p = m.to_gtt_place_params(_order(variety="gtt", trigger_price="2850"), "NSE_EQ|X")
    assert p["type"] == "SINGLE" and p["instrument_token"] == "NSE_EQ|X"
    assert p["transaction_type"] == "BUY" and p["product"] == "I" and p["quantity"] == 10
    assert p["rules"] == [{"strategy": "ENTRY", "trigger_type": "ABOVE", "trigger_price": 2850.0}]


def test_to_gtt_place_params_multiple_with_stoploss_and_target():
    order = _order(variety="gtt", trigger_price="2850", stop_loss_price="2800", target_price="2950")
    p = m.to_gtt_place_params(order, "NSE_EQ|X")
    assert p["type"] == "MULTIPLE"
    strategies = [r["strategy"] for r in p["rules"]]
    assert strategies == ["ENTRY", "STOPLOSS", "TARGET"]
    assert p["rules"][1]["trigger_price"] == 2800.0 and p["rules"][2]["trigger_price"] == 2950.0


def test_to_gtt_place_params_requires_trigger_price():
    with pytest.raises(m.UpstoxMappingError, match="trigger_price"):
        m.to_gtt_place_params(_order(variety="gtt"), "NSE_EQ|X")


def test_to_gtt_modify_params_rebuilds_rules():
    p = m.to_gtt_modify_params(
        "GTT-1",
        {"quantity": 20, "trigger_price": 100, "entry_trigger_type": "BELOW", "target_price": 110},
    )
    assert p["gtt_order_id"] == "GTT-1" and p["quantity"] == 20 and p["type"] == "MULTIPLE"
    assert [r["strategy"] for r in p["rules"]] == ["ENTRY", "TARGET"]
    assert p["rules"][0]["trigger_type"] == "BELOW"
    assert p["rules"][1]["trigger_type"] == "IMMEDIATE"
    with pytest.raises(m.UpstoxMappingError, match="gtt_order_id"):
        m.to_gtt_modify_params("", {"trigger_price": 100})


def test_gtt_protective_legs_use_immediate_trigger_type_from_docs():
    buy = m.to_gtt_place_params(
        _order(variety="gtt", action="BUY", trigger_price="2850", stop_loss_price="2800", target_price="2950"),
        "NSE_EQ|X",
    )
    by_strategy = {r["strategy"]: r for r in buy["rules"]}
    assert by_strategy["ENTRY"]["trigger_type"] == "ABOVE"
    assert by_strategy["STOPLOSS"]["trigger_type"] == "IMMEDIATE"
    assert by_strategy["TARGET"]["trigger_type"] == "IMMEDIATE"

    sell = m.to_gtt_place_params(
        _order(variety="gtt", action="SELL", trigger_price="2850", stop_loss_price="2900", target_price="2750"),
        "NSE_EQ|X",
    )
    by_strategy = {r["strategy"]: r for r in sell["rules"]}
    assert by_strategy["STOPLOSS"]["trigger_type"] == "IMMEDIATE"
    assert by_strategy["TARGET"]["trigger_type"] == "IMMEDIATE"


def test_gtt_entry_trigger_type_override_and_validation():
    order = _order(variety="gtt", action="BUY", trigger_price="2850", stop_loss_price="2800")
    object.__setattr__(order, "entry_trigger_type", "BELOW")
    p = m.to_gtt_place_params(order, "NSE_EQ|X")
    entry = next(r for r in p["rules"] if r["strategy"] == "ENTRY")
    assert entry["trigger_type"] == "BELOW"

    bad = _order(variety="gtt", action="BUY", trigger_price="2850", stop_loss_price="2800")
    object.__setattr__(bad, "entry_trigger_type", "SIDEWAYS")
    with pytest.raises(m.UpstoxMappingError, match="trigger_type"):
        m.to_gtt_place_params(bad, "NSE_EQ|X")


def test_gtt_protective_trigger_type_rejects_non_immediate_override():
    bad = _order(variety="gtt", action="BUY", trigger_price="2850", stop_loss_price="2800")
    object.__setattr__(bad, "stop_loss_trigger_type", "BELOW")
    with pytest.raises(m.UpstoxMappingError, match="IMMEDIATE"):
        m.to_gtt_place_params(bad, "NSE_EQ|X")


def test_to_gtt_cancel_params_and_id_detection():
    assert m.to_gtt_cancel_params("GTT-CU25") == {"gtt_order_id": "GTT-CU25"}
    with pytest.raises(m.UpstoxMappingError, match="gtt_order_id"):
        m.to_gtt_cancel_params("")
    assert m.is_gtt_order_id("GTT-CU25270200024002") is True
    assert m.is_gtt_order_id("240221025997024") is False


def test_extract_gtt_order_id_variants():
    assert m.extract_gtt_order_id({"data": {"gtt_order_ids": ["GTT-9"]}}) == "GTT-9"
    assert m.extract_gtt_order_id({"data": {"gtt_order_id": "GTT-8"}}) == "GTT-8"
    with pytest.raises(m.UpstoxMappingError, match="GTT"):
        m.extract_gtt_order_id({"data": {}})


def test_from_upstox_gtt_order_normalises_rules():
    out = m.from_upstox_gtt_order(
        {
            "gtt_order_id": "GTT-CU1",
            "type": "MULTIPLE",
            "trading_symbol": "NHPC",
            "exchange": "NSE",
            "product": "D",
            "quantity": 1,
            "rules": [
                {
                    "strategy": "ENTRY",
                    "status": "TRIGGERED",
                    "trigger_price": 7.7,
                    "transaction_type": "BUY",
                    "order_id": "250228010168535",
                },
                {
                    "strategy": "STOPLOSS",
                    "status": "PENDING",
                    "trigger_price": 7.6,
                    "transaction_type": "SELL",
                    "order_id": None,
                },
            ],
            "created_at": 1740641185000000,
            "expires_at": 1772216999000000,
        }
    )
    assert out["gtt_order_id"] == "GTT-CU1" and out["product"] == "CNC"  # equity D -> CNC
    assert out["rules"][0]["order_id"] == "250228010168535"
    assert out["rules"][1]["strategy"] == "STOPLOSS" and out["rules"][1]["order_id"] == ""


def test_from_upstox_trade_and_gtt_disambiguate_fno_product_d():
    # Upstox product "D" is delivery (CNC) for equity but carry-forward (NRML)
    # for F&O. The trade and GTT read paths must disambiguate by segment, not
    # blindly map D->CNC (which would mislabel every F&O record).
    trade = m.from_upstox_trade(
        {
            "order_id": "9",
            "trading_symbol": "BANKNIFTY",
            "exchange": "NFO",
            "transaction_type": "SELL",
            "product": "D",
            "quantity": 15,
            "average_price": 1.2,
        }
    )
    assert trade["product"] == "NRML"
    gtt = m.from_upstox_gtt_order(
        {
            "gtt_order_id": "GTT-F1",
            "type": "SINGLE",
            "trading_symbol": "NIFTY",
            "exchange": "NFO",
            "product": "D",
            "quantity": 50,
            "rules": [],
        }
    )
    assert gtt["product"] == "NRML"
    # An equity trade still maps D -> CNC.
    eq = m.from_upstox_trade(
        {
            "order_id": "10",
            "trading_symbol": "TCS",
            "exchange": "NSE",
            "transaction_type": "BUY",
            "product": "D",
            "quantity": 5,
            "average_price": 3500,
        }
    )
    assert eq["product"] == "CNC"


def test_upstox_cds_position_preserves_multiplier_and_previous_close():
    position = m.from_upstox_position(
        {
            "exchange": "CDS",
            "multiplier": 1000,
            "product": "D",
            "instrument_token": "NCD_FO|USDINR23OCT85.5CE",
            "average_price": 0.005,
            "quantity": 1,
            "overnight_quantity": 1,
            "day_buy_quantity": 0,
            "day_sell_quantity": 0,
            "last_price": 0.0025,
            "close_price": 0.0025,
            "trading_symbol": "USDINR23OCT85.5CE",
        }
    )

    assert position["exchange"] == "CDS"
    assert position["product"] == "NRML"
    assert position["multiplier"] == 1000
    assert position["close_price"] == 0.0025
    assert position["instrument_id"] == "NCD_FO|USDINR23OCT85.5CE"
    assert position["accounting_complete"] is True
    assert position["cross_currency"] is False
    assert position["previous_close_trusted"] is True


def test_upstox_option_position_preserves_explicit_contract_type() -> None:
    position = m.from_upstox_position(
        {
            "trading_symbol": "NIFTY 30 JUL 26 25000 CE",
            "instrument_token": "NSE_FO|54452",
            "exchange": "NFO",
            "segment": "NSE_FO",
            "instrument_type": "CE",
            "product": "D",
            "quantity": 75,
            "overnight_quantity": 0,
            "day_buy_quantity": 75,
            "day_sell_quantity": 0,
        }
    )

    assert position["option_type"] == "CE"


def test_upstox_holding_preserves_delivery_ledger_identity_and_close():
    holding = m.from_upstox_holding(
        {
            "exchange": "NSE",
            "product": "D",
            "instrument_token": "NSE_EQ|INE528G01035",
            "trading_symbol": "YESBANK",
            "quantity": 36,
            "average_price": 18.75,
            "last_price": 17.05,
            "close_price": 17.0,
            "pnl": -61.2,
        }
    )

    assert holding["exchange"] == "NSE"
    assert holding["product"] == "CNC"
    assert holding["close_price"] == 17.0
    assert holding["instrument_id"] == "NSE_EQ|INE528G01035"
    assert holding["accounting_complete"] is True


def test_upstox_rejects_inconsistent_complete_position_accounting() -> None:
    with pytest.raises(m.UpstoxMappingError, match="position accounting is inconsistent"):
        m.from_upstox_position({
            "trading_symbol": "TCS",
            "exchange": "NSE",
            "product": "D",
            "quantity": 5,
            "overnight_quantity": 4,
            "day_buy_quantity": 0,
            "day_sell_quantity": 0,
        })


def test_upstox_trade_prefers_exchange_execution_timestamp() -> None:
    trade = m.from_upstox_trade({
        "order_id": "10",
        "trading_symbol": "TCS",
        "exchange": "NSE",
        "transaction_type": "BUY",
        "product": "D",
        "quantity": 5,
        "average_price": 3500,
        "order_timestamp": "2026-07-13T09:20:00+05:30",
        "exchange_timestamp": "2026-07-13T09:21:00+05:30",
    })

    assert trade["timestamp"] == "2026-07-13T09:21:00+05:30"


def test_upstox_v3_funds_map_opening_cash_without_margin_inference():
    funds = m.from_upstox_funds(
        {
            "status": "success",
            "data": {
                "available_to_trade": {
                    "total": 5379.03,
                    "cash_available_to_trade": {
                        "total": 5117.34,
                        "cash": {"opening_balance": 5137.34},
                        "margin_used": {"total": 0.0},
                    },
                    "pledge_available_to_trade": {
                        "total": 261.69,
                        "margin_used": {"total": 1.8},
                    },
                },
                "unavailable_to_trade": {},
            },
        }
    )

    assert funds["available_balance"] == "5379.03"
    assert funds["used_margin"] == "1.8"
    assert funds["total_balance"] == "5380.83"
    assert funds["opening_risk_capital"] == "5137.34"


def test_upstox_v2_funds_do_not_infer_opening_risk_capital():
    funds = m.from_upstox_funds(
        {
            "status": "success",
            "data": {"equity": {"available_margin": 50000, "used_margin": 12000}},
        }
    )

    assert funds["available_balance"] == "50000"
    assert funds["total_balance"] == "62000.0"
    assert funds["opening_risk_capital"] == "0"


# ---------------------------------------------------------------------------
# Product disambiguation: Upstox "D" → CNC (equity) vs NRML (F&O carry-forward)
# ---------------------------------------------------------------------------


def test_from_upstox_order_equity_d_is_cnc():
    # An equity-segment "D" position is delivery → CNC.
    out = m.from_upstox_order(
        {
            "order_id": "1",
            "trading_symbol": "RELIANCE",
            "instrument_token": "NSE_EQ|INE002A01018",
            "product": "D",
            "transaction_type": "BUY",
            "order_type": "LIMIT",
            "quantity": 1,
            "price": 2900,
        }
    )
    assert out["exchange"] == "NSE" and out["product"] == "CNC"


def test_from_upstox_order_fno_d_is_nrml():
    # An F&O-segment "D" position is carry-forward → NRML, NOT CNC. Reading it
    # back as CNC would feed reconciliation the wrong product.
    out = m.from_upstox_order(
        {
            "order_id": "2",
            "trading_symbol": "NIFTY 24600 CE",
            "instrument_token": "NSE_FO|54452",
            "product": "D",
            "transaction_type": "SELL",
            "order_type": "MARKET",
            "quantity": 75,
        }
    )
    assert out["exchange"] == "NFO" and out["product"] == "NRML"


def test_from_upstox_position_d_disambiguated_by_segment():
    equity = m.from_upstox_position(
        {
            "trading_symbol": "TCS",
            "instrument_token": "NSE_EQ|INE467B01029",
            "product": "D",
            "quantity": 5,
            "average_price": 3500,
        }
    )
    fno = m.from_upstox_position(
        {
            "trading_symbol": "BANKNIFTY FUT",
            "instrument_token": "NSE_FO|99999",
            "product": "D",
            "quantity": 15,
            "average_price": 50000,
        }
    )
    assert equity["product"] == "CNC"
    assert fno["product"] == "NRML"
    # MTF still maps to NRML regardless of segment (unambiguous code).
    mtf = m.from_upstox_position(
        {
            "trading_symbol": "SBIN",
            "instrument_token": "NSE_EQ|INE062A01020",
            "product": "MTF",
            "quantity": 100,
            "average_price": 600,
        }
    )
    assert mtf["product"] == "NRML"


def test_from_upstox_d_uses_explicit_segment_field_when_present():
    # When the record carries an explicit Upstox segment string, an F&O segment
    # disambiguates "D" to NRML even if the exchange field is generic.
    out = m.from_upstox_position(
        {
            "trading_symbol": "GOLD FUT",
            "exchange": "MCX",
            "segment": "MCX_FO",
            "product": "D",
            "quantity": 1,
            "average_price": 70000,
        }
    )
    assert out["product"] == "NRML"


# ---------------------------------------------------------------------------
# Convert position + brokerage
# ---------------------------------------------------------------------------


def test_to_convert_position_params_intraday_to_delivery():
    p = m.to_convert_position_params(
        {
            "instrument_token": "NSE_EQ|X",
            "old_product": "MIS",
            "new_product": "CNC",
            "transaction_type": "BUY",
            "quantity": 10,
        }
    )
    assert p == {
        "instrument_token": "NSE_EQ|X",
        "new_product": "D",
        "old_product": "I",
        "transaction_type": "BUY",
        "quantity": 10,
    }


def test_to_convert_position_params_rejects_noop_and_unknowns():
    # CNC and NRML both map to Upstox D — converting between them is a no-op.
    with pytest.raises(m.UpstoxMappingError, match="no-op"):
        m.to_convert_position_params(
            {
                "instrument_token": "T",
                "old_product": "CNC",
                "new_product": "NRML",
                "transaction_type": "BUY",
                "quantity": 1,
            }
        )
    with pytest.raises(m.UpstoxMappingError, match="products"):
        m.to_convert_position_params(
            {
                "instrument_token": "T",
                "old_product": "ZZ",
                "new_product": "CNC",
                "transaction_type": "BUY",
                "quantity": 1,
            }
        )
    with pytest.raises(m.UpstoxMappingError, match="action"):
        m.to_convert_position_params(
            {
                "instrument_token": "T",
                "old_product": "MIS",
                "new_product": "CNC",
                "transaction_type": "HOLD",
                "quantity": 1,
            }
        )


def test_to_brokerage_query_uses_validated_core():
    q = m.to_brokerage_query(_order(quantity="7", price="101.5"), "NSE_EQ|X")
    assert q == {
        "instrument_token": "NSE_EQ|X",
        "quantity": 7,
        "product": "I",
        "transaction_type": "BUY",
        "price": 101.5,
    }


def test_from_upstox_brokerage_unwraps_charges():
    out = m.from_upstox_brokerage(
        {
            "status": "success",
            "data": {
                "charges": {
                    "total": 104.05,
                    "brokerage": 20.0,
                    "taxes": {"gst": 3.6, "stt": 29.0, "stamp_duty": 4.35},
                    "other_taxes": {"transaction": 1.0},
                }
            },
        }
    )
    assert out["total_charges"] == "104.05" and out["brokerage"] == "20.0"
    assert out["taxes"]["stt"] == 29.0 and out["other_taxes"]["transaction"] == 1.0


# ---------------------------------------------------------------------------
# Profile / kill switch
# ---------------------------------------------------------------------------


def test_from_upstox_profile():
    out = m.from_upstox_profile(
        {
            "status": "success",
            "data": {
                "user_id": "AB1234",
                "user_name": "N",
                "email": "n@x.in",
                "broker": "UPSTOX",
                "exchanges": ["NSE", "BSE"],
                "products": ["D", "I"],
                "order_types": ["LIMIT"],
                "is_active": True,
                "poa": False,
            },
        }
    )
    assert out["user_id"] == "AB1234" and out["is_active"] is True
    assert out["exchanges"] == ["NSE", "BSE"] and out["products"] == ["D", "I"]


# ---------------------------------------------------------------------------
# v3 quotes: OHLC / LTP / option Greeks
# ---------------------------------------------------------------------------


def test_from_upstox_ohlc_v3():
    rows = m.from_upstox_ohlc_v3(
        {
            "status": "success",
            "data": {
                "NSE_EQ:RELIANCE": {
                    "last_price": 2905.5,
                    "instrument_token": "NSE_EQ|INE002A01018",
                    "live_ohlc": {"open": 2900, "high": 2920, "low": 2890, "close": 2905, "volume": 12000},
                    "prev_ohlc": {
                        "open": 2880,
                        "high": 2901,
                        "low": 2870,
                        "close": 2899,
                        "ts": 1783881000000,
                    },
                },
            },
        }
    )
    assert len(rows) == 1
    r = rows[0]
    assert r["instrument_token"] == "NSE_EQ|INE002A01018" and r["ltp"] == 2905.5
    assert r["open"] == 2900.0 and r["volume"] == 12000 and r["prev_close"] == 2899.0
    assert r["previous_close_trusted"] is True
    assert r["previous_close_as_of"] == "1783881000000"


def test_from_upstox_ltp_v3():
    rows = m.from_upstox_ltp_v3(
        {
            "status": "success",
            "data": {
                "NSE_EQ:TCS": {
                    "last_price": 3501.0,
                    "instrument_token": "NSE_EQ|INE467B01029",
                    "volume": 999,
                    "cp": 3490.0,
                },
            }
        }
    )
    assert rows == [{
        "instrument_token": "NSE_EQ|INE467B01029",
        "ltp": 3501.0,
        "volume": 999,
        "prev_close": 3490.0,
        "previous_close_trusted": True,
    }]


def test_from_upstox_option_greeks():
    rows = m.from_upstox_option_greeks(
        {
            "status": "success",
            "data": {
                "NSE_FO|54452": {
                    "last_price": 120.5,
                    "instrument_token": "NSE_FO|54452",
                    "iv": 13.2,
                    "delta": 0.55,
                    "gamma": 0.002,
                    "theta": -8.1,
                    "vega": 6.4,
                    "oi": 30000,
                    "volume": 5000,
                },
            }
        }
    )
    assert rows[0]["delta"] == 0.55 and rows[0]["iv"] == 13.2 and rows[0]["oi"] == 30000


@pytest.mark.parametrize(
    "payload",
    [
        {"data": {}},
        {
            "status": "success",
            "data": {
                "NSE_FO|54452": {
                    "last_price": 120.5,
                    "iv": 13.2,
                    "delta": 0.55,
                    "gamma": 0.002,
                    "theta": -8.1,
                    "vega": 6.4,
                    "oi": 30_000,
                    "volume": 5_000,
                },
            },
        },
    ],
)
def test_from_upstox_option_greeks_requires_success_and_broker_identity(payload) -> None:
    with pytest.raises(m.UpstoxMappingError):
        m.from_upstox_option_greeks(payload)


# ---------------------------------------------------------------------------
# Instruments / expiries
# ---------------------------------------------------------------------------


def test_from_upstox_instrument_rows():
    rows = m.from_upstox_instrument_rows(
        {
            "data": [
                {
                    "instrument_key": "NSE_FO|54452",
                    "trading_symbol": "NIFTY 24600 CE",
                    "name": "NIFTY",
                    "exchange": "NSE",
                    "segment": "NSE_FO",
                    "instrument_type": "CE",
                    "expiry": "2025-06-26",
                    "strike_price": 24600,
                    "lot_size": 75,
                    "tick_size": 5,
                    "freeze_quantity": 1800,
                    "underlying_key": "NSE_INDEX|Nifty 50",
                },
                "junk",
            ]
        }
    )
    assert len(rows) == 1
    r = rows[0]
    assert r["instrument_key"] == "NSE_FO|54452" and r["strike_price"] == 24600.0
    assert r["lot_size"] == 75 and r["underlying_key"] == "NSE_INDEX|Nifty 50"


def test_from_upstox_expiries():
    assert m.from_upstox_expiries({"data": ["2025-06-26", "2025-07-03"]}) == ["2025-06-26", "2025-07-03"]
    assert m.from_upstox_expiries({"data": {}}) == []


# ---------------------------------------------------------------------------
# Reports: trade history + P&L
# ---------------------------------------------------------------------------


def test_from_upstox_trade_history():
    rows = m.from_upstox_trade_history(
        {
            "data": [
                {
                    "trade_id": "T1",
                    "scrip_name": "RELIANCE",
                    "exchange": "NSE",
                    "segment": "EQ",
                    "transaction_type": "BUY",
                    "quantity": 10,
                    "price": 2900.0,
                    "amount": 29000.0,
                    "trade_date": "2025-04-01",
                    "isin": "INE002A01018",
                    "instrument_token": "NSE_EQ|INE002A01018",
                },
            ]
        }
    )
    assert rows[0]["trade_id"] == "T1" and rows[0]["symbol"] == "RELIANCE"
    assert rows[0]["amount"] == "29000.0" and rows[0]["trade_date"] == "2025-04-01"


def test_from_upstox_pnl_rows_computes_pnl():
    rows = m.from_upstox_pnl_rows(
        {
            "data": [
                {
                    "scrip_name": "INFY",
                    "isin": "INE009A01021",
                    "trade_type": "EQ",
                    "quantity": 10,
                    "buy_date": "2025-01-02",
                    "buy_average": 1500.0,
                    "sell_date": "2025-02-02",
                    "sell_average": 1550.0,
                    "buy_amount": 15000.0,
                    "sell_amount": 15500.0,
                },
            ]
        }
    )
    assert rows[0]["pnl"] == "500.0" and rows[0]["symbol"] == "INFY"


def test_from_upstox_pnl_charges():
    out = m.from_upstox_pnl_charges({"data": {"charges_breakdown": {"total": 350.5, "brokerage": 120.0}}})
    assert out["total_charges"] == "350.5" and out["brokerage"] == "120.0"


# ---------------------------------------------------------------------------
# Market information
# ---------------------------------------------------------------------------


def test_from_upstox_timings_holidays_status():
    timings = m.from_upstox_timings(
        {
            "data": [
                {"exchange": "NSE", "start_time": 1718595000000, "end_time": 1718618400000},
            ]
        }
    )
    assert timings[0]["exchange"] == "NSE" and timings[0]["start_time"] == "1718595000000"

    holidays = m.from_upstox_holidays(
        {
            "data": [
                {
                    "date": "2025-08-15",
                    "description": "Independence Day",
                    "holiday_type": "TRADING_HOLIDAY",
                    "closed_exchanges": ["NSE", "BSE"],
                },
            ]
        }
    )
    assert holidays[0]["date"] == "2025-08-15" and "NSE" in holidays[0]["closed_exchanges"]

    status = m.from_upstox_market_status(
        {"data": {"exchange": "NSE", "status": "NORMAL_OPEN", "last_updated": 1718595000000}}
    )
    assert status["status"] == "NORMAL_OPEN" and status["exchange"] == "NSE"


def test_from_upstox_holidays_preserves_special_session_epochs():
    holidays = m.from_upstox_holidays(
        {
            "data": [
                {
                    "date": "2026-11-08",
                    "description": "Muhurat trading",
                    "holiday_type": "SPECIAL_SESSION",
                    "closed_exchanges": ["NSE", "BSE"],
                    "open_exchanges": [
                        {"exchange": "NSE", "start_time": 1794150000000, "end_time": 1794153600000},
                        {"exchange": "BSE", "start_time": 1794150000000, "end_time": 1794153600000},
                    ],
                },
            ]
        }
    )

    assert holidays[0]["open_exchanges"] == [
        {"exchange": "NSE", "start_time": "1794150000000", "end_time": "1794153600000"},
        {"exchange": "BSE", "start_time": "1794150000000", "end_time": "1794153600000"},
    ]


# ---------------------------------------------------------------------------
# History params: one-second candles
# ---------------------------------------------------------------------------


def test_to_history_params_supports_one_second_unit():
    p = m.to_history_params(
        {"interval": "1s", "instrument_key": "NSE_EQ|X", "from_date": "2025-06-01", "to_date": "2025-06-02"}
    )
    assert p["unit"] == "seconds" and p["interval"] == "1"


# ---------------------------------------------------------------------------
# Streaming: feed authorise + decoded-message ticks
# ---------------------------------------------------------------------------


def test_extract_authorized_uri():
    uri = m.extract_authorized_uri({"data": {"authorized_redirect_uri": "wss://feed.upstox/x?t=1"}})
    assert uri.startswith("wss://")
    with pytest.raises(m.UpstoxMappingError, match="feed URI"):
        m.extract_authorized_uri({"data": {}})


def test_from_upstox_feed_ticks_ltpc_mode():
    ticks = m.from_upstox_feed_ticks(
        {
            "type": "live_feed",
            "feeds": {
                "NSE_EQ|INE002A01018": {"ltpc": {"ltp": 2905.5, "ltt": "1718595000123", "ltq": "5", "cp": 2899.0}},
            },
        }
    )
    assert len(ticks) == 1
    t = ticks[0]
    assert t["instrument_key"] == "NSE_EQ|INE002A01018" and t["ltp"] == 2905.5
    assert t["prev_close"] == 2899.0 and t["ltq"] == 5 and t["ltt"] == "1718595000123"


def test_from_upstox_feed_ticks_full_feed_market_and_index():
    ticks = m.from_upstox_feed_ticks(
        {
            "feeds": {
                "NSE_FO|54452": {
                    "fullFeed": {
                        "marketFF": {
                            "ltpc": {"ltp": 120.5, "ltt": "1", "ltq": "75", "cp": 118.0},
                            "vtt": "123456",
                            "oi": "30000",
                        }
                    }
                },
                "NSE_INDEX|Nifty 50": {
                    "fullFeed": {
                        "indexFF": {
                            "ltpc": {"ltp": 24650.0, "ltt": "2", "cp": 24600.0},
                        }
                    }
                },
                "BAD|REC": {"fullFeed": {}},
                "WORSE|REC": "junk",
            }
        }
    )
    by_key = {t["instrument_key"]: t for t in ticks}
    assert set(by_key) == {"NSE_FO|54452", "NSE_INDEX|Nifty 50"}
    assert by_key["NSE_FO|54452"]["volume"] == 123456 and by_key["NSE_FO|54452"]["oi"] == 30000
    assert by_key["NSE_INDEX|Nifty 50"]["ltp"] == 24650.0


def test_from_upstox_feed_ticks_tolerates_junk_messages():
    assert m.from_upstox_feed_ticks({}) == []
    assert m.from_upstox_feed_ticks({"feeds": "nope"}) == []


# ---------------------------------------------------------------------------
# Broker-error translation (contract §7)
# ---------------------------------------------------------------------------


def test_is_api_exception_duck_types_by_shape():
    assert m.is_api_exception(_StandInApiException(400, _err_body("E", "x"))) is True
    assert m.is_api_exception(ValueError("nope")) is False
    assert m.is_api_exception(m.UpstoxMappingError("bad")) is False


def test_map_upstox_error_rejected_order_400():
    exc = _StandInApiException(400, _err_body("UDAPI100038", "Invalid order parameters"), reason="Bad Request")
    mapped = m.map_upstox_error(exc)
    assert isinstance(mapped, OrderRejectedByBroker)
    assert "Invalid order parameters" in str(mapped)  # broker message preserved
    assert mapped.broker_code == "UDAPI100038" and mapped.broker_id == "upstox"


def test_map_upstox_error_reads_camelcase_errorcode_wire_key():
    # The wire key is errorCode (camelCase). A snake_case-only parser would lose
    # the broker code; assert the real envelope's code reaches broker_code.
    camel = json.dumps({"status": "error", "errors": [{"errorCode": "UDAPI100038", "message": "Rejected"}]}).encode(
        "utf-8"
    )
    mapped = m.map_upstox_error(_StandInApiException(400, camel, reason="Bad Request"))
    assert mapped.broker_code == "UDAPI100038"
    # The snake_case fallback still works for any endpoint that emits it.
    snake = json.dumps({"status": "error", "errors": [{"error_code": "X9", "message": "Rejected"}]}).encode("utf-8")
    assert m.map_upstox_error(_StandInApiException(400, snake)).broker_code == "X9"


def test_map_upstox_error_expired_token_401_is_session_expired():
    exc = _StandInApiException(401, _err_body("UDAPI100050", "Invalid token"), reason="Unauthorized")
    assert isinstance(m.map_upstox_error(exc), SessionExpired)


def test_map_upstox_error_rate_limit_429():
    exc = _StandInApiException(429, _err_body("UDAPI10005", "Too many requests"), reason="Too Many Requests")
    mapped = m.map_upstox_error(exc)
    assert isinstance(mapped, RateLimitError) and mapped.endpoint == "default"


def test_map_upstox_error_specialises_by_message():
    funds = m.map_upstox_error(_StandInApiException(400, _err_body("E", "Insufficient margin available")))
    assert isinstance(funds, InsufficientFunds)
    qty = m.map_upstox_error(_StandInApiException(400, _err_body("E", "Quantity below lot size")))
    assert isinstance(qty, InvalidQuantity)
    price = m.map_upstox_error(_StandInApiException(400, _err_body("E", "Price outside circuit limit")))
    assert isinstance(price, InvalidPrice)


def test_map_upstox_error_5xx_and_non_json_body():
    server = m.map_upstox_error(_StandInApiException(500, None, reason="Internal Server Error"))
    assert isinstance(server, BrokerError) and "Internal Server Error" in str(server)
    # A non-JSON body still surfaces its text rather than being lost.
    raw = m.map_upstox_error(_StandInApiException(503, b"upstream gateway down", reason="Unavailable"))
    assert "upstream gateway down" in str(raw)
