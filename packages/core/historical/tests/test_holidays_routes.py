"""Tests for GET /api/v1/holidays endpoint.

Run with:
    python -m pytest packages/core/historical/tests/test_holidays_routes.py -v --import-mode=importlib
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from flask import Flask

from flinttrade_historical.holidays_routes import holidays_bp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app() -> Flask:
    """Minimal Flask app with the holidays blueprint."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(holidays_bp)
    return flask_app


@pytest.fixture()
def client(app: Flask):  # type: ignore[no-untyped-def]
    return app.test_client()


def _mock_client(holidays_data: object) -> MagicMock:
    """Build a mock OpenAlgoClient that returns *holidays_data* from holidays()."""
    mock = MagicMock()
    mock.holidays = AsyncMock(return_value={"status": "success", "data": holidays_data})
    mock.close = AsyncMock()
    return mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHolidaysRoute:
    """Tests for GET /api/v1/holidays."""

    def test_default_params_returns_200(self, client) -> None:  # type: ignore[no-untyped-def]
        """Calling without params uses NSE + current year and returns 200."""
        mock = _mock_client(["2026-01-26", "2026-08-15"])
        with patch("flinttrade_historical.holidays_routes.resolve_openalgo_client", return_value=(mock, True)):
            response = client.get("/api/v1/holidays")
        assert response.status_code == 200
        mock.close.assert_awaited_once()

    def test_response_shape(self, client) -> None:  # type: ignore[no-untyped-def]
        """Response contains status, exchange, year, holidays, count."""
        mock = _mock_client(["2026-01-26", "2026-08-15"])
        with patch("flinttrade_historical.holidays_routes.resolve_openalgo_client", return_value=(mock, True)):
            response = client.get("/api/v1/holidays?exchange=NSE&year=2026")
        data = response.get_json()
        assert data["status"] == "success"
        assert data["exchange"] == "NSE"
        assert data["year"] == 2026
        assert isinstance(data["holidays"], list)
        assert data["count"] == len(data["holidays"])

    def test_invalid_year_returns_400(self, client) -> None:  # type: ignore[no-untyped-def]
        """Non-integer year returns HTTP 400."""
        response = client.get("/api/v1/holidays?year=twentytwentysix")
        assert response.status_code == 400

    def test_out_of_range_year_returns_400(self, client) -> None:  # type: ignore[no-untyped-def]
        """Year outside [2000, 2100] returns HTTP 400."""
        response = client.get("/api/v1/holidays?year=1999")
        assert response.status_code == 400

    def test_openalgo_failure_returns_fallback(self, client) -> None:  # type: ignore[no-untyped-def]
        """When OpenAlgo is unreachable a fallback empty list is returned (not 5xx)."""
        with patch(
            "flinttrade_historical.holidays_routes.resolve_openalgo_client",
            side_effect=Exception("connection refused"),
        ):
            response = client.get("/api/v1/holidays?year=2026")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert data["holidays"] == []
        assert data.get("source") == "fallback"
