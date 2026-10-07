"""Regressions at the legacy Delta mapper used by the actual adapter."""

from __future__ import annotations

from copy import deepcopy
from decimal import localcontext
from types import SimpleNamespace

import pytest

from flinttrade_core.exceptions import BrokerError
from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_gateway.brokers import delta_mapping as M

pytestmark = pytest.mark.unit


def _order(**changes: object) -> SimpleNamespace:
    fields: dict[str, object] = {
        "symbol": "CRYPTO:BTCUSD", "action": "BUY", "quantity": "10",
        "pricetype": "LIMIT", "price": "59000.50", "validity": "DAY", "variety": "regular",
    }
    fields.update(changes)
    return SimpleNamespace(**fields)


def test_legacy_mapper_uses_native_boolean_reduce_only() -> None:
    assert M.to_place_payload(_order(), reduce_only=True)["reduce_only"] is True
    assert "reduce_only" not in M.to_place_payload(_order(), reduce_only=False)
    for flag in ("true", "false", 0, 1, None):
        with pytest.raises(BrokerError, match="boolean"):
            M.to_place_payload(_order(), reduce_only=flag)


@pytest.mark.parametrize("counts,expected,status", [
    ({}, {}, "UNKNOWN"),
    ({"size": 10}, {"quantity": "10"}, "UNKNOWN"),
    ({"unfilled_size": 2}, {"remaining_quantity": "2"}, "UNKNOWN"),
    ({"size": 10, "unfilled_size": 2}, {
        "quantity": "10", "remaining_quantity": "2", "filled_quantity": "8",
    }, "UNKNOWN"),
    ({"size": 10, "unfilled_size": 0}, {
        "quantity": "10", "remaining_quantity": "0", "filled_quantity": "10",
    }, "COMPLETE"),
])
def test_legacy_closed_order_requires_coherent_observed_counts(counts: dict, expected: dict, status: str) -> None:
    result = M.from_order({"id": 123, "product_symbol": "BTCUSD", "state": "closed", **counts})
    assert {key: value for key, value in result.items() if key in {
        "quantity", "remaining_quantity", "filled_quantity",
    }} == expected
    assert result["status"] == status
    assert result["raw_status"] == "closed"
    assert result["quantity_unit"] == "contracts"


@pytest.mark.parametrize("field", ["size", "unfilled_size"])
@pytest.mark.parametrize("value", [True, None, "", -1, "-1", 1.5, "1.5", "NaN", "Infinity", 10.0, "1e1"])
def test_legacy_order_refuses_impossible_contract_evidence(field: str, value: object) -> None:
    with pytest.raises(BrokerReadResponseInvalid):
        M.from_order({"size": 10, "unfilled_size": 2, field: value})


@pytest.mark.parametrize("counts", [{"size": 0}, {"size": 10, "unfilled_size": 11}])
def test_legacy_order_refuses_oversized_remainder_or_zero_total(counts: dict) -> None:
    with pytest.raises(BrokerReadResponseInvalid):
        M.from_order(counts)


def test_legacy_cancelled_order_retains_exact_partial_and_detached_native_evidence() -> None:
    row = {
        "id": 123, "product_id": 27, "product_symbol": "BTCUSD", "state": "cancelled",
        "size": "123456789012345678901234567890", "unfilled_size": "2",
        "reduce_only": False, "client_order_id": "fixture-intent", "created_at": "1725865012000000",
        "stop_order_type": "take_profit_order", "bracket_stop_loss_price": "56000.00",
        "cancellation_reason": "cancelled_by_user", "children": [{"id": 124, "state": "pending"}],
    }
    original = deepcopy(row)
    with localcontext() as context:
        context.prec = 6
        result = M.from_order(row)
    assert result["filled_quantity"] == "123456789012345678901234567888"
    assert result["status"] == "CANCELLED"
    assert result["attempt_state"] == "CANCELLED"
    assert result["exchange"] == "CRYPTO"
    assert result["product"] == "MARGIN"
    assert result["native"] == original
    result["native"]["children"][0]["id"] = 999
    assert row == original


@pytest.mark.parametrize("state", ["OPEN", " Closed ", "complete", "FILLED", "cancel_pending", None, []])
def test_legacy_order_unknown_native_state_never_becomes_terminal(state: object) -> None:
    result = M.from_order({"state": state, "size": 10, "unfilled_size": 0})
    assert result["status"] == "UNKNOWN"
    assert result["attempt_state"] == "UNKNOWN"
    assert result["native"]["state"] == state


@pytest.mark.parametrize("value", [True, "-1", "NaN", "Infinity", "sNaN", "not-a-price"])
@pytest.mark.parametrize("field", ["price", "trigger_price", "stop_loss_price"])
def test_legacy_placement_refuses_invalid_applicable_decimal(field: str, value: object) -> None:
    with pytest.raises(BrokerError):
        M.to_place_payload(_order(**{"pricetype": "SL", "price": "59000.50", "trigger_price": "56000", field: value}))


