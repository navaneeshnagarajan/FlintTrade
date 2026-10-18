"""Exact configuration HTTP reads use real normal-factory durable owners."""
from __future__ import annotations

import hashlib

import pytest

from packages.core.core.tests.test_run_adoption_integration import composed as composed
from packages.core.core.tests.test_run_adoption_integration import desk as desk, mounted as mounted
from packages.core.core.tests.test_run_learning_remote import action
from packages.core.core.tests.test_service_tasks import BASE, HEADERS, NOW, configure, create, policy

pytestmark = pytest.mark.integration


def evaluation_value(composed, category):
    owner, supervisor, app, client, _store, _calls, headers, _desk = composed
    selection = selection_for(composed)
    evidence = app.config["EVALUATION_STORE"]
    evidence._graders["synthetic-independent"] = lambda *_: {"score": 1}
    manifest = {"schema_version": 1, "model": selection, "data": "synthetic", "skill": "synthetic",
                "strategy": "synthetic", "config": "synthetic", "producer": "synthetic-producer",
                "evaluator": "synthetic-independent", "role": "reasoning",
                "control_scope": vars(owner.runs.scope(supervisor.run.run_id))}
    trial = evidence.begin(evidence.create(manifest))
    evidence.freeze("sealed-config", {name: [{"id": name, "group": name, "as_of": n}]
                    for n, name in enumerate(("development", "calibration", "final"))},
                    evaluator="synthetic-independent", policy={"thresholds": {"score": {"min": 1}},
                                                               "budgets": {"max_trials": 1}})
    if category == "evaluation":
        return {"trial": trial, "suite": "sealed-config"}
    action(client, headers, url_for(composed), "access", {"operations": ["evaluation.score"],
        "valid_until": NOW.timestamp() + 3600, "evidence": "synthetic-evaluation-only"})
    action(client, headers, url_for(composed), "evaluation", {"trial": trial, "suite": "sealed-config"})
    app.config["EVALUATION_PROSPECTIVE_RESOLVER"] = lambda _: {"candidate": manifest, "receipt": "synthetic-prospective"}
    scored = client.post("/api/v1/backtest/evaluation/suites/sealed-config/score", headers=headers, json={"trial_id": trial})
    assert scored.status_code == 200, scored.json
    return {"candidate": trial, "selection": selection, "role": "reasoning", "identity_scope": "provider-reported-revision",
            "valid_until": NOW.timestamp() + 3600, "deadline_ms": 2000, "max_output_tokens": 256,
            "readiness_ttl_seconds": 60}


@pytest.mark.parametrize("category", ["evaluation", "candidate"])
def test_exact_immutable_read_pins_owned_trial_and_does_not_grade_or_activate(composed, category):
    owner, supervisor, app, client, _store, calls, headers, desk = composed
    value = evaluation_value(composed, category)
    selector = {"action": category, "trial": value.get("trial", value.get("candidate"))}
    if category == "evaluation":
        selector["suite"] = value["suite"]
    url = url_for(composed)
    before = client.get(url + "/control", headers=headers, query_string=selector)
    assert before.status_code == 200, before.json
    assert before.json["exact_control"]["revision"] == 0
    assert before.json["exact_control"]["value"] is None
    evidence = app.config["EVALUATION_STORE"]
    trial_before = evidence.trial(selector["trial"])
    suite_before = evidence.suite("sealed-config")
    configured = action(client, headers, url, category, value)
    events = desk.store.events(supervisor.run.run_id)
    after = client.get(url + "/control", headers=headers, query_string=selector)
    assert after.status_code == 200, after.json
    exact = after.json["exact_control"]
    assert exact == configured["exact_control"]
    assert exact["revision"] == 1 and exact["selector"] == selector
    assert all(exact["value"][key] == entry for key, entry in value.items())
    assert exact["identity"] == before.json["exact_control"]["identity"]
    assert evidence.trial(selector["trial"]) == trial_before and evidence.suite("sealed-config") == suite_before
    assert desk.store.events(supervisor.run.run_id) == events
    assert not owner.serving.bound and owner._training is None and calls == []


