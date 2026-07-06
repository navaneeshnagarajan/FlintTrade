"""Tests for GET /api/v1/leverage/margin/current endpoint.

Run with:
    python -m pytest packages/services/engine/tests/test_leverage_routes.py -v --import-mode=importlib
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from flask import Flask

from flinttrade_engine.leverage_routes import leverage_bp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def app() -> Flask:
    """Minimal Flask app with only the leverage blueprint."""
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.register_blueprint(leverage_bp)
    return flask_app


@pytest.fixture()
def client(app: Flask):  # type: ignore[no-untyped-def]
    return app.test_client()


def _mock_client(margin_data: dict) -> MagicMock:
    """Build a mock OpenAlgoClient with a stubbed margin() method."""
    mock = MagicMock()
    mock.margin = AsyncMock(return_value={"status": "success", "data": margin_data})
    mock.close = AsyncMock()
    return mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLeverageMarginRoute:
    """Tests for GET /api/v1/leverage/margin/current."""

    def test_returns_200_on_success(self, client) -> None:  # type: ignore[no-untyped-def]
        """Returns HTTP 200 when OpenAlgo responds."""
        margin_payload = {"available": 50000.0, "used": 10000.0, "total": 60000.0}
        mock = _mock_client(margin_payload)
        with patch("flinttrade_engine.leverage_routes.resolve_openalgo_client", return_value=(mock, True)):
            response = client.get("/api/v1/leverage/margin/current")
        assert response.status_code == 200
        mock.close.assert_awaited_once()

    def test_response_shape(self, client) -> None:  # type: ignore[no-untyped-def]
        """Response contains available, used, total, leverage_ratio."""
        margin_payload = {"available": 50000.0, "used": 10000.0, "total": 60000.0}
        mock = _mock_client(margin_payload)
        with patch("flinttrade_engine.leverage_routes.resolve_openalgo_client", return_value=(mock, True)):
            response = client.get("/api/v1/leverage/margin/current")
        data = response.get_json()
        assert data["status"] == "success"
        assert data["available"] == 50000.0
        assert data["used"] == 10000.0
        assert data["total"] == 60000.0

    def test_leverage_ratio_calculation(self, client) -> None:  # type: ignore[no-untyped-def]
        """leverage_ratio = used / total."""
        margin_payload = {"available": 80000.0, "used": 20000.0, "total": 100000.0}
        mock = _mock_client(margin_payload)
        with patch("flinttrade_engine.leverage_routes.resolve_openalgo_client", return_value=(mock, True)):
            response = client.get("/api/v1/leverage/margin/current")
        data = response.get_json()
        assert data["leverage_ratio"] == pytest.approx(0.2, abs=1e-4)

    def test_openalgo_failure_returns_503(self, client) -> None:  # type: ignore[no-untyped-def]
        """Returns HTTP 503 when OpenAlgo is unreachable."""
        with patch(
            "flinttrade_engine.leverage_routes.resolve_openalgo_client",
            side_effect=Exception("connection refused"),
        ):
            response = client.get("/api/v1/leverage/margin/current")
        assert response.status_code == 503
        data = response.get_json()
        assert data["status"] == "error"
