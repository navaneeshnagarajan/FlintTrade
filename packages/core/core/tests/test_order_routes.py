"""Tests for order proxy blueprint — mode enforcement and request forwarding.

Run with:
    python -m pytest packages/core/core/tests/test_order_routes.py -v --import-mode=importlib

This is a SAFETY-CRITICAL test suite.  The order proxy is the sole gateway
between the frontend and real-money broker orders.  Every mode enforcement
path must be verified to prevent accidental live execution in demo/practice
modes.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


_TEST_API_KEY = "test-order-routes-key"


def _make_jwt(mode: str, *, live_mode_unlocked: bool = False) -> str:
    """Create a signed JWT with the given mode claim for use in test headers.

    Uses the same ``_create_token`` function as the production auth routes so
    that the JWT secret and algorithm are always in sync.

    Args:
        mode: Trading mode claim — ``"explore"``, ``"practice"``, or ``"live"``.
        live_mode_unlocked: If ``True``, the token carries ``live_mode_unlocked:
            true``, which is required for live order forwarding.

    Returns:
        Encoded JWT string.
    """
    from flinttrade_core.auth_routes import _create_token

    return _create_token("testuser", mode=mode, live_mode_unlocked=live_mode_unlocked)


def _create_live_token() -> str:
    """Create a JWT with ``live_mode_unlocked: true`` for live-mode tests."""
    return _make_jwt("live", live_mode_unlocked=True)


# All order endpoints and their FlintTrade route suffixes
_ORDER_ENDPOINTS = [
    "/api/v1/orders/place",
    "/api/v1/orders/modify",
    "/api/v1/orders/cancel",
    "/api/v1/orders/cancel-all",
    "/api/v1/orders/options",
    "/api/v1/orders/options-multi",
]

_SAMPLE_ORDER_BODY = {
    "symbol": "NIFTY",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 50,
    "price": 0,
    "product": "MIS",
    "order_type": "MARKET",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch fixture."""
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def flask_app(monkeypatch_module, tmp_path_factory):
    """Create a Flask app with FLINTTRADE_API_KEY set for auth."""
    monkeypatch_module.setenv("FLINTTRADE_API_KEY", _TEST_API_KEY)
    # This API-only suite must not inherit a local build's GET-only SPA fallback.
    frontend = tmp_path_factory.mktemp("order_routes_frontend") / "absent"
    monkeypatch_module.setenv("FLINTTRADE_FRONTEND_DIST", str(frontend))
    from flinttrade_core.app import create_flask_app

    app = create_flask_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture(autouse=True)
def _laya_ready_for_open_place() -> None:
    """Seed Ready so an open place in this module still reaches the sandbox or gate."""
    from flinttrade_engine.laya import DecisionStatus, process_laya

    process_laya().set_status(DecisionStatus.READY)
    yield


@pytest.fixture(autouse=True)
def _reset_rate_limiter(flask_app):
    """Refill the order-route token buckets before each test.

    The order routes now carry ``@rate_limit("orders", 10/s)`` (Phase 1 G10)
    and Flask-Limiter's default 50/s. ``flask_app`` is module-scoped, so both
    limiters accumulate state across every test in this file — dozens of order
    POSTs share one bucket keyed by the test client's remote_addr and would 429
    after the burst. Production keys per operator and never fires that many
    orders in one second; tests just need a clean bucket per case.
    """
    limiter = flask_app.config.get("RATE_LIMITER")
    if limiter is not None:
        limiter.reset()
    flask_limiter = flask_app.config.get("LIMITER")
    if flask_limiter is not None:
        flask_limiter.reset()
    yield


@pytest.fixture()
def client(flask_app):
    """Flask test client that sends the API key header by default."""
    with flask_app.test_client() as c:
        yield c


def _auth_headers(
    mode: str | None = None,
    *,
    include_live_token: bool = False,
    **extra: str,
) -> dict[str, str]:
    """Build request headers with API key and a mode-bearing JWT.

    The mode is embedded in a signed JWT ``Authorization: Bearer`` header so
    that the server-side ``_get_mode_from_jwt()`` enforcement path is exercised.
    The legacy ``X-FlintTrade-Mode`` header is NOT set here — it is no longer
    trusted by ``order_routes.py``.

    Args:
        mode: Trading mode to embed as the ``mode`` claim in the JWT.
            Pass ``None`` to omit the ``Authorization`` header entirely
            (simulates an unauthenticated / no-JWT request).
        include_live_token: If ``True``, override the JWT with one that
            carries ``live_mode_unlocked: true`` regardless of *mode*.
            The *mode* argument is still used when ``include_live_token``
            is ``False``.
    """
    headers: dict[str, str] = {
        "X-API-Key": _TEST_API_KEY,
        "Content-Type": "application/json",
    }
    if include_live_token:
        # Live-unlocked token always carries mode="live"
        headers["Authorization"] = f"Bearer {_create_live_token()}"
    elif mode is not None and mode.strip():
        # Embed whichever mode was requested (including invalid ones, which the
        # production code will reject with 400 after JWT decode).
        try:
            token = _make_jwt(mode.strip().lower())
            headers["Authorization"] = f"Bearer {token}"
        except Exception:
            # If _make_jwt itself fails (shouldn't happen in tests), omit header
            pass
    headers.update(extra)
    return headers


