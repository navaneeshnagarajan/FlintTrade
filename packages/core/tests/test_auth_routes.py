# packages/core/tests/test_auth_routes.py
"""Tests for auth REST endpoints."""

from __future__ import annotations
import json
import pytest
from unittest.mock import patch
from packages.core.src.app import create_flask_app


@pytest.fixture()
def client(tmp_path):
    """Flask test client with auth service pointed at tmp_path."""
    with patch("packages.core.src.auth_routes._get_auth_service") as mock:
        from packages.core.src.auth_service import AuthService
        svc = AuthService(db_path=tmp_path / "auth.db")
        mock.return_value = svc
        app = create_flask_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c, svc


class TestSetupEndpoint:
    def test_setup_creates_account(self, client):
        c, svc = client
        resp = c.post("/v1/auth/setup", json={
            "username": "nav",
            "email": "nav@example.com",
            "password": "StrongP@ss123!",
            "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "success"
        assert len(data["data"]["backup_codes"]) == 8
        assert "totp_uri" in data["data"]

    def test_setup_rejects_duplicate(self, client):
        c, svc = client
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        resp = c.post("/v1/auth/setup", json={
            "username": "nav2", "email": "nav2@example.com",
            "password": "StrongP@ss123!", "pin": "654321",
        }, headers={"Content-Type": "application/json"})
        assert resp.status_code == 409


class TestLoginEndpoint:
    def test_login_with_correct_credentials(self, client):
        c, svc = client
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        # Get TOTP code
        import pyotp
        secret = svc.get_totp_secret()
        code = pyotp.TOTP(secret).now()
        resp = c.post("/v1/auth/login", json={
            "password": "StrongP@ss123!",
            "totp_code": code,
        }, headers={"Content-Type": "application/json"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "token" in data["data"]

    def test_login_with_wrong_password(self, client):
        c, svc = client
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        resp = c.post("/v1/auth/login", json={
            "password": "wrong",
            "totp_code": "000000",
        }, headers={"Content-Type": "application/json"})
        assert resp.status_code == 401


class TestStatusEndpoint:
    def test_status_returns_setup_state(self, client):
        c, svc = client
        resp = c.get("/v1/auth/status")
        data = resp.get_json()
        assert data["data"]["is_setup"] is False

    def test_status_after_setup(self, client):
        c, svc = client
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        resp = c.get("/v1/auth/status")
        data = resp.get_json()
        assert data["data"]["is_setup"] is True


class TestPinEndpoint:
    def test_pin_verify_correct(self, client):
        c, svc = client
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        resp = c.post("/v1/auth/pin", json={"pin": "123456"},
                       headers={"Content-Type": "application/json"})
        assert resp.status_code == 200

    def test_pin_verify_wrong(self, client):
        c, svc = client
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        resp = c.post("/v1/auth/pin", json={"pin": "000000"},
                       headers={"Content-Type": "application/json"})
        assert resp.status_code == 401

    def test_pin_response_includes_new_token(self, client):
        """Regression for the 2026-05-19 Codex audit finding —
        ``/v1/auth/pin`` must return the live-unlocked JWT so the
        frontend can replace its in-memory token. Discarding the token
        (the old behaviour) left a Practice JWT in place, and every
        subsequent live order was 403'd by ``require_live_unlocked``.
        """
        c, svc = client
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        resp = c.post("/v1/auth/pin", json={"pin": "123456"},
                       headers={"Content-Type": "application/json"})
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert isinstance(data.get("token"), str)
        assert len(data["token"]) > 20
        assert data["live_mode_unlocked"] is True


class TestModeSwitchEndpoint:
    """POST /v1/auth/mode — downgrade live → practice + revoke prior JWT.

    Closes the 2026-05-19 Codex CRITICAL finding (UI mode toggle never
    invalidated the PIN-unlocked JWT). Upgrades must continue to go
    through /v1/auth/pin.
    """

    def _setup_and_pin_unlock(self, c):
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        pin_resp = c.post("/v1/auth/pin", json={"pin": "123456"},
                          headers={"Content-Type": "application/json"})
        return pin_resp.get_json()["data"]["token"]

    def test_downgrade_to_practice_returns_fresh_token(self, client):
        c, _ = client
        live_token = self._setup_and_pin_unlock(c)

        resp = c.post(
            "/v1/auth/mode",
            json={"mode": "practice"},
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {live_token}",
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert isinstance(data["token"], str)
        assert data["token"] != live_token
        assert data["mode"] == "practice"
        assert data["live_mode_unlocked"] is False

    def test_downgrade_revokes_prior_jwt(self, client):
        c, _ = client
        live_token = self._setup_and_pin_unlock(c)

        c.post(
            "/v1/auth/mode",
            json={"mode": "practice"},
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {live_token}",
            },
        )

        # Second downgrade with the now-revoked live token MUST fail.
        retry = c.post(
            "/v1/auth/mode",
            json={"mode": "practice"},
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {live_token}",
            },
        )
        assert retry.status_code == 401

    def test_upgrade_to_live_is_rejected(self, client):
        c, _ = client
        live_token = self._setup_and_pin_unlock(c)

        resp = c.post(
            "/v1/auth/mode",
            json={"mode": "live"},
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {live_token}",
            },
        )
        assert resp.status_code == 400
        assert "pin" in resp.get_json()["message"].lower()

    def test_missing_token_returns_401(self, client):
        c, _ = client
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})

        resp = c.post(
            "/v1/auth/mode",
            json={"mode": "practice"},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401

    def test_revocation_failure_fails_closed(self, client):
        """If JTI revocation raises, the endpoint MUST return 5xx and
        MUST NOT mint a new Practice token. Otherwise the frontend would
        flip the UI to Practice while the stale live-unlocked JWT in
        memory remained replayable. Codex stop-gate caught this gap on
        commit 00c06e7 — the original best-effort revoke was a silent
        defeat of the whole mode-downgrade safety property.
        """
        c, _ = client
        live_token = self._setup_and_pin_unlock(c)

        with patch("packages.core.src.auth_routes._revoke_jti") as mock_revoke:
            mock_revoke.side_effect = RuntimeError("DuckDB lock error")
            resp = c.post(
                "/v1/auth/mode",
                json={"mode": "practice"},
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {live_token}",
                },
            )
        assert resp.status_code == 503
        assert "live" in resp.get_json()["message"].lower()
        # No token should have been minted on the failure path — caller
        # keeps the old live-unlocked JWT, frontend stays in Live.
        assert "data" not in resp.get_json() or "token" not in resp.get_json().get("data", {})


