"""Independent, offline tests for native Groww smart-order mappings."""

from copy import deepcopy
from decimal import Decimal, localcontext
from types import MappingProxyType

import pytest
from flinttrade_gateway.brokers import groww_smart_mapping


def _gtt_request():
    return {
        "reference_id": "sref-unique-123",
        "smart_order_type": "GTT",
        "segment": "CASH",
        "trading_symbol": "TCS",
        "quantity": 10,
        "trigger_price": "3985.00",
        "trigger_direction": "DOWN",
        "order": {"order_type": "LIMIT", "price": "3990.00", "transaction_type": "BUY"},
        "product_type": "CNC",
        "exchange": "NSE",
        "duration": "DAY",
    }


def _oco_request():
    return {
        "reference_id": "sref-unique-456",
        "smart_order_type": "OCO",
        "segment": "FNO",
        "trading_symbol": "NIFTY25OCT24000CE",
        "quantity": 50,
        "net_position_quantity": 50,
        "transaction_type": "SELL",
        "target": {"trigger_price": "120.50", "order_type": "LIMIT", "price": "121.00"},
        "stop_loss": {"trigger_price": "95.00", "order_type": "SL_M", "price": None},
        "product_type": "NRML",
        "exchange": "NSE",
        "duration": "DAY",
    }


def _create(family, request):
    name = "to_gtt_create_payload" if family == "GTT" else "to_oco_create_payload"
    creator = getattr(groww_smart_mapping, name, None)
    assert callable(creator), f"Missing production interface: {name}"
    return creator(request)


def _request(family):
    return _gtt_request() if family == "GTT" else _oco_request()


def _set(request, path, value):
    container = request
    for name in path[:-1]:
        container = container[name]
    container[path[-1]] = value


def test_create_gtt_nested_order():
    request = _gtt_request()
    payload = _create("GTT", request)
    assert payload == request
    assert payload["order"] == {"order_type": "LIMIT", "price": "3990.00", "transaction_type": "BUY"}
    assert payload["trigger_price"] == "3985.00"
    assert payload["order"]["price"] != payload["trigger_price"]
    assert payload is not request
    assert payload["order"] is not request["order"]
    assert "reduce_only" not in payload


def test_create_oco_position_bound():
    request = _oco_request()
    original = deepcopy(request)
    payload = _create("OCO", request)
    assert payload == original
    assert payload["quantity"] == payload["net_position_quantity"] == 50
    assert payload["transaction_type"] == "SELL"
    assert payload["target"] is not request["target"]
    assert payload["stop_loss"] is not request["stop_loss"]
    assert "reduce_only" not in payload
    request["quantity"] = 51
    with pytest.raises(ValueError):
        _create("OCO", request)
    request["quantity"] = 50
    request["transaction_type"] = "BUY"
    with pytest.raises(ValueError):
        _create("OCO", request)
    assert original == _oco_request()


@pytest.mark.parametrize("family", ["GTT", "OCO"])
@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("quantity",), True),
        (("quantity",), False),
        (("quantity",), 0),
        (("quantity",), -1),
        (("quantity",), 1.5),
        (("quantity",), 10.0),
        (("quantity",), "10"),
        (("quantity",), Decimal("10")),
        (("quantity",), None),
        (("reference_id",), "short"),
        (("reference_id",), "a" * 21),
        (("reference_id",), "a-b-c-d12"),
        (("reference_id",), "abcdefgh_1"),
        (("reference_id",), "abcdefgh 1"),
        (("reference_id",), "abcdefgh\n"),
        (("reference_id",), "äbcdefgh"),
        (("reference_id",), True),
        (("segment",), "COMMODITY"),
        (("segment",), "cash"),
        (("segment",), []),
        (("exchange",), "MCX"),
        (("exchange",), "nse"),
        (("exchange",), {}),
        (("duration",), "GTC"),
        (("duration",), "YEAR"),
        (("duration",), True),
        (("product_type",), "UNKNOWN"),
        (("product_type",), []),
        (("trading_symbol",), ""),
        (("trading_symbol",), " "),
        (("trading_symbol",), " TCS"),
        (("trading_symbol",), "TCS\n"),
        (("trading_symbol",), 1),
        (("smart_order_type",), "OTHER"),
        (("smart_order_type",), None),
    ],
)
def test_create_rejects_invalid_inputs(family, path, value):
    request = _request(family)
    _set(request, path, value)
    original = deepcopy(request)
    with pytest.raises(ValueError):
        _create(family, request)
    assert request == original


@pytest.mark.parametrize("family", ["GTT", "OCO"])
@pytest.mark.parametrize("candidate", [None, [], (), "not a mapping", 1, True])
def test_create_rejects_non_mappings(family, candidate):
    with pytest.raises(ValueError):
        _create(family, candidate)


@pytest.mark.parametrize("family", ["GTT", "OCO"])
@pytest.mark.parametrize(
    "field",
    [
        "reference_id",
        "smart_order_type",
        "segment",
        "trading_symbol",
        "quantity",
        "product_type",
        "exchange",
        "duration",
    ],
)
def test_create_requires_explicit_common_scope(family, field):
    request = _request(family)
    del request[field]
    with pytest.raises(ValueError):
        _create(family, request)


@pytest.mark.parametrize(
    ("family", "path"),
    [
        ("GTT", ("trigger_price",)),
        ("GTT", ("trigger_direction",)),
        ("GTT", ("order",)),
        ("GTT", ("order", "order_type")),
        ("GTT", ("order", "transaction_type")),
        ("GTT", ("order", "price")),
        ("OCO", ("net_position_quantity",)),
        ("OCO", ("transaction_type",)),
        ("OCO", ("target",)),
        ("OCO", ("stop_loss",)),
        ("OCO", ("target", "trigger_price")),
        ("OCO", ("target", "order_type")),
        ("OCO", ("target", "price")),
        ("OCO", ("stop_loss", "trigger_price")),
        ("OCO", ("stop_loss", "order_type")),
    ],
)
def test_create_requires_resource_fields(family, path):
    request = _request(family)
    container = request
    for name in path[:-1]:
        container = container[name]
    del container[path[-1]]
    with pytest.raises(ValueError):
        _create(family, request)


