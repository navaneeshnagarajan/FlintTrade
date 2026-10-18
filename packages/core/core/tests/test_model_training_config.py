"""Confirmed optional backend policy and portable training lineage, no weights claims."""
from __future__ import annotations

from uuid import uuid4

import pytest

from packages.core.core.tests.test_run_adoption_integration import composed as composed
from packages.core.core.tests.test_run_adoption_integration import desk as desk, mounted as mounted
from packages.core.core.tests.test_model_run_config import mount
from packages.core.core.tests.test_run_learning_remote import action
from packages.core.core.tests.test_service_tasks import BASE, HEADERS, NOW, policy

pytestmark = pytest.mark.integration


def test_confirmed_training_backend_configuration_uses_real_connection_owner(composed):
    from flinttrade_core.service_usage_contracts import USAGE_DIMENSIONS
    from flinttrade_core.training_jobs import UNSLOTH_PIN
    owner, supervisor, app, client, store, calls, headers, desk = composed
    mount(app)
    url = f"/v1/model-runs/{supervisor.run.run_id}/configuration"
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    response = client.post(BASE, headers={**HEADERS, "If-Match": revision, "Idempotency-Key": str(uuid4())}, json={
        "provider_id": "llm:custom", "label": "Synthetic training", "model": "test-model-v1",
        "endpoint": "http://127.0.0.1:8765", "auth_mode": "api_key", "credential": "synthetic-only"})
    assert response.status_code == 201, response.json
    connection = response.json["connection_id"]
    config = policy(client.get(BASE, headers=HEADERS).headers["ETag"])
    config = {key: config[key] for key in ("connection_revision", "budget", "tariff", "reservation", "quota_group")}
    config["budget"]["limits"] = {key: 100000 for key in USAGE_DIMENSIONS}
    config["tariff"]["provider_id"] = "llm:custom"
    config["reservation"] = {key: 0 for key in USAGE_DIMENSIONS} | {"requests": 1, "concurrency": 1, "bytes": 10000, "currency_micros": 100}
    config.update(version=UNSLOTH_PIN, principal="synthetic-owner", principal_role="owner", region="test-region",
        terms_revision="synthetic-terms", model_revision="test-model-v1", valid_until=NOW.timestamp() + 3600,
        isolation={"dedicated": True, "pool": "synthetic-training-only", "evidence": "synthetic-capacity-evidence"},
        controls={key: "hard-provider" for key in USAGE_DIMENSIONS}, controls_evidence="synthetic-controls", timeout_seconds=2)
    result = action(client, headers, url, "training-backend", {"connection_id": connection, "policy": config})
    assert result["result"]["revision"] == 1
    assert owner.training_owner()._policy(connection)["version"] == UNSLOTH_PIN
    assert calls == []


def test_completed_training_provenance_is_portable_but_not_served_weight_attestation(composed):
    import httpx
    from packages.core.core.tests.test_training_integration import prepared
    owner, supervisor, app, client, store, calls, headers, desk = composed
    mount(app)
    payload, run_id, grant, batch, ledger = prepared(composed)
    response = client.post("/api/v1/backtest/training/jobs", headers=headers,
        json={"request_id": "training-one", "payload": payload, "lineage": {"run_id": run_id, "dataset": batch}})
    assert response.status_code == 202, response.json
    app.config["MODEL_TRAINING_TRANSPORT"] = httpx.MockTransport(lambda _: httpx.Response(200,
        json={"job_id": "remote-one", "phase": "completed"}))
    assert client.post("/api/v1/backtest/training/jobs/training-one/reconcile", headers=headers, json={}).json["data"]["state"] == "completed"
    response = client.get(f"/v1/model-runs/{run_id}/configuration/training-provenance/training-one", headers=headers)
    assert response.status_code == 200, response.json
    assert response.json["remote_job_id"] == "remote-one"
    assert response.json["dataset"]["payload_hash"] == ledger.manifest(batch)["payload_hash"]
    assert response.json["serving_attestation"] == "unavailable"
    assert response.json["exported_artifact_digest"] is None
    assert response.json["automatic_activation_eligible"] is False
