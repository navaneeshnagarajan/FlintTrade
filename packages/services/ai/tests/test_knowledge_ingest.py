"""Retained input → immutable lineage → actual consumer, with synthetic evidence."""
from __future__ import annotations

import hashlib
import json

import pytest

from flinttrade_ai.knowledge_store import KnowledgeScope
from packages.services.ai.tests.test_knowledge_store import rights
from packages.core.core.tests.test_service_tasks import (
    BASE, HEADERS, configure, create, policy, task,
    mounted as _mounted_fixture,
)

mounted = _mounted_fixture
DRAFTS = "/api/v1/ai/skill-drafts"


@pytest.fixture(autouse=True)
def synthetic_factory_secret(monkeypatch):
    from flinttrade_core import app
    monkeypatch.setattr(app, "_MASTER_PASSWORD", "synthetic-r10-test-secret")


@pytest.mark.integration
def test_legacy_approval_preserves_both_files_and_returns_inert_candidate(mounted):
    app, client, workspace_store, calls = mounted
    workspace = workspace_store.workspace_dir
    app.config["BROKER_MGMT_WRITE_GUARD"] = lambda: None
    source = workspace / "skill_drafts" / "session-lessons-2026-07-19.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    draft = b"---\r\nname: session-lessons-2026-07-19\r\nstatus: draft\r\n---\r\nPrivate new procedure.\r\n"
    source.write_bytes(draft)
    incumbent = workspace / "skills" / source.name
    incumbent.parent.mkdir(parents=True, exist_ok=True)
    incumbent.write_bytes(b"An existing local file must not be overwritten.\n")
    response = client.post(DRAFTS + "/session-lessons-2026-07-19/approve", headers={"X-API-Key": "synthetic-key"})
    assert response.status_code == 202, response.get_json()
    result = response.json["data"]
    assert result["state"] == "candidate" and result["enabled"] is False
    assert "approved" not in response.json.get("message", "").lower()
    assert source.read_bytes() == draft
    assert incumbent.read_bytes() == b"An existing local file must not be overwritten.\n"
    runtime = app.config["KNOWLEDGE_RUNTIME"]
    candidate = runtime.store.version(result["version_id"])
    assert candidate["files"][source.name].encode() == draft
    assert candidate["origin"] == "learned"
    assert candidate["scope"] is None
    with pytest.raises(ValueError, match="rights"):
        runtime.store.validate(result["version_id"], validator="synthetic-independent", evidence_ref="test:passed")
    assert "session-lessons-2026-07-19" not in runtime.registry
    assert not calls


def package(workspace, name="learned_procedure", source="skills", body="Full new procedure, last step retained."):
    root = workspace / source
    (root / "references").mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(exist_ok=True)
    files = {
        name + ".md": f"---\nname: {name}\ncategory: safety\ndescription: Independent learned procedure\n"
        f"references: [references/check.md]\nscripts: [scripts/inert.py]\n---\n{body}\n",
        "references/check.md": "Full declared reference, final clause retained.\r\n",
        "scripts/inert.py": "raise RuntimeError('must never execute or become prompt text')\n",
    }
    for member, content in files.items():
        (root / member).write_bytes(content.encode())
    return files


