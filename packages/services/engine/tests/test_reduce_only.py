"""Reduce-only classification. The place pipeline decides; a client flag is not an input."""

from __future__ import annotations

import pytest

from flinttrade_engine.reduce_only import (
    _order_is_open,
    classify_reduce_only,
    exit_orders_unreadable_message,
    own_exit_already_pending,
    reset_reduce_only_for_tests,
)


@pytest.mark.unit
@pytest.mark.parametrize("status", [
    "CANCEL_PENDING",
    "CANCEL_REQUESTED",
    "CANCEL PENDING",
    "PENDING_CANCEL",
    "REJECT_PENDING",
    "COMPLETE_PENDING",
    "NOT_CANCELLED",
    "",
    "   ",
    "UNFAMILIAR_STATUS",
    " cancel_pending ",
])
def test_pending_and_unknown_status_remain_executable(status: str) -> None:
    assert _order_is_open({"status": status}) is True


@pytest.mark.unit
@pytest.mark.parametrize("status", [
    "COMPLETE", "COMPLETED", "FILLED", "CANCELLED", "CANCELED", "REJECTED", "TRADED", "EXPIRED",
])
@pytest.mark.parametrize("field", ["status", "order_status", "orderStatus"])
def test_only_exact_terminal_statuses_are_closed(status: str, field: str) -> None:
    assert _order_is_open({field: status}) is False
    assert _order_is_open({field: f" {status.lower()} "}) is False


def _long() -> dict[str, object]:
    return {"symbol": "INFY", "exchange": "NSE", "product": "MIS", "net_qty": 10}


def _decision(**overrides: object):
    fields = {
        "symbol": "INFY",
        "exchange": "NSE",
        "product": "MIS",
        "action": "SELL",
        "quantity": 10,
        "positions": [_long()],
        "our_orders": [],
        "broker_orders": [],
        "live": False,
    }
    fields.update(overrides)
    return classify_reduce_only(**fields)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _clear_reservations() -> None:
    reset_reduce_only_for_tests()
    yield
    reset_reduce_only_for_tests()


@pytest.mark.unit
def test_same_contract_opposite_side_within_the_open_quantity_qualifies() -> None:
    decision = _decision(quantity=10)
    assert decision.qualifies is True
    assert decision.open_quantity == 10
    assert decision.cap == 10
    short = _decision(
        action="BUY",
        quantity=4,
        positions=[{"symbol": "INFY", "exchange": "NSE", "product": "MIS", "net_qty": -4}],
    )
    assert short.qualifies is True
    assert short.cap == 4


@pytest.mark.unit
def test_our_unfilled_opposite_order_reduces_the_cap() -> None:
    decision = _decision(
        quantity=7,
        our_orders=[{
            "symbol": "INFY",
            "exchange": "NSE",
            "product": "MIS",
            "action": "SELL",
            "quantity": 4,
            "filled_qty": 0,
            "status": "PENDING",
            "order_id": "ours-1",
        }],
    )
    assert decision.qualifies is False
    assert decision.pending_exits == 4
    assert decision.cap == 6
    inside = _decision(
        quantity=6,
        our_orders=[{
            "symbol": "INFY",
            "exchange": "NSE",
            "product": "MIS",
            "action": "SELL",
            "quantity": 4,
            "status": "PENDING",
            "order_id": "ours-1",
        }],
    )
    assert inside.qualifies is True


@pytest.mark.unit
def test_adding_or_flipping_does_not_qualify() -> None:
    assert _decision(action="BUY", quantity=1).qualifies is False
    assert _decision(quantity=11).qualifies is False
    other = _decision(symbol="TCS", quantity=1)
    assert other.qualifies is False


def _our_sell(quantity: int = 4) -> dict[str, object]:
    return {
        "symbol": "INFY",
        "exchange": "NSE",
        "product": "MIS",
        "action": "SELL",
        "quantity": quantity,
        "filled_qty": 0,
        "status": "PENDING",
        "order_id": "ours-1",
    }


