"""Durable spend admission, independent of transports and real credentials."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest


def api():
    from flinttrade_core import service_usage

    return service_usage


NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)


def connection():
    from flinttrade_core.service_connections import ServiceConnectionRef

    return ServiceConnectionRef("llm:openai", UUID("4c0687bf-c7b2-455b-9a43-3220121d40ab"))


def tariff(**overrides):
    values = dict(
        provider_id="llm:openai",
        model="fixture-model",
        model_revision="fixture-revision",
        source_kind="operator",
        source="test fixture tariff",
        currency="USD",
        effective_from=NOW - timedelta(days=1),
        effective_until=NOW + timedelta(days=30),
        prices={"input_tokens": api().UnitPrice(2, 1), "output_tokens": api().UnitPrice(4, 1)},
    )
    values.update(overrides)
    return api().TariffSnapshot(**values)


def policy(**overrides):
    values = dict(
        connection=connection(),
        currency="USD",
        window_start=NOW - timedelta(hours=1),
        window_end=NOW + timedelta(hours=1),
        limits={"currency_micros": 100, "requests": 10, "concurrency": 2},
    )
    values.update(overrides)
    return api().BudgetPolicy(**values)


def ledger(tmp_path: Path):
    result = api().ServiceUsageLedger(tmp_path / "usage", clock=lambda: NOW)
    result.configure_budget(policy(), expected_revision=0)
    return result


def prepare(store, attempt_id="attempt-1", **overrides):
    values = dict(
        attempt_id=attempt_id,
        connection=connection(),
        connection_revision="revision-1",
        request_id="request-1",
        run_id="run-1",
        model="fixture-model",
        model_revision="fixture-revision",
        tariff=tariff(),
        reservation=api().UsageAmounts(
            requests=1, input_tokens=10, output_tokens=10, currency_micros=60, concurrency=1
        ),
    )
    values.update(overrides)
    return store.prepare(**values)


def test_reservation_persists_and_duplicate_cannot_invoke_twice(tmp_path):
    """Dropping the invocation CAS would permit duplicate provider requests."""
    with ledger(tmp_path) as store:
        first = prepare(store)
        assert first.state == "PREPARED"
        assert prepare(store) == first
        store.mark_invoked("attempt-1")
        with pytest.raises(api().UsageConflict):
            store.mark_invoked("attempt-1")
    with api().ServiceUsageLedger(tmp_path / "usage", clock=lambda: NOW) as reopened:
        assert reopened.get_attempt("attempt-1").state == "INVOKED"
        with pytest.raises(api().BudgetExceeded):
            prepare(reopened, "attempt-2")


def test_unknown_holds_maximum_until_explicit_reconciliation(tmp_path):
    """Unknown outcomes must not refund money or authorise a replay."""
    with ledger(tmp_path) as store:
        prepare(store)
        store.mark_invoked("attempt-1")
        store.mark_unknown("attempt-1")
        with pytest.raises(api().BudgetExceeded):
            prepare(store, "attempt-2")
        with pytest.raises(api().UsageConflict):
            store.settle("attempt-1", api().UsageAmounts(requests=1))
        usage = api().UsageAmounts(requests=1, input_tokens=2, output_tokens=3, currency_micros=16)
        result = store.reconcile("attempt-1", usage, evidence="fixture final usage receipt")
        assert result.charged.currency_micros == 16
        assert store.reconcile("attempt-1", usage, evidence="fixture final usage receipt") == result
        assert prepare(store, "attempt-2").state == "PREPARED"


def test_only_prepared_can_cancel_and_conflicts_do_not_mutate(tmp_path):
    with ledger(tmp_path) as store:
        prepare(store)
        with pytest.raises(api().UsageConflict):
            prepare(store, run_id="other-run")
        cancelled = store.cancel_prepared("attempt-1")
        assert cancelled.state == "CANCELLED"
        assert cancelled.charged.currency_micros == 0
        prepare(store, "attempt-2")
        store.mark_invoked("attempt-2")
        with pytest.raises(api().UsageConflict):
            store.cancel_prepared("attempt-2")


def test_actual_overage_is_retained_and_blocks_new_admission(tmp_path):
    with ledger(tmp_path) as store:
        prepare(store)
        store.mark_invoked("attempt-1")
        actual = api().UsageAmounts(requests=1, input_tokens=10, output_tokens=25, currency_micros=120)
        result = store.settle("attempt-1", actual)
        assert result.charged.currency_micros == 120
        assert store.settle("attempt-1", actual) == result
        with pytest.raises(api().UsageConflict):
            store.settle("attempt-1", api().UsageAmounts(requests=1))
        with pytest.raises(api().BudgetExceeded):
            prepare(store, "attempt-2")


def test_snapshot_detached_digest_and_input_validation(tmp_path):
    from dataclasses import FrozenInstanceError

    prices = {"input_tokens": api().UnitPrice(2, 1)}
    snap = tariff(prices=prices)
    original = snap.digest
    prices["input_tokens"] = api().UnitPrice(999, 1)
    assert snap.digest == original
    assert snap.quote(api().UsageAmounts(input_tokens=3)) == 6
    with pytest.raises((FrozenInstanceError, AttributeError)):
        snap.currency = "INR"
    with pytest.raises(TypeError):
        snap.prices["input_tokens"] = api().UnitPrice(3, 1)
    for bad in (True, -1, 1.2, float("nan"), float("inf"), "10"):
        with pytest.raises(ValueError):
            api().UsageAmounts(input_tokens=bad)
    with pytest.raises((TypeError, ValueError)):
        api().UsageAmounts(invented_units=1)
    with pytest.raises(ValueError):
        policy(limits={"invented_units": 1})
    with ledger(tmp_path) as store:
        with pytest.raises(ValueError):
            prepare(store, model="wrong-model")
        with pytest.raises(ValueError):
            prepare(store, tariff=tariff(currency="INR"))
        assert store.list_attempts() == ()


def test_unknown_price_requires_positive_explicit_ceiling(tmp_path):
    with ledger(tmp_path) as store:
        with pytest.raises(ValueError):
            prepare(store, tariff=tariff(prices=None))
        admitted = prepare(store, tariff=tariff(prices=None), conservative_cost_ceiling=60)
        assert admitted.charged.currency_micros == 60


def test_pricing_rounding_and_budget_edit_cannot_refund_existing_spend(tmp_path):
    snap = tariff(prices={"input_tokens": api().UnitPrice(5, 3)}, markup_basis_points=1000, tax_basis_points=1000)
    assert snap.quote(api().UsageAmounts(input_tokens=2)) == 5  # ceil(ceil(10/3) * 1.1 * 1.1)
    with ledger(tmp_path) as store:
        prepare(store)
        store.mark_invoked("attempt-1")
        store.settle("attempt-1", api().UsageAmounts(requests=1, input_tokens=10, currency_micros=20))
        store.configure_budget(policy(limits={"currency_micros": 70}), expected_revision=1)
        with pytest.raises(api().BudgetExceeded):
            prepare(store, "attempt-2")
        assert store.get_attempt("attempt-1").tariff.digest == tariff().digest


def test_every_supported_dimension_is_enforced(tmp_path):
    for dimension in api().USAGE_DIMENSIONS:
        with api().ServiceUsageLedger(tmp_path / dimension, clock=lambda: NOW) as store:
            store.configure_budget(policy(limits={dimension: 0}), expected_revision=0)
            values = {"requests": 1, "concurrency": 1, "currency_micros": 60, dimension: 1}
            with pytest.raises(api().BudgetExceeded):
                prepare(store, reservation=api().UsageAmounts(**values), tariff=tariff(prices={}))


_PROCESS = """
import json, os, sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID
from flinttrade_core.service_connections import ServiceConnectionRef
from flinttrade_core.service_usage import *
now = datetime(2026, 9, 10, 12, tzinfo=UTC)
ref = ServiceConnectionRef('llm:openai', UUID('4c0687bf-c7b2-455b-9a43-3220121d40ab'))
tariff = TariffSnapshot(provider_id='llm:openai', model='fixture-model', model_revision='fixture-revision',
    source_kind='operator', source='test fixture tariff', currency='USD',
    effective_from=now-timedelta(days=1), effective_until=now+timedelta(days=30),
    prices={'output_tokens': UnitPrice(4, 1), 'input_tokens': UnitPrice(2, 1)})
