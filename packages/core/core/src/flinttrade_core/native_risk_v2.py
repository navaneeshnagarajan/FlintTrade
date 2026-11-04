"""Pure v2 risk arithmetic, not authority, reservation custody or a durable latch.

Inputs are immutable projections from trusted canonical owners, NOT client
proofs or transport DTOs. This finite profile supports long-only cash in INR
and exact, fully allocated fee-component upper bounds. It does not infer
current tariffs, margin, market-order bounds, charge allocation or flatness.
"""

from dataclasses import dataclass, fields
from decimal import ROUND_HALF_EVEN, Context, Decimal, DivisionByZero, Inexact, InvalidOperation, Overflow, localcontext
from types import UnionType
from typing import Literal, TypeVar, cast, get_args, get_origin

from pydantic import BaseModel, ValidationError

from flinttrade_core.native_autonomy_contracts_v2 import (
    PositiveMoneyV2,
    RevisionRefV2,
    RiskPolicyV2,
    RunScopeV2,
)


@dataclass(frozen=True)
class FilledLot:
    """One unique lifetime fill and its owner-attributed cumulative exits.

    Attributes:
        fill_ref: Immutable owner-resolved fill identity, not an inferred order ID.
        quantity: Total whole units ever acquired by this fill.
        unit_cost: Exact acquisition cost per unit in the input currency.
        exited_quantity: Cumulative units exited, never greater than quantity.
        gross_exit_proceeds: Lifetime receipts for those exits, before fees.
    """

    fill_ref: RevisionRefV2
    quantity: int
    unit_cost: Decimal
    exited_quantity: int
    gross_exit_proceeds: Decimal


@dataclass(frozen=True)
class EntryObservation:
    """One canonical entry, not an order-book row or an additional reservation.

    Lots are unique cumulative fills, including exited lots. Remaining possible
    quantity excludes those fills. Committed principal and fee allowance are
    the existing owner's NON-replenishing lifetime counters, exclusive of the
    remaining pending hold computed here. No ACK/cancel/transfer state is an
    input: none can release these counters or prove a possible write absent.
    All lots and the mark must refer to the entry's same owner-bound instrument.
    """

    entry_ref: RevisionRefV2
    scope: RunScopeV2
    source_ref: RevisionRefV2
    currency: str
    family: Literal["cash_long"]
    lots: tuple[FilledLot, ...]
    remaining_possible_quantity: int | None
    remaining_price_upper_bound: Decimal | None
    unknown_possible_write: bool
    mark: Decimal | None
    mark_at_ms: int | None
    committed_principal: Decimal
    committed_fee_allowance: Decimal


@dataclass(frozen=True)
class IncurredCharge:
    """One uniquely identified, already charged fee in the paid-charge profile.

    Attributes:
        charge_ref: Owner-resolved identity preventing duplicate fee consumption.
        amount: Exact paid amount, retained in capital and lifetime loss even
            after its attributed filled position closes. An unpaid liability
            must not be presented as paid; it remains in the inclusive bound.
        charged_at_ms: Observed charge time within the resolved tariff interval.
    """

    charge_ref: RevisionRefV2
    amount: Decimal
    charged_at_ms: int


@dataclass(frozen=True)
class FeeComponent:
    """An exact owner-allocated inclusive upper bound for one charge component.

    Attributes:
        name: Required component name, including explicit applicable zeroes.
        basis: Observed fill/order/day/depository charge basis, not a lot split.
        basis_ref: Exact disjoint basis identity resolved by the existing owner.
        total_upper_bound: Paid amount plus all remaining applicable liabilities;
            None means unknown, not free execution.
        incurred: Unique paid charges consuming this bound exactly once.
    """

    name: str
    basis: Literal["fill", "order", "day", "depository"]
    basis_ref: RevisionRefV2
    total_upper_bound: Decimal | None
    incurred: tuple[IncurredCharge, ...]


