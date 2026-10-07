"""Strict JSON evidence and its existing INDstocks smart-result caller."""

from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import NoReturn

import pytest

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_gateway.brokers.indmoney_mapping import (
    IndMoneyMappingError,
    extract_smart_order_ids,
    from_indmoney_smart_results,
)
from flinttrade_gateway.json_evidence import copy_json_evidence

pytestmark = pytest.mark.unit


def _hook_called(*args: object, **kwargs: object) -> NoReturn:
    raise AssertionError("Untrusted evidence hook was invoked")


class _HostileMeta(type):
    __eq__ = _hook_called
    __hash__ = type.__hash__


class _Opaque(metaclass=_HostileMeta):
    __getattribute__ = _hook_called
    __repr__ = _hook_called
    __str__ = _hook_called
    __bool__ = _hook_called
    __int__ = _hook_called
    __float__ = _hook_called
    __index__ = _hook_called
    __iter__ = _hook_called
    __eq__ = _hook_called
    __hash__ = object.__hash__
    __copy__ = _hook_called
    __deepcopy__ = _hook_called
    __json__ = _hook_called
    to_dict = _hook_called
    model_dump = _hook_called


class _StringSubclass(str):
    __str__ = _hook_called
    __repr__ = _hook_called
    __copy__ = _hook_called
    __deepcopy__ = _hook_called


class _IntSubclass(int):
    __int__ = _hook_called
    __float__ = _hook_called
    __index__ = _hook_called


class _FloatSubclass(float):
    __float__ = _hook_called


class _ListSubclass(list):
    __iter__ = _hook_called
    __len__ = _hook_called
    __getitem__ = _hook_called
    __deepcopy__ = _hook_called


class _DictSubclass(dict):
    __iter__ = _hook_called
    __len__ = _hook_called
    __getitem__ = _hook_called
    items = _hook_called
    values = _hook_called
    __deepcopy__ = _hook_called


_HOSTILE_FACTORIES = [_Opaque, _StringSubclass, _IntSubclass, _FloatSubclass, _ListSubclass, _DictSubclass]
_HOSTILE_IDS = ["opaque-metaclass", "str-subclass", "int-subclass", "float-subclass", "list-subclass", "dict-subclass"]


def _nested_containers(count: int, kind: str, *, empty_leaf: bool) -> object:
    value: object = ({} if kind == "dict" else []) if empty_leaf else None
    for index in range(count - int(empty_leaf)):
        value = {"child": value} if kind == "dict" or (kind == "mixed" and index % 2) else [value]
    return value


def _cycle(kind: str) -> object:
    if kind == "list":
        values: list[object] = []
        values.append(values)
        return values
    record: dict[str, object] = {}
    record["child"] = record if kind == "dict" else [record]
    return record


@pytest.mark.parametrize("value", [None, "", "evidence", False, True, 0, -1, 0.0, -0.0, 1.5,
                                   sys.float_info.max, -sys.float_info.max, 5e-324])
def test_copy_preserves_exact_primitives_and_float_sign(value: object) -> None:
    copied = copy_json_evidence(value)
    assert type(copied) is type(value)
    assert copied == value
    if type(value) is float:
        assert type(copied) is float
        assert copied.hex() == value.hex()


def test_copy_preserves_integers_beyond_float_and_json_string_conversion_limits() -> None:
    large = 10 ** 5000
    copied = copy_json_evidence({"large": large, "negative": -large})
    assert type(copied) is dict
    assert type(copied["large"]) is int and copied["large"] == large
    assert type(copied["negative"]) is int and copied["negative"] == -large


def test_copy_preserves_order_null_and_empty_containers_with_bidirectional_detachment() -> None:
    source = {"z": [None, False, 0, -0.0, {"text": "evidence"}], "a": {}, "": []}
    copied = copy_json_evidence(source)
    assert type(copied) is dict
    assert copied == {"z": [None, False, 0, -0.0, {"text": "evidence"}], "a": {}, "": []}
    assert list(copied) == ["z", "a", ""]
    assert copied is not source and copied["z"] is not source["z"]
    assert copied["z"][3].hex() == "-0x0.0p+0"
    source["z"][4]["text"] = "source changed"
    source["a"]["new"] = 1
    source[""].append("source changed")
    assert copied["z"][4] == {"text": "evidence"} and copied["a"] == {} and copied[""] == []
    copied["z"].append("copy changed")
    assert len(source["z"]) == 5