@pytest.mark.parametrize(
    ("family", "path"),
    [
        ("GTT", ("trigger_price",)),
        ("GTT", ("order", "price")),
        ("OCO", ("target", "trigger_price")),
        ("OCO", ("target", "price")),
        ("OCO", ("stop_loss", "trigger_price")),
        ("OCO", ("stop_loss", "price")),
    ],
)
@pytest.mark.parametrize(
    "value", ["NaN", "sNaN", "Infinity", "-Infinity", "0", "-1.00", "", "bad", " 1.00", "1_000", True, None, 1, 1.25]
)
def test_create_rejects_invalid_prices(family, path, value):
    request = _request(family)
    if path == ("stop_loss", "price"):
        request["stop_loss"]["order_type"] = "SL"
    _set(request, path, value)
    with pytest.raises(ValueError):
        _create(family, request)


@pytest.mark.parametrize("family", ["GTT", "OCO"])
@pytest.mark.parametrize(
    "field", ["account_id", "broker_id", "reduce_only", "child_legs", "price", "order_id", "status", "expires_at"]
)
def test_create_rejects_unsupported_top_level_fields(family, field):
    request = _request(family)
    request[field] = None
    with pytest.raises(ValueError):
        _create(family, request)


@pytest.mark.parametrize(("family", "path"), [("GTT", ("order",)), ("OCO", ("target",)), ("OCO", ("stop_loss",))])
@pytest.mark.parametrize("value", [None, [], "LIMIT", True])
def test_create_rejects_non_mapping_children(family, path, value):
    request = _request(family)
    _set(request, path, value)
    with pytest.raises(ValueError):
        _create(family, request)


@pytest.mark.parametrize(("family", "child"), [("GTT", "order"), ("OCO", "target"), ("OCO", "stop_loss")])
@pytest.mark.parametrize("field", ["quantity", "exchange", "reduce_only", "unknown", "trigger_direction"])
def test_create_rejects_unsupported_nested_fields(family, child, field):
    request = _request(family)
    request[child][field] = "unexpected"
    with pytest.raises(ValueError):
        _create(family, request)


@pytest.mark.parametrize("order_type", ["LIMIT", "MARKET", "SL", "SL_M"])
@pytest.mark.parametrize("direction", ["UP", "DOWN"])
@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_create_gtt_order_types_keep_native_nesting(order_type, direction, side):
    request = _gtt_request()
    request["trigger_direction"] = direction
    request["order"] = {"order_type": order_type, "transaction_type": side}
    if order_type in {"LIMIT", "SL"}:
        request["order"]["price"] = "0003990.00100"
    payload = _create("GTT", request)
    assert payload == request
    assert payload["trigger_price"] == "3985.00"
    assert payload["order"]["order_type"] == order_type
    assert "trigger_price" not in payload["order"]
    assert "transaction_type" not in payload


@pytest.mark.parametrize(
    ("family", "path", "value"),
    [
        ("GTT", ("trigger_direction",), "ABOVE"),
        ("GTT", ("trigger_direction",), []),
        ("GTT", ("order", "order_type"), "STOP_MARKET"),
        ("GTT", ("order", "order_type"), []),
        ("GTT", ("order", "transaction_type"), "buy"),
        ("GTT", ("order", "transaction_type"), {}),
        ("OCO", ("target", "order_type"), "STOP_MARKET"),
        ("OCO", ("target", "order_type"), []),
        ("OCO", ("stop_loss", "order_type"), "STOP"),
        ("OCO", ("stop_loss", "order_type"), {}),
        ("OCO", ("transaction_type",), "sell"),
        ("OCO", ("transaction_type",), []),
    ],
)
def test_create_rejects_non_native_enums(family, path, value):
    request = _request(family)
    _set(request, path, value)
    with pytest.raises(ValueError):
        _create(family, request)


@pytest.mark.parametrize("family", ["GTT", "OCO"])
def test_create_rejects_resource_family_mismatch(family):
    request = _request(family)
    request["smart_order_type"] = "OCO" if family == "GTT" else "GTT"
    with pytest.raises(ValueError):
        _create(family, request)


@pytest.mark.parametrize(
    ("net", "quantity", "side"),
    [(50, 1, "SELL"), (50, 50, "SELL"), (-50, 1, "BUY"), (-50, 50, "BUY"), (51, 51, "SELL")],
)
def test_create_oco_preserves_signed_exposure_and_quantity_units(net, quantity, side):
    request = _oco_request()
    request.update(net_position_quantity=net, quantity=quantity, transaction_type=side)
    payload = _create("OCO", request)
    assert payload == request
    assert payload["quantity"] == quantity
    assert payload["net_position_quantity"] == net
    assert "reduce_only" not in payload


@pytest.mark.parametrize("net", [0, True, False, "50", 50.0, 50.5, Decimal("50"), None, [], {}])
def test_create_oco_rejects_invalid_net_exposure(net):
    request = _oco_request()
    request["net_position_quantity"] = net
    with pytest.raises(ValueError):
        _create("OCO", request)


@pytest.mark.parametrize(
    ("net", "quantity", "side"), [(50, 51, "SELL"), (-50, 51, "BUY"), (50, 50, "BUY"), (-50, 50, "SELL")]
)
def test_create_oco_rejects_exposure_increase(net, quantity, side):
    request = _oco_request()
    request.update(net_position_quantity=net, quantity=quantity, transaction_type=side)
    with pytest.raises(ValueError):
        _create("OCO", request)


@pytest.mark.parametrize("segment", ["CASH", "FNO"])
@pytest.mark.parametrize("exchange", ["NSE", "BSE"])
@pytest.mark.parametrize("target_type", ["LIMIT", "MARKET", "SL", "SL_M"])
@pytest.mark.parametrize("stop_type", ["LIMIT", "MARKET", "SL", "SL_M"])
def test_create_oco_preserves_documented_scope_and_annexure_types(segment, exchange, target_type, stop_type):
    request = _oco_request()
    request.update(segment=segment, product_type="MIS" if segment == "CASH" else "NRML", exchange=exchange)
    request["target"]["order_type"] = target_type
    request["stop_loss"]["order_type"] = stop_type
    request["target"]["price"] = "121.00" if target_type in {"LIMIT", "SL"} else None
    request["stop_loss"]["price"] = "94.50" if stop_type in {"LIMIT", "SL"} else None
    payload = _create("OCO", request)
    assert payload == request
    assert payload["exchange"] == exchange
    assert payload["segment"] == segment
    assert payload["product_type"] == request["product_type"]


