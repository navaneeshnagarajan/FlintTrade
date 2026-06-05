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