@dataclass(frozen=True)
class FeeAllocation:
    """One disjoint charge-basis allocation, including explicit zero components.

    Upper bounds INCLUDE incurred amounts. The remaining reserve is calculated
    by subtraction, never added to an already inclusive total. Canonical owners
    must resolve fragmentation/day/depository aggregation before supplying this.
    Shared component/basis identities across allocations are refused.

    The exact entry reference attributes each component to that entry's filled
    or pending phase. Paid fees leave exposure only when the complete non-empty
    filled-lot census for that entry is closed. A historical phase or an opaque
    fill/order/day/depository basis ID alone does not prove closure. Partly open
    entries retain all paid fees: no lot-level fee split is inferred or prorated.
    Every remaining bound stays a liability, even when filled quantities close.
    """

    allocation_ref: RevisionRefV2
    entry_ref: RevisionRefV2
    phase: Literal["entry_filled", "entry_pending", "exit_filled", "exit_pending", "historical"]
    tariff_ref: RevisionRefV2
    as_of_ms: int
    components: tuple[FeeComponent, ...]


@dataclass(frozen=True)
class FeeSchedule:
    """Resolved owner observation, NOT tariff verification or qualification.

    No legacy default brokerage or backwards extrapolation is used. Components
    are already-rounded, exact owner-allocated totals/finite upper bounds;
    tariffs with unresolved rates, minima or shared charge bases are unavailable.
    """

    policy_ref: RevisionRefV2
    tariff_ref: RevisionRefV2
    source_ref: RevisionRefV2
    currency: str
    family: Literal["cash_long"]
    effective_from_ms: int
    effective_through_ms: int
    complete: bool
    allocation: Literal["exact_component_upper_bounds"]


@dataclass(frozen=True)
class RiskInputs:
    """Complete run-lifetime census at a canonical/reservation revision.

    Source completeness, allocation and reference resolution are the caller's
    responsibilities; booleans here describe that trusted projection, not proof
    of it. Previously paid fees/fills must remain after exit, handback/restart.
    """

    scope: RunScopeV2
    policy_ref: RevisionRefV2
    source_ref: RevisionRefV2
    reservation_ref: RevisionRefV2
    fee_policy_ref: RevisionRefV2
    run_started_at_ms: int
    observed_at_ms: int
    currency: str
    complete: bool
    allocated: bool
    entries: tuple[EntryObservation, ...]
    fee_schedule: FeeSchedule
    fees: tuple[FeeAllocation, ...]


@dataclass(frozen=True)
class LatchObservation:
    """An immutable observation of the existing owner's loss-retirement latch.

    Attributes:
        scope: Exact run/account binding; this observation creates no authority.
        policy_ref: The policy episode whose retirement is being observed.
        revision: Owner-resolved revision for a later, separate durable CAS.
        retired: Explicit existing retirement. Recovery cannot silently clear it.
    """

    scope: RunScopeV2
    policy_ref: RevisionRefV2
    revision: RevisionRefV2
    retired: bool


@dataclass(frozen=True)
class LatchProposal:
    """In-memory proposal ONLY. No event is persisted or authority changed."""

    action: Literal["retain", "retire_entries_and_request_custody", "hold_unknown"]
    retired: bool | None
    expected_revision: RevisionRefV2 | None


@dataclass(frozen=True)
class RiskAssessment:
    """Pure arithmetic and a non-durable transition proposal, never permission.

    Attributes:
        status: Arithmetic within bounds, breached, or unavailable.
        reasons: Bounded refusal or threshold codes, never arbitrary input text.
        capital: Non-replenishing fee-inclusive commitment, or None if unknown.
        exposure: Conservative surviving/pending exposure and applicable fees.
        net_pnl_after_fees_and_closing_reserve: Whole-run net cashflow/mark basis.
        loss: Non-negative whole-run loss, not a realised-loss guarantee.
        inputs: Original structurally validated evidence, including stale or
            incomplete observations; None if nested structure/tokens are invalid.
        evaluated_at_ms: Exact supplied time, or None when that scalar is invalid.
        transition: Owner-applied proposal; malformed latch evidence supplies no
            trusted CAS revision and cannot clear an explicit prior retirement.
    """

    status: Literal["within_bounds", "breached", "unavailable"]
    reasons: tuple[str, ...]
    capital: Decimal | None
    exposure: Decimal | None
    net_pnl_after_fees_and_closing_reserve: Decimal | None
    loss: Decimal | None
    inputs: RiskInputs | None
    evaluated_at_ms: int | None
    transition: LatchProposal


