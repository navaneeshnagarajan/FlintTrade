"""Unit tests for the Kotak Neo v3 mapping surface.

Covers regular/AMO orders, the exact v3 modify surface, margin requests, the NEO
error envelopes, order-history unwrapping, limits/scrip-master/depth
normalisation and the HSM market-feed + HSI order-feed decoders — all against
synthetic frames shaped per the pinned v3 SDK.
"""

from __future__ import annotations

import json

import pytest

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_core.exceptions import SessionExpired
from flinttrade_core.models import Order
from flinttrade_gateway.brokers.kotakneo_mapping import (
    KotakNeoMappingError,
    canonical_index_name,
    canonical_quote_type,
    decode_kotak_feed,
    decode_kotak_order_feed,
    ensure_ok,
    from_kotak_depth,
    from_kotak_funds,
    from_kotak_margin,
    from_kotak_order,
    from_kotak_position,
    from_kotak_scrip_master,
    from_kotak_trade,
    is_index_name,
    order_history_rows,
    require_write_success,
    subscription_flags,
    to_limits_params,
    to_margin_params,
    to_modify_order_params,
    to_place_order_params,
    to_quote_tokens,
)

pytestmark = pytest.mark.unit


def test_rejected_limits_cannot_map_to_zero_funds():
    with pytest.raises(SessionExpired):
        from_kotak_funds({"stat": "Not_Ok", "errMsg": "session expired"})


def test_malformed_successful_limits_do_not_map_invalid_number_to_zero():
    with pytest.raises(BrokerReadResponseInvalid):
        from_kotak_funds({"stat": "Ok", "Net": "not a number", "MarginUsed": "5"})


# ---------------------------------------------------------------------------
# Place: AMO variety
# ---------------------------------------------------------------------------


def test_place_order_amo_variety_sets_flag():
    order = Order(
        symbol="IDEA",
        action="BUY",
        exchange="NSE",
        pricetype="LIMIT",
        product="CNC",
        quantity="10",
        price="9.4",
        variety="amo",
    )
    p = to_place_order_params(order, "IDEA-EQ")
    assert p["amo"] == "YES"
    assert p["product"] == "CNC"  # AMO is a flag, not a product override


def test_place_order_regular_defaults_amo_no():
    order = Order(
        symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT", product="CNC", quantity="10", price="9.4"
    )
    assert to_place_order_params(order, "IDEA-EQ")["amo"] == "NO"


@pytest.mark.parametrize("market_protection", [True, False])
def test_place_order_rejects_caller_market_protection(market_protection):
    base = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="MARKET", product="CNC", quantity="10")
    assert "market_protection" not in to_place_order_params(base, "IDEA-EQ")
    protected = base.model_copy(update={"market_protection": market_protection})
    with pytest.raises(KotakNeoMappingError, match="market protection"):
        to_place_order_params(protected, "IDEA-EQ")


# ---------------------------------------------------------------------------
# Place: validity pass-through (Order.validity)
# ---------------------------------------------------------------------------


def test_place_order_validity_defaults_to_day_when_unset():
    order = Order(
        symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT", product="CNC", quantity="10", price="9.4"
    )
    assert to_place_order_params(order, "IDEA-EQ")["validity"] == "DAY"


def test_place_order_mcx_rejects_ioc_before_mapping():
    order = Order(
        symbol="GOLDPETAL25JUNFUT",
        action="BUY",
        exchange="MCX",
        pricetype="LIMIT",
        product="NRML",
        quantity="1",
        price="7000",
        validity="IOC",
    )
    with pytest.raises(KotakNeoMappingError, match="MCX.*DAY"):
        to_place_order_params(order, "GOLDPETAL25JUNFUT")


def test_place_order_validity_invalid_raises():
    order = Order(
        symbol="IDEA",
        action="BUY",
        exchange="NSE",
        pricetype="LIMIT",
        product="CNC",
        quantity="10",
        price="9.4",
        validity="FOREVER",
    )
    with pytest.raises(KotakNeoMappingError, match="validity"):
        to_place_order_params(order, "IDEA-EQ")


def test_place_order_rejects_legacy_validity_before_sdk():
    order = Order(
        symbol="GOLDPETAL25JUNFUT",
        action="BUY",
        exchange="MCX",
        pricetype="LIMIT",
        product="NRML",
        quantity="1",
        price="7000",
        validity="GTC",
    )
    with pytest.raises(KotakNeoMappingError, match="validity"):
        to_place_order_params(order, "GOLDPETAL25JUNFUT")


@pytest.mark.parametrize(("exchange", "expected"), [("BFO", "bse_fo"), ("MCX", "mcx_fo")])
def test_place_order_maps_supported_v3_derivative_segments(exchange, expected):
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