def training_value(composed):
    from uuid import uuid4
    from flinttrade_core.service_usage_contracts import USAGE_DIMENSIONS
    from flinttrade_core.training_jobs import UNSLOTH_PIN
    client = composed[3]
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    created = client.post(BASE, headers={**HEADERS, "If-Match": revision, "Idempotency-Key": str(uuid4())}, json={
        "provider_id": "llm:custom", "label": "Synthetic training", "model": "test-model-v1",
        "endpoint": "http://127.0.0.1:8765", "auth_mode": "api_key", "credential": "synthetic-only"})
    assert created.status_code == 201, created.json
    config = policy(client.get(BASE, headers=HEADERS).headers["ETag"])
    config = {key: config[key] for key in ("connection_revision", "budget", "tariff", "reservation", "quota_group")}
    config["budget"]["limits"] = {key: 100000 for key in USAGE_DIMENSIONS}
    config["tariff"]["provider_id"] = "llm:custom"
    config["reservation"] = {key: 0 for key in USAGE_DIMENSIONS} | {"requests": 1, "concurrency": 1, "bytes": 10000, "currency_micros": 100}
    config.update(version=UNSLOTH_PIN, principal="synthetic-owner", principal_role="owner", region="test-region",
        terms_revision="synthetic-terms", model_revision="test-model-v1", valid_until=NOW.timestamp() + 3600,
        isolation={"dedicated": True, "pool": "synthetic-training-only", "evidence": "synthetic-capacity-evidence"},
        controls={key: "hard-provider" for key in USAGE_DIMENSIONS}, controls_evidence="synthetic-controls", timeout_seconds=2)
    # Explicit trusted setup, not a GET bootstrapping absent usage custody.
    composed[0].dispatcher()
    return {"connection_id": created.json["connection_id"], "policy": config}


def test_exact_training_read_is_connection_scoped_without_endpoint_secret_or_job_creation(composed):
    owner, supervisor, app, client, store, calls, headers, desk = composed
    value = training_value(composed)
    selector = {"action": "training-backend", "connection_id": value["connection_id"]}
    url = url_for(composed)
    before = client.get(url + "/control", headers=headers, query_string=selector)
    assert before.status_code == 200, before.json
    assert before.json["exact_control"]["revision"] == 0 and before.json["exact_control"]["value"] is None
    confirmed = action(client, headers, url, "training-backend", value)
    events = desk.store.events(supervisor.run.run_id)
    after = client.get(url + "/control", headers=headers, query_string=selector)
    assert after.status_code == 200, after.json
    exact = after.json["exact_control"]
    assert exact == confirmed["exact_control"]
    assert exact["revision"] == 1 and exact["value"] == value
    assert exact["identity"] == {"connection_id": value["connection_id"], "connection_revision": value["policy"]["connection_revision"]}
    assert "127.0.0.1" not in after.text and "synthetic-only" not in after.text
    assert desk.store.events(supervisor.run.run_id) == events
    assert not (store.workspace_dir / "training-jobs.sqlite").exists()
    assert owner.runs.control(supervisor.run.run_id, "access") == (0, None)
    assert owner._activation is None and calls == []


def test_preview_pins_sealed_identity_and_refuses_changed_evidence_before_write(composed):
    import json
    owner, _supervisor, app, client, _store, calls, headers, _desk = composed
    value = evaluation_value(composed, "evaluation")
    proposal = {"action": "evaluation", "expected_revision": 0, "value": value}
    url = url_for(composed)
    preview = client.post(url + "/preview", headers=headers, json=proposal)
    assert preview.status_code == 200
    store = app.config["EVALUATION_STORE"]
    with store._db() as db:
        raw = json.loads(db.execute("SELECT payload FROM suites WHERE id=?", (value["suite"],)).fetchone()[0])
        raw["policy"]["thresholds"]["score"]["min"] = 0
        db.execute("UPDATE suites SET payload=? WHERE id=?", (json.dumps(raw), value["suite"]))
    confirmed = client.post(url + "/confirm", headers=headers, json={**proposal, "confirmation": preview.json["confirmation"]})
    assert confirmed.status_code == 409, confirmed.json
    assert owner.dispatcher().ledger.control("run-evaluation:" + value["trial"]) == (0, None)
    assert calls == []


