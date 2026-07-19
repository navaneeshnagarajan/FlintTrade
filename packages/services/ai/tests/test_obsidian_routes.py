"""Lightweight tests for the Obsidian vault routes (blueprint only)."""

from __future__ import annotations

import pytest
from flask import Flask

from flinttrade_ai.obsidian_routes import obsidian_bp

pytestmark = pytest.mark.unit


@pytest.fixture
def client(tmp_path, monkeypatch):
    (tmp_path / "ideas.md").write_text("Iron condor on BANKNIFTY\n", encoding="utf-8")
    monkeypatch.setenv("FLINTTRADE_OBSIDIAN_VAULT", str(tmp_path))
    app = Flask(__name__)
    app.register_blueprint(obsidian_bp)
    return app.test_client()


def test_status_reports_configured(client):
    resp = client.get("/api/v1/ai/obsidian/status")
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["configured"] is True
    assert data["available"] is True


def test_list_notes(client):
    resp = client.get("/api/v1/ai/obsidian/notes")
    assert resp.status_code == 200
    assert "ideas.md" in resp.get_json()["data"]


def test_read_note(client):
    resp = client.get("/api/v1/ai/obsidian/note?path=ideas.md")
    assert resp.status_code == 200
    assert "Iron condor" in resp.get_json()["data"]["content"]


def test_read_missing_note_404(client):
    resp = client.get("/api/v1/ai/obsidian/note?path=nope.md")
    assert resp.status_code == 404


def test_write_then_read(client):
    w = client.post("/api/v1/ai/obsidian/note", json={"path": "Journal/x", "content": "+2R"})
    assert w.status_code == 200
    assert w.get_json()["data"]["path"] == "Journal/x.md"
    r = client.get("/api/v1/ai/obsidian/note?path=Journal/x.md")
    assert "+2R" in r.get_json()["data"]["content"]


def test_write_requires_path(client):
    resp = client.post("/api/v1/ai/obsidian/note", json={"content": "x"})
    assert resp.status_code == 400


def test_search(client):
    resp = client.get("/api/v1/ai/obsidian/search?q=condor")
    assert resp.status_code == 200
    assert any(h["path"] == "ideas.md" for h in resp.get_json()["data"])


def test_not_configured_returns_503(monkeypatch):
    monkeypatch.delenv("FLINTTRADE_OBSIDIAN_VAULT", raising=False)
    app = Flask(__name__)
    app.register_blueprint(obsidian_bp)
    client = app.test_client()
    assert client.get("/api/v1/ai/obsidian/notes").status_code == 503


# ---------------------------------------------------------------------------
# Vault-path config (workspace-backed, env override)
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace_client(tmp_path, monkeypatch):
    """Client with NO env var — the workspace key is the source."""
    monkeypatch.delenv("FLINTTRADE_OBSIDIAN_VAULT", raising=False)
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(tmp_path / "ws"))
    app = Flask(__name__)
    app.register_blueprint(obsidian_bp)
    return app.test_client()


def test_config_roundtrip_persists_the_vault_path(workspace_client, tmp_path):
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    (vault_dir / "note.md").write_text("hello\n", encoding="utf-8")

    resp = workspace_client.post(
        "/api/v1/ai/obsidian/config", json={"vault_path": str(vault_dir)}
    )
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["data"] == {
        "vault_path": str(vault_dir),
        "env_override": False,
    }

    get_resp = workspace_client.get("/api/v1/ai/obsidian/config")
    assert get_resp.get_json()["data"]["vault_path"] == str(vault_dir)

    # The rest of the blueprint now serves from the persisted path.
    status = workspace_client.get("/api/v1/ai/obsidian/status")
    assert status.get_json()["data"]["configured"] is True


def test_config_rejects_a_nonexistent_directory(workspace_client, tmp_path):
    resp = workspace_client.post(
        "/api/v1/ai/obsidian/config", json={"vault_path": str(tmp_path / "missing")}
    )
    assert resp.status_code == 400
    assert "existing directory" in resp.get_json()["message"]


def test_config_clears_with_an_empty_path(workspace_client, tmp_path):
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    workspace_client.post("/api/v1/ai/obsidian/config", json={"vault_path": str(vault_dir)})

    resp = workspace_client.post("/api/v1/ai/obsidian/config", json={"vault_path": ""})
    assert resp.status_code == 200
    assert resp.get_json()["data"]["vault_path"] == ""
    status = workspace_client.get("/api/v1/ai/obsidian/status")
    assert status.get_json()["data"]["configured"] is False


def test_env_variable_overrides_the_stored_path(workspace_client, tmp_path, monkeypatch):
    stored = tmp_path / "stored"
    stored.mkdir()
    env_vault = tmp_path / "env-vault"
    env_vault.mkdir()
    workspace_client.post("/api/v1/ai/obsidian/config", json={"vault_path": str(stored)})
    monkeypatch.setenv("FLINTTRADE_OBSIDIAN_VAULT", str(env_vault))

    get_resp = workspace_client.get("/api/v1/ai/obsidian/config")
    data = get_resp.get_json()["data"]
    assert data == {"vault_path": str(env_vault), "env_override": True}

    save = workspace_client.post(
        "/api/v1/ai/obsidian/config", json={"vault_path": str(stored)}
    )
    assert "overrides" in save.get_json()["message"]
