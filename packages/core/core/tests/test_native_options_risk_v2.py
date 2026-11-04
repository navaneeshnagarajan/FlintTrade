"""Synthetic owner-resolved options worksheets, never broker qualification."""

from dataclasses import replace
from decimal import Decimal

import pytest

from flinttrade_core.native_autonomy_contracts_v2 import OptionsRiskPolicyV2, RevisionRefV2, RunScopeV2
from flinttrade_core.native_options_risk_v2 import (
    OptionContract,
    OptionEntry,
    OptionExit,
    OptionFill,
    OptionMark,
    OptionWrite,
    OptionsBasis,
    OptionsInputs,
    OptionsLatch,
    OptionsFee,
    OptionsFeeComponent,
    OptionsCharge,
    StandaloneMargin,
    assess_options_risk,
)

D = Decimal
pytestmark = pytest.mark.unit
COMPONENTS = ("brokerage", "exchange", "sebi", "stt", "stamp", "gst", "delivery", "other")


def ref(name: str) -> RevisionRefV2:
    """Build a labelled synthetic revision reference.

    Args:
        name: Synthetic reference or nominal model name.

    Returns:
        A labelled RevisionRefV2.
    """
    return RevisionRefV2(id=name, revision="a" * 64)


def sample(side: str = "long") -> tuple[OptionsRiskPolicyV2, OptionsInputs, OptionsLatch]:
    """Build a complete synthetic options worksheet, without qualification.

    Args:
        side: Synthetic long or short option direction.

    Returns:
        Policy, immutable inputs and prior latch.
    """
    scope = RunScopeV2(
        run_id="synthetic-options",
        operator="operator:" + "b" * 64,
        actor="bounded:synthetic-options",
        broker="dhan",
        account_id="Exact.Account",
        environment="synthetic",
        registry_generation=1,
        binding_revision="c" * 64,
    )
    policy = OptionsRiskPolicyV2(
        profile_version="index_options_v1",
        policy_ref=ref("policy"),
        capital_basis="non_replenishing_long_premium_short_standalone_margin_plus_fees",
        exposure_basis="gross_underlying_notional_no_cross_contract_netting_plus_liabilities",
        loss_basis="run_lifetime_net_realised_plus_unrealised_after_fees",
        threshold_action="latch_entry_retirement_and_broker_held_or_handback",
        capital_cap={"amount": "1000000", "currency": "INR"},
        exposure_cap={"amount": "10000000", "currency": "INR"},
        loss_action_threshold={"amount": "1000", "currency": "INR"},
        max_mark_age_ms=100,
        fee_policy_ref=ref("fee-policy"),
    )
    basis = OptionsBasis(
        scope, ref("policy"), ref("source"), ref("reservations"), ref("fee-policy"), ref("tariff"), ref("fee-source")
    )
    contract = OptionContract(
        ref("contract"),
        ref("listing"),
        "token-exact",
        ref("NIFTY"),
        "NIFTY",
        "NFO",
        "NRML",
        2000,
        "CE",
        D("25000"),
        50,
        "underlying_units",
        "INR",
    )
    fill = OptionFill(ref("trade"), ref("entry-write"), contract.contract_ref, 50, D("100"), 900, ())
    write = OptionWrite(
        ref("entry-write"),
        contract.contract_ref,
        "entry",
        "buy" if side == "long" else "sell",
        100,
        50,
        0,
        None,
        D("110"),
    )
    mark = OptionMark(contract.contract_ref, contract.underlying_ref, ref("quote"), D("25000"), 950, D("90"), 950)
    margin = (
        None
        if side == "long"
        else StandaloneMargin(
            ref("margin"),
            basis,
            contract.contract_ref,
            50,
            50,
            D("80000"),
            D("90000"),
            950,
            "exact_standalone_disjoint",
        )
    )
    entry = OptionEntry(
        ref("entry"),
        basis,
        contract,
        contract,
        950,
        side,
        (fill,),
        (write,),
        mark,
        margin,
        D("5000") if side == "long" else D("80000"),
        D("0"),
    )
    fees = tuple(fee(phase) for phase in ("entry_filled", "close_filled", "entry_possible", "close_possible"))
    inputs = OptionsInputs(basis, 1, 950, "complete", "exact_disjoint", 1, 3000, (entry,), fees)
    return policy, inputs, OptionsLatch(basis.scope, policy.policy_ref, ref("latch"), False)


def fee(
    phase: str,
    upper: str = "0",
    amount: str | None = None,
    payment: str = "paid",
    entry: str = "entry",
) -> OptionsFee:
    """Build explicit synthetic fee components and payment observations.

    Args:
        phase: Fee obligation phase.
        upper: Explicit inclusive synthetic fee upper bound.
        amount: Reported charge amount, or absent evidence.
        payment: Observed synthetic payment disposition.
        entry: Synthetic entry identity or entry to copy.

    Returns:
        An OptionsFee with every component explicitly supplied.
    """
    charge = (
        ()
        if amount is None
        else (
            OptionsCharge(
                ref("charge:" + phase),
                D(amount),
                payment,
                900,
                ref("payment:" + phase) if payment in ("paid", "reversed") else None,
            ),
        )
    )
    parts = tuple(
        OptionsFeeComponent(
            name,
            "order",
            ref(entry + ":" + phase + ":" + name),
            D(upper) if name == "brokerage" else D("0"),
            charge if name == "brokerage" else (),
        )
        for name in COMPONENTS
    )
    return OptionsFee(ref(entry + ":" + phase), ref(entry), ref("tariff"), phase, 950, parts)