class _Unavailable(ValueError):
    pass


def _arithmetic_context() -> Context:
    """Create exact arithmetic settings without reading either mutable context.

    Prices have at most 60 whole and eight fractional digits, quantities at
    most 16 whole digits, and every collection at most 10,000 items. Precision
    128 and this exponent range exceed their products and aggregate bounds.
    Every setting, including empty flags and the complete trap set, is explicit.
    """
    return Context(
        prec=128,
        rounding=ROUND_HALF_EVEN,
        Emin=-999999,
        Emax=999999,
        capitals=1,
        clamp=0,
        flags=[],
        traps=[InvalidOperation, DivisionByZero, Overflow, Inexact],
    )


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise _Unavailable(reason)


def _integer(value: int, *, positive: bool = False) -> None:
    _require(type(value) is int and (1 if positive else 0) <= value <= 9007199254740991, "invalid_scalar")


def _money(value: Decimal, *, positive: bool = False) -> None:
    _require(type(value) is Decimal and value.is_finite(), "invalid_scalar")
    exponent = value.as_tuple().exponent
    _require(
        type(exponent) is int and exponent >= -8 and value.adjusted() < 60 and (value > 0 if positive else value >= 0),
        "invalid_scalar",
    )


def _reference(value: RevisionRefV2) -> None:
    _require(type(value) is RevisionRefV2, "invalid_reference")
    try:
        RevisionRefV2.model_validate(value.model_dump())
    except ValidationError as exc:
        raise _Unavailable("invalid_reference") from exc


def _scope(value: RunScopeV2) -> None:
    _require(type(value) is RunScopeV2, "invalid_scope")
    try:
        RunScopeV2.model_validate(value.model_dump())
    except ValidationError as exc:
        raise _Unavailable("invalid_scope") from exc


def _sequence(value: tuple, item_type: type) -> None:
    _require(
        type(value) is tuple and len(value) <= 10000 and all(type(item) is item_type for item in value),
        "invalid_structure",
    )


_T = TypeVar("_T")


def _known(value: _T | None) -> _T:
    if value is None:
        raise _Unavailable("evidence_missing")
    return value


_Observation = (
    FilledLot
    | EntryObservation
    | IncurredCharge
    | FeeComponent
    | FeeAllocation
    | FeeSchedule
    | RiskInputs
    | LatchObservation
)


def _plain_tree(value: object, schema: object, reason: str = "invalid_scalar") -> None:
    """Check this closed observation grammar before any serialisation or equality.

    Only the explicitly named observation/model classes are traversed. Inspect
    their stored fields, never convert, copy or format an arbitrary input. The
    schema comes from these trusted classes, not from the supplied instance.
    Plain valid instances retain their identity; bypassed subclasses, metadata,
    missing/extra fields and invalid model tokens cannot become result evidence.
    """
    origin = get_origin(schema)
    if origin is UnionType:
        options = get_args(schema)
        if value is None and any(option is type(None) for option in options):
            return
        schema = next(option for option in options if option is not type(None))
        _plain_tree(value, schema, reason)
        return
    if origin is Literal:
        options = get_args(schema)
        _require(type(value) is str and value in options, reason)
        return
    if origin is tuple:
        _require(type(value) is tuple and len(value) <= 10000, "invalid_structure")
        for item in cast(tuple[object, ...], value):
            _plain_tree(item, get_args(schema)[0], reason)
        return
    if schema is str or schema is int or schema is bool or schema is Decimal:
        _require(type(value) is schema, reason)
        if schema is Decimal:
            _money(cast(Decimal, value))
        elif schema is int:
            _integer(cast(int, value))
        return
    model = schema is RevisionRefV2 or schema is RunScopeV2 or schema is PositiveMoneyV2 or schema is RiskPolicyV2
    observation = any(
        schema is cls
        for cls in (
            FilledLot,
            EntryObservation,
            IncurredCharge,
            FeeComponent,
            FeeAllocation,
            FeeSchedule,
            RiskInputs,
            LatchObservation,
        )
    )
    _require(model or observation, "invalid_structure")
    if schema is RiskPolicyV2 or schema is PositiveMoneyV2:
        reason = "invalid_policy"
    elif schema is RevisionRefV2:
        reason = "invalid_reference"
    elif schema is RunScopeV2:
        reason = "invalid_scope"
    _require(type(value) is schema, reason if model else "invalid_structure")
    data = object.__getattribute__(value, "__dict__")
    _require(type(data) is dict and all(type(key) is str for key in data), reason)
    expected = (
        {name: field.annotation for name, field in cast(type[BaseModel], schema).model_fields.items()}
        if model
        else {field.name: field.type for field in fields(cast(type[_Observation], schema))}
    )
    _require(data.keys() == expected.keys(), reason)
    if model:
        try:
            extra = object.__getattribute__(value, "__pydantic_extra__")
            private = object.__getattribute__(value, "__pydantic_private__")
            supplied = object.__getattribute__(value, "__pydantic_fields_set__")
        except AttributeError as exc:
            raise _Unavailable(reason) from exc
        _require(extra is None and private is None, reason)
        _require(type(supplied) is set and all(type(key) is str for key in supplied), reason)
        _require(supplied <= expected.keys(), reason)
    for name, annotation in expected.items():
        _plain_tree(data[name], annotation, reason)
    if model:
        try:
            cast(type[BaseModel], schema).model_validate(cast(BaseModel, value).model_dump())
        except ValidationError as exc:
            raise _Unavailable(reason) from exc


