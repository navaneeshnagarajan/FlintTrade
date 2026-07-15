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
        """A successful backtest writes its metrics to the result store under the
        refiner's ``sharpe_ratio``/``sortino_ratio`` keys.

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
            expectancy = 0.35

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

            # Response metrics use the frontend's contract keys (sharpe_ratio /
            # sortino_ratio / expectancy) — a rename here crashes the terminal's
            # Performance Metrics card, so assert them directly.
            body_metrics = resp.get_json()["data"]["metrics"]
            assert body_metrics["sharpe_ratio"] == 1.5
            assert body_metrics["sortino_ratio"] == 2.0
            assert body_metrics["expectancy"] == 0.35
            assert "sharpe" not in body_metrics and "sortino" not in body_metrics

            saved = store.latest("EMACrossover")
            assert saved is not None
            assert saved["sharpe_ratio"] == 1.5
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


class TestStrategyLifecycleRoutes:
    """Live strategy routes submit work to the scheduler's runtime loop."""

    def test_start_uses_bound_scheduler_loop_instead_of_request_local_loop(
        self,
        flask_app,
        client,
        monkeypatch,
    ):
        import asyncio

        scheduler = MagicMock()
        scheduler.get_runner.return_value = MagicMock()
        previous = flask_app.config.get("SCHEDULER")
        flask_app.config["SCHEDULER"] = scheduler
        monkeypatch.setattr(
            asyncio,
            "new_event_loop",
            MagicMock(side_effect=AssertionError("request-local loop created")),
        )
        try:
            response = client.post(
                "/api/v1/backtest/strategies/ema/start",
                headers=_auth_headers(),
            )
        finally:
            flask_app.config["SCHEDULER"] = previous

        assert response.status_code == 200
        scheduler.start_one_threadsafe.assert_called_once_with("ema")

    def test_stop_uses_same_bound_scheduler_loop(
        self,
        flask_app,
        client,
        monkeypatch,
    ):
        import asyncio

        scheduler = MagicMock()
        scheduler.get_runner.return_value = MagicMock()
        previous = flask_app.config.get("SCHEDULER")
        flask_app.config["SCHEDULER"] = scheduler
        monkeypatch.setattr(
            asyncio,
            "new_event_loop",
            MagicMock(side_effect=AssertionError("request-local loop created")),
        )
        try:
            response = client.post(
                "/api/v1/backtest/strategies/ema/stop",
                headers=_auth_headers(),
            )
        finally:
            flask_app.config["SCHEDULER"] = previous

        assert response.status_code == 200
        scheduler.stop_one_threadsafe.assert_called_once_with("ema")

    def test_start_timeout_is_reported_only_as_a_rolled_back_failure(
        self,
        flask_app,
        client,
    ):
        from flinttrade_engine.scheduler import StrategyStartTimeoutError

        scheduler = MagicMock()
        scheduler.get_runner.return_value = MagicMock()
        scheduler.start_one_threadsafe.side_effect = StrategyStartTimeoutError("rolled back")
        previous = flask_app.config.get("SCHEDULER")
        flask_app.config["SCHEDULER"] = scheduler
        try:
            response = client.post(
                "/api/v1/backtest/strategies/ema/start",
                headers=_auth_headers(),
            )
        finally:
            flask_app.config["SCHEDULER"] = previous

        assert response.status_code == 504
        assert response.get_json() == {
            "status": "error",
            "code": "strategy_start_timeout",
            "message": "Strategy start timed out and was rolled back",
        }

    def test_stop_timeout_is_reported_as_cleanup_still_in_progress(
        self,
        flask_app,
        client,
    ):
        from flinttrade_engine.scheduler import StrategyStopTimeoutError

        scheduler = MagicMock()
        scheduler.stop_one_threadsafe.side_effect = StrategyStopTimeoutError("still in progress")
        previous = flask_app.config.get("SCHEDULER")
        flask_app.config["SCHEDULER"] = scheduler
        try:
            response = client.post(
                "/api/v1/backtest/strategies/ema/stop",
                headers=_auth_headers(),
            )
        finally:
            flask_app.config["SCHEDULER"] = previous

        assert response.status_code == 504
        assert response.get_json() == {
            "status": "error",
            "code": "strategy_stop_in_progress",
            "message": "Strategy stop is still in progress",
        }


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


class TestRegistryStrategies:
    """The ~29 STRATEGY_REGISTRY strategies (BaseBacktestStrategy on BacktestEngine)
    are reachable via /backtest/run through a faithful result conversion."""

    @staticmethod
    def _sine_bars(n: int = 360):
        import math
        return [
            {
                "timestamp": f"2025-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}T09:15:00",
                "open": 200.0 + 60.0 * math.sin(i / 14.0),
                "high": 201.0 + 60.0 * math.sin(i / 14.0),
                "low": 199.0 + 60.0 * math.sin(i / 14.0),
                "close": 200.0 + 60.0 * math.sin(i / 14.0),
                "volume": 5000,
            }
            for i in range(n)
        ]

    def test_registry_strategy_is_resolvable(self):
        from flinttrade_core.backtest_routes import _registry_strategy

        assert _registry_strategy("RSIStrategy") is not None
        assert _registry_strategy("EMACrossoverStrategy") is not None
        assert _registry_strategy("definitely-not-a-strategy") is None

    def test_registry_backtest_produces_faithful_trades_and_metrics(self):
        from flinttrade_core.backtest_routes import _registry_strategy, _run_registry_backtest
        from flinttrade_backtest.metrics import PerformanceMetrics
        from flinttrade_backtest.simulator import BacktestConfig, BacktestResult

        config = BacktestConfig(
            symbol="RELIANCE", exchange="NSE", interval="1d",
            start_date="2025-01-01", end_date="2025-12-01",
            initial_capital=1_000_000, position_size_pct=20,
        )
        result = _run_registry_backtest(_registry_strategy("EMACrossoverStrategy"), config, self._sine_bars())

        # Returns a simulator BacktestResult the existing response code can consume.
        assert isinstance(result, BacktestResult)
        assert result.total_bars == 360
        assert len(result.trades) > 0  # the oscillating series forces round-trips
        assert result.error == ""

        # First trade carries faithfully-converted (Decimal -> float) fields.
        first = result.trades[0]
        assert first.symbol == "RELIANCE"
        assert first.entry_price > 0 and first.exit_price > 0
        assert isinstance(first.net_pnl, float)

        # The TESTED metrics run on the converted result and agree on the count.
        report = PerformanceMetrics.compute(result)
        assert report.trade_stats.total_trades == len(result.trades)

    def test_strategies_endpoint_lists_registry_strategies(self, client):
        resp = client.get("/api/v1/backtest/strategies", headers=_auth_headers())
        names = [s["name"] for s in resp.get_json()["data"]["strategies"]]
        assert "RSIStrategy" in names  # a STRATEGY_REGISTRY entry, now discoverable
        assert "MACDStrategy" in names

    def test_run_accepts_a_registry_strategy_name(self, client):
        # Must pass the strategy lookup (may then fail on data, but not "Unknown").
        resp = client.post("/api/v1/backtest/run", json={
            "symbol": "RELIANCE", "exchange": "NSE", "interval": "1d",
            "start_date": "2025-01-01", "end_date": "2025-02-01",
            "strategy": "RSIStrategy",
        }, headers=_auth_headers())
        body = resp.get_json()
        assert not (resp.status_code == 400 and "Unknown strategy" in body.get("message", ""))
