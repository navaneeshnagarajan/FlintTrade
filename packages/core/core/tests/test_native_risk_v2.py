"""Synthetic owner observations only; not Indian tariffs or broker evidence."""

from dataclasses import replace
from decimal import Decimal, localcontext
from typing import Literal

import pytest

from flinttrade_core.native_autonomy_contracts_v2 import PositiveMoneyV2, RevisionRefV2, RiskPolicyV2, RunScopeV2
from flinttrade_core.native_risk_v2 import (
    EntryObservation,
    FeeAllocation,
    FeeComponent,
    FeeSchedule,
    FilledLot,
    IncurredCharge,
    LatchObservation,
    RiskInputs,
    assess_risk,
)


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flinttrade_core.native_risk_v2 import RiskAssessment

D = Decimal
pytestmark = pytest.mark.unit
COMPONENTS = ("brokerage", "exchange", "sebi", "stt", "stamp", "gst", "delivery", "other")


def ref(name: "str") -> "RevisionRefV2":
    """Construct a synthetic revision reference with the fixture's fixed digest.

    Args:
        name: Synthetic reference identifier; the fixture supplies its fixed revision.

    Returns:
        Typed reference preserving the supplied identifier.
    """
    return RevisionRefV2(id=name, revision="a" * 64)


def sample() -> "tuple[RiskPolicyV2, RiskInputs, LatchObservation]":
    """Build a typed partial-fill scenario with explicitly synthetic fees and owner observations.

    Returns:
        Risk policy, complete inputs and prior latch observation for the fixed test clock.
    """
    scope = RunScopeV2(
        run_id="synthetic-run",
        operator="operator:" + "b" * 64,
        actor="bounded:synthetic-run",
        broker="synthetic",
        account_id="Exact.Account",
        environment="synthetic",
        registry_generation=1,
        binding_revision="c" * 64,
    )
    policy = RiskPolicyV2(
        policy_ref=ref("policy"),
        capital_basis="non_replenishing_fee_inclusive_commitments",
        exposure_basis="max_entry_cost_fresh_mark_plus_possible_fills_and_exit_fees",
        loss_basis="run_lifetime_net_realised_plus_unrealised_after_fees",
        threshold_action="latch_entry_retirement_and_broker_held_or_handback",
        capital_cap=PositiveMoneyV2(amount="2000", currency="INR"),
        exposure_cap=PositiveMoneyV2(amount="2000", currency="INR"),
        loss_action_threshold=PositiveMoneyV2(amount="100", currency="INR"),
        max_mark_age_ms=100,
        fee_policy_ref=ref("fee-policy"),
    )
    entry = EntryObservation(
        ref("entry"),
        scope,
        ref("source"),
        "INR",
        "cash_long",
        (FilledLot(ref("fill"), 10, D("100"), 4, D("480")),),
        4,
        D("105"),
        False,
        D("110"),
        950,
        D("1000"),
        D("12"),
    )
    schedule = FeeSchedule(
        ref("fee-policy"),
        ref("tariff"),
        ref("fee-source"),
        "INR",
        "cash_long",
        1,
        2000,
        True,
        "exact_component_upper_bounds",
    )

    def fee(phase, upper, paid):
        components = tuple(
            FeeComponent(
                name,
                "order",
                ref(phase + ":" + name),
                D(upper if name == "brokerage" else "0"),
                (IncurredCharge(ref("paid:" + phase), D(paid), 900),) if name == "brokerage" and paid != "0" else (),
            )
            for name in COMPONENTS
        )
        return FeeAllocation(ref(phase), ref("entry"), phase, ref("tariff"), 950, components)

    inputs = RiskInputs(
        scope,
        ref("policy"),
        ref("source"),
        ref("reservations"),
        ref("fee-policy"),
        1,
        950,
        "INR",
        True,
        True,
        (entry,),
        schedule,
        (
            fee("entry_filled", "2", "2"),
            fee("exit_filled", "10", "4"),
            fee("entry_pending", "3", "0"),
            fee("exit_pending", "5", "0"),
        ),
    )
    latch = LatchObservation(scope, ref("policy"), ref("latch"), False)
    return policy, inputs, latch


def assess(policy: "RiskPolicyV2", inputs: "RiskInputs", latch: "LatchObservation") -> "RiskAssessment":
    """Evaluate the supplied typed risk observations at the fixture's fixed clock.

    Args:
        policy: Explicit fee-inclusive policy for the synthetic run.
        inputs: Typed owner observations and dated fee allocations.
        latch: Prior owner-observed entry-retirement state.

    Returns:
        The pure risk assessment; it does not issue execution authority.
    """
    return assess_risk(policy, inputs, latch, now_ms=1000)


def test_exact_fee_inclusive_partial_fill_calculation() -> None:
    """Calculate exact fee-inclusive capital, exposure and loss for a partial fill."""
    result = assess(*sample())
    assert result.status == "within_bounds"
    assert (result.capital, result.exposure) == (D("1440"), D("1120"))
    assert result.net_pnl_after_fees_and_closing_reserve == D("128")
    assert result.loss == D("0")
    assert result.inputs == sample()[1]
    assert result.transition.action == "retain"


@pytest.mark.parametrize(
    ("field", "amount", "status", "reason"),
    [
        ("capital_cap", "1440", "within_bounds", None),
        ("capital_cap", "1439.99999999", "breached", "capital_cap"),
        ("capital_cap", "1421", "breached", "capital_cap"),
        ("exposure_cap", "1120", "within_bounds", None),
        ("exposure_cap", "1119.99999999", "breached", "exposure_cap"),
        ("exposure_cap", "1101", "breached", "exposure_cap"),
    ],
)
def test_exact_caps_and_fee_makes_otherwise_below_cap_fail(
    field: "str",
    amount: "str",
    status: "str",
    reason: "str | None",
) -> None:
    """Apply inclusive exact caps with fees retained at either side of the boundary.

    Args:
        field: Policy or observation field receiving the parameterised boundary value.
        amount: Exact decimal cap spelling used without float conversion.
        status: Expected risk assessment status.
        reason: Expected breached-cap reason, or None for the exact-cap positive.
    """
    policy, inputs, latch = sample()
    policy = RiskPolicyV2.model_validate({**policy.model_dump(), field: {"amount": amount, "currency": "INR"}})
    result = assess(policy, inputs, latch)
    assert result.status == status
    assert (reason in result.reasons) if reason else not result.reasons