@pytest.mark.parametrize(
    ("family", "segment", "product"),
    [
        ("OCO", "CASH", "CNC"),
        ("OCO", "CASH", "NRML"),
        ("OCO", "FNO", "CNC"),
        ("OCO", "FNO", "MIS"),
    ],
)
def test_create_rejects_oco_product_combinations_outside_documented_scope(family, segment, product):
    request = _request(family)
    request.update(segment=segment, product_type=product)
    with pytest.raises(ValueError, match="product_type"):
        _create(family, request)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("segment", "product"), [("CASH", "MIS"), ("CASH", "NRML"), ("FNO", "CNC"), ("FNO", "MIS")]
)
def test_create_gtt_refuses_unverified_product_pairs(segment, product):
    request = _gtt_request()
    request.update(segment=segment, product_type=product)
    original = deepcopy(request)
    with pytest.raises(ValueError, match="GTT product_type.*unverified"):
        _create("GTT", request)
    assert request == original


@pytest.mark.unit
@pytest.mark.parametrize(("segment", "product"), [("CASH", "CNC"), ("FNO", "NRML")])
def test_create_gtt_preserves_documented_product_pairs_without_lot_inference(segment, product):
    request = _gtt_request()
    request.update(segment=segment, product_type=product, quantity=51)
    if segment == "FNO":
        request["trading_symbol"] = "NIFTY25OCT24000CE"
    payload = _create("GTT", request)
    assert payload == request
    assert payload["quantity"] == 51


@pytest.mark.parametrize("exchange", ["NSE", "BSE"])
@pytest.mark.parametrize("reference_id", ["Abcdef12", "abcde-12", "abc-def-12", "A" * 20])
def test_create_gtt_preserves_exchange_and_reference(exchange, reference_id):
    request = _gtt_request()
    request.update(exchange=exchange, reference_id=reference_id)
    assert _create("GTT", request) == request


@pytest.mark.parametrize(
    ("family", "child", "order_type"),
    [("GTT", "order", "MARKET"), ("GTT", "order", "SL_M"), ("OCO", "target", "MARKET"), ("OCO", "stop_loss", "SL_M")],
)
@pytest.mark.parametrize("provided", [False, True])
def test_create_market_leg_preserves_omitted_or_null_price(family, child, order_type, provided):
    request = _request(family)
    request[child]["order_type"] = order_type
    if provided:
        request[child]["price"] = None
    else:
        request[child].pop("price", None)
    assert _create(family, request) == request


@pytest.mark.parametrize(
    ("family", "child", "order_type"),
    [("GTT", "order", "MARKET"), ("GTT", "order", "SL_M"), ("OCO", "target", "MARKET"), ("OCO", "stop_loss", "SL_M")],
)
def test_create_preserves_optional_native_market_price(family, child, order_type):
    request = _request(family)
    request[child].update(order_type=order_type, price="1.00")
    assert _create(family, request) == request


def test_create_payloads_are_independent_snapshots():
    gtt = _gtt_request()
    oco = _oco_request()
    gtt_payload = _create("GTT", gtt)
    oco_payload = _create("OCO", oco)
    gtt["order"]["price"] = "4000.00"
    oco["target"]["trigger_price"] = "200.00"
    gtt_payload["quantity"] = 99
    oco_payload["stop_loss"]["price"] = "0"
    assert gtt_payload["order"]["price"] == "3990.00"
    assert oco_payload["target"]["trigger_price"] == "120.50"
    assert gtt["quantity"] == 10
    assert oco["stop_loss"]["price"] is None


@pytest.mark.parametrize(("family", "child"), [("GTT", "order"), ("OCO", "target"), ("OCO", "stop_loss")])
@pytest.mark.parametrize("order_type", ["LIMIT", "SL"])
@pytest.mark.parametrize("omit", [False, True])
def test_create_requires_limit_price_for_every_native_limit_type(family, child, order_type, omit):
    request = _request(family)
    request[child].update(order_type=order_type, price=None)
    if omit:
        del request[child]["price"]
    original = deepcopy(request)
    with pytest.raises(ValueError):
        _create(family, request)
    assert request == original


@pytest.mark.parametrize("family", ["GTT", "OCO"])
@pytest.mark.parametrize("value", ["0001.23000", ".125", "1.", "+1.00", "1e-1000", "1E+1000", "9" * 200 + ".001"])
def test_create_preserves_exact_decimal_text_under_small_context(family, value):
    request = _request(family)
    if family == "GTT":
        request["trigger_price"] = value
        request["order"]["price"] = value
    else:
        request["target"].update(trigger_price=value, price=value)
        request["stop_loss"].update(trigger_price=value, order_type="SL", price=value)
    with localcontext() as context:
        context.prec = 2
        context.Emin = -9
        context.Emax = 9
        assert _create(family, request) == request


@pytest.mark.parametrize("family", ["GTT", "OCO"])
@pytest.mark.parametrize("value", ["-0", "0e-1000", "1e999999999999999999999999", "1\n", "１２.０", "1,000.00"])
def test_create_rejects_malformed_decimal_text(family, value):
    request = _request(family)
    if family == "GTT":
        request["trigger_price"] = value
    else:
        request["target"]["trigger_price"] = value
    with pytest.raises(ValueError):
        _create(family, request)


@pytest.mark.parametrize("family", ["GTT", "OCO"])
def test_create_accepts_read_only_mapping_snapshots(family):
    request = _request(family)
    for child in ["order"] if family == "GTT" else ["target", "stop_loss"]:
        request[child] = MappingProxyType(request[child])
    assert _create(family, MappingProxyType(request)) == request


@pytest.mark.parametrize("family", ["GTT", "OCO"])
@pytest.mark.parametrize("key", [1, None, ("unexpected",)])
def test_create_rejects_non_string_field_keys(family, key):
    request = _request(family)
    request[key] = "unexpected"
    with pytest.raises(ValueError):
        _create(family, request)


def _current(family):
    current = _request(family)
    current["smart_order_id"] = "gtt_fixture_123" if family == "GTT" else "oco_fixture_456"
    # Creation idempotency is not part of the documented modify contract.
    del current["reference_id"]
    return current


def _modify(current, changes):
    modifier = getattr(groww_smart_mapping, "to_smart_modify_payload", None)
    assert callable(modifier), "Missing production interface: to_smart_modify_payload"
    return modifier(current, changes)


