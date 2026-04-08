"""Tests for order proxy blueprint — mode enforcement and request forwarding.

Run with:
    python -m pytest packages/core/tests/test_order_routes.py -v --import-mode=importlib

This is a SAFETY-CRITICAL test suite.  The order proxy is the sole gateway
between the frontend and real-money broker orders.  Every mode enforcement
path must be verified to prevent accidental live execution in demo/practice
modes.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


_TEST_API_KEY = "test-order-routes-key"


def _create_live_token() -> str:
    """Create a JWT with ``live_mode_unlocked: true`` for live-mode tests."""
    from packages.core.src.auth_routes import _create_token
    return _create_token("testuser", live_mode_unlocked=True)

# All order endpoints and their FlintTrade route suffixes
_ORDER_ENDPOINTS = [
    "/v1/orders/place",
    "/v1/orders/place-smart",
    "/v1/orders/modify",
    "/v1/orders/cancel",
    "/v1/orders/cancel-all",
    "/v1/orders/close-position",
    "/v1/orders/open-position",
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
def flask_app(monkeypatch_module):
    """Create a Flask app with OPENALGO_API_KEY set for auth."""
    monkeypatch_module.setenv("OPENALGO_API_KEY", _TEST_API_KEY)
    from packages.core.src.app import create_flask_app
    app = create_flask_app()
    app.config["TESTING"] = True
    return app


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
    """Build request headers with API key and optional mode.

    Args:
        mode: Value for the ``X-FlintTrade-Mode`` header.
        include_live_token: If ``True``, include a JWT ``Authorization``
            header with ``live_mode_unlocked: true`` — required for live
            mode orders to pass server-side enforcement.
    """
    headers: dict[str, str] = {
        "X-API-Key": _TEST_API_KEY,
        "Content-Type": "application/json",
    }
    if mode is not None:
        headers["X-FlintTrade-Mode"] = mode
    if include_live_token:
        headers["Authorization"] = f"Bearer {_create_live_token()}"
    headers.update(extra)
    return headers


# ---------------------------------------------------------------------------
# 1. Mode enforcement — Explore mode blocks all orders
# ---------------------------------------------------------------------------


class TestExploreModeBlocked:
    """Explore mode must return 403 for every order endpoint."""

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
        assert "Explore mode" in data["message"]

    @pytest.mark.parametrize("endpoint", _ORDER_ENDPOINTS)
    def test_explore_mode_case_insensitive(self, client, endpoint):
        """Mode header should be case-insensitive (EXPLORE, Explore, etc.)."""
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
            "/v1/orders/place",
            json=body,
            headers=_auth_headers(mode="explore"),
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# 2. Missing / invalid mode header
# ---------------------------------------------------------------------------


class TestMissingOrInvalidMode:
    """Requests without a valid mode header must be rejected."""

    @pytest.mark.parametrize("endpoint", _ORDER_ENDPOINTS)
    def test_missing_mode_header_returns_400(self, client, endpoint):
        resp = client.post(
            endpoint,
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode=None),
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["status"] == "error"
        assert "X-FlintTrade-Mode" in data["message"]

    def test_empty_mode_header_returns_400(self, client):
        resp = client.post(
            "/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode=""),
        )
        assert resp.status_code == 400

    def test_invalid_mode_returns_400(self, client):
        resp = client.post(
            "/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="yolo"),
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "Invalid mode" in data["message"]

    def test_whitespace_only_mode_returns_400(self, client):
        resp = client.post(
            "/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="   "),
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 3. Practice mode — routes to SandboxEngine
# ---------------------------------------------------------------------------


class TestPracticeMode:
    """Practice mode must route to SandboxEngine, never to OpenAlgo."""

    def test_practice_place_order(self, flask_app, client):
        mock_sandbox = MagicMock()
        mock_sandbox.place_order.return_value = {
            "order_id": "SB-001",
            "status": "COMPLETE",
            "message": "Paper order filled",
        }
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox

        resp = client.post(
            "/v1/orders/place",
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
        )

    def test_practice_place_smart_order(self, flask_app, client):
        mock_sandbox = MagicMock()
        mock_sandbox.place_order.return_value = {
            "order_id": "SB-002",
            "status": "COMPLETE",
            "message": "Smart paper order filled",
        }
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox

        resp = client.post(
            "/v1/orders/place-smart",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="practice"),
        )
        assert resp.status_code == 200
        mock_sandbox.place_order.assert_called_once()

    def test_practice_cancel_order_acknowledged(self, flask_app, client):
        """Cancel in practice mode returns success (sandbox fills instantly)."""
        mock_sandbox = MagicMock()
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox

        resp = client.post(
            "/v1/orders/cancel",
            json={"order_id": "SB-001"},
            headers=_auth_headers(mode="practice"),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert "acknowledged" in data["message"]

    def test_practice_cancel_all_acknowledged(self, flask_app, client):
        mock_sandbox = MagicMock()
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox

        resp = client.post(
            "/v1/orders/cancel-all",
            json={},
            headers=_auth_headers(mode="practice"),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"

    def test_practice_modify_acknowledged(self, flask_app, client):
        mock_sandbox = MagicMock()
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox

        resp = client.post(
            "/v1/orders/modify",
            json={"order_id": "SB-001", "quantity": 100},
            headers=_auth_headers(mode="practice"),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"

    def test_practice_close_position(self, flask_app, client):
        mock_sandbox = MagicMock()
        mock_sandbox.get_positions.return_value = [
            {"symbol": "NIFTY", "exchange": "NSE", "product": "MIS", "net_qty": 50},
        ]
        mock_sandbox.place_order.return_value = {
            "order_id": "SB-003",
            "status": "COMPLETE",
            "message": "Position closed",
        }
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox

        resp = client.post(
            "/v1/orders/close-position",
            json={"symbol": "NIFTY", "exchange": "NSE", "product": "MIS"},
            headers=_auth_headers(mode="practice"),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "COMPLETE"
        # Should sell to close long position
        mock_sandbox.place_order.assert_called_once_with(
            symbol="NIFTY",
            exchange="NSE",
            action="SELL",
            quantity=50,
            price=0.0,
            product="MIS",
        )

    def test_practice_close_position_no_matching(self, flask_app, client):
        """Closing a position that does not exist returns REJECTED."""
        mock_sandbox = MagicMock()
        mock_sandbox.get_positions.return_value = []
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox

        resp = client.post(
            "/v1/orders/close-position",
            json={"symbol": "NIFTY", "exchange": "NSE", "product": "MIS"},
            headers=_auth_headers(mode="practice"),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "REJECTED"

    def test_practice_open_position(self, flask_app, client):
        mock_sandbox = MagicMock()
        mock_sandbox.place_order.return_value = {
            "order_id": "SB-004",
            "status": "COMPLETE",
            "message": "Position opened",
        }
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox

        resp = client.post(
            "/v1/orders/open-position",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="practice"),
        )
        assert resp.status_code == 200
        mock_sandbox.place_order.assert_called_once()

    def test_practice_sandbox_not_configured_returns_500(self, flask_app, client):
        """If SandboxEngine is missing from config, return 500."""
        flask_app.config["DATA_SANDBOX_ENGINE"] = None

        resp = client.post(
            "/v1/orders/place",
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
            "/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="practice"),
        )
        assert resp.status_code == 500
        data = resp.get_json()
        assert data["status"] == "error"


# ---------------------------------------------------------------------------
# 4. Live mode — forwards to OpenAlgo
# ---------------------------------------------------------------------------


class TestLiveModeForwarding:
    """Live mode must forward requests to OpenAlgo with the API key."""

    @patch("packages.core.src.order_routes.httpx.Client")
    def test_live_place_order_forwards_correctly(self, mock_client_cls, client):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "success",
            "order_id": "OA-123",
        }
        mock_response.status_code = 200
        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.post.return_value = mock_response
        mock_client_cls.return_value = mock_http

        resp = client.post(
            "/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="live", include_live_token=True),
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["order_id"] == "OA-123"

        # Verify the forwarded payload includes apikey
        call_args = mock_http.post.call_args
        forwarded_body = call_args.kwargs.get("json") or call_args[1].get("json")
        assert forwarded_body["apikey"] == _TEST_API_KEY
        assert forwarded_body["symbol"] == "NIFTY"

    @patch("packages.core.src.order_routes.httpx.Client")
    def test_live_forwards_to_correct_openalgo_endpoint(self, mock_client_cls, client):
        """Each FlintTrade route should map to the correct OpenAlgo endpoint."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "success"}
        mock_response.status_code = 200
        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.post.return_value = mock_response
        mock_client_cls.return_value = mock_http

        endpoint_map = {
            "/v1/orders/place": "placeorder",
            "/v1/orders/place-smart": "placesmartorder",
            "/v1/orders/modify": "modifyorder",
            "/v1/orders/cancel": "cancelorder",
            "/v1/orders/cancel-all": "cancelallorder",
            "/v1/orders/close-position": "closeposition",
            "/v1/orders/open-position": "openposition",
        }

        for ft_route, oa_endpoint in endpoint_map.items():
            mock_http.post.reset_mock()
            resp = client.post(
                ft_route,
                json=_SAMPLE_ORDER_BODY,
                headers=_auth_headers(mode="live", include_live_token=True),
            )
            assert resp.status_code == 200, f"Failed for {ft_route}"
            call_url = mock_http.post.call_args[0][0]
            assert call_url.endswith(f"/api/v1/{oa_endpoint}"), (
                f"Expected URL ending with /api/v1/{oa_endpoint}, got {call_url}"
            )

    @patch("packages.core.src.order_routes.httpx.Client")
    def test_live_propagates_openalgo_error_status(self, mock_client_cls, client):
        """If OpenAlgo returns an error status, propagate it."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "status": "error",
            "message": "Insufficient margin",
        }
        mock_response.status_code = 400
        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.post.return_value = mock_response
        mock_client_cls.return_value = mock_http

        resp = client.post(
            "/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="live", include_live_token=True),
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["message"] == "Insufficient margin"

    def test_live_without_pin_token_returns_403(self, client):
        """Live orders without a PIN-unlocked JWT must be rejected with 403."""
        resp = client.post(
            "/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="live"),
        )
        assert resp.status_code == 403
        data = resp.get_json()
        assert "Live mode not unlocked" in data["message"]


# ---------------------------------------------------------------------------
# 5. Error handling — connection errors, timeouts, missing API key
# ---------------------------------------------------------------------------


class TestLiveModeErrors:
    """Error handling when forwarding to OpenAlgo fails."""

    @patch("packages.core.src.order_routes.httpx.Client")
    def test_openalgo_unreachable_returns_502(self, mock_client_cls, client):
        import httpx
        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.post.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_http

        resp = client.post(
            "/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="live", include_live_token=True),
        )
        assert resp.status_code == 502
        data = resp.get_json()
        assert "unreachable" in data["message"].lower()

    @patch("packages.core.src.order_routes.httpx.Client")
    def test_openalgo_timeout_returns_504(self, mock_client_cls, client):
        import httpx
        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.post.side_effect = httpx.ReadTimeout("Read timed out")
        mock_client_cls.return_value = mock_http

        resp = client.post(
            "/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="live", include_live_token=True),
        )
        assert resp.status_code == 504
        data = resp.get_json()
        assert "timed out" in data["message"].lower()

    @patch("packages.core.src.order_routes.httpx.Client")
    def test_openalgo_generic_http_error_returns_502(self, mock_client_cls, client):
        import httpx
        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.post.side_effect = httpx.HTTPError("Something went wrong")
        mock_client_cls.return_value = mock_http

        resp = client.post(
            "/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="live", include_live_token=True),
        )
        assert resp.status_code == 502

    @patch("packages.core.src.order_routes._openalgo_api_key", return_value="")
    def test_missing_api_key_returns_503(self, _mock_key, client):
        """If OPENALGO_API_KEY is empty for forwarding, live orders return 503.

        Note: the auth middleware still sees the real env var (so the request
        passes auth), but _forward_to_openalgo sees an empty key via the
        patched helper and returns 503.
        """
        resp = client.post(
            "/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="live", include_live_token=True),
        )
        assert resp.status_code == 503
        data = resp.get_json()
        assert "API key" in data["message"]

    @patch("packages.core.src.order_routes.httpx.Client")
    def test_openalgo_non_json_response(self, mock_client_cls, client):
        """If OpenAlgo returns non-JSON, return an error with the status code."""
        mock_response = MagicMock()
        mock_response.json.side_effect = ValueError("No JSON")
        mock_response.status_code = 500
        mock_http = MagicMock()
        mock_http.__enter__ = MagicMock(return_value=mock_http)
        mock_http.__exit__ = MagicMock(return_value=False)
        mock_http.post.return_value = mock_response
        mock_client_cls.return_value = mock_http

        resp = client.post(
            "/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers=_auth_headers(mode="live", include_live_token=True),
        )
        assert resp.status_code == 500
        data = resp.get_json()
        assert "Non-JSON" in data["message"]


# ---------------------------------------------------------------------------
# 6. Request body edge cases
# ---------------------------------------------------------------------------


class TestRequestBodyEdgeCases:
    """Edge cases around malformed or missing request bodies."""

    def test_empty_body_in_explore_still_blocked(self, client):
        """Even with no body, explore mode must block."""
        resp = client.post(
            "/v1/orders/place",
            json={},
            headers=_auth_headers(mode="explore"),
        )
        assert resp.status_code == 403

    def test_empty_body_in_practice_mode(self, flask_app, client):
        """Practice mode with empty body — sandbox gets defaults."""
        mock_sandbox = MagicMock()
        mock_sandbox.place_order.return_value = {
            "order_id": "SB-EMPTY",
            "status": "COMPLETE",
            "message": "Filled",
        }
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox

        resp = client.post(
            "/v1/orders/place",
            json={},
            headers=_auth_headers(mode="practice"),
        )
        assert resp.status_code == 200
        # Should call with default/empty values, not crash
        mock_sandbox.place_order.assert_called_once()
        call_kwargs = mock_sandbox.place_order.call_args.kwargs
        assert call_kwargs["symbol"] == ""
        assert call_kwargs["quantity"] == 0

    def test_non_numeric_quantity_defaults_to_zero(self, flask_app, client):
        """Non-numeric quantity should default to 0, not crash."""
        mock_sandbox = MagicMock()
        mock_sandbox.place_order.return_value = {
            "order_id": "SB-005",
            "status": "COMPLETE",
            "message": "Filled",
        }
        flask_app.config["DATA_SANDBOX_ENGINE"] = mock_sandbox

        body = dict(_SAMPLE_ORDER_BODY)
        body["quantity"] = "not-a-number"

        resp = client.post(
            "/v1/orders/place",
            json=body,
            headers=_auth_headers(mode="practice"),
        )
        assert resp.status_code == 200
        call_kwargs = mock_sandbox.place_order.call_args.kwargs
        assert call_kwargs["quantity"] == 0


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
            "/v1/orders/place",
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
            "/v1/orders/place",
            json=_SAMPLE_ORDER_BODY,
            headers={
                "X-API-Key": "wrong-key",
                "Content-Type": "application/json",
                "X-FlintTrade-Mode": "live",
            },
        )
        # CSRF middleware rejects before auth middleware runs
        assert resp.status_code in (401, 403)