if sys.argv[2] == 'digest':
    print(tariff.digest)
    sys.exit(0)
with ServiceUsageLedger(Path(sys.argv[1]), clock=lambda: now) as store:
    if sys.argv[2] == 'inspect':
        print(json.dumps([x.to_dict() for x in store.list_attempts()]))
    elif sys.argv[2] == 'invoke-existing':
        try:
            store.mark_invoked('attempt-1')
            print('invoked')
        except UsageConflict:
            print('blocked')
    else:
        try:
            record = store.prepare(attempt_id=sys.argv[3], connection=ref, connection_revision='revision-1',
                request_id='request-1', run_id='run-1', model='fixture-model', model_revision='fixture-revision',
                tariff=tariff, reservation=UsageAmounts(requests=1, input_tokens=10, output_tokens=10,
                    currency_micros=60, concurrency=1))
            if sys.argv[2] == 'crash-invoked':
                store.mark_invoked(sys.argv[3])
                os._exit(17)
            if sys.argv[2] == 'crash-prepared':
                os._exit(18)
            print('admitted')
        except BudgetExceeded:
            print('denied')
"""


def child(tmp_path, mode, attempt="attempt-1"):
    """Fresh interpreter against synthetic owner-only state, never live workspace."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(str(p) for p in sys.path if p)
    return subprocess.Popen(
        [sys.executable, "-c", _PROCESS, str(tmp_path / "usage"), mode, attempt],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def finish(process):
    stdout, stderr = process.communicate(timeout=30)
    assert not stderr, stderr
    return process.returncode, stdout.strip()


def test_fresh_process_reservations_are_atomic_at_ceiling(tmp_path):
    """Removing either transaction or process synchronisation permits overspend."""
    with ledger(tmp_path):
        pass
    results = [finish(p) for p in [child(tmp_path, "race", f"attempt-{i}") for i in range(8)]]
    assert results.count((0, "admitted")) == 1
    assert results.count((0, "denied")) == 7
    status, data = finish(child(tmp_path, "inspect"))
    assert status == 0
    assert len(json.loads(data)) == 1


@pytest.mark.parametrize(
    ("mode", "exit_code", "state"),
    [
        ("crash-prepared", 18, "PREPARED"),
        ("crash-invoked", 17, "INVOKED"),
    ],
)
def test_killed_process_keeps_exact_reservation_and_invocation(tmp_path, mode, exit_code, state):
    with ledger(tmp_path):
        pass
    assert finish(child(tmp_path, mode))[0] == exit_code
    status, data = finish(child(tmp_path, "inspect"))
    assert status == 0
    assert json.loads(data)[0]["state"] == state
    assert json.loads(data)[0]["charged"]["currency_micros"] == 60
    with api().ServiceUsageLedger(tmp_path / "usage", clock=lambda: NOW) as store:
        if state == "PREPARED":
            store.cancel_prepared("attempt-1")
            assert prepare(store, "replacement").state == "PREPARED"
        else:
            store.mark_unknown("attempt-1")
            with pytest.raises(api().BudgetExceeded):
                prepare(store, "replacement")
    if state == "INVOKED":
        assert finish(child(tmp_path, "invoke-existing")) == (0, "blocked")


def test_tariff_digest_is_stable_in_fresh_interpreter(tmp_path):
    assert finish(child(tmp_path, "digest")) == (0, tariff().digest)


def test_period_rollover_carries_unknown_but_not_settled_usage(tmp_path):
    now = [NOW]
    with api().ServiceUsageLedger(tmp_path / "usage", clock=lambda: now[0]) as store:
        store.configure_budget(policy(), expected_revision=0)
        prepare(store)
        store.mark_invoked("attempt-1")
        store.mark_unknown("attempt-1")
        now[0] += timedelta(days=1)
        store.configure_budget(policy(window_start=now[0], window_end=now[0] + timedelta(days=1)), expected_revision=1)
        with pytest.raises(api().BudgetExceeded):
            prepare(store, "attempt-2")
        store.reconcile(
            "attempt-1",
            api().UsageAmounts(requests=1, input_tokens=10, output_tokens=10, currency_micros=60),
            evidence="final receipt",
        )
        assert prepare(store, "attempt-2").state == "PREPARED"


def test_changed_tariff_does_not_reprice_prior_usage(tmp_path):
    with ledger(tmp_path) as store:
        prepare(store)
        store.mark_invoked("attempt-1")
        store.settle("attempt-1", api().UsageAmounts(requests=1, input_tokens=10, output_tokens=10, currency_micros=60))
        cheap = tariff(prices={"input_tokens": api().UnitPrice(1, 10), "output_tokens": api().UnitPrice(1, 10)})
        prepare(
            store,
            "attempt-2",
            tariff=cheap,
            reservation=api().UsageAmounts(
                requests=1, concurrency=1, input_tokens=10, output_tokens=10, currency_micros=2
            ),
        )
        records = store.list_attempts()
        assert [r.charged.currency_micros for r in records] == [60, 2]
        public = records[0].to_dict()
        public["charged"]["currency_micros"] = 0
        assert store.get_attempt("attempt-1").charged.currency_micros == 60


def test_storage_rejects_linked_or_missing_database(tmp_path):
    with ledger(tmp_path) as store:
        prepare(store)
    database = tmp_path / "usage" / "usage.sqlite"
    preserved = tmp_path / "preserved.sqlite"
    database.rename(preserved)
    with pytest.raises(api().UsageUnavailable):
        api().ServiceUsageLedger(tmp_path / "usage", clock=lambda: NOW)
    if os.name != "nt":
        database.symlink_to(preserved)
        with pytest.raises(OSError):
            api().ServiceUsageLedger(tmp_path / "usage", clock=lambda: NOW)


def test_known_cost_overflow_cannot_erase_observed_overage(tmp_path):
    """Repricing overflow must not erase a trustworthy reported overage."""
    with ledger(tmp_path) as store:
        prepare(store)
        store.mark_invoked("attempt-1")
        actual = api().UsageAmounts(requests=1, input_tokens=(1 << 63) - 1, currency_micros=(1 << 63) - 1)
        result = store.settle("attempt-1", actual)
        assert result.charged.input_tokens == (1 << 63) - 1
        with pytest.raises(api().BudgetExceeded):
            prepare(store, "attempt-2")


def test_period_edit_cannot_erase_current_period_spend(tmp_path):
    with ledger(tmp_path) as store:
        prepare(store)
        store.mark_invoked("attempt-1")
        store.settle("attempt-1", api().UsageAmounts(requests=1, input_tokens=10, output_tokens=10, currency_micros=60))
        with pytest.raises(api().UsageConflict):
            store.configure_budget(policy(window_start=NOW + timedelta(seconds=1)), expected_revision=1)


def test_storage_remains_charged_across_budget_periods(tmp_path):
    now = [NOW]
    with api().ServiceUsageLedger(tmp_path / "usage", clock=lambda: now[0]) as store:
        store.configure_budget(policy(limits={"storage_bytes": 10}), expected_revision=0)
        prepare(
            store, reservation=api().UsageAmounts(requests=1, concurrency=1, storage_bytes=10), tariff=tariff(prices={})
        )
        store.mark_invoked("attempt-1")
        store.settle("attempt-1", api().UsageAmounts(requests=1, storage_bytes=10))
        now[0] += timedelta(days=1)
        store.configure_budget(
            policy(limits={"storage_bytes": 10}, window_start=now[0], window_end=now[0] + timedelta(days=1)),
            expected_revision=1,
        )
        with pytest.raises(api().BudgetExceeded):
            prepare(
                store,
                "attempt-2",
                reservation=api().UsageAmounts(requests=1, concurrency=1, storage_bytes=1),
                tariff=tariff(prices={}),
            )


def test_cross_process_invocation_wins_once(tmp_path):
    with ledger(tmp_path) as store:
        prepare(store)
    results = [finish(p) for p in [child(tmp_path, "invoke-existing") for _ in range(5)]]
    assert results.count((0, "invoked")) == 1
    assert results.count((0, "blocked")) == 4


def test_missing_usage_or_invalid_settlement_keeps_reservation(tmp_path):
    with ledger(tmp_path) as store:
        prepare(store)
        store.mark_invoked("attempt-1")
        for invalid in (None, {}, api().UsageAmounts(requests=0), api().UsageAmounts(requests=1, concurrency=1)):
            with pytest.raises(ValueError):
                store.settle("attempt-1", invalid)
        assert store.get_attempt("attempt-1").charged.currency_micros == 60


def test_stale_policy_and_admission_mismatch_refuse_before_insert(tmp_path):
    with ledger(tmp_path) as store:
        with pytest.raises(api().UsageConflict):
            store.configure_budget(policy(), expected_revision=0)
        with pytest.raises(api().UsageConflict):
            store.configure_budget(policy(currency="INR"), expected_revision=1)
        for options in (
            {"reservation": api().UsageAmounts(requests=1, concurrency=1, input_tokens=10)},
            {"tariff": tariff(effective_until=NOW)},
            {"tariff": tariff(prices=None), "conservative_cost_ceiling": 0},
            {"tariff": tariff(prices=None), "conservative_cost_ceiling": True},
        ):
            with pytest.raises(ValueError):
                prepare(store, **options)
        assert store.list_attempts() == ()


def test_fx_evidence_roundtrip_and_unknown_dimensions_are_not_dropped(tmp_path):
    snap = tariff(exchange_rate=api().ExchangeRate("INR", 84, 1, "fixture FX", NOW))
    assert api().TariffSnapshot.from_dict(snap.to_dict()).digest == snap.digest
    for options in (
        {"prices": {"invented": api().UnitPrice(1)}},
        {"rounding": "floor"},
        {"price_dimension": "inr"},
        {"markup_basis_points": True},
    ):
        with pytest.raises(ValueError):
            tariff(**options)
    with ledger(tmp_path) as store:
        prepare(store, tariff=snap)
        assert store.get_attempt("attempt-1").tariff.exchange_rate.target_currency == "INR"


def test_provider_credit_tariffs_have_exact_credit_units(tmp_path):
    with api().ServiceUsageLedger(tmp_path / "usage", clock=lambda: NOW) as store:
        store.configure_budget(policy(currency="TEST_CREDIT", limits={"credits_micros": 4}), expected_revision=0)
        credit = tariff(
            currency="TEST_CREDIT", price_dimension="credits_micros", prices={"requests": api().UnitPrice(3)}
        )
        prepare(store, tariff=credit, reservation=api().UsageAmounts(requests=1, concurrency=1, credits_micros=3))
        with pytest.raises(api().BudgetExceeded):
            prepare(
                store,
                "attempt-2",
                tariff=credit,
                reservation=api().UsageAmounts(requests=1, concurrency=1, credits_micros=3),
            )


def test_prior_period_prepared_attempt_cannot_invoke_after_rollover(tmp_path):
    """A prior-period invocation must not hide its eventual bill from the active budget."""
    now = [NOW]
    with api().ServiceUsageLedger(tmp_path / "usage", clock=lambda: now[0]) as store:
        store.configure_budget(policy(), expected_revision=0)
        original = prepare(store)
        now[0] += timedelta(days=1)
        store.configure_budget(policy(window_start=now[0], window_end=now[0] + timedelta(days=1)), expected_revision=1)
        with pytest.raises(api().UsageConflict):
            store.mark_invoked("attempt-1")
        assert store.get_attempt("attempt-1") == original
        with pytest.raises(api().BudgetExceeded):
            prepare(store, "attempt-2")
        store.cancel_prepared("attempt-1")
        prepare(store, "attempt-2")
        store.mark_invoked("attempt-2")
        store.settle(
            "attempt-2", api().UsageAmounts(requests=1, input_tokens=10, output_tokens=25, currency_micros=120)
        )
        with pytest.raises(api().BudgetExceeded):
            prepare(store, "attempt-3")


@pytest.mark.parametrize("advance_seconds", [1, 2])
def test_expired_tariff_cannot_invoke_prepared_attempt(tmp_path, advance_seconds):
    """The tariff's exclusive expiry must be checked again immediately before invocation."""
    now = [NOW]
    with api().ServiceUsageLedger(tmp_path / "usage", clock=lambda: now[0]) as store:
        store.configure_budget(policy(), expected_revision=0)
        original = prepare(store, tariff=tariff(effective_until=NOW + timedelta(seconds=1)))
        now[0] += timedelta(seconds=advance_seconds)
        with pytest.raises(api().UsageConflict):
            store.mark_invoked("attempt-1")
        assert store.get_attempt("attempt-1") == original
        store.cancel_prepared("attempt-1")
        prepare(store, "attempt-2")
        assert store.mark_invoked("attempt-2").state == "INVOKED"