@pytest.mark.parametrize("exchange", ["CDS", "BCD"])
def test_place_order_rejects_currency_segments(exchange):
    order = Order(
        symbol="SYNTHETIC",
        action="BUY",
        exchange="NSE",
        pricetype="LIMIT",
        product="NRML",
        quantity="1",
        price="1",
    )
    object.__setattr__(order, "exchange", exchange)
    with pytest.raises(KotakNeoMappingError, match="exchange"):
        to_place_order_params(order, "SYNTHETIC")


# ---------------------------------------------------------------------------
# Modify: exact v3 order-id surface
# ---------------------------------------------------------------------------


def test_modify_emits_only_exact_v3_order_id_surface():
    p = to_modify_order_params(
        "250122000624384",
        {
            "pricetype": "SL",
            "price": 9.5,
            "quantity": 20,
            "trigger_price": 9.45,
            "disclosed_quantity": 5,
            "validity": "IOC",
            "amo": True,
        },
    )
    assert p == {
        "order_id": "250122000624384",
        "order_type": "SL",
        "price": "9.5",
        "quantity": "20",
        "validity": "IOC",
        "trigger_price": "9.45",
        "disclosed_quantity": "5",
        "amo": "YES",
    }


@pytest.mark.parametrize(
    "unsupported",
    [
        {"instrument_token": "14366"},
        {"exchange_segment": "NSE"},
        {"trading_symbol": "IDEA-EQ"},
        {"transaction_type": "BUY"},
        {"filled_quantity": 2},
        {"market_protection": 3},
        {"dd": "NA"},
    ],
)
def test_modify_rejects_removed_quick_and_legacy_fields(unsupported):
    with pytest.raises(KotakNeoMappingError, match="does not support"):
        to_modify_order_params(
            "250122000624384",
            {"pricetype": "MARKET", "price": 0, "quantity": 1, **unsupported},
        )


def test_modify_consumes_signed_route_context_but_emits_only_exact_v3_kwargs():
    params = to_modify_order_params(
        "250122000624384",
        {
            "symbol": "GOLDPETAL25JUNFUT",
            "exchange": "MCX",
            "action": "BUY",
            "product": "NRML",
            "strategy": "Flint",
            "pricetype": "LIMIT",
            "price": "7000",
            "quantity": "1",
            "validity": "DAY",
            "trigger_price": "0",
            "disclosed_quantity": "0",
        },
    )

    assert params == {
        "order_id": "250122000624384",
        "order_type": "L",
        "price": "7000",
        "quantity": "1",
        "validity": "DAY",
        "trigger_price": "0",
        "disclosed_quantity": "0",
    }


def test_modify_mcx_context_rejects_ioc():
    with pytest.raises(KotakNeoMappingError, match="MCX.*DAY"):
        to_modify_order_params(
            "250122000624384",
            {
                "symbol": "GOLDPETAL25JUNFUT",
                "exchange": "MCX",
                "action": "BUY",
                "product": "NRML",
                "strategy": "Flint",
                "pricetype": "LIMIT",
                "price": "7000",
                "quantity": "1",
                "validity": "IOC",
            },
        )


def test_modify_minimal_omits_optional_keys():
    p = to_modify_order_params("1", {"quantity": 4, "price": 9.5})
    for key in (
        "instrument_token",
        "exchange_segment",
        "product",
        "trading_symbol",
        "transaction_type",
        "amo",
        "filled_quantity",
        "market_protection",
        "dd",
    ):
        assert key not in p
    assert p["validity"] == "DAY"


def test_modify_amo_string_passthrough():
    assert to_modify_order_params(
        "1", {"pricetype": "MARKET", "price": 0, "quantity": 1, "amo": "yes"}
    )["amo"] == "YES"


def test_modify_validity_validated():
    assert to_modify_order_params(
        "1", {"pricetype": "MARKET", "price": 0, "quantity": 1, "validity": "IOC"}
    )["validity"] == "IOC"
    with pytest.raises(KotakNeoMappingError, match="validity"):
        to_modify_order_params(
            "1", {"pricetype": "MARKET", "price": 0, "quantity": 1, "validity": "GTC"}
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quantity", ""),
        ("quantity", "abc"),
        ("quantity", "1.5"),
        ("quantity", "0"),
        ("quantity", "-1"),
        ("quantity", True),
        ("quantity", None),
        ("price", "abc"),
        ("price", "NaN"),
        ("price", "Infinity"),
        ("price", "-0.01"),
        ("price", True),
        ("price", None),
        ("trigger_price", "abc"),
        ("trigger_price", "NaN"),
        ("trigger_price", "-0.01"),
        ("trigger_price", "Infinity"),
        ("trigger_price", True),
        ("trigger_price", None),
        ("disclosed_quantity", ""),
        ("disclosed_quantity", "abc"),
        ("disclosed_quantity", "1.5"),
        ("disclosed_quantity", "-1"),
        ("disclosed_quantity", "NaN"),
        ("disclosed_quantity", "Infinity"),
        ("disclosed_quantity", True),
        ("disclosed_quantity", None),
    ],
)
def test_place_rejects_malformed_or_non_finite_numeric_intent(field, value):
    order = Order(
        symbol="IDEA",
        action="BUY",
        exchange="NSE",
        pricetype="MARKET",
        product="MIS",
        quantity="1",
    ).model_copy(update={field: value})

    with pytest.raises(KotakNeoMappingError, match=field.replace("_", " ")):
        to_place_order_params(order, "IDEA-EQ")