def assess(policy: OptionsRiskPolicyV2, inputs: OptionsInputs, latch: OptionsLatch) -> object:
    """Evaluate the synthetic worksheet at its fixed observation time.

    Args:
        policy: Explicit options risk policy.
        inputs: Owner-resolved synthetic lifetime observations.
        latch: Prior synthetic entry-retirement latch.

    Returns:
        The calculator's OptionsAssessment; it grants no authority.
    """
    return assess_options_risk(policy, inputs, latch, now_ms=1000)


def test_long_premium_pending_and_underlying_units_are_distinct() -> None:
    """Verify long premium pending and underlying units are distinct."""
    result = assess(*sample())
    assert result.status == "within_bounds"
    assert (result.capital, result.exposure, result.net_pnl_after_fees_and_closing_reserve, result.loss) == (
        D("10500"),
        D("2500000"),
        D("-500"),
        D("500"),
    )
    assert result.inputs == sample()[1]
    assert result.transition.action == "retain"


def test_short_uses_full_standalone_margin_not_received_premium() -> None:
    """Verify short uses full standalone margin not received premium."""
    policy, inputs, latch = sample("short")
    fees = (
        fee("entry_filled", "2", "2"),
        fee("close_filled", "10", "4", "accrued_unpaid"),
        fee("entry_possible", "3"),
        fee("close_possible", "5"),
    )
    result = assess(policy, replace(inputs, fees=fees), latch)
    assert result.status == "within_bounds"
    assert (result.capital, result.exposure, result.net_pnl_after_fees_and_closing_reserve, result.loss) == (
        D("170020"),
        D("2500020"),
        D("488"),
        D("0"),
    )
    assert result.required_lifetime_principal == ((ref("entry"), D("80000")),)


@pytest.mark.parametrize("side,pnl", [("long", "100"), ("short", "-100")])
def test_real_exits_are_signed_cashflows_and_partial_margin_is_not_prorated(side: str, pnl: str) -> None:
    """Verify real exits are signed cashflows and partial margin is not prorated.

    Args:
        side: Synthetic long or short option direction.
        pnl: Expected signed net cashflow.
    """
    policy, inputs, latch = sample(side)
    entry = inputs.entries[0]
    exit = OptionExit(
        ref("exit-trade"), ref("exit-write"), entry.contract.contract_ref, 20, D("120"), 940, "trade", None
    )
    write = OptionWrite(
        ref("exit-write"),
        entry.contract.contract_ref,
        "exit",
        "sell" if side == "long" else "buy",
        50,
        30,
        0,
        None,
        D("120"),
    )
    entry = replace(
        entry,
        fills=(replace(entry.fills[0], exits=(exit,)),),
        writes=(*entry.writes, write),
        margin=None if side == "long" else replace(entry.margin, filled_units=30),
    )
    result = assess(policy, replace(inputs, entries=(entry,)), latch)
    assert result.status == "within_bounds"
    assert result.capital == D("10500" if side == "long" else "170000")
    assert result.exposure == D("2000000")
    assert result.net_pnl_after_fees_and_closing_reserve == D(pnl)


def unavailable(result: object) -> None:
    """Require unavailable arithmetic and retained uncertainty.

    Args:
        result: OptionsAssessment returned by the pure calculator.
    """
    assert result.status == "unavailable"
    assert result.reasons
    assert (result.capital, result.exposure, result.loss) == (None, None, None)
    assert result.transition.action == "hold_unknown"


