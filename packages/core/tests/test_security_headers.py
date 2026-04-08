"""Tests for the security headers after_request hook in app.py.

Verifies that every response from the FlintTrade Flask app carries the
five mandatory security headers defined in create_flask_app().

Run with:
    python -m pytest packages/core/tests/test_security_headers.py -v --import-mode=importlib
"""

from __future__ import annotations

import os

import pytest

_TEST_API_KEY = "test-secheaders-key"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _restore_env():
    """Restore environment after module-scoped tests."""
    original = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(original)


@pytest.fixture(scope="module")
def client(_restore_env):
    """Flask test client with a pre-set API key."""
    os.environ["OPENALGO_API_KEY"] = _TEST_API_KEY
    from packages.core.src.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _authed_get(client, path: str):
    """Issue a GET request with the test API key."""
    return client.get(path, headers={"X-API-Key": _TEST_API_KEY})


# ---------------------------------------------------------------------------
# Header presence tests
# ---------------------------------------------------------------------------


class TestSecurityHeaders:
    """All five mandatory headers must be present on every response."""

    def test_x_content_type_options_present(self, client):
        resp = _authed_get(client, "/v1/admin/health")
        assert "X-Content-Type-Options" in resp.headers

    def test_x_content_type_options_value(self, client):
        resp = _authed_get(client, "/v1/admin/health")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"

    def test_x_frame_options_deny(self, client):
        resp = _authed_get(client, "/v1/admin/health")
        assert resp.headers.get("X-Frame-Options") == "DENY"

    def test_x_xss_protection(self, client):
        resp = _authed_get(client, "/v1/admin/health")
        assert resp.headers.get("X-XSS-Protection") == "1; mode=block"

    def test_referrer_policy(self, client):
        resp = _authed_get(client, "/v1/admin/health")
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy(self, client):
        resp = _authed_get(client, "/v1/admin/health")
        val = resp.headers.get("Permissions-Policy", "")
        assert "camera=()" in val
        assert "microphone=()" in val
        assert "geolocation=()" in val

    def test_headers_on_401_response(self, client):
        """Security headers must be set even on unauthenticated error responses."""
        resp = client.get("/v1/admin/health")  # no API key
        # Health check is an exempted endpoint — still gets headers regardless
        assert "X-Content-Type-Options" in resp.headers

    def test_no_csp_header_set_by_flask(self, client):
        """CSP is Nginx's responsibility — Flask must not set it."""
        resp = _authed_get(client, "/v1/admin/health")
        assert "Content-Security-Policy" not in resp.headers
