"""Regression tests for ``flinttrade_engine.mode_guard``.

Covers both decorators end-to-end against a real Flask app with
``TESTING=False`` so the JWT decode path is exercised:

- :func:`require_non_explore` — explore/missing → 403, practice/live → pass
- :func:`require_live_unlocked` — full explore/practice/live × locked/unlocked
  fan-out matching :func:`flinttrade_core.order_routes._dispatch_order`.

These tests are the regression guard for the 2026-05-19 Codex stop-gate
finding ("advanced order routing is not mode-safe"): basket/split/
options-strategy/bracket execute orders directly via FT executors that
bypass ``orders_bp``, so they need the strict guard rather than
``require_non_explore``.
"""

from __future__ import annotations

import pytest
from flask import Flask, jsonify

import flinttrade_engine.mode_guard as mg
from flinttrade_core.auth_routes import _create_token


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app(monkeypatch, tmp_path) -> Flask:
    """A minimal Flask app with two test routes — one per decorator.

    ``TESTING`` is False so decorators apply their real logic. The JWT
    secret is forced to a deterministic value so ``_create_token`` and
    ``decode_token`` agree even across import order quirks.
    """
    # Pin JWT secret so token creation/decoding stays in sync regardless of
    # whether a previous test has touched the cached module-level secret.
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-mode-guard-hs256")
    import flinttrade_core.auth_routes as auth_mod
    monkeypatch.setattr(auth_mod, "_JWT_SECRET_KEY", "test-secret-for-mode-guard-hs256")

    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = False  # MUST be False to exercise the guard

    @flask_app.route("/test/non-explore", methods=["POST"])
    @mg.require_non_explore
    def _non_explore_route():
        return jsonify({"status": "success", "passed": True}), 200

    @flask_app.route("/test/live-unlocked", methods=["POST"])
    @mg.require_live_unlocked
    def _live_unlocked_route():
        return jsonify({"status": "success", "passed": True}), 200

    return flask_app


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# require_non_explore — original behaviour preserved
# ---------------------------------------------------------------------------


def test_non_explore_no_token_rejected(app):
    """No JWT → 403."""
    with app.test_client() as c:
        resp = c.post("/test/non-explore")
    assert resp.status_code == 403
    assert resp.get_json()["code"] == "mode_blocked"


