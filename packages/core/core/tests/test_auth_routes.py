# packages/core/core/tests/test_auth_routes.py
"""Tests for auth REST endpoints."""

from __future__ import annotations
import pytest
from unittest.mock import patch
from flinttrade_core.app import create_flask_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Flask test client with auth service pointed at tmp_path."""
    # Other test modules set OPENALGO_API_KEY / FLINTTRADE_API_KEY via os.environ
    # directly, and the value leaks across xdist workers — making the global
    # require_auth demand an X-API-Key before our own auth guards even run.
    # Unset them so the guard/PIN/native-write tests exercise the loopback
    # allowance deterministically (mirrors the test_native_account_routes fixture).
    monkeypatch.delenv("OPENALGO_API_KEY", raising=False)
    monkeypatch.delenv("FLINTTRADE_API_KEY", raising=False)
    with patch("flinttrade_core.auth_routes._get_auth_service") as mock:
        from flinttrade_core.auth_service import AuthService
        svc = AuthService(db_path=tmp_path / "auth.db")
        mock.return_value = svc
        app = create_flask_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c, svc


def _session_headers() -> dict[str, str]:
    """A valid session JWT — /v1/auth/pin is session-bound (policy D6): the
    PIN is a re-auth factor, never a session-minting factor."""
    from flinttrade_core.auth_routes import _create_token

    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_create_token('nav', mode='explore')}",
    }


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


def _enable_totp(svc, password: str = "StrongP@ss123!") -> str:
    """Confirm authenticator enrolment and return the live TOTP code used."""
    import pyotp

    assert svc.verify_password(password)
    code = pyotp.TOTP(svc.get_totp_secret()).now()
    assert svc.enable_totp(code)
    return code


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

    def test_login_password_only_when_authenticator_deferred(self, client):
        """FT-SETUP-002: Explore/Practice daily login is password-only
        until the operator enrols TOTP."""
        c, svc = client
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        assert svc.is_totp_enabled() is False
        resp = c.post("/v1/auth/login", json={
            "password": "StrongP@ss123!",
        }, headers={"Content-Type": "application/json"})
        assert resp.status_code == 200
        assert "token" in resp.get_json()["data"]

    def test_login_requires_totp_once_enrolled(self, client):
        c, svc = client
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        _enable_totp(svc)
        resp = c.post("/v1/auth/login", json={
            "password": "StrongP@ss123!",
        }, headers={"Content-Type": "application/json"})
        assert resp.status_code == 401
        assert "totp" in resp.get_json()["message"].lower()
        import pyotp
        code = pyotp.TOTP(svc.get_totp_secret()).now()
        ok = c.post("/v1/auth/login", json={
            "password": "StrongP@ss123!",
            "totp_code": code,
        }, headers={"Content-Type": "application/json"})
        assert ok.status_code == 200

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


class TestTotpEnableEndpoint:
    """POST /v1/auth/totp/enable — confirm optional authenticator enrolment."""

    def test_enable_totp_with_live_code(self, client):
        import pyotp
        c, svc = client
        setup = c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        token = setup.get_json()["data"]["token"]
        code = pyotp.TOTP(svc.get_totp_secret()).now()
        resp = c.post(
            "/v1/auth/totp/enable",
            json={"totp_code": code},
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["totp_enabled"] is True
        assert svc.is_totp_enabled() is True

    def test_enable_totp_rejects_wrong_code(self, client):
        c, svc = client
        setup = c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        token = setup.get_json()["data"]["token"]
        resp = c.post(
            "/v1/auth/totp/enable",
            json={"totp_code": "000000"},
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401
        assert svc.is_totp_enabled() is False


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
        assert data["data"]["totp_enabled"] is False

    def test_status_totp_enabled_after_enrolment(self, client):
        c, svc = client
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        _enable_totp(svc)
        data = c.get("/v1/auth/status").get_json()["data"]
        assert data["totp_enabled"] is True


class TestPinEndpoint:
    def _setup_with_totp(self, c, svc):
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        _enable_totp(svc)

    def test_pin_verify_correct(self, client):
        c, svc = client
        self._setup_with_totp(c, svc)
        resp = c.post("/v1/auth/pin", json={"pin": "123456"},
                       headers=_session_headers())
        assert resp.status_code == 200

    def test_live_pin_requires_authenticator_enrolment(self, client):
        """FT-SETUP-002: Live unlock keeps the stronger gate. Password-only
        Explore/Practice must not be enough to arm real-money mode."""
        c, svc = client
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        resp = c.post("/v1/auth/pin", json={"pin": "123456"},
                       headers=_session_headers())
        assert resp.status_code == 403
        body = resp.get_json()
        assert body.get("code") == "totp_required"
        assert "authenticator" in body["message"].lower()
        _enable_totp(svc)
        ok = c.post("/v1/auth/pin", json={"pin": "123456"},
                    headers=_session_headers())
        assert ok.status_code == 200
        assert ok.get_json()["data"]["live_mode_unlocked"] is True

    def test_practice_pin_unlock_without_totp(self, client):
        """Mode-preserving idle unlock stays password/PIN — TOTP is a Live gate."""
        c, _svc = client
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        resp = c.post("/v1/auth/pin", json={"pin": "123456", "mode": "practice"},
                       headers=_session_headers())
        assert resp.status_code == 200
        assert resp.get_json()["data"]["live_mode_unlocked"] is False

    def test_pin_verify_wrong(self, client):
        c, svc = client
        self._setup_with_totp(c, svc)
        resp = c.post("/v1/auth/pin", json={"pin": "000000"},
                       headers=_session_headers())
        assert resp.status_code == 401

    def test_pin_response_includes_new_token(self, client):
        """Regression for the 2026-05-19 Codex audit finding —
        ``/v1/auth/pin`` must return the live-unlocked JWT so the
        frontend can replace its in-memory token. Discarding the token
        (the old behaviour) left a Practice JWT in place, and every
        subsequent live order was 403'd by ``require_live_unlocked``.
        """
        c, svc = client
        self._setup_with_totp(c, svc)
        resp = c.post("/v1/auth/pin", json={"pin": "123456"},
                       headers=_session_headers())
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert isinstance(data.get("token"), str)
        assert len(data["token"]) > 20
        assert data["live_mode_unlocked"] is True


class TestPinSetEndpoint:
    """POST /v1/auth/pin/set — the set-PIN-later path.

    The PIN is optional at setup, but Live is armed exclusively via
    /v1/auth/pin; without this route a PIN-less account could never reach
    Live except by wiping itself. Session-bound (G9-style) + password
    re-confirm; mints no token (the PIN stays a re-auth factor, D6).
    """

    def _setup_without_pin(self, c):
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "",
        }, headers={"Content-Type": "application/json"})

    def test_status_exposes_has_pin(self, client):
        c, _ = client
        self._setup_without_pin(c)
        data = c.get("/v1/auth/status").get_json()["data"]
        assert data["has_pin"] is False

    def test_pin_verify_without_pin_returns_distinct_message(self, client):
        """A PIN-less account must not be told 'Invalid PIN.' — the old
        message sent operators chasing a PIN they never set, leaving Live
        permanently unreachable with no hint of the fix."""
        c, _ = client
        self._setup_without_pin(c)
        resp = c.post("/v1/auth/pin", json={"pin": "123456"},
                      headers=_session_headers())
        assert resp.status_code == 409
        body = resp.get_json()
        assert body.get("code") == "pin_not_set"
        assert "no pin is set" in body["message"].lower()
        assert "settings" in body["message"].lower()

    def test_set_pin_requires_session(self, client):
        c, _ = client
        self._setup_without_pin(c)
        resp = c.post("/v1/auth/pin/set",
                      json={"password": "StrongP@ss123!", "pin": "654321"},
                      headers={"Content-Type": "application/json"})
        assert resp.status_code == 401

    def test_set_pin_rejects_reset_token(self, client):
        """A reset token proves only email possession — (reset token + new
        PIN) must never become a Live-arming path."""
        c, _ = client
        self._setup_without_pin(c)
        from flinttrade_core.auth_routes import _create_reset_token

        reset = _create_reset_token("nav")
        resp = c.post("/v1/auth/pin/set",
                      json={"password": "StrongP@ss123!", "pin": "654321"},
                      headers={"Content-Type": "application/json",
                               "Authorization": f"Bearer {reset}"})
        assert resp.status_code == 401
        assert "full login session" in resp.get_json()["message"].lower()

    def test_set_pin_rejects_wrong_password(self, client):
        c, _ = client
        self._setup_without_pin(c)
        resp = c.post("/v1/auth/pin/set",
                      json={"password": "wrong-password", "pin": "654321"},
                      headers=_session_headers())
        assert resp.status_code == 401

    @pytest.mark.parametrize("pin", [
        "12345",
        "1234567",
        "12ab56",
        "abcdef",
        "１２３４５６",
    ])
    def test_set_pin_rejects_non_six_digit_pin(self, client, pin):
        """FT-SET-003: /v1/auth/pin/set stays fail-closed on anything but ^\\d{6}$."""
        c, _ = client
        self._setup_without_pin(c)
        resp = c.post("/v1/auth/pin/set",
                      json={"password": "StrongP@ss123!", "pin": pin},
                      headers=_session_headers())
        assert resp.status_code == 400
        assert "exactly 6 digits" in resp.get_json()["message"]

    def test_set_pin_then_live_unlock_works(self, client):
        """End-to-end recovery for the skipped-PIN account: set a PIN over a
        live session, then arm Live with it via /v1/auth/pin."""
        c, svc = client
        self._setup_without_pin(c)

        resp = c.post("/v1/auth/pin/set",
                      json={"password": "StrongP@ss123!", "pin": "654321"},
                      headers=_session_headers())
        assert resp.status_code == 200
        assert resp.get_json()["data"]["has_pin"] is True
        # Mints no token — the PIN set is not a session/mode change.
        assert "token" not in resp.get_json()["data"]
        assert svc.has_pin() is True

        status = c.get("/v1/auth/status").get_json()["data"]
        assert status["has_pin"] is True

        _enable_totp(svc)
        unlock = c.post("/v1/auth/pin", json={"pin": "654321"},
                        headers=_session_headers())
        assert unlock.status_code == 200
        data = unlock.get_json()["data"]
        assert data["mode"] == "live"
        assert data["live_mode_unlocked"] is True

    def test_set_pin_changes_existing_pin(self, client):
        c, svc = client
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        _enable_totp(svc)

        resp = c.post("/v1/auth/pin/set",
                      json={"password": "StrongP@ss123!", "pin": "999999"},
                      headers=_session_headers())
        assert resp.status_code == 200

        old = c.post("/v1/auth/pin", json={"pin": "123456"}, headers=_session_headers())
        assert old.status_code == 401
        new = c.post("/v1/auth/pin", json={"pin": "999999"}, headers=_session_headers())
        assert new.status_code == 200


class TestModeSwitchEndpoint:
    """POST /v1/auth/mode — downgrade live → practice + revoke prior JWT.

    Closes the 2026-05-19 Codex CRITICAL finding (UI mode toggle never
    invalidated the PIN-unlocked JWT). Upgrades must continue to go
    through /v1/auth/pin.
    """

    def _setup_and_pin_unlock(self, client):
        c, svc = client
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        _enable_totp(svc)
        pin_resp = c.post("/v1/auth/pin", json={"pin": "123456"},
                          headers=_session_headers())
        return pin_resp.get_json()["data"]["token"]

    def test_downgrade_to_practice_returns_fresh_token(self, client):
        c, _ = client
        live_token = self._setup_and_pin_unlock(client)

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
        live_token = self._setup_and_pin_unlock(client)

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
        live_token = self._setup_and_pin_unlock(client)

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
        live_token = self._setup_and_pin_unlock(client)

        with patch("flinttrade_core.auth_routes._revoke_jti") as mock_revoke:
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

    def test_downgrade_to_explore_returns_fresh_token(self, client):
        """Phase 1 G1: /auth/mode must also accept an 'explore' downgrade so
        a Practice/Live session flipping the UI to Explore keeps the JWT claim
        in lockstep instead of holding a higher-mode token.
        """
        c, _ = client
        live_token = self._setup_and_pin_unlock(client)

        resp = c.post(
            "/v1/auth/mode",
            json={"mode": "explore"},
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {live_token}",
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["mode"] == "explore"
        assert data["live_mode_unlocked"] is False
        assert data["token"] != live_token

    def test_downgrade_to_explore_revokes_prior_jwt(self, client):
        c, _ = client
        live_token = self._setup_and_pin_unlock(client)
        c.post(
            "/v1/auth/mode",
            json={"mode": "explore"},
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {live_token}",
            },
        )
        retry = c.post(
            "/v1/auth/mode",
            json={"mode": "explore"},
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {live_token}",
            },
        )
        assert retry.status_code == 401

    def test_downgrade_rejects_unknown_target(self, client):
        c, _ = client
        live_token = self._setup_and_pin_unlock(client)
        resp = c.post(
            "/v1/auth/mode",
            json={"mode": "live"},
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {live_token}",
            },
        )
        assert resp.status_code == 400


class TestPinModeParameter:
    """Phase 1 G2: /auth/pin takes an optional ``mode`` so the idle LockScreen
    can re-authenticate WITHOUT silently escalating an Explore/Practice session
    to a Live-unlocked JWT. Default (no mode) stays Live for the explicit
    arm-real-money callers.
    """

    def _setup(self, client, *, enable_totp: bool = False):
        c, svc = client
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        if enable_totp:
            _enable_totp(svc)
        return c

    def test_pin_default_mode_is_live(self, client):
        c = self._setup(client, enable_totp=True)
        resp = c.post("/v1/auth/pin", json={"pin": "123456"},
                      headers=_session_headers())
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["mode"] == "live"
        assert data["live_mode_unlocked"] is True

    def test_pin_practice_mode_does_not_unlock_live(self, client):
        c = self._setup(client)
        resp = c.post("/v1/auth/pin", json={"pin": "123456", "mode": "practice"},
                      headers=_session_headers())
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["mode"] == "practice"
        assert data["live_mode_unlocked"] is False

    def test_pin_explore_mode_does_not_unlock_live(self, client):
        c = self._setup(client)
        resp = c.post("/v1/auth/pin", json={"pin": "123456", "mode": "explore"},
                      headers=_session_headers())
        assert resp.status_code == 200
        data = resp.get_json()["data"]
        assert data["mode"] == "explore"
        assert data["live_mode_unlocked"] is False

    def test_pin_rejects_unknown_mode(self, client):
        c = self._setup(client)
        resp = c.post("/v1/auth/pin", json={"pin": "123456", "mode": "bogus"},
                      headers=_session_headers())
        assert resp.status_code == 400

    def test_pin_wrong_pin_still_401_with_mode(self, client):
        c = self._setup(client)
        resp = c.post("/v1/auth/pin", json={"pin": "000000", "mode": "practice"},
                      headers=_session_headers())
        assert resp.status_code == 401


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
        from flinttrade_core import auth_routes as mod

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
            "auth_totp_enable",
        ):
            assert required in names, (
                f"Auth view '{required}' is missing the @_rate_limit decorator — "
                "every public auth endpoint must be rate-limited."
            )


class TestPinIsSessionBound:
    """Policy D6 (Phase 1 review): the PIN is a RE-AUTH factor, never a
    session-minting factor — /v1/auth/pin without a valid session JWT is 401
    even with the correct PIN, so the daily password+TOTP login (the JWT's
    next-08:00-IST expiry) can never be sidestepped by a low-entropy PIN."""

    def _setup(self, c):
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})

    def test_correct_pin_without_session_is_rejected(self, client):
        c, _ = client
        self._setup(c)
        resp = c.post("/v1/auth/pin", json={"pin": "123456"},
                      headers={"Content-Type": "application/json"})
        assert resp.status_code == 401
        assert "sign in with password" in resp.get_json()["message"].lower()

    def test_correct_pin_with_garbage_session_is_rejected(self, client):
        c, _ = client
        self._setup(c)
        resp = c.post("/v1/auth/pin", json={"pin": "123456"},
                      headers={"Content-Type": "application/json",
                               "Authorization": "Bearer not-a-jwt"})
        assert resp.status_code == 401

    def test_correct_pin_with_revoked_session_is_rejected(self, client):
        c, _ = client
        self._setup(c)
        from flinttrade_core.auth_routes import _create_token, _revoke_jti, decode_token

        token = _create_token("nav", mode="explore")
        payload = decode_token(token)
        _revoke_jti(payload["jti"], float(payload["exp"]))
        resp = c.post("/v1/auth/pin", json={"pin": "123456"},
                      headers={"Content-Type": "application/json",
                               "Authorization": f"Bearer {token}"})
        assert resp.status_code == 401


class TestGuardsRejectResetTokens:
    """Audit finding (auth-bypass): a password-reset token (type='reset')
    proves only email possession and is exempt from the password-change kill
    switch, so it must NOT authorise broker-management writes (G9) or satisfy
    the D6 session requirement on /v1/auth/pin."""

    def _setup(self, c):
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})

    def test_reset_token_rejected_by_native_write_guard(self, client):
        c, _ = client
        self._setup(c)
        from flinttrade_core.auth_routes import _create_reset_token

        reset = _create_reset_token("nav")
        resp = c.post(
            "/api/v1/native/accounts",
            json={"adapter_id": "dhan", "account_id": "X", "credentials": {"access_token": "x"}},
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {reset}"},
        )
        assert resp.status_code == 401
        assert "full login session" in resp.get_json()["message"].lower()

    def test_reset_token_rejected_by_pin_unlock(self, client):
        c, _ = client
        self._setup(c)
        from flinttrade_core.auth_routes import _create_reset_token

        reset = _create_reset_token("nav")
        resp = c.post(
            "/v1/auth/pin", json={"pin": "123456"},
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {reset}"},
        )
        assert resp.status_code == 401
        assert "full login session" in resp.get_json()["message"].lower()


class TestSetupSessionReset:
    """FT-SETUP-001: Start over / Reset wipes an unfinished account.

    A valid setup session JWT is enough (lost QR seed). A password-reset
    token is never enough. Daily password+TOTP login and Live PIN are unchanged.
    """

    def _setup(self, c):
        return c.post("/v1/auth/setup", json={
            "username": "nav",
            "email": "nav@example.com",
            "password": "StrongP@ss123!",
            "pin": "123456",
        }, headers={"Content-Type": "application/json"})

    def test_session_reset_wipes_unfinished_account(self, client):
        c, svc = client
        created = self._setup(c)
        setup_token = created.get_json()["data"]["token"]
        resp = c.post(
            "/v1/auth/setup/reset",
            json={},
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {setup_token}"},
        )
        assert resp.status_code == 200
        assert svc.is_setup() is False

    def test_session_reset_rejects_ordinary_session_token(self, client):
        c, svc = client
        self._setup(c)
        resp = c.post(
            "/v1/auth/setup/reset",
            json={},
            headers=_session_headers(),
        )
        assert resp.status_code == 401
        assert svc.is_setup() is True

    def test_session_reset_rejects_stale_setup_token_after_recreate(self, client):
        c, svc = client
        first = self._setup(c)
        stale = first.get_json()["data"]["token"]
        assert svc.reset_account("StrongP@ss123!") is True
        second = c.post("/v1/auth/setup", json={
            "username": "bob",
            "email": "bob@example.com",
            "password": "AnotherP@ss123!",
            "pin": "654321",
        }, headers={"Content-Type": "application/json"})
        assert second.status_code == 201
        resp = c.post(
            "/v1/auth/setup/reset",
            json={},
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {stale}"},
        )
        assert resp.status_code == 401
        assert svc.is_setup() is True
        assert svc.get_profile()["username"] == "bob"

    def test_session_reset_rejects_reset_token(self, client):
        c, svc = client
        self._setup(c)
        from flinttrade_core.auth_routes import _create_reset_token
        reset = _create_reset_token("nav")
        resp = c.post(
            "/v1/auth/setup/reset",
            json={},
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {reset}"},
        )
        assert resp.status_code == 401
        assert svc.is_setup() is True


class TestSetupMintsSession:
    """Audit fix (#18/#19): /v1/auth/setup returns an explore-mode session token
    so the rest of the setup wizard (broker connect behind the G9 guard, mode
    select behind the D6 PIN) is authenticated. Non-live: arming Live still
    needs the PIN."""

    def test_setup_returns_explore_session_token(self, client):
        c, _ = client
        resp = c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})
        assert resp.status_code == 201
        data = resp.get_json()["data"]
        assert data["mode"] == "explore"
        from flinttrade_core.auth_routes import decode_token

        payload = decode_token(data["token"])
        assert payload["type"] == "session"
        assert payload["mode"] == "explore"
        assert payload["live_mode_unlocked"] is False
        assert payload["setup_session"] is True
        assert payload["setup_bound"]
        # And that token satisfies the G9 write guard (proves the wizard's
        # broker-connect step is authenticated).
        w = c.post(
            "/api/v1/native/accounts",
            json={"adapter_id": "dhan", "account_id": "X", "credentials": {"access_token": "x"}},
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {data['token']}"},
        )
        assert w.status_code != 401


class TestModeSwitchRejectsResetToken:
    """Re-audit fix #8: /v1/auth/mode must not mint a fresh session token from a
    reset token — that would launder email-possession into a full session that
    then satisfies the G9 write guard and the D6 PIN unlock."""

    def _setup(self, c):
        c.post("/v1/auth/setup", json={
            "username": "nav", "email": "nav@example.com",
            "password": "StrongP@ss123!", "pin": "123456",
        }, headers={"Content-Type": "application/json"})

    def test_reset_token_cannot_downgrade_mode(self, client):
        c, _ = client
        self._setup(c)
        from flinttrade_core.auth_routes import _create_reset_token

        reset = _create_reset_token("nav")
        resp = c.post(
            "/v1/auth/mode", json={"mode": "practice"},
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {reset}"},
        )
        assert resp.status_code == 401
        assert "full login session" in resp.get_json()["message"].lower()

    def test_session_token_can_still_downgrade(self, client):
        c, _ = client
        self._setup(c)
        from flinttrade_core.auth_routes import _create_token

        token = _create_token("nav", mode="live", live_mode_unlocked=True)
        resp = c.post(
            "/v1/auth/mode", json={"mode": "practice"},
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["data"]["mode"] == "practice"


def test_verified_operator_session_derives_bounded_opaque_identity_without_raw_claims(monkeypatch):
    """Catch raw username/JTI publication or actor/session domain reuse."""
    from types import SimpleNamespace
    from flinttrade_core import auth_routes

    monkeypatch.setattr(
        auth_routes,
        "_decode_token_with_signing_key",
        lambda token, signing_key: {
            "type": "session",
            "sub": "Nava+நவ",
            "jti": "private-jti",
            "scopes": ["admin.services.read", "admin.services.write"],
        },
    )
    monkeypatch.setattr(auth_routes, "_get_jwt_secret", lambda: "test-signing-key")
    verify = getattr(auth_routes, "verify_operator_session_token", lambda token: SimpleNamespace())
    principal = verify("signed.jwt.value")

    assert principal.actor_ref == "operator:685a1f30a3b5970c37588cb9d3b852415558a0026182484c35c400faba4c3aa7"
    assert principal.session_binding == "session:a431817ca10eb3719e198fb8df304b0ec9ed0365fc1a7e0185dea48e9cc2c485"
    assert principal.scopes == ("admin.services.read", "admin.services.write")
    assert not hasattr(principal, "claims")
    assert not hasattr(principal, "jti")
    assert not hasattr(principal, "token")


@pytest.mark.parametrize(
    "claims",
    [
        {"type": "reset", "sub": "nav", "jti": "j1"},
        {"type": "session", "sub": " ", "jti": "j1"},
        {"type": "session", "sub": "nav", "jti": ""},
        {"type": "session", "sub": "x" * 1025, "jti": "j1"},
        {"type": "session", "sub": "nav", "jti": "x" * 257},
    ],
)
def test_verified_operator_session_rejects_non_full_or_invalid_identity(monkeypatch, claims):
    """Catch reset or malformed signed identity becoming a connection principal."""
    from flinttrade_core import auth_routes

    monkeypatch.setattr(auth_routes, "_decode_token_with_signing_key", lambda token, signing_key: claims)
    verify = getattr(auth_routes, "verify_operator_session_token", lambda token: None)
    with pytest.raises(Exception):
        verify("signed.jwt.value")