def test_candidate_preview_pins_reported_serving_identity_before_configuration(composed):
    owner, _supervisor, _app, client, _store, calls, headers, _desk = composed
    value = evaluation_value(composed, "candidate")
    proposal = {"action": "candidate", "expected_revision": 0, "value": value}
    url = url_for(composed)
    preview = client.post(url + "/preview", headers=headers, json=proposal)
    assert preview.status_code == 200
    key = "admission:" + value["selection"]["connection_id"]
    revision, policy_value = owner.dispatcher().ledger.control(key)
    owner.dispatcher().ledger.configure_control(key, {**policy_value, "qualification": "replacement-synthetic-evidence"}, expected_revision=revision)
    confirmed = client.post(url + "/confirm", headers=headers, json={**proposal, "confirmation": preview.json["confirmation"]})
    assert confirmed.status_code == 409, confirmed.json
    assert owner.dispatcher().ledger.control("run-candidate:" + value["candidate"]) == (0, None)
    assert calls == []


def url_for(composed):
    return f"/v1/model-runs/{composed[1].run.run_id}/configuration"


def selection_for(composed):
    client = composed[3]
    connection = create(client)
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    configure(client, connection, policy(revision))
    return {"connection_id": connection, "connection_revision": revision,
            "model": "test-model-v1", "effort": "balanced"}


def rights_value(composed, subject):
    from flinttrade_core.run_learning import FIELDS
    from flinttrade_core.service_providers import LicenceFact, RightsBasis, RightsGrant, intersect_rights
    from packages.core.core.tests.test_learning_consent import rights
    selection = selection_for(composed)
    document = 'Synthetic reviewed bytes only: नमस्ते 🚦 "quoted"\\path\n' + subject
    basis = RightsBasis.LICENCE if subject == "source" else RightsBasis.PROVIDER_TERMS
    fact = LicenceFact("synthetic-" + subject, "dataset" if subject == "source" else "provider-output",
        "closed-trades:" + composed[1].run.run_id if subject == "source" else selection["model"],
        "https://example.invalid/synthetic", "synthetic-v1", hashlib.sha256(document.encode()).hexdigest(),
        NOW.isoformat(), basis)
    resolved = intersect_rights(RightsGrant("synthetic-" + subject, basis, rights().rights, (fact,)))
    return {"subject": subject, "selection": selection, "rights": resolved.to_public_dict(),
            "documents": {fact.fact_id: document}, "fields": list(FIELDS),
            "review_statement": "Explicit synthetic review — not entitlement"}


@pytest.mark.parametrize("subject", ["source", "output"])
def test_exact_rights_read_returns_current_revision_and_canonical_event_without_documents(composed, subject):
    owner, supervisor, app, client, _store, calls, headers, desk = composed
    url = url_for(composed)
    selector = {"action": "learning-rights", "subject": subject}
    before = client.get(url + "/control", headers=headers, query_string=selector)
    assert before.status_code == 200, before.json
    assert before.json["exact_control"] == {"selector": selector, "revision": 0, "value": None, "identity": None}
    value = rights_value(composed, subject)
    confirmed = action(client, headers, url, "learning-rights", value)
    events = desk.store.events(supervisor.run.run_id)
    after = client.get(url + "/control", headers=headers, query_string=selector)
    assert after.status_code == 200, after.json
    exact = after.json["exact_control"]
    assert exact == confirmed["exact_control"]
    assert exact["revision"] == 1
    assert exact["identity"] == {key: confirmed["result"][key] for key in ("event_id", "rights_digest")}
    from flinttrade_core.evaluation import digest
    assert exact["value"] == {key: value[key] for key in ("subject", "selection", "fields")} | {
        "rights_digest": digest(value["rights"]),
        "document_digests": {key: hashlib.sha256(text.encode()).hexdigest() for key, text in value["documents"].items()},
        "review_statement_digest": hashlib.sha256(value["review_statement"].encode()).hexdigest()}
    assert after.headers["Cache-Control"] == "no-store"
    assert "documents" not in after.text and value["review_statement"] not in after.text
    assert desk.store.events(supervisor.run.run_id) == events
    assert owner.runs.control(supervisor.run.run_id, "access") == (0, None)
    assert owner._training is None and owner._activation is None and calls == []
