"""Parent-owned catalogue/reference seams needed by retained learned inputs."""
import pytest

from flinttrade_ai.knowledge_store import KnowledgeScope
from packages.services.ai.tests.test_knowledge_store import rights
from packages.services.ai.tests.test_knowledge_ingest import (
    mounted as _mounted_fixture,
    synthetic_factory_secret as _secret_fixture,
)
from packages.core.core.tests.test_service_tasks import HEADERS

mounted = _mounted_fixture
synthetic_factory_secret = _secret_fixture


@pytest.mark.integration
def test_http_catalogue_and_hyphenated_learned_consumer_share_exact_state(mounted):
    app, client, _workspace_store, _calls = mounted
    runtime = app.config["KNOWLEDGE_RUNTIME"]
    scope = KnowledgeScope("synthetic:a", "paper", "run-a")
    app.config["KNOWLEDGE_SCOPE_RESOLVER"] = lambda actor: scope
    name = "session-lessons-2026-01-01"
    candidate = runtime.store.propose(name, {name + ".md": "Entire learned procedure."},
                                      proposer="synthetic", source_ref="synthetic:input", rights=rights(), scope=scope)

    def row():
        response = client.get("/v1/knowledge/skills", headers=HEADERS)
        assert response.status_code == 200
        matching = [item for item in response.json["skills"] if item["name"] == name]
        assert len(matching) == 1, "HTTP catalogue must use authorised scoped immutable catalogue"
        return matching[0]

    assert row()["state"] == "candidate" and row()["enabled"] is False
    runtime.store.validate(candidate, validator="independent", evidence_ref="synthetic:suite")
    assert row()["state"] == "validated" and row()["enabled"] is False
    runtime.store.promote(candidate, expected=None)
    assert row()["state"] == "default" and row()["enabled"] is True
    read = client.get("/v1/knowledge/skills/" + name, headers=HEADERS)
    assert read.status_code == 200, read.json
    assert read.json["version"] == row()["version_id"] == candidate
    assert "Entire learned procedure." in read.json["body"]
    assert row()["run_pinned"] is True
    runtime.store.retire(candidate, reason="synthetic obsolete")
    assert row()["state"] == "retired" and row()["enabled"] is False
    assert client.get("/v1/knowledge/skills/" + name, headers=HEADERS).status_code == 422
    app.config["KNOWLEDGE_SCOPE_RESOLVER"] = lambda actor: None
    assert not any(item["name"] == name for item in client.get("/v1/knowledge/skills", headers=HEADERS).json["skills"])
