"""Pure index-options risk. No transport input, authority, I/O or durable state.

The canonical owner alone resolves this immutable projection and its complete
lifetime census. Instances/references/flags are not proof of trust. No route
accepts these records; decoding a client DTO cannot construct owner authority.
"""

import re
from dataclasses import dataclass, fields
from decimal import ROUND_HALF_EVEN, Context, Decimal, DivisionByZero, Inexact, InvalidOperation, Overflow, localcontext
from types import UnionType
from typing import Callable, Literal, TypeVar, cast, get_args, get_origin

from pydantic import BaseModel, ValidationError

from flinttrade_core.native_autonomy_contracts_v2 import (
    OptionsRiskPolicyV2,
    PositiveMoneyV2,
    RevisionRefV2,
    RunScopeV2,
)
from flinttrade_core.native_risk_v2 import LatchProposal


@dataclass(frozen=True)
class OptionsBasis:
    """Exact independently resolved owner revisions; never caller attestation."""

    scope: RunScopeV2
    policy_ref: RevisionRefV2
    source_ref: RevisionRefV2
    reservation_ref: RevisionRefV2
    fee_policy_ref: RevisionRefV2
    tariff_ref: RevisionRefV2
    fee_source_ref: RevisionRefV2


@dataclass(frozen=True)
class OptionContract:
    """Historical listing identity. Quantities are units, NOT a lot count.

    A changed current listing cannot erase known fills in this pinned contract.
    Product/expiry metadata does not qualify overnight protection or eligibility.
    """

    contract_ref: RevisionRefV2
    listing_ref: RevisionRefV2
    token: str
    underlying_ref: RevisionRefV2
    underlying: Literal["NIFTY", "SENSEX"]
    exchange: Literal["NFO", "BFO"]
    product: Literal["MIS", "NRML"]
    expiry_at_ms: int
    right: Literal["CE", "PE"]
    strike: Decimal
    units_per_lot: int
    quantity_unit: Literal["underlying_units"]
    currency: Literal["INR"]


@dataclass(frozen=True)
class OptionExit:
    """Exact allocated exit execution; settlement requires an observed event.

    The owner must split multi-fill allocations uniquely; no cumulative order
    fill is counted a second time. Zero settlement is an event, not disappearance.
    """

    execution_ref: RevisionRefV2
    write_ref: RevisionRefV2 | None
    contract_ref: RevisionRefV2
    quantity: int
    unit_price: Decimal
    observed_at_ms: int
    kind: Literal["trade", "cash_settlement"]
    settlement_ref: RevisionRefV2 | None


@dataclass(frozen=True)
class OptionFill:
    """One immutable trade fill, retained after close/restart/handback."""

    fill_ref: RevisionRefV2
    write_ref: RevisionRefV2
    contract_ref: RevisionRefV2
    quantity: int
    unit_price: Decimal
    observed_at_ms: int
    exits: tuple[OptionExit, ...]


@dataclass(frozen=True)
class OptionWrite:
    """Original possible write minus unique executions and proved releases.

    remaining_quantity excludes recorded trades. released_quantity needs the
    canonical resolution revision; ACK, rejection or cancellation is not proof.
    Independently executable exits have no inferred OCO/reduce-only guarantee.
    """

    write_ref: RevisionRefV2
    contract_ref: RevisionRefV2
    purpose: Literal["entry", "exit"]
    side: Literal["buy", "sell"]
    original_quantity: int
    remaining_quantity: int | None
    released_quantity: int
    resolution_ref: RevisionRefV2 | None
    premium_upper_bound: Decimal | None


@dataclass(frozen=True)
class OptionMark:
    """Owner-bound independent underlying and option marks and timestamps."""

    contract_ref: RevisionRefV2
    underlying_ref: RevisionRefV2
    source_ref: RevisionRefV2
    underlying_price: Decimal | None
    underlying_at_ms: int | None
    option_price: Decimal | None
    option_at_ms: int | None