@pytest.mark.unit
@pytest.mark.parametrize(("position_quantity", "exit_action"), [(10, "SELL"), (-10, "BUY")])
def test_cancel_pending_exit_retains_pending_quantity(position_quantity: int, exit_action: str) -> None:
    position = {**_long(), "net_qty": position_quantity}
    exit_order = {**_our_sell(), "action": exit_action, "status": "CANCEL_PENDING"}
    decision = _decision(action=exit_action, quantity=7, positions=[position], our_orders=[exit_order])
    assert decision.qualifies is False
    assert decision.pending_exits == 4
    assert decision.cap == 6
    assert own_exit_already_pending(
        symbol="INFY",
        exchange="NSE",
        product="MIS",
        action=exit_action,
        positions=[position],
        our_orders=[exit_order],
    ) is True


@pytest.mark.unit
def test_live_broker_open_exit_reduces_the_cap_and_an_unreadable_book_stays_capped() -> None:
    broker_exit = {
        "symbol": "INFY",
        "exchange": "NSE",
        "product": "MIS",
        "action": "SELL",
        "quantity": 4,
        "status": "OPEN",
        "order_id": "broker-1",
    }
    reduced = _decision(quantity=7, live=True, broker_orders=[broker_exit])
    assert reduced.qualifies is False
    assert reduced.pending_exits == 4
    assert reduced.cap == 6
    allowed = _decision(quantity=6, live=True, broker_orders=[broker_exit])
    assert allowed.qualifies is True

    unreadable = _decision(quantity=10, live=True, broker_orders=None)
    assert unreadable.qualifies is False
    assert unreadable.cap == 0

    capped = _decision(quantity=6, live=True, broker_orders=None, our_orders=[_our_sell()])
    assert capped.qualifies is False
    assert capped.cap == 0
    over = _decision(quantity=7, live=True, broker_orders=None, our_orders=[_our_sell()])
    assert over.qualifies is False
    assert over.cap == 0

    duplicate = _decision(
        quantity=6,
        live=True,
        our_orders=[dict(broker_exit)],
        broker_orders=[broker_exit],
    )
    assert duplicate.pending_exits == 4
    assert duplicate.qualifies is True


@pytest.mark.unit
@pytest.mark.parametrize("status", ["COMPLETE", "CANCELLED", "REJECTED", "EXPIRED"])
def test_partial_fill_is_not_subtracted_from_position_twice(status: str) -> None:
    position = {**_long(), "net_qty": 60}
    original = {**_our_sell(100), "order_id": "original", "filled_qty": 40, "status": status}
    no_other_exit = _decision(quantity=60, positions=[position], our_orders=[original])
    assert no_other_exit.qualifies is True
    assert no_other_exit.open_quantity == 60
    assert no_other_exit.pending_exits == 0
    assert no_other_exit.cap == 60

    for pending_status in ("OPEN", "CANCEL_PENDING"):
        other_exit = {**_our_sell(30), "order_id": "other-exit", "filled_qty": 10, "status": pending_status}
        capped = _decision(quantity=40, positions=[position], our_orders=[original, other_exit])
        assert capped.qualifies is True
        assert capped.pending_exits == 20
        assert capped.cap == 40
        over = _decision(quantity=41, positions=[position], our_orders=[original, other_exit])
        assert over.qualifies is False
        assert over.cap == 40


@pytest.mark.unit
@pytest.mark.parametrize("source", ["our_orders", "broker_orders"])
@pytest.mark.parametrize("changes", [
    {"quantity": None},
    {"quantity": ""},
    {"quantity": -1},
    {"quantity": True},
    {"quantity": float("nan")},
    {"quantity": float("inf")},
    {"quantity": -float("inf")},
    {"quantity": 1.5},
    {"quantity": "1.5"},
    {"quantity": "1.0000000000000000001"},
    {"quantity": "invalid"},
    {"qty": 3},
    {"qty": None},
    {"filled_qty": None},
    {"filled_qty": ""},
    {"filled_qty": -1},
    {"filled_qty": True},
    {"filled_qty": float("nan")},
    {"filled_qty": float("inf")},
    {"filled_qty": 0.5},
    {"filled_qty": "0.0000000000000000001"},
    {"filled_qty": 5},
    {"filled_quantity": 1},
    {"filledQty": 1},
    {"tradedQty": 1},
    {"filledQty": None},
    {"order_id": None},
    {"order_id": "   "},
    {"orderid": "different-id"},
])
def test_ambiguous_quantity_evidence_refuses(source: str, changes: dict[str, object]) -> None:
    order = {**_our_sell(), **changes}
    decision = _decision(quantity=1, live=True, **{source: [order]})
    assert decision.qualifies is False
    assert decision.cap == 0


