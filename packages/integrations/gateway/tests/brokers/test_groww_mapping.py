"""Focused contract tests for Groww response mapping."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from flinttrade_core.broker_read_port import BrokerReadResponseInvalid
from flinttrade_core.exceptions import BrokerError
from flinttrade_gateway.brokers import groww_mapping as mapping

pytestmark = pytest.mark.unit


def test_order_mapping_keeps_requested_and_filled_quantities_separate() -> None:
    mapped = mapping.from_order(
        {
            "groww_order_id": "G1",
            "order_status": "OPEN",
            "exchange": "NSE",
            "segment": "CASH",
            "quantity": 10,
            "filled_quantity": 4,
        }
    )

    assert mapped["quantity"] == 10
    assert mapped["filled_quantity"] == 4


def test_order_mapping_does_not_invent_requested_quantity_from_fills() -> None:
    mapped = mapping.from_order(
        {
            "groww_order_id": "G1",
            "order_status": "EXECUTED",
            "exchange": "NSE",
            "segment": "CASH",
            "filled_quantity": 4,
        }
    )

    assert "quantity" not in mapped
    assert mapped["filled_quantity"] == 4


def test_cancellation_requested_stays_non_terminal() -> None:
    mapped = mapping.from_order(
        {
            "groww_order_id": "G1",
            "order_status": "CANCELLATION_REQUESTED",
            "exchange": "NSE",
            "segment": "CASH",
            "quantity": 10,
            "filled_quantity": 4,
        }
    )

    assert mapped["status"] == "CANCEL_PENDING"


def test_to_modify_payload_ignores_disclosed_quantity() -> None:
    payload = mapping.to_modify_payload(
        "G1",
        {"pricetype": "LIMIT", "quantity": 5, "price": 100, "disclosed_quantity": 25},
        segment="CASH",
    )
    assert payload == {
        "groww_order_id": "G1",
        "segment": "CASH",
        "order_type": "LIMIT",
        "quantity": 5,
        "price": 100.0,
    }
    assert "disclosed_quantity" not in payload


@pytest.mark.parametrize("field", ["quantity", "filled_quantity", "remaining_quantity"])
@pytest.mark.parametrize("value", [-1, "-1", 1.5, "1.5", True, "NaN", "1_000", " 10", "１２"])
def test_order_read_rejects_non_whole_or_negative_quantity_evidence(field, value) -> None:
    row = {
        "groww_order_id": "G1",
        "order_status": "OPEN",
        "exchange": "NSE",
        "segment": "CASH",
        "quantity": 10,
        "filled_quantity": 4,
        "remaining_quantity": 6,
    }
    row[field] = value
    with pytest.raises(BrokerReadResponseInvalid):
        mapping.from_order(row)


@pytest.mark.parametrize(
    "counts",
    [
        {"quantity": 10, "filled_quantity": 11},
        {"quantity": "9007199254740992", "filled_quantity": "9007199254740993"},
        {"quantity": 10, "remaining_quantity": 11},
        {"quantity": 10, "filled_quantity": 4, "remaining_quantity": 7},
    ],
)
def test_order_read_rejects_contradictory_total_filled_and_remaining(counts) -> None:
    with pytest.raises(BrokerReadResponseInvalid):
        mapping.from_order({"order_status": "OPEN", "exchange": "NSE", "segment": "CASH", **counts})


def test_order_read_uses_exact_large_integers_for_partial_status() -> None:
    mapped = mapping.from_order(
        {
            "order_status": "OPEN",
            "exchange": "NSE",
            "segment": "CASH",
            "quantity": "9007199254740993",
            "filled_quantity": "9007199254740992",
            "remaining_quantity": "1",
        }
    )
    assert mapped["status"] == "PARTIALLY_FILLED"
    assert mapped["quantity"] == "9007199254740993"
    assert mapped["filled_quantity"] == "9007199254740992"
    assert mapped["remaining_quantity"] == "1"


def test_cancelled_partial_fill_and_absent_counts_remain_distinct() -> None:
    mapped = mapping.from_order(
        {
            "order_status": "CANCELLED",
            "exchange": "BSE",
            "segment": "FNO",
            "quantity": 100,
            "filled_quantity": 40,
            "remaining_quantity": 0,
        }
    )
    assert mapped["status"] == "CANCELLED"
    assert mapped["filled_quantity"] == 40
    assert mapped["remaining_quantity"] == 0
    unknown = mapping.from_order({"order_status": "FUTURE_STATE", "exchange": "NSE", "segment": "CASH"})
    assert unknown["status"] == "UNKNOWN"
    assert "quantity" not in unknown and "filled_quantity" not in unknown and "remaining_quantity" not in unknown


def _ordinary_request(**edits):
    return SimpleNamespace(
        **{
            "symbol": "TCS",
            "action": "BUY",
            "exchange": "NSE",
            "product": "CNC",
            "pricetype": "LIMIT",
            "quantity": "10",
            "price": 100,
            "trigger_price": 95,
            "validity": "DAY",
            "strategy": "FlintTest",
            **edits,
        }
    )


@pytest.mark.parametrize(
    ("canonical", "native"),
    [
        ("SL", "SL"),
        ("SL-M", "SL_M"),
        ("SLM", "SL_M"),
        ("SL_M", "SL_M"),
        ("STOP_LOSS_LIMIT", "SL"),
        ("STOP_LOSS_MARKET", "SL_M"),
    ],
)
def test_ordinary_stop_create_and_modify_use_current_rest_tokens(canonical, native) -> None:
    created = mapping.to_place_order_payload(_ordinary_request(pricetype=canonical))
    modified = mapping.to_modify_payload(
        "G1", {"pricetype": canonical, "price": 100, "trigger_price": 95}, segment="CASH"
    )
    assert created["order_type"] == modified["order_type"] == native
    assert created["trigger_price"] == modified["trigger_price"] == 95


@pytest.mark.parametrize(
    ("native", "canonical"),
    [
        ("SL", "SL"),
        ("SL_M", "SL-M"),
        ("SL-M", "SL-M"),
        ("SLM", "SL-M"),
        ("STOP_LOSS_LIMIT", "SL"),
        ("STOP_LOSS_MARKET", "SL-M"),
    ],
)
def test_ordinary_stop_read_retains_current_and_legacy_spellings(native, canonical) -> None:
    row = mapping.from_order({"exchange": "NSE", "segment": "CASH", "order_status": "OPEN", "order_type": native})
    assert row["pricetype"] == row["order_type"] == canonical


@pytest.mark.parametrize(
    "value", [0, -1, True, False, 1.5, "1.5", "NaN", "Infinity", "bad", None, "1_000", " 10", "１２"]
)
def test_ordinary_requests_reject_lossy_quantity_conversion(value) -> None:
    with pytest.raises(BrokerError):
        mapping.to_place_order_payload(_ordinary_request(quantity=value))
    with pytest.raises(BrokerError):
        mapping.to_modify_payload("G1", {"pricetype": "LIMIT", "quantity": value}, segment="CASH")


@pytest.mark.parametrize("value", [0, -1, True, "NaN", "Infinity", float("inf"), "bad", None, "1_000", " 10", "１２"])
@pytest.mark.parametrize(
    ("kind", "field"), [("LIMIT", "price"), ("SL", "price"), ("SL", "trigger_price"), ("SL-M", "trigger_price")]
)
def test_ordinary_requests_reject_invalid_applicable_decimals(kind, field, value) -> None:
    with pytest.raises(BrokerError):
        mapping.to_place_order_payload(_ordinary_request(pricetype=kind, **{field: value}))
    with pytest.raises(BrokerError):
        mapping.to_modify_payload("G1", {"pricetype": kind, field: value}, segment="CASH")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("exchange", "OTHER"),
        ("exchange", ""),
        ("exchange", None),
        ("product", "OTHER"),
        ("product", ""),
        ("action", "HOLD"),
        ("action", ""),
        ("pricetype", ""),
        ("validity", "GTC"),
        ("validity", ""),
        ("symbol", ""),
        ("symbol", " TCS"),
        ("symbol", "TCS\n"),
    ],
)
def test_ordinary_requests_refuse_invalid_required_identity_and_enums(field, value) -> None:
    with pytest.raises(BrokerError):
        mapping.to_place_order_payload(_ordinary_request(**{field: value}))


@pytest.mark.parametrize(
    "reference", ["Flint", "", "A" * 21, "a-b-c-d12", "abcdefgh_1", "abcdefgh 1", "abcdefgh\n", "äbcdefgh"]
)
def test_ordinary_reference_is_required_and_never_repaired(reference) -> None:
    with pytest.raises(BrokerError):
        mapping.to_place_order_payload(_ordinary_request(strategy=reference))


@pytest.mark.parametrize("reference", ["Abcdef12", "abc-def-12", "A" * 20])
def test_ordinary_reference_and_exact_large_quantity_survive(reference) -> None:
    payload = mapping.to_place_order_payload(_ordinary_request(quantity="9007199254740993", strategy=reference))
    assert payload["quantity"] == 9007199254740993
    assert payload["order_reference_id"] == reference


@pytest.mark.parametrize(
    "changes",
    [
        {"quantity": 10},
        {"price": 100},
        {"pricetype": "LIMIT", "order_type": "MARKET"},
        {"pricetype": "LIMIT", "quantity": 10, "qty": 11},
        {"pricetype": "LIMIT", "price": 100, "limit_price": 101},
        {"pricetype": "LIMIT", "trailing_jump": "1"},
        {"pricetype": "LIMIT", "unknown": 1},
    ],
)
def test_ordinary_modify_requires_type_and_refuses_conflicting_or_unknown_edits(changes) -> None:
    with pytest.raises(BrokerError):
        mapping.to_modify_payload("G1", changes, segment="CASH")


def test_ordinary_modify_keeps_valid_aliases_context_and_unsupported_disclosure_off_wire() -> None:
    payload = mapping.to_modify_payload(
        "G1",
        {
            "pricetype": "SL",
            "order_type": "STOP_LOSS_LIMIT",
            "quantity": "9007199254740993",
            "qty": 9007199254740993,
            "price": "100.00",
            "limit_price": "1e2",
            "trigger_price": "99.50",
            "exchange": "NFO",
            "symbol": "TCS",
            "action": "BUY",
            "product": "NRML",
            "validity": "DAY",
            "strategy": "Flint",
            "disclosed_quantity": 25,
        },
        segment="FNO",
    )
    assert payload == {
        "groww_order_id": "G1",
        "segment": "FNO",
        "order_type": "SL",
        "quantity": 9007199254740993,
        "price": 100.0,
        "trigger_price": 99.5,
    }


@pytest.mark.parametrize("segment", [None, "OTHER", "cash", "FNO/path"])
def test_ordinary_modify_and_cancel_require_valid_native_segment(segment) -> None:
    with pytest.raises(BrokerError):
        mapping.to_modify_payload("G1", {"pricetype": "LIMIT"}, segment=segment)
    with pytest.raises(BrokerError):
        mapping.to_cancel_payload("G1", segment=segment)


@pytest.mark.parametrize("identifier", [None, True, "", " id", "id/path", "id?x", "id%2fpath", "ümlaut", ".."])
def test_ordinary_mutations_refuse_unsafe_or_non_string_ids(identifier) -> None:
    with pytest.raises(BrokerError):
        mapping.to_modify_payload(identifier, {"pricetype": "LIMIT"}, segment="CASH")
    with pytest.raises(BrokerError):
        mapping.to_cancel_payload(identifier, segment="CASH")