def _path(operation, smart_order_id="gtt_fixture_123", segment="CASH", smart_order_type="GTT"):
    addresser = getattr(groww_smart_mapping, "smart_resource_path", None)
    assert callable(addresser), "Missing production interface: smart_resource_path"
    return addresser(operation, smart_order_id=smart_order_id, segment=segment, smart_order_type=smart_order_type)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("segment", "product"), [("CASH", "MIS"), ("CASH", "NRML"), ("FNO", "CNC"), ("FNO", "MIS")]
)
def test_modify_gtt_refuses_supplied_unverified_product_pairs(segment, product):
    current = _current("GTT")
    current.update(segment=segment, product_type=product)
    original = deepcopy(current)
    with pytest.raises(ValueError, match="GTT product_type.*unverified"):
        _modify(current, {"quantity": 12})
    assert current == original


@pytest.mark.unit
@pytest.mark.parametrize(("segment", "product"), [("CASH", "CNC"), ("FNO", "NRML")])
def test_modify_gtt_retains_documented_pair_context_without_emitting_product(segment, product):
    current = _current("GTT")
    current.update(segment=segment, product_type=product)
    assert _modify(current, {"quantity": 12}) == {
        "smart_order_type": "GTT",
        "segment": segment,
        "quantity": 12,
        "order": {"order_type": "LIMIT", "price": "3990.00", "transaction_type": "BUY"},
    }


def test_modify_resource_allowlists():
    gtt = _current("GTT")
    changes = {"quantity": 12, "trigger_price": "3980.00", "trigger_direction": "UP", "order": {"order_type": "MARKET"}}
    originals = deepcopy((gtt, changes))
    assert _modify(gtt, changes) == {
        "smart_order_type": "GTT",
        "segment": "CASH",
        "quantity": 12,
        "trigger_price": "3980.00",
        "trigger_direction": "UP",
        "order": {"order_type": "MARKET", "price": None, "transaction_type": "BUY"},
    }
    assert (gtt, changes) == originals
    oco = _current("OCO")
    edits = {
        "quantity": 40,
        "duration": "DAY",
        "product_type": "NRML",
        "target": {"trigger_price": "122.00"},
        "stop_loss": {"trigger_price": "97.50"},
    }
    assert _modify(oco, edits) == {"smart_order_type": "OCO", "segment": "FNO", **edits}
    assert "smart_order_id" not in _modify(oco, edits)
    assert "net_position_quantity" not in _modify(oco, edits)


@pytest.mark.parametrize("side", ["BUY", "SELL"])
@pytest.mark.parametrize("order_type", ["LIMIT", "MARKET", "SL", "SL_M"])
def test_modify_gtt_keeps_effective_nested_order_and_current_side(side, order_type):
    current = _current("GTT")
    current["order"]["transaction_type"] = side
    edits = {"order": {"order_type": order_type}}
    if order_type in {"LIMIT", "SL"}:
        edits["order"]["price"] = "0003991.00100"
    expected = {
        "order_type": order_type,
        "transaction_type": side,
        "price": "0003991.00100" if order_type in {"LIMIT", "SL"} else None,
    }
    assert _modify(current, edits) == {"smart_order_type": "GTT", "segment": "CASH", "order": expected}


@pytest.mark.parametrize("order_type", ["MARKET", "SL_M"])
@pytest.mark.parametrize("current_price", [None, "1.00"])
def test_modify_gtt_scalar_edit_uses_modify_null_rule(order_type, current_price):
    current = _current("GTT")
    current["order"].update(order_type=order_type, price=current_price)
    payload = _modify(current, {"quantity": 11})
    assert payload["order"] == {"order_type": order_type, "price": None, "transaction_type": "BUY"}
    assert current["order"]["price"] == current_price


@pytest.mark.parametrize("order_type", ["MARKET", "SL_M"])
@pytest.mark.parametrize("price", ["1.00", "0", True, 1, "NaN"])
def test_modify_gtt_rejects_supplied_non_null_market_price(order_type, price):
    with pytest.raises(ValueError):
        _modify(_current("GTT"), {"order": {"order_type": order_type, "price": price}})


@pytest.mark.parametrize("order_type", ["MARKET", "SL_M"])
def test_modify_gtt_accepts_explicit_market_null(order_type):
    assert _modify(_current("GTT"), {"order": {"order_type": order_type, "price": None}})["order"]["price"] is None


@pytest.mark.parametrize("order_type", ["LIMIT", "SL"])
@pytest.mark.parametrize("price", [None, "0", "NaN", True, "1_000", 1])
def test_modify_gtt_requires_effective_limit_price(order_type, price):
    current = _current("GTT")
    current["order"].update(order_type="MARKET", price=None)
    with pytest.raises(ValueError):
        _modify(current, {"order": {"order_type": order_type, "price": price}})


@pytest.mark.parametrize("order_type", ["LIMIT", "SL"])
def test_modify_gtt_requires_price_on_market_to_limit_transition(order_type):
    current = _current("GTT")
    current["order"].update(order_type="MARKET", price=None)
    with pytest.raises(ValueError):
        _modify(current, {"order": {"order_type": order_type}})


@pytest.mark.parametrize("family", ["GTT", "OCO"])
@pytest.mark.parametrize(
    "field",
    [
        "smart_order_id",
        "smart_order_type",
        "segment",
        "reference_id",
        "exchange",
        "trading_symbol",
        "transaction_type",
        "net_position_quantity",
        "child_legs",
        "reduce_only",
        "account_id",
        "price",
        "unknown",
        1,
        None,
    ],
)
def test_modify_rejects_unknown_or_immutable_top_level_edits(family, field):
    with pytest.raises(ValueError):
        _modify(_current(family), {field: "changed"})


@pytest.mark.parametrize("field", ["product_type", "duration", "target", "stop_loss"])
def test_modify_gtt_rejects_oco_only_edits(field):
    with pytest.raises(ValueError):
        _modify(_current("GTT"), {field: "changed"})


@pytest.mark.parametrize("field", ["trigger_price", "trigger_direction", "order"])
def test_modify_oco_rejects_gtt_only_edits(field):
    with pytest.raises(ValueError):
        _modify(_current("OCO"), {field: "changed"})


@pytest.mark.parametrize("field", ["transaction_type", "quantity", "trigger_price", "reduce_only", "unknown", 1])
def test_modify_gtt_rejects_nested_side_or_unknown_edits(field):
    current = _current("GTT")
    with pytest.raises(ValueError):
        _modify(current, {"order": {field: current["order"].get(field)}})


