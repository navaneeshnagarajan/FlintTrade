"""Offline schema and source-backed starting-inventory checks."""

from __future__ import annotations

import json
import tomllib
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path

import pytest

from flinttrade_gateway.order_feature_contract import OrderFeatureRecord, validate_feature_records

ROOT = Path(__file__).resolve().parents[4]
INVENTORY = ROOT / "docs/acceptance/FT-GTT-001-capabilities.json"
BROKERS = {"dhan", "upstox", "kotakneo", "indmoney", "groww", "delta"}


def record(**changes: object) -> OrderFeatureRecord:
    """Supply a concrete example without implying runtime eligibility."""
    values = {
        "schema_version": 1,
        "broker": "dhan",
        "api_version": "v2",
        "checked_on": "2026-10-06",
        "family": "native_gtt_single",
        "operation": "create",
        "product": "CNC",
        "segment": "NSE_EQ",
        "documented": "yes",
        "implemented": "unknown",
        "readiness": "blocked",
        "supported_fields": ("quantity", "triggerPrice"),
        "quantity_unit": "shares",
        "limitations": ("Independent runtime evidence is outstanding.",),
        "sources": ("https://dhanhq.co/docs/v2/forever/",),
    }
    values.update(changes)
    return OrderFeatureRecord(**values)


def inventory() -> tuple[dict, list[OrderFeatureRecord]]:
    data = json.loads(INVENTORY.read_text(encoding="utf-8"))
    records = []
    for item in data["records"]:
        assert set(item) == {field.name for field in fields(OrderFeatureRecord)}
        item = dict(item)
        for name in ("supported_fields", "limitations", "sources"):
            item[name] = tuple(item[name])
        records.append(OrderFeatureRecord(**item))
    return data, records


def test_contract_is_frozen_and_has_only_the_approved_fields():
    assert [field.name for field in fields(OrderFeatureRecord)] == [
        "schema_version", "broker", "api_version", "checked_on", "family", "operation",
        "product", "segment", "documented", "implemented", "readiness", "supported_fields",
        "quantity_unit", "limitations", "sources",
    ]
    with pytest.raises(FrozenInstanceError):
        record().readiness = "verified"


def test_support_does_not_imply_readiness():
    supported = record(documented="yes", implemented="yes", readiness="unverified")
    validate_feature_records([supported])
    assert supported.readiness == "unverified"
    data, records = inventory()
    assert data["schema_version"] == 1
    assert any(item.documented == "yes" for item in records)
    assert {item.readiness for item in records} <= {"blocked", "unverified"}


def test_native_gtt_does_not_require_native_reduce_only():
    gtt = record(documented="yes", implemented="yes", readiness="unverified")
    reduce_only = record(family="native_reduce_only", documented="no", implemented="no", supported_fields=())
    validate_feature_records([gtt, reduce_only])
    assert gtt.readiness == "unverified"


def test_records_are_unique_by_broker_version_family_operation_product_segment():
    original = record()
    with pytest.raises(ValueError, match="duplicate"):
        validate_feature_records([original, replace(original, readiness="unverified")])
    for name, value in {
        "broker": "upstox", "api_version": "v3", "family": "native_gtt_oco",
        "operation": "modify", "product": "MTF", "segment": "BSE_EQ",
    }.items():
        validate_feature_records([original, replace(original, **{name: value})])


def test_all_six_brokers_have_explicit_unknowns():
    _, records = inventory()
    validate_feature_records(records)
    assert {item.broker for item in records} == BROKERS
    for broker in BROKERS:
        assert any(item.broker == broker and item.documented == "unknown" for item in records)
        assert any(item.broker == broker and item.implemented == "unknown" for item in records)
        assert any(item.broker == broker and item.quantity_unit == "unknown" for item in records)


@pytest.mark.parametrize("name,value", [
    ("schema_version", 0), ("schema_version", 2), ("schema_version", True),
    ("schema_version", "1"), ("broker", ""), ("broker", " dhan"),
    ("api_version", ""), ("checked_on", "2026-02-30"), ("checked_on", "20261006"),
    ("checked_on", "2026-10-06T00:00:00Z"), ("family", ""), ("operation", None),
    ("product", ""), ("segment", ""), ("documented", "YES"), ("implemented", "maybe"),
    ("readiness", "ready"), ("quantity_unit", ""), ("quantity_unit", None),
    ("supported_fields", ["quantity"]), ("supported_fields", ("quantity", "quantity")),
    ("supported_fields", ("",)), ("supported_fields", (1,)),
    ("limitations", ["Unverified"]), ("limitations", (" ",)),
    ("sources", ()), ("sources", ["https://dhanhq.co/docs/v2/forever/"]),
    ("sources", ("http://dhanhq.co/docs/v2/forever/",)),
    ("sources", ("https://",)), ("sources", ("https://user:secret@example.com/",)),
])
def test_invalid_records_raise_value_error(name, value):
    with pytest.raises(ValueError):
        validate_feature_records([record(**{name: value})])


