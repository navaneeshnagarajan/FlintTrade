"""Pure snapshot advice; event ordering and durable ingestion belong to Stage D."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, localcontext
from itertools import permutations

import pytest

from flinttrade_engine.exit_evidence import (
    ExitAttempt,
    ExitDecision,
    ExitEvidence,
    ExitScope,
    ProtectionLeg,
    ProtectionResource,
    decide_exit,
)

pytestmark = pytest.mark.unit
D = Decimal
SCOPE = ExitScope("PAPER", "example", "account-a", "instrument-a", "", "NSE", "MIS")


def snapshot(**changes: object) -> ExitEvidence:
    values = {
        "scope": SCOPE,
        "original_sign": 1,
        "current_signed_quantity": D("100"),
        "authorised_remaining": D("100"),
        "attempts": (),
        "protection_resources": (),
        "unmatched_reservations": (),
        "books_complete": True,
        "coherence_verified": True,
        "freshness_verified": True,
        "scope_verified": True,
    }
    return ExitEvidence(**(values | changes))  # type: ignore[arg-type]


def attempt(state: str = "WORKING", remaining: str = "40", **changes: object) -> ExitAttempt:
    values = {
        "attempt_id": "attempt-a",
        "broker_order_id": "order-a",
        "state": state,
        "remaining": D(remaining),
        "reservation_id": None,
        "parent_resource_id": None,
    }
    return ExitAttempt(**(values | changes))  # type: ignore[arg-type]


def leg(state: str = "ARMED", remaining: str = "40", **changes: object) -> ProtectionLeg:
    values = {
        "leg_id": "leg-a",
        "state": state,
        "remaining": D(remaining),
        "child_ids": (),
        "children_complete": True,
    }
    return ProtectionLeg(**(values | changes))  # type: ignore[arg-type]


def resource(*legs: ProtectionLeg, resource_id: str = "resource-a") -> ProtectionResource:
    return ProtectionResource(resource_id, legs or (leg(),))


def decide(evidence: ExitEvidence, **changes: bool) -> ExitDecision:
    flags = {
        "explicit_close": True,
        "protection_authorised": False,
        "market_supported": True,
        "preconditions_changed": True,
    }
    return decide_exit(evidence, **(flags | changes))


def assert_reconcile(evidence: ExitEvidence) -> None:
    decision = decide(evidence)
    assert decision.cap == D(0)
    assert decision.outcome == "UNKNOWN"
    assert decision.next_action == "RECONCILE"
    assert decision.reason


def test_contracts_are_frozen_and_decision_is_repeatable() -> None:
    evidence = snapshot()
    objects = (SCOPE, attempt(), leg(), resource(), evidence, decide(evidence))
    for value in objects:
        field = next(iter(value.__dataclass_fields__))
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, None)
    assert decide(evidence) == decide(evidence)
    assert evidence == snapshot()


def test_initial_explicit_close_can_proceed_without_changed_preconditions() -> None:
    result = decide(snapshot(), preconditions_changed=False)
    assert result.cap == D(100)
    assert result.outcome == "OPEN"
    assert result.next_action == "SUBMIT_MARKET"


def test_initial_protection_authorisation_alone_does_not_start_a_close() -> None:
    result = decide(snapshot(), explicit_close=False, protection_authorised=True)
    assert result.next_action == "NONE"
    assert result.outcome == "OPEN"


def test_position_already_reflecting_fill_pins_cap_60_then_40() -> None:
    previous = attempt("CANCELLED", "60")
    evidence = snapshot(current_signed_quantity=D(60), attempts=(previous,))
    assert decide(evidence).cap == D(60)
    pending = attempt("PARTIALLY_FILLED", "20", attempt_id="attempt-b", broker_order_id="order-b")
    result = decide(replace(evidence, attempts=(previous, pending)))
    assert result.cap == D(40)
    assert result.next_action == "CANCEL_THEN_RECONCILE"


@pytest.mark.parametrize("state", ["FILLED", "CANCELLED", "REJECTED", "EXPIRED"])
def test_closed_requires_flat_and_no_executable_or_unknown_attempt(state: str) -> None:
    terminal = attempt(state, "0" if state == "FILLED" else "40")
    evidence = snapshot(current_signed_quantity=D(0), attempts=(terminal,))
    result = decide(evidence)
    assert (result.cap, result.outcome, result.next_action) == (D(0), "CLOSED", "NONE")
    for unresolved in (
        "REQUESTED",
        "SUBMITTING",
        "ACKNOWLEDGED",
        "WORKING",
        "PARTIALLY_FILLED",
        "MODIFY_PENDING",
        "CANCEL_PENDING",
        "UNKNOWN",
    ):
        pending = attempt(unresolved, "0", attempt_id="attempt-b", broker_order_id="order-b")
        result = decide(replace(evidence, attempts=(terminal, pending)))
        assert result.cap == D(0)
        assert result.outcome != "CLOSED"
        assert result.next_action != "SUBMIT_MARKET"


@pytest.mark.parametrize(
    "state",
    [
        "UNKNOWN",
        "SUBMITTING",
        "",
        "NOT_CANCELLED",
        "REJECT_PENDING",
        "COMPLETE_PENDING",
        "CANCEL_REQUESTED",
        "FILLED_LATER",
    ],
)
def test_unknown_never_replays(state: str) -> None:
    evidence = snapshot(attempts=(attempt(state),))
    assert_reconcile(evidence)


def test_cancel_ack_never_releases_quantity() -> None:
    evidence = snapshot(attempts=(attempt("CANCEL_PENDING", "40"),))
    result = decide(evidence)
    assert result.cap == D(60)
    assert result.next_action == "WAIT"
    assert result.outcome == "OPEN"
    # An absent order with its reservation still unresolved is not a cancellation proof.
    missing = snapshot(unmatched_reservations=(("reservation-a", D(40)),))
    result = decide(missing)
    assert result.cap == D(60)
    assert result.outcome == "UNKNOWN"
    assert result.next_action == "RECONCILE"


def test_reservation_transfer_counts_once() -> None:
    local = attempt(reservation_id="reservation-a")
    broker_alias = attempt(attempt_id="broker-observation")
    evidence = snapshot(attempts=(local, broker_alias), unmatched_reservations=(("reservation-a", D(100)),))
    result = decide(evidence)
    assert result.cap == D(60)
    assert result.next_action == "CANCEL_THEN_RECONCILE"
    terminal = replace(local, state="CANCELLED")
    result = decide(replace(evidence, attempts=(terminal,)))
    assert result.cap == D(100)
    assert result.next_action == "SUBMIT_MARKET"


def test_pre_ack_reservation_cannot_be_released_by_a_terminal_local_record() -> None:
    local = attempt("REJECTED", "0", broker_order_id=None, reservation_id="reservation-a")
    result = decide(snapshot(attempts=(local,), unmatched_reservations=(("reservation-a", D(40)),)))
    assert result.cap == D(60)
    assert result.outcome == "UNKNOWN"
    assert result.next_action == "RECONCILE"


@pytest.mark.parametrize("state", ["REQUESTED", "SUBMITTING"])
def test_pre_ack_attempt_retains_uncertainty_without_a_visible_reservation(state: str) -> None:
    result = decide(snapshot(attempts=(attempt(state, broker_order_id=None),)))
    assert result.outcome != "CLOSED"
    assert result.next_action in {"WAIT", "RECONCILE"}


def test_two_armed_oco_legs_of_40_leave_cap_20() -> None:
    oco = resource(leg(), leg(leg_id="leg-b"))
    result = decide(snapshot(protection_resources=(oco,)))
    assert result.cap == D(20)
    assert result.next_action == "CANCEL_THEN_RECONCILE"


def test_oco_children_remain_independently_executable() -> None:
    oco = resource(leg("TRIGGERED", child_ids=("order-a",)), leg("TRIGGERED", child_ids=("order-b",), leg_id="leg-b"))
    children = (
        attempt(parent_resource_id="resource-a"),
        attempt(attempt_id="attempt-b", broker_order_id="order-b", parent_resource_id="resource-a"),
    )
    evidence = snapshot(attempts=children, protection_resources=(oco,))
    assert decide(evidence).cap == D(20)
    assert decide(evidence).next_action == "CANCEL_THEN_RECONCILE"
    first_filled = replace(children[0], state="FILLED", remaining=D(0))
    partial = replace(evidence, current_signed_quantity=D(60), attempts=(first_filled, children[1]))
    assert decide(partial).cap == D(20)
    assert decide(partial).outcome != "CLOSED"


@pytest.mark.parametrize("state", ["CANCELLED", "REJECTED", "EXPIRED", "TRIGGERED"])
def test_terminal_trigger_is_not_a_terminal_child(state: str) -> None:
    parent = resource(leg(state, "0", child_ids=("order-a",)))
    child = attempt("WORKING", "20", parent_resource_id="resource-a")
    evidence = snapshot(current_signed_quantity=D(60), attempts=(child,), protection_resources=(parent,))
    result = decide(evidence)
    assert result.cap == D(40)
    assert result.next_action == "CANCEL_THEN_RECONCILE"
    assert decide(replace(evidence, current_signed_quantity=D(0))).outcome != "CLOSED"
    resolved = replace(child, state="FILLED", remaining=D(0))
    assert decide(replace(evidence, current_signed_quantity=D(0), attempts=(resolved,))).outcome == "CLOSED"


def test_trigger_transfers_only_complete_known_children() -> None:
    child = attempt("PARTIALLY_FILLED", "20", parent_resource_id="resource-a")
    parent = resource(leg("TRIGGERED", "40", child_ids=("order-a",)))
    evidence = snapshot(attempts=(child,), protection_resources=(parent,))
    assert decide(evidence).cap == D(80)
    incomplete = resource(replace(parent.legs[0], children_complete=False))
    assert_reconcile(replace(evidence, protection_resources=(incomplete,)))
    assert_reconcile(replace(evidence, attempts=()))
    assert_reconcile(replace(evidence, protection_resources=(resource(leg("TRIGGERED")),)))


def test_cancellation_pending_leg_keeps_its_own_executable_quantity() -> None:
    child = attempt("WORKING", "20", parent_resource_id="resource-a")
    parent = resource(leg("CANCEL_PENDING", "40", child_ids=("order-a",)))
    result = decide(snapshot(attempts=(child,), protection_resources=(parent,)))
    assert result.cap == D(40)
    assert result.next_action == "WAIT"


@pytest.mark.parametrize(
    "change",
    [
        {"parent_resource_id": None},
        {"parent_resource_id": "resource-other"},
        {"broker_order_id": "order-other"},
        {"broker_order_id": None},
    ],
)
def test_child_ids_are_broker_ids_with_reciprocal_resource_ownership(change: dict[str, object]) -> None:
    child = attempt(parent_resource_id="resource-a")
    parent = resource(leg("TRIGGERED", child_ids=("order-a",)))
    assert_reconcile(snapshot(attempts=(replace(child, **change),), protection_resources=(parent,)))


def test_orphan_child_and_shared_child_between_legs_require_reconciliation() -> None:
    child = attempt(parent_resource_id="resource-a")
    assert_reconcile(snapshot(attempts=(child,)))
    parents = resource(
        leg("TRIGGERED", child_ids=("order-a",)), leg("TRIGGERED", leg_id="leg-b", child_ids=("order-a",))
    )
    assert_reconcile(snapshot(attempts=(child,), protection_resources=(parents,)))


@pytest.mark.parametrize("state", ["ARMED", "CANCEL_PENDING"])
def test_flat_with_armed_or_cancel_pending_resource_remains_hazardous(state: str) -> None:
    result = decide(snapshot(current_signed_quantity=D(0), protection_resources=(resource(leg(state)),)))
    assert result.cap == D(0)
    assert result.outcome != "CLOSED"
    assert result.next_action in {"WAIT", "CANCEL_THEN_RECONCILE"}


def test_flat_with_unmatched_reservation_or_unresolved_child_is_not_closed() -> None:
    result = decide(snapshot(current_signed_quantity=D(0), unmatched_reservations=(("reservation-a", D(0)),)))
    assert result.outcome == "UNKNOWN"
    assert result.next_action == "RECONCILE"
    assert_reconcile(snapshot(current_signed_quantity=D(0), protection_resources=(resource(leg("TRIGGERED")),)))


@pytest.mark.parametrize("sign,quantity", [(1, "-10"), (-1, "10")])
def test_external_reversal_does_not_authorise_new_direction(sign: int, quantity: str) -> None:
    evidence = snapshot(original_sign=sign, current_signed_quantity=D(quantity))
    result = decide(evidence)
    assert result.cap == D(0)
    assert result.outcome == "FAILED"
    assert result.next_action == "NONE"
    assert "revers" in result.reason.lower()
    assert evidence.original_sign == sign


def test_short_exposure_retains_original_sign_and_authorised_cap() -> None:
    evidence = snapshot(original_sign=-1, current_signed_quantity=D(-60), authorised_remaining=D(35))
    result = decide(evidence)
    assert result.cap == D(35)
    assert result.next_action == "SUBMIT_MARKET"
    assert decide(replace(evidence, current_signed_quantity=D(0))).outcome == "CLOSED"
    assert evidence.original_sign == -1


def test_exhausted_authorisation_and_over_reserved_exposure_never_submit() -> None:
    result = decide(snapshot(authorised_remaining=D(0)))
    assert result.cap == D(0)
    assert result.outcome == "OPEN"
    assert result.next_action == "NONE"
    result = decide(snapshot(attempts=(attempt(remaining="120"),)))
    assert result.cap == D(0)
    assert result.next_action == "CANCEL_THEN_RECONCILE"


@pytest.mark.parametrize("state", ["CANCELLED", "REJECTED", "EXPIRED"])
def test_recovery_waits_for_definite_failure_and_changed_preconditions(state: str) -> None:
    evidence = snapshot(current_signed_quantity=D(60), attempts=(attempt(state, "60"),))
    unchanged = decide(evidence, preconditions_changed=False)
    assert unchanged.outcome == "FAILED"
    assert unchanged.next_action == "NONE"
    changed = decide(evidence)
    assert changed.cap == D(60)
    assert changed.next_action == "SUBMIT_MARKET"
    assert decide(evidence, market_supported=False).next_action == "REQUEST_ALTERNATIVE"


@pytest.mark.parametrize(
    "state",
    [
        "REQUESTED",
        "ACKNOWLEDGED",
        "WORKING",
        "PARTIALLY_FILLED",
        "MODIFY_PENDING",
        "CANCEL_PENDING",
        "SUBMITTING",
        "UNKNOWN",
    ],
)
def test_nonterminal_attempts_never_become_resubmission_opportunities(state: str) -> None:
    result = decide(snapshot(attempts=(attempt(state),)))
    assert result.next_action != "SUBMIT_MARKET"
    if state in {"REQUESTED", "MODIFY_PENDING", "CANCEL_PENDING"}:
        assert result.next_action == "WAIT"


def test_failed_stop_needs_authorised_policy() -> None:
    evidence = snapshot(protection_resources=(resource(leg("REJECTED")),))
    imported = decide(evidence, explicit_close=False, protection_authorised=False)
    assert imported.outcome == "FAILED"
    assert imported.next_action == "NONE"
    authorised = decide(evidence, explicit_close=False, protection_authorised=True)
    assert authorised.next_action == "SUBMIT_MARKET"
    unchanged = decide(evidence, explicit_close=False, protection_authorised=True, preconditions_changed=False)
    assert unchanged.next_action == "NONE"
    explicit = decide(evidence, explicit_close=True, protection_authorised=False)
    assert explicit.next_action == "SUBMIT_MARKET"


def test_authorised_protection_does_not_cancel_a_healthy_working_order() -> None:
    result = decide(snapshot(attempts=(attempt(),)), explicit_close=False, protection_authorised=True)
    assert result.next_action == "WAIT"


@pytest.mark.parametrize("gate", ["books_complete", "coherence_verified", "freshness_verified", "scope_verified"])
def test_missing_books_stale_mismatched_or_incoherent_evidence_blocks(gate: str) -> None:
    assert_reconcile(snapshot(**{gate: False}))
    assert_reconcile(snapshot(current_signed_quantity=D(0), **{gate: False}))


def test_timestamps_cannot_replace_explicit_coherence_verification() -> None:
    # This contract intentionally has no timestamp heuristic or readiness inference.
    evidence = snapshot(coherence_verified=False)
    assert "timestamp" not in evidence.__dataclass_fields__
    assert_reconcile(evidence)


@pytest.mark.parametrize("field", ["mode", "broker", "account_id", "instrument_id", "segment", "product"])
def test_scope_requires_nonblank_identity_fields(field: str) -> None:
    assert_reconcile(snapshot(scope=replace(SCOPE, **{field: " "})))


@pytest.mark.parametrize("sign", [0, 2, -2, True, D(1), "1"])
def test_invalid_original_sign_requires_reconciliation(sign: object) -> None:
    assert_reconcile(snapshot(original_sign=sign))


@pytest.mark.parametrize("bad", [D(-1), D("NaN"), D("sNaN"), D("Infinity"), D("-Infinity"), 1.0, 1, "1"])
@pytest.mark.parametrize("location", ["authorisation", "attempt", "leg", "reservation"])
def test_invalid_unsigned_quantities_require_reconciliation(bad: object, location: str) -> None:
    if location == "authorisation":
        evidence = snapshot(authorised_remaining=bad)
    elif location == "attempt":
        evidence = snapshot(attempts=(replace(attempt(), remaining=bad),))
    elif location == "leg":
        evidence = snapshot(protection_resources=(resource(replace(leg(), remaining=bad)),))
    else:
        evidence = snapshot(unmatched_reservations=(("reservation-a", bad),))
    assert_reconcile(evidence)


@pytest.mark.parametrize("bad", [D("NaN"), D("sNaN"), D("Infinity"), D("-Infinity"), 1.0, "1"])
def test_position_must_be_finite_decimal(bad: object) -> None:
    assert_reconcile(snapshot(current_signed_quantity=bad))


def test_quantities_are_exact_decimal_broker_units_independent_of_context() -> None:
    evidence = snapshot(
        current_signed_quantity=D("1.00000000000000000000000000001"),
        authorised_remaining=D("2"),
        attempts=(attempt(remaining="0.00000000000000000000000000001"),),
    )
    with localcontext() as context:
        context.prec = 5
        result = decide(evidence)
    assert result.cap == D(1)


def test_identical_attempt_and_broker_aliases_are_counted_once_in_any_order() -> None:
    local = attempt(reservation_id="reservation-a")
    alias = replace(local, attempt_id="alias")
    evidence = snapshot(attempts=(local, local, alias))
    decisions = {decide(replace(evidence, attempts=rows)) for rows in permutations(evidence.attempts)}
    assert len(decisions) == 1
    assert next(iter(decisions)).cap == D(60)


@pytest.mark.parametrize(
    "change",
    [
        {"state": "CANCELLED"},
        {"remaining": D(39)},
        {"broker_order_id": "order-other"},
        {"reservation_id": "reservation-other"},
        {"parent_resource_id": "resource-other"},
    ],
)
def test_conflicting_duplicate_attempt_id_requires_reconciliation(change: dict[str, object]) -> None:
    original = attempt()
    assert_reconcile(snapshot(attempts=(original, replace(original, **change))))


@pytest.mark.parametrize(
    "change",
    [
        {"state": "CANCELLED"},
        {"remaining": D(39)},
        {"reservation_id": "reservation-other"},
        {"parent_resource_id": "resource-other"},
    ],
)
def test_conflicting_broker_aliases_require_reconciliation(change: dict[str, object]) -> None:
    original = attempt(reservation_id="reservation-a", parent_resource_id="resource-a")
    alias = replace(original, attempt_id="alias", **change)
    assert_reconcile(snapshot(attempts=(original, alias)))


def test_one_reservation_cannot_transfer_to_two_distinct_broker_orders() -> None:
    first = attempt(reservation_id="reservation-a")
    second = replace(first, attempt_id="attempt-b", broker_order_id="order-b")
    assert_reconcile(snapshot(attempts=(first, second)))


def test_identical_unmatched_reservations_count_once_but_conflicts_block() -> None:
    reservation = ("reservation-a", D(40))
    result = decide(snapshot(unmatched_reservations=(reservation, reservation)))
    assert result.cap == D(60)
    assert result.next_action == "RECONCILE"
    assert_reconcile(snapshot(unmatched_reservations=(reservation, ("reservation-a", D(41)))))


@pytest.mark.parametrize("duplicate", [leg(), leg(remaining="41"), leg("CANCELLED")])
def test_duplicate_leg_identities_require_reconciliation(duplicate: ProtectionLeg) -> None:
    assert_reconcile(snapshot(protection_resources=(resource(leg(), duplicate),)))
    assert_reconcile(snapshot(protection_resources=(resource(), resource(duplicate, resource_id="resource-b"))))


def test_duplicate_resource_and_child_identities_require_reconciliation() -> None:
    assert_reconcile(snapshot(protection_resources=(resource(), resource())))
    repeated_child = resource(leg("TRIGGERED", child_ids=("order-a", "order-a")))
    child = attempt(parent_resource_id="resource-a")
    assert_reconcile(snapshot(attempts=(child,), protection_resources=(repeated_child,)))


@pytest.mark.parametrize("state", ["UNKNOWN", "", "NOT_CANCELLED", "REJECT_PENDING", "COMPLETE"])
def test_unknown_protection_status_never_releases_risk(state: str) -> None:
    assert_reconcile(snapshot(protection_resources=(resource(leg(state)),)))


def test_filled_attempt_with_unfilled_quantity_is_conflicting_snapshot_evidence() -> None:
    assert_reconcile(snapshot(attempts=(attempt("FILLED", "1"),)))


def test_armed_leg_with_existing_child_is_conflicting_snapshot_evidence() -> None:
    child = attempt(parent_resource_id="resource-a")
    parent = resource(leg("ARMED", child_ids=("order-a",)))
    assert_reconcile(snapshot(attempts=(child,), protection_resources=(parent,)))


def test_empty_resource_or_incomplete_child_book_requires_reconciliation() -> None:
    assert_reconcile(snapshot(protection_resources=(ProtectionResource("resource-a", ()),)))
    assert_reconcile(snapshot(protection_resources=(resource(leg("CANCELLED", children_complete=False)),)))


@pytest.mark.parametrize("state", ["ACKNOWLEDGED", "WORKING", "PARTIALLY_FILLED", "MODIFY_PENDING", "CANCEL_PENDING"])
def test_broker_active_state_without_broker_identity_requires_reconciliation(state: str) -> None:
    assert_reconcile(snapshot(attempts=(attempt(state, broker_order_id=None),)))


def test_requested_pre_ack_identity_does_not_transfer_or_release_reservation() -> None:
    local = attempt("REQUESTED", "0", reservation_id="reservation-a")
    result = decide(snapshot(attempts=(local,), unmatched_reservations=(("reservation-a", D(100)),)))
    assert result.cap == D(0)
    assert result.outcome == "UNKNOWN"
    assert result.next_action == "RECONCILE"


def test_filled_attempt_may_progress_confirmed_explicit_close_remainder() -> None:
    evidence = snapshot(current_signed_quantity=D(60), attempts=(attempt("FILLED", "0"),))
    result = decide(evidence, preconditions_changed=False)
    assert result.cap == D(60)
    assert result.next_action == "SUBMIT_MARKET"
    result = decide(evidence, explicit_close=False, protection_authorised=True, preconditions_changed=False)
    assert result.next_action == "NONE"


@pytest.mark.parametrize(
    ("authorised_remaining", "expected_action"),
    [(D(25), "SUBMIT_MARKET"), (D(0), "NONE")],
)
def test_filled_attempt_continuation_respects_remaining_authorisation(
    authorised_remaining: Decimal,
    expected_action: str,
) -> None:
    evidence = snapshot(
        current_signed_quantity=D(60),
        authorised_remaining=authorised_remaining,
        attempts=(attempt("FILLED", "0"),),
    )
    result = decide(evidence, preconditions_changed=False)
    assert result.cap == authorised_remaining
    assert result.outcome == "OPEN"
    assert result.next_action == expected_action


@pytest.mark.parametrize(
    "flag", ["explicit_close", "protection_authorised", "market_supported", "preconditions_changed"]
)
def test_truthy_values_are_not_decision_authorisation(flag: str) -> None:
    result = decide(snapshot(), **{flag: "yes"})  # type: ignore[arg-type]
    assert (result.cap, result.outcome, result.next_action) == (D(0), "UNKNOWN", "RECONCILE")


@pytest.mark.parametrize("field", ["attempt_id", "broker_order_id", "reservation_id", "parent_resource_id"])
def test_blank_attempt_identity_requires_reconciliation(field: str) -> None:
    assert_reconcile(snapshot(attempts=(replace(attempt(), **{field: " "}),)))


@pytest.mark.parametrize("state", ["FILLED", "CANCELLED", "REJECTED", "EXPIRED"])
def test_exact_normalised_terminal_states_are_supported(state: str) -> None:
    row = attempt(f" {state.lower()} ", "0" if state == "FILLED" else "40")
    assert decide(snapshot(current_signed_quantity=D(0), attempts=(row,))).outcome == "CLOSED"


def test_unmatched_reservation_is_retained_alongside_separate_working_order() -> None:
    result = decide(snapshot(attempts=(attempt(remaining="20"),), unmatched_reservations=(("reservation-a", D(40)),)))
    assert result.cap == D(40)
    assert result.next_action == "RECONCILE"


def test_reservation_transfer_does_not_hide_conflicting_duplicate_reservation_amounts() -> None:
    row = attempt("CANCELLED", reservation_id="reservation-a")
    assert_reconcile(
        snapshot(
            attempts=(row,),
            unmatched_reservations=(
                ("reservation-a", D(40)),
                ("reservation-a", D(41)),
            ),
        )
    )


@pytest.mark.parametrize("field", ["attempts", "protection_resources", "unmatched_reservations"])
def test_mutable_snapshot_containers_require_reconciliation(field: str) -> None:
    assert_reconcile(snapshot(**{field: []}))


def test_unverified_truthy_snapshot_flags_require_reconciliation() -> None:
    assert_reconcile(snapshot(scope_verified="yes"))
    assert_reconcile(snapshot(books_complete=1))
