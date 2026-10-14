"""Actual Practice supervisor, canonical order admission and immutable scope."""
from __future__ import annotations

import asyncio
import importlib.util

import pytest

from packages.core.core.tests.test_practice_agent_runtime import desk as desk, _start, _supervisor, _wait_for

pytestmark = pytest.mark.integration


def owner_for(desk):
    assert importlib.util.find_spec("flinttrade_core.execution_session") is not None, "execution owner missing"
    from flinttrade_core.execution_session import PracticeRunOwner
    result = _start(desk, cycle_interval_sec=3600)
    assert result.status_code == 202, result.json
    supervisor = _supervisor(desk)
    _wait_for(lambda: supervisor.run.trader is not None and supervisor.run.status == "running")
    return PracticeRunOwner(supervisor)


def test_binding_changes_only_model_epoch_not_execution_ledger(desk):
    owner = owner_for(desk)
    run_id = _supervisor(desk).run.run_id
    before = owner.snapshot(run_id, "reasoning")
    assert before.account == "paper:sandbox" and before.environment == "paper"
    assert before.protection_verified
    books = (desk.sandbox.get_all_orders(), desk.sandbox.get_trades(), desk.sandbox.get_pnl())
    with owner.fence(run_id, "reasoning"):
        owner.bind("candidate-next", before)
    after = owner.snapshot(run_id, "reasoning")
    assert after.binding == "candidate-next" and after.generation == before.generation + 1
    assert after.entries_armed == before.entries_armed
    assert (desk.sandbox.get_all_orders(), desk.sandbox.get_trades(), desk.sandbox.get_pnl()) == books
    assert owner.scope(run_id).actor == desk.owner
    with pytest.raises(ValueError):
        owner.bind("stale", before)
    owner.pause_entries(run_id, "reasoning")
    assert not owner.snapshot(run_id, "reasoning").entries_armed
    assert not _supervisor(desk).run.stop.is_set(), "pausing models must not request liquidation"


def test_old_generation_proposal_rejected_at_real_sandbox_write(desk):
    owner = owner_for(desk)
    run = _supervisor(desk).run
    class Activation:
        def accepts(self, run_id, role, *, generation, candidate):
            state = owner.snapshot(run_id, role)
            return state.entries_armed and (state.generation, state.binding) == (generation, candidate)
    run.adapter.bind_model_admission(owner, Activation(), run.run_id, "reasoning")
    old = owner.snapshot(run.run_id, "reasoning")
    run.adapter.record_model_proposal(old.generation, old.binding)
    owner.bind("new", old)
    result = asyncio.run(run.adapter.place_order(symbol="RELIANCE", exchange="NSE", product="MIS", action="BUY", quantity=1))
    assert result.get("code") == "practice_model_generation_retired", result
    assert desk.sandbox.get_trades() == []
    current = owner.snapshot(run.run_id, "reasoning")
    run.adapter.record_model_proposal(current.generation, current.binding)
    accepted = asyncio.run(run.adapter.place_order(symbol="RELIANCE", exchange="NSE", product="MIS", action="BUY", quantity=1))
    assert accepted["status"] == "COMPLETE", accepted
    owner.pause_entries(run.run_id, "reasoning")
    run.adapter.record_model_proposal(old.generation, old.binding)
    stale_reduction = asyncio.run(run.adapter.place_order(symbol="RELIANCE", exchange="NSE", product="MIS", action="SELL", quantity=1))
    assert stale_reduction.get("code") == "practice_model_generation_retired", stale_reduction
    from flinttrade_core.models import Order
    reduction = Order(symbol="RELIANCE", exchange="NSE", product="MIS", action="SELL", quantity="1", pricetype="MARKET")
    with run.adapter.protective_action():
        reduced = asyncio.run(run.adapter.route_order(reduction))
    assert reduced.passed, reduced
    assert len(desk.sandbox.get_trades()) == 2


def test_actual_supervisor_fixed_squareoff_is_model_independent(desk):
    desk.signal = "BUY"
    owner = owner_for(desk)
    supervisor = _supervisor(desk)
    _wait_for(lambda: bool(supervisor.run.trader.state.active_positions))
    run = supervisor.run
    class NoModel:
        def accepts(self, *_args, **_kwargs):
            raise AssertionError("Fixed protection consulted model generation")
    run.adapter.bind_model_admission(owner, NoModel(), run.run_id, "reasoning")
    owner.pause_entries(run.run_id, "reasoning")
    supervisor.stop(desk.owner)
    _wait_for(lambda: run.cleanup_complete)
    assert desk.sandbox.get_positions() == [], run.error
    assert len(desk.sandbox.get_trades()) == 2