@pytest.mark.parametrize(
    "order",
    [
        Order(
            symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT",
            product="MIS", quantity="1", price="0",
        ),
        Order(
            symbol="IDEA", action="BUY", exchange="NSE", pricetype="SL",
            product="MIS", quantity="1", price="9.4", trigger_price="0",
        ),
        Order(
            symbol="IDEA", action="BUY", exchange="NSE", pricetype="SL-M",
            product="MIS", quantity="1", price="0", trigger_price="0",
        ),
    ],
    ids=["limit-zero-price", "stop-limit-zero-trigger", "stop-market-zero-trigger"],
)
def test_place_requires_positive_limit_price_and_stop_trigger(order):
    with pytest.raises(KotakNeoMappingError):
        to_place_order_params(order, "IDEA-EQ")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quantity", ""),
        ("quantity", "abc"),
        ("quantity", "1.5"),
        ("quantity", "0"),
        ("quantity", "-1"),
        ("quantity", True),
        ("price", "NaN"),
        ("price", "Infinity"),
        ("price", "-1"),
        ("price", True),
        ("trigger_price", "abc"),
        ("trigger_price", "NaN"),
        ("trigger_price", "Infinity"),
        ("trigger_price", "-1"),
        ("trigger_price", True),
        ("disclosed_quantity", ""),
        ("disclosed_quantity", "abc"),
        ("disclosed_quantity", "1.5"),
        ("disclosed_quantity", "-1"),
        ("disclosed_quantity", "NaN"),
        ("disclosed_quantity", "Infinity"),
        ("disclosed_quantity", True),
    ],
)
def test_modify_rejects_malformed_or_non_finite_numeric_intent(field, value):
    changes = {
        "pricetype": "MARKET",
        "price": "0",
        "quantity": "1",
        "trigger_price": "0",
        "disclosed_quantity": "0",
        field: value,
    }
    with pytest.raises(KotakNeoMappingError, match=field.replace("_", " ")):
        to_modify_order_params("OID-1", changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"pricetype": "LIMIT", "price": "0", "quantity": "1"},
        {"pricetype": "SL", "price": "9.4", "quantity": "1", "trigger_price": "0"},
        {"pricetype": "SL-M", "price": "0", "quantity": "1", "trigger_price": "0"},
    ],
)
def test_modify_requires_positive_limit_price_and_stop_trigger(changes):
    with pytest.raises(KotakNeoMappingError):
        to_modify_order_params("OID-1", changes)


@pytest.mark.parametrize("order_id", ["", " ", " OID-1", "OID 1", "OID-1\n"])
def test_modify_requires_canonical_order_id(order_id):
    with pytest.raises(KotakNeoMappingError, match="order id"):
        to_modify_order_params(
            order_id,
            {"pricetype": "MARKET", "price": "0", "quantity": "1"},
        )


