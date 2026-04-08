"""Tests for packages/core/src/user_routes.py (Flask Blueprint).

Mocks the UserManager and JWT secret so tests run standalone.

Run with:
    python -m pytest packages/core/tests/test_user_routes.py -v --import-mode=importlib
"""

from __future__ import annotations

import datetime
from unittest.mock import MagicMock, patch

import jwt
import pytest
from flask import Flask

from packages.core.src.user_routes import users_bp


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_JWT_SECRET = "test-jwt-secret-for-user-routes-32ch"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _admin_token() -> str:
    """Generate a valid admin JWT token."""
    payload = {
        "sub": "admin",
        "role": "admin",
        "exp": datetime.datetime.now(tz=datetime.timezone.utc)
        + datetime.timedelta(hours=1),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm="HS256")


def _trader_token() -> str:
    """Generate a valid non-admin JWT token."""
    payload = {
        "sub": "trader1",
        "role": "trader",
        "exp": datetime.datetime.now(tz=datetime.timezone.utc)
        + datetime.timedelta(hours=1),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm="HS256")


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_mgr():
    """A mock UserManager with sensible defaults."""
    mgr = MagicMock()
    mgr.list_users.return_value = [
        {"username": "admin", "email": "admin@example.com", "role": "admin", "is_active": True},
    ]
    mgr.create_user.return_value = {
        "username": "newuser",
        "email": "new@example.com",
        "role": "trader",
        "is_active": True,
    }
    mgr.update_user.return_value = True
    mgr.get_user.return_value = {
        "username": "admin",
        "email": "updated@example.com",
        "role": "admin",
        "is_active": True,
    }
    mgr.delete_user.return_value = True
    return mgr


@pytest.fixture()
def app(mock_mgr):
    """Flask app with user blueprint, multi-user enabled, mock manager."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.config["USER_MANAGER"] = mock_mgr
    flask_app.register_blueprint(users_bp)
    return flask_app


@pytest.fixture()
def client(app):
    with patch("packages.core.src.user_routes._get_jwt_secret", return_value=_JWT_SECRET), \
         patch("packages.core.src.user_routes._is_multi_user_enabled", return_value=True):
        with app.test_client() as c:
            yield c


@pytest.fixture()
def client_single_user(app):
    """Client with multi-user mode disabled."""
    with patch("packages.core.src.user_routes._get_jwt_secret", return_value=_JWT_SECRET), \
         patch("packages.core.src.user_routes._is_multi_user_enabled", return_value=False):
        with app.test_client() as c:
            yield c


# ---------------------------------------------------------------------------
# Tests — List users
# ---------------------------------------------------------------------------


class TestListUsers:
    def test_list_users_admin(self, client, mock_mgr):
        resp = client.get("/v1/users", headers=_auth_header(_admin_token()))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert len(data["data"]["users"]) == 1
        mock_mgr.list_users.assert_called_once()

    def test_list_users_no_auth(self, client):
        resp = client.get("/v1/users")
        assert resp.status_code == 401

    def test_list_users_non_admin_forbidden(self, client):
        resp = client.get("/v1/users", headers=_auth_header(_trader_token()))
        assert resp.status_code == 403

    def test_list_users_multi_user_disabled(self, client_single_user):
        resp = client_single_user.get(
            "/v1/users", headers=_auth_header(_admin_token()),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Tests — Create user
# ---------------------------------------------------------------------------


class TestCreateUser:
    def test_create_user_success(self, client, mock_mgr):
        resp = client.post("/v1/users", json={
            "username": "newuser",
            "password": "StrongP@ss1!",
            "email": "new@example.com",
        }, headers=_auth_header(_admin_token()))
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["username"] == "newuser"
        mock_mgr.create_user.assert_called_once()

    def test_create_user_missing_fields(self, client):
        resp = client.post("/v1/users", json={
            "username": "newuser",
        }, headers=_auth_header(_admin_token()))
        assert resp.status_code == 400
        assert "Required fields" in resp.get_json()["message"]


# ---------------------------------------------------------------------------
# Tests — Update user
# ---------------------------------------------------------------------------


class TestUpdateUser:
    def test_update_user_success(self, client, mock_mgr):
        resp = client.put("/v1/users/admin", json={
            "email": "updated@example.com",
        }, headers=_auth_header(_admin_token()))
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        mock_mgr.update_user.assert_called_once_with(
            "admin", email="updated@example.com",
        )

    def test_update_user_no_valid_fields(self, client):
        resp = client.put("/v1/users/admin", json={
            "password": "ignored",
        }, headers=_auth_header(_admin_token()))
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Tests — Delete user
# ---------------------------------------------------------------------------


class TestDeleteUser:
    def test_delete_user_success(self, client, mock_mgr):
        resp = client.delete(
            "/v1/users/trader1", headers=_auth_header(_admin_token()),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "deactivated" in data["data"]["message"]
        mock_mgr.delete_user.assert_called_once_with("trader1")

    def test_delete_user_not_found(self, client, mock_mgr):
        mock_mgr.delete_user.return_value = False
        resp = client.delete(
            "/v1/users/ghost", headers=_auth_header(_admin_token()),
        )
        assert resp.status_code == 404