def test_legacy_stop_aliases_cannot_override_or_reuse_bracket_protection() -> None:
    with pytest.raises(BrokerError, match="conflict"):
        M.to_place_payload(_order(pricetype="SL", trigger_price="57000", stop_loss_price="56000"))
    payload = M.to_place_payload(_order(
        pricetype="SL", variety="bracket", trigger_price="57000.00",
        stop_loss_price="56000.00", target_price="61000.00", trailing_jump="50.00",
    ))
    assert payload["stop_price"] == "57000.00"
    assert payload["bracket_stop_loss_price"] == "56000.00"
    assert payload["bracket_take_profit_price"] == "61000.00"
    assert payload["bracket_trail_amount"] == "50.00"
    with pytest.raises(BrokerError):
        M.to_place_payload(_order(pricetype="SL", variety="bracket", stop_loss_price="56000"))


@pytest.mark.parametrize("changes", [
    {"symbol": "BTCUSD", "price": "1", "limit_price": "2"},
    {"symbol": "BTCUSD", "quantity": "1", "size": "2"},
    {"symbol": "BTCUSD", "trigger_price": "1", "stop_price": "2"},
    {"symbol": "BTCUSD", "product_symbol": "ETHUSD", "price": "1"},
    {"product_symbol": "BTCUSD", "product_id": 27, "price": "1"},
    {"product_id": True, "price": "1"},
    {"product_id": 27, "limit_price": "NaN"},
    {"product_id": 27, "quantity": "1.5"},
])
def test_legacy_edit_rejects_alias_and_identity_conflicts(changes: dict) -> None:
    with pytest.raises(BrokerError):
        M.to_edit_payload("123", changes)


def test_legacy_edit_preserves_agreeing_exact_aliases() -> None:
    assert M.to_edit_payload("123", {
        "symbol": "CRYPTO:BTCUSD", "product_symbol": "BTCUSD", "quantity": "10", "size": 10,
        "price": "59000.50", "limit_price": "59000.500", "trigger_price": "56000.00", "stop_price": "56000",
    }) == {
        "id": 123, "product_symbol": "BTCUSD", "size": 10,
        "limit_price": "59000.500", "stop_price": "56000",
    }


@pytest.mark.parametrize("price_type,native", [
    ("SL-M", {"stop_price": "56000.00"}),
    ("SL-M", {"trail_amount": "50.00"}),
    ("LIMIT", {"stop_order_type": "take_profit_order", "stop_price": "61000.00",
               "stop_trigger_method": "spot_price"}),
])
def test_legacy_native_conditional_options_reach_exact_payload(price_type: str, native: dict) -> None:
    options = {"post_only": False, "client_order_id": "fixture-intent", **native}
    payload = M.to_place_payload(_order(pricetype=price_type), native=options, reduce_only=True)
    assert payload["size"] == 10
    assert payload["post_only"] is False
    assert payload["client_order_id"] == "fixture-intent"
    assert payload["reduce_only"] is True
    assert payload["stop_order_type"] == native.get("stop_order_type", "stop_loss_order")
    assert all(payload[key] == value for key, value in native.items())
    M.validate_contract_payload(payload, tick_size="0.50")
    with pytest.raises(BrokerError):
        M.validate_contract_payload({**payload, "stop_price": "56000.51"}, tick_size="0.50")


def test_legacy_native_bracket_options_are_not_silently_lost() -> None:
    payload = M.to_place_payload(_order(
        variety="bracket", stop_loss_price="56000.00", target_price="61000.00", trailing_jump="50.00",
    ), native={"bracket_stop_loss_limit_price": "55000.50", "bracket_take_profit_limit_price": "61000.50",
               "bracket_stop_trigger_method": "last_traded_price"})
    assert payload["bracket_stop_loss_price"] == "56000.00"
    assert payload["bracket_stop_loss_limit_price"] == "55000.50"
    assert payload["bracket_take_profit_limit_price"] == "61000.50"
    assert payload["bracket_stop_trigger_method"] == "last_traded_price"


@pytest.mark.parametrize("native", [{"reduce_only": True}, {"post_only": "false"}, {"client_order_id": "x" * 33},
                                       {"stop_price": "0"}, {"stop_trigger_method": "index_price"}])
def test_legacy_native_invalid_options_fail_as_broker_errors(native: dict) -> None:
    with pytest.raises(BrokerError):
        M.to_place_payload(_order(), native=native)


@pytest.mark.parametrize("changes", [{"post_only": True}, {"native": {"post_only": False}}, {"target_price": "61000"},
                                        {"trailing_jump": "50"}, {"stop_order_type": "take_profit_order"}])
def test_canonical_placement_refuses_unmodelled_native_intent_instead_of_silently_dropping_it(changes: dict) -> None:
    with pytest.raises(BrokerError):
        M.to_place_payload(_order(**changes))


@pytest.mark.parametrize("changes", [{"post_only": "false"}, {"mmp": "arbitrary"}, {"trail_amount": "NaN"},
                                        {"reduce_only": True}, {"client_order_id": "mutation"}])
def test_ordinary_modification_refuses_invalid_or_unsupported_native_mutations(changes: dict) -> None:
    with pytest.raises(BrokerError):
        M.to_edit_payload("7", {"product_id": 27, "size": 10, **changes})
