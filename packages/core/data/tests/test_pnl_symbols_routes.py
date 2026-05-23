"""Tests for GET /api/v1/pnl/symbols endpoint.

Run with:
    python -m pytest packages/core/data/tests/test_pnl_symbols_routes.py -v --import-mode=importlib
"""

from __future__ import annotations


import pytest
from flask import Flask

from flinttrade_data.pnl_symbols_routes import pnl_symbols_bp, init_pnl_symbols_routes
from flinttrade_journal.pnl_tracker import PnLTracker


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tracker() -> PnLTracker:
    """Return a fresh in-memory PnLTracker populated with sample data."""
    t = PnLTracker()
    trades = [
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 10,
            "entry_price": 2500.0,
            "exit_price": 2550.0,
        }
    ]
    positions: list = []
    ltp_map: dict = {}
    t.update(trades, positions, ltp_map)
    return t


@pytest.fixture()
def app(tracker: PnLTracker) -> Flask:
    """Minimal Flask app with pnl_symbols blueprint and injected tracker."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(pnl_symbols_bp)
    init_pnl_symbols_routes(tracker)
    return flask_app


@pytest.fixture()
def client(app: Flask):  # type: ignore[no-untyped-def]
    return app.test_client()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPnlSymbolsRoute:
    """Tests for GET /api/v1/pnl/symbols."""

    def test_returns_200_no_filters(self, client) -> None:  # type: ignore[no-untyped-def]
        """Calling without date filters returns HTTP 200."""
        response = client.get("/api/v1/pnl/symbols")
        assert response.status_code == 200

    def test_response_shape(self, client) -> None:  # type: ignore[no-untyped-def]
        """Response contains status, period, overall_summary, series_count."""
        response = client.get("/api/v1/pnl/symbols")
        data = response.get_json()
        assert data["status"] == "success"
        assert "period" in data
        assert "overall_summary" in data
        assert "series_count" in data
        period = data["period"]
        assert "realized_pnl" in period
        assert "unrealized_pnl" in period
        assert "total_pnl" in period

    def test_invalid_date_from_returns_400(self, client) -> None:  # type: ignore[no-untyped-def]
        """Non-ISO date_from returns HTTP 400."""
        response = client.get("/api/v1/pnl/symbols?date_from=not-a-date")
        assert response.status_code == 400
        data = response.get_json()
        assert data["status"] == "error"

    def test_date_filter_reduces_series(self, client) -> None:  # type: ignore[no-untyped-def]
        """Future date_from returns zero series_count (no future points)."""
        response = client.get("/api/v1/pnl/symbols?date_from=2099-01-01")
        data = response.get_json()
        assert response.status_code == 200
        assert data["series_count"] == 0

    def test_valid_date_range_returns_data(self, client) -> None:  # type: ignore[no-untyped-def]
        """Past date_from returns existing series data."""
        response = client.get("/api/v1/pnl/symbols?date_from=2020-01-01")
        data = response.get_json()
        assert response.status_code == 200
        assert data["series_count"] >= 1
