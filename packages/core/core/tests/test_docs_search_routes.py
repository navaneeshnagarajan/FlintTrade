"""Tests for packages/core/core/src/docs_search_routes.py — in-app docs search."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from flask import Flask

import flinttrade_core.docs_search_routes as mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app(tmp_path):
    """Flask app with docs search blueprint and a temp docs directory."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.docs_search_bp)

    # Seed a tiny markdown doc so the index has content
    doc = tmp_path / "guide.md"
    doc.write_text("# Order Placement\n\nPlace orders via the orderpad widget.", encoding="utf-8")

    # Build index synchronously against the temp dir
    mod.rebuild_index(docs_dir=tmp_path)

    return flask_app


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# GET /v1/docs/search
# ---------------------------------------------------------------------------


def test_search_ok(client):
    """200 with results array for a known query."""
    resp = client.get("/v1/docs/search?q=order")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "results" in body
    assert "total" in body
    assert isinstance(body["results"], list)


def test_search_missing_q(client):
    """400 when q parameter is absent."""
    resp = client.get("/v1/docs/search")
    assert resp.status_code == 400
    assert resp.get_json()["status"] == "error"


def test_search_no_match(client):
    """Returns empty list for a query with no matching docs."""
    resp = client.get("/v1/docs/search?q=xyzzy_nonexistent_token")
    assert resp.status_code == 200
    assert resp.get_json()["total"] == 0


def test_search_limit_applied(client):
    """Limit parameter caps result count."""
    resp = client.get("/v1/docs/search?q=order&limit=1")
    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["results"]) <= 1


# ---------------------------------------------------------------------------
# GET /v1/docs/document
# ---------------------------------------------------------------------------


def test_document_ok(client):
    """200 with markdown content for an indexed docs-relative path."""
    resp = client.get("/v1/docs/document?path=guide.md")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["path"] == "guide.md"
    assert body["title"] == "Order Placement"
    assert "orderpad widget" in body["content"]


@pytest.mark.parametrize("path", ["", "../secrets.md", "/etc/passwd", "guide.txt"])
def test_document_rejects_invalid_paths(client, path):
    """Document reader must not become an arbitrary filesystem read endpoint."""
    resp = client.get(f"/v1/docs/document?path={path}")

    assert resp.status_code == 400


def test_document_not_found(client):
    """Unknown markdown paths return 404 rather than a fake doc."""
    resp = client.get("/v1/docs/document?path=missing.md")

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /v1/docs/changelog
# ---------------------------------------------------------------------------


def test_changelog_ok(tmp_path):
    """200 serving CHANGELOG.md content as plain text."""
    # Create a temporary changelog and patch the module-level path
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## v0.5.0\n- Initial release\n", encoding="utf-8")

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.docs_search_bp)

    with patch.object(mod, "_CHANGELOG_PATH", changelog):
        with flask_app.test_client() as c:
            resp = c.get("/v1/docs/changelog")

    assert resp.status_code == 200
    assert b"v0.5.0" in resp.data


def test_changelog_not_found(tmp_path):
    """404 when CHANGELOG.md does not exist."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(mod.docs_search_bp)

    missing = tmp_path / "CHANGELOG.md"  # not created

    with patch.object(mod, "_CHANGELOG_PATH", missing):
        with flask_app.test_client() as c:
            resp = c.get("/v1/docs/changelog")

    assert resp.status_code == 404