@pytest.mark.parametrize("tag", ["", " ", " TAG-1", "TAG-1\n"])
def test_place_rejects_noncanonical_tag(tag):
    order = Order(symbol="IDEA", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS")
    with pytest.raises(KotakNeoMappingError, match="tag"):
        to_place_order_params(order, "IDEA-EQ", tag=tag)


# ---------------------------------------------------------------------------
# Margin: exact v3 regular-order request
# ---------------------------------------------------------------------------


def test_margin_params_carry_trigger_price():
    order = Order(
        symbol="IDEA",
        action="SELL",
        exchange="NSE",
        pricetype="SL",
        product="MIS",
        quantity="10",
        price="9.3",
        trigger_price="9.35",
    )
    p = to_margin_params(order, "14366")
    assert p["trigger_price"] == "9.35"


def test_margin_params_reject_bracket_variety():
    order = Order(
        symbol="IDEA",
        action="BUY",
        exchange="NSE",
        pricetype="LIMIT",
        product="MIS",
        quantity="10",
        price="9.4",
        variety="bracket",
        target_price="9.8",
        stop_loss_price="9.1",
        trailing_jump="0.1",
    )
    with pytest.raises(KotakNeoMappingError, match="variety"):
        to_margin_params(order, "14366")


def test_margin_params_reject_cover_variety():
    order = Order(
        symbol="IDEA",
        action="BUY",
        exchange="NSE",
        pricetype="LIMIT",
        product="MIS",
        quantity="10",
        price="9.4",
        variety="cover",
        stop_loss_price="9.1",
    )
    with pytest.raises(KotakNeoMappingError, match="variety"):
        to_margin_params(order, "14366")


# ---------------------------------------------------------------------------
# Margin keys the scrip only by numeric instrument_token (pSymbol).
# ---------------------------------------------------------------------------


def test_margin_params_use_only_numeric_instrument_token():
    order = Order(
        symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT", product="MIS", quantity="10", price="9.4"
    )
    p = to_margin_params(order, "14366")
    assert p["instrument_token"] == "14366"
    assert "trading_symbol" not in p


@pytest.mark.parametrize("instrument_token", ["", "IDEA-EQ", "14.366", "-14366", "0"])
def test_margin_params_reject_non_numeric_instrument_token(instrument_token):
    order = Order(
        symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT", product="MIS", quantity="10", price="9.4"
    )
    with pytest.raises(KotakNeoMappingError, match="numeric instrument_token"):
        to_margin_params(order, instrument_token)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quantity", ""),
        ("quantity", "abc"),
        ("quantity", "1.5"),
        ("quantity", "0"),
        ("quantity", "-1"),
        ("quantity", True),
        ("price", "abc"),
        ("price", "NaN"),
        ("price", "Infinity"),
        ("price", "-0.01"),
        ("price", True),
        ("trigger_price", "abc"),
        ("trigger_price", "NaN"),
        ("trigger_price", "-0.01"),
        ("trigger_price", "-Infinity"),
        ("trigger_price", True),
    ],
)
def test_margin_params_reject_malformed_or_non_finite_numeric_intent(field, value):
    order = Order(
        symbol="IDEA",
        action="BUY",
        exchange="NSE",
        pricetype="MARKET",
        product="MIS",
        quantity="1",
    ).model_copy(update={field: value})
    with pytest.raises(KotakNeoMappingError, match=field.replace("_", " ")):
        to_margin_params(order, "14366")


def test_margin_params_never_truncate_fractional_quantity():
    order = Order(
        symbol="IDEA", action="BUY", exchange="NSE", pricetype="MARKET", product="MIS", quantity="1"
    ).model_copy(update={"quantity": "1.5"})
    with pytest.raises(KotakNeoMappingError, match="quantity"):
        to_margin_params(order, "14366")


@pytest.mark.parametrize(
    "order",
    [
        Order(
            symbol="IDEA", action="BUY", exchange="NSE", pricetype="LIMIT",
            product="MIS", quantity="1", price="0",
        ),
        Order(
            symbol="IDEA", action="BUY", exchange="NSE", pricetype="SL",
            product="MIS", quantity="1", price="9.4", trigger_price="0",
        ),
        Order(
            symbol="IDEA", action="BUY", exchange="NSE", pricetype="SL-M",
            product="MIS", quantity="1", price="0", trigger_price="0",
        ),
    ],
)
def test_margin_params_require_positive_limit_price_and_stop_trigger(order):
    with pytest.raises(KotakNeoMappingError):
        to_margin_params(order, "14366")