@pytest.mark.parametrize(
    ("proceeds", "loss", "action"),
    [
        ("252.00000001", "99.99999999", "retain"),
        ("252", "100", "retire_entries_and_request_custody"),
        ("251.99999999", "100.00000001", "retire_entries_and_request_custody"),
    ],
)
def test_loss_threshold_includes_reserved_filled_exit_fees(proceeds: "str", loss: "str", action: "str") -> None:
    """Include reserved closing fees when deciding the loss-retirement transition.

    Args:
        proceeds: Exact realised proceeds used to straddle the loss threshold.
        loss: Expected exact fee-inclusive loss spelling.
        action: Expected retirement transition action.
    """
    policy, inputs, latch = sample()
    entry = inputs.entries[0]
    entry = replace(entry, lots=(replace(entry.lots[0], gross_exit_proceeds=D(proceeds)),))
    result = assess(policy, replace(inputs, entries=(entry,)), latch)
    assert result.loss == D(loss)
    assert result.transition.action == action
    assert result.transition.retired == (action != "retain")
    assert result.status == ("breached" if action != "retain" else "within_bounds")


def test_recovery_keeps_prior_retirement_without_reemitting_event() -> None:
    """Retain prior entry retirement without emitting the same transition again."""
    policy, inputs, latch = sample()
    result = assess(policy, inputs, replace(latch, retired=True))
    assert result.status == "within_bounds"
    assert result.transition.retired is True
    assert result.transition.action == "retain"


def assert_unavailable(result: "RiskAssessment", reason: "str") -> None:
    """Check unavailable arithmetic and a hold-unknown transition for the named refusal.

    Args:
        result: Risk result whose unavailable state and absent arithmetic are checked.
        reason: Expected refusal reason in the risk result.

    Raises:
        AssertionError: The result lacks the reason, exposes arithmetic or fails to hold unknown.
    """
    assert result.status == "unavailable"
    assert reason in result.reasons
    assert (result.capital, result.exposure, result.loss) == (None, None, None)
    assert result.transition.action == "hold_unknown"


@pytest.mark.parametrize("change", ["account", "source", "policy", "fee", "currency", "latch_scope", "latch_policy"])
def test_cross_scope_and_revision_inputs_never_create_capacity(change: "str") -> None:
    """Reject foreign scope or revision observations instead of creating risk capacity.

    Args:
        change: Named mutation applied to the otherwise valid control.
    """
    policy, inputs, latch = sample()
    entry = inputs.entries[0]
    if change == "account":
        entry = replace(entry, scope=entry.scope.model_copy(update={"account_id": "exact.account"}))
    elif change == "source":
        entry = replace(entry, source_ref=ref("other-source"))
    elif change == "currency":
        entry = replace(entry, currency="USD")
    elif change == "policy":
        inputs = replace(inputs, policy_ref=ref("other-policy"))
    elif change == "fee":
        inputs = replace(inputs, fee_policy_ref=ref("other-fee"))
    elif change == "latch_scope":
        latch = replace(
            latch, scope=latch.scope.model_copy(update={"run_id": "other", "actor": "bounded:other"}), retired=True
        )
    else:
        latch = replace(latch, policy_ref=ref("other-policy"), retired=True)
    result = assess(policy, replace(inputs, entries=(entry,)), latch)
    assert_unavailable(result, "scope_or_revision_mismatch")
    assert result.transition.retired == latch.retired


@pytest.mark.parametrize(
    ("field", "value", "available"),
    [
        ("mark_at_ms", 900, True),
        ("mark_at_ms", 899, False),
        ("mark_at_ms", 1001, False),
        ("mark_at_ms", None, False),
        ("mark", None, False),
        ("remaining_possible_quantity", None, False),
        ("remaining_price_upper_bound", None, False),
        ("unknown_possible_write", True, False),
    ],
)
def test_missing_stale_future_and_possible_write_observations(field: "str", value: "object", available: "bool") -> None:
    """Require fresh complete observations while retaining unknown possible writes.

    Args:
        field: Policy or observation field receiving the parameterised boundary value.
        value: Boundary or invalid input passed without coercion to the validator.
        available: Whether the supplied observation should permit an arithmetic result.
    """
    policy, inputs, latch = sample()
    entry = replace(inputs.entries[0], **{field: value})
    result = assess(policy, replace(inputs, entries=(entry,)), latch)
    if available:
        assert result.status == "within_bounds"
    else:
        assert result.status == "unavailable"
        assert result.capital is None
        assert result.inputs.entries[0] == entry
        assert result.transition.action == "hold_unknown"


@pytest.mark.parametrize(
    ("field", "value"), [("complete", False), ("allocated", False), ("observed_at_ms", 899), ("observed_at_ms", 1001)]
)
def test_incomplete_unallocated_or_stale_source_never_means_empty(field: "str", value: "object") -> None:
    """Keep incomplete, unallocated or stale source facts distinct from an empty run.

    Args:
        field: Policy or observation field receiving the parameterised boundary value.
        value: Boundary or invalid input passed without coercion to the validator.
    """
    policy, inputs, latch = sample()
    result = assess(policy, replace(inputs, **{field: value}), replace(latch, retired=True))
    assert result.status == "unavailable"
    assert result.transition.retired is True


@pytest.mark.parametrize("value", [True, 1.5, "100", D("NaN"), D("sNaN"), D("Infinity"), D("-1"), D("1e-9"), D("1e61")])
@pytest.mark.parametrize("field", ["mark", "committed_principal", "remaining_price_upper_bound"])
def test_money_scalars_are_exact_finite_bounded_decimals(field: "str", value: "object") -> None:
    """Reject coerced, non-finite or out-of-range monetary observations.

    Args:
        field: Policy or observation field receiving the parameterised boundary value.
        value: Boundary or invalid input passed without coercion to the validator.
    """
    policy, inputs, latch = sample()
    result = assess(policy, replace(inputs, entries=(replace(inputs.entries[0], **{field: value}),)), latch)
    assert_unavailable(result, "invalid_scalar")


@pytest.mark.parametrize("value", [True, 1.5, D("1"), -1, 9007199254740992])
def test_fractional_boolean_or_inexact_quantities_refuse(value: "object") -> None:
    """Reject fractional, boolean or inexact quantities rather than coercing them.

    Args:
        value: Boundary or invalid input passed without coercion to the validator.
    """
    policy, inputs, latch = sample()
    entry = replace(inputs.entries[0], remaining_possible_quantity=value)
    assert_unavailable(assess(policy, replace(inputs, entries=(entry,)), latch), "invalid_scalar")


@pytest.mark.parametrize("field", ["run_started_at_ms", "observed_at_ms"])
@pytest.mark.parametrize("value", [True, 0, 1.5])
def test_time_scalars_refuse_coercion(field: "str", value: "object") -> None:
    """Require supported integer time observations without coercion.

    Args:
        field: Policy or observation field receiving the parameterised boundary value.
        value: Boundary or invalid input passed without coercion to the validator.
    """
    policy, inputs, latch = sample()
    assert_unavailable(assess(policy, replace(inputs, **{field: value}), latch), "invalid_scalar")


def test_invalid_bypassed_policy_still_refuses() -> None:
    """Revalidate a policy even when its normal constructor checks were bypassed."""
    policy, inputs, latch = sample()
    policy = policy.model_copy(update={"max_mark_age_ms": True})
    assert_unavailable(assess(policy, inputs, latch), "invalid_policy")