@pytest.mark.integration
def test_new_learned_procedure_automatically_validated_reaches_real_private_http_consumer(mounted, monkeypatch):
    app, client, workspace_store, calls = mounted
    runtime = app.config["KNOWLEDGE_RUNTIME"]
    scope = KnowledgeScope("synthetic:private-a", "paper", "run-a")
    app.config["KNOWLEDGE_SCOPE_RESOLVER"] = lambda actor: scope
    files = package(workspace_store.workspace_dir)
    candidate = runtime.ingest_skill("learned_procedure", source="skills", scope=scope, rights=rights())
    registry = runtime.skills(scope)
    assert "learned_procedure" not in registry
    assert client.get("/v1/knowledge/skills/learned_procedure", headers=HEADERS).status_code == 422
    with pytest.raises(ValueError, match="validated"):
        runtime.store.promote(candidate, expected=None)
    with pytest.raises(ValueError, match="independent"):
        runtime.store.validate(candidate, validator="workspace-input", evidence_ref="model:self-report")
    runtime.store.validate(candidate, validator="synthetic-independent", evidence_ref="synthetic:suite-passed")
    runtime.store.promote(candidate, expected=None)  # no manual queue or legacy approve call
    assert "learned_procedure" in registry
    read = client.get("/v1/knowledge/skills/learned_procedure", headers=HEADERS)
    assert read.status_code == 200, read.json
    assert read.json["classification"] == "private" and read.json["version"] == candidate
    assert "Full new procedure, last step retained." in read.json["body"]
    assert files["references/check.md"] in read.json["body"]
    assert files["scripts/inert.py"] not in read.json["body"]
    receipt = runtime.ledger.get_event(read.json["receipt"]).payload["skills"][0]
    assert receipt["files"]["scripts/inert.py"] == hashlib.sha256(files["scripts/inert.py"].encode()).hexdigest()
    assert receipt["package_hash"] == runtime.store.version(candidate)["package_hash"]
    identifier = create(client)
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    admission = policy(revision)
    configure(client, identifier, admission)
    # This is a lineage/privacy/consumer contract, not a host-speed benchmark.
    # Scope elapsed time to this dispatcher; retain real HTTP/auth and ledgers.
    monkeypatch.setattr(app.config["SERVICE_TASK_DISPATCHER"], "monotonic", lambda: 10.0)
    request = task(identifier, revision, context_refs=["skill:learned_procedure"])
    assert client.post(BASE + "/tasks", headers=HEADERS, json=request).json["code"] == "privacy_denied"
    assert not calls
    admission["privacy"]["classifications"] = ["public", "private"]
    assert client.put(BASE + f"/{identifier}/admission", headers={**HEADERS, "If-Match": '"1"'},
                      json=admission).status_code == 200
    response = client.post(BASE + "/tasks", headers=HEADERS,
                           json=task(identifier, revision, context_refs=["skill:learned_procedure"]))
    assert response.json["outcome"] == "completed", response.json
    assert read.json["body"] in json.loads(calls[0].content)["messages"][0]["content"]
    runtime.store.retire(candidate, reason="synthetic retirement")
    assert "learned_procedure" not in registry
    assert client.get("/v1/knowledge/skills/learned_procedure", headers=HEADERS).status_code == 422
    assert client.get("/v1/knowledge/versions/" + candidate, headers=HEADERS).json["files"] == files
    app.config["KNOWLEDGE_SCOPE_RESOLVER"] = lambda actor: KnowledgeScope("synthetic:private-b", "paper", "run-a")
    assert client.get("/v1/knowledge/versions/" + candidate, headers=HEADERS).status_code == 403
    assert len(calls) == 1


@pytest.mark.integration
def test_private_knowledge_consumer_enforces_real_elapsed_deadline(mounted, monkeypatch):
    import time

    app, client, workspace_store, calls = mounted
    runtime = app.config["KNOWLEDGE_RUNTIME"]
    scope = KnowledgeScope("synthetic:private-a", "paper", "run-a")
    app.config["KNOWLEDGE_SCOPE_RESOLVER"] = lambda actor: scope
    package(workspace_store.workspace_dir)
    candidate = runtime.ingest_skill("learned_procedure", source="skills", scope=scope, rights=rights())
    runtime.store.validate(candidate, validator="synthetic-independent", evidence_ref="synthetic:suite-passed")
    runtime.store.promote(candidate, expected=None)
    identifier = create(client)
    revision = client.get(BASE, headers=HEADERS).headers["ETag"]
    admission = policy(revision)
    admission["privacy"]["classifications"] = ["public", "private"]
    configure(client, identifier, admission)
    owner = app.config["SERVICE_TASK_DISPATCHER"]
    assert owner.monotonic is time.monotonic  # independent of the positive test's clock
    resolve = owner.context_resolver.resolve

    def delayed_resolve(**kwargs):
        contexts = resolve(**kwargs)
        time.sleep(2.05)
        return contexts

    monkeypatch.setattr(owner.context_resolver, "resolve", delayed_resolve)
    request = task(identifier, revision, context_refs=["skill:learned_procedure"])
    assert request["deadline_ms"] == 2000
    response = client.post(BASE + "/tasks", headers=HEADERS, json=request)
    result = response.get_json()
    assert response.status_code == 200
    assert result["outcome"] == "refused" and result["code"] == "deadline_exceeded", result
    assert result["latency_ms"] >= request["deadline_ms"]
    assert "output" not in result
    assert result["context"][0]["version"] == candidate
    assert not calls
    attempt = result["attempts"][0]
    assert attempt["state"] == "CANCELLED"
    assert not any(attempt["charged"].values())
    persisted = client.get(BASE + "/tasks/" + request["request_id"], headers=HEADERS).get_json()
    assert persisted["code"] == "deadline_exceeded"


