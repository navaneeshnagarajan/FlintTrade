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