@pytest.mark.parametrize("child", ["target", "stop_loss"])
@pytest.mark.parametrize("field", ["order_type", "price", "transaction_type", "quantity", "reduce_only", "unknown", 1])
def test_modify_oco_rejects_nested_order_or_price_edits(child, field):
    with pytest.raises(ValueError):
        _modify(_current("OCO"), {child: {field: "changed"}})


@pytest.mark.parametrize("family", ["GTT", "OCO"])
@pytest.mark.parametrize("candidate", [None, [], (), "not a mapping", 1, True])
def test_modify_rejects_non_mapping_inputs(family, candidate):
    with pytest.raises(ValueError):
        _modify(candidate, {"quantity": 1})
    with pytest.raises(ValueError):
        _modify(_current(family), candidate)


@pytest.mark.parametrize(("family", "child"), [("GTT", "order"), ("OCO", "target"), ("OCO", "stop_loss")])
@pytest.mark.parametrize("candidate", [None, [], "LIMIT", True, {}])
def test_modify_rejects_malformed_or_empty_nested_edits(family, child, candidate):
    with pytest.raises(ValueError):
        _modify(_current(family), {child: candidate})


@pytest.mark.parametrize("family", ["GTT", "OCO"])
def test_modify_rejects_empty_edits(family):
    with pytest.raises(ValueError):
        _modify(_current(family), {})


@pytest.mark.parametrize("family", ["GTT", "OCO"])
@pytest.mark.parametrize("value", [0, -1, True, False, 1.5, 1.0, "1", Decimal("1"), None])
def test_modify_rejects_invalid_quantity_edits(family, value):
    with pytest.raises(ValueError):
        _modify(_current(family), {"quantity": value})


@pytest.mark.parametrize(
    ("family", "edits"),
    [
        ("GTT", {"trigger_direction": "ABOVE"}),
        ("GTT", {"trigger_direction": []}),
        ("GTT", {"order": {"order_type": "STOP"}}),
        ("GTT", {"order": {"order_type": []}}),
        ("OCO", {"duration": "GTC"}),
        ("OCO", {"duration": []}),
        ("OCO", {"product_type": "MIS"}),
        ("OCO", {"product_type": "CNC"}),
        ("OCO", {"product_type": []}),
    ],
)
def test_modify_rejects_invalid_enums_or_oco_product_scope(family, edits):
    with pytest.raises(ValueError):
        _modify(_current(family), edits)


@pytest.mark.parametrize(
    ("family", "edits"),
    [
        ("GTT", {"trigger_price": "bad"}),
        ("GTT", {"order": {"price": "bad"}}),
        ("OCO", {"target": {"trigger_price": "bad"}}),
        ("OCO", {"stop_loss": {"trigger_price": "bad"}}),
    ],
)
@pytest.mark.parametrize(
    "value", ["NaN", "sNaN", "Infinity", "-Infinity", "0", "-1", "", " 1", "1_000", "１２", True, None, 1]
)
def test_modify_rejects_invalid_decimal_edits(family, edits, value):
    edits = deepcopy(edits)
    container = edits
    if "order" in edits:
        container = edits["order"]
    elif "target" in edits:
        container = edits["target"]
    elif "stop_loss" in edits:
        container = edits["stop_loss"]
    container[next(iter(container))] = value
    with pytest.raises(ValueError):
        _modify(_current(family), edits)


@pytest.mark.parametrize("family", ["GTT", "OCO"])
@pytest.mark.parametrize("field", ["smart_order_id", "smart_order_type", "segment"])
def test_modify_requires_explicit_resource_identity(family, field):
    current = _current(family)
    del current[field]
    with pytest.raises(ValueError):
        _modify(current, {"quantity": 1})


@pytest.mark.parametrize(
    ("family", "path", "value"),
    [
        ("GTT", ("quantity",), True),
        ("GTT", ("trigger_price",), "NaN"),
        ("GTT", ("trigger_direction",), "ABOVE"),
        ("GTT", ("order", "transaction_type"), "buy"),
        ("GTT", ("order", "order_type"), "STOP"),
        ("GTT", ("order", "price"), None),
        ("OCO", ("quantity",), False),
        ("OCO", ("duration",), "GTC"),
        ("OCO", ("product_type",), "MIS"),
        ("OCO", ("target", "order_type"), "STOP"),
        ("OCO", ("target", "price"), None),
        ("OCO", ("stop_loss", "trigger_price"), "NaN"),
    ],
)
def test_modify_validates_effective_current_resource(family, path, value):
    current = _current(family)
    _set(current, path, value)
    with pytest.raises(ValueError):
        _modify(
            current,
            {"quantity": 1}
            if path != ("quantity",)
            else {"duration": "DAY"}
            if family == "OCO"
            else {"trigger_direction": "UP"},
        )


@pytest.mark.parametrize("family", ["GTT", "OCO"])
def test_modify_does_not_require_or_emit_create_reference_or_response_metadata(family):
    current = _current(family)
    current.update(
        status="ACTIVE", is_modification_allowed=False, created_at="fixture-timestamp", child_legs={"unknown": []}
    )
    payload = _modify(current, {"quantity": 1})
    expected = {"smart_order_type", "segment", "quantity"}
    if family == "GTT":
        expected.add("order")
    assert set(payload) == expected
    assert "is_modification_allowed" not in payload
    assert "child_legs" not in payload


@pytest.mark.unit
@pytest.mark.parametrize(
    ("segment", "product", "documented_pair"),
    [
        ("CASH", "CNC", True), ("CASH", "MIS", False), ("CASH", "NRML", False),
        ("FNO", "CNC", False), ("FNO", "MIS", False), ("FNO", "NRML", True),
    ],
)
def test_modify_gtt_applies_documented_pair_policy_without_lot_inference(segment, product, documented_pair):
    current = _current("GTT")
    current.update(segment=segment, product_type=product)
    if documented_pair:
        assert _modify(current, {"quantity": 51})["segment"] == segment
    else:
        with pytest.raises(ValueError, match="GTT product_type.*unverified"):
            _modify(current, {"quantity": 51})


@pytest.mark.parametrize("segment", ["CASH", "FNO"])
def test_modify_oco_without_creation_only_exposure_fields(segment):
    current = _current("OCO")
    current.update(segment=segment, product_type="MIS" if segment == "CASH" else "NRML")
    del current["net_position_quantity"]
    del current["transaction_type"]
    assert _modify(current, {"quantity": 51, "product_type": current["product_type"]}) == {
        "smart_order_type": "OCO",
        "segment": segment,
        "quantity": 51,
        "product_type": current["product_type"],
    }