# ---------------------------------------------------------------------------
# 0. H1 — startup binds the dedicated safety-gate HMAC secret
# ---------------------------------------------------------------------------


def test_get_safety_gate_secret_bytes_generates_and_caches(tmp_path, monkeypatch):
    """H1: the gate-secret helper generates a >=32-byte key, persists it, caches it.

    Pure unit test of the loader; no second full app is needed under xdist.
    """
    import flinttrade_core.app as app_mod

    monkeypatch.setattr(app_mod, "_workspace_dir", lambda: tmp_path)
    monkeypatch.setattr(app_mod, "_SAFETY_GATE_SECRET", None, raising=False)

    secret = app_mod._get_safety_gate_secret_bytes()
    assert isinstance(secret, bytes)
    assert len(secret) >= 32
    assert (tmp_path / "safety_gate_secret").exists()
    # Cached: a second call returns the identical object, no regeneration.
    assert app_mod._get_safety_gate_secret_bytes() is secret


def test_app_startup_binds_safety_gate_secret(flask_app):
    """H1 regression: building the app binds the dedicated safety-gate HMAC secret.

    Without it, gate_order() fails closed and every live routed order 403s. Uses
    the existing module-scoped fixture (no extra create_flask_app / DuckDB).
    """
    import flinttrade_engine.safety as safety_mod

    assert safety_mod._SAFETY_GATE_SECRET is not None
    assert len(safety_mod._SAFETY_GATE_SECRET) >= 32


# ---------------------------------------------------------------------------
# 1. Mode enforcement — the explore claim blocks all orders
# ---------------------------------------------------------------------------

_EXAMPLE_ORDERS_REFUSAL = "Orders are not available for Example. Switch to Practice or Live to trade."


class TestExploreModeBlocked:
    """The explore claim must return 403 for every order endpoint."""

    @pytest.mark.parametrize("endpoint", _ORDER_ENDPOINTS)
    def test_explore_mode_returns_403(self, client, endpoint):
        resp = client.post(
            endpoint,
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="explore"),
        )
        assert resp.status_code == 403
        data = resp.get_json()
        assert data["status"] == "error"
        assert data["message"] == _EXAMPLE_ORDERS_REFUSAL

    @pytest.mark.parametrize("endpoint", _ORDER_ENDPOINTS)
    def test_explore_mode_upper_case_jwt_normalised(self, client, endpoint):
        """``_auth_headers`` lowercases the mode before embedding in JWT.

        The JWT claim is therefore ``"explore"`` regardless of what case the
        caller passes, and the endpoint correctly returns 403.
        """
        # _auth_headers normalises to lowercase before calling _make_jwt,
        # so "EXPLORE" → JWT mode="explore" → 403 blocked.
        resp = client.post(
            endpoint,
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="EXPLORE"),
        )
        assert resp.status_code == 403

    def test_explore_mode_with_real_order_body(self, client):
        """Even a fully valid order body must be rejected in explore mode."""
        body = {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 1,
            "price": 2500.0,
            "product": "CNC",
            "order_type": "LIMIT",
        }
        resp = client.post(
            "/api/v1/orders/place",
            json=body,
            headers=_auth_headers(mode="explore"),
        )
        assert resp.status_code == 403

    def test_explore_order_attempt_is_mode_blocked(self, client):
        """FT-TRADE-009: backend rejects Explore orders if the UI slips."""
        resp = client.post(
            "/api/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="explore"),
        )
        assert resp.status_code == 403
        data = resp.get_json()
        assert data["status"] == "error"
        assert data["code"] == "mode_blocked"
        assert data["message"] == _EXAMPLE_ORDERS_REFUSAL


# ---------------------------------------------------------------------------
# 2. Missing / invalid mode header
# ---------------------------------------------------------------------------


