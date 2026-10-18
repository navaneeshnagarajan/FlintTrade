"""Run-owned version handover contract with inert serving and execution owner."""
from contextlib import contextmanager
from dataclasses import replace
import pytest

pytestmark = pytest.mark.unit


class Runs:
    def __init__(self):
        from flinttrade_core.artifact_activation import RunState
        self.state = RunState("run", "admission", "paper:fixture", "paper", 1, 1,
                              "risk-v1", "orders-fills-1", "protector", True, "old", True)
        self.ledger = {"orders": ["unknown-order"], "fills": ["partial-fill"], "pnl": 17}
    def snapshot(self, run, role):
        return self.state
    @contextmanager
    def fence(self, run, role):
        yield
    def bind(self, candidate, expected):
        assert self.state == expected
        self.state = replace(self.state, binding=candidate, generation=self.state.generation + 1)
    def pause_entries(self, run, role):
        self.state = replace(self.state, entries_armed=False)


class Serving:
    staging_preserves_incumbent = True
    def __init__(self):
        self.active = "old"
        self.loads = []
        self.on_stage = lambda: None
    def stage(self, candidate, state):
        self.loads.append(candidate)
        self.on_stage()
        return candidate
    def identity(self, handle):
        return handle
    def commit(self, handle, run, role):
        self.active = handle
    def current(self, run, role):
        return self.active


def setup(tmp_path):
    from flinttrade_core.artifact_activation import ArtifactActivation
    runs, serving = Runs(), Serving()
    grant = {"id": "grant", "generation": 1, "run_id": "run", "role": "admission", "account": "paper:fixture",
             "environment": "paper", "risk_fingerprint": "risk-v1", "valid_until": 100,
             "identity_scope": "connection-revision-1", "operation": "planned-adoption"}
    def qualification(candidate):
        return {"candidate": candidate, "identity": candidate, "role": "admission", "qualified": True,
                "independent": True, "prospective": "shadow-v1", "policy": "policy-v1",
                "identity_scope": "connection-revision-1", "valid_until": 100, "receipt": "evaluation-v1"}
    coordinator = ArtifactActivation(tmp_path / "adoptions.db", runs=runs, serving=serving,
        authority=lambda state, candidate: dict(grant), qualification=qualification, clock=lambda: 10)
    return coordinator, runs, serving, grant


def test_A08_atomic_same_limit_adoption_and_A11_rollback_preserve_current_execution_ledger(tmp_path):
    owner, runs, serving, _ = setup(tmp_path)
    before = dict(runs.ledger)
    result = owner.adopt("request", run_id="run", role="admission", candidate="new", expected_generation=1)
    assert result["status"] == "completed"
    assert runs.state.binding == serving.active == "new"
    assert runs.state.entries_armed is True
    assert owner.adopt("request", run_id="run", role="admission", candidate="new", expected_generation=1) == result
    assert serving.loads == ["new"]
    assert not owner.accepts("run", "admission", generation=1, candidate="old")
    runs.ledger["fills"].append("new-fill")
    owner.adopt("rollback", run_id="run", role="admission", candidate="old", expected_generation=2, kind="rollback")
    assert runs.state.binding == serving.active == "old"
    assert runs.ledger["orders"] == before["orders"]
    assert runs.ledger["fills"] == ["partial-fill", "new-fill"]
    assert runs.ledger["pnl"] == 17


@pytest.mark.parametrize("change", ["expired", "role", "account", "risk", "grant-missing", "unqualified"])
def test_A01_A02_A03_refuse_without_exact_current_authority_or_evidence(tmp_path, change):
    owner, runs, serving, grant = setup(tmp_path)
    if change == "expired":
        grant["valid_until"] = 9
    if change == "role":
        grant["role"] = "forecast"
    if change == "account":
        grant["account"] = "other"
    if change == "risk":
        grant["risk_fingerprint"] = "larger-risk"
    if change == "grant-missing":
        grant.clear()
    if change == "unqualified":
        owner.qualification = lambda candidate: None
    result = owner.adopt("request", run_id="run", role="admission", candidate="new", expected_generation=1)
    assert result["status"] == "refused"
    assert serving.loads == []
    assert runs.state.binding == "old"


@pytest.mark.parametrize("change", ["fill", "config", "risk", "revoke", "protection"])
def test_A05_A06_revalidate_at_commit_fence(tmp_path, change):
    owner, runs, serving, grant = setup(tmp_path)
    def stage():
        if change == "fill":
            runs.state = replace(runs.state, frontier="orders-fills-2")
        if change == "config":
            runs.state = replace(runs.state, config_generation=2)
        if change == "risk":
            runs.state = replace(runs.state, risk_fingerprint="changed")
        if change == "revoke":
            grant["valid_until"] = 9
        if change == "protection":
            runs.state = replace(runs.state, protection_verified=False)
    serving.on_stage = stage
    result = owner.adopt("request", run_id="run", role="admission", candidate="new", expected_generation=1)
    assert result["status"] == "refused"
    assert serving.active == runs.state.binding == "old"