def test_margin_response_maps_ord_margin_as_common_required_margin():
    assert from_kotak_margin(
        {
            "data": {
                "stat": "Ok",
                "stCode": 200,
                "avlCash": "38.190000",
                "ordMrgn": "15.500000",
                "reqdMrgn": "0.000000",
                "insufFund": "0.000000",
                "rmsVldtd": "OK",
            }
        }
    ) == {
        "required_margin": "15.50",
        "order_margin": "15.50",
        "provider_additional_margin": "0.00",
        "available_balance": "38.19",
        "insufficient_balance": "0.00",
        "rms_validated": "OK",
    }


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"data": {}},
        {"data": {"stat": "Ok", "stCode": 200, "reqdMrgn": "0", "avlCash": "38.19",
                  "insufFund": "0", "rmsVldtd": "OK"}},
        {"data": {"stat": "Ok", "stCode": 200, "ordMrgn": "NaN", "reqdMrgn": "0",
                  "avlCash": "38.19", "insufFund": "0", "rmsVldtd": "OK"}},
        {"data": {"stat": "Ok", "stCode": 200, "ordMrgn": "Infinity", "reqdMrgn": "0",
                  "avlCash": "38.19", "insufFund": "0", "rmsVldtd": "OK"}},
        {"data": {"stat": "Ok", "stCode": 200, "ordMrgn": "-1", "reqdMrgn": "0",
                  "avlCash": "38.19", "insufFund": "0", "rmsVldtd": "OK"}},
        {"data": {"stat": "Ok", "stCode": 200, "ordMrgn": True, "reqdMrgn": "0",
                  "avlCash": "38.19", "insufFund": "0", "rmsVldtd": "OK"}},
        {"data": {"stat": "Ok", "stCode": 200, "ordMrgn": "15.5", "reqdMrgn": "bad",
                  "avlCash": "38.19", "insufFund": "0", "rmsVldtd": "OK"}},
        {"data": {"stat": "Ok", "stCode": 200, "ordMrgn": "15.5", "reqdMrgn": "-1",
                  "avlCash": "38.19", "insufFund": "0", "rmsVldtd": "OK"}},
        {"data": {"stat": "Ok", "stCode": 200, "ordMrgn": "15.5", "reqdMrgn": "0",
                  "avlCash": "bad", "insufFund": "0", "rmsVldtd": "OK"}},
        {"data": {"stat": "Ok", "stCode": 200, "ordMrgn": "15.5", "reqdMrgn": "0",
                  "avlCash": "38.19", "insufFund": "-1", "rmsVldtd": "OK"}},
        {"data": {"stat": "Ok", "stCode": "200", "ordMrgn": "15.5", "reqdMrgn": "0",
                  "avlCash": "38.19", "insufFund": "0", "rmsVldtd": "OK"}},
        {"data": {"stat": "Ok", "stCode": 200, "ordMrgn": "15.5", "reqdMrgn": "0",
                  "avlCash": "38.19", "insufFund": "0", "rmsVldtd": ""}},
    ],
)
def test_margin_response_rejects_missing_or_malformed_official_success_fields(response):
    with pytest.raises(BrokerReadResponseInvalid):
        from_kotak_margin(response)


def test_trade_mapping_requires_order_id():
    with pytest.raises(BrokerReadResponseInvalid):
        from_kotak_trade(
            {
                "trdSym": "IDEA-EQ",
                "exSeg": "nse_cm",
                "trnsTp": "B",
                "fldQty": "1",
                "avgPrc": "9.40",
                "prod": "MIS",
                "flDtTm": "22-Jan-2025 14:28:16",
            }
        )


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
    assert is_index_name("BANKEX")
    assert not is_index_name("IDEA") and not is_index_name("RELIANCE")


def test_canonical_quote_type_preserves_documented_path_case():
    assert canonical_quote_type("52w") == "52W"
    assert canonical_quote_type("52W") == "52W"
    assert canonical_quote_type("ltp") == "ltp"
    with pytest.raises(KotakNeoMappingError, match="quote_type"):
        canonical_quote_type("greeks")


def test_canonical_index_name_uses_documented_case_when_known():
    assert canonical_index_name("nifty 50") == "Nifty 50"
    assert canonical_index_name("NIFTY BANK") == "Nifty Bank"
    assert canonical_index_name("bankex") == "BANKEX"
    assert canonical_index_name("NIFTY MID SELECT") == "NIFTY MID SELECT"


# ---------------------------------------------------------------------------
# Unsupported advanced varieties must fail instead of degrading to regular.
# ---------------------------------------------------------------------------


def test_place_cover_is_not_supported_by_v3_adapter():
    order = Order(
        symbol="IDEA",
        action="BUY",
        exchange="NSE",
        pricetype="LIMIT",
        product="MIS",
        quantity="10",
        price="9.4",
        variety="cover",
        stop_loss_price="9.1",
    )
    with pytest.raises(KotakNeoMappingError, match="variety"):
        to_place_order_params(order, "IDEA-EQ")


def test_place_cover_with_trigger_is_still_unsupported():
    order = Order(
        symbol="IDEA",
        action="SELL",
        exchange="NSE",
        pricetype="SL-M",
        product="MIS",
        quantity="10",
        price="0",
        variety="cover",
        trigger_price="9.55",
    )
    with pytest.raises(KotakNeoMappingError, match="variety"):
        to_place_order_params(order, "IDEA-EQ")


def test_place_cover_without_stop_level_is_unsupported():
    order = Order(
        symbol="IDEA",
        action="BUY",
        exchange="NSE",
        pricetype="MARKET",
        product="MIS",
        quantity="10",
        price="0",
        variety="cover",
    )
    with pytest.raises(KotakNeoMappingError, match="variety"):
        to_place_order_params(order, "IDEA-EQ")


# ---------------------------------------------------------------------------
# Finding #4 — avg price denominator includes multiplier (Positions.md:110-112).
# ---------------------------------------------------------------------------


