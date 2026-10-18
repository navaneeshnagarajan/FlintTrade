"""Mounted optional-training controls with real shared owners and inert HTTP."""
from __future__ import annotations

import hashlib
import importlib.util
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest

from packages.core.core.tests.test_run_adoption_integration import composed as composed
from packages.core.core.tests.test_service_tasks import BASE, HEADERS, NOW, policy, mounted as mounted
from packages.core.core.tests.test_practice_agent_runtime import desk as desk
from packages.core.core.tests.test_learning_consent import rights

pytestmark = pytest.mark.integration


def prepared(composed):
    assert importlib.util.find_spec("flinttrade_core.training_integration") is not None, "training composition missing"
    from flinttrade_core.knowledge_integration import install_knowledge_runtime, get_learning_consent_ledger
    from flinttrade_core.learning_consent import DatasetScope, DatasetRecord
    from flinttrade_core.service_usage_contracts import USAGE_DIMENSIONS
    from flinttrade_core.evaluation import canonical
    from flinttrade_core.training_jobs import UNSLOTH_PIN
    owner, supervisor, app, client, store, calls, headers, desk = composed
    install_knowledge_runtime(app, store.workspace_dir)
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    created = client.post(BASE, headers={**HEADERS, "If-Match": revision, "Idempotency-Key": str(uuid4())},
                          json={"provider_id": "llm:custom", "label": "Synthetic training", "model": "test-model-v1",
                                "endpoint": "http://127.0.0.1:8765", "auth_mode": "api_key", "credential": "synthetic-only"})
    assert created.status_code == 201, created.json
    connection = created.json["connection_id"]
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    training = owner.training_owner()
    config = policy(revision)
    config = {key: config[key] for key in ("connection_revision", "budget", "tariff", "reservation", "quota_group")}
    config["budget"]["limits"] = {key: 100000 for key in USAGE_DIMENSIONS}
    config["tariff"]["provider_id"] = "llm:custom"
    config["reservation"] = {key: 0 for key in USAGE_DIMENSIONS} | {"requests": 1, "concurrency": 1, "bytes": 10000, "currency_micros": 100}
    config.update(version=UNSLOTH_PIN, principal="synthetic-studio-owner", principal_role="owner", region="test-region",
                  terms_revision="synthetic-terms", model_revision="test-model-v1", valid_until=NOW.timestamp() + 3600,
                  isolation={"dedicated": True, "pool": "synthetic-training-only", "evidence": "synthetic-capacity-proof"},
                  controls={key: "hard-provider" for key in USAGE_DIMENSIONS}, controls_evidence="synthetic-deployment-limits",
                  timeout_seconds=2)
    training.configure_backend(connection, config, expected_revision=0)
    ledger = get_learning_consent_ledger(app)
    assert ledger.usage is owner.dispatcher().ledger
    run_id = supervisor.run.run_id
    scope = DatasetScope("synthetic-dataset", "1", ("paper:sandbox",), ("paper",), (run_id,), ("synthetic",),
                         ("input",), ("development",), "redacted", NOW - timedelta(days=1), NOW + timedelta(days=1))
    version = app.config["KNOWLEDGE_RUNTIME"].store.stock("synthetic", "1", {"synthetic.md": "Synthetic training evidence"}, rights())
    training.register_dataset(scope, actor=desk.owner, rights_versions=[version])
    recipient = training.recipient(connection)
    resolved = app.config["LEARNING_PERMISSION_RESOLVER"](actor=desk.owner, scope=scope, recipient=recipient,
                                                          purpose="fine-tuning", operations=("training.start",))
    assert resolved == (scope, recipient, rights())
    assert app.config["LEARNING_PERMISSION_RESOLVER"](actor="other", scope=scope, recipient=recipient,
                                                      purpose="fine-tuning", operations=("training.start",)) is None
    grant = ledger.grant(scope=scope, recipient=recipient, purpose="fine-tuning", operations=("training.start",),
                         approver=desk.owner, valid_from=NOW, valid_until=NOW + timedelta(hours=1),
                         limits={key: 100000 for key in USAGE_DIMENSIONS}, max_rows=10, max_trials=10,
                         retention="synthetic-retention", derivatives="same-scope", confirmation="synthetic-consent", objective="test")
    version = app.config["KNOWLEDGE_RUNTIME"].store.stock("synthetic", "1", {"synthetic.md": "Synthetic training evidence"}, rights())
    payload = {"model_name": "test-model-v1", "training_type": "lora", "format_type": "chatml", "hf_dataset": "synthetic/remote-dataset"}
    wire = canonical({**payload, "start_request_id": "training-one"}).encode()
    batch = ledger.batch(scope, (DatasetRecord(version, "paper:sandbox", "paper", run_id, "synthetic", NOW,
                         "development", {"input": "Synthetic training evidence"}, rights()),), wire, transform="redacted")
    training.prepare("training-one", actor=desk.owner, run_id=run_id, connection_id=connection, payload=payload,
                     grant_id=grant, batch_id=batch, rights_versions=[version])
    owner.configure_access(run_id, actor=desk.owner, operations=["training.start", "training.get", "training.cancel", "training.reconcile"],
                           valid_until=NOW.timestamp() + 3600, evidence="synthetic-training-control", expected_revision=0)
    def send(request):
        calls.append(request)
        if request.url.path.endswith("status"):
            return httpx.Response(200, json={"job_id": "remote-one", "phase": "training"})
        return httpx.Response(200, json={"job_id": "remote-one", "status": "pending"})
    app.config["MODEL_TRAINING_TRANSPORT"] = httpx.MockTransport(send)
    return payload, run_id, grant, batch, ledger