@pytest.mark.unit
@pytest.mark.parametrize("missing_field", ["quantity", "order_id"])
def test_missing_exit_quantity_or_identity_refuses(missing_field: str) -> None:
    order = _our_sell()
    del order[missing_field]
    decision = _decision(quantity=1, our_orders=[order])
    assert decision.qualifies is False
    assert decision.cap == 0


@pytest.mark.unit
@pytest.mark.parametrize("changes", [
    {"quantity": 5},
    {"filled_qty": 1},
    {"status": "OPEN"},
    {"status": "COMPLETE"},
    {"action": "BUY"},
    {"symbol": "TCS"},
    {"product": "CNC"},
    {"exchange": "BSE"},
])
def test_conflicting_copies_of_one_exit_id_refuse(changes: dict[str, object]) -> None:
    decision = _decision(
        quantity=1,
        live=True,
        our_orders=[_our_sell()],
        broker_orders=[{**_our_sell(), **changes}],
    )
    assert decision.qualifies is False
    assert decision.cap == 0


@pytest.mark.unit
@pytest.mark.parametrize("secondary_id", ["orderid", "orderId", "broker_order_id"])
@pytest.mark.parametrize("terminal_source", ["our_orders", "broker_orders"])
def test_terminal_identity_alias_cannot_hide_a_conflicting_live_copy(
    secondary_id: str, terminal_source: str,
) -> None:
    live_exit = {**_our_sell(), "order_id": "A"}
    terminal_exit = {
        **_our_sell(8), "order_id": "B", secondary_id: "A", "filled_qty": 8, "status": "COMPLETE",
    }
    live_source = "broker_orders" if terminal_source == "our_orders" else "our_orders"
    decision = _decision(quantity=6, live=True, **{live_source: [live_exit], terminal_source: [terminal_exit]})
    assert decision.qualifies is False
    assert decision.cap == 0


@pytest.mark.unit
def test_a_secondary_identity_link_cannot_hide_a_conflicting_contract_copy() -> None:
    live_exit = {**_our_sell(), "order_id": "A"}
    conflicting_copy = {
        **_our_sell(8), "symbol": "TCS", "order_id": "B", "orderId": "A",
        "filled_qty": 8, "status": "COMPLETE",
    }
    decision = _decision(quantity=6, live=True, our_orders=[live_exit], broker_orders=[conflicting_copy])
    assert decision.qualifies is False
    assert decision.cap == 0


@pytest.mark.unit
def test_truly_unmatched_identity_conflicts_do_not_expand_validation_scope() -> None:
    live_exit = {**_our_sell(), "order_id": "A"}
    unrelated = {
        **_our_sell(), "symbol": "TCS", "quantity": None, "order_id": "B", "orderId": "C",
    }
    decision = _decision(quantity=6, live=True, our_orders=[live_exit], broker_orders=[unrelated])
    assert decision.qualifies is True
    assert decision.pending_exits == 4
    assert decision.cap == 6


@pytest.mark.unit
def test_a_terminal_history_row_with_no_identity_remains_outside_pending_quantity() -> None:
    terminal = {**_our_sell(8), "order_id": None, "filled_qty": 8, "status": "COMPLETE"}
    decision = _decision(quantity=6, our_orders=[_our_sell(), terminal])
    assert decision.qualifies is True
    assert decision.pending_exits == 4
    assert decision.cap == 6


@pytest.mark.unit
@pytest.mark.parametrize("changes", [
    {"net_qty": None},
    {"net_qty": ""},
    {"net_qty": True},
    {"net_qty": float("nan")},
    {"net_qty": float("inf")},
    {"net_qty": 10.5},
    {"net_qty": "10.0000000000000000001"},
    {"netQty": 9},
    {"net_quantity": 9},
    {"quantity": 9},
    {"qty": 9},
    {"qty": None},
])
def test_ambiguous_matching_position_quantity_refuses(changes: dict[str, object]) -> None:
    decision = _decision(quantity=1, positions=[{**_long(), **changes}])
    assert decision.qualifies is False
    assert decision.cap == 0