@pytest.mark.parametrize("value", [None, {}, "record", 1])
def test_non_records_raise_value_error(value):
    with pytest.raises(ValueError):
        validate_feature_records([value])


@pytest.mark.parametrize("name", ["product", "segment", "quantity_unit"])
@pytest.mark.parametrize("value", ["*", "ALL", "any", "NSE_*"])
def test_wildcards_cannot_grant_eligibility(name, value):
    with pytest.raises(ValueError, match="wildcard"):
        validate_feature_records([record(**{name: value})])


@pytest.mark.parametrize("name", ["documented", "implemented", "product", "segment", "quantity_unit"])
def test_verified_requires_positive_evidence_and_concrete_scope(name):
    verified = record(documented="yes", implemented="yes", readiness="verified")
    validate_feature_records([verified])
    with pytest.raises(ValueError, match="verified"):
        validate_feature_records([replace(verified, **{name: "unknown"})])
    if name in {"documented", "implemented"}:
        with pytest.raises(ValueError, match="verified"):
            validate_feature_records([replace(verified, **{name: "no"})])


def test_unknown_scope_is_an_explicit_unresolved_record():
    unknown = record(product="unknown", segment="unknown", quantity_unit="unknown")
    validate_feature_records([unknown])
    assert (unknown.product, unknown.segment, unknown.quantity_unit) == ("unknown",) * 3
    with pytest.raises(ValueError, match="limitations"):
        validate_feature_records([replace(unknown, limitations=())])


@pytest.mark.parametrize("name", ["product", "segment", "quantity_unit"])
def test_unknown_placeholder_case_cannot_be_verified(name):
    with pytest.raises(ValueError, match="verified"):
        validate_feature_records([record(documented="yes", implemented="yes", readiness="verified", **{name: "UNKNOWN"})])


def test_inventory_versions_match_public_dependency_pins_without_upgrading():
    data, records = inventory()
    lock = tomllib.loads((ROOT / "brokers.lock").read_text(encoding="utf-8"))
    pins = {item["name"]: item for item in lock["broker"]}
    for broker, package in {
        "dhan": "dhanhq", "upstox": "upstox-python-sdk", "kotakneo": "kotakneoapi", "groww": "growwapi",
    }.items():
        assert data["sdk_pins"][broker]["package"] == package
        assert data["sdk_pins"][broker]["version"] == pins[package]["version"]
    assert data["sdk_pins"]["kotakneo"]["source_commit"] == pins["kotakneoapi"]["source_commit"]
    assert data["sdk_pins"]["kotakneo"]["release_version"] == pins["kotakneoapi"]["release_version"]
    assert data["sdk_pins"]["indmoney"]["package"] is None
    assert data["sdk_pins"]["delta"]["package"] is None
    assert {item.checked_on for item in records} == {"2026-10-06"}


@pytest.mark.parametrize("broker,families", [
    ("dhan", {"normal", "slice", "native_gtt_single", "native_gtt_oco", "super", "conditional_trigger",
              "legacy_cover", "legacy_bracket"}),
    ("upstox", {"normal", "slice", "native_gtt_single", "native_gtt_multiple", "batch", "exit_all"}),
    ("kotakneo", {"normal", "legacy_cover", "legacy_bracket", "native_gtt"}),
    ("indmoney", {"normal", "smart_trigger", "smart_linked", "trailing_stop", "pure_market"}),
    ("groww", {"normal", "native_gtt_single", "native_gtt_oco", "gtt_child_legs"}),
    ("delta", {"normal", "conditional", "order_bracket", "position_bracket", "batch", "close_all",
               "native_reduce_only", "post_only", "trailing_stop"}),
])
def test_starting_inventory_preserves_reviewed_families(broker, families):
    _, records = inventory()
    assert families <= {item.family for item in records if item.broker == broker}