@pytest.mark.parametrize(
    ("net", "quantity", "side"), [(50, 51, "SELL"), (-50, 51, "BUY"), (50, 50, "BUY"), (-50, 50, "SELL")]
)
def test_modify_oco_checks_supplied_exposure_snapshot_when_present(net, quantity, side):
    current = _current("OCO")
    current.update(net_position_quantity=net, transaction_type=side)
    with pytest.raises(ValueError):
        _modify(current, {"quantity": quantity})


@pytest.mark.parametrize("family", ["GTT", "OCO"])
def test_modify_read_only_inputs_and_independent_outputs(family):
    current = _current(family)
    child = "order" if family == "GTT" else "target"
    edits = {child: {"price": "4000.00"} if family == "GTT" else {"trigger_price": "123.00"}}
    current[child] = MappingProxyType(current[child])
    edits[child] = MappingProxyType(edits[child])
    payload = _modify(MappingProxyType(current), MappingProxyType(edits))
    assert payload[child] is not edits[child]
    assert payload[child] is not current[child]
    payload[child]["unknown"] = 1
    assert "unknown" not in current[child]
    assert "unknown" not in edits[child]


@pytest.mark.parametrize("value", ["0001.23000", ".125", "1.", "+1.00", "1e-1000", "1E+1000"])
def test_modify_preserves_exact_decimal_text(value):
    with localcontext() as context:
        context.prec = 2
        context.Emin = -9
        context.Emax = 9
        payload = _modify(_current("GTT"), {"trigger_price": value, "order": {"price": value}})
        assert payload["trigger_price"] == payload["order"]["price"] == value
        assert _modify(_current("OCO"), {"target": {"trigger_price": value}})["target"]["trigger_price"] == value


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ("modify", "/v1/order-advance/modify/gtt_fixture_123"),
        ("cancel", "/v1/order-advance/cancel/CASH/GTT/gtt_fixture_123"),
        ("get", "/v1/order-advance/status/CASH/GTT/internal/gtt_fixture_123"),
    ],
)
def test_resource_paths(operation, expected):
    assert _path(operation) == expected


@pytest.mark.parametrize("operation", ["modify", "cancel", "get"])
@pytest.mark.parametrize("segment", ["CASH", "FNO"])
@pytest.mark.parametrize("family", ["GTT", "OCO"])
def test_resource_paths_keep_explicit_scope(operation, segment, family):
    identifier = "fixture-id_123"
    expected = (
        f"/v1/order-advance/modify/{identifier}"
        if operation == "modify"
        else f"/v1/order-advance/cancel/{segment}/{family}/{identifier}"
        if operation == "cancel"
        else f"/v1/order-advance/status/{segment}/{family}/internal/{identifier}"
    )
    assert _path(operation, identifier, segment, family) == expected


@pytest.mark.parametrize("operation", ["modify", "cancel", "get"])
@pytest.mark.parametrize(
    "identifier",
    [
        "",
        " ",
        " id",
        "id ",
        "id/path",
        "..",
        "id..path",
        "id?x",
        "id#x",
        "id%2fpath",
        "id\\path",
        "id\n",
        "ümlaut",
        "１２",
        True,
        1,
        None,
        [],
    ],
)
def test_resource_paths_reject_unsafe_or_non_string_ids(operation, identifier):
    with pytest.raises(ValueError):
        _path(operation, identifier)
    current = _current("GTT")
    current["smart_order_id"] = identifier
    with pytest.raises(ValueError):
        _modify(current, {"quantity": 1})


@pytest.mark.parametrize("operation", ["modify", "cancel", "get"])
@pytest.mark.parametrize(
    ("segment", "family"),
    [
        ("cash", "GTT"),
        ("CASH/path", "GTT"),
        (None, "GTT"),
        ([], "GTT"),
        ("CASH", "gtt"),
        ("CASH", "GTT/path"),
        ("CASH", None),
        ("CASH", []),
    ],
)
def test_resource_paths_reject_unknown_or_unsafe_scope(operation, segment, family):
    with pytest.raises(ValueError):
        _path(operation, segment=segment, smart_order_type=family)


@pytest.mark.parametrize("operation", ["PUT", "status", "create", "get_reference", "MODIFY", "", None, [], True])
def test_resource_paths_reject_unsupported_operations(operation):
    with pytest.raises(ValueError):
        _path(operation)


@pytest.mark.parametrize("field", ["net_position_quantity", "transaction_type"])
def test_modify_oco_rejects_incomplete_supplied_snapshot_constraints(field):
    current = _current("OCO")
    del current[field]
    with pytest.raises(ValueError):
        _modify(current, {"quantity": 1})


@pytest.mark.parametrize("net", [0, True, False, "50", 50.0, 50.5, Decimal("50"), None, [], {}])
def test_modify_oco_rejects_malformed_supplied_snapshot_constraints(net):
    current = _current("OCO")
    current["net_position_quantity"] = net
    with pytest.raises(ValueError):
        _modify(current, {"quantity": 1})


@pytest.mark.parametrize(
    ("net", "quantity", "side"), [(50, 1, "SELL"), (50, 50, "SELL"), (-50, 1, "BUY"), (-50, 50, "BUY")]
)
def test_modify_oco_accepts_supplied_valid_snapshot_constraints(net, quantity, side):
    current = _current("OCO")
    current.update(net_position_quantity=net, transaction_type=side)
    assert _modify(current, {"quantity": quantity}) == {
        "smart_order_type": "OCO",
        "segment": "FNO",
        "quantity": quantity,
    }


@pytest.mark.parametrize("field", ["reference_id", "exchange", "trading_symbol"])
def test_modify_does_not_require_create_only_fields(field):
    for family in ("GTT", "OCO"):
        current = _current(family)
        current.pop(field, None)
        assert _modify(current, {"quantity": 1})["quantity"] == 1


@pytest.mark.parametrize("child", ["target", "stop_loss"])
def test_modify_oco_does_not_apply_gtt_market_null_rule_to_unchanged_legs(child):
    current = _current("OCO")
    current[child].update(order_type="MARKET", price="1.00")
    assert _modify(current, {child: {"trigger_price": "100.00"}}) == {
        "smart_order_type": "OCO",
        "segment": "FNO",
        child: {"trigger_price": "100.00"},
    }
    assert current[child]["price"] == "1.00"