def test_non_explore_invalid_token_rejected(app):
    """Garbage JWT → 403."""
    with app.test_client() as c:
        resp = c.post("/test/non-explore", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 403


def test_non_explore_explore_mode_rejected(app):
    """Valid JWT with mode=explore → 403."""
    tok = _create_token("alice", mode="explore")
    with app.test_client() as c:
        resp = c.post("/test/non-explore", headers=_bearer(tok))
    assert resp.status_code == 403
    assert resp.get_json()["code"] == "mode_blocked"


def test_non_explore_practice_mode_passes(app):
    """Valid JWT with mode=practice → view executes."""
    tok = _create_token("alice", mode="practice")
    with app.test_client() as c:
        resp = c.post("/test/non-explore", headers=_bearer(tok))
    assert resp.status_code == 200
    assert resp.get_json()["passed"] is True


def test_non_explore_live_mode_passes(app):
    """Valid JWT with mode=live → view executes (live_mode_unlocked irrelevant for this guard)."""
    tok = _create_token("alice", mode="live", live_mode_unlocked=False)
    with app.test_client() as c:
        resp = c.post("/test/non-explore", headers=_bearer(tok))
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# require_live_unlocked — the new strict guard
# ---------------------------------------------------------------------------


def test_live_unlocked_no_token_returns_401(app):
    """Missing JWT → 401 ``auth_required`` (not 403)."""
    with app.test_client() as c:
        resp = c.post("/test/live-unlocked")
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "auth_required"


def test_live_unlocked_invalid_token_returns_401(app):
    """Garbage JWT → 401."""
    with app.test_client() as c:
        resp = c.post("/test/live-unlocked", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


def test_live_unlocked_explore_mode_returns_403_blocked(app):
    """mode=explore → 403 ``mode_blocked``."""
    tok = _create_token("alice", mode="explore")
    with app.test_client() as c:
        resp = c.post("/test/live-unlocked", headers=_bearer(tok))
    assert resp.status_code == 403
    assert resp.get_json()["code"] == "mode_blocked"


def test_live_unlocked_practice_mode_returns_403_unsupported(app):
    """mode=practice → 403 ``practice_unsupported`` (executors lack sandbox parity)."""
    tok = _create_token("alice", mode="practice")
    with app.test_client() as c:
        resp = c.post("/test/live-unlocked", headers=_bearer(tok))
    assert resp.status_code == 403
    assert resp.get_json()["code"] == "practice_unsupported"


def test_live_unlocked_live_mode_locked_returns_403_locked(app):
    """mode=live without live_mode_unlocked → 403 ``live_locked`` (PIN re-verify)."""
    tok = _create_token("alice", mode="live", live_mode_unlocked=False)
    with app.test_client() as c:
        resp = c.post("/test/live-unlocked", headers=_bearer(tok))
    assert resp.status_code == 403
    assert resp.get_json()["code"] == "live_locked"


def test_live_unlocked_live_mode_unlocked_passes(app):
    """mode=live with live_mode_unlocked=True → view executes."""
    tok = _create_token("alice", mode="live", live_mode_unlocked=True)
    with app.test_client() as c:
        resp = c.post("/test/live-unlocked", headers=_bearer(tok))
    assert resp.status_code == 200
    assert resp.get_json()["passed"] is True


def test_live_unlocked_via_x_flinttrade_token_header(app):
    """``X-FlintTrade-Token`` header is honoured as a fallback."""
    tok = _create_token("alice", mode="live", live_mode_unlocked=True)
    with app.test_client() as c:
        resp = c.post(
            "/test/live-unlocked",
            headers={"X-FlintTrade-Token": tok},
        )
    assert resp.status_code == 200


def test_live_unlocked_unknown_mode_returns_400(app, monkeypatch):
    """Unknown mode value in JWT → 400 ``mode_invalid``."""
    # Bypass _create_token's parameter typing so we can inject an
    # unrecognised mode and confirm the decorator's invalid-mode branch.
    import jwt as pyjwt
    payload = {
        "sub": "alice",
        "type": "session",
        "jti": "abc123",
        "live_mode_unlocked": False,
        "mode": "rogue_mode",
        # No exp = decode treats as missing → jwt may still decode if
        # require_exp isn't set. Include a far-future exp for safety.
        "exp": 9999999999,
    }
    tok = pyjwt.encode(payload, "test-secret-for-mode-guard-hs256", algorithm="HS256")
    with app.test_client() as c:
        resp = c.post("/test/live-unlocked", headers=_bearer(tok))
    assert resp.status_code == 400
    assert resp.get_json()["code"] == "mode_invalid"


# ---------------------------------------------------------------------------
# TESTING=True bypass — preserved so existing route tests stay green
# ---------------------------------------------------------------------------


def test_live_unlocked_testing_bypass(app):
    """When ``TESTING`` is True, the guard short-circuits to the view."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.post("/test/live-unlocked")  # no JWT, no headers
    assert resp.status_code == 200
    assert resp.get_json()["passed"] is True


def test_non_explore_testing_bypass(app):
    """``require_non_explore`` also honours TESTING=True for unit tests."""
    app.config["TESTING"] = True
    with app.test_client() as c:
        resp = c.post("/test/non-explore")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# current_mode public helper
# ---------------------------------------------------------------------------


def test_current_mode_returns_jwt_mode(app):
    """``current_mode()`` returns the JWT mode claim when called inside a request."""
    tok = _create_token("alice", mode="practice")
    seen: dict[str, str | None] = {}

    @app.route("/inspect-mode", methods=["GET"])
    def _inspect():
        seen["mode"] = mg.current_mode()
        return jsonify({})

    with app.test_client() as c:
        c.get("/inspect-mode", headers=_bearer(tok))
    assert seen["mode"] == "practice"


def test_current_mode_returns_none_without_token(app):
    """``current_mode()`` returns ``None`` when no token is present."""
    seen: dict[str, str | None] = {}

    @app.route("/inspect-none", methods=["GET"])
    def _inspect():
        seen["mode"] = mg.current_mode()
        return jsonify({})

    with app.test_client() as c:
        c.get("/inspect-none")
    assert seen["mode"] is None
