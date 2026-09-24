"""Unit tests for the Kotak Neo v3 mapping surface.

Covers regular/AMO orders, the exact v3 modify surface, margin requests, the NEO
error envelopes, order-history unwrapping, limits/scrip-master/depth and v3
historical/option-chain normalisation against pinned SDK-shaped fixtures.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_core.exceptions import SessionExpired
from flinttrade_core.models import Order
from flinttrade_gateway.brokers.kotakneo_mapping import (
    KotakNeoMappingError,
    canonical_index_name,
    canonical_quote_type,
    ensure_ok,
    from_kotak_depth,
    from_kotak_funds,
    from_kotak_historical,
    from_kotak_margin,
    from_kotak_option_chain,
    from_kotak_order,
    from_kotak_position,
    from_kotak_scrip_master,
    from_kotak_trade,
    is_index_name,
    order_history_rows,
    require_write_success,
    subscription_flags,
    to_historical_request,
    to_limits_params,
    to_margin_params,
    to_modify_order_params,
    to_option_chain_request,
    to_place_order_params,
    to_quote_tokens,
)

pytestmark = pytest.mark.unit


def _official_option_chain_response() -> dict:
    """Return the immutable v3.0.7 option-chain sample shape."""
    return {
        "data": {
            "common_data": {
                "mktLot": "65",
                "multiplier": "1",
                "unlSymbol": "NIFTY",
                "exSeg": "nse_fo",
                "expiryDt": "2026-06-23",
            },
            "call": [
                {
                    "instrument": {
                        "neoSymbol": "nse_fo|71472",
                        "symbol": "NIFTY26JUN22250CE",
                        "optionType": "CE",
                        "strikePrice": "22250",
                        "moneyness": "ATM",
                    },
                    "quote": {"ltp": "166.7500", "volume": 225431505},
                    "openInterest": {"current": 10715645},
                }
            ],
            "put": [
                {
                    "instrument": {
                        "neoSymbol": "nse_fo|71473",
                        "symbol": "NIFTY26JUN22250PE",
                        "optionType": "PE",
                        "strikePrice": "22250.0",
                        "moneyness": "ATM",
                    },
                    "quote": {"ltp": "99.25", "volume": 100},
                    "openInterest": {"current": 0},
                },
                {
                    "instrument": {
                        "neoSymbol": "nse_fo|71475",
                        "symbol": "NIFTY26JUN22300PE",
                        "optionType": "PE",
                        "strikePrice": "22300",
                    },
                    "quote": {},
                },
            ],
        }
    }


# Conservative wire bounds: these ordinary Indian-market examples must remain
# valid, while the compact/oversized cases below must be rejected before Decimal
# formatting can amplify them into thousands of transport characters.
_ORDINARY_BROKER_QUANTITY = Decimal("10000000")
_ORDINARY_BROKER_PRICE = Decimal("99999999.9999")
_ORDINARY_BROKER_TRIGGER = Decimal("0.0001")
_OUT_OF_BOUNDS_ORDER_NUMBERS = (
    pytest.param(
        "price",
        Decimal("12345678901234567890123456789012345678901234567890123456789012345"),
        id="65-significant-digits",
    ),
    pytest.param("quantity", Decimal("1e5000"), id="quantity-exponent-positive-5000"),
    pytest.param("price", Decimal("1e100000"), id="price-exponent-positive-100000"),
    pytest.param("price", Decimal("1e-5000"), id="price-scale-5000"),
)


@pytest.mark.parametrize(
    ("value", "accepted"),
    [
        (Decimal("9" * 64), True),
        (Decimal("9" * 65), False),
        (Decimal("1e-16"), True),
        (Decimal("1e-17"), False),
    ],
)
@pytest.mark.parametrize("mapper", ["place", "modify", "margin"])
def test_order_numeric_wire_shape_boundary(mapper, value, accepted):
    order = Order(
        symbol="IDEA",
        action="BUY",
        exchange="NSE",
        pricetype="MARKET",
        product="MIS",
        quantity="1",
    ).model_copy(update={"price": value})

    def mapped_params():
        if mapper == "place":
            return to_place_order_params(order, "IDEA-EQ")
        if mapper == "modify":
            return to_modify_order_params(
                "OID-1",
                {"pricetype": "MARKET", "quantity": "1", "price": value},
            )
        return to_margin_params(order, "14366")

    if accepted:
        assert mapped_params()["price"] == format(value, "f")
    else:
        with pytest.raises(KotakNeoMappingError, match="price"):
            mapped_params()


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


@pytest.mark.parametrize("amo", [None, 1, "", "sometimes"])
def test_modify_rejects_explicit_malformed_amo_instead_of_omitting_it(amo):
    with pytest.raises(KotakNeoMappingError, match="AMO"):
        to_modify_order_params(
            "1",
            {"pricetype": "MARKET", "price": 0, "quantity": 1, "amo": amo},
        )


def test_modify_validity_validated():
    assert to_modify_order_params(
        "1", {"pricetype": "MARKET", "price": 0, "quantity": 1, "validity": "IOC"}
    )["validity"] == "IOC"
    with pytest.raises(KotakNeoMappingError, match="validity"):
        to_modify_order_params(
            "1", {"pricetype": "MARKET", "price": 0, "quantity": 1, "validity": "GTC"}
        )


@pytest.mark.parametrize("mapper", ["place", "modify", "margin"])
def test_order_numeric_bounds_preserve_ordinary_indian_broker_values(mapper):
    order = Order(
        symbol="IDEA",
        action="BUY",
        exchange="NSE",
        pricetype="SL",
        product="MIS",
        quantity="1",
        price="1",
        trigger_price="1",
    ).model_copy(
        update={
            "quantity": _ORDINARY_BROKER_QUANTITY,
            "price": _ORDINARY_BROKER_PRICE,
            "trigger_price": _ORDINARY_BROKER_TRIGGER,
        }
    )

    if mapper == "place":
        params = to_place_order_params(order, "IDEA-EQ")
    elif mapper == "modify":
        params = to_modify_order_params(
            "OID-1",
            {
                "pricetype": "SL",
                "quantity": _ORDINARY_BROKER_QUANTITY,
                "price": _ORDINARY_BROKER_PRICE,
                "trigger_price": _ORDINARY_BROKER_TRIGGER,
            },
        )
    else:
        params = to_margin_params(order, "14366")

    assert params["quantity"] == "10000000"
    assert params["price"] == "99999999.9999"
    assert params["trigger_price"] == "0.0001"


@pytest.mark.parametrize("field,value", _OUT_OF_BOUNDS_ORDER_NUMBERS)
@pytest.mark.parametrize("mapper", ["place", "modify", "margin"])
def test_order_numeric_bounds_reject_pathological_decimals_without_expansion(mapper, field, value):
    order = Order(
        symbol="IDEA",
        action="BUY",
        exchange="NSE",
        pricetype="MARKET",
        product="MIS",
        quantity="1",
    ).model_copy(update={field: value})

    with pytest.raises(KotakNeoMappingError, match=field.replace("_", " ")):
        if mapper == "place":
            to_place_order_params(order, "IDEA-EQ")
        elif mapper == "modify":
            to_modify_order_params(
                "OID-1",
                {"pricetype": "MARKET", "quantity": "1", "price": "0", field: value},
            )
        else:
            to_margin_params(order, "14366")


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


def test_margin_instrument_token_wire_length_is_bounded_before_integer_conversion():
    order = Order(
        symbol="IDEA",
        action="BUY",
        exchange="NSE",
        pricetype="MARKET",
        product="MIS",
        quantity="1",
    )

    assert to_margin_params(order, "9" * 64)["instrument_token"] == "9" * 64
    for malformed in ("9" * 65, 10**5000):
        with pytest.raises(KotakNeoMappingError, match="numeric instrument_token"):
            to_margin_params(order, malformed)


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


@pytest.mark.parametrize("field", ["ordMrgn", "reqdMrgn", "avlCash", "insufFund"])
def test_margin_response_rejects_compact_numbers_that_expand_beyond_wire_bounds(field):
    response = {
        "data": {
            "stat": "Ok",
            "stCode": 200,
            "ordMrgn": "15.50",
            "reqdMrgn": "0",
            "avlCash": "38.19",
            "insufFund": "0",
            "rmsVldtd": "OK",
        }
    }
    response["data"][field] = "1e100000"

    with pytest.raises(BrokerReadResponseInvalid):
        from_kotak_margin(response)


def test_margin_response_rejects_oversized_primitive_int_as_canonical_read_error():
    response = {
        "data": {
            "stat": "Ok",
            "stCode": 200,
            "ordMrgn": 10**5000,
            "reqdMrgn": "0",
            "avlCash": "38.19",
            "insufFund": "0",
            "rmsVldtd": "OK",
        }
    }

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


@pytest.mark.parametrize(
    ("broker_product", "generation", "product", "variety", "amo"),
    [
        ("CNC", "AMO", "CNC", "amo", True),
        ("NRML", "NA", "NRML", "regular", False),
        ("BO", "NA", "MIS", "bracket", False),
        ("CO", "--", "MIS", "cover", False),
    ],
)
def test_from_kotak_order_retains_authoritative_product_and_generation(
    broker_product,
    generation,
    product,
    variety,
    amo,
):
    """Removing raw product/generation binding would make signed writes spoofable."""
    row = {
        "nOrdNo": "1",
        "ordSt": "open",
        "trdSym": "IDEA-EQ",
        "exSeg": "nse_cm",
        "trnsTp": "B",
        "prcTp": "L",
        "prod": broker_product,
        "qty": "10",
        "fldQty": "0",
        "prc": "9.39",
        "trgPrc": "0",
        "dscQty": "0",
        "vldt": "IOC",
        "ordGenTp": generation,
    }

    order = from_kotak_order(row)

    assert order["broker_product"] == broker_product
    assert order["product"] == product
    assert order["variety"] == variety
    assert order["amo"] is amo


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
    # Legacy terse REST/readback vocabulary: bp..bp4 bids, sp..sp4 offers,
    # bq../bs.. sizes, and bno/sno order counts.
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
# v3 historical candles
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("requested", "sdk_label"),
    [
        ("1m", "1min"),
        ("3min", "3min"),
        ("5", "5min"),
        ("10m", "10min"),
        ("15min", "15min"),
        ("30m", "30min"),
        ("60min", "60min"),
        ("1h", "60min"),
        ("1D", "D"),
        ("D", "D"),
        ("1W", "W"),
        ("W", "W"),
    ],
)
def test_historical_request_maps_supported_labels_without_changing_identity(requested, sdk_label):
    mapped = to_historical_request(
        {
            "symbol": "NIFTY",
            "exchange": "NSE_INDEX",
            "interval": requested,
            "start_date": "2026-09-01",
            "end_date": "2026-09-20",
        }
    )

    assert mapped == {
        "symbol": "NIFTY",
        "exchange": "NSE_INDEX",
        "interval": requested,
        "sdk_interval": sdk_label,
        "from_date": "2026-09-01",
        "to_date": "2026-09-20",
        "neosymbol": None,
    }


def test_historical_request_treats_explicit_null_neosymbol_as_omitted():
    mapped = to_historical_request(
        {
            "symbol": "NIFTY",
            "exchange": "NSE_INDEX",
            "interval": "1D",
            "start_date": "2026-09-01",
            "end_date": "2026-09-20",
            "neosymbol": None,
        }
    )
    assert mapped["neosymbol"] is None


@pytest.mark.parametrize(
    ("start_key", "end_key"),
    [("start_date", "end_date"), ("from_date", "to_date"), ("start", "end"), ("from", "to")],
)
def test_historical_request_accepts_each_documented_date_alias_pair(start_key, end_key):
    mapped = to_historical_request(
        {
            "symbol": "NIFTY",
            "exchange": "NSE",
            "interval": "D",
            start_key: "2026-01-01",
            end_key: "2026-06-29",
        }
    )
    assert mapped["from_date"] == "2026-01-01"
    assert mapped["to_date"] == "2026-06-29"


def test_historical_request_scans_all_same_value_date_aliases():
    mapped = to_historical_request(
        {
            "symbol": "NIFTY",
            "exchange": "NSE",
            "interval": "D",
            "start_date": "2026-01-01",
            "from_date": "2026-01-01",
            "start": "2026-01-01",
            "from": "2026-01-01",
            "end_date": "2026-01-02",
            "to_date": "2026-01-02",
            "end": "2026-01-02",
            "to": "2026-01-02",
        }
    )
    assert mapped["from_date"] == "2026-01-01"
    assert mapped["to_date"] == "2026-01-02"


def test_historical_request_rejects_a_malformed_secondary_alias_even_when_primary_is_valid():
    with pytest.raises(KotakNeoMappingError):
        to_historical_request(
            {
                "symbol": "NIFTY",
                "exchange": "NSE",
                "interval": "D",
                "start_date": "2026-01-01",
                "from_date": object(),
                "end_date": "2026-01-02",
            }
        )


@pytest.mark.parametrize(
    "updates",
    [
        {"from_date": "2026-09-02"},
        {"to_date": "2026-09-19"},
        {"interval": "2m"},
        {"start_date": "2026-02-30"},
        {"end_date": "2026-09-01", "start_date": "2026-09-20"},
        {"end_date": "2026-10-01"},  # 31 inclusive intraday days
        {"interval": "D", "start_date": "2026-01-01", "end_date": "2026-06-30"},  # 181 inclusive
        {"exchange": "MCX"},
    ],
)
def test_historical_request_rejects_conflicts_invalid_ranges_and_unsupported_values(updates):
    request = {
        "symbol": "NIFTY",
        "exchange": "NSE",
        "interval": "1m",
        "start_date": "2026-09-01",
        "end_date": "2026-09-30",
    }
    request.update(updates)
    if "from_date" in updates:
        request["start_date"] = "2026-09-01"
    if "to_date" in updates:
        request["end_date"] = "2026-09-20"
    with pytest.raises(KotakNeoMappingError):
        to_historical_request(request)


def test_historical_response_maps_exact_seven_column_v3_rows():
    response = {
        "status": "success",
        "interval": "1min",
        "data": {
            "candles": [
                ["2026-08-20T09:15:00+0530", 12009.9, 12019.35, 12001.25, 12001.5, 163275, None],
                ["2026-08-20T09:16:00+05:30", "12001", "12003", "11998.25", "12001", "0", 0],
            ]
        },
    }

    assert from_kotak_historical(response, expected_interval="1min") == [
        {
            "timestamp": "2026-08-20T09:15:00+0530",
            "open": 12009.9,
            "high": 12019.35,
            "low": 12001.25,
            "close": 12001.5,
            "volume": 163275,
        },
        {
            "timestamp": "2026-08-20T09:16:00+05:30",
            "open": 12001.0,
            "high": 12003.0,
            "low": 11998.25,
            "close": 12001.0,
            "volume": 0,
        },
    ]


@pytest.mark.parametrize(
    "row",
    [
        ["2026-08-20T09:15:00+0530", 1, 2, 0.5, 1.5, 10],
        ["2026-08-20T09:15:00+0530", 1, 2, 0.5, 1.5, 10, None, "extra"],
        ["not-a-timestamp", 1, 2, 0.5, 1.5, 10, None],
        ["2026-08-20T09:15:00+0530", True, 2, 0.5, 1.5, 10, None],
        ["2026-08-20T09:15:00+0530", 1, float("inf"), 0.5, 1.5, 10, None],
        ["2026-08-20T09:15:00+0530", 1, 2, 0.5, 1.5, -1, None],
        ["2026-08-20T09:15:00+0530", 1, 2, 0.5, 1.5, 1.5, None],
        ["2026-08-20T09:15:00+0530", 1, 2, 0.5, 1.5, True, None],
        ["2026-08-20T09:15:00+0530", 1, 2, 0.5, 1.5, 10, -1],
        ["2026-08-20T09:15:00+0530", 1, 2, 0.5, 1.5, 10, 1.5],
    ],
)
def test_historical_response_rejects_malformed_or_invented_candle_values(row):
    with pytest.raises(BrokerReadResponseInvalid):
        from_kotak_historical(
            {"status": "success", "interval": "1min", "data": {"candles": [row]}},
            expected_interval="1min",
        )


def test_historical_response_rejects_a_conflicting_interval_identity():
    with pytest.raises(BrokerReadResponseInvalid):
        from_kotak_historical(
            {
                "status": "success",
                "interval": "5min",
                "data": {"candles": [["2026-08-20T09:15:00+05:30", 1, 2, 0.5, 1.5, 10, None]]},
            },
            expected_interval="1min",
        )


# ---------------------------------------------------------------------------
# v3 option chain
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exchange", "sdk_exchange"),
    [
        ("NSE", "nse_fo"),
        ("NSE_INDEX", "nse_fo"),
        ("NFO", "nse_fo"),
        ("BSE", "bse_fo"),
        ("BSE_INDEX", "bse_fo"),
        ("BFO", "bse_fo"),
        ("MCX", "mcx_fo"),
    ],
)
def test_option_request_uses_narrow_derivative_segment_map(exchange, sdk_exchange):
    mapped = to_option_chain_request(
        {
            "underlying": "NIFTY",
            "exchange": exchange,
            "expiry": "2026-06-23",
            "instrument_type": "option",
            "count": 40,
        }
    )
    assert mapped == {
        "underlying": "NIFTY",
        "exchange": exchange,
        "sdk_exchange": sdk_exchange,
        "expiry": "2026-06-23",
        "instrument_type": "option",
        "count": 40,
    }


@pytest.mark.parametrize(
    "updates",
    [
        {"exchange": "CDS"},
        {"exchange": "UNKNOWN"},
        {"instrument_type": "fut"},
        {"instrument_type": "future"},
        {"expiry": ""},
        {"expiry": "23-06-2026"},
        {"expiry": "2026-02-30"},
        {"count": True},
        {"count": 0},
        {"count": -10},
        {"count": 15},
    ],
)
def test_option_request_rejects_unknown_segments_futures_and_invalid_count(updates):
    request = {"underlying": "NIFTY", "exchange": "NFO", "instrument_type": "option", "count": 40}
    request.update(updates)
    with pytest.raises(KotakNeoMappingError):
        to_option_chain_request(request)


def test_option_request_defaults_the_optional_sdk_fields_to_an_option_chain():
    mapped = to_option_chain_request({"symbol": "NIFTY", "exchange": "NSE_INDEX"})
    assert mapped["underlying"] == "NIFTY"
    assert mapped["instrument_type"] == "option"
    assert mapped["expiry"] is None
    assert mapped["count"] is None


def test_option_request_treats_explicit_null_sdk_defaults_as_omitted():
    mapped = to_option_chain_request(
        {
            "symbol": "NIFTY",
            "exchange": "NSE_INDEX",
            "expiry": None,
            "expiry_date": None,
            "instrument_type": None,
        }
    )
    assert mapped["instrument_type"] == "option"
    assert mapped["expiry"] is None


def test_option_request_ignores_null_expiry_alias_when_another_alias_is_supplied():
    mapped = to_option_chain_request(
        {
            "symbol": "NIFTY",
            "exchange": "NSE_INDEX",
            "expiry": None,
            "expiry_date": "2026-06-23",
        }
    )
    assert mapped["expiry"] == "2026-06-23"


def test_option_request_ignores_null_underlying_alias_when_symbol_is_supplied():
    mapped = to_option_chain_request(
        {
            "underlying": None,
            "symbol": "NIFTY",
            "exchange": "NSE_INDEX",
        }
    )
    assert mapped["underlying"] == "NIFTY"


def test_option_request_rejects_only_null_underlying_aliases():
    with pytest.raises(KotakNeoMappingError):
        to_option_chain_request({"underlying": None, "symbol": None, "exchange": "NSE_INDEX"})


def test_option_request_rejects_conflicting_underlying_aliases():
    with pytest.raises(KotakNeoMappingError):
        to_option_chain_request({"underlying": "NIFTY", "symbol": "BANKNIFTY", "exchange": "NFO"})


def test_option_response_merges_legs_by_numeric_strike_and_maps_only_observed_fields():
    mapped = from_kotak_option_chain(
        _official_option_chain_response(),
        underlying="NIFTY",
        exchange="NSE_INDEX",
        sdk_exchange="nse_fo",
        requested_expiry="2026-06-23",
    )

    assert mapped == {
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "expiry": "2026-06-23",
        "expiry_date": "2026-06-23",
        "strikes": [
            {
                "strike_price": 22250.0,
                "ce_instrument_id": "nse_fo|71472",
                "ce_ltp": 166.75,
                "ce_volume": 225431505,
                "ce_oi": 10715645,
                "pe_instrument_id": "nse_fo|71473",
                "pe_ltp": 99.25,
                "pe_volume": 100,
                "pe_oi": 0,
            },
            {"strike_price": 22300.0, "pe_instrument_id": "nse_fo|71475"},
        ],
    }
    assert "underlying_key" not in mapped
    assert "spot_price" not in mapped


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("common_data", "unlSymbol"), "BANKNIFTY"),
        (("common_data", "exSeg"), "bse_fo"),
        (("common_data", "expiryDt"), "2026-06-30"),
        (("common_data", "expiryDt"), None),
        (("common_data", "expiryDt"), ""),
        (("call", 0, "instrument", "optionType"), "PE"),
        (("call", 0, "instrument", "neoSymbol"), "bse_fo|71472"),
        (("call", 0, "instrument", "neoSymbol"), "nse_fo|0"),
        (("call", 0, "instrument", "strikePrice"), 0),
        (("call", 0, "instrument", "strikePrice"), float("inf")),
    ],
)
def test_option_response_rejects_common_and_leg_identity_mismatches(path, value):
    response = _official_option_chain_response()
    target = response["data"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(BrokerReadResponseInvalid):
        from_kotak_option_chain(
            response,
            underlying="NIFTY",
            exchange="NSE_INDEX",
            sdk_exchange="nse_fo",
            requested_expiry="2026-06-23",
        )


def test_option_response_rejects_duplicate_numeric_strike_within_one_side():
    response = _official_option_chain_response()
    duplicate = deepcopy(response["data"]["call"][0])
    duplicate["instrument"]["neoSymbol"] = "nse_fo|99999"
    duplicate["instrument"]["strikePrice"] = "22250.00"
    response["data"]["call"].append(duplicate)
    with pytest.raises(BrokerReadResponseInvalid):
        from_kotak_option_chain(
            response,
            underlying="NIFTY",
            exchange="NSE_INDEX",
            sdk_exchange="nse_fo",
            requested_expiry="2026-06-23",
        )


@pytest.mark.parametrize(
    ("container", "field", "value"),
    [
        ("quote", "ltp", True),
        ("quote", "ltp", float("nan")),
        ("quote", "volume", -1),
        ("quote", "volume", 1.5),
        ("openInterest", "current", -1),
        ("openInterest", "current", 1.5),
        ("openInterest", "current", True),
    ],
)
def test_option_response_rejects_invalid_observed_market_values(container, field, value):
    response = _official_option_chain_response()
    response["data"]["call"][0][container][field] = value
    with pytest.raises(BrokerReadResponseInvalid):
        from_kotak_option_chain(
            response,
            underlying="NIFTY",
            exchange="NSE_INDEX",
            sdk_exchange="nse_fo",
            requested_expiry="2026-06-23",
        )


def test_option_response_rejects_duplicate_instrument_ids_across_sides():
    response = _official_option_chain_response()
    response["data"]["put"][0]["instrument"]["neoSymbol"] = "nse_fo|71472"
    with pytest.raises(BrokerReadResponseInvalid):
        from_kotak_option_chain(
            response,
            underlying="NIFTY",
            exchange="NSE_INDEX",
            sdk_exchange="nse_fo",
            requested_expiry="2026-06-23",
        )


def test_option_response_rejects_strikes_that_collide_when_published_as_float():
    response = _official_option_chain_response()
    response["data"]["call"][0]["instrument"]["strikePrice"] = "9007199254740992"
    response["data"]["put"][0]["instrument"]["strikePrice"] = "9007199254740993"
    response["data"]["put"] = response["data"]["put"][:1]
    with pytest.raises(BrokerReadResponseInvalid):
        from_kotak_option_chain(
            response,
            underlying="NIFTY",
            exchange="NSE_INDEX",
            sdk_exchange="nse_fo",
            requested_expiry="2026-06-23",
        )


def test_option_response_rejects_a_single_strike_that_changes_when_published_as_float():
    response = _official_option_chain_response()
    response["data"]["call"][0]["instrument"]["strikePrice"] = "9007199254740993"
    response["data"]["put"] = []
    with pytest.raises(BrokerReadResponseInvalid):
        from_kotak_option_chain(
            response,
            underlying="NIFTY",
            exchange="NSE_INDEX",
            sdk_exchange="nse_fo",
            requested_expiry="2026-06-23",
        )


def test_market_data_mapping_never_invokes_untrusted_conversion_hooks():
    class Hostile:
        def __str__(self):
            raise AssertionError("__str__ must not run")

        def __float__(self):
            raise AssertionError("__float__ must not run")

        def __bool__(self):
            raise AssertionError("__bool__ must not run")

    hostile = Hostile()
    with pytest.raises(KotakNeoMappingError):
        to_historical_request(
            {
                "symbol": hostile,
                "exchange": "NSE",
                "interval": "D",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
            }
        )
    with pytest.raises(BrokerReadResponseInvalid):
        from_kotak_historical(
            {
                "status": "success",
                "interval": "D",
                "data": {"candles": [["2026-01-01T00:00:00+05:30", hostile, 2, 1, 1.5, 10, None]]},
            },
            expected_interval="D",
        )
    response = _official_option_chain_response()
    response["data"]["call"][0]["instrument"]["strikePrice"] = hostile
    with pytest.raises(BrokerReadResponseInvalid):
        from_kotak_option_chain(
            response,
            underlying="NIFTY",
            exchange="NSE_INDEX",
            sdk_exchange="nse_fo",
            requested_expiry="2026-06-23",
        )


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("１２３", id="unicode-digits"),
        pytest.param("\ud800", id="surrogate"),
        pytest.param(10**5000, id="huge-integer"),
    ],
)
def test_market_data_rejects_non_ascii_surrogate_and_unbounded_numeric_values(value):
    response = _official_option_chain_response()
    response["data"]["call"][0]["instrument"]["strikePrice"] = value
    with pytest.raises(BrokerReadResponseInvalid):
        from_kotak_option_chain(
            response,
            underlying="NIFTY",
            exchange="NSE_INDEX",
            sdk_exchange="nse_fo",
            requested_expiry="2026-06-23",
        )
