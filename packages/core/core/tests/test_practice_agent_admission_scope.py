"""Canonical Paper account selection at the durable normal-write lease."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from flinttrade_core import order_routes
from flinttrade_core.execution_session import ExecutionSession
from flinttrade_core.execution_sessions import ExecutionSessions
from flinttrade_core.models import Action
from flinttrade_core.practice_agent_adapter import PracticeAgentAdapter, PracticeAgentError
from flinttrade_core.practice_agent_runtime import validate_practice_config
from flinttrade_engine.emergency_intents import EmergencyIntentJournal
from flinttrade_engine.safety import KillSwitchActiveError, SafetyBypassError
from packages.core.core.tests.test_practice_agent_adapter import _order, runtime as runtime
from packages.core.core.tests.test_practice_agent_runtime import _wait_for, desk as desk

pytestmark = pytest.mark.integration


async def test_legacy_write_uses_real_journal_with_canonical_sandbox_owner(runtime, tmp_path, monkeypatch):
    journal = EmergencyIntentJournal(tmp_path / "emergency.sqlite3")
    kill = runtime.app.config["SAFETY"].l5_kill
    kill.bind_emergency_journal(journal)
    observed = []
    original = journal.blocking_sources

    def record(selector):
        observed.append(selector)
        return original(selector)

    monkeypatch.setattr(journal, "blocking_sources", record)
    adapter = runtime.create()
    decision = await adapter.route_order(_order())
    assert decision.passed, decision.response
    assert observed == ["paper:sandbox"]
    assert journal.active_episodes("l5") == ()
    assert runtime.sandbox.get_positions()[0]["net_qty"] == 1
    assert kill._normal_writes_in_progress == 0
    reduced = await adapter.route_order(_order(action=Action.SELL))
    assert reduced.passed, reduced.response
    assert runtime.sandbox.get_positions() == []
    assert len(runtime.sandbox.get_trades()) == 2
    assert observed == ["paper:sandbox"]  # Proven reduction does not become a normal lease.


async def test_unavailable_real_journal_is_not_reported_as_kill_activation(runtime, tmp_path):
    path = tmp_path / "emergency.sqlite3"
    journal = EmergencyIntentJournal(path)
    kill = runtime.app.config["SAFETY"].l5_kill
    kill.bind_emergency_journal(journal)
    path.unlink()
    path.mkdir()  # Established journal cannot be opened, not an active episode.
    decision = await runtime.create().route_order(_order())
    assert not decision.passed
    assert decision.response["code"] == "practice_safety_unavailable"
    assert not kill.is_active
    assert runtime.sandbox.get_trades() == []
    assert kill._normal_writes_in_progress == 0


@pytest.fixture
def scoped_runs(desk, tmp_path, monkeypatch):
    journal = EmergencyIntentJournal(tmp_path / "emergency.sqlite3")
    desk.app.config["SAFETY"].l5_kill.bind_emergency_journal(journal)
    selectors = []
    original = journal.blocking_sources

    def observe(selector):
        selectors.append(selector)
        return original(selector)

    monkeypatch.setattr(journal, "blocking_sources", observe)
    sessions = ExecutionSessions(desk.app, tmp_path / "sessions")
    scopes = [ExecutionSession(name, desk.owner, "paper:run:" + name, "paper") for name in ("first", "second")]
    try:
        for scope in scopes:
            sessions.create(scope, kind="practice", config=validate_practice_config(
                {"symbols": ["RELIANCE"], "cycle_interval_sec": 3600}))
            sessions.start(scope, token=desk.token(), expected_generation=0)
        _wait_for(lambda: all(sessions.owners[s.run_id].run.snapshot.get("cycle_count") == 1 for s in scopes))
        yield sessions, scopes, journal, selectors
    finally:
        for scope in scopes:
            owner = sessions.owners.get(scope.run_id)
            if owner is not None and owner.run.thread.is_alive():
                if owner.sandbox.get_positions():
                    # These seam tests placed through the adapter, not the
                    # trader monitor. Clean up through that same scoped ingress.
                    with owner.run.adapter.protective_action():
                        reduction = asyncio.run(owner.run.adapter.route_order(_order(action=Action.SELL)))
                    assert reduction.passed, reduction.response
                    assert owner.sandbox.get_positions() == []
                sessions.close_positions(scope, expected_generation=sessions.status(scope)["generation"])
        _wait_for(lambda: all(not owner.run.thread.is_alive() for owner in sessions.owners.values()))
        assert all(sessions.status(scope)["books"]["positions"] == [] for scope in scopes)
        assert sessions.shutdown(timeout=5)
        sessions.close()
        if desk.sandbox.get_positions():
            result = asyncio.run(PracticeAgentAdapter(desk.app, desk.token()).route_order(_order(action=Action.SELL)))
            assert result.passed, result.response
        assert desk.sandbox.get_positions() == []


def test_normal_lease_uses_each_registered_run_not_data_or_order_selectors(scoped_runs, desk, monkeypatch):
    sessions, scopes, journal, selectors = scoped_runs
    for scope in scopes:
        owner = sessions.owners[scope.run_id]
        binding = owner.execution_binding
        original = owner.sandbox.place_order

        def counted_fill(*args, _original=original, _binding=binding, **kwargs):
            assert desk.app.config["SAFETY"].l5_kill._normal_writes_in_progress == 1
            assert sessions.lock._is_owned() and _binding.sandbox._lock._is_owned()
            assert selectors[-1] == _binding.scope.account
            return _original(*args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(owner.sandbox, "place_order", counted_fill)
            result = asyncio.run(owner.run.adapter.place_order(
                symbol="RELIANCE", exchange="NSE", product="MIS", action="BUY", quantity=1,
                selector="dhan:Quotes", account="paper:sandbox", run_id="second"))
            assert result["status"] == "COMPLETE", result
        assert len(owner.sandbox.get_trades()) == 1
    assert selectors == [scope.account for scope in scopes]
    assert desk.sandbox.get_positions() == []
    legacy = PracticeAgentAdapter(desk.app, desk.token())
    assert asyncio.run(legacy.route_order(_order())).passed
    assert selectors == [scope.account for scope in scopes] + ["paper:sandbox"]
    assert all(sessions.status(scope)["books"]["positions"][0]["net_qty"] == 1 for scope in scopes)
    assert journal.active_episodes("l5") == ()


@pytest.mark.parametrize("selector", ["*", "paper:run:first"])
def test_durable_global_and_exact_run_kills_refuse_without_sharing_books(scoped_runs, desk, selector):
    sessions, scopes, journal, selectors = scoped_runs
    first, second = scopes
    journal.activate_episode(source="l5", selector=selector, session_key="manual", reason_hash="a" * 64)
    # A foreign scoped durable episode does not masquerade as this account's
    # episode. Once L5 restores its global latch, its existing global policy stays.
    if selector != "*":
        other = asyncio.run(sessions.owners[second.run_id].run.adapter.route_order(_order()))
        assert other.passed, other.response
        assert selectors == [second.account]
    result = asyncio.run(sessions.owners[first.run_id].run.adapter.route_order(_order()))
    assert result.response["code"] == "practice_kill_switch_active"
    assert desk.app.config["SAFETY"].l5_kill.is_active
    assert sessions.status(first)["books"]["trades"] == []
    assert desk.sandbox.get_trades() == []
    assert journal.active_episodes("l5")[0].selector == selector


@pytest.mark.parametrize("mutation", ["scope", "book", "registry", "generation"])
def test_invalid_or_retired_binding_never_uses_legacy_admission(scoped_runs, desk, mutation):
    sessions, scopes, _journal, selectors = scoped_runs
    first, second = scopes
    binding = sessions.binding(first)
    changed = {
        "scope": {"scope": replace(first, account="malformed")},
        "book": {"sandbox": sessions.binding(second).sandbox},
        "registry": {"registry": object()},
        "generation": {"generation": binding.generation - 1},
    }[mutation]
    bad = replace(binding, **changed)
    if mutation == "generation":
        adapter = PracticeAgentAdapter(desk.app, desk.token(), execution_binding=bad)
        result = asyncio.run(adapter.route_order(_order()))
        assert result.response["code"] == "practice_execution_scope_invalid"
    else:
        with pytest.raises((PracticeAgentError, ValueError, AttributeError)):
            PracticeAgentAdapter(desk.app, desk.token(), execution_binding=bad)
    assert selectors == []
    assert all(sessions.status(scope)["books"]["trades"] == [] for scope in scopes)
    assert desk.sandbox.get_trades() == []


def test_missing_canonical_request_binding_refuses_before_lease(scoped_runs, desk):
    sessions, scopes, _journal, selectors = scoped_runs
    adapter = sessions.owners[scopes[0].run_id].run.adapter
    context = asyncio.run(adapter._context("RELIANCE", "NSE", fresh=True))
    body = adapter._body({"symbol": "RELIANCE", "exchange": "NSE", "product": "MIS", "action": "BUY", "quantity": 1})
    with desk.app.test_request_context("/api/v1/orders/place", method="POST", json=body):
        response, status = adapter._locked_dispatch_guard(body, [], [], context)
        assert status == 409 and response.get_json()["code"] == "practice_execution_scope_invalid"
    assert selectors == []


def test_retired_session_generation_cannot_enter(scoped_runs, desk):
    sessions, scopes, _journal, selectors = scoped_runs
    scope = scopes[0]
    adapter = sessions.owners[scope.run_id].run.adapter
    sessions.stop_entries(scope, expected_generation=sessions.status(scope)["generation"])
    result = asyncio.run(adapter.route_order(_order()))
    assert result.response["code"] == "practice_stopped"
    assert selectors == []
    assert sessions.status(scope)["books"]["trades"] == []


def test_model_generation_and_fixed_reduction_keep_real_journal(desk, tmp_path):
    from packages.core.core.tests.test_execution_session import test_old_generation_proposal_rejected_at_real_sandbox_write

    journal = EmergencyIntentJournal(tmp_path / "emergency.sqlite3")
    desk.app.config["SAFETY"].l5_kill.bind_emergency_journal(journal)
    # Replay the existing real-owner epoch/one-shot/reduction oracles unchanged.
    test_old_generation_proposal_rejected_at_real_sandbox_write(desk)
    assert desk.sandbox.get_positions() == []
    assert desk.app.config["SAFETY"].l5_kill._normal_writes_in_progress == 0


@pytest.mark.parametrize("error_type", [ValueError, SafetyBypassError, KillSwitchActiveError])
async def test_lease_body_exception_is_not_relabelled_and_releases_count(runtime, tmp_path, error_type):
    journal = EmergencyIntentJournal(tmp_path / "emergency.sqlite3")
    kill = runtime.app.config["SAFETY"].l5_kill
    kill.bind_emergency_journal(journal)
    adapter = runtime.create()
    body = adapter._body({"symbol": "RELIANCE", "exchange": "NSE", "product": "MIS", "action": "BUY", "quantity": 1})
    failure = error_type("body failure, not admission")
    with pytest.raises(error_type) as raised, adapter._write_admission(body, runtime.context):
        assert kill._normal_writes_in_progress == 1
        raise failure
    assert raised.value is failure
    assert kill._normal_writes_in_progress == 0
    assert runtime.sandbox.get_trades() == []


async def test_activation_after_laya_before_lease_refuses_with_typed_cause(runtime, tmp_path, monkeypatch):
    journal = EmergencyIntentJournal(tmp_path / "emergency.sqlite3")
    kill = runtime.app.config["SAFETY"].l5_kill
    kill.bind_emergency_journal(journal)
    original = order_routes._admit_place

    def activate_after_laya(*args, **kwargs):
        result = original(*args, **kwargs)
        journal.activate_episode(source="l5", selector="paper:sandbox", session_key="manual", reason_hash="b" * 64)
        assert not kill.is_active
        return result

    monkeypatch.setattr(order_routes, "_admit_place", activate_after_laya)
    decision = await runtime.create().route_order(_order())
    assert decision.response["code"] == "practice_kill_switch_active"
    assert runtime.sandbox.get_trades() == []
    assert kill.is_active and kill._normal_writes_in_progress == 0