@pytest.mark.integration
def test_stock_licence_does_not_licence_new_text_or_widen_private_evidence(tmp_path):
    from flinttrade_ai.knowledge_runtime import KnowledgeRuntime
    from flinttrade_core.service_providers import PermissionState, RightsResolution
    runtime = KnowledgeRuntime(tmp_path, stock_rights=rights())
    try:
        scope = KnowledgeScope("synthetic:a", "paper", "run-a")
        other = KnowledgeScope("synthetic:b", "paper", "run-b")
        base = runtime.store.resolve("risk_management")
        files = {"risk_management.md": "New private teacher text, not covered by bundled AGPL."}
        unknown = runtime.store.adapt(base, files, proposer="teacher", scope=scope)
        assert runtime.ledger.get_event(unknown).rights.rights.output_use is PermissionState.UNKNOWN
        with pytest.raises(ValueError, match="rights"):
            runtime.store.validate(unknown, validator="independent", evidence_ref="synthetic:passed")
        memory = runtime.memory(scope, rights=RightsResolution())
        evidence = memory.propose("Unknown teacher rights", symbol="SYNTHETIC", source_ref="synthetic:teacher")
        derived = runtime.store.adapt(base, files, proposer="teacher", scope=scope,
                                      rights=rights(), evidence_ids=(evidence,))
        assert runtime.ledger.get_event(derived).rights.rights.output_use is PermissionState.UNKNOWN
        with pytest.raises(ValueError, match="scope"):
            runtime.store.propose("private_lesson", {"private_lesson.md": "Private procedure"}, proposer="teacher",
                                  source_ref="synthetic:lesson", rights=rights(), scope=other, evidence_ids=(evidence,))
        with pytest.raises(ValueError, match="scope"):
            runtime.store.adapt(base, files, proposer="teacher", scope=other, evidence_ids=(evidence,))
        unscoped = runtime.store.propose("unscoped", {"unscoped.md": "Retained but not globally publishable"},
                                        proposer="teacher", source_ref="synthetic:input", rights=rights())
        with pytest.raises(ValueError, match="scope"):
            runtime.store.validate(unscoped, validator="independent", evidence_ref="synthetic:passed")
    finally:
        runtime.close()


@pytest.mark.integration
def test_retained_workspace_inputs_catalogue_restart_and_retirement_preserve_bytes(tmp_path):
    from flinttrade_ai.knowledge_runtime import KnowledgeRuntime
    old = package(tmp_path, "existing_skill", source="skills")
    package(tmp_path, "old_draft", source="skill_drafts")
    runtime = KnowledgeRuntime(tmp_path, stock_rights=rights())
    rows = [row for row in runtime.registry.catalogue() if row["origin"] == "learned"]
    assert {row["name"] for row in rows} == {"existing_skill", "old_draft"}
    assert all(row["state"] == "candidate" and not row["enabled"] for row in rows)
    identities = {row["name"]: row["version_id"] for row in rows}
    runtime.close()
    runtime = KnowledgeRuntime(tmp_path, stock_rights=rights())
    try:
        assert {row["name"]: row["version_id"] for row in runtime.registry.catalogue()
                if row["origin"] == "learned"} == identities
        runtime.store.retire(identities["existing_skill"], reason="synthetic obsolete input")
        runtime.refresh_inputs()
        retired = next(row for row in runtime.registry.catalogue() if row["version_id"] == identities["existing_skill"])
        assert retired["state"] == "retired" and not retired["enabled"]
        assert runtime.store.version(identities["existing_skill"])["files"] == old
        for name, body in old.items():
            assert (tmp_path / "skills" / name).read_bytes() == body.encode()
        assert "existing_skill" not in runtime.registry.get_system_prompt_section()
    finally:
        runtime.close()


