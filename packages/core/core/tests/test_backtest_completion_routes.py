"""Mounted backtest acceptance with real loaders, engines, metrics and storage.

Only historical input, public strategy entries and a targeted metric failure
are injected. No application server, runtime lease or provider is started.
"""

from __future__ import annotations

import pytest

from flinttrade_backtest.base_strategy import BaseBacktestStrategy
from flinttrade_backtest.data_connector import DataConnector, DataResult
from flinttrade_backtest.engine import BacktestEngine, OrderSide, OrderStatus
from flinttrade_backtest.metrics import PerformanceMetrics
from flinttrade_backtest.result_store import BacktestResultStore
from flinttrade_backtest.strategies import BUILTIN_STRATEGIES, STRATEGY_REGISTRY
from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

pytestmark = pytest.mark.integration

_API_KEY = "synthetic-backtest-completion-key"
_NAME = "CompletionEvidence"
_BODY = {
    "symbol": "TEST", "exchange": "NSE", "interval": "1d",
    "start_date": "2025-01-01", "end_date": "2025-01-03",
    "strategy": _NAME, "initial_capital": 1000, "position_size_pct": 10,
}


class RoundTripStrategy(BaseStrategy):
    def __init__(self, name: str, exchange: str, symbol: str) -> None:
        super().__init__(name=name, exchange=exchange)
        self.symbol = symbol
        self.seen = 0

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_signal(self, signal: dict) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self.seen += 1

    def generate_orders(self) -> list[Order]:
        if self.seen > 2:
            return []
        return [Order(symbol=self.symbol, action="BUY" if self.seen == 1 else "SELL", quantity="1")]


class FailingBarStrategy(RoundTripStrategy):
    def on_bar(self, bar: OHLCV) -> None:
        super().on_bar(bar)
        if self.seen == 2:
            raise RuntimeError("synthetic callback failure")


@pytest.fixture
def mounted(monkeypatch, tmp_path):
    monkeypatch.setenv("FLINTTRADE_API_KEY", _API_KEY)
    from flinttrade_core.app import create_flask_app

    loaded = []

    def load(self, symbol, exchange, interval, start_date, end_date):
        assert (symbol, exchange, interval, start_date, end_date) == (
            "TEST", "NSE", "1d", "2025-01-01", "2025-01-03",
        )
        loaded.append(symbol)
        return DataResult(bars=[
            {"timestamp": f"2025-01-0{i}", "open": price, "high": price + 1, "low": price - 1,
             "close": price, "volume": 1000}
            for i, price in enumerate((100, 110, 999), 1)
        ], symbol=symbol, exchange=exchange, interval=interval, source="synthetic-test")

    monkeypatch.setattr(DataConnector, "load", load)
    monkeypatch.setitem(BUILTIN_STRATEGIES, _NAME, RoundTripStrategy)
    app = create_flask_app()
    app.config["TESTING"] = True
    store = BacktestResultStore(tmp_path / "results")
    app.config["BACKTEST_RESULT_STORE"] = store
    with app.test_client() as client:
        yield client, store, loaded


def post(client):
    return client.post("/api/v1/backtest/run", json=_BODY, headers={"X-API-Key": _API_KEY})


def test_failed_simulation_never_scores_or_overwrites_success(mounted, monkeypatch):
    client, store, loaded = mounted
    good = post(client)
    assert good.status_code == 200
    prior = store.record(_NAME)
    assert prior is not None
    assert store.latest(_NAME) == good.get_json()["data"]["metrics"]

    monkeypatch.setitem(BUILTIN_STRATEGIES, _NAME, FailingBarStrategy)
    scored = []

    def forbidden_metrics(result):
        scored.append(result)
        raise AssertionError("failed simulation must not be scored")

    monkeypatch.setattr(PerformanceMetrics, "compute", forbidden_metrics)
    failed = post(client)
    assert failed.status_code == 500
    assert failed.get_json()["status"] == "error"
    assert "data" not in failed.get_json()
    assert scored == []
    assert loaded == ["TEST", "TEST"]
    assert store.record(_NAME) == prior
    assert store.latest(_NAME) == prior["metrics"]


@pytest.mark.parametrize("branch", ["simulator", "registry"])
def test_metrics_failure_never_overwrites_success(mounted, monkeypatch, branch):
    client, store, loaded = mounted
    if branch == "registry":
        monkeypatch.delitem(BUILTIN_STRATEGIES, _NAME)
        monkeypatch.setitem(STRATEGY_REGISTRY, _NAME, RegistryRoundTrip)
    good = post(client)
    assert good.status_code == 200
    prior = store.record(_NAME)
    assert prior is not None
    scored = []

    def broken_metrics(result):
        scored.append(result)
        raise RuntimeError("synthetic metric failure")

    monkeypatch.setattr(PerformanceMetrics, "compute", broken_metrics)
    failed = post(client)
    assert failed.status_code == 500
    assert failed.get_json()["status"] == "error"
    assert "data" not in failed.get_json()
    assert len(scored) == 1
    assert scored[0].error == ""
    assert scored[0].total_bars == 3
    assert len(scored[0].trades) == 1
    assert loaded == ["TEST", "TEST"]
    assert store.record(_NAME) == prior
    assert store.latest(_NAME) == prior["metrics"]


