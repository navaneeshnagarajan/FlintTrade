"""Tests for GET /api/v1/search endpoint.

Run with:
    python -m pytest packages/core/historical/tests/test_search_routes.py -v --import-mode=importlib
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from flask import Flask

from flinttrade_historical.search_routes import search_bp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app() -> Flask:
    """Minimal Flask app with only the search blueprint."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(search_bp)
    return flask_app


@pytest.fixture()
def client(app: Flask):  # type: ignore[no-untyped-def]
    return app.test_client()


_SAMPLE_RESULTS = [
    {"symbol": "RELIANCE", "exchange": "NSE", "name": "Reliance Industries"},
    {"symbol": "RELIANCE", "exchange": "BSE", "name": "Reliance Industries"},
    {"symbol": "RELIANCEPP", "exchange": "NSE", "name": "Reliance PP"},
]


def _mock_client(results: object) -> MagicMock:
    """Build a mock OpenAlgoClient with a stubbed search() method."""
    mock = MagicMock()
    mock.search = AsyncMock(return_value={"status": "success", "data": results})
    mock.close = AsyncMock()
    return mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSearchRoute:
    """Tests for GET /api/v1/search."""

    def test_missing_query_returns_400(self, client) -> None:  # type: ignore[no-untyped-def]
        """Calling without ?q returns HTTP 400."""
        response = client.get("/api/v1/search")
        assert response.status_code == 400
        data = response.get_json()
        assert data["status"] == "error"
        assert "'q'" in data["message"]

    def test_empty_query_returns_400(self, client) -> None:  # type: ignore[no-untyped-def]
        """Empty ?q= returns HTTP 400."""
        response = client.get("/api/v1/search?q=")
        assert response.status_code == 400

    def test_basic_search_returns_results(self, client) -> None:  # type: ignore[no-untyped-def]
        """Valid query returns results list with status=success."""
        mock = _mock_client(_SAMPLE_RESULTS)
        with patch("flinttrade_historical.search_routes.resolve_openalgo_client", return_value=(mock, True)):
            response = client.get("/api/v1/search?q=RELI")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "success"
        assert data["query"] == "RELI"
        assert isinstance(data["results"], list)
        mock.close.assert_awaited_once()

    def test_exchange_filter_applied(self, client) -> None:  # type: ignore[no-untyped-def]
        """?exchange=NSE filters results to NSE-only entries."""
        mock = _mock_client(_SAMPLE_RESULTS)
        with patch("flinttrade_historical.search_routes.resolve_openalgo_client", return_value=(mock, True)):
            response = client.get("/api/v1/search?q=RELI&exchange=NSE")
        data = response.get_json()
        assert data["exchange"] == "NSE"
        for result in data["results"]:
            assert result["exchange"] == "NSE"

    def test_limit_applied(self, client) -> None:  # type: ignore[no-untyped-def]
        """?limit=1 caps results at 1 entry."""
        mock = _mock_client(_SAMPLE_RESULTS)
        with patch("flinttrade_historical.search_routes.resolve_openalgo_client", return_value=(mock, True)):
            response = client.get("/api/v1/search?q=RELI&limit=1")
        data = response.get_json()
        assert data["count"] == 1
        assert len(data["results"]) == 1
