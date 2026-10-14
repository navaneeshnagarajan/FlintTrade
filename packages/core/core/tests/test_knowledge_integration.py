"""Real Flask/task/knowledge seams; all external HTTP is inert and explicit."""
from __future__ import annotations

import hashlib
import importlib.util
import json

import pytest

from packages.core.core.tests.test_service_tasks import (
    BASE, HEADERS, configure, create, policy, task,
    mounted as _mounted_fixture,
)

mounted = _mounted_fixture
pytestmark = pytest.mark.integration


def install(app, store):
    assert importlib.util.find_spec("flinttrade_core.knowledge_integration") is not None, "knowledge installer missing"
    from flinttrade_core.knowledge_integration import install_knowledge_runtime
    install_knowledge_runtime(app, store.workspace_dir)


@pytest.fixture
def knowledge(mounted):
    app, client, store, calls = mounted
    install(app, store)
    yield app, client, store, calls
    for key in ("LEARNING_CONSENT_LEDGER", "KNOWLEDGE_RUNTIME"):
        owner = app.config.pop(key, None)
        if owner is not None:
            owner.close()


def test_full_procedure_catalogue_wire_receipt_and_retirement(knowledge):
    app, client, store, calls = knowledge
    catalogue = client.get("/v1/knowledge/skills", headers=HEADERS)
    assert catalogue.status_code == 200, catalogue.get_json()
    assert "risk_management" in [item["name"] for item in catalogue.json["skills"]]
    read = client.get("/v1/knowledge/skills/risk_management", headers=HEADERS)
    assert read.status_code == 200, read.json
    document = read.json
    assert "## Position Sizing" in document["body"]
    assert document["classification"] == "public"
    version = client.get("/v1/knowledge/versions/" + document["version"], headers=HEADERS)
    assert version.status_code == 200
    assert "risk_management.md" in version.json["files"]
    identifier = create(client)
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    admission = policy(revision)
    admission["reservation"].update(input_tokens=8192, currency_micros=1000)
    configure(client, identifier, admission)
    response = client.post(BASE + "/tasks", headers=HEADERS,
                           json=task(identifier, revision, context_refs=["skill:risk_management"]))
    assert response.status_code == 200, response.json
    assert response.json["outcome"] == "completed", response.json
    assert len(calls) == 1
    wire = json.loads(calls[0].content)
    assert document["body"] in wire["messages"][-1]["content"]
    assert response.json["context"][0]["version"] == document["version"]
    from flinttrade_core.service_usage_contracts import canonical
    assert response.json["context"][0]["body_digest"] == hashlib.sha256(canonical(document["body"]).encode()).hexdigest()
    influence = app.config["KNOWLEDGE_RUNTIME"].ledger.get_event(document["receipt"]).payload
    assert influence["context_hash"] == hashlib.sha256(document["body"].encode()).hexdigest()
    retired = client.post("/v1/knowledge/versions/" + document["version"] + "/retire",
                          headers=HEADERS, json={"reason": "Synthetic retirement"})
    assert retired.status_code == 200, retired.json
    refused = client.post(BASE + "/tasks", headers=HEADERS,
                          json=task(identifier, revision, context_refs=["skill:risk_management"]))
    assert refused.json["outcome"] == "refused"
    assert len(calls) == 1
    assert client.get("/v1/knowledge/versions/" + document["version"], headers=HEADERS).status_code == 200
    assert read.headers["Cache-Control"] == "no-store"


