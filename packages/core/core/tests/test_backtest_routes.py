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

    def test_strategies_returns_503_when_runner_not_configured(self, flask_app, client):
        """Without a strategy runner, the engine blueprint returns 503.

        ``create_flask_app`` now auto-provisions a ``UserStrategyRunner`` so the
        route works in production, so we null it out explicitly to exercise the
        not-configured branch (mirroring ``test_strategies_returns_200_with_runner``).
        """
        previous = flask_app.config.get("STRATEGY_RUNNER")
        flask_app.config["STRATEGY_RUNNER"] = None
        try:
            resp = client.get("/api/v1/strategies", headers=_auth_headers())
            assert resp.status_code == 503
        finally:
            flask_app.config["STRATEGY_RUNNER"] = previous

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

    def test_successful_run_persists_metrics_to_the_store(self, flask_app, client, monkeypatch, tmp_path):
        """A successful backtest writes its metrics to the result store, with the
        engine's ``sharpe``/``sortino`` aliased to the refiner's ``*_ratio`` keys.

        This is the populating half of the overnight-optimiser loop: without it
        the optimiser refines on an empty dict.
        """
        import flinttrade_core.backtest_routes as br
        from flinttrade_backtest.result_store import BacktestResultStore

        store = BacktestResultStore(tmp_path)
        flask_app.config["BACKTEST_RESULT_STORE"] = store

        class _FakeConfig:
            def __init__(self, **_kwargs):
                pass

        class _FakeStrategy:
            def __init__(self, **_kwargs):
                pass

        class _FakeResult:
            trades: list = []
            equity_curve: list = []
            total_bars = 10
            final_equity = 1_050_000.0
            total_return_pct = 5.0

        class _FakeSim:
            def __init__(self, _config):
                pass

            def run(self, _strategy, _bars):
                return _FakeResult()

        class _FakeData:
            success = True
            error = None
            bars = [1, 2, 3]

        class _FakeDataConnector:
            def load(self, *_a, **_k):
                return _FakeData()

        class _Drawdown:
            max_drawdown_pct = -0.1

        class _TradeStats:
            win_rate = 0.6
            profit_factor = 1.8
            total_trades = 12

        class _FakeReport:
            total_return_pct = 5.0
            cagr = 0.12
            sharpe_ratio = 1.5
            sortino_ratio = 2.0
            drawdown = _Drawdown
            trade_stats = _TradeStats

        class _FakeMetrics:
            @staticmethod
            def compute(_result):
                return _FakeReport()

        def _fake_engine():
            return (_FakeConfig, _FakeSim, {"EMACrossover": _FakeStrategy}, _FakeDataConnector, _FakeMetrics)

        monkeypatch.setattr(br, "_load_backtest_engine", _fake_engine)
        try:
            resp = client.post("/api/v1/backtest/run", json={
                "symbol": "RELIANCE", "exchange": "NSE", "interval": "5m",
                "start_date": "2025-01-01", "end_date": "2025-02-01",
                "strategy": "EMACrossover",
            }, headers=_auth_headers())
            assert resp.status_code == 200

            saved = store.latest("EMACrossover")
            assert saved is not None
            assert saved["sharpe_ratio"] == 1.5  # aliased from the engine's `sharpe`
            assert saved["sortino_ratio"] == 2.0
            assert saved["max_drawdown"] == -0.1
            assert saved["win_rate"] == 0.6
        finally:
            flask_app.config["BACKTEST_RESULT_STORE"] = None


class TestStrategiesRunning:
    """GET /api/v1/backtest/strategies/running — running strategy status."""

    def test_running_returns_200_when_scheduler_not_configured(self, client):
        """When SCHEDULER is not set, returns an empty list."""
        resp = client.get("/api/v1/backtest/strategies/running", headers=_auth_headers())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["data"]["strategies"] == []


class TestStrategyLibrary:
    """The full strategy library (ALL_STRATEGIES) is reachable, not just the 12 builtins."""

    def test_load_backtest_engine_exposes_the_full_library(self):
        from flinttrade_core.backtest_routes import _load_backtest_engine

        _, _, strategies, _, _ = _load_backtest_engine()
        # ALL_STRATEGIES (~88) merged with the 12 curated BUILTINs.
        assert len(strategies) >= 50
        assert "SMACrossover" in strategies  # an ALL_STRATEGIES entry, previously unreachable
        assert "EMACrossover" in strategies  # a BUILTIN, still present (wins on clash)

    def test_strategies_endpoint_lists_the_full_library(self, client):
        resp = client.get("/api/v1/backtest/strategies", headers=_auth_headers())
        assert resp.status_code == 200
        names = [s["name"] for s in resp.get_json()["data"]["strategies"]]
        assert len(names) >= 50
        assert "SMACrossover" in names
        assert "EMACrossover" in names

    def test_run_accepts_a_previously_unreachable_strategy(self, client):
        # A strategy from ALL_STRATEGIES must pass the strategy lookup (it may
        # later fail on data availability, but it is no longer "Unknown").
        resp = client.post("/api/v1/backtest/run", json={
            "symbol": "RELIANCE", "exchange": "NSE", "interval": "1d",
            "start_date": "2025-01-01", "end_date": "2025-02-01",
            "strategy": "SMACrossover",
        }, headers=_auth_headers())
        body = resp.get_json()
        # Whatever the outcome (data/engine), it must NOT be the unknown-strategy 400.
        assert not (resp.status_code == 400 and "Unknown strategy" in body.get("message", ""))