@pytest.mark.integration
def test_rejection_and_redraft_never_delete_or_overwrite_existing_bytes(mounted):
    from types import SimpleNamespace
    from flinttrade_ai.skill_drafts import draft_skill_from_reflection
    app, client, workspace_store, _calls = mounted
    workspace = workspace_store.workspace_dir
    app.config["BROKER_MGMT_WRITE_GUARD"] = lambda: None
    result = SimpleNamespace(recommendations=["First synthetic lesson"])
    first = draft_skill_from_reflection(workspace, result, session_date="2026-01-01", symbols=["SYNTHETIC"])
    original = first.read_bytes()
    result.recommendations = ["Second synthetic lesson"]
    second = draft_skill_from_reflection(workspace, result, session_date="2026-01-01", symbols=["SYNTHETIC"])
    assert first.read_bytes() == original
    assert first != second
    headers = {"X-API-Key": "synthetic-key"}
    response = client.delete(DRAFTS + "/" + first.stem, headers=headers)
    assert response.status_code == 200, response.json
    assert response.json["data"]["state"] == "retired"
    assert first.read_bytes() == original
    repeat = client.post(DRAFTS + "/" + first.stem + "/approve", headers=headers)
    assert repeat.json["data"]["state"] == "retired"
    assert repeat.json["data"]["enabled"] is False


@pytest.mark.unit
@pytest.mark.parametrize("member", ["../private.md", "/private.md", "references/../private.md", "./check.md"])
def test_package_names_cannot_alias_or_escape(member, tmp_path):
    from flinttrade_ai.knowledge_store import KnowledgeStore
    from flinttrade_ai.memory_ledger import MemoryLedger
    with MemoryLedger(tmp_path / "ledger") as ledger:
        store = KnowledgeStore(ledger)
        with pytest.raises(ValueError, match="package"):
            store.propose("safe_name", {"safe_name.md": "body", member: "private bytes"},
                          proposer="synthetic", source_ref="synthetic:input")
        assert ledger.history() == ()


@pytest.mark.unit
@pytest.mark.parametrize("files", [
    {"wrong.md": "missing main"},
    {"safe_name.md": "---\nname: other\n---\nbody"},
    {"safe_name.md": "---\nreferences: [missing.md]\n---\nbody"},
    {"safe_name.md": "---\nscripts: script.py\n---\nbody"},
    {"safe_name.md": "---\n[]\n---\nbody"},
])
def test_invalid_procedure_packages_never_enter_candidate_lineage(files, tmp_path):
    from flinttrade_ai.knowledge_store import KnowledgeStore
    from flinttrade_ai.memory_ledger import MemoryLedger
    with MemoryLedger(tmp_path / "ledger") as ledger:
        store = KnowledgeStore(ledger)
        with pytest.raises(ValueError):
            store.propose("safe_name", files, proposer="synthetic", source_ref="synthetic:input")
        assert ledger.history() == ()


@pytest.mark.unit
def test_symlinked_draft_directory_is_not_read_or_written(tmp_path):
    from types import SimpleNamespace
    from flinttrade_ai.skill_drafts import draft_skill_from_reflection, list_drafts, read_draft
    outside = tmp_path / "unrelated"
    outside.mkdir()
    original = outside / "session-lessons-2026-01-01.md"
    original.write_text("Unrelated bytes")
    (tmp_path / "skill_drafts").symlink_to(outside, target_is_directory=True)
    assert read_draft(tmp_path, original.stem) is None
    assert list_drafts(tmp_path) == []
    with pytest.raises(ValueError, match="symlink"):
        draft_skill_from_reflection(tmp_path, SimpleNamespace(recommendations=["No write"]),
                                    session_date="2026-01-01", symbols=[])
    assert original.read_text() == "Unrelated bytes"