def _evidence_error(value: object, schema: object) -> _Unavailable | None:
    """Audit retained evidence independently of earlier validation failures."""
    try:
        _plain_tree(value, schema)
    except _Unavailable as exc:
        return exc
    return None


def _retained_retirement(latch: LatchObservation | None, valid: bool) -> bool | None:
    """Preserve an explicit prior retirement; never clear an invalid latch."""
    if type(latch) is not LatchObservation:
        return None
    data = object.__getattribute__(latch, "__dict__")
    if type(data) is not dict or not all(type(key) is str for key in data):
        return None
    retired = data.get("retired")
    return retired if retired is True or (valid and retired is False) else None


def _validate(policy: RiskPolicyV2, inputs: RiskInputs, latch: LatchObservation, now_ms: int) -> None:
    _require(type(policy) is RiskPolicyV2, "invalid_policy")
    try:
        RiskPolicyV2.model_validate(policy.model_dump())
    except ValidationError as exc:
        raise _Unavailable("invalid_policy") from exc
    for cap in (policy.capital_cap, policy.exposure_cap, policy.loss_action_threshold):
        _require(type(cap) is PositiveMoneyV2, "invalid_policy")
    _reference(policy.policy_ref)
    _reference(policy.fee_policy_ref)
    _require(type(inputs) is RiskInputs and type(latch) is LatchObservation, "invalid_structure")
    _require(type(inputs.currency) is str, "invalid_scalar")
    _scope(inputs.scope)
    _scope(latch.scope)
    for reference in (
        inputs.policy_ref,
        inputs.source_ref,
        inputs.reservation_ref,
        inputs.fee_policy_ref,
        latch.policy_ref,
        latch.revision,
    ):
        _reference(reference)
    _require(type(latch.retired) is bool, "invalid_scalar")
    for time in (now_ms, inputs.run_started_at_ms, inputs.observed_at_ms):
        _integer(time, positive=True)
    _sequence(inputs.entries, EntryObservation)
    entry_ids: set[str] = set()
    fill_ids: set[str] = set()
    for entry in inputs.entries:
        _require(type(entry.currency) is str, "invalid_scalar")
        _scope(entry.scope)
        _reference(entry.entry_ref)
        _require(entry.entry_ref.id not in entry_ids, "duplicate_entry")
        entry_ids.add(entry.entry_ref.id)
        _require(type(entry.family) is str and entry.family == "cash_long", "unsupported_profile")
        _reference(entry.source_ref)
        _money(entry.committed_principal)
        _money(entry.committed_fee_allowance)
        if entry.remaining_possible_quantity is not None:
            _integer(entry.remaining_possible_quantity)
        if entry.remaining_price_upper_bound is not None:
            _money(entry.remaining_price_upper_bound, positive=True)
        if entry.mark is not None:
            _money(entry.mark, positive=True)
        if entry.mark_at_ms is not None:
            _integer(entry.mark_at_ms, positive=True)
        _sequence(entry.lots, FilledLot)
        filled_principal = Decimal(0)
        for lot in entry.lots:
            _reference(lot.fill_ref)
            _require(lot.fill_ref.id not in fill_ids, "duplicate_fill")
            fill_ids.add(lot.fill_ref.id)
            _integer(lot.quantity, positive=True)
            _integer(lot.exited_quantity)
            _money(lot.unit_cost, positive=True)
            _money(lot.gross_exit_proceeds)
            _require(
                lot.exited_quantity <= lot.quantity and (lot.exited_quantity > 0 or lot.gross_exit_proceeds == 0),
                "fill_conflicting",
            )
            filled_principal += lot.quantity * lot.unit_cost
        _require(entry.committed_principal >= filled_principal, "capital_commitment_conflicting")
    _require(
        inputs.policy_ref == policy.policy_ref == latch.policy_ref
        and inputs.scope == latch.scope
        and inputs.fee_policy_ref == policy.fee_policy_ref
        and inputs.currency == policy.capital_cap.currency,
        "scope_or_revision_mismatch",
    )
    _require(inputs.complete is True and inputs.allocated is True, "incomplete_or_unallocated")
    _require(
        inputs.run_started_at_ms <= inputs.observed_at_ms <= now_ms
        and now_ms - inputs.observed_at_ms <= policy.max_mark_age_ms,
        "source_time_unavailable",
    )
    for entry in inputs.entries:
        _require(
            entry.scope == inputs.scope and entry.source_ref == inputs.source_ref and entry.currency == inputs.currency,
            "scope_or_revision_mismatch",
        )
        _require(
            entry.unknown_possible_write is False and entry.remaining_possible_quantity is not None,
            "unknown_possible_writes",
        )
        if entry.remaining_possible_quantity:
            _require(entry.remaining_price_upper_bound is not None, "unbounded_possible_fill")
        active = entry.remaining_possible_quantity or any(lot.quantity > lot.exited_quantity for lot in entry.lots)
        if active:
            _require(entry.mark is not None and entry.mark_at_ms is not None, "mark_unavailable")
            mark_at = _known(entry.mark_at_ms)
            _require(
                inputs.run_started_at_ms <= mark_at <= inputs.observed_at_ms
                and now_ms - mark_at <= policy.max_mark_age_ms,
                "mark_time_unavailable",
            )