def test_modify_oco_does_not_require_untouched_create_leg_types_or_prices():
    current = {"smart_order_id": "oco_fixture_456", "smart_order_type": "OCO", "segment": "FNO"}
    assert _modify(current, {"quantity": 51, "target": {"trigger_price": "100.00"}}) == {
        "smart_order_type": "OCO",
        "segment": "FNO",
        "quantity": 51,
        "target": {"trigger_price": "100.00"},
    }


def test_modify_gtt_requires_current_side_even_when_edit_has_no_order_fields():
    current = _current("GTT")
    del current["order"]["transaction_type"]
    with pytest.raises(ValueError):
        _modify(current, {"quantity": 1})


@pytest.mark.parametrize("field", ["smart_order_type", "segment"])
@pytest.mark.parametrize("value", [None, [], "unknown", "cash/GTT"])
def test_modify_rejects_malformed_current_resource_scope(field, value):
    current = _current("GTT")
    current[field] = value
    with pytest.raises(ValueError):
        _modify(current, {"quantity": 1})


def test_modify_gtt_scalar_outer_edit_replays_exact_current_limit_order():
    current = _current("GTT")
    current["order"]["price"] = "0003990.00100"
    assert _modify(current, {"trigger_price": "3995.00"}) == {
        "smart_order_type": "GTT",
        "segment": "CASH",
        "trigger_price": "3995.00",
        "order": current["order"],
    }


@pytest.mark.parametrize(
    "path", [("order",), ("order", "order_type"), ("order", "price"), ("order", "transaction_type")]
)
def test_modify_gtt_requires_current_order_fields_for_full_replay(path):
    current = _current("GTT")
    container = current
    for field in path[:-1]:
        container = container[field]
    del container[path[-1]]
    with pytest.raises(ValueError):
        _modify(current, {"quantity": 1})


@pytest.mark.parametrize("candidate", [None, [], "LIMIT", True])
def test_modify_gtt_rejects_malformed_current_order(candidate):
    current = _current("GTT")
    current["order"] = candidate
    with pytest.raises(ValueError):
        _modify(current, {"quantity": 1})


@pytest.mark.parametrize("side", ["buy", "HOLD", True, None, [], {}])
def test_modify_oco_rejects_malformed_supplied_snapshot_side(side):
    current = _current("OCO")
    current["transaction_type"] = side
    with pytest.raises(ValueError):
        _modify(current, {"quantity": 1})


def test_modify_oco_requires_effective_quantity_for_supplied_snapshot_constraints():
    current = _current("OCO")
    del current["quantity"]
    with pytest.raises(ValueError):
        _modify(current, {"duration": "DAY"})


@pytest.mark.parametrize("order_type", ["MARKET", "SL_M"])
def test_modify_gtt_price_only_edit_uses_effective_current_type(order_type):
    current = _current("GTT")
    current["order"].update(order_type=order_type, price=None)
    with pytest.raises(ValueError):
        _modify(current, {"order": {"price": "1.00"}})
    assert _modify(current, {"order": {"price": None}})["order"] == {
        "order_type": order_type,
        "price": None,
        "transaction_type": "BUY",
    }


def test_modify_does_not_forward_nested_current_metadata():
    current = _current("GTT")
    current["order"].update(order_id="fixture-child", broker_permission=False)
    assert _modify(current, {"quantity": 1})["order"] == {
        "order_type": "LIMIT",
        "price": "3990.00",
        "transaction_type": "BUY",
    }


def _read_smart(row):
    reader = getattr(groww_smart_mapping, "from_smart_order", None)
    assert callable(reader), "Missing production interface: from_smart_order"
    return reader(row)


def _read_page(payload):
    reader = getattr(groww_smart_mapping, "from_smart_page", None)
    assert callable(reader), "Missing production interface: from_smart_page"
    return reader(payload)


@pytest.mark.parametrize("family", ["GTT", "OCO"])
def test_smart_read_preserves_evidence(family):
    row = _current(family)
    row.update(
        status="ACTIVE",
        created_at="2025-09-30T07:00:00",
        expire_at=None,
        triggered_at="2025-09-30T08:00:00",
        updated_at="2025-09-30T08:00:01",
        is_cancellation_allowed=False,
        is_modification_allowed=True,
        account_id="fixture-account",
        child_legs={"undocumented": [{"order_id": "child-1", "failure": {"code": "REJECTED"}}]},
        requested={"quantity": 10},
        effective={"quantity": 9},
        groww_order_id="returned-ordinary-id",
    )
    original = deepcopy(row)
    result = _read_smart(row)
    assert result == {
        "smart_order_id": row["smart_order_id"],
        "smart_order_type": family,
        "segment": row["segment"],
        "raw_status": "ACTIVE",
        "status": "ARMED",
        "native": original,
    }
    assert row == original
    assert result["native"] is not row
    row["child_legs"]["undocumented"][0]["order_id"] = "changed-input"
    assert result["native"]["child_legs"]["undocumented"][0]["order_id"] == "child-1"
    result["native"]["child_legs"]["undocumented"][0]["failure"]["code"] = "changed-output"
    assert row["child_legs"]["undocumented"][0]["failure"]["code"] == "REJECTED"
    child = "order" if family == "GTT" else "target"
    result["native"][child]["price"] = "changed-price"
    assert row[child]["price"] == original[child]["price"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ACTIVE", "ARMED"),
        ("CANCELLED", "CANCELLED"),
        ("COMPLETED", "UNKNOWN"),
        ("TRIGGERED", "UNKNOWN"),
        ("FILLED", "UNKNOWN"),
        ("CLOSED", "UNKNOWN"),
        ("EXECUTED", "UNKNOWN"),
        ("REJECTED", "UNKNOWN"),
        ("EXPIRED", "UNKNOWN"),
        ("SUCCESS", "UNKNOWN"),
        ("ACK", "UNKNOWN"),
        ("active", "UNKNOWN"),
        (" ACTIVE ", "UNKNOWN"),
        ("", "UNKNOWN"),
        (None, "UNKNOWN"),
        (True, "UNKNOWN"),
        (200, "UNKNOWN"),
        ([], "UNKNOWN"),
        ({"status": "ACTIVE"}, "UNKNOWN"),
    ],
)
def test_smart_read_status_never_establishes_execution(raw, expected):
    row = {"smart_order_id": "native-id", "status": raw, "order_id": "ordinary-id", "filled_quantity": 10}
    result = _read_smart(row)
    assert result["raw_status"] == raw
    assert result["status"] == expected
    assert result["native"] == row
    assert set(result) == {"smart_order_id", "smart_order_type", "segment", "raw_status", "status", "native"}