@dataclass(frozen=True)
class StandaloneMargin:
    """Exact standalone allocation, never net portfolio margin or maximum loss.

    filled_units is currently open short units; possible_short_units includes
    independent possible shorts, including excess competing long exits. Floors
    and holds are separately resolved, never proportional allocations from a
    nonlinear basket quote. Unknown allocation is unavailable. The owner must
    durably increase its lifetime counter before allowing a later lower quote.
    """

    margin_ref: RevisionRefV2
    basis: OptionsBasis
    contract_ref: RevisionRefV2
    filled_units: int
    possible_short_units: int
    filled_floor: Decimal | None
    pending_hold: Decimal | None
    observed_at_ms: int
    allocation: Literal["exact_standalone_disjoint", "unavailable"]


@dataclass(frozen=True)
class OptionEntry:
    """One lifetime lineage, disjoint from every other entry and hold.

    committed_principal excludes pending holds and never decreases after close,
    profits or premium receipts. Long counters include every original premium;
    short counters include retained standalone margin high-water commitments.
    Current listing disagreement blocks calculation, never drops historical fills.
    """

    entry_ref: RevisionRefV2
    basis: OptionsBasis
    contract: OptionContract
    current_contract: OptionContract | None
    listing_observed_at_ms: int | None
    side: Literal["long", "short"]
    fills: tuple[OptionFill, ...]
    writes: tuple[OptionWrite, ...]
    mark: OptionMark | None
    margin: StandaloneMargin | None
    committed_principal: Decimal
    committed_fee_allowance: Decimal


@dataclass(frozen=True)
class OptionsCharge:
    """Known incurred amount; payment status is distinct from incurrence.

    payment_unknown still counts as incurred and as an unpaid exposure liability.
    A reversal is the observed current state of this same unique charge, not a
    second negative charge. Paid/reversed states require their evidence revision.
    Estimates/holds belong in the inclusive bound, never in incurred cashflows.
    """

    charge_ref: RevisionRefV2
    amount: Decimal | None
    payment: Literal["paid", "accrued_unpaid", "payment_unknown", "reversed", "unknown"]
    observed_at_ms: int
    payment_evidence_ref: RevisionRefV2 | None


@dataclass(frozen=True)
class OptionsFeeComponent:
    """Inclusive upper bound minus allocated incurred amounts, exactly once."""

    name: str
    basis: Literal["fill", "order", "day", "depository"]
    basis_ref: RevisionRefV2
    total_upper_bound: Decimal | None
    charges: tuple[OptionsCharge, ...]


@dataclass(frozen=True)
class OptionsFee:
    """Disjoint exact tariff allocation, not a tariff/eligibility attestation.

    close_filled includes existing filled exposure's closing reserve; close_possible
    is for possible new exposure only. Pending allowances never invent loss.
    Historical unpaid fees stay liabilities. Only nonempty wholly closed filled
    lineages permit their paid fees to leave exposure; no prorating is inferred.
    """

    allocation_ref: RevisionRefV2
    entry_ref: RevisionRefV2
    tariff_ref: RevisionRefV2
    phase: Literal["entry_filled", "close_filled", "entry_possible", "close_possible", "historical"]
    as_of_ms: int
    components: tuple[OptionsFeeComponent, ...]


@dataclass(frozen=True)
class OptionsInputs:
    """Complete lifetime history, current unresolved writes and fee census.

    The canonical owner must persist missing-trade high-water evidence, disjoint
    hold resolution, paid allocation and commitment history. This calculator
    cannot compare an earlier snapshot, infer completeness, or release a hold.
    """

    basis: OptionsBasis
    run_started_at_ms: int
    observed_at_ms: int
    coverage: Literal["complete", "partial", "unavailable", "conflicting"]
    allocation: Literal["exact_disjoint", "unavailable"]
    tariff_from_ms: int
    tariff_through_ms: int
    entries: tuple[OptionEntry, ...]
    fees: tuple[OptionsFee, ...]


@dataclass(frozen=True)
class OptionsLatch:
    """Existing policy-episode latch observation for a separate owner CAS."""

    scope: RunScopeV2
    policy_ref: RevisionRefV2
    revision: RevisionRefV2
    retired: bool


@dataclass(frozen=True)
class OptionsAssessment:
    """Arithmetic, basis pins and non-durable recommendation; never permission."""

    status: Literal["within_bounds", "breached", "unavailable"]
    reasons: tuple[str, ...]
    capital: Decimal | None
    exposure: Decimal | None
    net_pnl_after_fees_and_closing_reserve: Decimal | None
    loss: Decimal | None
    inputs: OptionsInputs | None
    evaluated_at_ms: int | None
    transition: LatchProposal
    required_lifetime_principal: tuple[tuple[RevisionRefV2, Decimal], ...]
    required_lifetime_fee_allowance: tuple[tuple[RevisionRefV2, Decimal], ...]


