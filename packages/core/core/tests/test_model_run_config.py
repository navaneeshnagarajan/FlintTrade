"""Full-session, exact-run, revision/confirmation model policy configuration."""
from __future__ import annotations

import importlib.util

import pytest

from packages.core.core.tests.test_run_adoption_integration import composed as composed
from packages.core.core.tests.test_run_adoption_integration import desk as desk, mounted as mounted
from packages.core.core.tests.test_service_tasks import NOW

pytestmark = pytest.mark.integration


def mount(app):
    if importlib.util.find_spec("flinttrade_core.model_run_config") is not None:
        from flinttrade_core.model_run_config import model_run_config_bp
        if model_run_config_bp.name not in app.blueprints:
            app.register_blueprint(model_run_config_bp)


def test_confirmed_access_configuration_is_usable_read_back_and_one_shot(composed):
    owner, supervisor, app, client, _store, calls, headers, desk = composed
    mount(app)
    url = f"/v1/model-runs/{supervisor.run.run_id}/configuration"
    before = client.get(url, headers=headers)
    assert before.status_code == 200, before.json
    assert before.json["scope"] == vars(owner.runs.scope(supervisor.run.run_id))
    proposal = {"action": "access", "expected_revision": 0, "value": {
        "operations": ["evaluation.read"], "valid_until": NOW.timestamp() + 3600,
        "evidence": "synthetic-operator-policy"}}
    preview = client.post(url + "/preview", headers=headers, json=proposal)
    assert preview.status_code == 200, preview.json
    assert preview.json["policy_provenance"] == "operator-supplied-not-measured-entitlement"
    assert owner.runs.control(supervisor.run.run_id, "access") == (0, None)
    body = {**proposal, "confirmation": preview.json["confirmation"]}
    response = client.post(url + "/confirm", headers=headers, json=body)
    assert response.status_code == 200, response.json
    assert owner.runs.control(supervisor.run.run_id, "access")[0] == 1
    assert client.get(url, headers=headers).json["controls"]["access"]["value"]["actor"] == desk.owner
    assert client.post(url + "/confirm", headers=headers, json=body).status_code == 409
    assert calls == []


def test_configuration_pins_sealed_evaluation_and_qualified_candidate_without_self_grading(composed):
    from flinttrade_core.evaluation import EvaluationStore
    from packages.core.core.tests.test_service_tasks import create, configure, policy, BASE, HEADERS
    from packages.core.core.tests.test_run_learning_remote import action
    owner, supervisor, app, client, store, calls, headers, desk = composed
    mount(app)
    run_id = supervisor.run.run_id
    url = f"/v1/model-runs/{run_id}/configuration"
    connection = create(client)
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    configure(client, connection, policy(revision))
    selection = {"connection_id": connection, "connection_revision": revision,
                 "model": "test-model-v1", "effort": "balanced"}
    evidence = EvaluationStore(store.workspace_dir / "config-evaluation.sqlite",
                               graders={"synthetic-independent": lambda *_: {"score": 1}})
    app.config["EVALUATION_STORE"] = evidence
    manifest = {"schema_version": 1, "model": selection, "data": "synthetic", "skill": "synthetic",
                "strategy": "synthetic", "config": "synthetic", "producer": "synthetic-producer",
                "evaluator": "synthetic-independent", "role": "reasoning",
                "control_scope": vars(owner.runs.scope(run_id))}
    trial = evidence.begin(evidence.create(manifest))
    evidence.freeze("sealed-config", {name: [{"id": name, "group": name, "as_of": n}]
                    for n, name in enumerate(("development", "calibration", "final"))},
                    evaluator="synthetic-independent", policy={"thresholds": {"score": {"min": 1}},
                                                               "budgets": {"max_trials": 1}})
    action(client, headers, url, "access", {"operations": ["evaluation.read", "evaluation.score", "adoption.adopt"],
        "valid_until": NOW.timestamp() + 3600, "evidence": "explicit-synthetic-run-policy"})
    action(client, headers, url, "evaluation", {"trial": trial, "suite": "sealed-config"})
    assert evidence.suite("sealed-config")["consumed_by"] is None
    app.config["EVALUATION_PROSPECTIVE_RESOLVER"] = lambda _: {"candidate": manifest, "receipt": "synthetic-prospective"}
    scored = client.post("/api/v1/backtest/evaluation/suites/sealed-config/score", headers=headers, json={"trial_id": trial})
    assert scored.status_code == 200, scored.json
    candidate = action(client, headers, url, "candidate", {"candidate": trial, "selection": selection,
        "role": "reasoning", "identity_scope": "provider-reported-revision", "valid_until": NOW.timestamp() + 3600,
        "deadline_ms": 2000, "max_output_tokens": 256, "readiness_ttl_seconds": 60})
    assert candidate["result"]["candidate"] == trial
    grant = action(client, headers, url, "grant", {"role": "reasoning", "valid_until": NOW.timestamp() + 3600,
        "identity_scope": "provider-reported-revision", "evidence": "explicit-synthetic-grant"})
    assert grant["controls"]["grant:reasoning"]["value"]["risk_fingerprint"] == owner.runs.snapshot(run_id, "reasoning").risk_fingerprint
    assert calls == [], "configuration is not serving, training or grading"
    action(client, headers, url, "revoke-grant", {"role": "reasoning"}, revision=1)
    assert not owner.runs.snapshot(run_id, "reasoning").entries_armed


