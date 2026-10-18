"""Run composition through the normal factory; synthetic authority only."""
from __future__ import annotations

import importlib.util

import pytest

from packages.core.core.tests.test_service_tasks import mounted as mounted, create, configure, policy, BASE, HEADERS, NOW
from packages.core.core.tests.test_practice_agent_runtime import desk as desk, _wait_for

pytestmark = pytest.mark.integration


def install(app, workspace):
    assert importlib.util.find_spec("flinttrade_core.run_adoption") is not None, "run installer missing"
    from flinttrade_core.run_adoption import install_run_services
    return install_run_services(app, workspace)


def test_normal_factory_installer_is_lazy_and_close_is_idempotent(mounted, tmp_path):
    app, client, store, calls = mounted
    workspace = store.workspace_dir
    owner = app.config["MODEL_RUN_SERVICES"]
    assert owner.workspace == workspace
    assert install(app, workspace) is owner
    assert app.config["ARTIFACT_ACTIVATION"] is owner.adoptions
    assert app.config["TRAINING_JOBS"] is owner.training
    with pytest.raises(ValueError, match="different scope"):
        install(app, tmp_path / "different-run-services")
    assert app.config["MODEL_RUN_SERVICES"] is owner
    assert owner._activation is None and owner._training is None
    assert not (workspace / "artifact-adoptions.sqlite").exists()
    assert not calls
    owner.close()
    owner.close()
    assert not (workspace / "artifact-adoptions.sqlite").exists()
    assert client.post("/api/v1/backtest/adoptions", json={}).status_code in {401, 403}


def test_normal_factory_keeps_pure_metadata_before_admission_and_model_auth(mounted, monkeypatch):
    from flinttrade_core.request_observability import current_safe_request_summary
    app, client, _store, _calls = mounted
    names = [hook.__name__ for hook in app.before_request_funcs[None]]
    assert names.index('_require_running_runtime') < names.index('guard_model_control')
    tracker = app.config['RUNTIME_REQUEST_TRACKER']
    admit = tracker.try_admit
    summaries = []
    def observed_admission():
        summary = current_safe_request_summary()
        summaries.append(None if summary is None else summary.to_dict())
        return admit()
    monkeypatch.setattr(tracker, 'try_admit', observed_admission)
    response = client.post('/v1/model-runs/private-run/configuration/confirm', json={'private': 'synthetic-context'})
    assert response.status_code == 403
    assert len(summaries) == 1 and summaries[0] is not None
    assert summaries[0]['route_template'] == '/v1/model-runs/{resource}'
    assert 'private-run' not in repr(summaries) and 'synthetic-context' not in repr(summaries)
    assert current_safe_request_summary() is None


@pytest.fixture
def composed(mounted, desk, monkeypatch, tmp_path, request):
    from flinttrade_core.practice_agent_runtime import PracticeAgentSupervisor, shutdown_practice_agent
    from flinttrade_core.auth_routes import VerifiedOperatorSession
    from flinttrade_core import service_connection_routes
    app, client, store, calls = mounted
    for key in ("DATA_SANDBOX_ENGINE", "RATE_LIMITER", "TIME_SCHEDULER", "BACKEND_LEASE_PROOF", "SAFETY"):
        app.config[key] = desk.app.config[key]
    app.config.update(RUNTIME_ACCEPTING_REQUESTS=True, TICK_RECORDER=None)
    principal = VerifiedOperatorSession(desk.owner, "session:" + "b" * 64,
                                       ("admin.services.read", "admin.services.write"))
    monkeypatch.setattr(service_connection_routes, "verify_operator_session_token", lambda _token: principal)
    owner = install(app, store.workspace_dir)
    supervisor = PracticeAgentSupervisor(app, desk.store)
    app.extensions["practice_agent_supervisor"] = supervisor
    request.addfinalizer(lambda: shutdown_practice_agent(app, timeout=5))
    supervisor.start(desk.token(scopes=list(principal.scopes)), desk.owner,
                     {"symbols": ["RELIANCE"], "cycle_interval_sec": 3600}, llm=desk.llm)
    _wait_for(lambda: supervisor.run.snapshot.get("cycle_count", 0) >= 1 and supervisor.run.status == "running")
    assert owner.runs.owner(supervisor.run.run_id).supervisor is supervisor, "normal start must attach its existing owner"
    token = desk.token(scopes=list(principal.scopes))
    yield owner, supervisor, app, client, store, calls, {"Authorization": "Bearer " + token}, desk
    shutdown_practice_agent(app, timeout=5)
    owner.close()
    for key in ("LEARNING_CONSENT_LEDGER", "KNOWLEDGE_RUNTIME"):
        dependency = app.config.get(key)
        if dependency is not None:
            dependency.close()


