"""Real SQLite fault injection for Practice lifecycle evidence."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest
from flask import Flask

from flinttrade_ai.run_store import AgentRunStore
from flinttrade_core import practice_agent_runtime as runtime

pytestmark = pytest.mark.unit


@pytest.fixture
def transition_runtime(tmp_path, backend_lease_proof, monkeypatch):
    app = Flask(__name__)
    app.config.update(BACKEND_LEASE_PROOF=backend_lease_proof, RUNTIME_ACCEPTING_REQUESTS=True)
    monkeypatch.setattr(runtime, "_enabled", lambda: True)
    store = AgentRunStore(tmp_path / "runs.sqlite")
    supervisor = runtime.PracticeAgentSupervisor(app, store)
    row = store.create_run(run_id="run-1", mode="practice", config={"owner": "operator"})
    run = runtime._Run("run-1", "operator", {}, row["created_at"])
    try:
        yield supervisor, run
    finally:
        supervisor._close_store()


@pytest.mark.parametrize("failure", ["invalid_snapshot", "row_write"])
def test_failed_transition_never_commits_phantom_event_or_releases_fence(transition_runtime, failure):
    supervisor, run = transition_runtime
    store = supervisor.store
    original = store.get_run(run.run_id)
    if failure == "invalid_snapshot":
        run.snapshot = {"cycle_count": float("nan")}
        expected_error = ValueError
    else:
        with sqlite3.connect(store.database_path) as conn:
            conn.execute("""CREATE TRIGGER reject_transition BEFORE UPDATE ON agent_runs BEGIN
                SELECT RAISE(ABORT, 'synthetic snapshot failure'); END""")
        expected_error = sqlite3.DatabaseError
    previous_snapshot = run.snapshot

    with pytest.raises(expected_error):
        supervisor._persist(run, "stopped")

    assert run.evidence_failed
    assert run.stop.is_set()
    assert run.status == original["status"]
    assert run.error == ""
    assert run.snapshot is previous_snapshot
    assert store.get_run(run.run_id) == original
    assert store.events(run.run_id) == []
    with pytest.raises(RuntimeError, match="active"):
        store.create_run(run_id="new-run", mode="practice", config={})

    if failure == "row_write":
        with sqlite3.connect(store.database_path) as conn:
            conn.execute("DROP TRIGGER reject_transition")
    run.snapshot = {}
    supervisor._persist(run, "reconciliation_required")
    event = store.events(run.run_id)[0]
    assert event["data"] == {"previous": "starting", "status": "reconciliation_required"}


def test_failed_resolution_keeps_reconciliation_fence_without_phantom_event(transition_runtime):
    supervisor, run = transition_runtime
    store = supervisor.store
    supervisor.app.config["DATA_SANDBOX_ENGINE"] = SimpleNamespace(
        get_positions=lambda: [], get_all_orders=lambda: [],
    )
    supervisor.run = run
    run.cleanup_complete = True
    run.status = "reconciliation_required"
    original = store.update_run(run.run_id, status="reconciliation_required")
    with sqlite3.connect(store.database_path) as conn:
        conn.execute("""CREATE TRIGGER reject_resolution BEFORE UPDATE ON agent_runs BEGIN
            SELECT RAISE(ABORT, 'synthetic resolution failure'); END""")

    with pytest.raises(sqlite3.DatabaseError, match="synthetic resolution failure"):
        supervisor.resolve(run.owner, run.run_id)

    assert store.get_run(run.run_id) == original
    assert store.events(run.run_id) == []
    assert run.status == "reconciliation_required"
    with pytest.raises(RuntimeError, match="active"):
        store.create_run(run_id="new-run", mode="practice", config={})
    with sqlite3.connect(store.database_path) as conn:
        conn.execute("DROP TRIGGER reject_resolution")
    resolved = supervisor.resolve(run.owner, run.run_id)
    assert resolved["status"] == "stopped"
    assert resolved["snapshot"]["status"] == "stopped"
    assert [event["kind"] for event in store.events(run.run_id)] == ["reconciliation_resolved"]


def test_interrupted_transition_restores_volatile_state_and_brakes(transition_runtime, monkeypatch):
    supervisor, run = transition_runtime
    original = supervisor.store.get_run(run.run_id)
    previous_snapshot = run.snapshot

    def interrupt_snapshot(_run):
        raise KeyboardInterrupt

    monkeypatch.setattr(supervisor, "_snapshot", interrupt_snapshot)
    with pytest.raises(KeyboardInterrupt):
        supervisor._persist(run, "stopped")
    assert run.status == original["status"]
    assert run.error == ""
    assert run.snapshot is previous_snapshot
    assert run.evidence_failed
    assert run.stop.is_set()
    assert supervisor.store.get_run(run.run_id) == original
    assert supervisor.store.events(run.run_id) == []
