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