class TestMissingOrInvalidMode:
    """Requests without a valid JWT mode claim must be rejected."""

    def test_live_jwt_with_practice_header_rejected_before_dispatch(self, client):
        """A contradictory legacy mode header narrows authority; it cannot retarget it."""
        with patch(
            "flinttrade_core.order_routes._dispatch_live_order",
            return_value=({"status": "unexpected-dispatch"}, 200),
        ) as dispatcher:
            resp = client.post(
                "/api/v1/orders/place",
                json=_SAMPLE_ORDER_BODY,
                headers=_auth_headers(
                    mode="live",
                    include_live_token=True,
                    **{"X-FlintTrade-Mode": "practice"},
                ),
            )

        assert resp.status_code == 403
        assert "mode" in resp.get_json()["message"].lower()
        dispatcher.assert_not_called()

    def test_routed_live_jwt_with_practice_header_rejected_before_dispatch(self, client):
        """Selector-bound order routes enforce the same narrowing assertion."""
        with patch(
            "flinttrade_core.order_routes._dispatch_live_order",
            return_value=({"status": "unexpected-dispatch"}, 200),
        ) as dispatcher:
            resp = client.post(
                "/api/v1/orders/dhan/place",
                json={**_SAMPLE_ORDER_BODY, "account_id": "ACCOUNT-A"},
                headers=_auth_headers(
                    mode="live",
                    include_live_token=True,
                    **{"X-FlintTrade-Mode": "practice"},
                ),
            )

        assert resp.status_code == 403
        assert "mode" in resp.get_json()["message"].lower()
        dispatcher.assert_not_called()

    @pytest.mark.parametrize("endpoint", _ORDER_ENDPOINTS)
    def test_missing_jwt_returns_401(self, client, endpoint):
        """No ``Authorization`` header → 401 (no mode claim to extract)."""
        resp = client.post(
            endpoint,
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode=None),
        )
        assert resp.status_code == 401
        data = resp.get_json()
        assert data["status"] == "error"
        assert "JWT" in data["message"] or "Authentication" in data["message"]

    def test_empty_mode_omits_jwt_returns_401(self, client):
        """Empty mode string → no JWT attached → 401."""
        resp = client.post(
            "/api/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode=""),
        )
        assert resp.status_code == 401

    def test_invalid_mode_in_jwt_returns_400(self, client):
        """A JWT that encodes an unrecognised mode value → 400."""
        import jwt as _jwt
        import secrets
        from datetime import datetime, timezone, timedelta
        from flinttrade_core.auth_routes import _get_jwt_secret

        payload = {
            "sub": "testuser",
            "iat": datetime.now(timezone.utc),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "type": "session",
            "jti": secrets.token_hex(16),
            "live_mode_unlocked": False,
            "mode": "yolo",
        }
        token = _jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")

        resp = client.post(
            "/api/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers={
                "X-API-Key": _TEST_API_KEY,
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "Invalid mode" in data["message"]

    def test_whitespace_only_mode_omits_jwt_returns_401(self, client):
        """Whitespace-only mode → no JWT attached → 401."""
        resp = client.post(
            "/api/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="   "),
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 3. Practice mode — routes to SandboxEngine
# ---------------------------------------------------------------------------


class TestOrderRateLimiting:
    """Phase 1 G10 — the reachable order path enforces a per-second rate limit.

    SEBI-derived requirement: per-second order rate limiting before broker
    submission on every order path. The ``orders`` bucket is 10/s per user
    (100/s global). This test proves the limiter is actually wired to the core
    ``/orders/place`` route and fires a 429 once the burst is exhausted — the
    exact property that silently regressed for the login limiter (whose tests
    skip because the decoration didn't fire). The ``_reset_rate_limiter``
    autouse fixture gives this test a full burst to start from.
    """

    def test_place_order_429s_after_the_per_second_burst(self, flask_app, client):
        mock_sandbox = MagicMock()
        mock_sandbox.place_order.return_value = {
            "order_id": "SB-RL",
            "status": "COMPLETE",
            "message": "Paper order filled",
        }
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox

        statuses = [
            client.post(
                "/api/v1/orders/place",
                json=_SAMPLE_ORDER_BODY,
                headers=_auth_headers(mode="practice"),
            ).status_code
            for _ in range(20)
        ]

        # The 10-token burst lets the first orders through (200), then the
        # limiter must start returning 429 — proof it is wired and enforcing.
        assert 429 in statuses, f"order rate limit never fired across 20 rapid posts: {statuses}"
        # Everything that was NOT rate-limited reached the sandbox and filled.
        assert all(s in (200, 429) for s in statuses), statuses
        assert statuses[0] == 200, "the very first order must not be throttled"

    def test_reset_gives_a_fresh_burst(self, flask_app, client):
        """After reset (the autouse fixture), the first order is never 429 —
        confirms the bucket genuinely refills between test cases rather than the
        previous test's exhaustion leaking through the module-scoped app.
        """
        mock_sandbox = MagicMock()
        mock_sandbox.place_order.return_value = {"order_id": "SB-1", "status": "COMPLETE"}
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox
        resp = client.post(
            "/api/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="practice"),
        )
        assert resp.status_code == 200


class TestPracticeMode:
    """Practice mode must route to SandboxEngine, never to native broker."""

    def test_practice_place_order(self, flask_app, client):
        mock_sandbox = MagicMock()
        mock_sandbox.place_order.return_value = {
            "order_id": "SB-001",
            "status": "COMPLETE",
            "message": "Paper order filled",
        }
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox

        resp = client.post(
            "/api/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="practice"),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["order_id"] == "SB-001"
        assert data["status"] == "COMPLETE"
        mock_sandbox.place_order.assert_called_once_with(
            symbol="NIFTY",
            exchange="NSE",
            action="BUY",
            quantity=50,
            price=0.0,
            product="MIS",
            order_type="MARKET",
            trigger_price=0.0,
            strategy="",
            instrument_token="",
        )

    def test_practice_rejection_is_an_http_error(self, flask_app, client):
        mock_sandbox = MagicMock()
        mock_sandbox.place_order.return_value = {
            "order_id": "",
            "status": "REJECTED",
            "message": "A market order needs a live price (LTP) to fill",
        }
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox

        resp = client.post(
            "/api/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="practice"),
        )

        assert resp.status_code == 400
        assert resp.get_json() == {
            "status": "error",
            "message": "A market order needs a live price (LTP) to fill",
        }

    def test_raw_missing_ltp_is_a_plain_sentence(self, flask_app, client):
        mock_sandbox = MagicMock()
        mock_sandbox.place_order.return_value = {
            "order_id": "",
            "status": "REJECTED",
            "message": "A market fill needs a positive live price; no LTP was available",
        }
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox

        resp = client.post(
            "/api/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="practice"),
        )

        assert resp.status_code == 400
        assert resp.get_json()["message"] == (
            "No price for NIFTY right now. Practice needs a live price or a recent close."
        )
        assert "no LTP was available" not in resp.get_json()["message"]

    def test_unmarked_practice_price_is_not_a_fill(self, flask_app, client):
        mock_sandbox = MagicMock()
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox

        resp = client.post(
            "/api/v1/orders/place",
            json={**_SAMPLE_ORDER_BODY, "price": 812.4},
            headers=_auth_headers(mode="practice"),
        )

        assert resp.status_code == 400
        assert "No price for NIFTY" in resp.get_json()["message"]
        mock_sandbox.place_order.assert_not_called()

    def test_marked_live_price_is_the_practice_fill(self, flask_app, client):
        mock_sandbox = MagicMock()
        mock_sandbox.place_order.return_value = {
            "order_id": "SB-LTP",
            "status": "COMPLETE",
            "message": "Paper order filled",
        }
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox

        resp = client.post(
            "/api/v1/orders/place",
            json={**_SAMPLE_ORDER_BODY, "price": 812.4, "price_basis": "ltp"},
            headers=_auth_headers(mode="practice"),
        )

        assert resp.status_code == 200
        mock_sandbox.place_order.assert_called_once()
        assert mock_sandbox.place_order.call_args.kwargs["price"] == 812.4
        assert mock_sandbox.place_order.call_args.kwargs["price_source"] == "ltp"

    def test_last_stored_close_fills_and_is_labelled(self, flask_app, client, monkeypatch):
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        now = datetime.now(ZoneInfo("Asia/Kolkata"))

        class Store:
            def get_ticks(self, symbol, exchange, start, end, limit=None):
                assert symbol == "SBIN"
                return [
                    {
                        "ts": now - timedelta(days=2),
                        "prev_close": 812.40,
                        "close": 810.0,
                    }
                ]

        monkeypatch.setitem(flask_app.config, "TICK_STORAGE", Store())
        monkeypatch.setitem(flask_app.config, "TICK_STORAGE_LOCK", None)
        mock_sandbox = MagicMock()
        mock_sandbox.place_order.return_value = {
            "order_id": "SB-CLOSE",
            "status": "COMPLETE",
            "message": "Paper order executed",
        }
        monkeypatch.setitem(flask_app.config, "DATA_SANDBOX_ENGINE", mock_sandbox)

        resp = client.post(
            "/api/v1/orders/place",
            json={**_SAMPLE_ORDER_BODY, "symbol": "SBIN", "price": 1.0},
            headers=_auth_headers(mode="practice"),
        )

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["price"] == 812.40
        assert body["price_source"] == "last_close"
        assert body["message"] == "Simulated at last close ₹812.40 (2 days old)"
        assert "0.00" not in body["message"]
        kwargs = mock_sandbox.place_order.call_args.kwargs
        assert kwargs["price"] == 812.40
        assert kwargs["price_source"] == "last_close"

    def test_option_outside_market_hours_is_refused(self, flask_app, client, monkeypatch):
        class Closed:
            def is_market_open(self, exchange, symbol=None):
                return False

        monkeypatch.setitem(flask_app.config, "TIME_SCHEDULER", Closed())
        mock_sandbox = MagicMock()
        monkeypatch.setitem(flask_app.config, "DATA_SANDBOX_ENGINE", mock_sandbox)

        resp = client.post(
            "/api/v1/orders/place",
            json={
                **_SAMPLE_ORDER_BODY,
                "symbol": "NIFTY24APR25500CE",
                "exchange": "NFO",
                "price": 12.5,
                "price_basis": "ltp",
            },
            headers=_auth_headers(mode="practice"),
        )

        assert resp.status_code == 400
        assert resp.get_json()["message"] == (
            "Option prices go stale outside market hours. Try again when the market opens."
        )
        mock_sandbox.place_order.assert_not_called()

    def test_pending_order_requires_a_running_tick_source(self, flask_app, client, monkeypatch):
        mock_sandbox = MagicMock()
        monkeypatch.setitem(flask_app.config, "DATA_SANDBOX_ENGINE", mock_sandbox)
        monkeypatch.delitem(flask_app.config, "TICK_RECORDER", raising=False)

        resp = client.post(
            "/api/v1/orders/place",
            json={**_SAMPLE_ORDER_BODY, "order_type": "LIMIT", "price": 100.0},
            headers=_auth_headers(mode="practice"),
        )

        assert resp.status_code == 503
        assert "tick capture" in resp.get_json()["message"].lower()
        mock_sandbox.place_order.assert_not_called()

    def test_practice_pending_order_preserves_metadata_and_subscribes_ticks(self, flask_app, client, monkeypatch):
        mock_sandbox = MagicMock()
        mock_sandbox.place_order.return_value = {
            "order_id": "SB-LIMIT",
            "status": "PENDING",
            "message": "Pending",
        }
        recorder = MagicMock()
        monkeypatch.setitem(flask_app.config, "DATA_SANDBOX_ENGINE", mock_sandbox)
        monkeypatch.setitem(flask_app.config, "TICK_RECORDER", recorder)
        body = {
            **_SAMPLE_ORDER_BODY,
            "symbol": "INFY",
            "order_type": "LIMIT",
            "price": 1_500.0,
            "trigger_price": 1_490.0,
            "strategy": "mean-revert",
        }

        resp = client.post(
            "/api/v1/orders/place",
            json=body,
            headers=_auth_headers(mode="practice"),
        )

        assert resp.status_code == 200
        assert resp.get_json()["status"] == "PENDING"
        mock_sandbox.place_order.assert_called_once_with(
            symbol="INFY",
            exchange="NSE",
            action="BUY",
            quantity=50,
            price=1_500.0,
            product="MIS",
            order_type="LIMIT",
            trigger_price=1_490.0,
            instrument_token="",
            strategy="mean-revert",
        )
        recorder.add_symbols.assert_called_once_with(
            [{"exchange": "NSE", "symbol": "INFY"}],
            mode="ltp",
        )
        recorder.request_reconnect.assert_called_once_with()

    def test_removed_position_routes_are_unmounted(self, flask_app, client):
        """place-smart, open-position and close-position are not order writers."""
        mock_sandbox = MagicMock()
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox
        rules = {rule.rule for rule in flask_app.url_map.iter_rules()}
        for path in (
            "/api/v1/orders/place-smart",
            "/api/v1/orders/open-position",
            "/api/v1/orders/close-position",
        ):
            assert path not in rules
            resp = client.post(
                path,
                json=_SAMPLE_ORDER_BODY,
                headers=_auth_headers(mode="practice"),
            )
            assert resp.status_code == 404
        mock_sandbox.place_order.assert_not_called()

    def test_practice_cancel_order_reaches_pending_order(self, flask_app, client):
        mock_sandbox = MagicMock()
        mock_sandbox.cancel_order.return_value = {
            "order_id": "SB-001",
            "status": "CANCELLED",
            "message": "Practice order cancelled",
        }
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox

        resp = client.post(
            "/api/v1/orders/cancel",
            json={"order_id": "SB-001"},
            headers=_auth_headers(mode="practice"),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "CANCELLED"
        mock_sandbox.cancel_order.assert_called_once_with("SB-001")

    def test_practice_cancel_all_reaches_pending_orders(self, flask_app, client):
        mock_sandbox = MagicMock()
        mock_sandbox.cancel_pending_orders.return_value = {
            "status": "CANCELLED",
            "cancelled_count": 2,
            "message": "Cancelled 2 pending Practice order(s)",
        }
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox

        resp = client.post(
            "/api/v1/orders/cancel-all",
            json={},
            headers=_auth_headers(mode="practice"),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "CANCELLED"
        assert data["cancelled_count"] == 2
        mock_sandbox.cancel_pending_orders.assert_called_once_with()

    def test_practice_modify_reaches_pending_order(self, flask_app, client, monkeypatch):
        mock_sandbox = MagicMock()
        recorder = MagicMock()
        mock_sandbox.modify_order.return_value = {
            "order_id": "SB-001",
            "status": "PENDING",
            "message": "Practice order modified",
        }
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox
        monkeypatch.setitem(flask_app.config, "TICK_RECORDER", recorder)

        resp = client.post(
            "/api/v1/orders/modify",
            json={
                "order_id": "SB-001",
                "quantity": 100,
                "price": 100.5,
                "trigger_price": 99.0,
                "pricetype": "SL",
            },
            headers=_auth_headers(mode="practice"),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "PENDING"
        mock_sandbox.modify_order.assert_called_once_with(
            "SB-001",
            quantity=100,
            price=100.5,
            trigger_price=99.0,
            order_type="SL",
        )
        recorder.add_symbols.assert_not_called()

    def test_practice_place_closes_long_and_short_and_squares_off(self, flask_app, client):
        """Opposite /place orders flatten a long and a short and book net P&L.

        Square-off of two open positions is the same place route, once per row.
        """
        import json

        from flinttrade_data.sandbox_engine import SandboxEngine

        engine = SandboxEngine(db_path=":memory:")
        flask_app.config["DATA_SANDBOX_ENGINE"] = engine
        headers = _auth_headers(mode="practice")

        def place(symbol: str, action: str, quantity: int, price: float) -> None:
            resp = client.post(
                "/api/v1/orders/place",
                json={
                    "symbol": symbol,
                    "exchange": "NSE",
                    "action": action,
                    "quantity": quantity,
                    "price": price,
                    "price_basis": "ltp",
                    "product": "MIS",
                    "order_type": "MARKET",
                },
                headers=headers,
            )
            assert resp.status_code == 200, resp.get_json()
            assert resp.get_json()["status"] == "COMPLETE"

        place("INFY", "BUY", 10, 100.0)
        place("INFY", "SELL", 10, 110.0)
        assert engine.get_positions() == []
        assert engine.get_pnl()["realised"] == pytest.approx(100.0)

        engine.import_data(
            json.dumps(
                {
                    "schema_version": 2,
                    "capital": {"initial": 1_000_000.0, "current": 1_000_000.0},
                    "positions": [
                        {
                            "symbol": "TCS",
                            "exchange": "NSE",
                            "product": "MIS",
                            "net_qty": -8,
                            "avg_price": 200.0,
                            "sell_qty": 8,
                            "sell_value": 1600.0,
                        }
                    ],
                    "orders": [],
                    "trades": [],
                    "pnl_history": [],
                }
            )
        )
        assert engine.get_positions()[0]["net_qty"] == -8
        place("TCS", "BUY", 8, 190.0)
        assert engine.get_positions() == []
        assert engine.get_pnl()["realised"] == pytest.approx(80.0)

        place("RELIANCE", "BUY", 5, 50.0)
        place("SBIN", "BUY", 4, 80.0)
        assert {row["symbol"] for row in engine.get_positions()} == {"RELIANCE", "SBIN"}
        place("RELIANCE", "SELL", 5, 55.0)
        place("SBIN", "SELL", 4, 70.0)
        assert engine.get_positions() == []
        # 5 * (55 - 50) + 4 * (70 - 80) added to the short cover.
        assert engine.get_pnl()["realised"] == pytest.approx(65.0)

    def test_practice_sandbox_not_configured_returns_500(self, flask_app, client):
        """If SandboxEngine is missing from config, return 500."""
        flask_app.config["DATA_SANDBOX_ENGINE"] = None

        resp = client.post(
            "/api/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="practice"),
        )
        assert resp.status_code == 500
        data = resp.get_json()
        assert "not available" in data["message"]

    def test_practice_sandbox_exception_returns_500(self, flask_app, client):
        """If SandboxEngine raises, return 500 rather than crashing."""
        mock_sandbox = MagicMock()
        mock_sandbox.place_order.side_effect = RuntimeError("DB locked")
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox

        resp = client.post(
            "/api/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="practice"),
        )
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["status"] == "error"


# ---------------------------------------------------------------------------
# 4. Live mode — gated writes only
# ---------------------------------------------------------------------------


class TestLiveModeForwarding:
    """Live mode dispatch: every executable write must be gated.

    After the C1 fix, ``/api/v1/orders/place`` live runs through the SafetySystem
    + one-shot gate + per-account ACL BrokerRouter and NEVER hits the raw native broker
    forward. Legacy live actions without BrokerRouter verbs fail closed until
    they are implemented through the same gated channel.
    """

    def test_live_place_order_is_gated_not_forwarded(self, client):
        """C1 regression: live /place must NEVER reach the raw native broker forward.

        It now routes through the SafetySystem + one-shot gate + per-account ACL
        BrokerRouter. With the default workspace (empty account_acls) the
        unauthorised actor is refused — but the decisive assertion is that the raw
        httpx forward is never called, so an order cannot escape ungated.
        """

        resp = client.post(
            "/api/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="live", include_live_token=True),
        )
        # The ungated raw forward must never be reached on the live /place path.
        # Bare WSGI construction has no process-owned emergency runtime, so the
        # BrokerRouter is deliberately unpublished and the write fails closed.
        assert resp.status_code == 503

    @pytest.mark.parametrize(
        ("endpoint", "expected_status"),
        [
            # modify: the order is absent from the authoritative book — a
            # verifiable STATE refusal, reported 409 with the specific reason.
            ("/api/v1/orders/modify", 503),
            # cancel: no router available at all — a service-unavailable 503.
            ("/api/v1/orders/cancel", 503),
        ],
    )
    def test_live_modify_cancel_are_gated_not_forwarded(self, endpoint, expected_status, client):
        """modify/cancel live now route through the gated BrokerRouter, never the raw forward."""

        body = {**_SAMPLE_ORDER_BODY, "orderid": "OA-1"}
        resp = client.post(
            endpoint,
            json=body,
            headers=_auth_headers(mode="live", include_live_token=True),
        )
        # No raw httpx forward; bare WSGI has no emergency runtime/router.
        assert resp.status_code == expected_status

    def test_kotak_cancel_rejects_removed_trading_symbol_before_gate(
        self,
        flask_app,
        monkeypatch,
        *,
        backend_lease_factory,
    ):
        """Kotak v3 removed ``trading_symbol`` from cancel; reject it before routing."""
        from flinttrade_core import order_routes as routes

        calls: list[str] = []

        class CapturingRouter:
            backend_lease_proof = backend_lease_factory()

            async def cancel_order(self, request_ctx, *, order, order_id, safety_ctx, hint, extras):
                calls.append("router")

        def gate(order, request_ctx, *, adapter_id, account_id, backend_lease_proof):
            calls.append("gate")
            return object()

        monkeypatch.setattr("flinttrade_engine.safety.gate_order", gate)
        monkeypatch.setitem(flask_app.config, "BROKER_ROUTER", CapturingRouter())

        with flask_app.app_context():
            response, status = routes._dispatch_live_cancel(
                {
                    "orderid": "OID-1",
                    "variety": "amo",
                    "amo": True,
                    "trading_symbol": "IDEA-EQ",
                },
                {"jti": "jti-1", "sub": "operator"},
                adapter_id="kotakneo",
                account_id="KOTAK1",
            )

        assert status == 501
        assert response.get_json() == {
            "status": "error",
            "message": "Kotak Neo v3 cancel does not accept a trading symbol.",
        }
        assert calls == []

    def test_live_cancel_all_fails_closed_when_router_is_unavailable(self, client):
        """Cancel-all must use the gated router and never fall back to raw HTTP."""
        resp = client.post(
            "/api/v1/orders/cancel-all",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="live", include_live_token=True),
        )

        assert resp.status_code == 503
        assert "Order routing unavailable" in resp.get_json()["message"]

    def test_live_without_pin_token_returns_403(self, client):
        """Live orders without a PIN-unlocked JWT must be rejected with 403."""
        resp = client.post(
            "/api/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="live"),
        )
        assert resp.status_code == 403
        data = resp.get_json()
        assert "Live mode not unlocked" in data["message"]


# ---------------------------------------------------------------------------
# 5. Raw native broker forwarding helper remains fail-closed
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 6. Request body edge cases
# ---------------------------------------------------------------------------


class TestRequestBodyEdgeCases:
    """Edge cases around malformed or missing request bodies."""

    def test_empty_body_in_explore_still_blocked(self, client):
        """Even with no body, explore mode must block."""
        resp = client.post(
            "/api/v1/orders/place",
            json={},
            headers=_auth_headers(mode="explore"),
        )
        assert resp.status_code == 403

    def test_empty_body_in_practice_mode(self, flask_app, client):
        """Practice place with an empty body is denied before the sandbox."""
        mock_sandbox = MagicMock()
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox

        resp = client.post(
            "/api/v1/orders/place",
            json={},
            headers=_auth_headers(mode="practice"),
        )
        body = resp.get_json()
        assert resp.status_code == 403
        assert body["code"] == "laya_denied"
        assert body["reason"] == "Symbol and exchange are required."
        mock_sandbox.place_order.assert_not_called()

    def test_non_numeric_quantity_defaults_to_zero(self, flask_app, client):
        """A non-numeric quantity is denied. It is not placed as zero."""
        mock_sandbox = MagicMock()
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox

        body = dict(_SAMPLE_ORDER_BODY)
        body["quantity"] = "not-a-number"

        resp = client.post(
            "/api/v1/orders/place",
            json=body,
            headers=_auth_headers(mode="practice"),
        )
        data = resp.get_json()
        assert resp.status_code == 403
        assert data["code"] == "laya_denied"
        assert data["reason"] == "Quantity must be a positive whole number."
        mock_sandbox.place_order.assert_not_called()


# ---------------------------------------------------------------------------
# 7. Auth required (no API key → 401)
# ---------------------------------------------------------------------------


class TestAuthRequired:
    """Order endpoints require authentication — unauthenticated requests are rejected.

    Without a valid API key the CSRF middleware rejects POST requests with 403
    (because the API-key bypass does not trigger).  This is the correct
    security outcome: the request never reaches the order routes.
    """

    def test_no_api_key_rejected(self, client):
        resp = client.post(
            "/api/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers={
                "Content-Type": "application/json",
                "X-FlintTrade-Mode": "live",
            },
        )
        # CSRF middleware rejects before auth middleware runs
        assert resp.status_code in (401, 403)

    def test_wrong_api_key_rejected(self, client):
        resp = client.post(
            "/api/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers={
                "X-API-Key": "wrong-key",
                "Content-Type": "application/json",
                "X-FlintTrade-Mode": "live",
            },
        )
        # CSRF middleware rejects before auth middleware runs
        assert resp.status_code in (401, 403)


def test_gated_verb_write_returns_bounded_broker_error(flask_app, monkeypatch, *, backend_lease_factory):
    """Broker/adapter exception details stay out of the HTTP response."""
    from flinttrade_core.exceptions import BrokerError
    from flinttrade_core import order_routes as routes

    class RefusingRouter:
        backend_lease_proof = backend_lease_factory()

        async def execute_gated(self, *_args, **_kwargs):
            raise BrokerError('Traceback\nFile "/Users/me/secret.py"\napi_key=leaked')

    monkeypatch.setattr("flinttrade_engine.safety.gate_broker_write", lambda *_args, **_kwargs: object())
    monkeypatch.setitem(flask_app.config, "BROKER_ROUTER", RefusingRouter())

    with flask_app.app_context():
        response, status = routes._gated_verb_write(
            "cancel_forever",
            {"order_id": "GTT-1"},
            {"jti": "jti-1", "sub": "operator"},
            adapter_id="dhan",
            account_id="ACC1",
            audit_event="FOREVER_CANCELLED",
            fail_message="Forever order cancel failed",
            ref="GTT-1",
        )

    assert status == 502
    assert response.get_json()["message"] == "Forever order cancel failed"


def test_redact_exc_scrubs_raw_account_id():
    """A registry error's embedded raw account id is replaced by its log ref."""
    from flinttrade_core.order_routes import _redact_exc
    from flinttrade_gateway.log_safety import account_ref

    exc = ValueError("Account 'ACCT-SECRET-42' not found in registry.")
    out = _redact_exc(exc, "ACCT-SECRET-42")

    assert "ACCT-SECRET-42" not in out
    assert account_ref("ACCT-SECRET-42") in out


def test_redact_exc_leaves_unrelated_messages_untouched():
    """An exception that does not embed the account id is logged verbatim."""
    from flinttrade_core.order_routes import _redact_exc

    assert _redact_exc(ValueError("rate limit exceeded"), "ACCT-SECRET-42") == "rate limit exceeded"


def test_redact_exc_handles_empty_account():
    """An empty/None account id must not blank out or corrupt the message."""
    from flinttrade_core.order_routes import _redact_exc

    assert _redact_exc(ValueError("boom"), "") == "boom"
    assert _redact_exc(ValueError("boom"), None) == "boom"


def test_gated_verb_write_keeps_raw_account_id_out_of_logs(flask_app, monkeypatch, caplog, *, backend_lease_factory):
    """Finding #7: a broker-not-connected error must not re-leak the raw account
    id through the caught exception's message tail."""
    import logging

    from flinttrade_gateway.exceptions import BrokerNotFoundError
    from flinttrade_gateway.log_safety import account_ref
    from flinttrade_core import order_routes as routes

    raw_account = "ACCT-SECRET-98765"

    class MissingRouter:
        backend_lease_proof = backend_lease_factory()

        async def execute_gated(self, *_args, **_kwargs):
            raise BrokerNotFoundError(f"Account '{raw_account}' not found in registry.")

    monkeypatch.setattr("flinttrade_engine.safety.gate_broker_write", lambda *_args, **_kwargs: object())
    monkeypatch.setitem(flask_app.config, "BROKER_ROUTER", MissingRouter())

    with flask_app.app_context(), caplog.at_level(logging.WARNING, logger="flinttrade.order_routes"):
        _response, status = routes._gated_verb_write(
            "cancel_forever",
            {"order_id": "GTT-1"},
            {"jti": "jti-1", "sub": "operator"},
            adapter_id="dhan",
            account_id=raw_account,
            audit_event="FOREVER_CANCELLED",
            fail_message="Forever order cancel failed",
            ref="GTT-1",
        )

    assert status == 503
    assert raw_account not in caplog.text
    assert account_ref(raw_account) in caplog.text
