# packages/core/tests/test_csrf.py
"""Tests for CSRF double-submit cookie protection.

FlintTrade uses API key authentication (X-API-Key header) for all
endpoints.  There is no cookie-based session auth, which means
traditional CSRF attacks do not apply — browsers never automatically
attach API keys to cross-origin requests.

However, if a cookie-based CSRF layer is added in the future this test
suite validates the double-submit cookie flow end-to-end.  For now it
tests the existing security surface:

- API key auth rejects requests without the key (401)
- API key requests are not affected by the absence of CSRF tokens
- Public /v1/auth/* endpoints bypass API key auth
- GET requests do not require API key when explicitly public

Run with:
    python -m pytest packages/core/tests/test_csrf.py -v --import-mode=importlib
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

_TEST_API_KEY = "csrf-test-api-key"


@pytest.fixture()
def app():
    """Create a Flask test app with auth middleware active."""
    os.environ["OPENALGO_API_KEY"] = _TEST_API_KEY
    os.environ.setdefault("MASTER_PASSWORD", "test-master-pw")

    from packages.core.src.app import create_flask_app

    flask_app = create_flask_app()
    flask_app.config["TESTING"] = True
    yield flask_app

    # Restore — don't leak test key
    if os.environ.get("OPENALGO_API_KEY") == _TEST_API_KEY:
        os.environ.pop("OPENALGO_API_KEY", None)


@pytest.fixture()
def client(app):
    """Flask test client (no automatic auth headers)."""
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# API Key Auth — the primary CSRF-equivalent protection
# ---------------------------------------------------------------------------


class TestApiKeyProtection:
    """API key header acts as CSRF protection — cross-origin requests
    cannot include it automatically."""

    def test_post_without_api_key_returns_401(self, client: Any) -> None:
        """POST to a protected endpoint without X-API-Key is rejected."""
        resp = client.post(
            "/api/v1/security/ban",
            json={"ip": "1.2.3.4", "reason": "test"},
        )
        assert resp.status_code == 401
        data = resp.get_json()
        assert data["status"] == "error"
        assert "unauthorized" in data["message"].lower()

    def test_post_with_wrong_api_key_returns_401(self, client: Any) -> None:
        """POST with an incorrect API key is rejected."""
        resp = client.post(
            "/api/v1/security/ban",
            json={"ip": "1.2.3.4", "reason": "test"},
            headers={"X-API-Key": "wrong-key-entirely"},
        )
        assert resp.status_code == 401

    def test_post_with_correct_api_key_succeeds(self, client: Any) -> None:
        """POST with the correct X-API-Key header passes auth."""
        resp = client.post(
            "/api/v1/security/ban",
            json={"ip": "10.0.0.99", "reason": "test ban"},
            headers={"X-API-Key": _TEST_API_KEY},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"

    def test_bearer_token_also_accepted(self, client: Any) -> None:
        """Authorization: Bearer <key> is an alternative to X-API-Key."""
        resp = client.get(
            "/api/v1/security/stats",
            headers={"Authorization": f"Bearer {_TEST_API_KEY}"},
        )
        assert resp.status_code == 200

    def test_get_protected_endpoint_without_key_returns_401(self, client: Any) -> None:
        """GET requests to non-public endpoints also need the API key."""
        resp = client.get("/api/v1/security/stats")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Public endpoint bypass — /v1/auth/* does not need API key
# ---------------------------------------------------------------------------


class TestPublicEndpointBypass:
    """Public auth endpoints are accessible without API key."""

    def test_auth_status_no_key_required(self, client: Any) -> None:
        """GET /v1/auth/status is public — no API key needed."""
        resp = client.get("/v1/auth/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"

    def test_auth_login_no_key_required(self, client: Any) -> None:
        """POST /v1/auth/login is public (returns 401 on bad creds, not 403)."""
        resp = client.post(
            "/v1/auth/login",
            json={"password": "wrong", "totp_code": "000000"},
        )
        # Auth service may not be set up, but we should NOT get a 401 from
        # the API key check — that would be a different 401 message.
        assert resp.status_code in (401, 503)
        data = resp.get_json()
        # The error should be about credentials or service, not about API key
        assert "unauthorized" not in data.get("message", "").lower() or \
            "credentials" in data.get("message", "").lower() or \
            "service" in data.get("message", "").lower()

    def test_auth_setup_no_key_required(self, client: Any) -> None:
        """POST /v1/auth/setup is public — accessible without API key."""
        resp = client.post(
            "/v1/auth/setup",
            json={
                "username": "testuser",
                "email": "test@example.com",
                "password": "StrongP@ss123!",
                "pin": "123456",
            },
        )
        # Should succeed (201) or conflict (409) — never 401 from API key
        assert resp.status_code in (201, 409, 503)


# ---------------------------------------------------------------------------
# OPTIONS preflight bypass
# ---------------------------------------------------------------------------


class TestCorsPreflightBypass:
    """OPTIONS requests bypass auth for CORS preflight."""

    def test_options_request_does_not_need_api_key(self, client: Any) -> None:
        """CORS preflight (OPTIONS) should not be blocked by auth."""
        resp = client.options("/api/v1/security/stats")
        assert resp.status_code != 401


# ---------------------------------------------------------------------------
# Content-Type enforcement — mitigates non-JSON CSRF payloads
# ---------------------------------------------------------------------------


class TestContentTypeEnforcement:
    """POST/PUT/PATCH requests must send Content-Type: application/json.

    This is an important CSRF mitigation: browsers can send form-encoded
    POST requests cross-origin, but cannot send application/json without
    a CORS preflight.
    """

    def test_post_with_form_data_returns_415(self, client: Any) -> None:
        """POST with form-encoded data is rejected with 415."""
        resp = client.post(
            "/api/v1/security/ban",
            data="ip=1.2.3.4&reason=test",
            content_type="application/x-www-form-urlencoded",
            headers={"X-API-Key": _TEST_API_KEY},
        )
        assert resp.status_code == 415
        data = resp.get_json()
        assert "json" in data["message"].lower()

    def test_post_with_json_content_type_passes(self, client: Any) -> None:
        """POST with application/json Content-Type passes validation."""
        resp = client.post(
            "/api/v1/security/ban",
            json={"ip": "10.0.0.88", "reason": "content-type test"},
            headers={"X-API-Key": _TEST_API_KEY},
        )
        assert resp.status_code == 200