@pytest.mark.parametrize(
    "change",
    [
        "scope",
        "source",
        "reservation",
        "policy",
        "fee_policy",
        "tariff",
        "fee_source",
        "partial",
        "conflicting",
        "unallocated",
        "stale_source",
        "future_source",
        "foreign_latch",
        "token",
        "lot",
        "expiry",
        "right",
        "underlying",
        "unknown_listing",
        "stale_listing",
        "stale_underlying",
        "stale_option",
        "mark_contract",
        "mark_underlying",
        "missing_mark",
        "unknown_write",
        "unproved_release",
        "double_fill",
        "duplicate_write",
        "fill_contract",
        "fill_after_expiry",
        "wrong_direction",
        "negative_quantity",
        "boolean_quantity",
        "float_price",
        "unknown_margin",
        "stale_margin",
        "margin_scope",
        "margin_quantity",
        "nonlinear_unallocated",
        "fees_unknown",
        "fees_missing",
        "fee_tariff",
        "duplicate_fee",
        "duplicate_charge",
        "unproved_paid",
        "fees_over_bound",
        "fee_time",
        "unpaid_unknown_amount",
        "unknown_payment",
        "undercounted_capital",
    ],
)
def test_unavailable_evidence_never_manufactures_capacity(change: str) -> None:
    """Verify unavailable evidence never manufactures capacity.

    Args:
        change: Named evidence mutation to challenge.
    """
    policy, inputs, latch = sample(
        "short"
        if change.startswith("margin") or change in {"unknown_margin", "stale_margin", "nonlinear_unallocated"}
        else "long"
    )
    entry = inputs.entries[0]
    if change in {"scope", "source", "reservation", "policy", "fee_policy", "tariff", "fee_source"}:
        key = "scope" if change == "scope" else change + "_ref"
        value = replace_scope(entry.basis.scope, account_id="Foreign") if key == "scope" else ref("foreign")
        entry = replace(entry, basis=replace(entry.basis, **{key: value}))
    elif change in {"partial", "conflicting"}:
        inputs = replace(inputs, coverage=change)
    elif change == "unallocated":
        inputs = replace(inputs, allocation="unavailable")
    elif change == "stale_source":
        inputs = replace(inputs, observed_at_ms=899)
    elif change == "future_source":
        inputs = replace(inputs, observed_at_ms=1001)
    elif change == "foreign_latch":
        latch = replace(latch, policy_ref=ref("foreign"), retired=True)
    elif change in {"token", "lot", "expiry", "right", "underlying"}:
        field, value = {
            "token": ("token", "different"),
            "lot": ("units_per_lot", 75),
            "expiry": ("expiry_at_ms", 3000),
            "right": ("right", "PE"),
            "underlying": ("underlying_ref", ref("SENSEX")),
        }[change]
        entry = replace(entry, current_contract=replace(entry.contract, **{field: value}))
    elif change == "unknown_listing":
        entry = replace(entry, current_contract=None)
    elif change == "stale_listing":
        entry = replace(entry, listing_observed_at_ms=899)
    elif change == "stale_underlying":
        entry = replace(entry, mark=replace(entry.mark, underlying_at_ms=899))
    elif change == "stale_option":
        entry = replace(entry, mark=replace(entry.mark, option_at_ms=899))
    elif change == "mark_contract":
        entry = replace(entry, mark=replace(entry.mark, contract_ref=ref("foreign")))
    elif change == "mark_underlying":
        entry = replace(entry, mark=replace(entry.mark, underlying_ref=ref("foreign")))
    elif change == "missing_mark":
        entry = replace(entry, mark=None)
    elif change == "unknown_write":
        entry = replace(entry, writes=(replace(entry.writes[0], remaining_quantity=None),))
    elif change == "unproved_release":
        entry = replace(entry, writes=(replace(entry.writes[0], remaining_quantity=0, released_quantity=50),))
    elif change == "double_fill":
        entry = replace(entry, fills=entry.fills * 2)
    elif change == "duplicate_write":
        entry = replace(entry, writes=entry.writes * 2)
    elif change == "fill_contract":
        entry = replace(entry, fills=(replace(entry.fills[0], contract_ref=ref("foreign")),))
    elif change == "fill_after_expiry":
        entry = replace(entry, fills=(replace(entry.fills[0], observed_at_ms=2001),))
    elif change == "wrong_direction":
        entry = replace(entry, writes=(replace(entry.writes[0], side="sell"),))
    elif change in {"negative_quantity", "boolean_quantity", "float_price"}:
        field, value = {
            "negative_quantity": ("quantity", -1),
            "boolean_quantity": ("quantity", True),
            "float_price": ("unit_price", 100.0),
        }[change]
        entry = replace(entry, fills=(replace(entry.fills[0], **{field: value}),))
    elif change == "unknown_margin":
        entry = replace(entry, margin=None)
    elif change == "stale_margin":
        entry = replace(entry, margin=replace(entry.margin, observed_at_ms=899))
    elif change == "margin_scope":
        entry = replace(entry, margin=replace(entry.margin, basis=replace(entry.basis, reservation_ref=ref("foreign"))))
    elif change == "margin_quantity":
        entry = replace(entry, margin=replace(entry.margin, filled_units=25))
    elif change == "nonlinear_unallocated":
        entry = replace(entry, margin=replace(entry.margin, allocation="unavailable"))
    elif change == "fees_unknown":
        inputs = replace(
            inputs,
            fees=(
                replace(
                    inputs.fees[0],
                    components=(
                        replace(inputs.fees[0].components[0], total_upper_bound=None),
                        *inputs.fees[0].components[1:],
                    ),
                ),
                *inputs.fees[1:],
            ),
        )
    elif change == "fees_missing":
        inputs = replace(inputs, fees=inputs.fees[1:])
    elif change == "fee_tariff":
        inputs = replace(inputs, fees=(replace(inputs.fees[0], tariff_ref=ref("foreign")), *inputs.fees[1:]))
    elif change == "duplicate_fee":
        inputs = replace(inputs, fees=inputs.fees * 2)
    elif change == "duplicate_charge":
        f = fee("entry_filled", "4", "2")
        inputs = replace(
            inputs,
            fees=(
                replace(
                    f, components=(replace(f.components[0], charges=f.components[0].charges * 2), *f.components[1:])
                ),
                *inputs.fees[1:],
            ),
        )
    elif change == "unproved_paid":
        f = fee("entry_filled", "2", "2")
        inputs = replace(
            inputs,
            fees=(
                replace(
                    f,
                    components=(
                        replace(
                            f.components[0], charges=(replace(f.components[0].charges[0], payment_evidence_ref=None),)
                        ),
                        *f.components[1:],
                    ),
                ),
                *inputs.fees[1:],
            ),
        )
    elif change == "fees_over_bound":
        inputs = replace(inputs, fees=(fee("entry_filled", "1", "2"), *inputs.fees[1:]))
    elif change == "fee_time":
        inputs = replace(inputs, fees=(replace(inputs.fees[0], as_of_ms=899), *inputs.fees[1:]))
    elif change == "unpaid_unknown_amount":
        f = fee("entry_filled", "2", "2", "accrued_unpaid")
        inputs = replace(
            inputs,
            fees=(
                replace(
                    f,
                    components=(
                        replace(f.components[0], charges=(replace(f.components[0].charges[0], amount=None),)),
                        *f.components[1:],
                    ),
                ),
                *inputs.fees[1:],
            ),
        )
    elif change == "unknown_payment":
        inputs = replace(inputs, fees=(fee("entry_filled", "2", "2", "unknown"), *inputs.fees[1:]))
    elif change == "undercounted_capital":
        entry = replace(entry, committed_principal=D("4999"))
    result = assess(policy, replace(inputs, entries=(entry,)), latch)
    unavailable(result)
    if change == "lot":
        assert result.inputs.entries[0].fills[0].quantity == 50
        assert result.inputs.entries[0].contract.units_per_lot == 50
    if change == "foreign_latch":
        assert result.transition.retired is True
        assert result.transition.expected_revision is None