def test_training_exact_send_and_separate_post_revocation_management(composed):
    owner, supervisor, app, client, store, calls, headers, desk = composed
    payload, run_id, grant, batch, ledger = prepared(composed)
    body = {"request_id": "training-one", "payload": payload, "lineage": {"dataset": batch, "run_id": run_id}}
    response = client.post("/api/v1/backtest/training/jobs", headers=headers, json=body)
    assert response.status_code == 202, response.json
    assert response.json["data"]["state"] == "accepted", response.json
    assert len(calls) == 1
    receipt = ledger.receipt("training:training-one")
    assert receipt["payload_hash"] == hashlib.sha256(calls[0].content).hexdigest()
    assert calls[0].headers["authorization"] == "Bearer synthetic-only"
    ledger.revoke(grant, actor=desk.owner)
    read = client.post("/api/v1/backtest/training/jobs/training-one/reconcile", headers=headers, json={})
    assert read.json["data"]["state"] == "running", read.json
    cancel = client.post("/api/v1/backtest/training/jobs/training-one/cancel", headers=headers, json={})
    assert cancel.json["data"]["cancellation"] == "requested", cancel.json
    assert len(calls) == 3
    assert b'"save":false' in calls[-1].content
    assert client.post("/api/v1/backtest/training/jobs", headers=headers, json=body).json["data"]["remote_job_id"] == "remote-one"
    assert len(calls) == 3, "no start replay after revocation"


@pytest.mark.parametrize("reason", ["revoked", "rights_retired", "payload", "wrong_actor", "inference_only", "expired"])
def test_training_permission_and_scope_refusals_have_zero_sends(composed, reason):
    owner, supervisor, app, client, store, calls, headers, desk = composed
    payload, run_id, grant, batch, ledger = prepared(composed)
    body = {"request_id": "training-one", "payload": dict(payload), "lineage": {"dataset": batch, "run_id": run_id}}
    if reason == "revoked":
        ledger.revoke(grant, actor=desk.owner)
    elif reason == "rights_retired":
        version = ledger.manifest(batch)["members"][0]["record_id"]
        app.config["KNOWLEDGE_RUNTIME"].store.retire(version, reason="synthetic-rights-withdrawn")
    elif reason == "payload":
        body["payload"]["local_datasets"] = ["/home/operator/private.csv"]
    elif reason == "wrong_actor":
        headers = {"Authorization": "Bearer " + desk.token(sub="other", scopes=["admin.services.write"])}
    elif reason == "inference_only":
        owner.configure_access(run_id, actor=desk.owner, operations=["adoption.adopt"], valid_until=NOW.timestamp() + 3600,
                               evidence="synthetic-narrowing", expected_revision=1)
    else:
        owner.dispatcher().clock = lambda: NOW + timedelta(hours=2)
    response = client.post("/api/v1/backtest/training/jobs", headers=headers, json=body)
    assert response.status_code in {400, 403, 202}, response.json
    if response.status_code == 202:
        assert response.json["data"]["state"] == "unknown"
    assert not calls
