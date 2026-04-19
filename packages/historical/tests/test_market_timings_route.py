"""Tests for GET /api/v1/market/timings endpoint.

Run with:
    python -m pytest packages/historical/tests/test_market_timings_route.py -v --import-mode=importlib
"""

from __future__ import annotations

import pytest
from flask import Flask

from packages.historical.src.holidays_routes import holidays_bp


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