def replace_scope(scope: RunScopeV2, **changes: object) -> RunScopeV2:
    """Revalidate an explicitly changed synthetic run scope.

    Args:
        scope: Original synthetic run scope.
        changes: Fields explicitly replaced before revalidation.

    Returns:
        The revalidated RunScopeV2.
    """
    return RunScopeV2.model_validate({**scope.model_dump(), **changes})


@pytest.mark.parametrize(
    "field,value,status",
    [
        ("capital_cap", "10499.99999999", "breached"),
        ("capital_cap", "10500", "within_bounds"),
        ("capital_cap", "10500.00000001", "within_bounds"),
        ("exposure_cap", "2499999.99999999", "breached"),
        ("exposure_cap", "2500000", "within_bounds"),
        ("exposure_cap", "2500000.00000001", "within_bounds"),
        ("loss_action_threshold", "499.99999999", "breached"),
        ("loss_action_threshold", "500", "breached"),
        ("loss_action_threshold", "500.00000001", "within_bounds"),
    ],
)
def test_exact_cap_and_loss_threshold_neighbours(field: str, value: str, status: str) -> None:
    """Verify exact cap and loss threshold neighbours.

    Args:
        field: Policy field or contract key under test.
        value: Explicit boundary or malformed input under test.
        status: Expected assessment status.
    """
    policy, inputs, latch = sample()
    policy = OptionsRiskPolicyV2.model_validate({**policy.model_dump(), field: {"amount": value, "currency": "INR"}})
    result = assess(policy, inputs, latch)
    assert result.status == status
    assert (field in result.reasons) == (status == "breached")
    retire = field == "loss_action_threshold" and status == "breached"
    assert result.transition.action == ("retire_entries_and_request_custody" if retire else "retain")
    assert result.transition.expected_revision == latch.revision


def closed_sample(
    side: str = "long", settlement: bool = False
) -> tuple[OptionsRiskPolicyV2, OptionsInputs, OptionsLatch]:
    """Build a fully closed trade or independently evidenced cash settlement.

    Args:
        side: Synthetic long or short option direction.
        settlement: Use an evidenced cash-settlement event when true.

    Returns:
        Policy, closed lifetime inputs and prior latch.
    """
    policy, inputs, latch = sample(side)
    e = inputs.entries[0]
    contract = replace(e.contract, expiry_at_ms=950) if settlement else e.contract
    x = OptionExit(
        ref("exit-trade"),
        None if settlement else ref("exit-write"),
        contract.contract_ref,
        50,
        D("0" if settlement else "70"),
        950,
        "cash_settlement" if settlement else "trade",
        ref("settlement-event") if settlement else None,
    )
    writes = (
        replace(e.writes[0], remaining_quantity=0, released_quantity=50, resolution_ref=ref("resolved-unfilled")),
    )
    if not settlement:
        writes += (
            OptionWrite(
                ref("exit-write"),
                contract.contract_ref,
                "exit",
                "sell" if side == "long" else "buy",
                50,
                0,
                0,
                None,
                None,
            ),
        )
    e = replace(
        e,
        contract=contract,
        current_contract=None,
        listing_observed_at_ms=None,
        margin=None,
        mark=None,
        fills=(replace(e.fills[0], exits=(x,)),),
        writes=writes,
    )
    return (
        policy,
        replace(inputs, entries=(e,), fees=(fee("entry_filled", "2", "2"), fee("close_filled", "4", "4"))),
        latch,
    )


@pytest.mark.parametrize("payment,exposure", [("paid", "0"), ("accrued_unpaid", "2"), ("payment_unknown", "2")])
def test_fully_closed_fee_exclusion_requires_actual_payment(payment: str, exposure: str) -> None:
    """Verify fully closed fee exclusion requires actual payment.

    Args:
        payment: Observed synthetic payment disposition.
        exposure: Expected retained exposure.
    """
    policy, inputs, latch = closed_sample()
    inputs = replace(inputs, fees=(fee("entry_filled", "2", "2", payment), inputs.fees[1]))
    result = assess(policy, inputs, latch)
    assert (result.capital, result.exposure, result.loss) == (D("5006"), D(exposure), D("1506"))
    assert result.transition.action == "retire_entries_and_request_custody"
    again = assess(policy, inputs, replace(latch, retired=True, revision=ref("latch-after-cas")))
    assert again.transition.action == "retain" and again.transition.retired is True
    assert again.transition.expected_revision == ref("latch-after-cas")


@pytest.mark.parametrize("side,net", [("long", "-5006"), ("short", "4994")])
def test_zero_expiry_cash_settlement_is_an_evidenced_event(side: str, net: str) -> None:
    """Verify zero expiry cash settlement is an evidenced event.

    Args:
        side: Synthetic long or short option direction.
        net: Expected signed net result.
    """
    policy, inputs, latch = closed_sample(side, settlement=True)
    result = assess(policy, inputs, latch)
    assert result.exposure == 0
    assert result.net_pnl_after_fees_and_closing_reserve == D(net)
    entry = inputs.entries[0]
    unproved = replace(entry.fills[0].exits[0], settlement_ref=None)
    unavailable(
        assess(
            policy,
            replace(inputs, entries=(replace(entry, fills=(replace(entry.fills[0], exits=(unproved,)),)),)),
            latch,
        )
    )


