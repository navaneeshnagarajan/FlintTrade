"""Authoritative knowledge envelopes through the normal factory and real JWT guard."""
from __future__ import annotations

from dataclasses import asdict
from unittest.mock import MagicMock

import pytest

from flinttrade_ai.knowledge_store import KnowledgeScope
from flinttrade_core.app import create_flask_app
from flinttrade_core.auth_routes import _create_token

pytestmark = pytest.mark.integration
SCOPE = KnowledgeScope("native:synthetic:account-a", "paper", "server-run-a")


@pytest.fixture
def installed(tmp_path, monkeypatch):
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path / "workspace"))
    from packages.core.core.tests.test_service_tasks import Audit
    app = create_flask_app(safety=MagicMock(order_reservations_durable=True), audit=Audit(),
                           contract_manager=MagicMock())
    app.config["TESTING"] = True
    with app.app_context():
        headers = {"Authorization": "Bearer " + _create_token("synthetic-knowledge", mode="practice")}
    yield app, app.test_client(), headers
    for key in ("MODEL_RUN_SERVICES", "DATA_RUNTIME", "LEARNING_CONSENT_LEDGER", "KNOWLEDGE_RUNTIME",
                "SERVICE_TASK_DISPATCHER"):
        owner = app.config.pop(key, None)
        if owner is not None:
            owner.close()


@pytest.mark.parametrize("scope", [SCOPE, None])
def test_catalogue_exposes_same_authoritative_nullable_scope(installed, monkeypatch, scope):
    app, client, headers = installed
    app.config["KNOWLEDGE_SCOPE_RESOLVER"] = lambda actor: scope
    runtime = app.config["KNOWLEDGE_RUNTIME"]
    original = runtime.skills
    observed = []

    def skills(value):
        observed.append(value)
        return original(value)

    monkeypatch.setattr(runtime, "skills", skills)
    response = client.get("/v1/knowledge/skills?run_id=client-run", headers={
        **headers, "X-Account-Id": "client-account", "X-Run-Id": "client-run"})
    assert response.status_code == 200, response.json
    assert response.json["scope"] == (asdict(scope) if scope is not None else None)
    assert observed == [scope]
    assert response.json["skills"]
    assert client.get("/v1/knowledge/skills").status_code in {401, 403}


def test_canonical_stock_export_separates_release_label_from_ledger_identity(installed):
    _app, client, headers = installed
    catalogue = client.get("/v1/knowledge/skills", headers=headers).json
    stock = next(row for row in catalogue["skills"] if row["name"] == "risk_management")
    response = client.get("/v1/knowledge/versions/" + stock["version_id"], headers=headers)
    assert response.status_code == 200, response.json
    assert response.json["version_id"] == stock["version_id"]
    assert response.json["version"] != response.json["version_id"]
    assert response.json["package_hash"] == stock["package_hash"]
    assert response.json["context_scope"] is None


def test_full_body_discloses_scope_from_exact_influence_receipt(installed):
    app, client, headers = installed
    app.config["KNOWLEDGE_SCOPE_RESOLVER"] = lambda actor: SCOPE
    response = client.get("/v1/knowledge/skills/risk_management", headers=headers)
    assert response.status_code == 200, response.json
    receipt = app.config["KNOWLEDGE_RUNTIME"].ledger.get_event(response.json["receipt"]).payload
    assert response.json["scope"] == receipt["scope"] == asdict(SCOPE)
    assert "## Position Sizing" in response.json["body"]


@pytest.mark.parametrize("resource", ["skills/risk_management", "version"])
def test_changed_server_scope_during_version_read_refuses_whole_response(installed, monkeypatch, resource):
    app, client, headers = installed
    app.config["KNOWLEDGE_SCOPE_RESOLVER"] = lambda actor: SCOPE
    runtime = app.config["KNOWLEDGE_RUNTIME"]
    identifier = runtime.store.resolve("risk_management")
    original = runtime.store.version

    def change_during_read(version):
        value = original(version)
        app.config["KNOWLEDGE_SCOPE_RESOLVER"] = lambda actor: KnowledgeScope(SCOPE.account_id, "paper", "server-run-b")
        return value

    monkeypatch.setattr(runtime.store, "version", change_during_read)
    path = "versions/" + identifier if resource == "version" else resource
    response = client.get("/v1/knowledge/" + path, headers=headers)
    assert response.status_code == 409, response.json
    assert response.json == {"error": "context_changed"}


@pytest.mark.parametrize("resource", ["skill", "export"])
def test_http_response_refuses_scope_change_after_final_evidence_read(installed, monkeypatch, resource):
    app, client, headers = installed
    app.config["KNOWLEDGE_SCOPE_RESOLVER"] = lambda actor: SCOPE
    resolver = app.config["SERVICE_TASK_CONTEXT_RESOLVER"]
    identifier = app.config["KNOWLEDGE_RUNTIME"].store.resolve("risk_management")
    method = "context_scope" if resource == "skill" else "authorise_version"
    original = getattr(resolver, method)

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        app.config["KNOWLEDGE_SCOPE_RESOLVER"] = lambda actor: None
        return result

    monkeypatch.setattr(resolver, method, changed)
    path = "skills/risk_management" if resource == "skill" else "versions/" + identifier
    response = client.get("/v1/knowledge/" + path, headers=headers)
    assert response.status_code == 409, response.json
    assert response.json == {"error": "context_changed"}