def qualify(composed, *, lifetime=3600, training_job=None):
    from flinttrade_core.evaluation import EvaluationStore
    owner, supervisor, app, client, store, calls, headers, desk = composed
    connection = create(client)
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    value = policy(revision)
    value["privacy"]["classifications"] = ["public", "private"]
    configure(client, connection, value)
    selection = {"connection_id": connection, "connection_revision": revision,
                 "model": "test-model-v1", "effort": "balanced"}
    evidence = EvaluationStore(store.workspace_dir / "evaluation.sqlite", graders={"independent-synthetic": lambda *_: {"accuracy": 1.0}})
    app.config["EVALUATION_STORE"] = evidence
    manifest = {"schema_version": 1, "data": "synthetic-heldout-data", "model": selection, "skill": "fixed-skill",
                "strategy": "fixed-strategy", "config": "fixed-config", "evaluator": "independent-synthetic",
                "producer": "synthetic-trainer", "role": "reasoning", "training_job": training_job}
    trial = evidence.begin(evidence.create(manifest))
    evidence.freeze("synthetic-suite", {name: [{"id": name, "group": name, "as_of": n, "label_end": n}]
                    for n, name in enumerate(("development", "calibration", "final"))},
                    evaluator="independent-synthetic", policy={"thresholds": {"accuracy": {"min": .9}}, "budgets": {"max_trials": 1}})
    evidence.score_final("synthetic-suite", trial, prospective={"candidate": manifest, "receipt": "synthetic-prospective"})
    owner.configure_candidate(trial, selection=selection, role="reasoning", identity_scope="provider-reported-revision",
                              valid_until=NOW.timestamp() + lifetime, deadline_ms=2000, max_output_tokens=256,
                              readiness_ttl_seconds=60)
    run_id = supervisor.run.run_id
    state = owner.runs.snapshot(run_id, "reasoning")
    owner.configure_grant(run_id, "reasoning", actor=desk.owner, expected_revision=0,
                          valid_until=NOW.timestamp() + 3600, risk_fingerprint=state.risk_fingerprint,
                          identity_scope="provider-reported-revision", evidence="synthetic-run-authorisation")
    owner.configure_access(run_id, actor=desk.owner, operations=["adoption.adopt", "adoption.get", "adoption.reconcile"],
                           valid_until=NOW.timestamp() + 3600, evidence="synthetic-control-authorisation", expected_revision=0)
    return trial, run_id


def test_qualified_http_adoption_changes_real_run_and_real_serving(composed):
    owner, supervisor, app, client, store, calls, headers, desk = composed
    trial, run_id = qualify(composed)
    response = client.post("/api/v1/backtest/adoptions", headers=headers,
                           json={"request_id": "adopt-one", "run_id": run_id, "role": "reasoning",
                                 "candidate": trial, "expected_generation": 0})
    assert response.status_code == 202, response.json
    assert response.json["data"]["status"] == "completed", response.json
    assert owner.runs.snapshot(run_id, "reasoning").binding == trial
    assert len(calls) == 1, "stage uses actual identity-checked provider protocol"
    assert owner.serving.current(run_id, "reasoning") == owner.qualification(trial)["identity"]
    assert client.get("/api/v1/backtest/adoptions/adopt-one", headers=headers).status_code == 200
    generic = client.get("/api/v1/backtest/adoptions/adopt-one", headers={"X-API-Key": "synthetic-key"})
    assert generic.status_code in {401, 403}
    from flinttrade_core.practice_agent_runtime import _ObservedLLM
    from flinttrade_ai.llm_client import LLMMessage
    observed = _ObservedLLM(supervisor, supervisor.run, desk.llm)
    result = observed.chat([LLMMessage(role="user", content="Synthetic analysis")])
    assert result.content == "Explained without trading."
    assert len(calls) == 2, "actual run consumer must use the adopted provider, not legacy client"