def assert_success_contract(response, store):
    assert response.status_code == 200
    body = response.get_json()
    assert set(body) == {"status", "data"}
    assert body["status"] == "success"
    data = body["data"]
    assert set(data) == {"trades", "equity_curve", "metrics", "total_bars", "final_equity"}
    assert set(data["metrics"]) == {
        "total_return", "cagr", "sharpe_ratio", "sortino_ratio", "max_drawdown",
        "win_rate", "profit_factor", "total_trades", "expectancy",
    }
    assert data["total_bars"] == 3
    assert [point["timestamp"] for point in data["equity_curve"]] == [
        "2025-01-01", "2025-01-02", "2025-01-03",
    ]
    assert all(set(point) == {"timestamp", "equity", "cash", "drawdown"} for point in data["equity_curve"])
    for trade in data["trades"]:
        assert set(trade) == {
            "entry_timestamp", "exit_timestamp", "symbol", "side", "quantity", "entry_price",
            "exit_price", "pnl", "net_pnl", "commission", "bars_held",
        }
    assert store.latest(_NAME) == data["metrics"]
    record = store.record(_NAME)
    assert record["strategy"] == _NAME
    assert record["metrics"] == data["metrics"]
    assert record["context"] == {key: _BODY[key] for key in (
        "symbol", "exchange", "interval", "start_date", "end_date",
    )}
    return data


def test_successful_simulator_response_and_store_keep_real_evidence(mounted):
    client, store, loaded = mounted
    data = assert_success_contract(post(client), store)
    assert loaded == ["TEST"]
    assert len(data["trades"]) == data["metrics"]["total_trades"] == 1
    trade = data["trades"][0]
    assert trade["entry_timestamp"] == "2025-01-01"
    assert trade["exit_timestamp"] == "2025-01-02"
    assert trade["entry_price"] == pytest.approx(100.05)
    assert trade["exit_price"] == pytest.approx(109.945)
    # Preserve the existing model, not a claim that its fee accounting is qualified.
    assert data["final_equity"] == pytest.approx(969.895)
    assert [point["equity"] for point in data["equity_curve"]] == pytest.approx([979.95, 969.895, 969.895])


class RegistryRoundTrip(BaseBacktestStrategy):
    failure = ""

    def __init__(self, symbol: str) -> None:
        super().__init__(name=_NAME, symbol=symbol)
        self.seen = []

    def set_engine(self, engine) -> None:
        super().set_engine(engine)
        self.bound_engine = engine

    def start(self) -> None:
        super().start()
        if self.failure == "start":
            raise RuntimeError("registry startup failed")

    def stop(self) -> None:
        super().stop()
        if self.failure == "stop":
            raise RuntimeError("registry cleanup failed")

    def on_bar(self, bar) -> None:
        self.seen.append(bar.timestamp)
        if len(self.seen) == 1:
            self.enter_long(quantity=1)
        elif len(self.seen) == 2:
            if self.failure == "bar":
                raise RuntimeError("registry bar failed")
            if self.failure == "early_stop":
                self.bound_engine.stop()
                return
            self.exit_position()

    def generate_orders(self):
        if self.failure == "orders" and len(self.seen) == 2:
            raise RuntimeError("registry orders failed")
        return super().generate_orders()


@pytest.mark.parametrize("failure", ["bar", "orders", "early_stop", "start", "stop"])
def test_registry_failures_never_score_or_overwrite_success(mounted, monkeypatch, failure):
    client, store, loaded = mounted
    instances = []

    class Strategy(RegistryRoundTrip):
        def __init__(self, symbol):
            super().__init__(symbol)
            instances.append(self)

    monkeypatch.delitem(BUILTIN_STRATEGIES, _NAME)
    monkeypatch.setitem(STRATEGY_REGISTRY, _NAME, Strategy)
    good = assert_success_contract(post(client), store)
    assert len(good["trades"]) == good["metrics"]["total_trades"] == 1
    assert isinstance(instances[0].bound_engine, BacktestEngine)
    prior = store.record(_NAME)
    monkeypatch.setattr(Strategy, "failure", failure)
    scored = []

    def forbidden_metrics(result):
        scored.append(result)
        raise AssertionError("failed registry simulation must not be scored")

    monkeypatch.setattr(PerformanceMetrics, "compute", forbidden_metrics)
    failed = post(client)
    assert failed.status_code == 500
    assert failed.get_json() == {"status": "error", "message": "Backtest did not complete"}
    assert scored == []
    assert loaded == ["TEST", "TEST"]
    assert len(instances) == 2
    assert isinstance(instances[1].bound_engine, BacktestEngine)
    if failure in {"bar", "orders", "early_stop"}:
        assert instances[1].seen == ["2025-01-01", "2025-01-02"]
        position = instances[1].bound_engine.get_position("TEST")
        assert position is not None
        assert float(position.last_price) == 110
    assert store.record(_NAME) == prior
    assert store.latest(_NAME) == prior["metrics"]