@pytest.mark.unit
@pytest.mark.parametrize("other_quantity", [10, 9, -10])
def test_multiple_matching_position_rows_refuse(other_quantity: int) -> None:
    decision = _decision(quantity=1, positions=[_long(), {**_long(), "net_qty": other_quantity}])
    assert decision.qualifies is False
    assert decision.cap == 0


@pytest.mark.unit
@pytest.mark.parametrize("source", ["our_orders", "broker_orders"])
@pytest.mark.parametrize("changes", [
    {"trading_symbol": "TCS"},
    {"symbol": "TCS", "tradingsymbol": "INFY"},
    {"transaction_type": "BUY"},
    {"action": "BUY", "transaction_type": "SELL"},
    {"status": "COMPLETE", "order_status": "OPEN"},
    {"status": "OPEN", "orderStatus": "COMPLETE"},
    {"status": "COMPLETE", "orderStatus": "CANCEL_PENDING"},
])
def test_conflicting_single_exit_text_aliases_refuse(source: str, changes: dict[str, object]) -> None:
    decision = _decision(quantity=1, live=True, **{source: [{**_our_sell(), **changes}]})
    assert decision.qualifies is False
    assert decision.cap == 0


@pytest.mark.unit
@pytest.mark.parametrize("changes", [
    {"trading_symbol": "TCS"},
    {"symbol": "TCS", "tradingsymbol": "INFY"},
    {"side": "BUY", "action": "SELL"},
    {"side": "SELL", "transaction_type": "BUY"},
])
def test_conflicting_single_position_identity_or_side_aliases_refuse(changes: dict[str, object]) -> None:
    decision = _decision(quantity=1, positions=[{**_long(), **changes}])
    assert decision.qualifies is False
    assert decision.cap == 0


@pytest.mark.unit
def test_an_earlier_unmatched_symbol_alias_cannot_hide_an_ambiguous_position() -> None:
    shadowed = {**_long(), "symbol": "TCS", "trading_symbol": "INFY", "net_qty": 9}
    decision = _decision(quantity=1, positions=[_long(), shadowed])
    assert decision.qualifies is False
    assert decision.cap == 0


@pytest.mark.unit
def test_consistent_normalised_text_aliases_remain_valid() -> None:
    position = {**_long(), "trading_symbol": " infy ", "side": "BUY", "transaction_type": " buy "}
    order = {
        **_our_sell(), "tradingsymbol": " infy ", "transaction_type": " sell ",
        "order_status": " pending ", "orderStatus": "PENDING",
    }
    decision = _decision(quantity=6, positions=[position], our_orders=[order])
    assert decision.qualifies is True
    assert decision.pending_exits == 4
    assert decision.cap == 6


@pytest.mark.unit
@pytest.mark.parametrize("extra_pending", [
    -1, True, False, None, "2", 2.0, 0.5, float("nan"), float("inf"),
])
def test_invalid_extra_pending_refuses(extra_pending: object) -> None:
    decision = _decision(quantity=1, extra_pending=extra_pending)
    assert decision.qualifies is False
    assert decision.cap == 0


@pytest.mark.unit
def test_valid_quantity_aliases_and_identical_exit_copies_count_once() -> None:
    position = {**_long(), "net_qty": "10", "netQty": 10.0, "net_quantity": 10, "quantity": 10, "qty": 10}
    order = {
        **_our_sell(),
        "quantity": "4",
        "qty": 4.0,
        "filled_qty": "1",
        "filled_quantity": 1.0,
        "filledQty": 1,
        "tradedQty": 1,
        "orderid": "ours-1",
    }
    decision = _decision(
        quantity=5, positions=[position], our_orders=[order, dict(order)],
        broker_orders=[dict(order)], live=True, extra_pending=2,
    )
    assert decision.qualifies is True
    assert decision.open_quantity == 10
    assert decision.pending_exits == 5
    assert decision.cap == 5


@pytest.mark.unit
def test_practice_does_not_require_a_broker_book_or_validate_unrelated_rows() -> None:
    decision = _decision(
        quantity=6, broker_orders=None, our_orders=[_our_sell()],
        positions=[_long(), {"symbol": "TCS", "exchange": "NSE", "net_qty": None}],
    )
    assert decision.qualifies is True
    assert decision.cap == 6
    unrelated = _decision(quantity=10, our_orders=[{**_our_sell(), "symbol": "TCS", "quantity": None}])
    assert unrelated.qualifies is True
    assert unrelated.cap == 10