def test_sealed_evaluation_requires_exact_actor_run_and_separate_score_permission(composed):
    from flinttrade_core.evaluation import EvaluationStore
    owner, supervisor, app, client, store, calls, headers, desk = composed
    evidence = EvaluationStore(store.workspace_dir / "sealed.sqlite", graders={"judge": lambda *_: {"score": 1}})
    app.config["EVALUATION_STORE"] = evidence
    manifest = {"schema_version": 1, "data": "synthetic", "model": "synthetic", "skill": "fixed",
                "strategy": "fixed", "config": "fixed", "producer": "trainer", "evaluator": "judge", "role": "reasoning",
                "control_scope": {"actor": desk.owner, "run_id": supervisor.run.run_id,
                                  "account": "paper:sandbox", "environment": "paper"}}
    trial = evidence.begin(evidence.create(manifest))
    evidence.freeze("sealed", {name: [{"id": name, "group": name, "as_of": n}] for n, name in enumerate(
        ("development", "calibration", "final"))}, evaluator="judge",
        policy={"thresholds": {"score": {"min": 1}}, "budgets": {"max_trials": 1}})
    app.config["EVALUATION_PROSPECTIVE_RESOLVER"] = lambda _trial: {"candidate": manifest, "receipt": "synthetic"}
    url = "/api/v1/backtest/evaluation/suites/sealed/score"
    denied = client.post(url, headers={"X-API-Key": "synthetic-key"}, json={"trial_id": trial})
    assert denied.status_code in {401, 403}, denied.json
    assert evidence.suite("sealed")["consumed_by"] is None
    assert client.post(url, headers=headers, json={"trial_id": trial}).status_code == 403
    owner.configure_access(supervisor.run.run_id, actor=desk.owner,
                           operations=["evaluation.score", "evaluation.read"], valid_until=NOW.timestamp() + 3600,
                           evidence="synthetic-evaluation-permission", expected_revision=0)
    owner.configure_evaluation(trial, suite="sealed")
    def revoked_during_prospective(_trial):
        owner.configure_access(supervisor.run.run_id, actor=desk.owner, operations=[],
                               valid_until=NOW.timestamp() + 3600, evidence="synthetic-revocation", expected_revision=1)
        return {"candidate": manifest, "receipt": "synthetic"}
    app.config["EVALUATION_PROSPECTIVE_RESOLVER"] = revoked_during_prospective
    refused = client.post(url, headers=headers, json={"trial_id": trial})
    assert refused.status_code in {403, 422}, refused.json
    assert evidence.suite("sealed")["consumed_by"] is None
    owner.configure_access(supervisor.run.run_id, actor=desk.owner, operations=["evaluation.score", "evaluation.read"],
                           valid_until=NOW.timestamp() + 3600, evidence="synthetic-renewed-control", expected_revision=2)
    app.config["EVALUATION_PROSPECTIVE_RESOLVER"] = lambda _trial: {"candidate": manifest, "receipt": "synthetic"}
    scored = client.post(url, headers=headers, json={"trial_id": trial})
    assert scored.status_code == 200, scored.json
    assert evidence.suite("sealed")["consumed_by"] == trial
    assert client.get("/api/v1/backtest/trials/" + trial, headers=headers).status_code == 200
    other = {"Authorization": "Bearer " + desk.token(sub="other", scopes=["admin.services.read", "admin.services.write"])}
    assert client.get("/api/v1/backtest/trials/" + trial, headers=other).status_code == 403


def test_managed_model_outage_keeps_deterministic_protector_without_liquidation(composed):
    import httpx
    from flinttrade_ai.llm_client import LLMMessage
    from flinttrade_core.practice_agent_runtime import _ObservedLLM
    owner, supervisor, app, client, store, calls, headers, desk = composed
    trial, run_id = qualify(composed)
    assert owner._engine().adopt("activate", run_id=run_id, role="reasoning", candidate=trial,
                                expected_generation=0)["status"] == "completed"
    owner.dispatcher().transport = httpx.MockTransport(lambda _request: httpx.Response(503))
    observed = _ObservedLLM(supervisor, supervisor.run, desk.llm)
    with pytest.raises(RuntimeError, match="configured_model_unavailable"):
        observed.chat([LLMMessage(role="user", content="Synthetic model outage")])
    assert not supervisor.run.stop.is_set(), "provider outage must not trigger blanket liquidation"
    assert not supervisor.run.trader._stop_requested
    assert owner.runs.snapshot(run_id, "reasoning").protection_verified
    assert not owner.runs.snapshot(run_id, "reasoning").entries_armed