def test_increased_margin_is_a_new_lifetime_floor_not_reusable_collateral() -> None:
    """Verify increased margin is a new lifetime floor not reusable collateral."""
    policy, inputs, latch = sample("short")
    entry = inputs.entries[0]
    entry = replace(entry, margin=replace(entry.margin, filled_floor=D("95000")))
    result = assess(policy, replace(inputs, entries=(entry,)), latch)
    assert result.capital == D("185000")
    assert result.required_lifetime_principal == ((ref("entry"), D("95000")),)
    # The durable owner records the floor; a later lower quote cannot erase it.
    entry = replace(entry, committed_principal=D("95000"), margin=replace(entry.margin, filled_floor=D("60000")))
    assert assess(policy, replace(inputs, entries=(entry,)), latch).capital == D("185000")


def test_private_arithmetic_ignores_hostile_thread_context() -> None:
    """Verify private arithmetic ignores hostile thread context."""
    import decimal

    policy, inputs, latch = sample()
    with decimal.localcontext() as context:
        context.prec = 2
        context.Emax = 2
        context.Emin = -2
        context.clamp = 1
        context.traps[decimal.Clamped] = True
        context.traps[decimal.Inexact] = True
        result = assess(policy, inputs, latch)
        assert (result.capital, result.exposure, result.loss) == (D("10500"), D("2500000"), D("500"))
        assert context.prec == 2 and context.clamp == 1


