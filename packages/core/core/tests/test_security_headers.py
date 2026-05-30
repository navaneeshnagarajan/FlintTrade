"""Tests for the security headers after_request hook in app.py.

Verifies that every response from the FlintTrade Flask app carries the
five mandatory security headers defined in create_flask_app().

Run with:
    python -m pytest packages/core/core/tests/test_security_headers.py -v --import-mode=importlib
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
    from flinttrade_core.app import create_flask_app

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

    def test_csp_header_is_nonce_based_no_unsafe_inline(self, client):
        """CSP is delivered as a per-request gateway header with a nonce (DS-CSP-09).

        Supersedes the old "Nginx sets CSP, Flask must not" rule: only the gateway can
        mint a per-render nonce and weave it into the served HTML, so it must own CSP.
        """
        resp = _authed_get(client, "/v1/admin/health")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert csp, "gateway must set a Content-Security-Policy header"
        # the script directive must carry a nonce and must NOT allow inline scripts
        import re

        script_src = next(
            (d for d in csp.split(";") if d.strip().startswith("script-src")), ""
        )
        assert "'nonce-" in script_src, f"script directive lacks a nonce: {script_src!r}"
        assert "'unsafe-inline'" not in script_src, (
            f"script directive must not allow inline scripts: {script_src!r}"
        )
        # nonce must differ across requests (per-request randomness)
        resp2 = _authed_get(client, "/v1/admin/health")
        nonce1 = re.search(r"'nonce-([^']+)'", csp)
        nonce2 = re.search(
            r"'nonce-([^']+)'", resp2.headers.get("Content-Security-Policy", "")
        )
        assert nonce1 and nonce2 and nonce1.group(1) != nonce2.group(1), (
            "CSP nonce must be unique per request"
        )