@pytest.mark.parametrize("branch", ["simulator", "registry"])
def test_completed_no_order_run_is_valid_evidence(mounted, monkeypatch, branch):
    client, store, loaded = mounted
    if branch == "simulator":
        class NoSimulatorOrders(RoundTripStrategy):
            def generate_orders(self):
                return []

        monkeypatch.setitem(BUILTIN_STRATEGIES, _NAME, NoSimulatorOrders)
    else:
        class NoRegistryOrders(BaseBacktestStrategy):
            def on_bar(self, bar):
                pass

        monkeypatch.delitem(BUILTIN_STRATEGIES, _NAME)
        monkeypatch.setitem(STRATEGY_REGISTRY, _NAME, NoRegistryOrders)
    data = assert_success_contract(post(client), store)
    assert loaded == ["TEST"]
    assert data["trades"] == []
    assert data["metrics"]["total_trades"] == 0
    assert data["final_equity"] == 1000
    assert all(point["equity"] == 1000 for point in data["equity_curve"])


@pytest.mark.parametrize("failure", ["entry_order", "closing_order", "trade", "liquidation"])
def test_registry_notification_failure_never_scores_or_overwrites_success(mounted, monkeypatch, failure):
    client, store, loaded = mounted
    instances = []

    class Strategy(RegistryRoundTrip):
        notification_failure = ""

        def __init__(self, symbol):
            super().__init__(symbol)
            self.updates = []
            self.trades = []
            self.stopped = False
            instances.append(self)

        def on_bar(self, bar):
            if failure == "liquidation":
                self.seen.append(bar.timestamp)
                if len(self.seen) == 1:
                    self.enter_long(quantity=1)
            else:
                super().on_bar(bar)

        def on_order_update(self, order):
            self.updates.append(order)
            if (self.notification_failure == "entry_order"
                    or self.notification_failure == "closing_order" and order.side == OrderSide.SELL):
                raise RuntimeError("registry order notification failed")

        def on_trade(self, trade):
            self.trades.append(trade)
            if self.notification_failure in {"trade", "liquidation"}:
                raise RuntimeError("registry trade notification failed")

        def stop(self):
            self.stopped = True
            super().stop()

    monkeypatch.delitem(BUILTIN_STRATEGIES, _NAME)
    monkeypatch.setitem(STRATEGY_REGISTRY, _NAME, Strategy)
    scored = []
    compute = PerformanceMetrics.compute

    def observed_metrics(result):
        scored.append(result)
        return compute(result)

    monkeypatch.setattr(PerformanceMetrics, "compute", observed_metrics)
    good = assert_success_contract(post(client), store)
    assert len(scored) == 1 and scored[0].error == ""
    assert len(good["trades"]) == good["metrics"]["total_trades"] == 1
    prior = store.record(_NAME)
    monkeypatch.setattr(Strategy, "notification_failure", failure)
    failed = post(client)
    assert len(instances) == 2
    strategy = instances[-1]
    assert isinstance(strategy.bound_engine, BacktestEngine)
    assert strategy.updates, "the public strategy callback must actually be reached"
    assert failed.status_code == 500
    assert failed.get_json() == {"status": "error", "message": "Backtest did not complete"}
    assert len(scored) == 1
    expected_seen = {
        "entry_order": ["2025-01-01"],
        "closing_order": ["2025-01-01", "2025-01-02"],
        "trade": ["2025-01-01", "2025-01-02"],
        "liquidation": ["2025-01-01", "2025-01-02", "2025-01-03"],
    }
    assert strategy.seen == expected_seen[failure]
    assert strategy.stopped
    if failure == "entry_order":
        assert strategy.bound_engine.get_position("TEST") is not None
        assert strategy.trades == []
    else:
        assert strategy.bound_engine.get_position("TEST") is None
        assert len(strategy.trades) == 1
        if failure == "closing_order":
            assert strategy.updates[-1].status == OrderStatus.FILLED
    assert loaded == ["TEST", "TEST"]
    assert store.record(_NAME) == prior
    assert store.latest(_NAME) == prior["metrics"]