def test_position_avg_price_includes_multiplier():
    # Currency-derivative style row: multiplier = 1000, buy leg only.
    # Avg = amount / (qty * multiplier) = 105000 / (1 * 1000 * 1 * 1) = 105.00,
    # NOT 105000 (the pre-fix value with multiplier omitted).
    row = {
        "trdSym": "USDINR-FUT",
        "sym": "USDINR",
        "exSeg": "cde_fo",
        "prod": "NRML",
        "cfBuyQty": "1",
        "cfBuyAmt": "105000",
        "cfSellQty": "0",
        "cfSellAmt": "0",
        "flBuyQty": "0",
        "buyAmt": "0",
        "flSellQty": "0",
        "sellAmt": "0",
        "genNum": "1",
        "genDen": "1",
        "prcNum": "1",
        "prcDen": "1",
        "multiplier": "1000",
        "precision": "2",
    }
    pos = from_kotak_position(row)
    assert pos["average_price"] == "105.00"
    assert pos["quantity"] == "1"


def test_position_realised_pnl_amount_consistent_with_multiplier():
    # Fully matched buy 1 @105.00 / sell 1 @106.00, multiplier 1000.
    # Realised = matched * (sell_avg - buy_avg) * unit_factor = 1 * 1.00 * 1000 = 1000.00
    # = sell amount − buy amount (106000 − 105000), i.e. amount-consistent.
    row = {
        "trdSym": "USDINR-FUT",
        "sym": "USDINR",
        "exSeg": "cde_fo",
        "prod": "NRML",
        "cfBuyQty": "1",
        "cfBuyAmt": "105000",
        "cfSellQty": "1",
        "cfSellAmt": "106000",
        "flBuyQty": "0",
        "buyAmt": "0",
        "flSellQty": "0",
        "sellAmt": "0",
        "genNum": "1",
        "genDen": "1",
        "prcNum": "1",
        "prcDen": "1",
        "multiplier": "1000",
        "precision": "2",
    }
    pos = from_kotak_position(row)
    assert pos["pnl"] == "1000.00"


def test_position_avg_price_multiplier_one_unchanged():
    # Equity (multiplier 1) must be unaffected by the fix.
    row = {
        "trdSym": "IDEA-EQ",
        "sym": "IDEA",
        "exSeg": "nse_cm",
        "prod": "CNC",
        "cfBuyQty": "100",
        "cfBuyAmt": "939",
        "cfSellQty": "0",
        "cfSellAmt": "0",
        "flBuyQty": "0",
        "buyAmt": "0",
        "flSellQty": "0",
        "sellAmt": "0",
        "genNum": "1",
        "genDen": "1",
        "prcNum": "1",
        "prcDen": "1",
        "multiplier": "1",
        "precision": "2",
    }
    pos = from_kotak_position(row)
    assert pos["average_price"] == "9.39"


# ---------------------------------------------------------------------------
# V3 removed the quick-method field set entirely.
# ---------------------------------------------------------------------------


def test_modify_partial_quick_fields_rejected():
    with pytest.raises(KotakNeoMappingError, match="does not support"):
        to_modify_order_params("1", {"instrument_token": "14366", "quantity": 5})


def test_modify_partial_quick_fields_missing_one_rejected():
    with pytest.raises(KotakNeoMappingError, match="does not support"):
        to_modify_order_params(
            "1",
            {
                "instrument_token": "14366",
                "exchange_segment": "NSE",
                "product": "MIS",
                # trading_symbol deliberately omitted
            },
        )


def test_modify_complete_quick_set_is_still_rejected():
    with pytest.raises(KotakNeoMappingError, match="does not support"):
        to_modify_order_params(
            "1",
            {
                "instrument_token": "14366",
                "exchange_segment": "NSE",
                "product": "MIS",
                "trading_symbol": "IDEA-EQ",
                "quantity": 5,
            },
        )


def test_modify_order_id_path_no_quick_fields_accepted():
    p = to_modify_order_params("1", {"quantity": 5, "price": 9.5})
    for f in ("instrument_token", "exchange_segment", "product", "trading_symbol"):
        assert f not in p


# ---------------------------------------------------------------------------
# Finding #6 — stock feed sell_quantity is keyed 'sq', not the depth key 'bs'.
# ---------------------------------------------------------------------------


def test_stock_feed_decode_reads_sell_quantity_from_sq():
    tick = decode_kotak_feed(
        [
            {
                "tk": "11536",
                "ts": "TCS-EQ",
                "e": "nse_cm",
                "name": "sf",
                "ltp": "4000.5",
                "bq": "10",
                "sq": "7",
            }
        ]
    )[0]
    assert tick["kind"] == "quote"
    assert tick["sell_quantity"] == 7 and tick["buy_quantity"] == 10


