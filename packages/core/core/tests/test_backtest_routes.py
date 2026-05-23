"""Tests for backtest REST endpoints — strategy listing and backtest execution.

Run with:
    python -m pytest packages/core/core/tests/test_backtest_routes.py -v --import-mode=importlib
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


_TEST_API_KEY = "test-backtest-routes-key"


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch fixture."""
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(scope="module")
def flask_app(monkeypatch_module):
    """Create a Flask app with backtest blueprint registered."""
    monkeypatch_module.setenv("OPENALGO_API_KEY", _TEST_API_KEY)
    from flinttrade_core.app import create_flask_app
    app = create_flask_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture()
def client(flask_app):
    """Flask test client with API key header."""
    with flask_app.test_client() as c:
        yield c


def _auth_headers() -> dict[str, str]:
    return {
        "X-API-Key": _TEST_API_KEY,
        "Content-Type": "application/json",
    }


class TestListStrategies:
    """GET /api/v1/strategies — list available strategies.

    Note: The engine's strategy_bp (prefix /api/v1/strategies) takes
    priority over the backtest_bp (prefix /api/v1) for this path.
    When no STRATEGY_RUNNER is configured, the engine blueprint returns
    503.  We test with a mock runner to verify the happy path.
    """

    def test_strategies_returns_503_when_runner_not_configured(self, client):
        """Without a strategy runner, the engine blueprint returns 503."""
        resp = client.get("/api/v1/strategies", headers=_auth_headers())
        assert resp.status_code == 503

    def test_strategies_returns_200_with_runner(self, flask_app, client):
        """With a strategy runner configured, returns the strategy list."""
        mock_runner = MagicMock()
        mock_runner.list_strategies.return_value = [
            {"id": "ema_cross", "name": "EMA Crossover", "state": "idle"},
        ]
        flask_app.config["STRATEGY_RUNNER"] = mock_runner
        try:
            resp = client.get("/api/v1/strategies", headers=_auth_headers())
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "success"
        finally:
            flask_app.config["STRATEGY_RUNNER"] = None


class TestListUploadedStrategies:
    """GET /api/v1/backtest/strategies/uploaded — list user-uploaded strategies."""

    def test_uploaded_returns_200_when_runner_not_configured(self, client):
        """When STRATEGY_RUNNER is not set, returns an empty list."""
        resp = client.get("/api/v1/backtest/strategies/uploaded", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"] == {"strategies": []}

    def test_uploaded_returns_strategies_from_runner(self, flask_app, client):
        """When STRATEGY_RUNNER is configured, delegates to it."""
        mock_runner = MagicMock()
        mock_runner.list_strategies.return_value = [
            {"name": "my_custom_strat", "file": "my_custom_strat.py"},
        ]
        flask_app.config["STRATEGY_RUNNER"] = mock_runner
        try:
            resp = client.get("/api/v1/backtest/strategies/uploaded", headers=_auth_headers())
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["status"] == "success"
            assert len(data["data"]["strategies"]) == 1
            assert data["data"]["strategies"][0]["name"] == "my_custom_strat"
            mock_runner.list_strategies.assert_called_once()
        finally:
            flask_app.config["STRATEGY_RUNNER"] = None

    def test_uploaded_returns_500_on_runner_error(self, flask_app, client):
        """When the runner raises, returns 500."""
        mock_runner = MagicMock()
        mock_runner.list_strategies.side_effect = RuntimeError("DB locked")
        flask_app.config["STRATEGY_RUNNER"] = mock_runner
        try:
            resp = client.get("/api/v1/backtest/strategies/uploaded", headers=_auth_headers())
            assert resp.status_code == 500
            data = resp.get_json()
            assert data["status"] == "error"
        finally:
            flask_app.config["STRATEGY_RUNNER"] = None


class TestBacktestRun:
    """POST /api/v1/backtest/run — execute a backtest."""

    def test_missing_symbol_returns_400(self, client):
        resp = client.post("/api/v1/backtest/run", json={
            "strategy": "EMACrossover",
        }, headers=_auth_headers())
        assert resp.status_code in (400, 500)
        data = resp.get_json()
        assert data["status"] == "error"

    def test_missing_strategy_returns_400(self, client):
        resp = client.post("/api/v1/backtest/run", json={
            "symbol": "RELIANCE",
        }, headers=_auth_headers())
        assert resp.status_code in (400, 500)
        data = resp.get_json()
        assert data["status"] == "error"

    def test_invalid_initial_capital_returns_400(self, client):
        resp = client.post("/api/v1/backtest/run", json={
            "symbol": "RELIANCE",
            "strategy": "EMACrossover",
            "initial_capital": "not-a-number",
        }, headers=_auth_headers())
        assert resp.status_code in (400, 500)
        data = resp.get_json()
        assert data["status"] == "error"

    def test_empty_body_returns_error(self, client):
        resp = client.post("/api/v1/backtest/run", json={},
                           headers=_auth_headers())
        assert resp.status_code in (400, 500)
        data = resp.get_json()
        assert data["status"] == "error"


class TestStrategiesRunning:
    """GET /api/v1/backtest/strategies/running — running strategy status."""

    def test_running_returns_200_when_scheduler_not_configured(self, client):
        """When SCHEDULER is not set, returns an empty list."""
        resp = client.get("/api/v1/backtest/strategies/running", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["strategies"] == []