def test_unscoped_private_candidate_is_not_export_or_retirement_authority(installed):
    app, client, headers = installed
    runtime = app.config["KNOWLEDGE_RUNTIME"]
    identifier = runtime.store.propose("private-candidate", {"private-candidate.md": "# Retained private candidate\n"},
                                       proposer="synthetic", source_ref="synthetic:input")
    for scope in (None, SCOPE):
        app.config["KNOWLEDGE_SCOPE_RESOLVER"] = lambda actor, scope=scope: scope
        read = client.get("/v1/knowledge/versions/" + identifier, headers=headers)
        retire = client.post("/v1/knowledge/versions/" + identifier + "/retire", headers=headers,
                             json={"reason": "Synthetic review"})
        assert read.status_code == retire.status_code == 403
        assert read.json == retire.json == {"error": "context_scope_required"}
        retained = next(row for row in runtime.store.catalogue() if row["version_id"] == identifier)
        assert retained["state"] == "candidate"


@pytest.mark.parametrize("change", [True, False])
def test_actual_dispatch_binds_stock_context_to_original_run_receipt(installed, monkeypatch, change):
    import httpx
    from packages.core.core.tests import test_service_tasks as helpers
    app, client, headers = installed
    monkeypatch.setattr(helpers, "HEADERS", headers)
    app.config.update(SERVICE_TASK_CLOCK=lambda: helpers.NOW, KNOWLEDGE_SCOPE_RESOLVER=lambda actor: SCOPE)
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(200, json={"model": "test-model-v1", "provider": "approved-upstream",
                              "choices": [{"message": {"content": "Synthetic advisory"}, "finish_reason": "stop"}],
                              "usage": {"prompt_tokens": 12, "completion_tokens": 5}})

    app.config["SERVICE_TASK_TRANSPORT"] = httpx.MockTransport(transport)
    identifier = helpers.create(client)
    revision = client.get(helpers.BASE, headers=headers).headers["ETag"]
    admission = helpers.policy(revision)
    admission["reservation"].update(input_tokens=8192, currency_micros=1000)
    helpers.configure(client, identifier, admission)
    dispatcher = app.config["SERVICE_TASK_DISPATCHER"]
    # Scope/receipt semantics are independent of CI scheduling latency. The
    # existing injectable deadline clock remains explicit and bounded below.
    dispatcher.monotonic = lambda: 10.0
    ledger = dispatcher.ledger
    original = ledger.prepare

    def prepare(*args, **kwargs):
        result = original(*args, **kwargs)
        if change:
            app.config["KNOWLEDGE_SCOPE_RESOLVER"] = lambda actor: KnowledgeScope(SCOPE.account_id, "paper", "server-run-b")
        return result

    monkeypatch.setattr(ledger, "prepare", prepare)
    response = client.post(helpers.BASE + "/tasks", headers=headers,
                           json=helpers.task(identifier, revision, context_refs=["skill:risk_management"]))
    assert response.status_code == 200, response.json
    assert response.json["outcome"] == ("refused" if change else "completed"), response.json
    assert len(calls) == (0 if change else 1)
    if change:
        assert response.json["code"] == "context_changed"


@pytest.mark.parametrize("elapsed", [1.0, 3.0])
def test_stock_context_deadline_is_enforced_after_evidence_preparation(installed, monkeypatch, elapsed):
    import httpx
    from packages.core.core.tests import test_service_tasks as helpers

    app, client, headers = installed
    monkeypatch.setattr(helpers, "HEADERS", headers)
    app.config.update(SERVICE_TASK_CLOCK=lambda: helpers.NOW, KNOWLEDGE_SCOPE_RESOLVER=lambda actor: SCOPE)
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(200, json={"model": "test-model-v1", "provider": "approved-upstream",
            "choices": [{"message": {"content": "Synthetic advisory"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5}})

    app.config["SERVICE_TASK_TRANSPORT"] = httpx.MockTransport(transport)
    identifier = helpers.create(client)
    revision = client.get(helpers.BASE, headers=headers).headers["ETag"]
    admission = helpers.policy(revision)
    admission["reservation"].update(input_tokens=8192, currency_micros=1000)
    helpers.configure(client, identifier, admission)
    dispatcher = app.config["SERVICE_TASK_DISPATCHER"]
    clock = [10.0]
    dispatcher.monotonic = lambda: clock[0]
    original = dispatcher.ledger.prepare

    def prepare(*args, **kwargs):
        result = original(*args, **kwargs)
        clock[0] += elapsed
        return result

    monkeypatch.setattr(dispatcher.ledger, "prepare", prepare)
    response = client.post(helpers.BASE + "/tasks", headers=headers,
        json=helpers.task(identifier, revision, context_refs=["skill:risk_management"]))
    assert response.status_code == 200, response.json
    assert response.json["outcome"] == ("completed" if elapsed < 2 else "refused"), response.json
    assert len(calls) == (1 if elapsed < 2 else 0)
    if elapsed > 2:
        assert response.json["code"] == "deadline_exceeded"