@pytest.mark.parametrize("root_kind", ["dict", "list"])
def test_shared_acyclic_aliases_become_independent_detached_branches(root_kind: str) -> None:
    shared = {"values": [0, None]}
    source = {"left": shared, "right": shared} if root_kind == "dict" else [shared, shared]
    copied = copy_json_evidence(source)
    if type(copied) is dict:
        left, right = copied["left"], copied["right"]
    else:
        assert type(copied) is list
        left, right = copied
    assert left is not right and left is not shared and right is not shared
    assert left["values"] is not right["values"] and left["values"] is not shared["values"]
    left["values"].append(1)
    assert right == {"values": [0, None]} and shared == {"values": [0, None]}


@pytest.mark.parametrize("kind", ["list", "dict", "mixed"])
@pytest.mark.parametrize("empty_leaf", [False, True], ids=["primitive-leaf", "empty-container-leaf"])
@pytest.mark.parametrize("count", [1, 63, 64])
def test_copy_accepts_at_most_64_containers_on_each_branch(count: int, kind: str, empty_leaf: bool) -> None:
    source = _nested_containers(count, kind, empty_leaf=empty_leaf)
    copied = copy_json_evidence(source)
    assert copied == source and copied is not source


@pytest.mark.parametrize("kind", ["list", "dict", "mixed"])
@pytest.mark.parametrize("empty_leaf", [False, True], ids=["primitive-leaf", "empty-container-leaf"])
@pytest.mark.parametrize("count", [65, 1000])
def test_copy_rejects_excess_depth_as_value_error_before_python_recursion_limit(
    count: int, kind: str, empty_leaf: bool,
) -> None:
    with pytest.raises(ValueError):
        copy_json_evidence(_nested_containers(count, kind, empty_leaf=empty_leaf))


@pytest.mark.parametrize("kind", ["list", "dict", "mixed"])
def test_copy_rejects_ancestor_cycles_as_value_error(kind: str) -> None:
    with pytest.raises(ValueError):
        copy_json_evidence(_cycle(kind))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), Decimal("1.25"),
                                   b"evidence", (1,), {1}, frozenset({1}), datetime(2026, 1, 1), object()],
                         ids=["nan", "inf", "negative-inf", "decimal", "bytes", "tuple", "set",
                              "frozenset", "datetime", "object"])
def test_copy_rejects_non_json_or_non_finite_values(value: object) -> None:
    with pytest.raises(ValueError):
        copy_json_evidence({"nested": [value]})


@pytest.mark.parametrize("key", [0, True, None, ("key",), _StringSubclass("key")],
                         ids=["int", "bool", "null", "tuple", "str-subclass"])
def test_copy_rejects_non_exact_string_keys_without_coercion(key: object) -> None:
    with pytest.raises(ValueError):
        copy_json_evidence({key: "evidence"})


@pytest.mark.parametrize("factory", _HOSTILE_FACTORIES, ids=_HOSTILE_IDS)
@pytest.mark.parametrize("nested", [False, True], ids=["root", "nested"])
def test_copy_rejects_hostile_values_without_invoking_any_hook(factory: Callable[[], object], nested: bool) -> None:
    value = factory()
    with pytest.raises(ValueError):
        copy_json_evidence({"nested": [value]} if nested else value)


def test_copy_rejects_hostile_dictionary_keys_without_attribute_or_conversion_hooks() -> None:
    with pytest.raises(ValueError):
        copy_json_evidence({_Opaque(): "evidence"})


def test_indmoney_smart_results_reject_65_containers_even_with_an_empty_leaf() -> None:
    nested: object = []
    for _ in range(63):
        nested = [nested]
    source = {"order_id": "EQ-TEST", "diagnostic": nested}
    response = {"status": "success", "data": {"order_data": [source]}}

    with pytest.raises(BrokerReadResponseInvalid):
        from_indmoney_smart_results(response)