@pytest.mark.parametrize("broker,family", [
    ("dhan", "normal"), ("dhan", "native_gtt_single"), ("dhan", "native_gtt_oco"), ("dhan", "super"),
    ("dhan", "conditional_trigger"), ("upstox", "normal"), ("upstox", "native_gtt_single"),
    ("upstox", "native_gtt_multiple"), ("kotakneo", "normal"), ("indmoney", "normal"),
    ("indmoney", "smart_trigger"), ("indmoney", "smart_linked"), ("groww", "normal"),
    ("groww", "native_gtt_single"), ("groww", "native_gtt_oco"), ("delta", "normal"),
    ("delta", "conditional"),
])
def test_reviewed_lifecycle_operations_have_separate_records(broker, family):
    _, records = inventory()
    assert {"create", "modify", "cancel", "list"} <= {
        item.operation for item in records if item.broker == broker and item.family == family
    }


def test_indstocks_ignored_trailing_fields_cannot_appear_active():
    _, records = inventory()
    trailing = [item for item in records if item.broker == "indmoney" and item.family == "trailing_stop"]
    assert trailing
    for item in trailing:
        assert item.documented == "no"
        assert item.readiness == "blocked"
        assert not {"is_tsl", "tsl_step_size"}.intersection(item.supported_fields)
        assert all(field in " ".join(item.limitations) for field in ("is_tsl", "tsl_step_size", "ignored"))


def test_indstocks_requested_market_and_effective_limit_remain_distinct():
    _, records = inventory()
    pure_market = [item for item in records if item.broker == "indmoney" and item.family == "pure_market"]
    assert pure_market and all(item.documented == "no" for item in pure_market)
    normal = [item for item in records if item.broker == "indmoney" and item.family == "normal"
              and item.operation == "create"]
    assert normal
    assert all("MARKET" in " ".join(item.limitations) and "LIMIT" in " ".join(item.limitations) for item in normal)


def test_kotak_v3_removed_legacy_products_are_not_reintroduced():
    _, records = inventory()
    for family in ("legacy_cover", "legacy_bracket"):
        removed = [item for item in records if item.broker == "kotakneo" and item.family == family]
        assert removed
        assert all(item.documented == "no" and item.implemented == "no" for item in removed)
        assert all("removed" in " ".join(item.limitations) for item in removed)


def test_delta_native_reduce_only_is_not_equated_with_gtt_or_client_checks():
    _, records = inventory()
    native = [item for item in records if item.broker == "delta" and item.family == "native_reduce_only"]
    assert native
    assert any(item.documented == "yes" and item.product == "perpetual_futures" for item in native)
    assert all("reduce_only" in item.supported_fields for item in native)
    assert all(item.quantity_unit == "contracts" and item.readiness == "blocked" for item in native)


def test_groww_modification_fields_are_resource_specific():
    _, records = inventory()
    single = [item for item in records if item.broker == "groww" and item.family == "native_gtt_single"
              and item.operation == "modify"]
    oco = [item for item in records if item.broker == "groww" and item.family == "native_gtt_oco"
           and item.operation == "modify"]
    assert single and oco
    assert all(not {"duration", "product_type"}.intersection(item.supported_fields) for item in single)
    assert all({"order.order_type", "order.price"} <= set(item.supported_fields) for item in single)
    assert all(not {"order.order_type", "order.price", "target.order_type", "target.price"}.intersection(
        item.supported_fields,
    ) for item in oco)


def test_unestablished_product_segment_expansions_remain_unknown():
    _, records = inventory()
    for broker, family, product, segment in [
        ("dhan", "native_gtt_single", "MTF", "NSE_EQ"),
        ("upstox", "native_gtt_multiple", "I", "NSE_FO"),
        ("groww", "native_gtt_single", "NRML", "FNO"),
        ("indmoney", "smart_trigger", "MARGIN", "DERIVATIVE"),
    ]:
        expanded = [item for item in records if (item.broker, item.family, item.product, item.segment)
                    == (broker, family, product, segment)]
        assert expanded
        assert all(item.documented == "unknown" for item in expanded)
        assert all("combination" in " ".join(item.limitations) for item in expanded)


def test_inventory_preserves_operation_specific_visibility_limits():
    _, records = inventory()
    upstox_reads = [item for item in records if item.broker == "upstox"
                    and item.family.startswith("native_gtt_") and item.operation in {"list", "get"}]
    assert upstox_reads
    assert all("completed" in " ".join(item.limitations) for item in upstox_reads)


def test_upstox_normal_placement_versions_remain_distinct():
    _, records = inventory()
    assert {"v2", "v3"} <= {item.api_version for item in records if item.broker == "upstox"
                           and item.family == "normal" and item.operation == "create"}