def test_cold_import_ignores_mutated_default_context() -> None:
    """Verify cold import ignores mutated default context."""
    import subprocess
    import sys
    from pathlib import Path

    code = (
               "import decimal, runpy\n"
               "c = decimal.DefaultContext\n"
               "c.prec = 2\n"
               "c.Emax = 2\n"
               "c.Emin = -2\n"
               "c.clamp = 1\n"
               "c.rounding = decimal.ROUND_FLOOR\n"
               "c.capitals = 0\n"
               "for k in c.traps:\n"
               "    c.traps[k] = True\n"
               "for k in c.flags:\n"
               "    c.flags[k] = True\n"
               "m = runpy.run_path(TEST_FILE)\n"
               "r = m['assess'](*m['sample']())\n"
               "assert (str(r.capital), str(r.exposure), str(r.loss)) == ('10500', '2500000', '500'), r\n"
               "assert c.prec == 2 and c.clamp == 1\n"
               "print('COLD_DEFAULT_CONTEXT_PASS')\n"
           ).replace("TEST_FILE", repr(str(Path(__file__).resolve())))
    result = subprocess.run([sys.executable, "-B", "-I", "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "COLD_DEFAULT_CONTEXT_PASS" in result.stdout


def test_same_execution_cannot_be_both_entry_and_exit() -> None:
    """Verify same execution cannot be both entry and exit."""
    policy, inputs, latch = closed_sample()
    entry = inputs.entries[0]
    exit = replace(entry.fills[0].exits[0], execution_ref=entry.fills[0].fill_ref)
    entry = replace(entry, fills=(replace(entry.fills[0], exits=(exit,)),))
    unavailable(assess(policy, replace(inputs, entries=(entry,)), latch))


def test_fee_high_water_is_explicit_and_reversals_never_replenish_capital() -> None:
    """Verify fee high water is explicit and reversals never replenish capital."""
    policy, inputs, latch = closed_sample()
    result = assess(policy, inputs, latch)
    assert result.required_lifetime_fee_allowance == ((ref("entry"), D("6")),)
    entry = replace(inputs.entries[0], committed_fee_allowance=D("6"))
    inputs = replace(inputs, entries=(entry,), fees=(fee("entry_filled", "0", "2", "reversed"), inputs.fees[1]))
    result = assess(policy, inputs, latch)
    assert (result.capital, result.exposure, result.loss) == (D("5006"), D("0"), D("1504"))
    assert result.required_lifetime_fee_allowance == ((ref("entry"), D("6")),)


def second_leg(
    entry: OptionEntry,
    fees: tuple[OptionsFee, ...],
    *,
    right: str = 'PE',
    expiry: int = 2500,
) -> tuple[OptionEntry, tuple[OptionsFee, ...]]:
    """Build a separately identified option lineage without hedge netting.

    Args:
        entry: Synthetic entry identity or entry to copy.
        fees: Explicit fee allocations belonging to the entry.
        right: Synthetic option right.
        expiry: Synthetic expiry timestamp in milliseconds.

    Returns:
        The distinct entry and its separately identified fee allocations.
    """
    contract = replace(
        entry.contract,
        contract_ref=ref("other-contract"),
        listing_ref=ref("other-listing"),
        token="other-token",
        right=right,
        expiry_at_ms=expiry,
    )
    writes = tuple(
        replace(w, write_ref=ref("other-" + w.write_ref.id), contract_ref=contract.contract_ref) for w in entry.writes
    )
    fills = tuple(
        replace(
            f,
            fill_ref=ref("other-" + f.fill_ref.id),
            write_ref=ref("other-" + f.write_ref.id),
            contract_ref=contract.contract_ref,
        )
        for f in entry.fills
    )
    margin = (
        None
        if entry.margin is None
        else replace(entry.margin, margin_ref=ref("other-margin"), contract_ref=contract.contract_ref)
    )
    entry = replace(
        entry,
        entry_ref=ref("other-entry"),
        contract=contract,
        current_contract=contract,
        fills=fills,
        writes=writes,
        margin=margin,
        mark=replace(entry.mark, contract_ref=contract.contract_ref),
    )
    fees = tuple(
        replace(
            f,
            allocation_ref=ref("other-" + f.allocation_ref.id),
            entry_ref=entry.entry_ref,
            components=tuple(replace(c, basis_ref=ref("other-" + c.basis_ref.id)) for c in f.components),
        )
        for f in fees
    )
    return entry, fees


@pytest.mark.parametrize("right,expiry", [("CE", 2000), ("PE", 2000), ("CE", 2500), ("PE", 2500)])
def test_hedges_never_net_distinct_contracts_or_expiries(right: str, expiry: int) -> None:
    """Verify hedges never net distinct contracts or expiries.

    Args:
        right: Synthetic option right.
        expiry: Synthetic expiry timestamp in milliseconds.
    """
    policy, inputs, latch = sample()
    _, short, _ = sample("short")
    leg, fees = second_leg(short.entries[0], short.fees, right=right, expiry=expiry)
    result = assess(policy, replace(inputs, entries=(*inputs.entries, leg), fees=(*inputs.fees, *fees)), latch)
    assert (result.capital, result.exposure, result.loss) == (D("180500"), D("5000000"), D("0"))
    # Mixed accounts, rejected/unknown hedge legs cannot become a discount.
    bad = replace(leg, basis=replace(leg.basis, scope=replace_scope(leg.basis.scope, account_id="Foreign")))
    unavailable(assess(policy, replace(inputs, entries=(*inputs.entries, bad), fees=(*inputs.fees, *fees)), latch))
    unknown = replace(leg, writes=(replace(leg.writes[0], remaining_quantity=None),))
    unavailable(assess(policy, replace(inputs, entries=(*inputs.entries, unknown), fees=(*inputs.fees, *fees)), latch))


@pytest.mark.parametrize("side,capital", [("long", "145000"), ("short", "98000")])
def test_competing_exits_are_independently_executable_not_reduce_only(side: str, capital: str) -> None:
    """Verify competing exits are independently executable not reduce only.

    Args:
        side: Synthetic long or short option direction.
        capital: Expected non-replenishing capital requirement.
    """
    policy, inputs, latch = sample(side)
    entry = inputs.entries[0]
    write = replace(entry.writes[0], remaining_quantity=0, released_quantity=50, resolution_ref=ref("resolved"))
    exits = tuple(
        OptionWrite(
            ref("exit-" + str(i)),
            entry.contract.contract_ref,
            "exit",
            "sell" if side == "long" else "buy",
            100,
            100,
            0,
            None,
            D("120" if i == 0 else "100"),
        )
        for i in range(2)
    )
    margin = (
        StandaloneMargin(
            ref("excess-short-margin"),
            entry.basis,
            entry.contract.contract_ref,
            0,
            150,
            D("0"),
            D("140000"),
            950,
            "exact_standalone_disjoint",
        )
        if side == "long"
        else replace(entry.margin, possible_short_units=0, pending_hold=D("0"))
    )
    entry = replace(entry, writes=(write, *exits), margin=margin)
    result = assess(policy, replace(inputs, entries=(entry,)), latch)
    assert result.capital == D(capital)
    assert result.exposure == D("3750000")  # max(|50|, |50-200|) underlying units
    if side == "long":
        unavailable(assess(policy, replace(inputs, entries=(replace(entry, margin=None),)), latch))


@pytest.mark.parametrize(
    "change",
    ["model_ref", "model_scope", "policy_money", "decimal", "quantity", "tuple", "extra", "missing", "latch_ref"],
)
def test_bypassed_nested_inputs_never_invoke_conversion_or_comparison_hooks(change: str) -> None:
    """Verify bypassed nested inputs never invoke conversion or comparison hooks.

    Args:
        change: Named evidence mutation to challenge.
    """
    hooks = []

    class Evil(str):
        def __eq__(self, other):
            hooks.append("eq")
            raise AssertionError("untrusted equality")

        def __hash__(self):
            hooks.append("hash")
            raise AssertionError("untrusted hash")

        def __str__(self):
            hooks.append("str")
            raise AssertionError("untrusted text")

    class BadDecimal(Decimal):
        def __mul__(self, other):
            hooks.append("mul")
            raise AssertionError("untrusted arithmetic")

    class BadInt(int):
        def __add__(self, other):
            hooks.append("add")
            raise AssertionError("untrusted arithmetic")

    class BadTuple(tuple):
        __slots__ = ()

        def __iter__(self):
            hooks.append("iter")
            raise AssertionError("untrusted traversal")

    policy, inputs, latch = sample()
    entry = inputs.entries[0]
    if change == "model_ref":
        entry = replace(entry, entry_ref=RevisionRefV2.model_construct(id=Evil("entry"), revision="a" * 64))
    elif change == "model_scope":
        scope = entry.basis.scope.model_copy(update={"account_id": Evil("Exact.Account")})
        entry = replace(entry, basis=replace(entry.basis, scope=scope))
    elif change == "policy_money":
        policy = policy.model_copy(
            update={"capital_cap": policy.capital_cap.model_copy(update={"amount": Evil("1000000")})}
        )
    elif change == "decimal":
        entry = replace(entry, committed_principal=BadDecimal("5000"))
    elif change == "quantity":
        entry = replace(entry, fills=(replace(entry.fills[0], quantity=BadInt(50)),))
    elif change == "tuple":
        entry = replace(entry, fills=BadTuple(entry.fills))
    elif change == "extra":
        object.__setattr__(entry, "client_authorized", True)
    elif change == "missing":
        object.__delattr__(entry, "writes")
    elif change == "latch_ref":
        latch = replace(
            latch, retired=True, revision=RevisionRefV2.model_construct(id=Evil("latch"), revision="a" * 64)
        )
    result = assess(policy, replace(inputs, entries=(entry,)), latch)
    unavailable(result)
    assert hooks == []
    if change not in ("policy_money", "latch_ref"):
        assert result.inputs is None
    if change == "latch_ref":
        assert result.transition.retired is True and result.transition.expected_revision is None


@pytest.mark.parametrize("side", ["long", "short"])
@pytest.mark.parametrize("exited", [0, 10, 50])
@pytest.mark.parametrize("pending", [0, 25, 50])
def test_independent_fraction_cashflow_worksheet(side: str, exited: int, pending: int) -> None:
    """Verify independent fraction cashflow worksheet.

    Args:
        side: Synthetic long or short option direction.
        exited: Independently executed exit units.
        pending: Remaining possible entry units.
    """
    from fractions import Fraction as F

    policy, inputs, latch = sample(side)
    e = inputs.entries[0]
    fill = e.fills[0]
    writes = (
        replace(
            e.writes[0],
            remaining_quantity=pending,
            released_quantity=50 - pending,
            resolution_ref=ref("resolved") if pending < 50 else None,
        ),
    )
    if exited:
        exit = OptionExit(
            ref("exit-trade"), ref("exit-write"), e.contract.contract_ref, exited, D("120"), 940, "trade", None
        )
        fill = replace(fill, exits=(exit,))
        writes += (
            OptionWrite(
                ref("exit-write"),
                e.contract.contract_ref,
                "exit",
                "sell" if side == "long" else "buy",
                50,
                0,
                50 - exited,
                ref("exit-resolved") if exited < 50 else None,
                None,
            ),
        )
    opened = 50 - exited
    margin = (
        None
        if side == "long" or not (opened or pending)
        else replace(
            e.margin,
            filled_units=opened,
            possible_short_units=pending,
            filled_floor=D("80000") if opened else D("0"),
            pending_hold=D("90000") if pending else D("0"),
        )
    )
    e = replace(e, fills=(fill,), writes=writes, margin=margin)
    close_upper = "10" if opened else "4"
    fees = (fee("entry_filled", "2", "2", "payment_unknown"), fee("close_filled", close_upper, "4"))
    if pending:
        fees += (fee("entry_possible", "3"), fee("close_possible", "5"))
    result = assess(policy, replace(inputs, entries=(e,), fees=fees), latch)
    cap = F(5000) + pending * F(110) if side == "long" else F(80000) + (F(90000) if pending else F(0))
    cap += F(2) + F(close_upper) + (F(8) if pending else F(0))
    exposure = (
        F(opened + pending) * F(25000)
        + F(2)
        + F(close_upper)
        + (F(8) if pending else F(0))
        - (F(4) if not opened else F(0))
    )
    net = (
        (1 if side == "long" else -1) * (F(exited) * F(120) + F(opened) * F(90) - F(50) * F(100))
        - F(6)
        - (F(close_upper) - F(4))
    )
    assert tuple(
        F(v) for v in (result.capital, result.exposure, result.net_pnl_after_fees_and_closing_reserve, result.loss)
    ) == (cap, exposure, net, max(F(0), -net))


def test_default_template_does_not_affect_either_arithmetic_callsite() -> None:
    """Verify default template does not affect either arithmetic callsite."""
    import decimal

    policy, inputs, latch = sample()
    original = decimal.DefaultContext.copy()
    try:
        template = decimal.DefaultContext
        template.prec = 2
        template.rounding = decimal.ROUND_FLOOR
        template.Emax = 2
        template.Emin = -2
        template.clamp = 1
        template.capitals = 0
        for key in template.traps:
            template.traps[key] = True
        for key in template.flags:
            template.flags[key] = True
        result = assess(policy, inputs, latch)
        assert (result.capital, result.exposure, result.loss) == (D("10500"), D("2500000"), D("500"))
        assert template.prec == 2 and template.clamp == 1
    finally:
        for name in ("prec", "rounding", "Emax", "Emin", "clamp", "capitals"):
            setattr(decimal.DefaultContext, name, getattr(original, name))
        decimal.DefaultContext.traps = original.traps
        decimal.DefaultContext.flags = original.flags


@pytest.mark.parametrize("value", [None, True, -1, 0, 9007199254740992, 1000.0])
def test_invalid_evaluation_time_is_not_a_basis_pin(value: object) -> None:
    """Verify invalid evaluation time is not a basis pin.

    Args:
        value: Explicit boundary or malformed input under test.
    """
    result = assess_options_risk(*sample(), now_ms=value)
    unavailable(result)
    assert result.evaluated_at_ms is None


@pytest.mark.parametrize("value", [D("NaN"), D("Infinity"), D("-0"), D("1e60"), D("0.000000001")])
def test_noncanonical_money_never_enters_arithmetic(value: Decimal) -> None:
    """Verify noncanonical money never enters arithmetic.

    Args:
        value: Explicit boundary or malformed input under test.
    """
    policy, inputs, latch = sample()
    entry = replace(inputs.entries[0], committed_principal=value)
    result = assess(policy, replace(inputs, entries=(entry,)), latch)
    unavailable(result)
    assert result.inputs is None


def test_uncovered_loss_is_not_clamped_to_capital_or_margin() -> None:
    """Verify uncovered loss is not clamped to capital or margin."""
    policy, inputs, latch = sample("short")
    entry = inputs.entries[0]
    entry = replace(entry, mark=replace(entry.mark, option_price=D("100000")))
    result = assess(policy, replace(inputs, entries=(entry,)), latch)
    assert result.capital == D("170000")
    assert result.loss == D("4995000")
    assert result.loss > result.capital
    assert result.transition.action == "retire_entries_and_request_custody"


def test_fee_reversal_cannot_erase_an_unrecorded_lifetime_commitment() -> None:
    """Verify fee reversal cannot erase an unrecorded lifetime commitment."""
    policy, inputs, latch = closed_sample()
    inputs = replace(inputs, fees=(fee("entry_filled", "0", "2", "reversed"), inputs.fees[1]))
    unavailable(assess(policy, inputs, latch))


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_basis",
        "missing_component",
        "paid_pending",
        "unallocated_close",
        "settlement_disappeared",
        "unbounded_buy",
    ],
)
def test_fee_and_pending_omissions_stay_unavailable(change: str) -> None:
    """Verify fee and pending omissions stay unavailable.

    Args:
        change: Named evidence mutation to challenge.
    """
    policy, inputs, latch = sample()
    entry = inputs.entries[0]
    if change == "duplicate_basis":
        f = replace(inputs.fees[1], components=inputs.fees[0].components)
        inputs = replace(inputs, fees=(inputs.fees[0], f, *inputs.fees[2:]))
    elif change == "missing_component":
        inputs = replace(
            inputs, fees=(replace(inputs.fees[0], components=inputs.fees[0].components[1:]), *inputs.fees[1:])
        )
    elif change == "paid_pending":
        inputs = replace(inputs, fees=(*inputs.fees[:2], fee("entry_possible", "1", "1"), inputs.fees[3]))
    elif change == "unallocated_close":
        policy, inputs, latch = closed_sample()
        entry = inputs.entries[0]
        inputs = replace(inputs, fees=(inputs.fees[0], fee("close_filled", "10", "4")))
    elif change == "settlement_disappeared":
        contract = replace(entry.contract, expiry_at_ms=950)
        entry = replace(entry, contract=contract, current_contract=contract)
    else:
        entry = replace(entry, writes=(replace(entry.writes[0], premium_upper_bound=None),))
    unavailable(assess(policy, replace(inputs, entries=(entry,)), latch))