@pytest.mark.parametrize("empty_leaf", [False, True])
def test_indmoney_smart_results_accept_exactly_64_containers(empty_leaf: bool) -> None:
    diagnostic = _nested_containers(63, "mixed", empty_leaf=empty_leaf)
    source = {"order_id": "EQ-TEST", "diagnostic": diagnostic}
    result = from_indmoney_smart_results({"status": "success", "data": {"order_data": [source]}})
    assert result[0]["parent_order_id"] == "EQ-TEST"
    assert result[0]["raw"] == source and result[0]["raw"] is not source
    assert result[0]["raw"]["diagnostic"] is not diagnostic


@pytest.mark.parametrize("factory", _HOSTILE_FACTORIES, ids=_HOSTILE_IDS)
def test_indmoney_smart_results_keep_the_read_error_taxonomy_without_hooks(factory: Callable[[], object]) -> None:
    response = {"status": "success", "data": {"order_data": [{"order_id": "EQ-TEST", "diagnostic": factory()}]}}
    with pytest.raises(BrokerReadResponseInvalid) as error:
        from_indmoney_smart_results(response)
    assert type(error.value) is BrokerReadResponseInvalid
    assert error.value.__cause__ is None and error.value.__suppress_context__
    with pytest.raises(IndMoneyMappingError, match="No valid order id") as write_error:
        extract_smart_order_ids(response)
    assert write_error.value.__cause__ is None and write_error.value.__suppress_context__


@pytest.mark.parametrize("kind", ["list", "dict", "mixed"])
def test_indmoney_smart_results_translate_cycles_to_the_existing_read_error(kind: str) -> None:
    response = {"status": "success", "data": {"order_data": [{"order_id": "EQ-TEST", "diagnostic": _cycle(kind)}]}}
    with pytest.raises(BrokerReadResponseInvalid):
        from_indmoney_smart_results(response)


def test_indmoney_smart_results_preserve_native_rows_and_detach_all_source_branches() -> None:
    shared = {"values": [None, False, 0, -0.0, sys.float_info.max, 10 ** 5000]}
    rows = [
        {"order_id": "EQ-PARENT", "order_status": "CREATED", "child_order_details": {
            "order_id": "GTT-CHILD", "order_status": "CREATED"}, "diagnostic_a": shared, "diagnostic_b": shared},
        {"order_id": "DRV-PARENT", "order_status": "FAILED", "error": {"code": "RMS", "message": "denied"}},
        {"error": "validation failed", "child_order_details": None},
    ]
    response = {"status": "success", "data": {"order_data": rows}}
    results = from_indmoney_smart_results(response)
    assert [(row["parent_order_id"], row["parent_status"], row["child_order_id"], row["child_status"])
            for row in results] == [("EQ-PARENT", "CREATED", "GTT-CHILD", "CREATED"),
                                   ("DRV-PARENT", "FAILED", None, None), (None, None, None, None)]
    assert results[1]["error"] == {"code": "RMS", "message": "denied"}
    assert results[2]["error"] == "validation failed" and results[2]["raw"]["child_order_details"] is None
    assert results[0]["raw"] == rows[0] and results[0]["raw"] is not rows[0]
    raw = results[0]["raw"]
    assert raw["diagnostic_a"] is not raw["diagnostic_b"] and raw["diagnostic_a"] is not shared
    assert raw["diagnostic_a"]["values"][3].hex() == "-0x0.0p+0"
    rows[0]["child_order_details"]["order_status"] = "source changed"
    rows[1]["error"]["message"] = "source changed"
    shared["values"].append("source changed")
    assert raw["child_order_details"]["order_status"] == "CREATED"
    assert results[1]["error"]["message"] == "denied" and len(raw["diagnostic_a"]["values"]) == 6
    raw["diagnostic_a"]["values"].append("copy changed")
    assert len(raw["diagnostic_b"]["values"]) == 6 and shared["values"][-1] == "source changed"
    with pytest.raises(IndMoneyMappingError, match="single|multiple"):
        extract_smart_order_ids(response)


def test_indmoney_smart_results_keep_flat_and_explicit_null_child_ack_compatibility() -> None:
    assert extract_smart_order_ids({"status": "success", "data": {"order_id": "GTT-FLAT"}}) == ("GTT-FLAT", None)
    assert extract_smart_order_ids({"status": "success", "data": {
        "order_data": [{"order_id": "EQ-TEST", "child_order_details": None}],
    }}) == ("EQ-TEST", None)