@pytest.mark.integration
def test_malformed_packages_cannot_poison_catalogue_or_bypass_guards(tmp_path):
    from flask import Flask
    from flinttrade_ai.knowledge_runtime import KnowledgeRuntime
    from flinttrade_ai.skill_draft_routes import skill_draft_bp
    app = Flask(__name__)
    app.register_blueprint(skill_draft_bp)
    app.config["WORKSPACE_DIR"] = tmp_path
    files = package(tmp_path, "guarded", source="skill_drafts")
    client = app.test_client()
    assert client.get(DRAFTS).status_code == 503
    assert client.get(DRAFTS + "/guarded").status_code == 503
    assert client.post(DRAFTS + "/guarded/approve").status_code == 503
    app.config["BROKER_MGMT_WRITE_GUARD"] = lambda: None
    assert client.post(DRAFTS + "/guarded/approve").status_code == 503
    assert (tmp_path / "skill_drafts" / "guarded.md").read_text() == files["guarded.md"]
    malformed = tmp_path / "skills" / "malformed.md"
    malformed.parent.mkdir(exist_ok=True)
    malformed.write_text("---\n- list\n- not mapping\n---\nUntrusted procedure")
    runtime = KnowledgeRuntime(tmp_path, stock_rights=rights())
    try:
        assert runtime.input_issues == [{"source": "skills", "name": "malformed", "state": "unavailable"}]
        assert "risk_management" in runtime.registry
        app.config["KNOWLEDGE_RUNTIME"] = runtime
        for body in ("[]", "null", '{"validator":"model-self"}', "{"):
            response = client.post(DRAFTS + "/guarded/candidate", data=body, content_type="application/json")
            assert response.status_code == 400
        response = client.post(DRAFTS + "/guarded/candidate", json={})
        assert response.status_code == 202 and response.json["data"]["state"] == "candidate"
        assert response.headers["Cache-Control"] == "no-store"
        listing = client.get(DRAFTS).json["data"]
        assert listing[0]["state"] == "candidate" and listing[0]["enabled"] is False
    finally:
        runtime.close()


@pytest.mark.integration
def test_learned_default_run_pin_rollback_and_full_body_survive_restart(tmp_path):
    from flinttrade_ai.knowledge_runtime import KnowledgeRuntime
    scope = KnowledgeScope("synthetic:a", "paper", "run-a")
    runtime = KnowledgeRuntime(tmp_path, stock_rights=rights())
    first = runtime.store.propose("learned", {"learned.md": "First full procedure"}, proposer="synthetic",
                                  source_ref="synthetic:source", rights=rights(), scope=scope)
    runtime.store.validate(first, validator="independent", evidence_ref="synthetic:suite-1")
    runtime.store.promote(first, expected=None)
    bound = runtime.skills(scope)
    assert "First full procedure" in bound.context(["learned"])[0]
    second = runtime.store.adapt(first, {"learned.md": "Second full procedure"}, proposer="synthetic", rights=rights())
    runtime.store.validate(second, validator="independent", evidence_ref="synthetic:suite-2")
    runtime.store.promote(second, expected=first)
    assert bound.load_skill("learned").content == "First full procedure"
    assert runtime.store.resolve("learned", scope=scope) == second
    rows = bound.catalogue()
    assert next(row for row in rows if row["version_id"] == first)["run_pinned"] is True
    assert next(row for row in rows if row["version_id"] == second)["default"] is True
    runtime.close()
    runtime = KnowledgeRuntime(tmp_path, stock_rights=rights())
    try:
        bound = runtime.skills(scope)
        assert "First full procedure" in bound.context(["learned"])[0]
        runtime.store.retire(second, reason="synthetic independent regression")
        with pytest.raises(ValueError, match="changed"):
            runtime.store.promote(first, expected=None)
        runtime.store.promote(first, expected=second)
        assert runtime.store.resolve("learned", scope=scope) == first
        assert runtime.store.version(second)["files"] == {"learned.md": "Second full procedure"}
        assert "learned" not in runtime.registry
        assert all(row["name"] != "learned" for row in runtime.registry.catalogue())
    finally:
        runtime.close()
