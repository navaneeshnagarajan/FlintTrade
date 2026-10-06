"""Independent tests of Delta's pure native placement and precision mapping."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, localcontext
from types import SimpleNamespace

import pytest

from flinttrade_core.exceptions import BrokerError
import flinttrade_gateway.brokers.delta_order_mapping as mapping


def _order(**changes: object) -> SimpleNamespace:
    fields = {
        "symbol": "CRYPTO:BTCUSD",
        "action": "BUY",
        "pricetype": "LIMIT",
        "quantity": 10,
        "price": "59000.50",
        "validity": "DAY",
        "variety": "regular",
        "contract_value": "0.001",
    }
    fields.update(changes)
    return SimpleNamespace(**fields)


def _payload(**changes: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "product_symbol": "BTCUSD",
        "size": 10,
        "side": "buy",
        "time_in_force": "gtc",
        "order_type": "limit_order",
        "limit_price": "59000.50",
    }
    fields.update(changes)
    return fields


def test_native_options_preserved() -> None:
    native = {
        "post_only": True,
        "client_order_id": "intent-0001",
        "stop_order_type": "stop_loss_order",
        "stop_price": "56000.00",
        "trail_amount": "50.00",
        "stop_trigger_method": "last_traded_price",
        "bracket_stop_loss_limit_price": "55000.50",
        "bracket_take_profit_limit_price": "61000.50",
        "bracket_stop_trigger_method": "spot_price",
    }
    original = native.copy()
    result = mapping.to_native_place_payload(_order(), native=native)
    assert result == {**_payload(), **native}
    assert native == original


@pytest.mark.parametrize("reduce_only", [False, True])
def test_reduce_only_boolean(reduce_only: bool) -> None:
    result = mapping.to_native_place_payload(_order(), native={}, reduce_only=reduce_only)
    assert result.get("reduce_only", False) is reduce_only
    assert "reduce_only" not in result or type(result["reduce_only"]) is bool


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None])
def test_reduce_only_requires_explicit_boolean(value: object) -> None:
    with pytest.raises(ValueError, match="reduce_only"):
        mapping.to_native_place_payload(_order(), native={}, reduce_only=value)


def test_native_cannot_override_reduce_only() -> None:
    with pytest.raises(ValueError, match="reduce_only"):
        mapping.to_native_place_payload(_order(), native={"reduce_only": True})


def test_contract_precision() -> None:
    result = mapping.to_native_place_payload(_order(), native={})
    assert result["size"] == 10
    assert result["limit_price"] == "59000.50"
    assert result["time_in_force"] == "gtc"
    mapping.validate_contract_payload(result, tick_size="0.50")


@pytest.mark.parametrize("quantity", [0.01, "0.01", True, False, 0, -1, "NaN", "Infinity"])
def test_invalid_contract_count_is_rejected(quantity: object) -> None:
    with pytest.raises(ValueError, match="size|contract|quantity"):
        mapping.to_native_place_payload(_order(quantity=quantity), native={})
    with pytest.raises(ValueError, match="size|contract|quantity"):
        mapping.validate_contract_payload(_payload(size=quantity), tick_size="0.50")


@pytest.mark.parametrize("field", [
    "limit_price", "stop_price", "trail_amount", "bracket_stop_loss_price", "bracket_take_profit_price",
    "bracket_trail_amount", "bracket_stop_loss_limit_price", "bracket_take_profit_limit_price",
])
@pytest.mark.parametrize("value", [True, False, "NaN", "sNaN", "Infinity", "-Infinity", "0", "-0.5"])
def test_invalid_decimal_fields_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError, match=field):
        mapping.validate_contract_payload(_payload(**{field: value}), tick_size="0.50")


@pytest.mark.parametrize("tick", [True, False, "NaN", "Infinity", "0", "-0.5", ""])
def test_invalid_tick_size_is_rejected(tick: object) -> None:
    with pytest.raises(ValueError, match="tick_size"):
        mapping.validate_contract_payload(_payload(), tick_size=tick)


@pytest.mark.parametrize("field", [
    "limit_price", "stop_price", "trail_amount", "bracket_stop_loss_price", "bracket_take_profit_price",
    "bracket_trail_amount", "bracket_stop_loss_limit_price", "bracket_take_profit_limit_price",
])
def test_tick_violation_is_rejected_without_rounding(field: str) -> None:
    payload = _payload(**{field: "59000.51"})
    original = payload.copy()
    with pytest.raises(ValueError, match=field):
        mapping.validate_contract_payload(payload, tick_size="0.50")
    assert payload == original


def test_tick_validation_is_exact_beyond_decimal_context_precision() -> None:
    payload = _payload(limit_price="123456789012345678901234567890.50")
    with localcontext() as context:
        context.prec = 6
        mapping.validate_contract_payload(payload, tick_size="0.50")
        with pytest.raises(ValueError, match="limit_price"):
            mapping.validate_contract_payload(
                _payload(limit_price="123456789012345678901234567890.51"), tick_size="0.50",
            )


@pytest.mark.parametrize("price_type", ["SL-M", "SLM"])
def test_native_only_stop_price(price_type: str) -> None:
    result = mapping.to_native_place_payload(_order(pricetype=price_type), native={"stop_price": "56000"})
    assert result == {
        **{key: value for key, value in _payload().items() if key != "limit_price"},
        "order_type": "market_order",
        "stop_order_type": "stop_loss_order",
        "stop_price": "56000",
        "stop_trigger_method": "mark_price",
    }


def test_trailing_only_stop() -> None:
    result = mapping.to_native_place_payload(_order(pricetype="SL-M"), native={"trail_amount": "50"})
    assert result["stop_order_type"] == "stop_loss_order"
    assert result["order_type"] == "market_order"
    assert result["trail_amount"] == "50"
    assert result["stop_trigger_method"] == "mark_price"
    assert "stop_price" not in result
    assert "limit_price" not in result


def test_stop_limit_uses_native_trigger_before_required_field_validation() -> None:
    result = mapping.to_native_place_payload(_order(pricetype="SL"), native={"stop_price": "56000"})
    assert result["order_type"] == "limit_order"
    assert result["limit_price"] == "59000.50"
    assert result["stop_price"] == "56000"


def test_canonical_stop_aliases_are_preserved() -> None:
    result = mapping.to_native_place_payload(
        _order(pricetype="SL-M", trigger_price="56000", stop_loss_price="56000.00"),
        native={"stop_price": "56000.000"},
    )
    assert result["stop_price"] == "56000.000"


@pytest.mark.parametrize("changes,native", [
    ({"trigger_price": "56000"}, {"stop_price": "55000"}),
    ({"stop_loss_price": "56000"}, {"stop_price": "55000"}),
    ({"trigger_price": "56000", "stop_loss_price": "55000"}, {}),
])
def test_conflicting_stop_aliases_are_rejected(changes: dict, native: dict) -> None:
    with pytest.raises(ValueError, match="conflict"):
        mapping.to_native_place_payload(_order(pricetype="SL-M", **changes), native=native)


@pytest.mark.parametrize("native", [{}, {"stop_trigger_method": "mark_price"}, {"stop_order_type": "stop_loss_order"}])
def test_conditional_order_requires_stop_or_trailing_amount(native: dict) -> None:
    with pytest.raises(ValueError, match="stop_price|trail_amount"):
        mapping.to_native_place_payload(_order(pricetype="SL-M"), native=native)


def test_payload_validator_enforces_conditional_shape() -> None:
    with pytest.raises(ValueError, match="stop_price|trail_amount"):
        mapping.validate_contract_payload(_payload(stop_order_type="stop_loss_order"), tick_size="0.50")
    with pytest.raises(ValueError, match="limit_price"):
        mapping.validate_contract_payload(
            {key: value for key, value in _payload().items() if key != "limit_price"}, tick_size="0.50",
        )


@pytest.mark.parametrize("native", [
    {"post_only": "false"}, {"post_only": 1},
    {"client_order_id": "x" * 33}, {"client_order_id": 123},
    {"stop_order_type": "trailing_stop"},
    {"stop_trigger_method": "index_price"}, {"bracket_stop_trigger_method": "index_price"},
    {"unrecognised": "value"},
    {"stop_price": True}, {"trail_amount": "NaN"}, {"bracket_stop_loss_limit_price": "Infinity"},
])
def test_native_options_reject_invalid_values(native: dict) -> None:
    with pytest.raises(ValueError):
        mapping.to_native_place_payload(_order(), native=native)


@pytest.mark.parametrize("trigger", ["mark_price", "last_traded_price", "spot_price"])
@pytest.mark.parametrize("kind", ["stop_loss_order", "take_profit_order"])
def test_documented_conditional_kinds_and_trigger_methods(kind: str, trigger: str) -> None:
    result = mapping.to_native_place_payload(
        _order(pricetype="MARKET"),
        native={"stop_order_type": kind, "stop_price": "56000", "stop_trigger_method": trigger},
        reduce_only=True,
    )
    assert result["stop_order_type"] == kind
    assert result["stop_trigger_method"] == trigger
    assert result["reduce_only"] is True


def test_existing_bracket_fields_survive_ordinary_composition() -> None:
    result = mapping.to_native_place_payload(
        _order(variety="bracket", target_price="61000", stop_loss_price="56000", trailing_jump="50"),
        native={"bracket_stop_loss_limit_price": "55000.50", "bracket_take_profit_limit_price": "61000.50"},
        reduce_only=True,
    )
    assert result["bracket_stop_loss_price"] == "56000"
    assert result["bracket_take_profit_price"] == "61000"
    assert result["bracket_trail_amount"] == "50"
    assert result["bracket_stop_trigger_method"] == "mark_price"
    assert "stop_order_type" not in result
    assert result["reduce_only"] is True


def test_decimal_input_is_not_converted_through_float() -> None:
    result = mapping.to_native_place_payload(_order(price=Decimal("59000.50")), native={})
    assert result["limit_price"] == "59000.50"


def test_conditional_bracket_keeps_entry_and_protection_stop_distinct() -> None:
    result = mapping.to_native_place_payload(
        _order(pricetype="SL", variety="bracket", trigger_price="57000", stop_loss_price="56000", target_price="61000"),
        native={"stop_price": "57000.00", "bracket_stop_trigger_method": "last_traded_price"},
    )
    assert result["stop_price"] == "57000.00"
    assert result["bracket_stop_loss_price"] == "56000"
    assert result["bracket_take_profit_price"] == "61000"
    assert result["bracket_stop_trigger_method"] == "last_traded_price"


def test_conditional_bracket_cannot_reuse_protection_as_entry_trigger() -> None:
    with pytest.raises(ValueError, match="stop_price|trail_amount"):
        mapping.to_native_place_payload(
            _order(pricetype="SL", variety="bracket", stop_loss_price="56000", target_price="61000"),
            native={},
        )


def test_native_client_id_boundary_and_post_only_false() -> None:
    result = mapping.to_native_place_payload(_order(), native={"client_order_id": "x" * 32, "post_only": False})
    assert result["client_order_id"] == "x" * 32
    assert result["post_only"] is False


@pytest.mark.parametrize("field", ["stop_order_type", "stop_trigger_method", "bracket_stop_trigger_method"])
@pytest.mark.parametrize("value", [[], {}])
def test_malformed_native_enum_fields_raise_value_error(field: str, value: object) -> None:
    with pytest.raises(ValueError, match=field):
        mapping.to_native_place_payload(_order(), native={field: value})
    with pytest.raises(ValueError, match=field):
        mapping.validate_contract_payload(_payload(**{field: value}), tick_size="0.50")


@pytest.mark.parametrize("value", [[], {}])
def test_malformed_order_type_raises_value_error(value: object) -> None:
    with pytest.raises(ValueError, match="order_type"):
        mapping.validate_contract_payload(_payload(order_type=value), tick_size="0.50")


@pytest.mark.parametrize("value", [None, []])
def test_non_mapping_payload_raises_value_error(value: object) -> None:
    with pytest.raises(ValueError, match="mapping"):
        mapping.validate_contract_payload(value, tick_size="0.50")


@pytest.mark.parametrize("value", [None, []])
def test_non_mapping_native_options_raise_value_error(value: object) -> None:
    with pytest.raises(ValueError, match="mapping"):
        mapping.to_native_place_payload(_order(), native=value)


@pytest.mark.parametrize("field", ["price", "trigger_price", "stop_loss_price"])
@pytest.mark.parametrize("value", [True, False, "NaN", "Infinity", "-Infinity"])
def test_invalid_canonical_decimal_is_rejected_before_string_conversion(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        mapping.to_native_place_payload(_order(pricetype="SL", **{field: value}), native={"stop_price": "56000"})


@pytest.mark.parametrize("price_type,native", [("LIMIT", {}), ("SL-M", {"stop_price": "56000"})])
@pytest.mark.parametrize("changes", [{"symbol": ""}, {"action": "SIDEWAYS"}, {"validity": "FOK"}])
def test_existing_canonical_broker_errors_remain_inherited(price_type: str, native: dict, changes: dict) -> None:
    with pytest.raises(BrokerError) as error:
        mapping.to_native_place_payload(_order(pricetype=price_type, **changes), native=native)
    assert error.value.broker_id == "deltaexchange"


def _bracket_call(builder: str, fields: object) -> dict[str, object]:
    if builder == "order":
        return mapping.to_order_bracket_edit_payload("34521712", fields)
    return mapping.to_position_bracket_create_payload(fields)


def _bracket_fields(builder: str, **changes: object) -> dict[str, object]:
    fields: dict[str, object] = {"product_symbol": "BTCUSD"}
    if builder == "order":
        fields["bracket_stop_loss_price"] = "56000.00"
    else:
        fields["stop_loss_order"] = {"order_type": "market_order", "stop_price": "56000.00"}
    fields.update(changes)
    return fields


def test_order_bracket_edit_is_flat() -> None:
    changes = {
        "product_id": "27",
        "bracket_stop_loss_price": Decimal("56000.00"),
        "bracket_stop_loss_limit_price": "55000.50",
        "bracket_take_profit_price": "61000.00",
        "bracket_take_profit_limit_price": "61000.50",
        "bracket_trail_amount": "50.00",
        "bracket_stop_trigger_method": "last_traded_price",
    }
    original = changes.copy()
    result = mapping.to_order_bracket_edit_payload("34521712", changes)
    assert result == {**changes, "id": 34521712, "product_id": 27, "bracket_stop_loss_price": "56000.00"}
    assert type(result["id"]) is int
    assert type(result["product_id"]) is int
    assert "stop_loss_order" not in result
    assert "take_profit_order" not in result
    assert changes == original


def test_position_bracket_create_is_nested() -> None:
    request = {
        "product_symbol": "BTCUSD",
        "stop_loss_order": {
            "order_type": "limit_order", "stop_price": Decimal("56000.00"),
            "limit_price": "55000.50", "trail_amount": "50.00",
        },
        "take_profit_order": {"order_type": "limit_order", "stop_price": "61000.00", "limit_price": "61000.50"},
        "bracket_stop_trigger_method": "spot_price",
    }
    result = mapping.to_position_bracket_create_payload(request)
    assert result == {
        **request, "stop_loss_order": {**request["stop_loss_order"], "stop_price": "56000.00"},
    }
    assert "id" not in result
    assert "size" not in result
    assert not any(key.startswith("bracket_stop_loss_") for key in result)
    assert result["stop_loss_order"] is not request["stop_loss_order"]
    assert result["take_profit_order"] is not request["take_profit_order"]
    result["stop_loss_order"]["stop_price"] = "1"
    result["take_profit_order"]["limit_price"] = "2"
    assert request["stop_loss_order"]["stop_price"] == Decimal("56000.00")
    assert request["take_profit_order"]["limit_price"] == "61000.50"


@pytest.mark.parametrize("builder", ["order", "position"])
@pytest.mark.parametrize("identity", [
    {}, {"product_id": 27, "product_symbol": "BTCUSD"}, {"product_id": None, "product_symbol": "BTCUSD"},
    {"product_id": True}, {"product_id": False}, {"product_id": 0}, {"product_id": -27},
    {"product_id": "27.0"}, {"product_id": "2e1"}, {"product_id": 27.0}, {"product_id": Decimal("27")},
    {"product_id": None}, {"product_id": ""}, {"product_symbol": None}, {"product_symbol": ""},
    {"product_symbol": "CRYPTO:"}, {"product_symbol": []}, {"product_symbol": {}}, {"product_symbol": 27},
])
def test_bracket_identity_rejected(builder: str, identity: dict) -> None:
    fields = {key: value for key, value in _bracket_fields(builder).items() if key != "product_symbol"}
    with pytest.raises(ValueError, match="product"):
        _bracket_call(builder, {**fields, **identity})


@pytest.mark.parametrize("builder", ["order", "position"])
@pytest.mark.parametrize("identity,expected", [
    ({"product_id": "27"}, {"product_id": 27}),
    ({"product_id": 27}, {"product_id": 27}),
    ({"product_symbol": "CRYPTO:BTCUSD"}, {"product_symbol": "BTCUSD"}),
])
def test_bracket_accepts_one_product_identity(builder: str, identity: dict, expected: dict) -> None:
    fields = {key: value for key, value in _bracket_fields(builder).items() if key != "product_symbol"}
    result = _bracket_call(builder, {**fields, **identity})
    assert {key: result[key] for key in expected} == expected
    assert ("product_id" in result) != ("product_symbol" in result)


@pytest.mark.parametrize("order_id", [None, "", True, False, 0, -1, "1.5", "1e2", "not-an-order", 1.5, [], {}])
def test_order_bracket_edit_rejects_malformed_order_id(order_id: object) -> None:
    with pytest.raises(ValueError, match="id"):
        mapping.to_order_bracket_edit_payload(order_id, _bracket_fields("order"))


@pytest.mark.parametrize("field", [
    "stop_loss_order", "take_profit_order", "id", "order_id", "symbol", "size", "reduce_only", "side",
    "limit_price", "client_order_id", "unexpected",
])
def test_order_bracket_edit_rejects_nested_and_unknown_fields(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        mapping.to_order_bracket_edit_payload("34521712", _bracket_fields("order", **{field: {"stop_price": "56000"}}))


@pytest.mark.parametrize("field", [
    "bracket_stop_loss_price", "bracket_stop_loss_limit_price", "bracket_take_profit_price",
    "bracket_take_profit_limit_price", "bracket_trail_amount",
])
@pytest.mark.parametrize("value", [True, "NaN", "Infinity", "0", "-1", "", None])
def test_order_bracket_edit_validates_each_decimal(field: str, value: object) -> None:
    with pytest.raises(ValueError, match=field):
        mapping.to_order_bracket_edit_payload("34521712", _bracket_fields("order", **{field: value}))


@pytest.mark.parametrize("builder", ["order", "position"])
@pytest.mark.parametrize("trigger", ["mark_price", "last_traded_price", "spot_price"])
def test_bracket_trigger_methods_preserved(builder: str, trigger: str) -> None:
    result = _bracket_call(builder, _bracket_fields(builder, bracket_stop_trigger_method=trigger))
    assert result["bracket_stop_trigger_method"] == trigger


@pytest.mark.parametrize("builder", ["order", "position"])
@pytest.mark.parametrize("trigger", ["index_price", None, [], {}])
def test_bracket_invalid_trigger_methods_rejected(builder: str, trigger: object) -> None:
    with pytest.raises(ValueError, match="bracket_stop_trigger_method"):
        _bracket_call(builder, _bracket_fields(builder, bracket_stop_trigger_method=trigger))


@pytest.mark.parametrize("builder", ["order", "position"])
@pytest.mark.parametrize("fields", [None, []])
def test_bracket_request_requires_mapping(builder: str, fields: object) -> None:
    with pytest.raises(ValueError, match="mapping"):
        _bracket_call(builder, fields)


@pytest.mark.parametrize("field", [
    "id", "order_id", "bracket_order_id", "symbol", "size", "side", "reduce_only", "client_order_id",
    "bracket_stop_loss_price", "bracket_take_profit_price", "bracket_trail_amount", "unexpected",
])
def test_position_bracket_rejects_arbitrary_identity_and_flat_fields(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        mapping.to_position_bracket_create_payload(_bracket_fields("position", **{field: "34521712"}))


@pytest.mark.parametrize("leg_name", ["stop_loss_order", "take_profit_order"])
@pytest.mark.parametrize("leg", [
    None, [], {}, {"order_type": "market_order"}, {"order_type": "limit_order", "stop_price": "56000"},
    {"stop_price": "56000"}, {"order_type": "stop_loss_order", "stop_price": "56000"},
    {"order_type": [], "stop_price": "56000"},
    {"order_type": "market_order", "stop_price": "56000", "id": 123},
    {"order_type": "market_order", "stop_price": "56000", "product_id": 27},
    {"order_type": "market_order", "stop_price": "56000", "size": 10},
    {"order_type": "market_order", "stop_price": "56000", "stop_trigger_method": "mark_price"},
])
def test_position_bracket_leg_shape_rejected(leg_name: str, leg: object) -> None:
    with pytest.raises(ValueError):
        mapping.to_position_bracket_create_payload({"product_id": 27, leg_name: leg})


@pytest.mark.parametrize("field", ["stop_price", "limit_price", "trail_amount"])
@pytest.mark.parametrize("value", [False, "NaN", "Infinity", "0", "-1", "", None])
def test_position_bracket_leg_decimal_validation(field: str, value: object) -> None:
    leg = {"order_type": "limit_order", "stop_price": "56000", "limit_price": "55000", "trail_amount": "50"}
    leg[field] = value
    with pytest.raises(ValueError, match=field):
        mapping.to_position_bracket_create_payload({"product_id": 27, "stop_loss_order": leg})


def test_position_bracket_trailing_stop_is_stop_loss_only() -> None:
    leg = {"order_type": "market_order", "trail_amount": "50.00"}
    result = mapping.to_position_bracket_create_payload({"product_id": 27, "stop_loss_order": leg})
    assert result["stop_loss_order"] == leg
    assert "stop_price" not in result["stop_loss_order"]
    with pytest.raises(ValueError, match="trail_amount"):
        mapping.to_position_bracket_create_payload({"product_id": 27, "take_profit_order": leg})


@pytest.mark.parametrize("leg_name", ["stop_loss_order", "take_profit_order"])
def test_position_bracket_accepts_one_market_leg(leg_name: str) -> None:
    leg = {"order_type": "market_order", "stop_price": "56000.00"}
    result = mapping.to_position_bracket_create_payload({"product_id": 27, leg_name: leg})
    assert result[leg_name] == leg
    assert ("stop_loss_order" in result) != ("take_profit_order" in result)
    assert "limit_price" not in result[leg_name]


def test_position_bracket_requires_at_least_one_leg() -> None:
    with pytest.raises(ValueError, match="leg|stop_loss_order|take_profit_order"):
        mapping.to_position_bracket_create_payload({"product_id": 27, "bracket_stop_trigger_method": "mark_price"})


def test_order_bracket_edit_requires_a_change() -> None:
    with pytest.raises(ValueError, match="change|bracket"):
        mapping.to_order_bracket_edit_payload("34521712", {"product_id": 27})


def test_bracket_builders_preserve_exact_decimals_without_inventing_tick_size() -> None:
    price = Decimal("123456789012345678901234567890.51")
    with localcontext() as context:
        context.prec = 6
        order = mapping.to_order_bracket_edit_payload(
            "34521712", {"product_id": 27, "bracket_take_profit_price": price},
        )
        position = mapping.to_position_bracket_create_payload({
            "product_id": 27, "take_profit_order": {"order_type": "market_order", "stop_price": price},
        })
    assert order["bracket_take_profit_price"] == str(price)
    assert position["take_profit_order"]["stop_price"] == str(price)


def test_position_bracket_modify_is_not_invented() -> None:
    assert not hasattr(mapping, "to_position_bracket_modify_payload")
    assert not hasattr(mapping, "to_position_bracket_edit_payload")


def _native_order(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "id": 123, "user_id": 453671, "product_id": 27, "product_symbol": "BTCUSD",
        "size": 10, "unfilled_size": 2, "state": "open",
    }
    row.update(changes)
    return row


def test_order_evidence_requires_quantities() -> None:
    result = mapping.from_native_order(_native_order())
    assert result["quantity"] == 10
    assert result["remaining_quantity"] == 2
    assert result["filled_quantity"] == 8
    assert result["quantity_unit"] == "contracts"
    assert result["status"] == "WORKING"
    assert result["raw_status"] == "open"
    assert result["orderid"] == 123
    assert result["product_id"] == 27
    assert result["symbol"] == "BTCUSD"
    cancelled = mapping.from_native_order(_native_order(state="cancelled"))
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["filled_quantity"] == 8
    assert cancelled["remaining_quantity"] == 2
    row = _native_order(state="closed")
    del row["unfilled_size"]
    missing = mapping.from_native_order(row)
    assert missing["quantity"] == 10
    assert "remaining_quantity" not in missing
    assert "filled_quantity" not in missing
    assert missing["status"] == "UNKNOWN"


@pytest.mark.parametrize("quantities,expected", [
    ({}, {}), ({"size": 10}, {"quantity": 10}),
    ({"unfilled_size": 2}, {"remaining_quantity": 2}),
    ({"size": 10, "unfilled_size": 10}, {"quantity": 10, "remaining_quantity": 10, "filled_quantity": 0}),
    ({"size": 10, "unfilled_size": 0}, {"quantity": 10, "remaining_quantity": 0, "filled_quantity": 10}),
    ({"size": "0010", "unfilled_size": "0002"}, {"quantity": 10, "remaining_quantity": 2, "filled_quantity": 8}),
])
def test_snapshot_quantities_are_present_only(quantities: dict, expected: dict) -> None:
    result = mapping.from_native_order({"state": "pending", **quantities})
    assert {key: value for key, value in result.items() if key in {
        "quantity", "remaining_quantity", "filled_quantity",
    }} == expected
    assert result["native"] == {"state": "pending", **quantities}
    assert result["status"] == "UNKNOWN"


@pytest.mark.parametrize("field", ["size", "unfilled_size"])
@pytest.mark.parametrize("value", [
    True, False, None, "", "-1", -1, "1.5", 1.5, "NaN", "Infinity", [], {}, "1e1", "10.0", 10.0,
    Decimal("10"),
])
def test_native_order_rejects_malformed_contract_counts(field: str, value: object) -> None:
    row = _native_order(**{field: value})
    original = deepcopy(row)
    with pytest.raises(ValueError, match=field):
        mapping.from_native_order(row)
    assert row == original


@pytest.mark.parametrize("quantities", [
    {"size": 0}, {"size": "0"}, {"unfilled_size": 11}, {"size": 1, "unfilled_size": 2},
])
def test_native_order_rejects_zero_size_and_oversized_remainder(quantities: dict) -> None:
    with pytest.raises(ValueError, match="size|unfilled_size"):
        mapping.from_native_order(_native_order(**quantities))


@pytest.mark.parametrize("state,quantities,expected", [
    ("open", {}, "WORKING"), ("pending", {"size": 10, "unfilled_size": 0}, "UNKNOWN"),
    ("cancelled", {}, "CANCELLED"), ("canceled", {}, "CANCELLED"),
    ("closed", {"size": 10, "unfilled_size": 0}, "FILLED"),
    ("closed", {"size": "10", "unfilled_size": "0"}, "FILLED"),
    ("closed", {"size": 10, "unfilled_size": 2}, "UNKNOWN"),
    ("closed", {"size": 10}, "UNKNOWN"), ("closed", {"unfilled_size": 0}, "UNKNOWN"),
    ("closed", {}, "UNKNOWN"),
])
def test_exact_native_status_mapping(state: str, quantities: dict, expected: str) -> None:
    result = mapping.from_native_order({"state": state, **quantities})
    assert result["status"] == expected
    assert result["raw_status"] == state


@pytest.mark.parametrize("state", [
    "", "OPEN", " Closed ", "complete", "FILLED", "cancel_pending", "cancel_requested", "not_cancelled",
    "reject_pending", "REJECTED", "expired", "unknown", "filled_then_corrected", None, [], {}, True,
])
def test_unknown_status_never_becomes_terminal(state: object) -> None:
    result = mapping.from_native_order(_native_order(state=state, unfilled_size=0))
    assert result["status"] == "UNKNOWN"
    assert result["raw_status"] == state
    assert result["native"]["state"] == state


def test_order_readback_detaches_all_native_evidence() -> None:
    row = _native_order(
        id="000123", product_id="00027", product_symbol="CRYPTO:BTCUSD", reduce_only="false",
        client_order_id="intent-0001", created_at="1725865012000000", updated_at="1725865012000001",
        stop_order_type="liquidation_order", stop_price="55000.00", trail_amount="50.00",
        stop_trigger_method="last_traded_price", bracket_order=True,
        bracket_stop_loss_price="56000.00", bracket_stop_loss_limit_price="57000.00",
        bracket_take_profit_price="61000.00", bracket_take_profit_limit_price="62000.00",
        bracket_trail_amount="50.00", bracket_stop_trigger_method="spot_price",
        requested={"validity": "DAY", "quantity": "10"}, effective={"time_in_force": "gtc", "size": 10},
        account_id="fixture-account", venue="india_testnet", parent_order_id=101,
        position_scope={"product_id": 27}, child_orders=[{"id": 124, "state": "pending"}],
    )
    original = deepcopy(row)
    result = mapping.from_native_order(row)
    assert result["native"] == original
    assert result["orderid"] == "000123"
    assert result["product_id"] == "00027"
    assert result["symbol"] == "CRYPTO:BTCUSD"
    assert "reduce_only" not in result
    assert "parent_order_id" not in result
    assert "closed_position" not in result
    result["native"]["requested"]["quantity"] = "1"
    result["native"]["child_orders"][0]["id"] = 999
    result["native"]["position_scope"]["product_id"] = 28
    row["effective"]["size"] = 20
    assert row["requested"] == original["requested"]
    assert row["child_orders"] == original["child_orders"]
    assert row["position_scope"] == original["position_scope"]
    assert result["native"]["effective"] == original["effective"]


def test_order_missing_identity_does_not_invent_parent_or_position() -> None:
    result = mapping.from_native_order({})
    assert result == {
        "orderid": None, "product_id": None, "symbol": None, "quantity_unit": "contracts",
        "raw_status": None, "status": "UNKNOWN", "native": {},
    }


def test_large_contract_arithmetic_is_exact_without_decimal_context() -> None:
    total = 123456789012345678901234567890
    row = _native_order(size=str(total), unfilled_size="2", state="closed")
    with localcontext() as context:
        context.prec = 6
        result = mapping.from_native_order(row)
    assert result["quantity"] == total
    assert result["remaining_quantity"] == 2
    assert result["filled_quantity"] == total - 2
    assert result["status"] == "UNKNOWN"


@pytest.mark.parametrize("value", [None, [], "order", 1])
def test_native_order_requires_mapping(value: object) -> None:
    with pytest.raises(ValueError, match="mapping"):
        mapping.from_native_order(value)


def test_operation_preserves_partial_evidence() -> None:
    payload = {
        "success": True,
        "result": [
            {"id": 123, "product_id": 27, "size": 10, "unfilled_size": 10, "state": "open",
             "child_orders": [{"id": 124}], "requested": {"reduce_only": True}},
            {"client_order_id": "intent-0002", "success": False, "error": {
                "code": "insufficient_margin", "context": {"product_id": 27},
            }},
        ],
        "error": {"code": "partial_failure"}, "meta": {"after": "opaque-next", "before": None},
    }
    original = deepcopy(payload)
    result = mapping.from_operation_response(payload, operation="batch_create")
    assert result == {
        "operation": "batch_create", "raw_response": original,
        "items": original["result"], "skipped_products": [], "complete": False,
    }
    assert result["items"] is not payload["result"]
    assert result["items"][0] is not result["raw_response"]["result"][0]
    result["items"][0]["child_orders"][0]["id"] = 999
    result["items"][1]["error"]["context"]["product_id"] = 28
    result["raw_response"]["meta"]["after"] = "changed"
    assert payload == original
    assert result["raw_response"]["result"] == original["result"]
    assert "filled_quantity" not in result["items"][0]
    assert "status" not in result


@pytest.mark.parametrize("operation", ["batch_create", "batch_edit", "batch_cancel", "cancel_all_orders"])
def test_bulk_items_keep_errors_and_child_identity_opaquely(operation: str) -> None:
    entries = [
        {"id": "000123", "product_id": 27, "parent_order_id": 122, "client_order_id": "fixture-child"},
        {"error": "rejected", "child_id": 125}, None, "unrecognised", ["opaque-child"],
    ]
    payload = {"success": True, "result": entries}
    result = mapping.from_operation_response(payload, operation=operation)
    assert result["items"] == entries
    assert len(result["items"]) == len(entries)
    assert result["complete"] is False
    assert result["raw_response"] == payload
    result["items"][4].append("changed")
    assert entries[4] == ["opaque-child"]


def test_duplicate_bulk_entries_are_preserved_without_execution_deduplication() -> None:
    entry = {"id": 123, "size": 10, "unfilled_size": 2, "state": "cancelled"}
    result = mapping.from_operation_response({"success": True, "result": [entry, entry]}, operation="order_history")
    assert result["items"] == [entry, entry]
    assert result["items"][0] is not result["items"][1]
    result["items"][0]["unfilled_size"] = 1
    assert result["items"][1]["unfilled_size"] == 2
    assert entry["unfilled_size"] == 2


@pytest.mark.parametrize("success", [True, False, "true", None])
@pytest.mark.parametrize("reason", [
    "market_disrupted_cancel_only_mode", "market_disrupted_post_only_mode", "market_disrupted", "unknown_reason",
])
def test_close_all_keeps_skipped_products_and_never_guarantees_flat(success: object, reason: str) -> None:
    payload = {"success": success, "result": {"skipped_products": [
        {"product_id": 27, "product_symbol": "BTCUSD", "reason": reason, "details": {"scope": "position"}},
    ]}}
    original = deepcopy(payload)
    result = mapping.from_operation_response(payload, operation="close_all_positions")
    assert result["skipped_products"] == original["result"]["skipped_products"]
    assert result["items"] == []
    assert result["complete"] is False
    assert result["raw_response"] == original
    assert "flat" not in result
    assert "closed" not in result
    result["skipped_products"][0]["details"]["scope"] = "changed"
    assert payload == original
    assert result["raw_response"] == original


@pytest.mark.parametrize("operation", ["open_orders", "order_history", "fills"])
@pytest.mark.parametrize("rows", [[], [{"id": 123, "order_id": 122, "size": 1}]])
@pytest.mark.parametrize("meta", [
    {"after": "next-page", "before": "previous-page"}, {"after": None, "before": None},
    {"cursor": {"opaque": [1, 2]}, "page_size": 1, "filters": {"product_id": 27}},
])
def test_paginated_read_operations_never_establish_complete_books(operation: str, rows: list, meta: dict) -> None:
    payload = {"success": True, "result": rows, "meta": meta}
    original = deepcopy(payload)
    result = mapping.from_operation_response(payload, operation=operation)
    assert result["items"] == rows
    assert result["raw_response"] == original
    assert result["complete"] is False
    result["raw_response"]["meta"]["additional"] = "changed"
    assert payload == original


@pytest.mark.parametrize("result_shape", [
    None, True, "success", 10, {}, {"orders": [{"id": 123}]}, {"errors": [{"code": "failure"}]},
    {"skipped_products": {"27": "halted"}}, {"skipped_products": "unrecognised"},
])
def test_unknown_operation_result_shapes_stay_raw(result_shape: object) -> None:
    payload = {"success": True, "result": result_shape, "complete": True}
    result = mapping.from_operation_response(payload, operation="unknown_operation")
    assert result["raw_response"] == payload
    assert result["items"] == []
    assert result["skipped_products"] == []
    assert result["complete"] is False


@pytest.mark.parametrize("payload", [
    {}, {"success": True}, {"success": True, "result": []},
    {"success": False, "error": {"code": "unavailable", "context": {"product_id": 27}}},
    {"result": {"skipped_products": []}},
])
def test_missing_rows_and_empty_success_never_establish_completion(payload: dict) -> None:
    result = mapping.from_operation_response(payload, operation="close_all_positions")
    assert result["raw_response"] == payload
    assert result["items"] == []
    assert result["skipped_products"] == []
    assert result["complete"] is False


@pytest.mark.parametrize("value", [None, [], "response", 1])
def test_operation_response_requires_mapping(value: object) -> None:
    with pytest.raises(ValueError, match="mapping"):
        mapping.from_operation_response(value, operation="fills")


@pytest.mark.parametrize("operation", [None, "", " ", [], {}, 1])
def test_operation_requires_an_explicit_nonempty_name(operation: object) -> None:
    with pytest.raises(ValueError, match="operation"):
        mapping.from_operation_response({}, operation=operation)