def test_A04_failed_load_retains_incumbent_and_A13_unknown_commit_is_not_replayed(tmp_path):
    owner, runs, serving, _ = setup(tmp_path)
    serving.on_stage = lambda: (_ for _ in ()).throw(RuntimeError("load failed"))
    assert owner.adopt("load", run_id="run", role="admission", candidate="new", expected_generation=1)["status"] == "refused"
    assert serving.active == runs.state.binding == "old"
    serving.on_stage = lambda: None
    def commit(*args): raise TimeoutError()
    serving.commit = commit
    result = owner.adopt("cutover", run_id="run", role="admission", candidate="new", expected_generation=1)
    assert result["status"] == "unknown"
    assert runs.state.entries_armed is False
    assert owner.adopt("cutover", run_id="run", role="admission", candidate="new", expected_generation=1) == result
    assert serving.loads == ["new", "new"]
    assert owner.reconcile("cutover")["status"] == "unknown"


def test_A07_evidence_write_failure_prevents_binding_and_A08_readback_checks_all_fences(tmp_path):
    owner, runs, serving, _ = setup(tmp_path)
    original_event = owner._event
    def broken_evidence(identity, **body):
        if body.get("phase") == "commit_intent":
            raise OSError("disk full")
        return original_event(identity, **body)
    owner._event = broken_evidence
    result = owner.adopt("disk", run_id="run", role="admission", candidate="new", expected_generation=1)
    assert result["status"] == "refused"
    assert runs.state.binding == serving.active == "old"
    owner._event = original_event
    bind = runs.bind
    def corrupt_binding(candidate, expected):
        bind(candidate, expected)
        runs.state = replace(runs.state, risk_fingerprint="widened")
    runs.bind = corrupt_binding
    result = owner.adopt("corrupt", run_id="run", role="admission", candidate="new", expected_generation=1)
    assert result["status"] == "unknown"
    assert not runs.state.entries_armed


def test_A10_drift_pauses_entries_without_failover_and_A15_disruptive_selector_refused(tmp_path):
    owner, runs, serving, _ = setup(tmp_path)
    owner.adopt("request", run_id="run", role="admission", candidate="new", expected_generation=1)
    serving.active = "drift"
    assert owner.check("run", "admission") is False
    assert runs.state.entries_armed is False
    assert runs.state.protection_verified is True
    serving.staging_preserves_incumbent = False
    assert owner.adopt("outage-repair", run_id="run", role="admission", candidate="other", expected_generation=2)["status"] == "refused"


def test_A12_failed_rollback_pauses_entries_but_retains_verified_protection(tmp_path):
    owner, runs, serving, _ = setup(tmp_path)
    owner.adopt("request", run_id="run", role="admission", candidate="new", expected_generation=1)
    serving.on_stage = lambda: (_ for _ in ()).throw(RuntimeError("retained target unavailable"))
    result = owner.adopt("rollback", run_id="run", role="admission", candidate="old", expected_generation=2, kind="rollback")
    assert result["status"] == "refused"
    assert runs.state.binding == serving.active == "new"
    assert not runs.state.entries_armed
    assert result["protection_verified"] is True


def test_A13_A14_lost_ack_reconciles_actual_identity_without_replay_or_rearming(tmp_path):
    owner, runs, serving, grant = setup(tmp_path)
    def lost_ack(handle, run, role):
        serving.active = handle
        raise TimeoutError()
    serving.commit = lost_ack
    owner.adopt("request", run_id="run", role="admission", candidate="new", expected_generation=1)
    from flinttrade_core.artifact_activation import ArtifactActivation
    recovered = ArtifactActivation(tmp_path / "adoptions.db", runs=runs, serving=serving,
        authority=owner.authority, qualification=owner.qualification, clock=lambda: 10)
    assert recovered.reconcile("request")["status"] == "completed"
    assert not runs.state.entries_armed
    assert runs.state.protection_verified
    assert serving.loads == ["new"]


def test_A07_concurrent_adopters_cannot_both_commit_one_generation(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, RLock
    owner, runs, serving, _ = setup(tmp_path)
    lock, barrier = RLock(), Barrier(2)
    @contextmanager
    def fence(run, role):
        with lock:
            yield
    runs.fence = fence
    serving.on_stage = lambda: barrier.wait(timeout=5)
    def adopt(identity):
        return owner.adopt(identity, run_id="run", role="admission", candidate=identity, expected_generation=1)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(adopt, ("one", "two")))
    assert sorted(r["status"] for r in results) == ["completed", "refused"]
    assert runs.state.generation == 2
    assert serving.active == runs.state.binding
