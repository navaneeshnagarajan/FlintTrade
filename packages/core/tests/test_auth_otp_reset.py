# packages/core/tests/test_auth_otp_reset.py
"""Tests for email OTP password reset endpoints and EmailTransport.

No real SMTP or SES connections are made. All network calls are mocked.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path):
    """Flask test client backed by a real AuthService in a tmp directory."""
    with patch("packages.core.src.auth_routes._get_auth_service") as mock_svc:
        from packages.core.src.auth_service import AuthService

        svc = AuthService(db_path=tmp_path / "auth.db")
        mock_svc.return_value = svc
        from packages.core.src.app import create_flask_app

        app = create_flask_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c, svc


def _setup_account(c, email="alice@example.com"):
    """Register an account and return the client + svc."""
    c.post(
        "/v1/auth/setup",
        json={
            "username": "alice",
            "email": email,
            "password": "StrongP@ss123!",
            "pin": "123456",
        },
        headers={"Content-Type": "application/json"},
    )


# ---------------------------------------------------------------------------
# Internal helpers — OTP store
# ---------------------------------------------------------------------------


class TestOtpHelpers:
    def setup_method(self):
        """Clear the OTP store before each test."""
        import packages.core.src.auth_routes as ar

        ar._OTP_STORE.clear()
        ar._OTP_REQUEST_LOG.clear()

    def test_generate_otp_is_6_digits(self):
        from packages.core.src.auth_routes import _generate_otp

        for _ in range(20):
            otp = _generate_otp()
            assert len(otp) == 6
            assert otp.isdigit()

    def test_store_and_verify_otp_succeeds(self):
        from packages.core.src.auth_routes import _store_otp, _verify_and_consume_otp

        _store_otp("a@b.com", "123456")
        assert _verify_and_consume_otp("a@b.com", "123456") is True

    def test_verify_otp_consumed_on_success(self):
        from packages.core.src.auth_routes import _store_otp, _verify_and_consume_otp

        _store_otp("a@b.com", "111111")
        _verify_and_consume_otp("a@b.com", "111111")  # consume it
        assert _verify_and_consume_otp("a@b.com", "111111") is False

    def test_verify_wrong_otp_returns_false(self):
        from packages.core.src.auth_routes import _store_otp, _verify_and_consume_otp

        _store_otp("a@b.com", "999999")
        assert _verify_and_consume_otp("a@b.com", "000000") is False

    def test_verify_expired_otp_returns_false(self):
        import packages.core.src.auth_routes as ar

        ar._OTP_STORE["x@y.com"] = {
            "otp": "555555",
            "expiry": time.monotonic() - 1,  # already expired
        }
        assert ar._verify_and_consume_otp("x@y.com", "555555") is False

    def test_verify_unknown_email_returns_false(self):
        from packages.core.src.auth_routes import _verify_and_consume_otp

        assert _verify_and_consume_otp("nobody@example.com", "000000") is False

    def test_otp_rate_limit_allows_3_per_hour(self):
        from packages.core.src.auth_routes import _otp_rate_ok

        email = "rate@test.com"
        assert _otp_rate_ok(email) is True   # 1st
        assert _otp_rate_ok(email) is True   # 2nd
        assert _otp_rate_ok(email) is True   # 3rd
        assert _otp_rate_ok(email) is False  # 4th — blocked

    def test_otp_rate_limit_resets_after_hour(self):
        import packages.core.src.auth_routes as ar

        email = "reset@test.com"
        # Simulate 3 requests from 2 hours ago
        old = time.monotonic() - 7200
        ar._OTP_REQUEST_LOG[email] = [old, old, old]
        assert ar._otp_rate_ok(email) is True  # window expired, allowed again


# ---------------------------------------------------------------------------
# EmailTransport — SMTP
# ---------------------------------------------------------------------------


class TestEmailTransportSmtp:
    def test_send_otp_via_smtp(self):
        from packages.core.src.auth_routes import EmailTransport

        transport = EmailTransport()
        transport._smtp_host = "smtp.example.com"
        transport._smtp_port = 587
        transport._smtp_user = "user@example.com"
        transport._smtp_password = "secret"
        transport._smtp_from = "user@example.com"
        transport._ses_region = ""

        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__ = lambda s: mock_server
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            result = transport.send_otp("alice@example.com", "123456")

        assert result is True

    def test_smtp_returns_false_on_exception(self):
        from packages.core.src.auth_routes import EmailTransport

        transport = EmailTransport()
        transport._smtp_host = "smtp.example.com"
        transport._smtp_port = 587
        transport._smtp_user = "u"
        transport._smtp_password = "p"
        transport._smtp_from = "u@x.com"
        transport._ses_region = ""

        with patch("smtplib.SMTP", side_effect=OSError("connection refused")):
            result = transport.send_otp("alice@example.com", "000000")

        assert result is False

    def test_smtp_skipped_when_no_host(self):
        from packages.core.src.auth_routes import EmailTransport

        transport = EmailTransport()
        transport._smtp_host = ""
        transport._smtp_from = ""
        transport._ses_region = ""

        with patch("smtplib.SMTP") as mock_smtp:
            result = transport._send_smtp("x@y.com", "subject", "body")

        mock_smtp.assert_not_called()
        assert result is False


# ---------------------------------------------------------------------------
# EmailTransport — SES
# ---------------------------------------------------------------------------


class TestEmailTransportSes:
    def test_send_otp_via_ses(self):
        from packages.core.src.auth_routes import EmailTransport

        transport = EmailTransport()
        transport._smtp_host = ""
        transport._smtp_from = "no-reply@example.com"
        transport._ses_region = "ap-south-1"

        mock_boto = MagicMock()
        mock_client = MagicMock()
        mock_boto.client.return_value = mock_client

        with patch.dict("sys.modules", {"boto3": mock_boto}):
            result = transport.send_otp("alice@example.com", "654321")

        assert result is True
        mock_client.send_email.assert_called_once()

    def test_ses_returns_false_when_boto3_missing(self):
        import sys
        from packages.core.src.auth_routes import EmailTransport

        transport = EmailTransport()
        transport._smtp_host = ""
        transport._smtp_from = "from@x.com"
        transport._ses_region = "us-east-1"

        # Remove boto3 from sys.modules to simulate absence
        with patch.dict("sys.modules", {"boto3": None}):
            result = transport._send_ses("to@x.com", "sub", "body")

        assert result is False

    def test_ses_returns_false_when_no_from_address(self):
        from packages.core.src.auth_routes import EmailTransport

        transport = EmailTransport()
        transport._smtp_from = ""
        transport._ses_region = "us-east-1"

        result = transport._send_ses("to@x.com", "sub", "body")
        assert result is False


# ---------------------------------------------------------------------------
# POST /v1/auth/forgot-password-otp
# ---------------------------------------------------------------------------


class TestForgotPasswordOtpEndpoint:
    def setup_method(self):
        import packages.core.src.auth_routes as ar

        ar._OTP_STORE.clear()
        ar._OTP_REQUEST_LOG.clear()

    def test_returns_200_for_registered_email(self, client):
        c, svc = client
        _setup_account(c)

        mock_transport = MagicMock()
        mock_transport.send_otp.return_value = True

        import packages.core.src.auth_routes as ar

        ar.set_email_transport(mock_transport)

        resp = c.post(
            "/v1/auth/forgot-password-otp",
            json={"email": "alice@example.com"},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "success"
        mock_transport.send_otp.assert_called_once()
        call_email, call_otp = mock_transport.send_otp.call_args[0]
        assert call_email == "alice@example.com"
        assert len(call_otp) == 6 and call_otp.isdigit()

    def test_returns_200_for_unknown_email(self, client):
        """Should not reveal whether email is registered."""
        c, _ = client
        resp = c.post(
            "/v1/auth/forgot-password-otp",
            json={"email": "nobody@example.com"},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200

    def test_returns_400_when_email_missing(self, client):
        c, _ = client
        resp = c.post(
            "/v1/auth/forgot-password-otp",
            json={},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_rate_limit_blocks_4th_request(self, client):
        c, svc = client
        _setup_account(c)

        import packages.core.src.auth_routes as ar

        mock_transport = MagicMock()
        mock_transport.send_otp.return_value = True
        ar.set_email_transport(mock_transport)

        for _ in range(3):
            r = c.post(
                "/v1/auth/forgot-password-otp",
                json={"email": "alice@example.com"},
                headers={"Content-Type": "application/json"},
            )
            assert r.status_code == 200

        r4 = c.post(
            "/v1/auth/forgot-password-otp",
            json={"email": "alice@example.com"},
            headers={"Content-Type": "application/json"},
        )
        assert r4.status_code == 429


# ---------------------------------------------------------------------------
# POST /v1/auth/reset-password-otp
# ---------------------------------------------------------------------------


class TestResetPasswordOtpEndpoint:
    def setup_method(self):
        import packages.core.src.auth_routes as ar

        ar._OTP_STORE.clear()
        ar._OTP_REQUEST_LOG.clear()

    def test_reset_succeeds_with_valid_otp(self, client):
        c, svc = client
        _setup_account(c)

        import packages.core.src.auth_routes as ar

        otp = "424242"
        ar._store_otp("alice@example.com", otp)

        resp = c.post(
            "/v1/auth/reset-password-otp",
            json={
                "email": "alice@example.com",
                "otp": otp,
                "new_password": "NewStr0ng!Pass",
            },
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"

    def test_reset_fails_with_wrong_otp(self, client):
        c, svc = client
        _setup_account(c)

        import packages.core.src.auth_routes as ar

        ar._store_otp("alice@example.com", "111111")

        resp = c.post(
            "/v1/auth/reset-password-otp",
            json={
                "email": "alice@example.com",
                "otp": "999999",
                "new_password": "NewStr0ng!Pass",
            },
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert "Invalid" in resp.get_json()["message"]

    def test_reset_fails_with_expired_otp(self, client):
        c, _ = client
        import packages.core.src.auth_routes as ar

        ar._OTP_STORE["alice@example.com"] = {
            "otp": "777777",
            "expiry": time.monotonic() - 1,
        }

        resp = c.post(
            "/v1/auth/reset-password-otp",
            json={
                "email": "alice@example.com",
                "otp": "777777",
                "new_password": "NewStr0ng!Pass",
            },
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_reset_fails_for_wrong_email(self, client):
        c, svc = client
        _setup_account(c)

        import packages.core.src.auth_routes as ar

        ar._store_otp("other@example.com", "123456")

        resp = c.post(
            "/v1/auth/reset-password-otp",
            json={
                "email": "other@example.com",
                "otp": "123456",
                "new_password": "NewStr0ng!Pass",
            },
            headers={"Content-Type": "application/json"},
        )
        # OTP validates but email is not the registered one
        assert resp.status_code == 400
        assert "not registered" in resp.get_json()["message"]

    def test_reset_returns_400_missing_fields(self, client):
        c, _ = client
        resp = c.post(
            "/v1/auth/reset-password-otp",
            json={"email": "alice@example.com"},
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_otp_consumed_after_successful_reset(self, client):
        c, svc = client
        _setup_account(c)

        import packages.core.src.auth_routes as ar

        otp = "555555"
        ar._store_otp("alice@example.com", otp)

        c.post(
            "/v1/auth/reset-password-otp",
            json={
                "email": "alice@example.com",
                "otp": otp,
                "new_password": "NewStr0ng!Pass",
            },
            headers={"Content-Type": "application/json"},
        )

        # Second attempt with same OTP must fail
        resp2 = c.post(
            "/v1/auth/reset-password-otp",
            json={
                "email": "alice@example.com",
                "otp": otp,
                "new_password": "AnotherPass!1",
            },
            headers={"Content-Type": "application/json"},
        )
        assert resp2.status_code == 400
