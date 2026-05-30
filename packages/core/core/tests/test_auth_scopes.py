"""require_scope decorator behaviour (OBS-09 / observability §16.3)."""

from __future__ import annotations

import jwt
import pytest
from flask import Flask, jsonify

from flinttrade_core.auth_scopes import DEFAULT_SESSION_SCOPES, require_scope


@pytest.fixture
def app():
    app = Flask(__name__)

    @app.route("/guarded")
    @require_scope("admin.audit.read")
    def guarded():
        return jsonify({"ok": True})

    return app


def _token(scopes, secret="x"):
    return jwt.encode({"sub": "op", "jti": "j1", "scopes": scopes}, secret, algorithm="HS256")


def test_no_token_passes_operator_via_api_key(app):
    # No session token => operator authenticated by the shared API key => all scopes.
    with app.test_client() as c:
        assert c.get("/guarded").status_code == 200


def test_session_with_scope_passes(app, monkeypatch):
    monkeypatch.setattr(
        "flinttrade_core.auth_routes.decode_token",
        lambda t: {"scopes": ["admin.audit.read", "admin.activity"]},
    )
    with app.test_client() as c:
        r = c.get("/guarded", headers={"Authorization": "Bearer abc"})
        assert r.status_code == 200


def test_session_missing_scope_is_403(app, monkeypatch):
    monkeypatch.setattr(
        "flinttrade_core.auth_routes.decode_token",
        lambda t: {"scopes": ["admin.observability.read"]},  # no admin.audit.read
    )
    with app.test_client() as c:
        r = c.get("/guarded", headers={"Authorization": "Bearer abc"})
        assert r.status_code == 403
        assert "missing required scope" in r.get_json()["message"]


def test_invalid_session_token_is_401(app, monkeypatch):
    def _boom(_t):
        raise jwt.InvalidTokenError("nope")

    monkeypatch.setattr("flinttrade_core.auth_routes.decode_token", _boom)
    with app.test_client() as c:
        r = c.get("/guarded", headers={"Authorization": "Bearer abc"})
        assert r.status_code == 401


def test_legacy_token_without_scopes_claim_gets_full_default(app, monkeypatch):
    # A session minted before the scopes claim existed is the operator => full scopes.
    monkeypatch.setattr(
        "flinttrade_core.auth_routes.decode_token", lambda t: {"sub": "op", "jti": "j1"}
    )
    with app.test_client() as c:
        assert c.get("/guarded", headers={"Authorization": "Bearer abc"}).status_code == 200


def test_default_scopes_cover_audit_and_activity():
    assert "admin.audit.read" in DEFAULT_SESSION_SCOPES
    assert "admin.activity" in DEFAULT_SESSION_SCOPES