_COMPONENTS = frozenset(("brokerage", "exchange", "sebi", "stt", "stamp", "gst", "delivery", "other"))
_PHASES = frozenset(("entry_filled", "entry_pending", "exit_filled", "exit_pending", "historical"))


def _validate_fees(inputs: RiskInputs, now_ms: int, max_age_ms: int) -> None:
    schedule = inputs.fee_schedule
    _require(type(schedule) is FeeSchedule, "fees_unavailable")
    _require(
        type(schedule.currency) is str and type(schedule.family) is str and type(schedule.allocation) is str,
        "invalid_scalar",
    )
    for reference in (schedule.policy_ref, schedule.tariff_ref, schedule.source_ref):
        _reference(reference)
    _integer(schedule.effective_from_ms, positive=True)
    _integer(schedule.effective_through_ms, positive=True)
    _require(
        schedule.complete is True
        and schedule.allocation == "exact_component_upper_bounds"
        and schedule.currency == inputs.currency == "INR"
        and schedule.family == "cash_long"
        and schedule.policy_ref == inputs.fee_policy_ref,
        "fees_unavailable",
    )
    _require(schedule.effective_from_ms <= now_ms <= schedule.effective_through_ms, "fee_date_unavailable")
    _sequence(inputs.fees, FeeAllocation)
    entries = {entry.entry_ref.id: entry for entry in inputs.entries}
    allocations: set[str] = set()
    charges: set[str] = set()
    bases: set[tuple[str, str]] = set()
    phases: dict[str, set[str]] = {key: set() for key in entries}
    for allocation in inputs.fees:
        for reference in (allocation.allocation_ref, allocation.entry_ref, allocation.tariff_ref):
            _reference(reference)
        _require(allocation.allocation_ref.id not in allocations, "duplicate_fee_allocation")
        allocations.add(allocation.allocation_ref.id)
        _require(
            allocation.entry_ref.id in entries
            and allocation.entry_ref == entries[allocation.entry_ref.id].entry_ref
            and allocation.tariff_ref == schedule.tariff_ref,
            "fee_reference_mismatch",
        )
        _require(type(allocation.phase) is str and allocation.phase in _PHASES, "fee_phase_unavailable")
        phases[allocation.entry_ref.id].add(allocation.phase)
        _integer(allocation.as_of_ms, positive=True)
        _require(
            max(inputs.run_started_at_ms, schedule.effective_from_ms) <= allocation.as_of_ms <= inputs.observed_at_ms
            and now_ms - allocation.as_of_ms <= max_age_ms,
            "fee_date_unavailable",
        )
        _sequence(allocation.components, FeeComponent)
        _require(
            len(allocation.components) == len(_COMPONENTS)
            and all(type(c.name) is str for c in allocation.components)
            and {c.name for c in allocation.components} == _COMPONENTS,
            "fee_components_incomplete",
        )
        entry = entries[allocation.entry_ref.id]
        for component in allocation.components:
            _reference(component.basis_ref)
            _require(
                type(component.basis) is str and component.basis in ("fill", "order", "day", "depository"),
                "fee_basis_unavailable",
            )
            key = (component.name, component.basis_ref.id)
            _require(key not in bases, "fee_basis_unallocated")
            bases.add(key)
            _require(component.total_upper_bound is not None, "fees_unbounded")
            upper = _known(component.total_upper_bound)
            _money(upper)
            _sequence(component.incurred, IncurredCharge)
            paid = Decimal(0)
            for charge in component.incurred:
                _reference(charge.charge_ref)
                _require(charge.charge_ref.id not in charges, "duplicate_incurred_charge")
                charges.add(charge.charge_ref.id)
                _money(charge.amount)
                _integer(charge.charged_at_ms, positive=True)
                _require(
                    max(inputs.run_started_at_ms, schedule.effective_from_ms)
                    <= charge.charged_at_ms
                    <= allocation.as_of_ms,
                    "fee_date_unavailable",
                )
                paid += charge.amount
            _require(paid <= upper, "fee_upper_bound_conflicting")
            remaining = upper - paid
            if allocation.phase in ("entry_pending", "exit_pending"):
                _require(
                    not component.incurred and _known(entry.remaining_possible_quantity) > 0, "fee_phase_conflicting"
                )
            elif allocation.phase == "entry_filled":
                _require(bool(entry.lots), "fee_phase_conflicting")
            elif allocation.phase == "exit_filled":
                _require(bool(entry.lots), "fee_phase_conflicting")
                _require(
                    not remaining or any(lot.quantity > lot.exited_quantity for lot in entry.lots),
                    "unallocated_closing_reserve",
                )
            else:
                _require(remaining == 0, "unallocated_historical_reserve")
    for entry in inputs.entries:
        required = set()
        if entry.lots:
            required.update(("entry_filled", "exit_filled"))
        if entry.remaining_possible_quantity:
            required.update(("entry_pending", "exit_pending"))
        _require(required <= phases[entry.entry_ref.id], "fee_phases_incomplete")