class TestRateLimitRegistration:
    """Codex stop-gate caught that the new `/mode`, `/forgot-password`,
    and `/reset-password` decorators were never registered with
    Flask-Limiter because `_apply_rate_limits` had a hardcoded list of
    five legacy endpoints. The fix swaps that for module-globals
    auto-discovery; this test asserts every `@_rate_limit`-decorated
    view in the module gets at least one rule registered.
    """

    def test_every_decorated_view_is_registered(self):
        import inspect
        from packages.core.src import auth_routes as mod

        # Collect functions that carry the _rate_limits attribute set
        # by the @_rate_limit decorator. ``inspect.isfunction`` is
        # intentionally strict — without it we'd try to ``getattr`` on
        # ``current_app`` (a Werkzeug LocalProxy in module globals),
        # which resolves the proxy and raises "outside request context".
        decorated_views = [
            (name, obj)
            for name, obj in vars(mod).items()
            if inspect.isfunction(obj) and getattr(obj, "_rate_limits", None)
        ]
        # Sanity check — the module should have multiple decorated views.
        assert len(decorated_views) >= 7

        # Each view that's been auto-discovered MUST appear by name in
        # the decorator-aware set so a future contributor can't silently
        # add a route without rate limiting kicking in.
        names = {name for name, _ in decorated_views}
        for required in (
            "auth_status",
            "auth_setup",
            "auth_login",
            "auth_pin_verify",
            "auth_logout",
            "auth_mode_switch",
            "auth_forgot_password",
            "auth_reset_password",
            "auth_setup_reset",
            "auth_setup_regenerate_2fa",
        ):
            assert required in names, (
                f"Auth view '{required}' is missing the @_rate_limit decorator — "
                "every public auth endpoint must be rate-limited."
            )
