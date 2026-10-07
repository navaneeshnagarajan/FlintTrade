"""Regression contracts for the Dhan mappers actually used by DhanAdapter.

Request integers deliberately accept only built-in ints and ASCII digit strings;
read observations retain the legacy finite numeric-string/null/blank policy.
Companion REST tests are separate and cannot establish these SDK seam contracts.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_gateway.brokers import dhan_mapping as m

pytestmark = pytest.mark.unit


def order(**changes: Any) -> SimpleNamespace:
    fields = {
        "symbol": "TCS", "action": "BUY", "exchange": "NSE", "product": "CNC",
        "pricetype": "LIMIT", "quantity": "10", "price": "100", "trigger_price": "99",
        "disclosed_quantity": "0", "validity": "DAY", "target_price": "0",
        "stop_loss_price": "0", "trailing_jump": "0", "variety": "regular",
    }
    fields.update(changes)
    return SimpleNamespace(**fields)


@pytest.mark.parametrize("value", [True, False, 1.5, 1.0, "1.5", "1e1", "NaN", float("inf"),
                                  -1, "-1", 0, "invalid", None, object()])
def test_legacy_normal_quantities_are_exact(value: Any) -> None:
    with pytest.raises(m.DhanMappingError, match="quantity"):
        m.to_place_order_kwargs(order(quantity=value), "11536")


@pytest.mark.parametrize(("value", "expected"), [("10", 10), ("0010", 10),
                                                ("9007199254740993", 9007199254740993)])
def test_legacy_normal_quantity_has_no_float_round_trip(value: str, expected: int) -> None:
    mapped = m.to_place_order_kwargs(order(quantity=value), "11536")
    assert type(mapped["quantity"]) is int
    assert mapped["quantity"] == expected


def forever_changes(**changes: Any) -> dict[str, Any]:
    fields = {"order_flag": "SINGLE", "leg_name": "TARGET_LEG", "pricetype": "LIMIT",
              "quantity": "10", "price": "100", "trigger_price": "99",
              "disclosed_quantity": "0", "validity": "DAY"}
    fields.update(changes)
    return fields


def super_changes(**changes: Any) -> dict[str, Any]:
    fields = {"leg_name": "ENTRY_LEG", "pricetype": "LIMIT", "quantity": "10", "price": "100",
              "target_price": "110", "stop_loss_price": "90", "trailing_jump": "5"}
    fields.update(changes)
    return fields


QUANTITY_SEAMS = ("normal", "amo", "slice", "super", "forever", "modify", "modify_forever",
                  "modify_super", "margin", "conditional", "convert", "convert_alias")
DISCLOSURE_SEAMS = ("normal", "amo", "slice", "forever", "modify", "modify_forever", "conditional")
BAD_QUANTITIES = (True, False, 1.5, 1.0, "1.5", "1e1", "NaN", float("nan"), float("inf"),
                  -1, "-1", "invalid", None, object(), "１０")


def build(seam: str, **changes: Any) -> dict[str, Any]:
    if seam == "modify":
        return m.to_modify_order_kwargs("order-example", {"quantity": "10", **changes})
    if seam == "modify_forever":
        return m.to_modify_forever_kwargs("forever-example", forever_changes(**changes))
    if seam == "modify_super":
        return m.to_modify_super_order_kwargs("super-example", super_changes(**changes))
    if seam.startswith("convert"):
        request = {"from_product": "MIS", "to_product": "CNC", "exchange": "NSE",
                   "position_type": "LONG", **changes}
        if seam == "convert_alias":
            request["convert_qty"] = request.pop("quantity")
        return m.to_convert_position_kwargs(request, "11536")
    mapper = {"normal": m.to_place_order_kwargs, "amo": m.to_amo_order_payload,
              "slice": m.to_slice_order_kwargs, "super": m.to_super_order_kwargs,
              "forever": m.to_forever_kwargs, "margin": m.to_margin_kwargs,
              "conditional": m.to_conditional_order_leg}[seam]
    # Only the Super seam consumes active child protection. Ordinary fixtures
    # must not ask for fields that their exact expected wire body omits.
    protection = {"target_price": "110", "stop_loss_price": "90", "trailing_jump": "5"} if seam == "super" else {}
    return mapper(order(**{**protection, **changes}), "11536")


@pytest.mark.parametrize("seam", QUANTITY_SEAMS)
@pytest.mark.parametrize("value", (*BAD_QUANTITIES, 0, "0"))
def test_legacy_order_quantities_are_exact(seam: str, value: Any) -> None:
    with pytest.raises(m.DhanMappingError, match="quantity"):
        build(seam, quantity=value)


@pytest.mark.parametrize("seam", DISCLOSURE_SEAMS)
@pytest.mark.parametrize("value", BAD_QUANTITIES)
def test_legacy_disclosed_quantities_are_exact(seam: str, value: Any) -> None:
    with pytest.raises(m.DhanMappingError, match="disclosed_quantity"):
        build(seam, disclosed_quantity=value)


@pytest.mark.parametrize("seam", QUANTITY_SEAMS)
@pytest.mark.parametrize(("value", "expected"), [(10, 10), ("0010", 10),
                                                ("9007199254740993", 9007199254740993)])
def test_legacy_all_request_quantities_preserve_exact_integers(seam: str, value: Any, expected: int) -> None:
    mapped = build(seam, quantity=value)
    result = mapped["convert_qty" if seam.startswith("convert") else "quantity"]
    assert type(result) is int
    assert result == expected


@pytest.mark.parametrize("seam", DISCLOSURE_SEAMS)
@pytest.mark.parametrize(("value", "expected"), [(0, 0), ("0", 0), ("0010", 10),
                                                ("9007199254740993", 9007199254740993)])
def test_legacy_disclosure_zero_and_large_integers_remain_exact(seam: str, value: Any, expected: int) -> None:
    mapped = build(seam, quantity="9007199254740993", disclosed_quantity=value)
    if seam == "conditional":
        assert mapped["discQuantity"] == str(expected)
    else:
        result = mapped["disclosedQuantity" if seam == "amo" else "disclosed_quantity"]
        assert type(result) is int
        assert result == expected


def test_legacy_disclosure_omission_defaults_but_explicit_invalid_does_not() -> None:
    request = order()
    del request.disclosed_quantity
    assert m.to_place_order_kwargs(request, "11536")["disclosed_quantity"] == 0
    assert m.to_modify_order_kwargs("order-example", {"quantity": 10})["disclosed_quantity"] == 0


@pytest.mark.parametrize("changes", [
    {"quantity1": "invalid"}, {"quantity1": 0},
    {"price1": 0, "trigger_price1": 0, "quantity1": 0},
    {"price1": -1, "trigger_price1": -1, "quantity1": -1},
    {"price1": 110}, {"price1": None, "trigger_price1": 109, "quantity1": 10},
])
def test_legacy_forever_explicit_invalid_second_leg_never_becomes_single(changes: dict[str, Any]) -> None:
    with pytest.raises(m.DhanMappingError):
        m.to_forever_kwargs(order(**changes), "11536")


@pytest.mark.parametrize("value", (*BAD_QUANTITIES, 0, "0"))
def test_legacy_forever_second_quantity_is_exact(value: Any) -> None:
    with pytest.raises(m.DhanMappingError):
        m.to_forever_kwargs(order(price1="110", trigger_price1="109", quantity1=value), "11536")


@pytest.mark.parametrize("field", ["price1", "trigger_price1"])
@pytest.mark.parametrize("value", [True, False, "invalid", "NaN", float("inf"), object(), 0, -1])
def test_legacy_forever_second_prices_must_be_finite_and_positive(field: str, value: Any) -> None:
    changes = {"price1": "110", "trigger_price1": "109", "quantity1": "10", field: value}
    with pytest.raises(m.DhanMappingError):
        m.to_forever_kwargs(order(**changes), "11536")


def test_legacy_forever_absent_second_leg_and_exact_oco_request() -> None:
    for request in (order(), order(price1=None, trigger_price1=None, quantity1=None)):
        assert m.to_forever_kwargs(request, "11536")["order_flag"] == "SINGLE"
    mapped = m.to_forever_kwargs(order(price1="110", trigger_price1="109", quantity1="9007199254740993",
                                     validity="IOC"), "11536", tag="offline-contract")
    assert mapped == {"security_id": "11536", "exchange_segment": "NSE_EQ", "transaction_type": "BUY",
                      "product_type": "CNC", "order_type": "LIMIT", "quantity": 10, "price": 100.0,
                      "trigger_Price": 99.0, "order_flag": "OCO", "disclosed_quantity": 0,
                      "validity": "IOC", "symbol": "TCS", "price1": 110.0, "trigger_Price1": 109.0,
                      "quantity1": 9007199254740993, "tag": "offline-contract"}


@pytest.mark.parametrize("validity", ["GTC", "GTD", "GTT", "FOREVER", "unrecognised", ""])
def test_legacy_modify_order_rejects_unsupported_validity(validity: str) -> None:
    with pytest.raises(m.DhanMappingError, match="validity"):
        m.to_modify_order_kwargs("order-example", {"quantity": 10, "validity": validity})


@pytest.mark.parametrize(("supplied", "expected"), [(None, "DAY"), ("DAY", "DAY"), ("ioc", "IOC")])
def test_legacy_modify_order_validity_preserves_ordinary_contract(supplied: Any, expected: str) -> None:
    assert m.to_modify_order_kwargs("order-example", {"quantity": 10, "validity": supplied})["validity"] == expected
    assert m.to_modify_order_kwargs("order-example", {"quantity": 10})["validity"] == "DAY"
    assert m.VALIDITY_MAP["GTT"] == "FOREVER"


@pytest.mark.parametrize("product", ["MIS", "NRML"])
def test_legacy_forever_creation_rejects_ordinary_products(product: str) -> None:
    with pytest.raises(m.DhanMappingError, match="product"):
        m.to_forever_kwargs(order(product=product), "11536")
    # Resource-specific creation restrictions must not narrow these other seams.
    expected = "INTRADAY" if product == "MIS" else "MARGIN"
    assert m.to_margin_kwargs(order(product=product), "11536")["product_type"] == expected
    assert m.to_conditional_order_leg(order(product=product), "11536")["productType"] == expected


@pytest.mark.parametrize("product", ["CNC", "MTF"])
def test_legacy_forever_creation_retains_documented_products(product: str) -> None:
    assert m.to_forever_kwargs(order(product=product), "11536")["product_type"] == product


@pytest.mark.parametrize("pricetype", ["SL", "SL-M", "SLM", "STOP_LOSS", "STOP_LOSS_MARKET"])
def test_legacy_forever_creation_rejects_stop_types_only_at_creation(pricetype: str) -> None:
    with pytest.raises(m.DhanMappingError, match="order type"):
        m.to_forever_kwargs(order(pricetype=pricetype), "11536")
    expected = "STOP_LOSS" if pricetype in ("SL", "STOP_LOSS") else "STOP_LOSS_MARKET"
    assert m.to_modify_forever_kwargs("forever-example", forever_changes(pricetype=pricetype))["order_type"] == expected


@pytest.mark.parametrize("pricetype", ["LIMIT", "MARKET"])
def test_legacy_forever_creation_retains_limit_and_market(pricetype: str) -> None:
    price = "0" if pricetype == "MARKET" else "100"
    assert m.to_forever_kwargs(order(pricetype=pricetype, price=price), "11536")["order_type"] == pricetype


@pytest.mark.parametrize("family", ["SINGLE", "OCO"])
def test_legacy_forever_native_family_is_not_an_execution_type(family: str) -> None:
    mapped = m.from_dhan_forever_order({"orderType": family})
    assert mapped["order_flag"] == family
    assert mapped["broker_order_type"] == family
    assert mapped["pricetype"] == ""


@pytest.mark.parametrize(("flag", "order_type"), [("SINGLE", "OCO"), ("OCO", "SINGLE")])
def test_legacy_forever_rejects_contradictory_family_evidence(flag: str, order_type: str) -> None:
    with pytest.raises(BrokerReadResponseInvalid):
        m.from_dhan_forever_order({"orderFlag": flag, "orderType": order_type})


@pytest.mark.parametrize(("native", "canonical"), [("LIMIT", "LIMIT"), ("STOP_LOSS", "SL"),
                                                  ("STOP_LOSS_MARKET", "SL-M"), ("UNKNOWN_TYPE", "UNKNOWN_TYPE")])
def test_legacy_forever_family_and_raw_execution_type_are_both_preserved(native: str, canonical: str) -> None:
    mapped = m.from_dhan_forever_order({"orderFlag": "OCO", "orderType": native})
    assert mapped["order_flag"] == "OCO"
    assert mapped["broker_order_type"] == native
    assert mapped["pricetype"] == canonical


@pytest.mark.parametrize("extra", [{}, {"validity": None}, {"validity": ""}])
def test_legacy_forever_absent_validity_stays_absent(extra: dict[str, Any]) -> None:
    mapped = m.from_dhan_forever_order({"orderId": "forever-example", "orderStatus": "CONFIRM", **extra})
    assert "validity" not in mapped
    for absent in ("filled_quantity", "execution_order_id", "reduce_only", "terminal", "closed"):
        assert absent not in mapped


@pytest.mark.parametrize("validity", ["DAY", "IOC", "UNKNOWN_VALIDITY"])
def test_legacy_forever_supplied_validity_is_an_observation(validity: str) -> None:
    assert m.from_dhan_forever_order({"validity": validity})["validity"] == validity


@pytest.mark.parametrize(("native", "canonical"), [("CNC", "CNC"), ("MTF", "MTF"), ("INTRADAY", "MIS"),
                                                  ("MARGIN", "NRML"), ("CO", "MIS"), ("BO", "MIS"),
                                                  ("UNKNOWN_PRODUCT", "UNKNOWN_PRODUCT")])
@pytest.mark.parametrize(("segment", "exchange"), [("NSE_EQ", "NSE"), ("NSE_FNO", "NFO"),
                                                  ("MCX_COMM", "MCX"), ("UNKNOWN_SEGMENT", "UNKNOWN_SEGMENT")])
def test_legacy_forever_read_preserves_broker_product_and_historical_visibility(
    native: str, canonical: str, segment: str, exchange: str,
) -> None:
    mapped = m.from_dhan_forever_order({"productType": native, "exchangeSegment": segment})
    assert mapped["broker_product"] == native
    assert mapped["product"] == canonical
    assert mapped["exchange"] == exchange


@pytest.mark.parametrize("changes", [
    {"leg_name": "STOP_LOSS_LEG", "stop_loss_price": 90},
    {"leg_name": "STOP_LOSS_LEG", "trailing_jump": 0},
    {"leg_name": "TARGET_LEG"}, {}, {"leg_name": "ENTRY_LEG", "quantity": 10},
    {"leg_name": "TARGET_LEG", "price": 110},
])
def test_legacy_super_modify_requires_leg_specific_complete_intent(changes: dict[str, Any]) -> None:
    with pytest.raises(m.DhanMappingError):
        m.to_modify_super_order_kwargs("super-example", changes)


@pytest.mark.parametrize("missing", ["pricetype", "quantity", "price", "target_price", "stop_loss_price", "trailing_jump"])
def test_legacy_super_modify_requires_complete_entry_replacement(missing: str) -> None:
    changes = super_changes()
    del changes[missing]
    with pytest.raises(m.DhanMappingError):
        m.to_modify_super_order_kwargs("super-example", changes)


@pytest.mark.parametrize("field", ["price", "target_price", "stop_loss_price", "trailing_jump"])
@pytest.mark.parametrize("value", [True, False, "invalid", "NaN", float("nan"), float("inf"), object(), None, -1])
def test_legacy_super_modify_rejects_malformed_economic_intent(field: str, value: Any) -> None:
    with pytest.raises(m.DhanMappingError):
        m.to_modify_super_order_kwargs("super-example", super_changes(**{field: value}))


@pytest.mark.parametrize("camel_case", [False, True])
@pytest.mark.parametrize("trailing", [0, "0", 5, "5"])
def test_legacy_super_modify_explicit_trailing_and_aliases(camel_case: bool, trailing: Any) -> None:
    stop, jump = ("stopLossPrice", "trailingJump") if camel_case else ("stop_loss_price", "trailing_jump")
    mapped = m.to_modify_super_order_kwargs("super-example", {"leg_name": "STOP_LOSS_LEG", stop: "90", jump: trailing})
    assert mapped == {"order_id": "super-example", "leg_name": "STOP_LOSS_LEG", "order_type": "LIMIT",
                      "quantity": 0, "price": 0.0, "targetPrice": 0.0, "stopLossPrice": 90.0,
                      "trailingJump": 0.0 if trailing in (0, "0") else 5.0}


def test_legacy_super_target_only_and_complete_entry_remain_buildable() -> None:
    assert m.to_modify_super_order_kwargs("super-example", {"leg_name": "TARGET_LEG", "targetPrice": "110"}) == {
        "order_id": "super-example", "leg_name": "TARGET_LEG", "order_type": "LIMIT", "quantity": 0,
        "price": 0.0, "targetPrice": 110.0, "stopLossPrice": 0.0, "trailingJump": 0.0,
    }
    assert m.to_modify_super_order_kwargs("super-example", super_changes()) == {
        "order_id": "super-example", "leg_name": "ENTRY_LEG", "order_type": "LIMIT", "quantity": 10,
        "price": 100.0, "targetPrice": 110.0, "stopLossPrice": 90.0, "trailingJump": 5.0,
    }


@pytest.mark.parametrize(("value", "expected"), [(3, "3"), (0, "0"), ("3.0", "3.0"), (1.5, "1.5")])
def test_legacy_super_read_preserves_remaining_quantity(value: Any, expected: str) -> None:
    mapped = m.from_dhan_super_order({"remainingQuantity": value})
    assert mapped["remaining_quantity"] == expected
    assert "filled_quantity" not in mapped
    assert "quantity" not in mapped


@pytest.mark.parametrize("extra", [{}, {"remainingQuantity": None}, {"remainingQuantity": ""}])
def test_legacy_super_remaining_absence_is_not_zero(extra: dict[str, Any]) -> None:
    assert "remaining_quantity" not in m.from_dhan_super_order(extra)


@pytest.mark.parametrize("value", [True, False, "invalid", "NaN", float("nan"), float("inf"), object()])
def test_legacy_super_rejects_bad_remaining_evidence(value: Any) -> None:
    with pytest.raises(BrokerReadResponseInvalid):
        m.from_dhan_super_order({"remainingQuantity": value})


LEG_NUMERIC_FIELDS = ("totalQuatity", "remainingQuantity", "triggeredQuantity", "quantity", "filledQty", "tradedQty",
                      "price", "triggerPrice", "trailingJump", "targetPrice", "stopLossPrice", "averageTradedPrice",
                      "disclosedQuantity")


class HostileEvidence:
    def __init__(self) -> None:
        self.hooks: list[str] = []

    def __float__(self) -> float:
        self.hooks.append("float")
        raise AssertionError("Untrusted numeric conversion")

    def __str__(self) -> str:
        self.hooks.append("str")
        raise AssertionError("Untrusted text conversion")

    def __deepcopy__(self, memo: Any) -> Any:
        self.hooks.append("deepcopy")
        raise AssertionError("Untrusted copy hook")


@pytest.mark.parametrize("field", LEG_NUMERIC_FIELDS)
@pytest.mark.parametrize("kind", ["boolean", "nan", "infinity", "nonnumeric", "opaque"])
def test_legacy_super_rejects_invalid_nested_numeric_evidence(field: str, kind: str) -> None:
    hostile = HostileEvidence()
    bad = {"boolean": True, "nan": float("nan"), "infinity": float("inf"), "nonnumeric": "invalid", "opaque": hostile}
    with pytest.raises(BrokerReadResponseInvalid):
        m.from_dhan_super_order({"legDetails": [{"legName": "TARGET_LEG", "orderStatus": "PENDING", field: bad[kind]}]})
    assert hostile.hooks == []


@pytest.mark.parametrize("field", ["parentOrderId", "extension"])
def test_legacy_super_rejects_opaque_leg_values_without_hooks(field: str) -> None:
    hostile = HostileEvidence()
    with pytest.raises(BrokerReadResponseInvalid):
        m.from_dhan_super_order({"legDetails": [{"legName": "TARGET_LEG", field: hostile}]})
    assert hostile.hooks == []


@pytest.mark.parametrize("value", [True, 123, ["parent-example"], {"id": "parent-example"}])
def test_legacy_super_parent_identity_must_be_text_if_supplied(value: Any) -> None:
    with pytest.raises(BrokerReadResponseInvalid):
        m.from_dhan_super_order({"legDetails": [{"parentOrderId": value}]})


@pytest.mark.parametrize("value", [3, "3.0", 1.5, -1, None, ""])
def test_legacy_super_valid_nested_numbers_preserve_native_keys(value: Any) -> None:
    leg = {"legName": "TARGET_LEG", "orderStatus": "PENDING", **dict.fromkeys(LEG_NUMERIC_FIELDS, value)}
    assert m.from_dhan_super_order({"legDetails": [leg]})["legs"] == [leg]


def test_legacy_super_parent_trade_does_not_hide_same_id_live_legs() -> None:
    raw = {"orderId": "super-example", "orderStatus": "TRADED", "legDetails": [
        {"orderId": "super-example", "parentOrderId": "super-example", "legName": "TARGET_LEG",
         "orderStatus": "PENDING", "totalQuatity": 10, "remainingQuantity": 3, "price": "110"},
        {"orderId": "super-example", "legName": "STOP_LOSS_LEG", "orderStatus": "CANCEL_PENDING",
         "totalQuatity": 10, "remainingQuantity": 10, "price": 90, "triggeredQuantity": 0},
    ]}
    mapped = m.from_dhan_super_order(raw)
    assert mapped["status"] == "TRADED"
    assert mapped["legs"] == raw["legDetails"]
    assert mapped["leg_details_valid"] is True
    for observation in (mapped, *mapped["legs"]):
        for absent in ("filled_quantity", "filledQty", "execution_order_id", "terminal", "closed", "reduce_only"):
            assert absent not in observation


def test_legacy_super_leg_projection_is_detached_json_evidence() -> None:
    leg = {"legName": "TARGET_LEG", "parentOrderId": "super-example", "price": 110,
           "extension": {"observed": [True, None, 1, "3.0", {"tag": "offline"}]}}
    raw = {"legDetails": [leg]}
    mapped = m.from_dhan_super_order(raw)
    assert mapped["legs"] == [leg]
    leg["price"] = 999
    leg["extension"]["observed"][4]["tag"] = "changed"
    raw["legDetails"].append({"legName": "STOP_LOSS_LEG"})
    assert mapped["legs"] == [{"legName": "TARGET_LEG", "parentOrderId": "super-example", "price": 110,
                              "extension": {"observed": [True, None, 1, "3.0", {"tag": "offline"}]}}]
    mapped["legs"][0]["extension"]["observed"].append("projection-only")
    assert len(leg["extension"]["observed"]) == 5


def test_legacy_super_cyclic_leg_evidence_is_not_json() -> None:
    leg: dict[str, Any] = {"legName": "TARGET_LEG"}
    leg["extension"] = leg
    with pytest.raises(BrokerReadResponseInvalid):
        m.from_dhan_super_order({"legDetails": [leg]})


@pytest.mark.parametrize("mapper", [m.from_dhan_forever_order, m.from_dhan_super_order])
def test_legacy_advanced_orders_preserve_observed_timestamps(mapper: Any) -> None:
    mapped = mapper({"createTime": "2026-06-01 10:00:00", "updateTime": "2026-06-01 10:01:00",
                     "exchangeTime": "2026-06-01 10:00:01"})
    assert mapped["created_at"] == "2026-06-01 10:00:00"
    assert mapped["updated_at"] == "2026-06-01 10:01:00"
    assert mapped["exchange_time"] == "2026-06-01 10:00:01"
    absent = mapper({})
    assert "updated_at" not in absent
    assert "exchange_time" not in absent
    assert "fresh" not in mapped and "closed" not in mapped


@pytest.mark.parametrize("mapper", [m.from_dhan_forever_order, m.from_dhan_super_order])
@pytest.mark.parametrize("field", ["createTime", "updateTime", "exchangeTime"])
@pytest.mark.parametrize("value", [123, True, object()])
def test_legacy_advanced_timestamps_are_text_evidence_not_coerced(mapper: Any, field: str, value: Any) -> None:
    with pytest.raises(BrokerReadResponseInvalid):
        mapper({field: value})


@pytest.mark.parametrize("status", ["CONFIRM", "TRANSIT", "PENDING", "TRADED", "CANCELLED", "REJECTED", "EXPIRED",
                                    "CANCEL_PENDING", "", "UNKNOWN_STATUS"])
def test_legacy_forever_status_contract_identity_and_missing_execution_evidence(status: str) -> None:
    mapped = m.from_dhan_forever_order({
        "orderId": "forever-example", "exchangeOrderId": "exchange-example", "correlationId": "offline-contract",
        "orderFlag": "OCO", "orderType": "STOP_LOSS", "orderStatus": status, "legName": "STOP_LOSS_LEG",
        "tradingSymbol": "NIFTY-Jul2026-25000-CE", "securityId": "49081", "exchangeSegment": "NSE_FNO",
        "transactionType": "SELL", "productType": "MARGIN", "quantity": 10, "price": 100, "triggerPrice": 99,
        "quantity1": 10, "price1": 90, "triggerPrice1": 91, "drvOptionType": "CALL",
        "drvExpiryDate": "2026-07-30", "drvStrikePrice": 25000,
    })
    assert (mapped["orderid"], mapped["exchange_order_id"], mapped["correlation_id"]) == (
        "forever-example", "exchange-example", "offline-contract",
    )
    assert mapped["status"] == status
    assert mapped["leg_name"] == "STOP_LOSS_LEG" and mapped["pricetype"] == "SL"
    assert (mapped["option_type"], mapped["expiry"], mapped["strike_price"], mapped["underlying"]) == (
        "CE", "2026-07-30", 25000.0, "NIFTY",
    )
    assert (mapped["quantity"], mapped["price"], mapped["trigger_price"], mapped["quantity1"],
            mapped["price1"], mapped["trigger_price1"]) == ("10", "100", "99", "10", "90", "91")
    assert mapped["oco_leg_complete"] is True
    for absent in ("filled_quantity", "execution_order_id", "reduce_only", "terminal", "closed", "validity"):
        assert absent not in mapped


@pytest.mark.parametrize("seam", QUANTITY_SEAMS)
def test_legacy_request_quantities_never_invoke_opaque_conversion_hooks(seam: str) -> None:
    hostile = HostileEvidence()
    with pytest.raises(m.DhanMappingError):
        build(seam, quantity=hostile)
    assert hostile.hooks == []


def test_legacy_missing_primary_quantities_are_mapped_refusals_not_defaults() -> None:
    missing = order()
    del missing.quantity
    for mapper in (m.to_place_order_kwargs, m.to_super_order_kwargs, m.to_forever_kwargs,
                   m.to_conditional_order_leg, m.to_margin_kwargs):
        with pytest.raises(m.DhanMappingError, match="quantity"):
            mapper(missing, "11536")
    with pytest.raises(m.DhanMappingError, match="quantity"):
        m.to_modify_order_kwargs("order-example", {})
    with pytest.raises(m.DhanMappingError, match="quantity"):
        m.to_convert_position_kwargs({"from_product": "MIS", "to_product": "CNC"}, "11536")