@pytest.mark.parametrize("raw", ['null', '[]', '"text"', '{', '{"action":"access","action":"grant"}',
    '{"action":"access","expected_revision":true,"value":{}}'])
def test_malformed_configuration_never_writes_run_control(composed, raw):
    owner, supervisor, app, client, store, calls, headers, desk = composed
    mount(app)
    run_id = supervisor.run.run_id
    before = desk.store.events(run_id)
    response = client.post(f"/v1/model-runs/{run_id}/configuration/preview", headers=headers,
                           data=raw, content_type="application/json")
    assert response.status_code == 400
    assert desk.store.events(run_id) == before
    assert calls == []


@pytest.mark.parametrize("change", ["body", "session", "expiry", "revision", "risk", "actor"])
def test_confirmation_rechecks_original_session_scope_and_revision(composed, change):
    owner, supervisor, app, client, store, calls, headers, desk = composed
    mount(app)
    run_id = supervisor.run.run_id
    url = f"/v1/model-runs/{run_id}/configuration"
    proposal = {"action": "access", "expected_revision": 0, "value": {"operations": [],
        "valid_until": NOW.timestamp() + 3600, "evidence": "explicit-synthetic-policy"}}
    preview = client.post(url + "/preview", headers=headers, json=proposal)
    assert preview.status_code == 200, preview.json
    body = {**proposal, "confirmation": preview.json["confirmation"]}
    if change == "body":
        body["value"]["operations"] = ["adoption.adopt"]
    elif change in {"session", "actor"}:
        headers = {"Authorization": "Bearer " + desk.token(jti="different", sub="other" if change == "actor" else "operator",
            scopes=["admin.services.read", "admin.services.write"])}
    elif change == "expiry":
        owner.configuration().pending[body["confirmation"]] = (0, "expired")
    elif change == "risk":
        desk.sandbox.update_config(equity_leverage=2)
    else:
        owner.configure_access(run_id, actor=desk.owner, expected_revision=0, **proposal["value"])
    before = desk.store.events(run_id)
    assert client.post(url + "/confirm", headers=headers, json=body).status_code in {403, 409}
    assert desk.store.events(run_id) == before
    assert calls == []


def test_configuration_refuses_api_key_foreign_origin_and_forged_scope(composed):
    owner, supervisor, app, client, store, calls, headers, desk = composed
    mount(app)
    url = f"/v1/model-runs/{supervisor.run.run_id}/configuration"
    for bad in ({"X-API-Key": "synthetic-key"}, {**headers, "Origin": "https://foreign.invalid"},
                {**headers, "Sec-Fetch-Site": "cross-site"}):
        assert client.get(url, headers=bad).status_code == 403
    forged = {"action": "access", "expected_revision": 0, "value": {"actor": desk.owner,
        "account": "live:forged", "run_id": supervisor.run.run_id, "operations": [],
        "valid_until": NOW.timestamp() + 3600, "evidence": "synthetic"}}
    assert client.post(url + "/preview", headers=headers, json=forged).status_code == 400
    assert client.get(url.replace(supervisor.run.run_id, "forged"), headers=headers).status_code == 403