@pytest.mark.parametrize(
    "change",
    [
        "missing_component",
        "duplicate_component",
        "missing_phase",
        "unknown_upper",
        "understated_upper",
        "duplicate_charge",
        "duplicate_basis",
        "wrong_tariff",
        "unknown_phase",
        "pending_incurred",
        "future_charge",
        "fee_before_tariff",
        "fee_after_tariff",
        "incomplete_tariff",
        "unsupported_basis",
        "unsupported_currency",
        "unsupported_family",
        "unresolved_allocation",
    ],
)
def test_strict_dated_complete_fee_allocations(change: "str") -> None:
    """Require complete, uniquely allocated fees within the declared tariff dates.

    Args:
        change: Named mutation applied to the otherwise valid control.
    """
    policy, inputs, latch = sample()
    fees = list(inputs.fees)
    fee = fees[0]
    component = fee.components[0]
    schedule = inputs.fee_schedule
    if change == "missing_component":
        fee = replace(fee, components=fee.components[:-1])
    elif change == "duplicate_component":
        fee = replace(fee, components=fee.components + (component,))
    elif change == "missing_phase":
        fees = fees[:-1]
    elif change == "unknown_upper":
        component = replace(component, total_upper_bound=None)
    elif change == "understated_upper":
        component = replace(component, total_upper_bound=D("1"))
    elif change == "duplicate_charge":
        component = replace(component, incurred=component.incurred * 2, total_upper_bound=D("4"))
    elif change == "duplicate_basis":
        component = replace(component, basis_ref=fees[1].components[0].basis_ref)
    elif change == "wrong_tariff":
        fee = replace(fee, tariff_ref=ref("foreign"))
    elif change == "unknown_phase":
        fee = replace(fee, phase="free")
    elif change == "pending_incurred":
        fee = replace(fee, phase="entry_pending")
    elif change == "future_charge":
        component = replace(component, incurred=(replace(component.incurred[0], charged_at_ms=1001),))
    elif change == "fee_before_tariff":
        schedule = replace(schedule, effective_from_ms=951)
    elif change == "fee_after_tariff":
        schedule = replace(schedule, effective_through_ms=949)
    elif change == "incomplete_tariff":
        schedule = replace(schedule, complete=False)
    elif change == "unsupported_basis":
        component = replace(component, basis="approximate_per_fill")
    elif change == "unsupported_currency":
        schedule = replace(schedule, currency="USD")
    elif change == "unsupported_family":
        schedule = replace(schedule, family="futures")
    else:
        schedule = replace(schedule, allocation="unallocated_per_day")
    if component != inputs.fees[0].components[0]:
        fee = replace(fee, components=(component, *fee.components[1:]))
    fees[0] = fee
    result = assess(policy, replace(inputs, fees=tuple(fees), fee_schedule=schedule), latch)
    assert result.status == "unavailable"
    assert result.capital is None


def test_paid_closing_charge_consumes_its_reserve_exactly_once() -> None:
    """Subtract a uniquely paid closing charge from its reserve once."""
    policy, inputs, latch = sample()
    before = assess(policy, inputs, latch)
    fee = inputs.fees[1]
    component = fee.components[0]
    component = replace(component, incurred=(*component.incurred, IncurredCharge(ref("new-charge"), D("2"), 950)))
    fee = replace(fee, components=(component, *fee.components[1:]))
    after = assess(policy, replace(inputs, fees=(inputs.fees[0], fee, *inputs.fees[2:])), latch)
    assert after.status == "within_bounds"
    assert (after.capital, after.exposure, after.net_pnl_after_fees_and_closing_reserve) == (
        before.capital,
        before.exposure,
        before.net_pnl_after_fees_and_closing_reserve,
    )


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_entry",
        "duplicate_fill",
        "exit_exceeds_fill",
        "proceeds_without_exit",
        "principal_erased",
        "unsupported_entry",
        "stale_fee",
    ],
)
def test_contradictions_and_duplicate_canonical_identities_refuse(change: "str") -> None:
    """Reject contradictory or duplicate canonical risk observations.

    Args:
        change: Named mutation applied to the otherwise valid control.
    """
    policy, inputs, latch = sample()
    entry = inputs.entries[0]
    if change == "duplicate_entry":
        inputs = replace(
            inputs, entries=(entry, replace(entry, entry_ref=entry.entry_ref.model_copy(update={"revision": "d" * 64})))
        )
    elif change == "duplicate_fill":
        inputs = replace(inputs, entries=(replace(entry, lots=entry.lots * 2, committed_principal=D("2000")),))
    elif change == "exit_exceeds_fill":
        inputs = replace(inputs, entries=(replace(entry, lots=(replace(entry.lots[0], exited_quantity=11),)),))
    elif change == "proceeds_without_exit":
        inputs = replace(inputs, entries=(replace(entry, lots=(replace(entry.lots[0], exited_quantity=0),)),))
    elif change == "principal_erased":
        inputs = replace(inputs, entries=(replace(entry, committed_principal=D("999")),))
    elif change == "unsupported_entry":
        inputs = replace(inputs, entries=(replace(entry, family="cash_short"),))
    else:
        fee = replace(inputs.fees[2], as_of_ms=899)
        inputs = replace(inputs, fees=(*inputs.fees[:2], fee, inputs.fees[3]))
    assert assess(policy, inputs, latch).status == "unavailable"


def zero_fees(inputs: "RiskInputs") -> "RiskInputs":
    """Copy risk inputs with zero synthetic fee bounds and no incurred charges.

    Args:
        inputs: Typed owner observations and dated fee allocations.

    Returns:
        New inputs retaining every non-fee observation from the original scenario.
    """
    return replace(
        inputs,
        fees=tuple(
            replace(f, components=tuple(replace(c, total_upper_bound=D("0"), incurred=()) for c in f.components))
            for f in inputs.fees
        ),
    )


@pytest.mark.parametrize(("mark", "expected"), [("90", "1040"), ("100", "1040"), ("110", "1120")])
def test_exposure_uses_cost_floor_not_discounted_mark(mark: "str", expected: "str") -> None:
    """Retain the entry-cost floor when a fresh market mark falls.

    Args:
        mark: Exact fresh mark spelling used to test the exposure cost floor.
        expected: Expected result value for this parameterised control.
    """
    policy, inputs, latch = sample()
    inputs = replace(inputs, entries=(replace(inputs.entries[0], mark=D(mark)),))
    assert assess(policy, inputs, latch).exposure == D(expected)