@pytest.mark.unit
def test_own_pending_exit_blocks_a_second_exit_and_a_broker_exit_does_not() -> None:
    assert own_exit_already_pending(
        symbol="INFY",
        exchange="NSE",
        product="MIS",
        action="SELL",
        positions=[_long()],
        our_orders=[_our_sell()],
    ) is True
    assert own_exit_already_pending(
        symbol="INFY",
        exchange="NSE",
        product="MIS",
        action="SELL",
        positions=[_long()],
        our_orders=[],
    ) is False
    assert own_exit_already_pending(
        symbol="INFY",
        exchange="NSE",
        product="MIS",
        action="BUY",
        positions=[_long()],
        our_orders=[_our_sell()],
    ) is False


@pytest.mark.unit
@pytest.mark.parametrize("contract, label", [("INFY", "INFY"), (" INFY ", "INFY"), ("", "this contract")])
def test_unreadable_orders_copy_requires_reconciliation(contract: str, label: str) -> None:
    assert exit_orders_unreadable_message(contract) == (
        f"Not placed. Broker orders for {label} are unavailable. Reconcile them before another exit."
    )


@pytest.mark.unit
@pytest.mark.parametrize("net_quantity,exit_action", [(100, "SELL"), (-100, "BUY")])
@pytest.mark.parametrize("source", ["our_orders", "broker_orders"])
@pytest.mark.parametrize("side_fields", [
    {}, {"action": None}, {"action": ""}, {"action": "   "}, {"action": "UNRECOGNISED"},
    {"transaction_type": ""}, {"transaction_type": "UNKNOWN"},
])
def test_matching_executable_order_with_ambiguous_side_refuses(net_quantity, exit_action, source, side_fields):
    order = {
        "symbol": "INFY", "exchange": "NSE", "product": "MIS",
        "order_id": "ambiguous-side", "status": "OPEN", "quantity": 100,
        **side_fields,
    }
    decision = _decision(
        quantity=100, action=exit_action, positions=[{**_long(), "net_qty": net_quantity}],
        live=True, **{source: [order]},
    )
    assert decision.qualifies is False
    assert decision.cap == 0


@pytest.mark.unit
@pytest.mark.parametrize("net_quantity,exit_action,entry_action", [(100, "SELL", "BUY"), (-100, "BUY", "SELL")])
@pytest.mark.parametrize("source", ["our_orders", "broker_orders"])
@pytest.mark.parametrize("unrelated_fields", [
    {"symbol": "TCS", "action": "UNKNOWN"},
    {"exchange": "BSE", "action": ""},
    {"product": "CNC"},
    {"action": "ENTRY_ACTION"},
])
def test_genuinely_unrelated_malformed_order_is_excluded_from_side_validation(
    net_quantity, exit_action, entry_action, source, unrelated_fields,
):
    fields = dict(unrelated_fields)
    if fields.get("action") == "ENTRY_ACTION":
        fields["action"] = entry_action
    order = {
        "symbol": "INFY", "exchange": "NSE", "product": "MIS",
        "order_id": "unrelated-side", "status": "OPEN", "quantity": None,
        **fields,
    }
    decision = _decision(
        quantity=100, action=exit_action, positions=[{**_long(), "net_qty": net_quantity}],
        live=True, **{source: [order]},
    )
    assert decision.qualifies is True
    assert decision.cap == 100


@pytest.mark.unit
@pytest.mark.parametrize("net_quantity,exit_action", [(100, "SELL"), (-100, "BUY")])
@pytest.mark.parametrize("source", ["our_orders", "broker_orders"])
def test_terminal_alias_cannot_hide_an_executable_order_with_missing_side(net_quantity, exit_action, source):
    order = {
        "symbol": "INFY", "exchange": "NSE", "product": "MIS", "quantity": 100,
        "order_id": "ambiguous-side", "status": "CANCELLED", "order_status": "OPEN",
    }
    decision = _decision(
        quantity=100, action=exit_action, positions=[{**_long(), "net_qty": net_quantity}],
        live=True, **{source: [order]},
    )
    assert decision.qualifies is False
    assert decision.cap == 0