def assess_risk(
    policy: RiskPolicyV2, inputs: RiskInputs | None, latch: LatchObservation | None, *, now_ms: int
) -> RiskAssessment:
    """Assess arithmetic only. A within-bounds result never permits an entry.

    Cap equality is within bounds; loss-threshold equality proposes retirement.
    Exposure excludes paid fees attributed to a fully closed filled position;
    unresolved partial-position attribution conservatively retains those fees.
    Pending exposure and all applicable remaining fee liabilities stay retained.
    Loss nets the entire run first, then deducts incurred fees and the unincurred
    closing reserve for filled exposure only. Pending allowances are NOT loss.
    No arithmetic output guarantees execution prices or a realised-loss ceiling.
    The owner must resolve inputs, persist counters/latch, and recheck all pinned
    revisions at admission AND invocation. Repeated proposals are not durable
    once-per-episode events; an owner CAS against expected_revision is required.

    Args:
        policy: Explicit operator-valued policy with pinned fee semantics.
        inputs: Immutable, complete owner-resolved lifetime observations and
            dated fee allocations, or None when unavailable. This finite profile
            treats incurred charges as paid; unresolved payment or attribution
            must stay a retained liability or unavailable at the producing owner.
        latch: Existing policy-episode retirement observation, or None if unknown.
        now_ms: Explicit positive evaluation time in the safe-integer domain.

    Returns:
        Exact arithmetic or unavailable amounts plus a non-durable latch
        proposal. Unknown or malformed evidence never becomes zero capacity or
        entry permission. Invalid nested evidence is withheld from result pins.

    Raises:
        Inexact: Arithmetic exceeds the supported exact representation; no
            rounded or floating-point fallback is returned.
    """
    input_error = _evidence_error(inputs, RiskInputs)
    latch_error = _evidence_error(latch, LatchObservation)
    try:
        inputs = _known(inputs)
        latch = _known(latch)
        _plain_tree(policy, RiskPolicyV2)
        if input_error is not None:
            raise input_error
        if latch_error is not None:
            raise latch_error
        with localcontext(_arithmetic_context()):
            _validate(policy, inputs, latch, now_ms)
            _validate_fees(inputs, now_ms, policy.max_mark_age_ms)
    except _Unavailable as exc:
        retired = _retained_retirement(latch, latch_error is None)
        revision = latch.revision if latch_error is None and latch is not None else None
        return RiskAssessment(
            "unavailable",
            (str(exc),),
            None,
            None,
            None,
            None,
            inputs if input_error is None else None,
            now_ms if type(now_ms) is int and 0 < now_ms <= 9007199254740991 else None,
            LatchProposal("hold_unknown", retired, revision),
        )
    with localcontext(_arithmetic_context()):
        capital = exposure = gross_pnl = incurred = closing = Decimal(0)
        for entry in inputs.entries:
            pending = _known(entry.remaining_possible_quantity)
            closed = bool(entry.lots) and all(lot.quantity == lot.exited_quantity for lot in entry.lots)
            pending_cost = pending * _known(entry.remaining_price_upper_bound) if pending else Decimal(0)
            capital += entry.committed_principal + pending_cost
            exposure += (
                pending * max(_known(entry.remaining_price_upper_bound), _known(entry.mark)) if pending else Decimal(0)
            )
            for lot in entry.lots:
                open_quantity = lot.quantity - lot.exited_quantity
                cost = open_quantity * lot.unit_cost
                mark = open_quantity * _known(entry.mark) if open_quantity else Decimal(0)
                exposure += max(cost, mark)
                gross_pnl += lot.gross_exit_proceeds - lot.exited_quantity * lot.unit_cost + mark - cost
            filled_fees = pending_fees = Decimal(0)
            for allocation in inputs.fees:
                if allocation.entry_ref != entry.entry_ref:
                    continue
                for component in allocation.components:
                    paid = sum((c.amount for c in component.incurred), Decimal(0))
                    remaining = _known(component.total_upper_bound) - paid
                    incurred += paid
                    exposure += remaining + (Decimal(0) if closed else paid)
                    if allocation.phase in ("entry_pending", "exit_pending"):
                        pending_fees += remaining
                    else:
                        filled_fees += paid + remaining
                    if allocation.phase == "exit_filled":
                        closing += remaining
            capital += max(entry.committed_fee_allowance, filled_fees) + pending_fees
        net = gross_pnl - incurred - closing
        loss = max(Decimal(0), -net)
        reasons = tuple(
            name
            for name, value, cap in (
                ("capital_cap", capital, policy.capital_cap.amount),
                ("exposure_cap", exposure, policy.exposure_cap.amount),
            )
            if value > Decimal(cap)
        )
        crossed = loss >= Decimal(policy.loss_action_threshold.amount)
        if crossed:
            reasons += ("loss_action_threshold",)
        transition = LatchProposal(
            "retire_entries_and_request_custody" if crossed and not latch.retired else "retain",
            latch.retired or crossed,
            latch.revision,
        )
        return RiskAssessment(
            "breached" if reasons else "within_bounds",
            reasons,
            capital,
            exposure,
            net,
            loss,
            inputs,
            now_ms,
            transition,
        )
