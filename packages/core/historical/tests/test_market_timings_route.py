"""Tests for GET /api/v1/market/timings endpoint.

Run with:
    python -m pytest packages/core/historical/tests/test_market_timings_route.py -v --import-mode=importlib
"""

from __future__ import annotations

import pytest
from flask import Flask

from flinttrade_historical.holidays_routes import holidays_bp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app() -> Flask:
    """Minimal Flask app with the holidays blueprint (contains market/timings)."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(holidays_bp)
    return flask_app


@pytest.fixture()
def client(app: Flask):  # type: ignore[no-untyped-def]
    return app.test_client()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMarketTimingsRoute:
    """Tests for GET /api/v1/market/timings."""

    def test_nse_returns_200(self, client) -> None:  # type: ignore[no-untyped-def]
        """NSE timings returns HTTP 200."""
        response = client.get("/api/v1/market/timings?exchange=NSE")
        assert response.status_code == 200

    def test_nse_response_shape(self, client) -> None:  # type: ignore[no-untyped-def]
        """NSE response has expected keys with correct market hours."""
        response = client.get("/api/v1/market/timings?exchange=NSE")
        data = response.get_json()
        assert data["status"] == "success"
        assert data["exchange"] == "NSE"
        assert data["open"] == "09:15"
        assert data["close"] == "15:30"
        assert data["pre_open"] == "09:00"
        assert isinstance(data["special_sessions"], list)

    def test_mcx_timings(self, client) -> None:  # type: ignore[no-untyped-def]
        """MCX returns correct extended hours (09:00-23:30)."""
        response = client.get("/api/v1/market/timings?exchange=MCX")
        data = response.get_json()
        assert response.status_code == 200
        assert data["open"] == "09:00"
        assert data["close"] == "23:30"

    def test_unknown_exchange_returns_400(self, client) -> None:  # type: ignore[no-untyped-def]
        """Unrecognised exchange code returns HTTP 400 with supported list."""
        response = client.get("/api/v1/market/timings?exchange=INVALID")
        assert response.status_code == 400
        data = response.get_json()
        assert "supported" in data

    def test_derivative_close_and_expiry_exception_switch_on_dec_7(self, client) -> None:  # type: ignore[no-untyped-def]
        before = client.get("/api/v1/market/timings?exchange=NFO&on=2026-12-04")
        after = client.get("/api/v1/market/timings?exchange=BFO&on=2026-12-07")
        assert before.status_code == 200
        assert before.get_json()["close"] == "15:40"
        assert before.get_json()["expiring_index_close"] is None
        body = after.get_json()
        assert body["close"] == "15:45"
        assert body["expiring_index_close"] == "15:30"
        assert body["order_entry"] == "open"

    def test_timings_reads_the_symbol_expiry_and_fails_closed_when_unconfirmed(self, client) -> None:  # type: ignore[no-untyped-def]
        listed = client.get(
            "/api/v1/market/timings?exchange=NFO&on=2026-12-10"
            "&symbol=NIFTY10DEC2624000CE&expiries=2026-12-10,2026-12-17"
        )
        from_symbol = client.get(
            "/api/v1/market/timings?exchange=NFO&on=2026-12-10&symbol=NIFTY10DEC2624000CE"
        )
        unconfirmed = client.get(
            "/api/v1/market/timings?exchange=NFO&on=2026-12-10"
            "&symbol=NIFTY10DEC2624000CE&expiries=2026-12-17"
        )
        ambiguous = client.get(
            "/api/v1/market/timings?exchange=NFO&on=2026-12-10&symbol=NIFTY"
        )
        later = client.get(
            "/api/v1/market/timings?exchange=BFO&on=2026-12-10"
            "&symbol=SENSEX17DEC2680000CE&expiries=2026-12-10,2026-12-17"
        )
        assert listed.get_json()["close"] == "15:30"
        assert listed.get_json()["order_entry"] == "open"
        assert from_symbol.get_json()["close"] == "15:30"
        assert from_symbol.get_json()["order_entry"] == "open"
        assert from_symbol.get_json()["expiring_index_close"] == "15:30"
        assert unconfirmed.get_json()["close"] is None
        assert unconfirmed.get_json()["order_entry"] == "closed"
        assert ambiguous.get_json()["close"] is None
        assert ambiguous.get_json()["order_entry"] == "closed"
        assert later.get_json()["close"] == "15:45"
