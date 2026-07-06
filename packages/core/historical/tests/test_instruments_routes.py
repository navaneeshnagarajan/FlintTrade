"""Tests for GET /api/v1/instruments endpoint.

Run with:
    python -m pytest packages/core/historical/tests/test_instruments_routes.py -v --import-mode=importlib
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from flask import Flask

from flinttrade_historical.instruments_routes import instruments_bp, _STREAM_THRESHOLD


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app() -> Flask:
    """Minimal Flask app with the instruments blueprint."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(instruments_bp)
    return flask_app


@pytest.fixture()
def client(app: Flask):  # type: ignore[no-untyped-def]
    return app.test_client()


def _mock_client(instruments_data: object) -> MagicMock:
    """Build a mock OpenAlgoClient with instruments() stub."""
    mock = MagicMock()
    mock.instruments = AsyncMock(return_value={"status": "success", "data": instruments_data})
    mock.close = AsyncMock()
    return mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInstrumentsRoute:
    """Tests for GET /api/v1/instruments."""

    def test_default_exchange_returns_200(self, client) -> None:  # type: ignore[no-untyped-def]
        """Calling without ?exchange defaults to NSE and returns 200."""
        mock = _mock_client([{"symbol": "RELIANCE", "exchange": "NSE"}])
        with patch("flinttrade_historical.instruments_routes.resolve_openalgo_client", return_value=(mock, True)):
            response = client.get("/api/v1/instruments")
        assert response.status_code == 200
        mock.close.assert_awaited_once()

    def test_response_shape_small(self, client) -> None:  # type: ignore[no-untyped-def]
        """Small result set returns standard JSON with count and instruments list."""
        data_rows = [{"symbol": f"SYM{i}", "exchange": "NSE"} for i in range(5)]
        mock = _mock_client(data_rows)
        with patch("flinttrade_historical.instruments_routes.resolve_openalgo_client", return_value=(mock, True)):
            response = client.get("/api/v1/instruments?exchange=NSE")
        body = response.get_json()
        assert body["status"] == "success"
        assert body["exchange"] == "NSE"
        assert body["count"] == 5
        assert len(body["instruments"]) == 5

    def test_large_result_streams_ndjson(self, client) -> None:  # type: ignore[no-untyped-def]
        """Result sets above _STREAM_THRESHOLD use streaming NDJSON content-type."""
        large_data = [{"symbol": f"SYM{i}"} for i in range(_STREAM_THRESHOLD + 1)]
        mock = _mock_client(large_data)
        with patch("flinttrade_historical.instruments_routes.resolve_openalgo_client", return_value=(mock, True)):
            response = client.get("/api/v1/instruments?exchange=NSE")
        assert response.status_code == 200
        assert "ndjson" in response.content_type

    def test_openalgo_failure_returns_503(self, client) -> None:  # type: ignore[no-untyped-def]
        """OpenAlgo failure returns HTTP 503 with error status."""
        with patch(
            "flinttrade_historical.instruments_routes.resolve_openalgo_client",
            side_effect=Exception("timeout"),
        ):
            response = client.get("/api/v1/instruments")
        assert response.status_code == 503
        body = response.get_json()
        assert body["status"] == "error"