def test_partial_fill_moves_pending_once_without_freeing_or_doubling_capital() -> None:
    """Move a partial fill out of pending exposure exactly once without freeing capital."""
    policy, inputs, latch = sample()
    entry = inputs.entries[0]
    moved = replace(
        entry,
        remaining_possible_quantity=2,
        committed_principal=D("1210"),
        committed_fee_allowance=D("16"),
        lots=(*entry.lots, FilledLot(ref("next-fill"), 2, D("105"), 0, D("0"))),
    )
    fees = []
    for fee, amount in zip(inputs.fees, ("3.5", "12.5", "1.5", "2.5"), strict=True):
        fees.append(
            replace(fee, components=(replace(fee.components[0], total_upper_bound=D(amount)), *fee.components[1:]))
        )
    result = assess(policy, replace(inputs, entries=(moved,), fees=tuple(fees)), latch)
    assert result.status == "within_bounds"
    assert result.capital == D("1440")
    assert result.exposure == D("1120")
    assert result.net_pnl_after_fees_and_closing_reserve == D("135.5")


def test_profit_and_fee_reserve_release_cannot_recycle_permanent_capital() -> None:
    """Discharged closed fees leave exposure, never permanent capital or run loss."""
    policy, inputs, latch = sample()
    entry = inputs.entries[0]
    entry = replace(
        entry,
        lots=(replace(entry.lots[0], exited_quantity=10, gross_exit_proceeds=D("1000000")),),
        remaining_possible_quantity=0,
        remaining_price_upper_bound=None,
        mark=None,
        mark_at_ms=None,
    )
    fees = tuple(f for f in inputs.fees if "pending" not in f.phase)
    exit_fee = fees[1]
    exit_fee = replace(
        exit_fee, components=(replace(exit_fee.components[0], total_upper_bound=D("4")), *exit_fee.components[1:])
    )
    inputs = replace(inputs, entries=(entry,), fees=(fees[0], exit_fee))
    result = assess(policy, inputs, latch)
    assert result.status == "within_bounds"
    assert result.capital == D("1012")
    assert result.exposure == D("0")
    assert result.loss == D("0")
    assert assess(policy, inputs, replace(latch, retired=True)).transition.retired is True


def test_run_net_pnl_not_sum_of_losing_lots_and_pending_fees_not_loss() -> None:
    """Use run-net PnL without treating pending fees as realised loss."""
    policy, inputs, latch = sample()
    entry = inputs.entries[0]
    entry = replace(
        entry, committed_principal=D("1200"), lots=(*entry.lots, FilledLot(ref("losing-fill"), 1, D("200"), 1, D("0")))
    )
    pending = inputs.fees[2]
    pending = replace(
        pending, components=(replace(pending.components[0], total_upper_bound=D("300")), *pending.components[1:])
    )
    inputs = replace(inputs, entries=(entry,), fees=(*inputs.fees[:2], pending, inputs.fees[3]))
    result = assess(policy, inputs, latch)
    assert result.loss == D("72")
    assert result.transition.action == "retain"


def test_large_exact_quantity_and_transport_precision_ignore_ambient_context() -> None:
    """Keep exact large-quantity arithmetic independent of ambient decimal context."""
    policy, inputs, latch = sample()
    value = D("999999999999999999.99999999")
    total = D("9007199254740990999999999909928007.45259009")
    entry = replace(
        inputs.entries[0],
        remaining_possible_quantity=0,
        remaining_price_upper_bound=None,
        committed_principal=total,
        committed_fee_allowance=D("0"),
        mark=value,
        lots=(FilledLot(ref("large-fill"), 9007199254740991, value, 0, D("0")),),
    )
    inputs = zero_fees(replace(inputs, entries=(entry,), fees=inputs.fees[:2]))
    with localcontext() as context:
        context.prec = 6
        result = assess(policy, inputs, latch)
        assert context.prec == 6
    assert result.status == "breached"
    assert result.capital == total
    assert result.exposure == total
    assert result.loss == D("0")


def test_complete_empty_is_distinct_from_missing_evidence() -> None:
    """Accept complete empty evidence without equating absence with emptiness."""
    policy, inputs, latch = sample()
    empty = replace(inputs, entries=(), fees=())
    result = assess(policy, empty, latch)
    assert result.status == "within_bounds"
    assert (result.capital, result.exposure, result.loss) == (D("0"), D("0"), D("0"))
    assert assess(policy, replace(empty, complete=False), latch).status == "unavailable"


@pytest.mark.parametrize("missing", ["inputs", "latch"])
def test_missing_owner_observation_holds_unknown_not_a_new_episode(missing: "str") -> None:
    """Hold unknown when an owner observation is missing without creating a new episode.

    Args:
        missing: Owner observation or primitive fact deliberately omitted.
    """
    policy, inputs, latch = sample()
    result = assess(policy, None if missing == "inputs" else inputs, None if missing == "latch" else latch)
    assert result.status == "unavailable"
    assert result.transition.action == "hold_unknown"
    if missing == "latch":
        assert result.transition.retired is None
        assert result.transition.expected_revision is None


def test_unavailable_inputs_cannot_carry_coerced_retirement() -> None:
    """Refuse coerced retirement state even when arithmetic inputs are unavailable."""
    policy, inputs, latch = sample()
    result = assess(policy, inputs, replace(latch, retired=0))
    assert result.status == "unavailable"
    assert result.transition.retired is None


def test_calculation_has_no_io_no_authority_and_does_not_mutate_inputs() -> None:
    """Keep the risk calculation pure, authority-free and non-mutating."""
    import sys

    policy, inputs, latch = sample()
    events = []
    active = True

    def observe(event, args):
        if active and (event == "open" or event.startswith(("socket.", "sqlite3.", "subprocess.", "os."))):
            events.append(event)

    sys.addaudithook(observe)
    try:
        result = assess(policy, inputs, latch)
        refused = assess(policy, replace(inputs, complete=False), latch)
    finally:
        active = False
    assert events == []
    assert result.status == "within_bounds"
    assert refused.status == "unavailable"
    assert (policy, inputs, latch) == sample()
    assert not hasattr(result, "entry_permission")
    assert not hasattr(result, "grant")
    assert result.transition.expected_revision == latch.revision


@pytest.mark.parametrize("charge", ["0", "0.00000001"])
def test_eighteen_whole_eight_fraction_boundary_with_exact_fee(charge: "str") -> None:
    """Preserve exact fees at the supported whole and fractional precision boundary.

    Args:
        charge: Exact paid fee at the supported decimal precision boundary.
    """
    policy, inputs, latch = sample()
    value = D("999999999999999999.99999999")
    cap = PositiveMoneyV2(amount=str(value), currency="INR")
    policy = policy.model_copy(update={"capital_cap": cap, "exposure_cap": cap})
    entry = replace(
        inputs.entries[0],
        lots=(FilledLot(ref("boundary-fill"), 1, value, 0, D("0")),),
        committed_principal=value,
        committed_fee_allowance=D("0"),
        remaining_possible_quantity=0,
        remaining_price_upper_bound=None,
        mark=value,
    )
    inputs = zero_fees(replace(inputs, entries=(entry,), fees=inputs.fees[:2]))
    fee = inputs.fees[1]
    fee = replace(fee, components=(replace(fee.components[0], total_upper_bound=D(charge)), *fee.components[1:]))
    result = assess(policy, replace(inputs, fees=(inputs.fees[0], fee)), latch)
    assert result.capital == (value if charge == "0" else D("1000000000000000000"))
    assert result.status == ("within_bounds" if charge == "0" else "breached")