@pytest.mark.parametrize("change", ["revoke", "expire", "risk", "fill", "access"])
def test_change_during_real_stage_refuses_commit_without_rewinding(composed, change, monkeypatch):
    owner, supervisor, app, client, store, calls, headers, desk = composed
    trial, run_id = qualify(composed)
    stage = owner.serving.stage
    mutations = []
    def mutate(candidate, state):
        handle = stage(candidate, state)
        if change == "revoke":
            owner.revoke_grant(run_id, "reasoning", actor=desk.owner, expected_revision=1)
        elif change == "expire":
            from datetime import timedelta
            app.config["SERVICE_TASK_DISPATCHER"].clock = lambda: NOW + timedelta(hours=2)
        elif change == "risk":
            desk.sandbox.update_config(equity_leverage=2)
        elif change == "fill":
            desk.sandbox.place_order(symbol="RELIANCE", exchange="NSE", product="MIS", action="BUY", quantity=1,
                                     price=123.5, order_type="MARKET")
        else:
            owner.configure_access(run_id, actor=desk.owner, operations=[], valid_until=NOW.timestamp() + 3600,
                                   evidence="synthetic-revocation", expected_revision=1)
        mutations.append(change)
        return handle
    monkeypatch.setattr(owner.serving, "stage", mutate)
    result = owner._engine().adopt("changed", run_id=run_id, role="reasoning", candidate=trial, expected_generation=0)
    assert mutations == [change], result
    assert result["status"] == "refused", result
    assert owner.runs.snapshot(run_id, "reasoning").binding == "unqualified-legacy"
    if change == "fill":
        assert len(desk.sandbox.get_trades()) == 1


def test_concurrent_adoption_and_unknown_commit_reconcile_no_replay(composed, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    owner, supervisor, app, client, store, calls, headers, desk = composed
    trial, run_id = qualify(composed)
    barrier = Barrier(2)
    stage = owner.serving.stage
    def staged(candidate, state):
        handle = stage(candidate, state)
        barrier.wait(timeout=5)
        return handle
    monkeypatch.setattr(owner.serving, "stage", staged)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda identity: owner._engine().adopt(identity, run_id=run_id, role="reasoning",
                            candidate=trial, expected_generation=0), ("first", "second")))
    assert sorted(result["status"] for result in results) == ["completed", "refused"]
    assert owner.runs.snapshot(run_id, "reasoning").generation == 1
    monkeypatch.setattr(owner.serving, "stage", stage)
    commit = owner.serving.commit
    def lost_ack(*args):
        commit(*args)
        raise RuntimeError("synthetic acknowledgement lost")
    monkeypatch.setattr(owner.serving, "commit", lost_ack)
    unknown = owner._engine().adopt("lost", run_id=run_id, role="reasoning", candidate=trial, expected_generation=1)
    assert unknown["status"] == "unknown"
    count = len(calls)
    resolved = owner._engine().reconcile("lost")
    assert resolved["status"] == "completed"
    assert not owner.runs.snapshot(run_id, "reasoning").entries_armed
    assert len(calls) == count
    assert owner._engine().adopt("lost", run_id=run_id, role="reasoning", candidate=trial, expected_generation=1) == resolved


@pytest.mark.parametrize("raw", ['[]', 'null', '{', '{"request_id":"a","request_id":"b"}', '{"expected_generation":true}'])
def test_model_control_rejects_malformed_payload_before_io(composed, raw):
    owner, supervisor, app, client, store, calls, headers, desk = composed
    response = client.post("/api/v1/backtest/adoptions", headers=headers, data=raw, content_type="application/json")
    assert response.status_code == 400
    assert not calls
    assert not (store.workspace_dir / "artifact-adoptions.sqlite").exists()