@pytest.mark.parametrize("broker", ["dhan", "kotakneo"])
@pytest.mark.parametrize("underlying,exchange,lot", [("NIFTY", "NFO", 50), ("SENSEX", "BFO", 25)])
@pytest.mark.parametrize("product", ["MIS", "NRML"])
@pytest.mark.parametrize("right", ["CE", "PE"])
def test_profile_targets_do_not_imply_account_or_overnight_qualification(
    broker: str, underlying: str, exchange: str, lot: int, product: str, right: str
) -> None:
    """Verify profile targets do not imply account or overnight qualification.

    Args:
        broker: Synthetic broker identity.
        underlying: Selected synthetic index.
        exchange: Selected synthetic exchange.
        lot: Explicit units per lot.
        product: Selected synthetic product.
        right: Synthetic option right.
    """
    policy, inputs, latch = sample()
    scope = replace_scope(inputs.basis.scope, broker=broker)
    basis = replace(inputs.basis, scope=scope)
    entry = inputs.entries[0]
    contract = replace(
        entry.contract,
        underlying=underlying,
        underlying_ref=ref(underlying),
        exchange=exchange,
        product=product,
        right=right,
        units_per_lot=lot,
    )
    entry = replace(
        entry,
        basis=basis,
        contract=contract,
        current_contract=contract,
        mark=replace(entry.mark, underlying_ref=contract.underlying_ref),
    )
    result = assess(policy, replace(inputs, basis=basis, entries=(entry,)), replace(latch, scope=scope))
    assert result.status == "within_bounds"
    assert (result.capital, result.exposure, result.loss) == (D("10500"), D("2500000"), D("500"))
    assert not hasattr(result, "entry_permission")