def test_scoped_recall_and_adaptation_upgrade_privacy_and_recheck_authority(knowledge, monkeypatch):
    from flinttrade_ai.knowledge_store import KnowledgeScope
    from packages.core.core.tests.test_learning_consent import rights
    app, client, store, calls = knowledge
    runtime = app.config["KNOWLEDGE_RUNTIME"]
    scope = KnowledgeScope("native:synthetic:account-a", "paper", "backend-run-a")
    actor = "operator:" + "a" * 64
    app.config["KNOWLEDGE_SCOPE_RESOLVER"] = lambda current: scope if current == actor else None
    memory = runtime.memory(scope, rights=rights())
    candidate = memory.propose("Private trading lessons for account A only.", symbol="FIXTURE", source_ref="journal:a")
    validated = memory.validate(candidate, validator="independent-fixture", evidence_ref="test:passed")
    base = runtime.store.resolve("risk_management")
    adapted = runtime.store.adapt(base, {"risk_management.md": "# Private risk procedure\nScoped lesson."},
                                  proposer="fixture-learner", scope=scope, evidence_ids=(validated,))
    runtime.store.validate(adapted, validator="independent-fixture", evidence_ref="test:passed")
    runtime.store.promote(adapted, expected=None)
    refs = ["memory:" + validated, "skill:risk_management"]
    identifier = create(client)
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    admission = policy(revision)
    admission["reservation"].update(input_tokens=8192, currency_micros=1000)
    configure(client, identifier, admission)
    denied = client.post(BASE + "/tasks", headers=HEADERS, json=task(identifier, revision, context_refs=refs))
    assert denied.json["code"] == "privacy_denied", denied.json
    assert not calls
    admission["privacy"]["classifications"] = ["public", "private"]
    assert client.put(BASE + f"/{identifier}/admission", headers={**HEADERS, "If-Match": '"1"'},
                      json=admission).status_code == 200
    sent = client.post(BASE + "/tasks", headers=HEADERS, json=task(identifier, revision, context_refs=refs))
    assert sent.json["outcome"] == "completed", sent.json
    assert [item["reference"] for item in sent.json["context"]] == refs
    wire = json.loads(calls[0].content)["messages"][0]["content"]
    assert "Private trading lessons for account A only." in wire and "Scoped lesson." in wire
    assert client.get("/v1/knowledge/versions/" + adapted, headers=HEADERS).status_code == 200
    app.config["KNOWLEDGE_SCOPE_RESOLVER"] = lambda current: None
    assert client.get("/v1/knowledge/versions/" + adapted, headers=HEADERS).status_code == 403
    refused = client.post(BASE + "/tasks", headers=HEADERS, json=task(identifier, revision, context_refs=refs))
    assert refused.json["outcome"] == "refused"
    assert len(calls) == 1


def test_retirement_between_resolution_and_actual_send_refuses(knowledge, monkeypatch):
    app, client, store, calls = knowledge
    runtime = app.config["KNOWLEDGE_RUNTIME"]
    identifier = create(client)
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    admission = policy(revision)
    admission["reservation"].update(input_tokens=8192, currency_micros=1000)
    configure(client, identifier, admission)
    ledger = app.config["SERVICE_TASK_DISPATCHER"].ledger
    original = ledger.prepare
    def retire_before_send(*args, **kwargs):
        result = original(*args, **kwargs)
        runtime.store.retire(runtime.store.resolve("risk_management"), reason="synthetic concurrent retirement")
        return result
    monkeypatch.setattr(ledger, "prepare", retire_before_send)
    response = client.post(BASE + "/tasks", headers=HEADERS,
                           json=task(identifier, revision, context_refs=["skill:risk_management"]))
    assert response.json["outcome"] == "refused"
    assert not calls


def test_private_recall_authority_revoked_at_send_never_leaks(knowledge, monkeypatch):
    from flinttrade_ai.knowledge_store import KnowledgeScope
    from packages.core.core.tests.test_learning_consent import rights
    app, client, store, calls = knowledge
    scope = KnowledgeScope("native:synthetic:account-a", "paper", "run-a")
    app.config["KNOWLEDGE_SCOPE_RESOLVER"] = lambda actor: scope
    memory = app.config["KNOWLEDGE_RUNTIME"].memory(scope, rights=rights())
    candidate = memory.propose("Private scoped lesson", symbol="FIXTURE", source_ref="journal:a")
    record = memory.validate(candidate, validator="independent-fixture", evidence_ref="test:passed")
    identifier = create(client)
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    admission = policy(revision)
    admission["privacy"]["classifications"] = ["private"]
    configure(client, identifier, admission)
    ledger = app.config["SERVICE_TASK_DISPATCHER"].ledger
    original = ledger.prepare
    def revoke_before_send(*args, **kwargs):
        result = original(*args, **kwargs)
        app.config["KNOWLEDGE_SCOPE_RESOLVER"] = lambda actor: None
        return result
    monkeypatch.setattr(ledger, "prepare", revoke_before_send)
    response = client.post(BASE + "/tasks", headers=HEADERS,
                           json=task(identifier, revision, context_refs=["memory:" + record]))
    assert response.json["code"] == "context_scope_required", response.json
    assert not calls