def test_failed_stage_and_qualified_rollback_preserve_actual_execution_state(composed):
    import asyncio
    import httpx
    owner, supervisor, app, client, store, calls, headers, desk = composed
    trial, run_id = qualify(composed)
    engine = owner._engine()
    assert engine.adopt("first", run_id=run_id, role="reasoning", candidate=trial, expected_generation=0)["status"] == "completed"
    supervisor.run.adapter.record_model_proposal(1, trial)
    fill = asyncio.run(supervisor.run.adapter.place_order(symbol="RELIANCE", exchange="NSE", product="MIS", action="BUY", quantity=1))
    assert fill["status"] == "COMPLETE", fill
    books = (desk.sandbox.get_all_orders(), desk.sandbox.get_trades(), desk.sandbox.get_pnl())
    transport = owner.dispatcher().transport
    owner.dispatcher().transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"model": "unknown"}))
    failed = engine.adopt("load-failed", run_id=run_id, role="reasoning", candidate=trial, expected_generation=1)
    assert failed["status"] == "refused"
    assert owner.runs.snapshot(run_id, "reasoning").generation == 1
    owner.dispatcher().transport = transport
    assert engine.adopt("retain", run_id=run_id, role="reasoning", candidate=trial, expected_generation=1)["status"] == "completed"
    rolled = engine.adopt("rollback", run_id=run_id, role="reasoning", candidate=trial, expected_generation=2, kind="rollback")
    assert rolled["status"] == "completed", rolled
    assert (desk.sandbox.get_all_orders(), desk.sandbox.get_trades(), desk.sandbox.get_pnl()) == books
    admitted = [event for event in desk.store.events(run_id) if event["kind"] == "model_proposal_admitted"]
    assert admitted[0]["data"]["generation"] == 1
    assert owner.runs.snapshot(run_id, "reasoning").generation == 3


def test_provider_entitlement_expiry_invalidates_longer_candidate_qualification(composed):
    from datetime import timedelta
    owner, supervisor, app, client, store, calls, headers, desk = composed
    trial, _ = qualify(composed, lifetime=7200)
    owner.dispatcher().clock = lambda: NOW + timedelta(minutes=61)
    with pytest.raises(ValueError, match="entitlement"):
        owner.qualification(trial)


def test_control_origin_is_exact_not_any_loopback_port(composed):
    owner, supervisor, app, client, store, calls, headers, desk = composed
    response = client.post("/api/v1/backtest/adoptions", headers={**headers, "Origin": "http://127.0.0.1:9999"}, json={})
    assert response.status_code == 403
    assert not calls


def test_paper_authority_never_inherits_live_ui_account_or_other_role(composed):
    from dataclasses import FrozenInstanceError
    from flinttrade_core.execution_session import ExecutionSession
    owner, supervisor, app, client, store, calls, headers, desk = composed
    trial, run_id = qualify(composed)
    live = ExecutionSession("synthetic-live-run", desk.owner, "native:synthetic:other-account", "live")
    app.config.update(ACTIVE_ACCOUNT=live.account, MODE=live.environment)
    with pytest.raises(FrozenInstanceError):
        live.environment = "paper"
    paper = owner.runs.scope(run_id)
    assert (paper.account, paper.environment) == ("paper:sandbox", "paper")
    for target_run, role in ((live.run_id, "reasoning"), (run_id, "admission")):
        refused = client.post("/api/v1/backtest/adoptions", headers=headers,
                              json={"request_id": "cross-scope", "run_id": target_run, "role": role,
                                    "candidate": trial, "expected_generation": 0})
        assert refused.status_code in {400, 403}, refused.json
    assert not calls
    assert owner.runs.snapshot(run_id, "reasoning").generation == 0


def test_training_job_label_alone_cannot_attest_served_artifact_provenance(composed):
    with pytest.raises(ValueError, match="Training artifact provenance"):
        qualify(composed, training_job="unknown-or-unexported-job")
    assert not composed[5]


def test_maintenance_snapshot_never_equates_missing_ui_session_with_safe_disposal(composed):
    owner, supervisor, app, client, store, calls, headers, desk = composed
    before = owner.maintenance_snapshot()
    assert before["disposal_authorised"] is False
    row = before["runs"][0]
    assert row["run_id"] == supervisor.run.run_id and row["worker_alive"] is True
    desk.revoked.add("practice-session")
    after = owner.maintenance_snapshot()
    assert after["disposal_authorised"] is False
    assert after["protection_lifetime"] == "independent-grant-unqualified"
    assert not calls