def test_stock_feed_decode_ignores_depth_bs_key_for_sell_quantity():
    # 'bs' is a depth-frame offer-size key; in a stock frame it must NOT be read
    # as sell_quantity (the pre-fix STOCK_FEED_KEYS bug).
    tick = decode_kotak_feed(
        [
            {
                "tk": "11536",
                "ts": "TCS-EQ",
                "e": "nse_cm",
                "name": "sf",
                "ltp": "4000.5",
                "bs": "99",
            }
        ]
    )[0]
    assert tick["sell_quantity"] == 0


def test_stock_feed_decode_reads_long_name_sell_quantity():
    # SDK quote_resp_mapper re-keys 'sq' -> 'sell_quantity'; the long name decodes too.
    tick = decode_kotak_feed(
        {
            "type": "quotes",
            "data": [
                {
                    "instrument_token": "11536",
                    "trading_symbol": "TCS-EQ",
                    "exchange_segment": "nse_cm",
                    "last_traded_price": 4000.5,
                    "sell_quantity": 5,
                    "buy_quantity": 8,
                }
            ],
        }
    )[0]
    assert tick["sell_quantity"] == 5 and tick["buy_quantity"] == 8


# ---------------------------------------------------------------------------
# Error envelopes
# ---------------------------------------------------------------------------


def test_ensure_ok_passes_ok_envelopes():
    assert ensure_ok({"stat": "Ok", "nOrdNo": "1", "stCode": 200})["nOrdNo"] == "1"
    assert ensure_ok({"stat": "ok", "data": []})  # OMS lower-case variant
    assert ensure_ok({"data": {"status": "success", "token": "view-token"}})
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
    with pytest.raises(KotakNeoMappingError, match="Invalid MPIN"):
        ensure_ok({"status": "error", "message": "Invalid MPIN.", "errorCode": "401"})


def test_require_write_success_accepts_explicit_matching_acknowledgement():
    response = {"stat": "Ok", "nOrdNo": "250720000007242", "stCode": 200}

    assert require_write_success(response, expected_order_id="250720000007242") is response


@pytest.mark.parametrize(
    "response",
    [
        None,
        [],
        {"stat": "Ok", "nOrdNo": "250720000007242"},
        {"stat": "Ok", "nOrdNo": "250720000007242", "stCode": "200"},
        {"stat": "Not_Ok", "nOrdNo": "250720000007242", "stCode": 200},
        {"stat": "Ok", "nOrdNo": "", "stCode": 200},
        {"stat": "Ok", "nOrdNo": " 250720000007242", "stCode": 200},
    ],
)
def test_require_write_success_rejects_ambiguous_acknowledgement(response):
    with pytest.raises(KotakNeoMappingError):
        require_write_success(response)


def test_require_write_success_rejects_different_order_id():
    response = {"stat": "Ok", "nOrdNo": "250720000007588", "stCode": 200}

    with pytest.raises(KotakNeoMappingError, match="different order id"):
        require_write_success(response, expected_order_id="250720000007242")


# ---------------------------------------------------------------------------
# Order history + order-report enrichment
# ---------------------------------------------------------------------------