def test_known_partial_units_are_not_rounded_to_lots_or_multiplied_again() -> None:
    """Verify known partial units are not rounded to lots or multiplied again."""
    policy, inputs, latch = sample()
    entry = inputs.entries[0]
    entry = replace(
        entry,
        committed_principal=D("4900"),
        fills=(replace(entry.fills[0], quantity=49),),
        writes=(replace(entry.writes[0], remaining_quantity=51),),
    )
    result = assess(policy, replace(inputs, entries=(entry,)), latch)
    assert (result.capital, result.exposure, result.loss) == (D("10510"), D("2500000"), D("490"))
    entry = replace(entry, current_contract=replace(entry.contract, units_per_lot=75))
    result = assess(policy, replace(inputs, entries=(entry,)), latch)
    unavailable(result)
    assert result.inputs.entries[0].fills[0].quantity == 49


def test_safe_integer_units_and_large_notional_are_exact() -> None:
    """Verify safe integer units and large notional are exact."""
    from fractions import Fraction

    policy, inputs, latch = sample()
    entry = inputs.entries[0]
    units = 9007199254740991
    contract = replace(entry.contract, units_per_lot=1)
    entry = replace(
        entry,
        contract=contract,
        current_contract=contract,
        committed_principal=D(units),
        fills=(replace(entry.fills[0], quantity=units, unit_price=D("1")),),
        writes=(replace(entry.writes[0], original_quantity=units, remaining_quantity=0),),
        mark=replace(entry.mark, underlying_price=D("1e59"), option_price=D("1")),
    )
    result = assess(policy, replace(inputs, entries=(entry,), fees=inputs.fees[:2]), latch)
    assert result.status == "breached"
    assert Fraction(result.exposure) == Fraction(units) * Fraction(10) ** 59
    assert result.loss == 0


def test_calculator_performs_no_io_or_input_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify calculator performs no io or input mutation.

    Args:
        monkeypatch: Scoped I/O refusal hooks.
    """
    import builtins
    import socket

    policy, inputs, latch = sample()
    before = repr((policy, inputs, latch))

    def forbidden(*args, **kwargs):
        raise AssertionError("pure calculator performed I/O")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    result = assess(policy, inputs, latch)
    assert result.status == "within_bounds"
    assert repr((policy, inputs, latch)) == before