@pytest.mark.parametrize("field", ["total_upper_bound", "incurred"])
@pytest.mark.parametrize("bad", [True, 0.1, D("NaN"), D("Infinity"), D("-1")])
def test_fee_values_have_no_coercion_or_nonfinite_escape(field: "str", bad: "object") -> None:
    """Reject coerced and non-finite fee values at the typed observation boundary.

    Args:
        field: Policy or observation field receiving the parameterised boundary value.
        bad: Deliberately invalid input; no canonical production type is implied.
    """
    policy, inputs, latch = sample()
    fee = inputs.fees[0]
    component = fee.components[0]
    if field == "incurred":
        component = replace(component, incurred=(replace(component.incurred[0], amount=bad),))
    else:
        component = replace(component, total_upper_bound=bad)
    fee = replace(fee, components=(component, *fee.components[1:]))
    assert_unavailable(assess(policy, replace(inputs, fees=(fee, *inputs.fees[1:])), latch), "invalid_scalar")


@pytest.mark.parametrize("change", ["reference", "entries_list", "lots_list", "fees_list", "schedule_none"])
def test_closed_typed_observation_shapes(change: "str") -> None:
    """Refuse bypassed container shapes rather than accept untyped observations.

    Args:
        change: Named mutation applied to the otherwise valid control.
    """
    policy, inputs, latch = sample()
    if change == "reference":
        inputs = replace(inputs, source_ref=ref("source").model_copy(update={"revision": "x"}))
    elif change == "entries_list":
        inputs = replace(inputs, entries=list(inputs.entries))
    elif change == "lots_list":
        inputs = replace(inputs, entries=(replace(inputs.entries[0], lots=list(inputs.entries[0].lots)),))
    elif change == "fees_list":
        inputs = replace(inputs, fees=list(inputs.fees))
    else:
        inputs = replace(inputs, fee_schedule=None)
    assert assess(policy, inputs, latch).status == "unavailable"


@pytest.mark.parametrize("where", ["input", "entry", "schedule"])
def test_currency_requires_plain_typed_text(where: "str") -> None:
    """Reject string-subclass currency values in each observation container.

    Args:
        where: Observation container carrying the non-plain currency value.
    """
    class Text(str):
        pass

    policy, inputs, latch = sample()
    if where == "input":
        inputs = replace(inputs, currency=Text("INR"))
    elif where == "entry":
        inputs = replace(inputs, entries=(replace(inputs.entries[0], currency=Text("INR")),))
    else:
        inputs = replace(inputs, fee_schedule=replace(inputs.fee_schedule, currency=Text("INR")))
    assert assess(policy, inputs, latch).status == "unavailable"


@pytest.mark.parametrize("setting", ["emax", "emin", "rounding", "traps", "clamp", "all"])
def test_mutable_decimal_template_cannot_change_exact_assessment(setting: str) -> None:
    """Keep exact results independent of every context-construction template field."""
    import decimal

    policy, inputs, latch = sample()
    # An eighth-place amount exercises Emin as well as the large Emax control.
    fee = inputs.fees[0]
    component = replace(fee.components[0], total_upper_bound=D("2.00000001"))
    inputs = replace(inputs, fees=(replace(fee, components=(component, *fee.components[1:])), *inputs.fees[1:]))
    expected = assess(policy, inputs, latch)
    assert expected.exposure == D("1120.00000001")
    saved = decimal.DefaultContext.copy()
    ambient = decimal.getcontext().copy()
    try:
        if setting in ("emax", "all"):
            decimal.DefaultContext.Emax = 1
        if setting in ("emin", "all"):
            decimal.DefaultContext.Emin = -1
        if setting in ("rounding", "all"):
            decimal.DefaultContext.rounding = decimal.ROUND_UP
        if setting in ("traps", "all"):
            for signal in decimal.DefaultContext.traps:
                decimal.DefaultContext.traps[signal] = True
                decimal.DefaultContext.flags[signal] = True
        if setting in ("clamp", "all"):
            decimal.DefaultContext.clamp = 1
        if setting == "all":
            decimal.DefaultContext.prec = 1
            decimal.DefaultContext.capitals = 0
        template = repr(decimal.DefaultContext)
        assert assess(policy, inputs, latch) == expected
        assert repr(decimal.DefaultContext) == template
        assert repr(decimal.getcontext()) == repr(ambient)
    finally:
        for field in ("prec", "rounding", "Emin", "Emax", "capitals", "clamp"):
            setattr(decimal.DefaultContext, field, getattr(saved, field))
        decimal.DefaultContext.traps = saved.traps.copy()
        decimal.DefaultContext.flags = saved.flags.copy()
    assert assess(policy, inputs, latch) == expected