def test_smart_read_abbreviated_documented_row_has_no_inferred_scope():
    row = {"smart_order_id": "gtt_91a7f4", "smart_order_type": "GTT", "status": "ACTIVE"}
    result = _read_smart(row)
    assert result["segment"] is None
    assert "segment" not in result["native"]
    assert result["smart_order_type"] == "GTT"
    with pytest.raises(ValueError):
        _modify(result, {"quantity": 1})
    with pytest.raises(ValueError):
        _path("get", result["smart_order_id"], result["segment"], result["smart_order_type"])


def test_smart_read_minimal_identity_never_defaults_family_or_status():
    row = {"smart_order_id": "oco_a12bc3"}
    assert _read_smart(row) == {
        "smart_order_id": "oco_a12bc3",
        "smart_order_type": None,
        "segment": None,
        "raw_status": None,
        "status": "UNKNOWN",
        "native": row,
    }


@pytest.mark.parametrize("identifier", [None, "", " ", "\t\n", True, 123, [], {}])
def test_smart_read_rejects_missing_or_invalid_identity(identifier):
    with pytest.raises(ValueError, match="smart_order_id"):
        _read_smart({"smart_order_id": identifier, "order_id": "ordinary-id", "reference_id": "reference-id"})


def test_smart_read_does_not_substitute_other_identifiers():
    with pytest.raises(ValueError, match="smart_order_id"):
        _read_smart({"order_id": "ordinary-id", "reference_id": "reference-id", "trading_symbol": "TCS"})


@pytest.mark.parametrize("identifier", ["future:id/1", "unicode-ä", " id "])
def test_smart_read_preserves_opaque_id_without_granting_path_safety(identifier):
    result = _read_smart({"smart_order_id": identifier, "segment": "CASH", "smart_order_type": "GTT"})
    assert result["smart_order_id"] == identifier
    with pytest.raises(ValueError):
        _path("get", identifier)


@pytest.mark.parametrize("candidate", [None, [], (), "row", 1, True])
def test_smart_read_rejects_non_mapping_rows(candidate):
    with pytest.raises(ValueError):
        _read_smart(candidate)


@pytest.mark.parametrize(
    ("family", "segment", "product"),
    [("GTT", "CASH", "CNC"), ("OCO", "CASH", "CNC"), ("OCO", "FNO", "MIS"), ("FUTURE", "OTHER", "NEW")],
)
def test_smart_page_preserves_all_returned_scope_without_eligibility_filter(family, segment, product):
    row = {"smart_order_id": "id", "smart_order_type": family, "segment": segment, "product_type": product}
    result = _read_page({"status": "SUCCESS", "payload": {"orders": [row]}})
    assert len(result) == 1
    assert result[0]["smart_order_type"] == family
    assert result[0]["segment"] == segment
    assert result[0]["native"] == row


@pytest.mark.parametrize("metadata", [{}, {"page": 0, "page_size": 10}, {"has_more": True, "next_page": 2}])
def test_page_is_not_complete_book(metadata):
    envelope = {"status": "SUCCESS", "payload": {"orders": [], **metadata}}
    original = deepcopy(envelope)
    assert _read_page(envelope) == []
    assert envelope == original


def test_smart_page_keeps_order_duplicates_failures_and_independent_native_copies():
    first = {"smart_order_id": "first", "status": "ACTIVE", "child_legs": {"failures": [{"code": "REJECTED"}]}}
    second = {"smart_order_id": "second", "status": "COMPLETED", "segment": "UNKNOWN"}
    envelope = {"status": "SUCCESS", "payload": {"orders": [first, second, first], "next_page": 1}}
    original = deepcopy(envelope)
    result = _read_page(envelope)
    assert [row["smart_order_id"] for row in result] == ["first", "second", "first"]
    assert [row["status"] for row in result] == ["ARMED", "UNKNOWN", "ARMED"]
    assert [row["native"] for row in result] == original["payload"]["orders"]
    result[0]["native"]["child_legs"]["failures"][0]["code"] = "changed"
    assert result[2]["native"]["child_legs"]["failures"][0]["code"] == "REJECTED"
    assert envelope == original


@pytest.mark.parametrize(
    "envelope",
    [
        None,
        [],
        (),
        "response",
        True,
        200,
        {},
        {"orders": []},
        {"payload": {"orders": []}},
        {"status": "SUCCESS"},
        {"status": "SUCCESS", "orders": []},
        {"status": "FAILURE", "payload": {"orders": []}},
        {"status": "success", "payload": {"orders": []}},
        {"status": True, "payload": {"orders": []}},
        {"status": 200, "payload": {"orders": []}},
        {"status": [], "payload": {"orders": []}},
        {"status": "SUCCESS", "payload": None},
        {"status": "SUCCESS", "payload": []},
        {"status": "SUCCESS", "payload": {}},
        {"status": "SUCCESS", "payload": {"orders": None}},
        {"status": "SUCCESS", "payload": {"orders": {}}},
        {"status": "SUCCESS", "payload": {"orders": ()}},
        {"status": "SUCCESS", "payload": {"orders": "[]"}},
        {"status": "SUCCESS", "payload": {"orders": False}},
    ],
)
def test_smart_page_rejects_unavailable_or_malformed_envelopes(envelope):
    with pytest.raises(ValueError):
        _read_page(envelope)


@pytest.mark.parametrize("bad_row", [None, [], "row", True, {}, {"order_id": "ordinary-id"}])
def test_smart_page_rejects_malformed_item_instead_of_returning_partial_page(bad_row):
    with pytest.raises(ValueError):
        _read_page({"status": "SUCCESS", "payload": {"orders": [{"smart_order_id": "valid"}, bad_row]}})


def test_smart_reads_accept_read_only_top_level_mappings():
    row = {"smart_order_id": "id", "status": "ACTIVE", "child_legs": {"opaque": [1]}}
    result = _read_smart(MappingProxyType(row))
    assert result["native"] == row
    result["native"]["child_legs"]["opaque"].append(2)
    assert row["child_legs"]["opaque"] == [1]
    envelope = MappingProxyType({"status": "SUCCESS", "payload": MappingProxyType({"orders": [MappingProxyType(row)]})})
    assert _read_page(envelope)[0]["native"] == row
