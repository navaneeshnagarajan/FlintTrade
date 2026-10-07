"""Pure snapshot advice for one scoped, originally directed exit intent.

This module performs no I/O and has no production callers. Its verification
booleans are an explicit trust boundary for a future, independently validated
Stage D evidence source, not assertions of runtime write readiness. Advice does
not bypass safety gates or authorise a broker write.

All quantities are Decimal broker units. IDs belong to the enclosing ExitScope;
child_ids reference broker_order_id, with reciprocal parent_resource_id links.
The evidence source must prove account/instrument ownership, complete books and
coherence; timestamps alone cannot do so. This snapshot cannot establish event
ordering, cumulative-fill monotonicity, durable recovery or exactly-once writes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import (
    MAX_EMAX,
    MIN_EMIN,
    Context,
    Decimal,
    DecimalException,
    Inexact,
    InvalidOperation,
    Overflow,
    localcontext,
)

_ZERO = Decimal(0)
_TERMINAL_ATTEMPTS = frozenset({"FILLED", "CANCELLED", "REJECTED", "EXPIRED"})
_FAILED_TERMINALS = frozenset({"CANCELLED", "REJECTED", "EXPIRED"})
_ATTEMPT_STATES = _TERMINAL_ATTEMPTS | {
    "REQUESTED",
    "SUBMITTING",
    "ACKNOWLEDGED",
    "WORKING",
    "PARTIALLY_FILLED",
    "MODIFY_PENDING",
    "CANCEL_PENDING",
    "UNKNOWN",
}
_LEG_STATES = frozenset({"ARMED", "TRIGGERED", "CANCEL_PENDING", "CANCELLED", "REJECTED", "EXPIRED", "UNKNOWN"})


@dataclass(frozen=True, slots=True)
class ExitScope:
    """Identity shared by every observation; empty expiry denotes a spot instrument."""

    mode: str
    broker: str
    account_id: str
    instrument_id: str
    expiry: str
    segment: str
    product: str


@dataclass(frozen=True, slots=True)
class ExitAttempt:
    """One attempt or broker observation, including external executable exits."""

    attempt_id: str
    broker_order_id: str | None
    state: str
    remaining: Decimal
    reservation_id: str | None
    parent_resource_id: str | None


@dataclass(frozen=True, slots=True)
class ProtectionLeg:
    """One independently executable leg; OCO does not imply atomic exclusion."""

    leg_id: str
    state: str
    remaining: Decimal
    child_ids: tuple[str, ...]
    children_complete: bool


@dataclass(frozen=True, slots=True)
class ProtectionResource:
    """An identified native resource with separately observed executable legs."""

    resource_id: str
    legs: tuple[ProtectionLeg, ...]


@dataclass(frozen=True, slots=True)
class ExitEvidence:
    """A complete snapshot; original_sign remains fixed after flatness or reversal."""

    scope: ExitScope
    original_sign: int
    current_signed_quantity: Decimal
    authorised_remaining: Decimal
    attempts: tuple[ExitAttempt, ...]
    protection_resources: tuple[ProtectionResource, ...]
    unmatched_reservations: tuple[tuple[str, Decimal], ...]
    books_complete: bool
    coherence_verified: bool
    freshness_verified: bool
    scope_verified: bool


@dataclass(frozen=True, slots=True)
class ExitDecision:
    """Advice only: a numeric cap is never permission to submit or cancel."""

    cap: Decimal
    outcome: str
    next_action: str
    reason: str


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _identity(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def _quantity(value: object, *, signed: bool = False) -> None:
    _require(isinstance(value, Decimal) and value.is_finite(), "Quantities must be finite Decimal broker units.")
    _require(signed or value >= _ZERO, "Remaining quantities cannot be negative.")


def _state(value: str, known: frozenset[str]) -> str:
    normalised = value.strip().upper() if isinstance(value, str) else "UNKNOWN"
    return normalised if normalised in known else "UNKNOWN"


def _validate_snapshot(evidence: ExitEvidence) -> None:
    _require(isinstance(evidence, ExitEvidence), "Exit evidence is required.")
    _require(
        all(
            value is True
            for value in (
                evidence.books_complete,
                evidence.coherence_verified,
                evidence.freshness_verified,
                evidence.scope_verified,
            )
        ),
        "Complete, fresh, coherent and scope-verified evidence is required.",
    )
    scope = evidence.scope
    _require(isinstance(scope, ExitScope), "An explicit exit scope is required.")
    _require(
        all(
            _identity(value)
            for value in (
                scope.mode,
                scope.broker,
                scope.account_id,
                scope.instrument_id,
                scope.segment,
                scope.product,
            )
        ),
        "Scope identity is missing or ambiguous.",
    )
    _require(isinstance(scope.expiry, str) and scope.expiry == scope.expiry.strip(), "Expiry identity is ambiguous.")
    _require(
        type(evidence.original_sign) is int and evidence.original_sign in {-1, 1}, "Original sign must be -1 or 1."
    )
    _quantity(evidence.current_signed_quantity, signed=True)
    _quantity(evidence.authorised_remaining)
    _require(
        all(
            isinstance(value, tuple)
            for value in (
                evidence.attempts,
                evidence.protection_resources,
                evidence.unmatched_reservations,
            )
        ),
        "Snapshot collections must be immutable tuples.",
    )


def _unique_attempts(rows: tuple[ExitAttempt, ...]) -> tuple[ExitAttempt, ...]:
    """Deduplicate broker aliases, but never guess through contradictory observations."""
    by_attempt: dict[str, ExitAttempt] = {}
    by_broker: dict[str, ExitAttempt] = {}
    local_only: list[ExitAttempt] = []
    for row in rows:
        _require(isinstance(row, ExitAttempt), "Invalid attempt evidence.")
        _require(_identity(row.attempt_id), "Attempt identity is missing or ambiguous.")
        for identity in (row.broker_order_id, row.reservation_id, row.parent_resource_id):
            _require(identity is None or _identity(identity), "Attempt linkage identity is ambiguous.")
        _quantity(row.remaining)
        state = _state(row.state, _ATTEMPT_STATES)
        _require(state not in {"UNKNOWN", "SUBMITTING"}, "An attempt may still execute; reconcile without replay.")
        _require(state != "FILLED" or row.remaining == _ZERO, "A filled attempt has conflicting remaining quantity.")
        _require(
            row.broker_order_id is not None or state in {"REQUESTED", "REJECTED"},
            "A broker attempt lacks its authoritative identity.",
        )
        row = replace(row, state=state)
        previous = by_attempt.get(row.attempt_id)
        if previous is not None:
            _require(previous == row, "Conflicting observations share an attempt identity.")
            continue
        by_attempt[row.attempt_id] = row
        if row.broker_order_id is None:
            local_only.append(row)
            continue
        previous = by_broker.get(row.broker_order_id)
        if previous is not None:
            _require(
                previous.state == row.state and previous.remaining == row.remaining,
                "Conflicting observations share a broker identity.",
            )
            for old, new in (
                (previous.reservation_id, row.reservation_id),
                (previous.parent_resource_id, row.parent_resource_id),
            ):
                _require(old is None or new is None or old == new, "Broker identity has conflicting ownership links.")
            row = replace(
                previous,
                reservation_id=previous.reservation_id or row.reservation_id,
                parent_resource_id=previous.parent_resource_id or row.parent_resource_id,
            )
        by_broker[row.broker_order_id] = row
    unique = (*by_broker.values(), *local_only)
    reservations: set[str] = set()
    for row in unique:
        if row.reservation_id is not None:
            _require(row.reservation_id not in reservations, "One reservation has multiple attempt identities.")
            reservations.add(row.reservation_id)
    return unique


def _protection_legs(
    resources: tuple[ProtectionResource, ...],
    attempts: tuple[ExitAttempt, ...],
) -> tuple[ProtectionLeg, ...]:
    """Validate the complete reciprocal resource/leg/broker-child identity graph."""
    resource_ids: set[str] = set()
    leg_ids: set[str] = set()
    children: dict[str, str] = {}
    legs: list[ProtectionLeg] = []
    for resource in resources:
        _require(isinstance(resource, ProtectionResource), "Invalid protection resource.")
        _require(
            _identity(resource.resource_id) and resource.resource_id not in resource_ids,
            "Protection resource identity is missing or duplicated.",
        )
        resource_ids.add(resource.resource_id)
        _require(isinstance(resource.legs, tuple) and bool(resource.legs), "Protection legs are missing.")
        for leg in resource.legs:
            _require(isinstance(leg, ProtectionLeg), "Invalid protection leg.")
            _require(
                _identity(leg.leg_id) and leg.leg_id not in leg_ids, "Protection leg identity is missing or duplicated."
            )
            leg_ids.add(leg.leg_id)
            _quantity(leg.remaining)
            state = _state(leg.state, _LEG_STATES)
            _require(state != "UNKNOWN", "Protection status is unknown; reconcile without replay.")
            _require(
                isinstance(leg.child_ids, tuple) and leg.children_complete is True,
                "Protection child evidence is incomplete.",
            )
            _require(state != "TRIGGERED" or bool(leg.child_ids), "A triggered leg has no verified execution children.")
            _require(state != "ARMED" or not leg.child_ids, "An armed leg has conflicting execution children.")
            for child_id in leg.child_ids:
                _require(
                    _identity(child_id) and child_id not in children,
                    "A child identity is missing, duplicated or shared between legs.",
                )
                children[child_id] = resource.resource_id
            legs.append(replace(leg, state=state))
    by_broker = {attempt.broker_order_id: attempt for attempt in attempts if attempt.broker_order_id is not None}
    for child_id, resource_id in children.items():
        child = by_broker.get(child_id)
        _require(
            child is not None and child.parent_resource_id == resource_id,
            "A protection child lacks reciprocal broker/resource evidence.",
        )
    for attempt in attempts:
        if attempt.parent_resource_id is not None:
            _require(
                attempt.parent_resource_id in resource_ids
                and children.get(attempt.broker_order_id) == attempt.parent_resource_id,
                "An execution child is absent from its resource's complete leg evidence.",
            )
    return tuple(legs)


def _unmatched_reservations(
    rows: tuple[tuple[str, Decimal], ...],
    attempts: tuple[ExitAttempt, ...],
) -> tuple[Decimal, ...]:
    """Transfer only uniquely broker-linked reservations, including final terminal evidence.

    A reservation may retain its original amount after a partial fill. The broker
    remainder supersedes that amount only after unique identity is proved. A local
    pre-ACK record, even a terminal one, cannot release an unmatched reservation.
    """
    reservations: dict[str, Decimal] = {}
    for row in rows:
        _require(isinstance(row, tuple) and len(row) == 2, "Invalid reservation evidence.")
        reservation_id, remaining = row
        _require(_identity(reservation_id), "Reservation identity is missing or ambiguous.")
        _quantity(remaining)
        _require(
            reservation_id not in reservations or reservations[reservation_id] == remaining,
            "A reservation has conflicting quantities.",
        )
        reservations[reservation_id] = remaining
    for attempt in attempts:
        if attempt.broker_order_id is not None and attempt.reservation_id is not None and attempt.state != "REQUESTED":
            reservations.pop(attempt.reservation_id, None)
    return tuple(reservations.values())


def _quantity_cap(evidence: ExitEvidence, outstanding: tuple[Decimal, ...]) -> Decimal:
    """Subtract exactly, independently of the caller's ambient Decimal precision."""
    position = evidence.current_signed_quantity
    eligible = position.copy_abs() if (position > _ZERO) == (evidence.original_sign == 1) else _ZERO
    amounts = (eligible, evidence.authorised_remaining, *outstanding)
    nonzero = [amount for amount in amounts if amount != _ZERO]
    precision = 28
    if nonzero:
        precision = max(
            precision,
            max(amount.adjusted() for amount in nonzero)
            - min(amount.as_tuple().exponent for amount in nonzero)
            + len(str(len(amounts)))
            + 2,
        )
    context = Context(prec=precision, Emax=MAX_EMAX, Emin=MIN_EMIN, traps=[InvalidOperation, Overflow, Inexact])
    with localcontext(context):
        return min(evidence.authorised_remaining, max(_ZERO, eligible - sum(outstanding, _ZERO)))