def test_decimal_template_before_cold_import_is_not_captured() -> None:
    """A fresh interpreter must not cache a context made from a poisoned template."""
    import subprocess
    import sys

    code = (
               "import decimal\n"
               "import runpy\n"
               "import sys\n"
               "saved = decimal.DefaultContext.copy()\n"
               "try:\n"
               "    decimal.DefaultContext.prec = 1\n"
               "    decimal.DefaultContext.Emax = 1\n"
               "    decimal.DefaultContext.Emin = -1\n"
               "    decimal.DefaultContext.rounding = decimal.ROUND_UP\n"
               "    decimal.DefaultContext.clamp = 1\n"
               "    for signal in decimal.DefaultContext.traps:\n"
               "        decimal.DefaultContext.traps[signal] = True\n"
               "        decimal.DefaultContext.flags[signal] = True\n"
               "    sample = runpy.run_path(sys.argv[1])\n"
               "    result = sample[\"assess\"](*sample[\"sample\"]())\n"
               "    assert result.status == \"within_bounds\"\n"
               "    assert (result.capital, result.exposure, result.net_pnl_after_fees_and_closing_reserve,\n"
               "        result.loss) == tuple(map(decimal.Decimal, (\"1440\", \"1120\", \"128\", \"0\")))\n"
               "finally:\n"
               "    for field in (\"prec\", \"rounding\", \"Emin\", \"Emax\", \"capitals\", \"clamp\"):\n"
               "        setattr(decimal.DefaultContext, field, getattr(saved, field))\n"
               "    decimal.DefaultContext.traps = saved.traps.copy()\n"
               "    decimal.DefaultContext.flags = saved.flags.copy()\n"
           )
    result = subprocess.run([sys.executable, "-c", code, __file__], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


class _EqualText(str):
    """A bypassed leaf that records an attempt to compare foreign identity."""

    hooks: list[str] = []

    def __eq__(self, other: object) -> bool:
        """Record and falsify an unsafe identity comparison."""
        self.hooks.append("equality")
        return True

    __hash__ = str.__hash__


class _AgeInteger(int):
    """A bypassed freshness limit that defeats the reverse comparison."""

    hooks: list[str] = []

    def __ge__(self, other: object) -> bool:
        """Record and falsify an unsafe age comparison."""
        self.hooks.append("age")
        return True


class _DistinctHashText(str):
    """A duplicate identity whose hash attempts to hide it from a census."""

    hooks: list[str] = []

    def __hash__(self) -> int:
        """Record an unsafe hash and return a different bucket."""
        self.hooks.append("hash")
        return str.__hash__(self) + 1


@pytest.mark.parametrize(
    "kind",
    [
        "account",
        "entry-source-id",
        "input-source-id",
        "entry-source-revision",
        "max-age",
        "latch-scope",
        "latch-policy",
        "charge-id",
        "component-basis-id",
    ],
)
def test_nested_bypassed_identity_refuses_without_hooks(kind: str) -> None:
    """Refuse all nested identity/freshness bypasses beside plain negative controls."""
    policy, inputs, latch = sample()
    if kind == "max-age":
        policy = policy.model_copy(update={"max_mark_age_ms": 200})
        inputs = replace(
            inputs,
            observed_at_ms=800,
            entries=(replace(inputs.entries[0], mark_at_ms=800),),
            fees=tuple(
                replace(
                    fee,
                    as_of_ms=800,
                    components=tuple(
                        replace(c, incurred=tuple(replace(charge, charged_at_ms=800) for charge in c.incurred))
                        for c in fee.components
                    ),
                )
                for fee in inputs.fees
            ),
        )
    assert assess(policy, inputs, latch).status == "within_bounds"
    plain_policy, plain_inputs, plain_latch = policy, inputs, latch
    if kind == "account":
        plain_scope = inputs.scope.model_copy(update={"account_id": "Foreign.Account"})
        plain_inputs = replace(inputs, entries=(replace(inputs.entries[0], scope=plain_scope),))
        inputs = replace(
            inputs,
            entries=(
                replace(
                    inputs.entries[0],
                    scope=plain_scope.model_copy(update={"account_id": _EqualText("Foreign.Account")}),
                ),
            ),
        )
    elif kind in ("entry-source-id", "entry-source-revision", "input-source-id"):
        field = "revision" if kind == "entry-source-revision" else "id"
        value = "d" * 64 if field == "revision" else "foreign-snapshot"
        plain = inputs.source_ref.model_copy(update={field: value})
        hostile = plain.model_copy(update={field: _EqualText(value)})
        if kind == "input-source-id":
            plain_inputs = replace(inputs, source_ref=plain)
            inputs = replace(inputs, source_ref=hostile)
        else:
            plain_inputs = replace(inputs, entries=(replace(inputs.entries[0], source_ref=plain),))
            inputs = replace(inputs, entries=(replace(inputs.entries[0], source_ref=hostile),))
    elif kind == "max-age":
        plain_policy = policy.model_copy(update={"max_mark_age_ms": 1})
        policy = policy.model_copy(update={"max_mark_age_ms": _AgeInteger(1)})
    elif kind == "latch-scope":
        plain_latch = replace(latch, scope=latch.scope.model_copy(update={"account_id": "Foreign.Account"}))
        latch = replace(latch, scope=latch.scope.model_copy(update={"account_id": _EqualText("Foreign.Account")}))
    elif kind == "latch-policy":
        plain_latch = replace(latch, policy_ref=ref("foreign-policy"))
        latch = replace(latch, policy_ref=ref("foreign-policy").model_copy(update={"id": _EqualText("foreign-policy")}))
    else:
        component = inputs.fees[1].components[0]
        if kind == "charge-id":
            existing = inputs.fees[0].components[0].incurred[0].charge_ref
            plain_component = replace(component, incurred=(replace(component.incurred[0], charge_ref=existing),))
            hostile = existing.model_copy(update={"id": _DistinctHashText(existing.id)})
            component = replace(component, incurred=(replace(component.incurred[0], charge_ref=hostile),))
        else:
            existing = inputs.fees[0].components[0].basis_ref
            plain_component = replace(component, basis_ref=existing)
            component = replace(component, basis_ref=existing.model_copy(update={"id": _DistinctHashText(existing.id)}))
        fee = inputs.fees[1]
        plain_inputs = replace(
            inputs,
            fees=(inputs.fees[0], replace(fee, components=(plain_component, *fee.components[1:])), *inputs.fees[2:]),
        )
        inputs = replace(
            inputs, fees=(inputs.fees[0], replace(fee, components=(component, *fee.components[1:])), *inputs.fees[2:])
        )
    assert assess(plain_policy, plain_inputs, plain_latch).status == "unavailable"
    _EqualText.hooks.clear()
    _AgeInteger.hooks.clear()
    _DistinctHashText.hooks.clear()
    result = assess(policy, inputs, latch)
    assert result.status == "unavailable"
    assert (result.capital, result.exposure, result.net_pnl_after_fees_and_closing_reserve, result.loss) == (None,) * 4
    assert result.transition.action == "hold_unknown"
    assert _EqualText.hooks == _AgeInteger.hooks == _DistinctHashText.hooks == []


@pytest.mark.parametrize("early", ["ordinary", "incomplete", "missing-policy"])
@pytest.mark.parametrize("where", ["input-reference", "fee-reference", "latch-revision", "latch-scope"])
def test_unavailable_result_does_not_endorse_invalid_nested_evidence(early: str, where: str) -> None:
    """Scan returned evidence even when an earlier prerequisite already refuses."""
    policy, inputs, latch = sample()
    latch = replace(latch, retired=True)
    if early == "incomplete":
        inputs = replace(inputs, complete=False)
    elif early == "missing-policy":
        policy = None
    bad = ref("bad").model_copy(update={"revision": _EqualText("not-a-digest")})
    if where == "input-reference":
        inputs = replace(inputs, source_ref=bad)
    elif where == "fee-reference":
        fee = inputs.fees[-1]
        inputs = replace(inputs, fees=(*inputs.fees[:-1], replace(fee, tariff_ref=bad)))
    elif where == "latch-revision":
        latch = replace(latch, revision=bad)
    else:
        latch = replace(latch, scope=latch.scope.model_copy(update={"account_id": _EqualText("Foreign.Account")}))
    _EqualText.hooks.clear()
    result = assess(policy, inputs, latch)
    assert result.status == "unavailable"
    assert result.transition.action == "hold_unknown"
    assert result.transition.retired is True
    if where.startswith("latch"):
        assert result.transition.expected_revision is None
    else:
        assert result.inputs is None
    assert _EqualText.hooks == []


def test_bypassed_values_are_not_serialised_compared_or_converted() -> None:
    """Reject arbitrary nested objects without equality, hash, repr or copy hooks."""
    hits: list[str] = []

    class HostileMeta(type):
        """Expose equality-based type allowlists without granting membership."""

        def __eq__(cls, other: object) -> bool:
            """Record an unsafe type comparison."""
            hits.append("type equality")
            return True

    class Hostile(metaclass=HostileMeta):
        """Expose unsafe serialisation and normalisation attempts."""

        def __repr__(self) -> str:
            """Record unexpected diagnostic stringification."""
            hits.append("repr")
            return "hostile"

        def __str__(self) -> str:
            """Record unexpected text normalisation."""
            hits.append("str")
            return "source"

        def __int__(self) -> int:
            """Record unexpected integer normalisation."""
            hits.append("int")
            return 1

        def __deepcopy__(self, memo: dict[int, object]) -> object:
            """Record unexpected arbitrary copying."""
            hits.append("copy")
            return self

    policy, inputs, latch = sample()
    inputs = replace(inputs, source_ref=inputs.source_ref.model_copy(update={"id": Hostile()}))
    result = assess(policy, inputs, latch)
    assert result.status == "unavailable"
    assert result.inputs is None
    assert hits == []


@pytest.mark.parametrize("where", ["money", "policy", "scope-extra", "scope-private", "reference-extra"])
def test_nested_models_have_only_plain_complete_fields(where: str) -> None:
    """Do not let bypassed fields or Pydantic equality metadata enter evidence."""
    policy, inputs, latch = sample()
    if where == "money":
        policy = policy.model_copy(
            update={"capital_cap": policy.capital_cap.model_copy(update={"amount": _EqualText("2000")})}
        )
    elif where == "policy":
        policy = policy.model_copy(update={"capital_basis": _EqualText("non_replenishing_fee_inclusive_commitments")})
    elif where == "reference-extra":
        inputs = replace(inputs, source_ref=inputs.source_ref.model_copy(update={"undeclared": _EqualText("source")}))
    elif where == "scope-extra":
        inputs = replace(inputs, scope=inputs.scope.model_copy(update={"undeclared": _EqualText("source")}))
    else:
        scope = inputs.scope.model_copy()
        object.__setattr__(scope, "__pydantic_private__", {"unchecked": _EqualText("source")})
        inputs = replace(inputs, scope=scope)
    _EqualText.hooks.clear()
    result = assess(policy, inputs, latch)
    assert result.status == "unavailable"
    if where not in ("policy", "money"):
        assert result.inputs is None
    assert _EqualText.hooks == []


@pytest.mark.parametrize("metadata", ["__pydantic_extra__", "__pydantic_private__", "__pydantic_fields_set__"])
@pytest.mark.parametrize("where", ["policy", "input-reference", "latch-revision"])
def test_missing_model_storage_refuses_without_an_exception(metadata: str, where: str) -> None:
    """An exact model with deleted validation storage is still bypassed evidence."""
    policy, inputs, latch = sample()
    if where == "policy":
        damaged = policy.model_copy()
        policy = damaged
    elif where == "input-reference":
        damaged = inputs.source_ref.model_copy()
        inputs = replace(inputs, source_ref=damaged)
    else:
        damaged = latch.revision.model_copy()
        latch = replace(latch, revision=damaged, retired=True)
    object.__delattr__(damaged, metadata)
    result = assess(policy, inputs, latch)
    assert result.status == "unavailable"
    assert result.transition.action == "hold_unknown"
    if where == "input-reference":
        assert result.inputs is None
    elif where == "latch-revision":
        assert result.transition.expected_revision is None
        assert result.transition.retired is True


def test_invalid_evaluation_time_is_not_returned_as_trusted_time() -> None:
    """Keep an invalid clock observation unknown rather than retaining its hooks."""
    policy, inputs, latch = sample()
    _AgeInteger.hooks.clear()
    result = assess_risk(policy, inputs, latch, now_ms=_AgeInteger(1000))
    assert result.status == "unavailable"
    assert result.evaluated_at_ms is None
    assert _AgeInteger.hooks == []


def _closed_observation(inputs: RiskInputs, *, pending: bool = False) -> RiskInputs:
    """Close the synthetic filled position while retaining its exact paid charges."""
    entry = inputs.entries[0]
    entry = replace(
        entry,
        lots=(replace(entry.lots[0], exited_quantity=10, gross_exit_proceeds=D("980")),),
        remaining_possible_quantity=4 if pending else 0,
        remaining_price_upper_bound=D("105") if pending else None,
        mark=D("110") if pending else None,
        mark_at_ms=950 if pending else None,
    )
    exit_fee = inputs.fees[1]
    exit_fee = replace(
        exit_fee, components=(replace(exit_fee.components[0], total_upper_bound=D("4")), *exit_fee.components[1:])
    )
    return replace(inputs, entries=(entry,), fees=(inputs.fees[0], exit_fee, *(inputs.fees[2:] if pending else ())))


@pytest.mark.parametrize("pending", [False, True])
@pytest.mark.parametrize("unpaid", ["0", "1.25"])
def test_closed_paid_fees_leave_exposure_not_capital_loss_or_unpaid_liabilities(pending: bool, unpaid: str) -> None:
    """Exclude only discharged filled fees, preserving pending holds and unpaid bounds."""
    from fractions import Fraction

    policy, inputs, latch = sample()
    inputs = _closed_observation(inputs, pending=pending)
    fee = inputs.fees[0]
    inputs = replace(
        inputs,
        fees=(
            replace(
                fee, components=(replace(fee.components[0], total_upper_bound=D("2") + D(unpaid)), *fee.components[1:])
            ),
            *inputs.fees[1:],
        ),
    )
    policy = policy.model_copy(
        update={"exposure_cap": PositiveMoneyV2(amount="500" if pending else "5", currency="INR")}
    )
    result = assess(policy, inputs, latch)
    # Independent surviving-inventory and cashflow sheet, not calculator helpers.
    expected_exposure = (4 * Fraction("110") + Fraction("8") if pending else Fraction(0)) + Fraction(unpaid)
    expected_capital = (
        Fraction("1000") + Fraction("12") + (4 * Fraction("105") + Fraction("8") if pending else Fraction(0))
    )
    expected_net = Fraction("980") - 10 * Fraction("100") - Fraction("2") - Fraction("4")
    assert result.status == "within_bounds"
    assert result.exposure == expected_exposure
    assert result.capital == expected_capital
    assert result.net_pnl_after_fees_and_closing_reserve == expected_net
    assert result.loss == -expected_net
    assert result.transition.action == "retain"
    assert assess(policy, inputs, replace(latch, retired=True)).transition.retired is True


def _distinct_entry(inputs: RiskInputs, identity: str) -> RiskInputs:
    """Give an independent synthetic entry a disjoint, opaque evidence census."""
    entry = replace(
        inputs.entries[0],
        entry_ref=ref(identity),
        lots=tuple(
            replace(lot, fill_ref=ref(identity + ":lot:" + str(index)))
            for index, lot in enumerate(inputs.entries[0].lots)
        ),
    )
    fees = tuple(
        replace(
            fee,
            entry_ref=entry.entry_ref,
            allocation_ref=ref(identity + ":allocation:" + str(index)),
            components=tuple(
                replace(
                    component,
                    basis_ref=ref(identity + ":basis:" + str(index) + ":" + component.name),
                    incurred=tuple(
                        replace(
                            charge,
                            charge_ref=ref(identity + ":charge:" + str(index) + ":" + component.name + ":" + str(n)),
                        )
                        for n, charge in enumerate(component.incurred)
                    ),
                )
                for component in fee.components
            ),
        )
        for index, fee in enumerate(inputs.fees)
    )
    return replace(inputs, entries=(entry,), fees=fees)


def test_mixed_closed_open_and_pending_entries_use_surviving_exposure_only() -> None:
    """Exclude the exactly attributed closed six, not active fees or pending holds."""
    from fractions import Fraction

    policy, inputs, latch = sample()
    closed = _distinct_entry(_closed_observation(inputs), "opaque-closed")
    pending = _distinct_entry(
        replace(
            inputs,
            entries=(replace(inputs.entries[0], lots=(), committed_principal=D("0"), committed_fee_allowance=D("0")),),
            fees=inputs.fees[2:],
        ),
        "opaque-pending",
    )
    combined = replace(
        inputs,
        entries=(*inputs.entries, *closed.entries, *pending.entries),
        fees=(*inputs.fees, *closed.fees, *pending.fees),
    )
    policy = policy.model_copy(
        update={
            "capital_cap": PositiveMoneyV2(amount="5000", currency="INR"),
            "exposure_cap": PositiveMoneyV2(amount="5000", currency="INR"),
        }
    )
    result = assess(policy, combined, latch)
    assert result.status == "within_bounds"
    # Surviving A inventory 6*110, two pending censuses 4*110 each, fees 20+8.
    assert result.exposure == 6 * Fraction("110") + 8 * Fraction("110") + Fraction("28")
    # Lifetime commitments and disjoint pending envelopes; no proceeds credit.
    assert result.capital == Fraction("1440") + Fraction("1012") + Fraction("428")
    assert result.net_pnl_after_fees_and_closing_reserve == Fraction("128") - Fraction("26")
    assert result.loss == 0


@pytest.mark.parametrize("basis", ["fill", "order", "day", "depository"])
@pytest.mark.parametrize("state", ["closed", "partial", "no-filled-evidence"])
def test_historical_fee_exclusion_needs_closed_entry_evidence(
    basis: Literal["fill", "order", "day", "depository"], state: str
) -> None:
    """Historical labels and charge-basis IDs do not supply missing position allocation."""
    policy, inputs, latch = sample()
    if state == "closed":
        inputs = _closed_observation(inputs)
    elif state == "no-filled-evidence":
        inputs = replace(
            inputs,
            entries=(
                replace(
                    inputs.entries[0],
                    lots=(),
                    remaining_possible_quantity=0,
                    remaining_price_upper_bound=None,
                    mark=None,
                    mark_at_ms=None,
                    committed_principal=D("0"),
                ),
            ),
            fees=(),
        )
    before = assess(policy, inputs, latch)
    assert before.status == "within_bounds"
    components = tuple(
        FeeComponent(
            name,
            basis,
            ref("opaque-historical-basis:" + name),
            D("0.75") if name == "brokerage" else D("0"),
            (IncurredCharge(ref("historical-paid"), D("0.75"), 900),) if name == "brokerage" else (),
        )
        for name in COMPONENTS
    )
    historical = FeeAllocation(
        ref("historical-allocation"), inputs.entries[0].entry_ref, "historical", ref("tariff"), 950, components
    )
    result = assess(policy, replace(inputs, fees=(*inputs.fees, historical)), latch)
    assert result.status == "within_bounds"
    assert before.exposure is not None and before.capital is not None
    assert before.net_pnl_after_fees_and_closing_reserve is not None
    assert result.net_pnl_after_fees_and_closing_reserve is not None
    assert result.exposure == before.exposure + (D("0") if state == "closed" else D("0.75"))
    assert result.capital == before.capital + (D("0.75") if state == "partial" else D("0"))
    assert result.net_pnl_after_fees_and_closing_reserve == before.net_pnl_after_fees_and_closing_reserve - D("0.75")
    assert result.loss == max(D("0"), -result.net_pnl_after_fees_and_closing_reserve)


@pytest.mark.parametrize("basis", ["fill", "order", "day", "depository"])
def test_closed_and_open_allocations_cannot_share_an_unresolved_charge_basis(basis: str) -> None:
    """Retain refusal rather than subtract a shared fee from a closed entry twice."""
    policy, inputs, latch = sample()
    closed = _distinct_entry(_closed_observation(inputs), "closed-shared-control")
    left, right = inputs.fees[0], closed.fees[0]
    shared = ref("same-charge-basis")
    left = replace(left, components=(replace(left.components[0], basis=basis, basis_ref=shared), *left.components[1:]))
    right = replace(
        right, components=(replace(right.components[0], basis=basis, basis_ref=shared), *right.components[1:])
    )
    combined = replace(
        inputs, entries=(*inputs.entries, *closed.entries), fees=(left, *inputs.fees[1:], right, *closed.fees[1:])
    )
    result = assess(policy, combined, latch)
    assert_unavailable(result, "fee_basis_unallocated")
    assert result.transition.action == "hold_unknown"


def test_partial_entry_does_not_infer_lot_fee_split_from_basis_identity() -> None:
    """Keep unresolved paid fees when any filled quantity remains open."""
    policy, inputs, latch = sample()
    entry = inputs.entries[0]
    closed_lot = FilledLot(ref("basis-is-not-allocation"), 1, D("50"), 1, D("60"))
    entry = replace(entry, lots=(*entry.lots, closed_lot), committed_principal=D("1050"))
    fee = inputs.fees[0]
    fee = replace(
        fee, components=(replace(fee.components[0], basis="fill", basis_ref=closed_lot.fill_ref), *fee.components[1:])
    )
    result = assess(policy, replace(inputs, entries=(entry,), fees=(fee, *inputs.fees[1:])), latch)
    assert result.status == "within_bounds"
    assert result.exposure == D("1120")
    assert result.capital == D("1490")
    assert result.net_pnl_after_fees_and_closing_reserve == D("138")


def test_unresolved_closing_liability_after_full_exit_stays_unavailable() -> None:
    """A closed quantity cannot erase an unallocated future closing reserve."""
    policy, inputs, latch = sample()
    inputs = _closed_observation(inputs)
    fee = inputs.fees[1]
    fee = replace(fee, components=(replace(fee.components[0], total_upper_bound=D("4.01")), *fee.components[1:]))
    result = assess(policy, replace(inputs, fees=(inputs.fees[0], fee)), replace(latch, retired=True))
    assert_unavailable(result, "unallocated_closing_reserve")
    assert result.transition.retired is True