_HISTORY_ROW = {
    "trdSym": "IDEA-EQ",
    "prc": "9.39",
    "qty": 1,
    "ordSt": "complete",
    "trnsTp": "B",
    "prcTp": "L",
    "exSeg": "nse_cm",
    "exchTmstp": "22-Jan-2025 14:32:53",
    "nOrdNo": "250122000624384",
    "avgPrc": "9.39",
    "trgPrc": "0.00",
    "dclQty": "0",
    "exchOrdId": "1100000060414692",
    "rejRsn": "--",
    "ordDur": "DAY",
    "prod": "NRML",
    "fldQty": 1,
    "GuiOrdId": "",
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
    assert o["timestamp"] == "22-Jan-2025 14:32:53"  # history rows use exchTmstp
    assert o["validity"] == "DAY"  # falls back to ordDur
    assert o["rejection_reason"] == ""  # "--" sentinel scrubbed
    assert o["exchange_order_id"] == "1100000060414692"


def test_from_kotak_order_report_extras():
    o = from_kotak_order(
        {
            "nOrdNo": "1",
            "ordSt": "rejected",
            "trdSym": "IDEA-EQ",
            "exSeg": "nse_cm",
            "trnsTp": "B",
            "prcTp": "L",
            "prod": "NRML",
            "qty": 1,
            "prc": "9.39",
            "ordDtTm": "22-Jan-2025 14:28:01",
            "vldt": "DAY",
            "dscQty": 0,
            "rejRsn": "RMS check failed",
            "exOrdId": "NA",
            "GuiOrdId": "FLINT1",
        }
    )
    assert o["timestamp"] == "22-Jan-2025 14:28:01" and o["validity"] == "DAY"
    assert o["rejection_reason"] == "RMS check failed"
    assert o["exchange_order_id"] == ""  # "NA" sentinel scrubbed
    assert o["tag"] == "FLINT1"


# ---------------------------------------------------------------------------
# Limits filters
# ---------------------------------------------------------------------------


def test_limits_params_defaults_and_normalisation():
    assert to_limits_params() == {}
    assert to_limits_params("all", "all", "all") == {}


def test_limits_params_validation():
    with pytest.raises(KotakNeoMappingError, match="server-side filters"):
        to_limits_params(segment="EQUITY")
    with pytest.raises(KotakNeoMappingError, match="server-side filters"):
        to_limits_params("CASH", "NSE", "MIS")
    with pytest.raises(KotakNeoMappingError, match="server-side filters"):
        to_limits_params(product="BO")


# ---------------------------------------------------------------------------
# Scrip master
# ---------------------------------------------------------------------------


def test_scrip_master_full_response():
    out = from_kotak_scrip_master(
        {
            "filesPaths": [
                "https://lapi.kotaksecurities.com/wso2-scripmaster/v1/prod/2025-01-22/transformed/nse_cm.csv",
                "https://lapi.kotaksecurities.com/wso2-scripmaster/v1/prod/2025-01-22/transformed/nse_fo.csv",
            ],
            "baseFolder": "https://lapi.kotaksecurities.com/wso2-scripmaster/v1/prod",
        }
    )
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
        "instrument_token": "11536",
        "trading_symbol": "TCS-EQ",
        "exchange_segment": "nse_cm",
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
        "tk": "11536",
        "ts": "TCS-EQ",
        "e": "nse_cm",
        "name": "dp",
        "bp": "4000",
        "bp1": "3999.5",
        "bq": "10",
        "bq1": "20",
        "bno1": "2",
        "bno2": "3",
        "sp": "4001",
        "sp1": "4001.5",
        "bs": "5",
        "bs1": "8",
        "sno1": "1",
        "sno2": "4",
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
    "tk": "11536",
    "ts": "TCS-EQ",
    "e": "nse_cm",
    "ltp": "4000.5",
    "v": "120000",
    "bp": "4000.0",
    "sp": "4001.0",
    "oi": "0",
    "ltt": "22/01/2025 14:28:16",
    "name": "sf",
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
    ticks = decode_kotak_feed(
        {
            "type": "quotes",
            "data": [
                {
                    "instrument_token": "11536",
                    "trading_symbol": "TCS-EQ",
                    "exchange_segment": "nse_cm",
                    "last_traded_price": 4000.5,
                    "volume": 120000,
                    "buy_price": 4000.0,
                    "sell_price": 4001.0,
                    "open_interest": 0,
                    "last_traded_time": "22/01/2025 14:28:16",
                }
            ],
        }
    )
    assert len(ticks) == 1
    t = ticks[0]
    assert t["kind"] == "quote" and t["symbol"] == "TCS-EQ" and t["ltp"] == 4000.5
    assert t["volume"] == 120000 and t["bid"] == 4000.0 and t["ask"] == 4001.0


def test_decode_feed_index_frame():
    ticks = decode_kotak_feed(
        [
            {
                "tk": "Nifty 50",
                "e": "nse_cm",
                "name": "if",
                "iv": "24050.5",
                "ic": "23990.0",
                "openingPrice": "24000",
                "highPrice": "24100",
                "lowPrice": "23950",
                "tvalue": "1737536296",
            }
        ]
    )
    assert len(ticks) == 1
    t = ticks[0]
    assert t["kind"] == "index" and t["ltp"] == 24050.5 and t["prev_close"] == 23990.0
    assert t["high"] == 24100.0 and t["timestamp"] == "1737536296"


def test_decode_feed_depth_frame_carries_book():
    ticks = decode_kotak_feed(
        [
            {
                "tk": "11536",
                "ts": "TCS-EQ",
                "e": "nse_cm",
                "name": "dp",
                "bp": "4000",
                "bq": "10",
                "bno1": "2",
                "sp": "4001",
                "bs": "5",
                "sno1": "1",
            }
        ]
    )
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
    "nOrdNo": "250122000624384",
    "ordSt": "complete",
    "trdSym": "IDEA-EQ",
    "exSeg": "nse_cm",
    "trnsTp": "B",
    "prcTp": "L",
    "prod": "NRML",
    "qty": 1,
    "prc": "9.39",
    "fldQty": 1,
    "avgPrc": "9.39",
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
