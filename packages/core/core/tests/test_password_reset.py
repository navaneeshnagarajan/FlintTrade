# packages/core/core/tests/test_password_reset.py
"""Tests for password reset — token generation, verification, password update, endpoints."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import jwt
import pytest

from flinttrade_core.auth_service import AuthService


# ---------------------------------------------------------------------------
# AuthService.update_password
# ---------------------------------------------------------------------------


class TestUpdatePassword:
    """AuthService.update_password — argon2id rehash."""

    def _setup_svc(self, tmp_path: Path) -> AuthService:
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="alice",
            email="alice@example.com",
            password="StrongP@ss123!",
            pin="123456",
        )
        return svc

    def test_update_password_success(self, tmp_path: Path):
        svc = self._setup_svc(tmp_path)
        assert svc.update_password("alice", "NewStr0ngP@ss!") is True
        # Old password no longer works
        assert svc.verify_password("StrongP@ss123!") is False
        # New password works
        assert svc.verify_password("NewStr0ngP@ss!") is True

    def test_update_password_wrong_username(self, tmp_path: Path):
        svc = self._setup_svc(tmp_path)
        assert svc.update_password("wronguser", "NewStr0ngP@ss!") is False
        # Original password still works
        assert svc.verify_password("StrongP@ss123!") is True

    def test_update_password_rejects_weak(self, tmp_path: Path):
        svc = self._setup_svc(tmp_path)
        with pytest.raises(ValueError, match="too weak"):
            svc.update_password("alice", "short")

    def test_update_password_no_account(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        assert svc.update_password("alice", "NewStr0ngP@ss!") is False


class TestGetEmail:
    """AuthService.get_email helper."""

    def test_returns_email_after_setup(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        svc.setup_account(
            username="alice", email="alice@example.com",
            password="StrongP@ss123!", pin="123456",
        )
        assert svc.get_email() == "alice@example.com"

    def test_returns_none_before_setup(self, tmp_path: Path):
        svc = AuthService(db_path=tmp_path / "auth.db")
        assert svc.get_email() is None


# ---------------------------------------------------------------------------
# Token generation and verification (auth_routes helpers)
# ---------------------------------------------------------------------------


class TestResetToken:
    """_create_reset_token / _verify_reset_token from auth_routes."""

    def test_roundtrip(self):
        from flinttrade_core.auth_routes import _create_reset_token, _verify_reset_token

        token = _create_reset_token("alice")
        assert _verify_reset_token(token) == "alice"

    def test_expired_token_rejected(self):
        from flinttrade_core.auth_routes import _get_jwt_secret, _verify_reset_token

        # Manually craft an expired token
        payload = {
            "sub": "alice",
            "iat": time.time() - 7200,
            "exp": time.time() - 3600,  # expired 1 hour ago
            "type": "reset",
            "jti": "deadbeef",
        }
        token = jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")
        assert _verify_reset_token(token) is None

    def test_session_token_rejected_as_reset(self):
        """A regular session JWT must not be accepted as a reset token."""
        from flinttrade_core.auth_routes import _create_token, _verify_reset_token

        session_token = _create_token("alice")
        assert _verify_reset_token(session_token) is None

    def test_invalid_token_string(self):
        from flinttrade_core.auth_routes import _verify_reset_token

        assert _verify_reset_token("not.a.valid.jwt") is None
        assert _verify_reset_token("") is None

    def test_tampered_token(self):
        from flinttrade_core.auth_routes import _create_reset_token, _verify_reset_token

        token = _create_reset_token("testuser")
        # Split JWT into header.payload.signature and corrupt the payload
        parts = token.split(".")
        assert len(parts) == 3
        # Reverse the payload to invalidate the HMAC signature
        parts[1] = parts[1][::-1]
        tampered = ".".join(parts)
        assert _verify_reset_token(tampered) is None


# ---------------------------------------------------------------------------
# Endpoint tests (Flask test client)
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_with_auth(tmp_path: Path):
    """Create a Flask test app with auth service and optionally mocked mail."""
    import os
    os.environ.setdefault("OPENALGO_API_KEY", "test-key-123")
    # master password comes from the seeded hardened file (root conftest), not env

    from flinttrade_core.app import create_flask_app

    auth_db = tmp_path / "auth.db"
    svc = AuthService(db_path=auth_db)
    svc.setup_account(
        username="alice",
        email="alice@example.com",
        password="StrongP@ss123!",
        pin="123456",
    )

    app = create_flask_app()
    app.config["AUTH_SERVICE"] = svc
    app.config["TESTING"] = True
    return app


class TestForgotPasswordEndpoint:
    """POST /v1/auth/forgot-password"""

    def test_returns_503_when_smtp_not_configured(self, app_with_auth):
        app_with_auth.config["MAIL"] = None
        with app_with_auth.test_client() as client:
            resp = client.post(
                "/v1/auth/forgot-password",
                json={"email": "alice@example.com"},
            )
            assert resp.status_code == 503

    def test_returns_200_for_valid_email(self, app_with_auth):
        mock_mail = MagicMock()
        app_with_auth.config["MAIL"] = mock_mail

        with patch("flinttrade_core.auth_routes.Message") as mock_msg_cls:
            mock_msg_cls.return_value = MagicMock()
            with app_with_auth.test_client() as client:
                resp = client.post(
                    "/v1/auth/forgot-password",
                    json={"email": "alice@example.com"},
                )
                assert resp.status_code == 200
                data = resp.get_json()
                assert data["status"] == "success"
                # Email was sent
                mock_mail.send.assert_called_once()

    def test_returns_200_for_unknown_email_no_leak(self, app_with_auth):
        mock_mail = MagicMock()
        app_with_auth.config["MAIL"] = mock_mail

        with app_with_auth.test_client() as client:
            resp = client.post(
                "/v1/auth/forgot-password",
                json={"email": "unknown@example.com"},
            )
            assert resp.status_code == 200
            # No email sent for unknown address
            mock_mail.send.assert_not_called()

    def test_returns_400_when_email_missing(self, app_with_auth):
        mock_mail = MagicMock()
        app_with_auth.config["MAIL"] = mock_mail

        with app_with_auth.test_client() as client:
            resp = client.post(
                "/v1/auth/forgot-password",
                json={},
            )
            assert resp.status_code == 400


class TestResetPasswordEndpoint:
    """POST /v1/auth/reset-password"""

    def test_reset_with_valid_token(self, app_with_auth):
        from flinttrade_core.auth_routes import _create_reset_token

        token = _create_reset_token("alice")

        with app_with_auth.test_client() as client:
            resp = client.post(
                "/v1/auth/reset-password",
                json={"token": token, "new_password": "BrandNewP@ss99!"},
            )
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "success"

        # Verify the new password works
        svc = app_with_auth.config["AUTH_SERVICE"]
        assert svc.verify_password("BrandNewP@ss99!") is True

    def test_reset_with_expired_token(self, app_with_auth):
        from flinttrade_core.auth_routes import _get_jwt_secret

        payload = {
            "sub": "alice",
            "iat": time.time() - 7200,
            "exp": time.time() - 3600,
            "type": "reset",
            "jti": "expired",
        }
        token = jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")

        with app_with_auth.test_client() as client:
            resp = client.post(
                "/v1/auth/reset-password",
                json={"token": token, "new_password": "BrandNewP@ss99!"},
            )
            assert resp.status_code == 400
            assert "expired" in resp.get_json()["message"].lower() or "invalid" in resp.get_json()["message"].lower()

    def test_reset_with_invalid_token(self, app_with_auth):
        with app_with_auth.test_client() as client:
            resp = client.post(
                "/v1/auth/reset-password",
                json={"token": "garbage.token.here", "new_password": "BrandNewP@ss99!"},
            )
            assert resp.status_code == 400

    def test_reset_with_weak_password(self, app_with_auth):
        from flinttrade_core.auth_routes import _create_reset_token

        token = _create_reset_token("alice")

        with app_with_auth.test_client() as client:
            resp = client.post(
                "/v1/auth/reset-password",
                json={"token": token, "new_password": "short"},
            )
            assert resp.status_code == 400
            assert "weak" in resp.get_json()["message"].lower()

    def test_reset_missing_fields(self, app_with_auth):
        with app_with_auth.test_client() as client:
            resp = client.post(
                "/v1/auth/reset-password",
                json={},
            )
            assert resp.status_code == 400