class _Unavailable(ValueError):
    pass


_T = TypeVar("_T")


def _arithmetic_context() -> Context:
    """Fully specified exact context, independent of mutable DefaultContext.

    60-digit monetary leaves, eight fractional places, safe integer quantities
    and bounded collections fit within this precision, including all totals.
    No rounding fallback is permitted; flags and every trap are explicit.
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


def _known(value: _T | None, reason: str = "evidence_missing") -> _T:
    if value is None:
        raise _Unavailable(reason)
    return value


_MODELS = (OptionsRiskPolicyV2, PositiveMoneyV2, RevisionRefV2, RunScopeV2)
_RECORDS = (
    OptionsBasis,
    OptionContract,
    OptionExit,
    OptionFill,
    OptionWrite,
    OptionMark,
    StandaloneMargin,
    OptionEntry,
    OptionsCharge,
    OptionsFeeComponent,
    OptionsFee,
    OptionsInputs,
    OptionsLatch,
)
_COMPONENTS = frozenset(("brokerage", "exchange", "sebi", "stt", "stamp", "gst", "delivery", "other"))

_Observation = (
    OptionsBasis
    | OptionContract
    | OptionExit
    | OptionFill
    | OptionWrite
    | OptionMark
    | StandaloneMargin
    | OptionEntry
    | OptionsCharge
    | OptionsFeeComponent
    | OptionsFee
    | OptionsInputs
    | OptionsLatch
)


def _canonical(value: object, schema: object) -> object:
    """Closed exact primitive grammar, before comparison/hash/serialisation.

    Return and USE newly validated values. Bypassed nested subclasses, arbitrary
    hooks, extra/private model state and missing storage never become evidence.
    The grammar comes from this module's classes, not from supplied objects.
    """
    origin = get_origin(schema)
    if origin is UnionType:
        options = get_args(schema)
        if value is None and any(t is type(None) for t in options):
            return None
        return _canonical(value, next(t for t in options if t is not type(None)))
    if origin is Literal:
        _require(type(value) is str and value in get_args(schema), "invalid_scalar")
        return value
    if origin is tuple:
        _require(type(value) is tuple and len(cast(tuple, value)) <= 10000, "invalid_structure")
        return tuple(_canonical(v, get_args(schema)[0]) for v in cast(tuple, value))
    if any(schema is t for t in (str, int, bool, Decimal)):
        _require(type(value) is schema, "invalid_scalar")
        if schema is int:
            _require(0 <= cast(int, value) <= 9007199254740991, "invalid_scalar")
        elif schema is Decimal:
            d = cast(Decimal, value)
            _require(d.is_finite() and not d.is_signed(), "invalid_scalar")
            _require(cast(int, d.as_tuple().exponent) >= -8 and d.adjusted() < 60, "invalid_scalar")
        return value
    model = any(schema is t for t in _MODELS)
    _require(model or any(schema is t for t in _RECORDS), "invalid_structure")
    _require(type(value) is schema, "invalid_structure")
    try:
        data = object.__getattribute__(value, "__dict__")
    except AttributeError as exc:
        raise _Unavailable("invalid_structure") from exc
    _require(type(data) is dict and all(type(k) is str for k in data), "invalid_structure")
    annotations = (
        {k: f.annotation for k, f in cast(type[BaseModel], schema).model_fields.items()}
        if model
        else {f.name: f.type for f in fields(cast(type[_Observation], schema))}
    )
    _require(data.keys() == annotations.keys(), "invalid_structure")
    if model:
        try:
            extra = object.__getattribute__(value, "__pydantic_extra__")
            private = object.__getattribute__(value, "__pydantic_private__")
            supplied = object.__getattribute__(value, "__pydantic_fields_set__")
        except AttributeError as exc:
            raise _Unavailable("invalid_structure") from exc
        _require(
            extra is None
            and private is None
            and type(supplied) is set
            and all(type(k) is str for k in supplied)
            and supplied <= annotations.keys(),
            "invalid_structure",
        )
    parsed = {k: _canonical(data[k], t) for k, t in annotations.items()}
    if model:
        try:
            return cast(type[BaseModel], schema).model_validate(parsed)
        except ValidationError as exc:
            raise _Unavailable("invalid_model") from exc
    return cast(Callable[..., _Observation], schema)(**parsed)


def _parsed(value: object, schema: type[_T]) -> _T | None:
    try:
        return cast(_T, _canonical(value, schema))
    except _Unavailable:
        return None


def _open(entry: OptionEntry) -> int:
    return sum(f.quantity - sum(x.quantity for x in f.exits) for f in entry.fills)


def _pending(entry: OptionEntry, side: str) -> int:
    return sum(_known(w.remaining_quantity, "unknown_possible_writes") for w in entry.writes if w.side == side)


def _fresh(at: int | None, inputs: OptionsInputs, now: int, age: int, reason: str) -> None:
    at = _known(at, reason)
    _require(inputs.run_started_at_ms <= at <= inputs.observed_at_ms and now - at <= age, reason)


def _unique(reference: RevisionRefV2, seen: set[str], reason: str) -> None:
    _require(reference.id not in seen, reason)
    seen.add(reference.id)


def _validate(policy: OptionsRiskPolicyV2, inputs: OptionsInputs, latch: OptionsLatch, now: int) -> None:
    _require(now > 0 and inputs.run_started_at_ms > 0, "invalid_time")
    basis = inputs.basis
    _require(
        basis.policy_ref == policy.policy_ref == latch.policy_ref
        and basis.scope == latch.scope
        and basis.fee_policy_ref == policy.fee_policy_ref,
        "scope_or_revision_mismatch",
    )
    _require(basis.scope.broker in ("dhan", "kotakneo") and policy.capital_cap.currency == "INR", "unsupported_profile")
    _require(inputs.coverage == "complete" and inputs.allocation == "exact_disjoint", "incomplete_or_unallocated")
    _require(
        inputs.run_started_at_ms <= inputs.observed_at_ms <= now
        and now - inputs.observed_at_ms <= policy.max_mark_age_ms,
        "source_time_unavailable",
    )
    _require(0 < inputs.tariff_from_ms <= now <= inputs.tariff_through_ms, "fee_date_unavailable")
    entries, executions, writes = set(), set(), set()
    contracts, tokens = {}, {}
    for entry in inputs.entries:
        _unique(entry.entry_ref, entries, "duplicate_entry")
        _require(entry.basis == basis, "scope_or_revision_mismatch")
        contract = entry.contract
        _require(
            contract.expiry_at_ms > 0
            and contract.strike > 0
            and contract.units_per_lot > 0
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}", contract.token) is not None
            and (contract.underlying, contract.exchange) in (("NIFTY", "NFO"), ("SENSEX", "BFO")),
            "contract_unavailable",
        )
        key = (contract.exchange, contract.product, contract.token)
        _require(
            contracts.get(contract.contract_ref.id, contract) == contract and tokens.get(key, contract) == contract,
            "contract_conflicting",
        )
        contracts[contract.contract_ref.id] = tokens[key] = contract
        write_map = {}
        for write in entry.writes:
            _unique(write.write_ref, writes, "duplicate_write")
            _require(write.contract_ref == contract.contract_ref, "contract_mismatch")
            _require(
                write.original_quantity > 0 and write.original_quantity % contract.units_per_lot == 0,
                "write_quantity_conflicting",
            )
            _known(write.remaining_quantity, "unknown_possible_writes")
            _require(not write.released_quantity or write.resolution_ref is not None, "unproved_release")
            expected_buy = (entry.side == "long") == (write.purpose == "entry")
            _require((write.side == "buy") == expected_buy, "write_direction_conflicting")
            if write.remaining_quantity and write.side == "buy":
                _known(write.premium_upper_bound, "unbounded_possible_fill")
            write_map[write.write_ref.id] = write
        filled_by_write = dict.fromkeys(write_map, 0)
        for fill in entry.fills:
            _unique(fill.fill_ref, executions, "duplicate_fill")
            _require(fill.quantity > 0 and fill.contract_ref == contract.contract_ref, "fill_conflicting")
            _require(
                inputs.run_started_at_ms <= fill.observed_at_ms <= inputs.observed_at_ms
                and fill.observed_at_ms < contract.expiry_at_ms,
                "fill_time_conflicting",
            )
            write = write_map.get(fill.write_ref.id)
            _require(
                write is not None and write.write_ref == fill.write_ref and write.purpose == "entry",
                "fill_write_mismatch",
            )
            filled_by_write[fill.write_ref.id] += fill.quantity
            for exit in fill.exits:
                _unique(exit.execution_ref, executions, "duplicate_exit")
                _require(
                    exit.quantity > 0
                    and exit.contract_ref == contract.contract_ref
                    and fill.observed_at_ms <= exit.observed_at_ms <= inputs.observed_at_ms,
                    "exit_conflicting",
                )
                if exit.kind == "cash_settlement":
                    _require(
                        exit.settlement_ref is not None
                        and exit.write_ref is None
                        and exit.observed_at_ms >= contract.expiry_at_ms,
                        "settlement_unavailable",
                    )
                else:
                    _require(exit.write_ref is not None and exit.settlement_ref is None, "exit_write_mismatch")
                    write = write_map.get(_known(exit.write_ref).id)
                    _require(
                        write is not None and write.write_ref == exit.write_ref and write.purpose == "exit",
                        "exit_write_mismatch",
                    )
                    filled_by_write[_known(exit.write_ref).id] += exit.quantity
            _require(sum(x.quantity for x in fill.exits) <= fill.quantity, "exit_quantity_conflicting")
        for write in entry.writes:
            _require(
                filled_by_write[write.write_ref.id] + _known(write.remaining_quantity) + write.released_quantity
                == write.original_quantity,
                "write_census_conflicting",
            )
        opened = _open(entry)
        buys, sells = _pending(entry, "buy"), _pending(entry, "sell")
        if opened or buys or sells:
            _require(entry.current_contract == contract, "listing_mismatch")
            _fresh(entry.listing_observed_at_ms, inputs, now, policy.max_mark_age_ms, "listing_time_unavailable")
            _require(now < contract.expiry_at_ms, "expiry_settlement_required")
            mark = _known(entry.mark, "mark_unavailable")
            _require(
                mark.contract_ref == contract.contract_ref and mark.underlying_ref == contract.underlying_ref,
                "mark_identity_mismatch",
            )
            _require(_known(mark.underlying_price, "mark_unavailable") > 0, "mark_unavailable")
            _fresh(mark.underlying_at_ms, inputs, now, policy.max_mark_age_ms, "underlying_time_unavailable")
            if opened:
                _known(mark.option_price, "mark_unavailable")
                _fresh(mark.option_at_ms, inputs, now, policy.max_mark_age_ms, "option_time_unavailable")
        if entry.side == "long":
            _require(
                entry.committed_principal >= sum((f.quantity * f.unit_price for f in entry.fills), Decimal(0)),
                "capital_commitment_conflicting",
            )
        elif entry.fills:
            _require(entry.committed_principal > 0, "capital_commitment_conflicting")
        short_open = opened if entry.side == "short" else 0
        short_possible = sells if entry.side == "short" else max(0, sells - opened)
        if short_open or short_possible or entry.margin is not None:
            margin = _known(entry.margin, "margin_unavailable")
            _require(margin.basis == basis and margin.contract_ref == contract.contract_ref, "margin_identity_mismatch")
            _require(
                margin.allocation == "exact_standalone_disjoint"
                and margin.filled_units == short_open
                and margin.possible_short_units == short_possible,
                "margin_allocation_unavailable",
            )
            floor, hold = (
                _known(margin.filled_floor, "margin_unavailable"),
                _known(margin.pending_hold, "margin_unavailable"),
            )
            _require(
                (floor > 0) == (short_open > 0) and (hold > 0) == (short_possible > 0), "margin_allocation_unavailable"
            )
            _fresh(margin.observed_at_ms, inputs, now, policy.max_mark_age_ms, "margin_time_unavailable")
    _validate_fees(inputs, now, policy.max_mark_age_ms)


def _validate_fees(inputs: OptionsInputs, now: int, age: int) -> None:
    entries = {e.entry_ref.id: e for e in inputs.entries}
    phases = {key: set() for key in entries}
    gross_charged = {key: Decimal(0) for key in entries}
    reversed_entries = set()
    allocations, bases, charges = set(), set(), set()
    for fee in inputs.fees:
        _unique(fee.allocation_ref, allocations, "duplicate_fee_allocation")
        entry = entries.get(fee.entry_ref.id)
        _require(
            entry is not None and entry.entry_ref == fee.entry_ref and fee.tariff_ref == inputs.basis.tariff_ref,
            "fee_reference_mismatch",
        )
        entry = _known(entry)
        _fresh(fee.as_of_ms, inputs, now, age, "fee_time_unavailable")
        _require(fee.as_of_ms >= inputs.tariff_from_ms, "fee_date_unavailable")
        phases[entry.entry_ref.id].add(fee.phase)
        _require(
            len(fee.components) == len(_COMPONENTS) and {c.name for c in fee.components} == _COMPONENTS,
            "fee_components_incomplete",
        )
        for component in fee.components:
            key = (component.name, component.basis_ref.id)
            _require(key not in bases, "fee_basis_unallocated")
            bases.add(key)
            upper = _known(component.total_upper_bound, "fees_unbounded")
            allocated = Decimal(0)
            for charge in component.charges:
                _unique(charge.charge_ref, charges, "duplicate_charge")
                amount = _known(charge.amount, "fees_unknown")
                gross_charged[entry.entry_ref.id] += amount
                if charge.payment == "reversed":
                    reversed_entries.add(entry.entry_ref.id)
                _require(charge.payment != "unknown", "fees_unknown")
                _require(
                    charge.payment not in ("paid", "reversed") or charge.payment_evidence_ref is not None,
                    "payment_unproved",
                )
                _require(
                    max(inputs.run_started_at_ms, inputs.tariff_from_ms) <= charge.observed_at_ms <= fee.as_of_ms,
                    "fee_date_unavailable",
                )
                if charge.payment != "reversed":
                    allocated += amount
            _require(allocated <= upper, "fee_upper_bound_conflicting")
            if fee.phase in ("entry_possible", "close_possible"):
                _require(
                    not component.charges and any(w.remaining_quantity for w in entry.writes), "fee_phase_conflicting"
                )
            elif fee.phase in ("entry_filled", "close_filled"):
                _require(bool(entry.fills), "fee_phase_conflicting")
                if fee.phase == "close_filled":
                    _require(upper == allocated or _open(entry) > 0, "unallocated_closing_reserve")
            else:
                _require(upper == allocated, "unallocated_historical_reserve")
    for entry in inputs.entries:
        required = {"entry_filled", "close_filled"} if entry.fills else set()
        if entry.entry_ref.id in reversed_entries:
            _require(entry.committed_fee_allowance >= gross_charged[entry.entry_ref.id], "fee_commitment_conflicting")
        opened = _open(entry)
        flip = _pending(entry, "sell" if entry.side == "long" else "buy") > opened
        if flip or any(w.purpose == "entry" and w.remaining_quantity for w in entry.writes):
            required.update(("entry_possible", "close_possible"))
        _require(required <= phases[entry.entry_ref.id], "fee_phases_incomplete")


def assess_options_risk(
    policy: OptionsRiskPolicyV2, inputs: OptionsInputs | None, latch: OptionsLatch | None, *, now_ms: int
) -> OptionsAssessment:
    """Use immutable owner evidence; this result grants nothing and writes nothing.

    Unavailable inputs cannot become zero. Structurally sound but stale/conflicting
    inputs remain attached so custody can retain the exact known trade obligations.
    Latch application, lifetime high-water persistence and revision CAS must occur
    separately at the existing canonical owner, including invocation rechecks.

    Args:
        policy: Explicit operator-valued options policy, never a cash-policy substitute.
        inputs: Immutable owner-resolved lifetime evidence, or unavailable evidence.
        latch: Prior owner-resolved retirement state, or unavailable state.
        now_ms: Exact evaluation timestamp in milliseconds.

    Returns:
        An assessment and proposed latch transition, retaining uncertainty and
        known obligations. No permission is issued and no state is written.
    """
    parsed_inputs, parsed_latch = _parsed(inputs, OptionsInputs), _parsed(latch, OptionsLatch)
    parsed_policy = _parsed(policy, OptionsRiskPolicyV2)
    parsed_now = _parsed(now_ms, int)
    try:
        policy = _known(parsed_policy, "invalid_policy")
        inputs = _known(parsed_inputs, "invalid_inputs")
        latch = _known(parsed_latch, "invalid_latch")
        now_ms = _known(parsed_now, "invalid_time")
        with localcontext(_arithmetic_context()):
            _validate(policy, inputs, latch, now_ms)
    except _Unavailable as exc:
        retired = None
        if type(latch) is OptionsLatch:
            data = object.__getattribute__(latch, "__dict__")
            if type(data) is dict and all(type(k) is str for k in data) and data.get("retired") is True:
                retired = True
        revision = None
        if (
            parsed_latch is not None
            and parsed_inputs is not None
            and parsed_policy is not None
            and parsed_latch.scope == parsed_inputs.basis.scope
            and parsed_latch.policy_ref == parsed_inputs.basis.policy_ref == parsed_policy.policy_ref
        ):
            revision, retired = parsed_latch.revision, parsed_latch.retired
        return OptionsAssessment(
            "unavailable",
            (str(exc),),
            None,
            None,
            None,
            None,
            parsed_inputs,
            parsed_now or None,
            LatchProposal("hold_unknown", retired, revision),
            (),
            (),
        )
    with localcontext(_arithmetic_context()):
        return _calculate(policy, inputs, latch, now_ms)


def _calculate(
    policy: OptionsRiskPolicyV2, inputs: OptionsInputs, latch: OptionsLatch, now_ms: int
) -> OptionsAssessment:
    capital = exposure = pnl = incurred = closing = Decimal(0)
    commitments = []
    fee_commitments = []
    for entry in inputs.entries:
        opened = _open(entry)
        sign = 1 if entry.side == "long" else -1
        buys = _pending(entry, "buy")
        sells = _pending(entry, "sell")
        quantity = max(abs(sign * opened + buys), abs(sign * opened - sells))
        exposure += quantity * _known(_known(entry.mark).underlying_price) if quantity else Decimal(0)
        principal = entry.committed_principal
        if entry.margin is not None:
            principal = max(principal, _known(entry.margin.filled_floor))
            capital += _known(entry.margin.pending_hold)
        commitments.append((entry.entry_ref, principal))
        capital += principal
        if entry.side == "long":
            capital += sum(
                _known(w.remaining_quantity) * _known(w.premium_upper_bound)
                for w in entry.writes
                if w.side == "buy" and w.remaining_quantity
            )
        elif buys > opened:
            capital += (buys - opened) * max(
                _known(w.premium_upper_bound) for w in entry.writes if w.side == "buy" and w.remaining_quantity
            )
        for fill in entry.fills:
            remaining = fill.quantity - sum(x.quantity for x in fill.exits)
            marked = remaining * _known(_known(entry.mark).option_price) if remaining else Decimal(0)
            pnl += sign * (
                sum((x.quantity * x.unit_price for x in fill.exits), Decimal(0))
                + marked
                - fill.quantity * fill.unit_price
            )
        filled_fees = possible_fees = Decimal(0)
        closed = bool(entry.fills) and opened == 0
        for allocation in inputs.fees:
            if allocation.entry_ref != entry.entry_ref:
                continue
            for component in allocation.components:
                allocated = sum((_known(c.amount) for c in component.charges if c.payment != "reversed"), Decimal(0))
                paid = sum((_known(c.amount) for c in component.charges if c.payment == "paid"), Decimal(0))
                upper = _known(component.total_upper_bound)
                remaining = upper - allocated
                incurred += allocated
                exposure += upper - (paid if closed else Decimal(0))
                if allocation.phase in ("entry_possible", "close_possible"):
                    possible_fees += upper
                else:
                    filled_fees += upper
                if allocation.phase == "close_filled":
                    closing += remaining
        fee_floor = max(entry.committed_fee_allowance, filled_fees)
        fee_commitments.append((entry.entry_ref, fee_floor))
        capital += fee_floor + possible_fees
    net = pnl - incurred - closing
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
    return OptionsAssessment(
        "breached" if reasons else "within_bounds",
        reasons,
        capital,
        exposure,
        net,
        loss,
        inputs,
        now_ms,
        transition,
        tuple(commitments),
        tuple(fee_commitments),
    )
