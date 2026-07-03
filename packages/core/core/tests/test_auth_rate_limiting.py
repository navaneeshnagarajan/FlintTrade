# packages/core/core/tests/test_auth_rate_limiting.py
"""Tests for auth endpoint rate limiting.

The FlintTrade auth blueprint applies per-route rate limits via
flask-limiter.  Limits are defined as ``@_rate_limit()`` decorators on each
route in ``auth_routes.py`` and wired onto Flask-Limiter by
``install_auth_rate_limits(app)``, called from ``create_flask_app`` AFTER the
blueprint is registered (the views must already be in ``view_functions``).

Configured limits:
  - /v1/auth/login   → 5 per minute
  - /v1/auth/setup   → 3 per minute
  - /v1/auth/status  → 30 per minute
  - /v1/auth/pin     → 10 per minute
  - /v1/auth/logout  → 10 per minute

NOTE on flask-limiter in tests:
  flask-limiter uses an in-memory backend by default (``memory://``), and each
  app instance gets its own Limiter + storage, so limits are per-app-isolated —
  a fresh ``_make_app`` per test starts with fresh counters.

Run with:
    python -m pytest packages/core/core/tests/test_auth_rate_limiting.py -v --import-mode=importlib
"""

from __future__ import annotations

import os
from pathlib import Path



def _make_app(tmp_path: Path):
    """Create a Flask app with auth service and rate limiter active."""
    os.environ["OPENALGO_API_KEY"] = "rate-limit-test-key"
    # master password comes from the seeded hardened file (root conftest), not env

    from flinttrade_core.app import create_flask_app
    from flinttrade_core.auth_service import AuthService

    auth_db = tmp_path / "auth.db"
    svc = AuthService(db_path=auth_db)

    app = create_flask_app()
    app.config["AUTH_SERVICE"] = svc
    app.config["TESTING"] = True

    # Ensure the rate limiter is enabled (it is by default, but be explicit).
    # flask-limiter honours RATELIMIT_ENABLED; ensure it's not disabled.
    app.config["RATELIMIT_ENABLED"] = True

    return app, svc


# ---------------------------------------------------------------------------
# Login rate limiting — 5 per minute
# ---------------------------------------------------------------------------


class TestLoginRateLimit:
    """POST /v1/auth/login is limited to 5 requests per minute.

    NOTE: flask-limiter with ``memory://`` storage counts requests
    globally per endpoint.  If limits are not applied (e.g. the
    ``_apply_rate_limits`` hook did not fire), requests will never be
    throttled.  This test documents the EXPECTED behaviour.

    If the rate limiter's deferred decoration via ``@auth_bp.record``
    does not wire up correctly in the test environment, these tests
    will pass trivially (all requests return 401/503 instead of 429).
    The test explicitly checks whether 429 appears to detect this case
    and marks it as xfail if the limiter is not active.
    """

    def test_login_rate_limit_applied(self, tmp_path: Path) -> None:
        """Send 6 rapid login attempts — the 6th should be rate-limited.

        The rate limit on /v1/auth/login is ``5 per minute``.  After 5
        requests the 6th should receive HTTP 429 Too Many Requests.
        """
        app, svc = _make_app(tmp_path)

        with app.test_client() as client:
            responses = []
            for i in range(6):
                resp = client.post(
                    "/v1/auth/login",
                    json={"password": "wrong", "totp_code": "000000"},
                )
                responses.append(resp.status_code)

            # First 5 should be either 401 (bad creds) or 503 (no account)
            for code in responses[:5]:
                assert code in (401, 503), f"Expected 401/503, got {code}"

            # The 6th request MUST be 429 — login is limited to 5/min and the
            # limiter is wired via install_auth_rate_limits() after blueprint
            # registration (previously the deferred decoration fired before the
            # routes existed and silently wired nothing, so this test skipped
            # and login brute-force went unthrottled in production).
            assert responses[5] == 429, (
                f"login rate limit did not fire: {responses} (6th must be 429)"
            )


# ---------------------------------------------------------------------------
# Setup rate limiting — 3 per minute
# ---------------------------------------------------------------------------


class TestSetupRateLimit:
    """POST /v1/auth/setup is limited to 3 requests per minute."""

    def test_setup_rate_limit_applied(self, tmp_path: Path) -> None:
        """Send 4 rapid setup attempts — the 4th should be rate-limited."""
        app, svc = _make_app(tmp_path)

        with app.test_client() as client:
            responses = []
            for i in range(4):
                resp = client.post(
                    "/v1/auth/setup",
                    json={
                        "username": f"user{i}",
                        "email": f"user{i}@example.com",
                        "password": "StrongP@ss123!",
                        "pin": f"{100000 + i}",
                    },
                )
                responses.append(resp.status_code)

            # First request should succeed (201) or fail for app reasons.
            # Subsequent setup attempts may return 409 (duplicate — only one
            # account allowed).
            assert responses[0] in (201, 503)

            # The 4th MUST be 429 — setup is limited to 3/min. (Note: the 2nd/3rd
            # legitimately return 409 "already set up" since only one account
            # exists; the limiter still counts them and trips on the 4th.)
            assert responses[3] == 429, (
                f"setup rate limit did not fire: {responses} (4th must be 429)"
            )


# ---------------------------------------------------------------------------
# Status endpoint — 30 per minute (sanity check)
# ---------------------------------------------------------------------------


class TestStatusRateLimit:
    """GET /v1/auth/status has a generous 30/min limit — verify it
    does NOT trigger with normal usage."""

    def test_status_not_rate_limited_within_bounds(self, tmp_path: Path) -> None:
        """10 rapid status checks should all succeed (well within 30/min)."""
        app, _svc = _make_app(tmp_path)

        with app.test_client() as client:
            for _ in range(10):
                resp = client.get("/v1/auth/status")
                assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Rate limiter configuration validation
# ---------------------------------------------------------------------------


class TestRateLimiterConfig:
    """Verify the rate limiter is correctly instantiated in the app."""

    def test_limiter_exists_in_app_config(self, tmp_path: Path) -> None:
        """The Limiter instance should be stored in app.config['LIMITER']."""
        app, _ = _make_app(tmp_path)
        limiter = app.config.get("LIMITER")
        assert limiter is not None, "LIMITER not found in app.config"

    def test_limiter_default_limit_is_50_per_second(self, tmp_path: Path) -> None:
        """Default rate limit is 50 req/s as configured in create_flask_app."""
        app, _ = _make_app(tmp_path)
        limiter = app.config["LIMITER"]
        # flask-limiter stores default limits as a list of LimitGroup objects
        # or strings.  We check that at least one default limit contains "50".
        default_limits = getattr(limiter, "_default_limits", [])
        if default_limits:
            limit_strs = [str(lim) for lim in default_limits]
            assert any("50" in s for s in limit_strs), (
                f"Expected '50 per second' in default limits, got: {limit_strs}"
            )

    def test_rate_limit_decorators_stored_on_view_functions(self) -> None:
        """The @_rate_limit decorator stores limit strings on the function."""
        from flinttrade_core.auth_routes import auth_login, auth_setup

        login_limits = getattr(auth_login, "_rate_limits", [])
        setup_limits = getattr(auth_setup, "_rate_limits", [])

        assert "5 per minute" in login_limits, (
            f"Expected '5 per minute' on auth_login, got: {login_limits}"
        )
        assert "3 per minute" in setup_limits, (
            f"Expected '3 per minute' on auth_setup, got: {setup_limits}"
        )