def test_mapping_evidence_does_not_claim_complete_adapter_support():
    data, records = inventory()
    assert "mapping" in data["evidence_policy"]["implemented"]
    assert all(item.implemented != "yes" for item in records)
    assert not data["coverage"]["exhaustive"]
    assert data["coverage"]["unresolved"]


@pytest.mark.parametrize("family,operation,expected_fields", [
    ("order_bracket", "create", {
        "product_id", "product_symbol", "size", "side", "order_type", "limit_price", "time_in_force",
        "bracket_stop_loss_limit_price", "bracket_stop_loss_price", "bracket_take_profit_limit_price",
        "bracket_take_profit_price", "bracket_trail_amount", "bracket_stop_trigger_method",
    }),
    ("order_bracket", "modify", {
        "id", "product_id", "product_symbol", "bracket_stop_loss_limit_price", "bracket_stop_loss_price",
        "bracket_take_profit_limit_price", "bracket_take_profit_price", "bracket_trail_amount",
        "bracket_stop_trigger_method",
    }),
    ("position_bracket", "create", {
        "product_id", "product_symbol", "stop_loss_order", "take_profit_order", "bracket_stop_trigger_method",
    }),
    ("position_bracket", "modify", set()),
])
def test_delta_bracket_fields_are_resource_and_operation_specific(family, operation, expected_fields):
    _, records = inventory()
    selected = [item for item in records if item.broker == "delta" and item.family == family
                and item.operation == operation]
    assert selected
    assert all(set(item.supported_fields) == expected_fields for item in selected)
    if family == "position_bracket" and operation == "modify":
        assert all(item.documented == "unknown" for item in selected)
        assert all("position-specific" in " ".join(item.limitations) for item in selected)
    elif family == "order_bracket":
        source = "#place-order" if operation == "create" else "#edit-bracket-order"
        assert all(any(link.endswith(source) for link in item.sources) for item in selected)


@pytest.mark.parametrize("operation", ["create", "modify"])
def test_indstocks_trigger_fields_exclude_plain_limit_price(operation):
    _, records = inventory()
    selected = [item for item in records if item.broker == "indmoney" and item.family == "smart_trigger"
                and item.operation == operation]
    assert selected
    for item in selected:
        assert "limit_price" not in item.supported_fields
        assert {"trigger_price", "trigger_limit_price"} <= set(item.supported_fields)
        assert "limit_price is excluded" in " ".join(item.limitations)


@pytest.mark.parametrize("operation,expected_fields", [
    ("get", {"id", "status", "requested_qty", "traded_qty"}),
    ("list", {"id", "status", "requested_qty", "traded_qty"}),
    ("trades", {"order_id", "segment", "fill_id", "exch_order_id", "quantity", "price", "trade_date"}),
    ("modify", {"order_id", "segment", "qty", "limit_price"}),
])
def test_indstocks_normal_fields_use_the_native_operation_contract(operation, expected_fields):
    _, records = inventory()
    selected = [item for item in records if item.broker == "indmoney" and item.family == "normal"
                and item.operation == operation]
    assert selected
    assert all(set(item.supported_fields) == expected_fields for item in selected)


def test_upstox_single_gtt_does_not_advertise_a_multiple_stoploss_trailing_field():
    _, records = inventory()
    single = [item for item in records if item.broker == "upstox" and item.family == "native_gtt_single"]
    multiple_creates = [item for item in records if item.broker == "upstox"
                        and item.family == "native_gtt_multiple" and item.operation == "create"]
    assert single and multiple_creates
    assert all("rules.trailing_gap" not in item.supported_fields for item in single)
    assert all("rules.trailing_gap" in item.supported_fields for item in multiple_creates)



def test_upstox_multi_cancel_has_native_filter_scope_and_response_only_ids():
    _, records = inventory()
    cancel = [item for item in records if item.broker == "upstox" and item.api_version == "v2"
              and item.family == "batch" and item.operation == "cancel"]
    assert cancel
    for item in cancel:
        assert set(item.supported_fields) == {"tag", "segment"}
        limitations = " ".join(item.limitations)
        assert "data.order_ids" in limitations and "response-only" in limitations
        assert "Without tag or segment" in limitations and "all open" in limitations
        assert "AMO and regular" in limitations
        assert "10" in limitations and "rejected" in limitations
        assert "https://upstox.com/developer/api-documentation/cancel-multi-order/" in item.sources
        assert item.implemented == "unknown" and item.readiness == "blocked"