def decide_exit(
    evidence: ExitEvidence,
    *,
    explicit_close: bool,
    protection_authorised: bool,
    market_supported: bool,
    preconditions_changed: bool,
) -> ExitDecision:
    """Return conservative snapshot advice without submitting or cancelling anything.

    All nonterminal attempts retain risk. Known working orders may be advised for
    cancellation only under explicit close intent; pending operations must wait.
    Unknown evidence never becomes a replay opportunity. An unmatched reservation
    retains its arithmetic risk and requires reconciliation even when its cap is
    positive. Definitive terminal failures require changed preconditions and
    continued intent/policy authorisation before market recovery can be advised.

    Args:
        evidence: Complete scoped snapshot from a separately verified evidence source.
        explicit_close: Whether the user authorised this continuing close intent.
        protection_authorised: Whether an authorised policy permits failed-stop recovery.
        market_supported: Whether market execution is supported for this exact scope.
        preconditions_changed: Whether the conditions causing a previous failure changed.

    Returns:
        Conservative outcome, quantity cap and next-action advice. Invalid or
        uncertain evidence requests reconciliation; no result authorises a write.
    """
    try:
        _validate_snapshot(evidence)
        _require(
            all(
                type(value) is bool
                for value in (
                    explicit_close,
                    protection_authorised,
                    market_supported,
                    preconditions_changed,
                )
            ),
            "Explicit boolean decision preconditions are required.",
        )
        attempts = _unique_attempts(evidence.attempts)
        legs = _protection_legs(evidence.protection_resources, attempts)
        unmatched = _unmatched_reservations(evidence.unmatched_reservations, attempts)
        active = tuple(attempt for attempt in attempts if attempt.state not in _TERMINAL_ATTEMPTS)
        armed = tuple(leg for leg in legs if leg.state in {"ARMED", "CANCEL_PENDING"})
        # Triggered and terminal legs never prove their children terminal. The
        # complete child graph above transfers each leg to its distinct attempts.
        outstanding = (*(attempt.remaining for attempt in active), *(leg.remaining for leg in armed), *unmatched)
        cap = _quantity_cap(evidence, outstanding)
    except (ValueError, DecimalException) as error:
        return ExitDecision(_ZERO, "UNKNOWN", "RECONCILE", str(error))

    if unmatched:
        return ExitDecision(
            cap, "UNKNOWN", "RECONCILE", "Unmatched reservations remain; do not replay or release them."
        )
    pending = any(attempt.state in {"REQUESTED", "MODIFY_PENDING", "CANCEL_PENDING"} for attempt in active)
    pending = pending or any(leg.state == "CANCEL_PENDING" for leg in armed)
    reversed_position = evidence.current_signed_quantity != _ZERO and (
        (evidence.current_signed_quantity > _ZERO) != (evidence.original_sign == 1)
    )
    if active or armed:
        action = "CANCEL_THEN_RECONCILE" if explicit_close and not pending else "WAIT"
        outcome = "FAILED" if reversed_position else "OPEN"
        reason = (
            "External position reversal leaves executable exit hazards."
            if reversed_position
            else (
                "Existing exits may still execute; wait for authoritative terminal evidence and reconcile final fills."
            )
        )
        return ExitDecision(cap, outcome, action, reason)
    if reversed_position:
        return ExitDecision(_ZERO, "FAILED", "NONE", "External position reversal does not authorise the new direction.")
    if evidence.current_signed_quantity == _ZERO:
        return ExitDecision(
            _ZERO, "CLOSED", "NONE", "Verified flat exposure with every linked execution risk resolved."
        )
    if cap == _ZERO:
        return ExitDecision(cap, "OPEN", "NONE", "No additional quantity is authorised for this exit intent.")
    failed = any(attempt.state in _FAILED_TERMINALS for attempt in attempts)
    failed = failed or any(leg.state in _FAILED_TERMINALS for leg in legs)
    if not explicit_close and not (protection_authorised and failed):
        return ExitDecision(
            cap,
            "FAILED" if failed else "OPEN",
            "NONE",
            "An explicit close or authorised failed-protection recovery policy is required.",
        )
    if failed and not preconditions_changed:
        return ExitDecision(cap, "FAILED", "NONE", "Failure preconditions are unchanged; do not start another attempt.")
    if not market_supported:
        return ExitDecision(
            cap, "FAILED", "REQUEST_ALTERNATIVE", "Market execution is unsupported; request an explicit alternative."
        )
    return ExitDecision(
        cap,
        "OPEN",
        "SUBMIT_MARKET",
        "Eligible remainder may progress through existing safety gates; execution and price are not guaranteed.",
    )
