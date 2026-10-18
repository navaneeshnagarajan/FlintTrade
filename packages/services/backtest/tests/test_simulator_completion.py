"""Completion truth at the public simulator boundary, using synthetic bars only.

``total_bars`` counts completed iterations, not attempts. Pending fills on a
failed attempt remain evidence; its marked equity is not a completed bar.
"""

from __future__ import annotations

import pytest

from flinttrade_backtest.simulator import BacktestConfig, BacktestSimulator
from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

pytestmark = pytest.mark.unit


def bars(suffix: float = 999.0) -> list[dict]:
    return [
        {"timestamp": "2025-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
        {"timestamp": "2025-01-02", "open": 106, "high": 111, "low": 104, "close": 110, "volume": 1000},
        {"timestamp": "2025-01-03", "open": suffix, "high": suffix, "low": suffix,
         "close": suffix, "volume": 1000},
    ]


class FailingBarStrategy(BaseStrategy):
    def __init__(self, order_type: str = "MARKET") -> None:
        super().__init__(name="completion-test")
        self.order_type = order_type
        self.seen: list[str] = []
        self.stopped = False

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_signal(self, signal: dict) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self.seen.append(bar.timestamp)
        if len(self.seen) == 2:
            raise RuntimeError("bar failed")

    def generate_orders(self) -> list[Order]:
        return [Order(symbol="TEST", action="BUY", quantity="1", pricetype=self.order_type, price="105")]

    def stop(self) -> None:
        self.stopped = True
        super().stop()


def simulator() -> BacktestSimulator:
    return BacktestSimulator(BacktestConfig(
        symbol="TEST", initial_capital=1000, slippage_pct=0, commission_per_order=0,
    ))


@pytest.mark.parametrize(("order_type", "fill_price", "final_equity"), [
    ("MARKET", 100, 1010),
    ("LIMIT", 105, 1005),
])
def test_failed_bar_preserves_reached_fills_without_suffix_valuation(order_type, fill_price, final_equity):
    results = []
    for suffix in (999.0, 1.0):
        strategy = FailingBarStrategy(order_type)
        result = simulator().run(strategy, bars(suffix))
        assert "bar failed" in result.error
        assert result.total_bars == 1
        assert strategy.seen == ["2025-01-01", "2025-01-02"]
        assert strategy.stopped
        assert result.trades == []  # No invented liquidation on failure.
        assert len(result.orders) == 1
        assert result.orders[0].status == "FILLED"
        assert result.orders[0].fill_price == fill_price
        assert result.orders[0].fill_timestamp == ("2025-01-01" if order_type == "MARKET" else "2025-01-02")
        assert [point.timestamp for point in result.equity_curve] == ["2025-01-01", "2025-01-02"]
        assert result.equity_curve[-1].equity == final_equity
        assert result.final_equity == final_equity
        results.append(result)
    assert results[0] == results[1]


class FailingOrdersStrategy(FailingBarStrategy):
    def on_bar(self, bar: OHLCV) -> None:
        self.seen.append(bar.timestamp)

    def generate_orders(self) -> list[Order]:
        if len(self.seen) == 2:
            raise RuntimeError("orders failed")
        return super().generate_orders()


def test_order_generation_failure_is_terminal():
    results = []
    for suffix in (999.0, 1.0):
        strategy = FailingOrdersStrategy()
        result = simulator().run(strategy, bars(suffix))
        assert "orders failed" in result.error
        assert result.total_bars == 1
        assert strategy.seen == ["2025-01-01", "2025-01-02"]
        assert strategy.stopped
        assert result.trades == []
        assert len(result.orders) == 1
        assert result.final_equity == 1010
        results.append(result)
    assert results[0] == results[1]


class LifecycleStrategy(FailingBarStrategy):
    def __init__(self, failure: str, cleanup_fails: bool) -> None:
        super().__init__()
        self.failure = failure
        self.cleanup_fails = cleanup_fails

    def start(self) -> None:
        super().start()
        if self.failure == "start":
            raise RuntimeError("startup failed")

    def on_bar(self, bar: OHLCV) -> None:
        if self.failure == "bar":
            super().on_bar(bar)
        else:
            self.seen.append(bar.timestamp)

    def generate_orders(self) -> list[Order]:
        return super().generate_orders() if len(self.seen) == 1 else []

    def stop(self) -> None:
        super().stop()
        if self.cleanup_fails:
            raise RuntimeError("cleanup failed")


@pytest.mark.parametrize(("failure", "cleanup_fails", "message", "completed"), [
    ("start", False, "startup failed", 0),
    ("start", True, "startup failed", 0),
    ("bar", True, "bar failed", 1),
    ("stop", True, "cleanup failed", 3),
])
def test_lifecycle_failure_returns_evidence_without_masking_first_failure(failure, cleanup_fails, message, completed):
    strategy = LifecycleStrategy(failure, cleanup_fails)
    result = simulator().run(strategy, bars(120))
    assert message in result.error
    assert result.total_bars == completed
    assert strategy.stopped
    assert result.trades == []
    if failure == "start":
        assert strategy.seen == []
        assert result.orders == []
        assert result.equity_curve == []
        assert result.final_equity == 1000
    else:
        assert len(result.orders) == 1
        assert result.orders[0].status == "FILLED"
        assert result.final_equity == (1010 if failure == "bar" else 1020)


def test_completed_trade_on_failed_attempt_is_not_rewound():
    class ReachedExit(FailingBarStrategy):
        def generate_orders(self):
            return [
                Order(symbol="TEST", action="BUY", quantity="1"),
                Order(symbol="TEST", action="SELL", quantity="1", pricetype="LIMIT", price="110"),
            ]

    results = [simulator().run(ReachedExit(), bars(suffix)) for suffix in (999, 1)]
    for result in results:
        assert "bar failed" in result.error
        assert result.total_bars == 1
        assert len(result.trades) == 1
        assert result.trades[0].exit_timestamp == "2025-01-02"
        assert result.trades[0].exit_price == 110
        assert [order.status for order in result.orders] == ["FILLED", "FILLED"]
        assert result.final_equity == 1010
    assert results[0] == results[1]


def test_completed_no_order_run_is_successful():
    class NoOrders(FailingBarStrategy):
        def on_bar(self, bar):
            self.seen.append(bar.timestamp)

        def generate_orders(self):
            return []

    strategy = NoOrders()
    result = simulator().run(strategy, bars())
    assert result.error == ""
    assert result.total_bars == 3
    assert strategy.stopped
    assert result.orders == result.trades == []
    assert len(result.equity_curve) == 3
    assert result.final_equity == 1000
