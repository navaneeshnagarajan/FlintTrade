"""Decimal engine completion evidence; no accounting-model changes are asserted.

Completed iterations exclude a failed attempt, but orders already filled on
that attempt and its marked equity remain observable. Untouched bars cannot
change partial evidence. The mounted registry route uses this public engine.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from flinttrade_backtest.base_strategy import BaseBacktestStrategy
from flinttrade_backtest.engine import BacktestEngine, EngineConfig, EngineOrder, FillMode, OrderSide, OrderStatus

pytestmark = pytest.mark.unit


def bars(suffix: float = 999) -> list[dict]:
    return [
        {"timestamp": "2025-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000},
        {"timestamp": "2025-01-02", "open": 106, "high": 111, "low": 104, "close": 110, "volume": 1000},
        {"timestamp": "2025-01-03", "open": suffix, "high": suffix, "low": suffix,
         "close": suffix, "volume": 1000},
    ]


class FailingBarStrategy(BaseBacktestStrategy):
    def __init__(self) -> None:
        super().__init__(name="engine-completion", symbol="TEST")
        self.seen: list[str] = []
        self.stopped = False

    def on_bar(self, bar) -> None:
        self.seen.append(bar.timestamp)
        if len(self.seen) == 2:
            raise RuntimeError("bar failed")
        self.enter_long(quantity=1)

    def stop(self) -> None:
        self.stopped = True
        super().stop()


def engine(strategy, mode=FillMode.NEXT_OPEN) -> BacktestEngine:
    instance = BacktestEngine(EngineConfig(
        symbol="TEST", initial_capital=Decimal(1000), slippage_bps=Decimal(0),
        commission_per_order=Decimal(0), tax_enabled=False, fill_mode=mode,
    ))
    instance.set_strategy(strategy)
    return instance


def evidence(result):
    """Stable public evidence excluding generated IDs and execution duration."""
    return (
        result.error, result.total_bars, result.final_equity, result.equity_curve,
        [(order.symbol, order.side, order.status, order.filled_quantity, order.avg_fill_price,
          order.submitted_at, order.filled_at) for order in result.orders],
        [(trade.symbol, trade.entry_price, trade.exit_price, trade.entry_time,
          trade.exit_time, trade.net_pnl) for trade in result.trades],
    )


@pytest.mark.parametrize(("mode", "fill_price"), [(FillMode.NEXT_OPEN, 106), (FillMode.CURRENT_CLOSE, 100)])
def test_failed_bar_keeps_reached_fills_and_is_invariant_to_suffix(mode, fill_price):
    results = []
    for suffix in (999, 1):
        strategy = FailingBarStrategy()
        instance = engine(strategy, mode)
        result = instance.run(bars(suffix))
        assert "bar failed" in result.error
        assert result.total_bars == 1
        assert strategy.seen == ["2025-01-01", "2025-01-02"]
        assert strategy.stopped
        assert result.trades == []
        assert len(result.orders) == 1
        assert result.orders[0].status == OrderStatus.FILLED
        assert result.orders[0].filled_quantity == 1
        assert result.orders[0].avg_fill_price == Decimal(fill_price)
        position = instance.get_position("TEST")
        assert position is not None
        assert position.last_price == Decimal(110)
        assert [point.timestamp for point in result.equity_curve] == ["2025-01-01", "2025-01-02"]
        assert result.final_equity == result.equity_curve[-1].equity == instance.get_equity()
        results.append(evidence(result))
    assert results[0] == results[1]


class FailingOrdersStrategy(FailingBarStrategy):
    def on_bar(self, bar) -> None:
        self.seen.append(bar.timestamp)
        if len(self.seen) == 1:
            self.enter_long(quantity=1)

    def generate_orders(self):
        if len(self.seen) == 2:
            raise RuntimeError("orders failed")
        return super().generate_orders()


def test_order_failure_keeps_pending_fill_and_terminates_run():
    results = []
    for suffix in (999, 1):
        strategy = FailingOrdersStrategy()
        instance = engine(strategy)
        result = instance.run(bars(suffix))
        assert "orders failed" in result.error
        assert result.total_bars == 1
        assert strategy.seen == ["2025-01-01", "2025-01-02"]
        assert strategy.stopped
        assert result.trades == []
        assert result.orders[0].status == OrderStatus.FILLED
        assert result.orders[0].avg_fill_price == Decimal(106)
        assert instance.get_position("TEST") is not None
        assert result.final_equity == result.equity_curve[-1].equity == instance.get_equity()
        results.append(evidence(result))
    assert results[0] == results[1]


class StoppingStrategy(FailingOrdersStrategy):
    def set_engine(self, engine) -> None:
        super().set_engine(engine)
        self.request_stop = engine.stop

    def on_bar(self, bar) -> None:
        super().on_bar(bar)
        if len(self.seen) == 2:
            self.request_stop()

    def generate_orders(self):
        return BaseBacktestStrategy.generate_orders(self)


def test_early_stop_is_partial_without_liquidating_or_visiting_suffix():
    results = []
    for suffix in (999, 1):
        strategy = StoppingStrategy()
        instance = engine(strategy)
        result = instance.run(bars(suffix))
        assert "stopped" in result.error.lower()
        assert result.total_bars == 2  # stop() takes effect at the next loop boundary.
        assert strategy.seen == ["2025-01-01", "2025-01-02"]
        assert strategy.stopped
        assert result.trades == []
        assert result.orders[0].status == OrderStatus.FILLED
        position = instance.get_position("TEST")
        assert position is not None
        assert position.last_price == Decimal(110)
        results.append(evidence(result))
    assert results[0] == results[1]


class LifecycleStrategy(FailingBarStrategy):
    def __init__(self, fail_on_bar: bool) -> None:
        super().__init__()
        self.fail_on_bar = fail_on_bar

    def on_bar(self, bar) -> None:
        if self.fail_on_bar:
            super().on_bar(bar)
        else:
            self.seen.append(bar.timestamp)
            if len(self.seen) == 1:
                self.enter_long(quantity=1)

    def stop(self) -> None:
        super().stop()
        raise RuntimeError("cleanup failed")


@pytest.mark.parametrize("fail_on_bar", [True, False])
def test_cleanup_failure_keeps_original_failure_and_open_exposure(fail_on_bar):
    strategy = LifecycleStrategy(fail_on_bar)
    instance = engine(strategy)
    result = instance.run(bars(120))
    assert ("bar failed" if fail_on_bar else "cleanup failed") in result.error
    assert result.total_bars == (1 if fail_on_bar else 3)
    assert strategy.stopped
    assert result.trades == []
    assert len(result.orders) == 1
    assert result.orders[0].status == OrderStatus.FILLED
    assert instance.get_position("TEST") is not None


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_start_failure_returns_zero_coverage_and_survives_cleanup_failure(cleanup_fails):
    class FailingStartStrategy(FailingBarStrategy):
        def start(self) -> None:
            super().start()
            raise RuntimeError("startup failed")

        def stop(self) -> None:
            super().stop()
            if cleanup_fails:
                raise RuntimeError("cleanup failed")

    strategy = FailingStartStrategy()
    result = engine(strategy).run(bars())
    assert "startup failed" in result.error
    assert result.total_bars == 0
    assert strategy.seen == []
    assert strategy.stopped
    assert result.orders == result.trades == result.equity_curve == []
    assert result.final_equity == Decimal(1000)


def test_completed_trade_on_failed_attempt_is_not_rewound():
    class ReachedExit(FailingBarStrategy):
        def on_bar(self, bar):
            self.seen.append(bar.timestamp)
            if len(self.seen) == 1:
                self.enter_long(quantity=1)
            elif len(self.seen) == 2:
                self.exit_position()
            else:
                raise RuntimeError("bar failed after exit fill")

    results = []
    for suffix in (999, 1):
        history = bars(120)
        history.append({"timestamp": "2025-01-04", "open": suffix, "high": suffix, "low": suffix,
                        "close": suffix, "volume": 1000})
        strategy = ReachedExit()
        instance = engine(strategy)
        result = instance.run(history)
        assert "bar failed after exit fill" in result.error
        assert result.total_bars == 2
        assert len(result.trades) == 1
        assert result.trades[0].exit_price == Decimal(120)
        assert str(result.trades[0].exit_time) == "2025-01-03 00:00:00"
        assert [order.status for order in result.orders] == [OrderStatus.FILLED, OrderStatus.FILLED]
        assert instance.get_position("TEST") is None
        results.append(evidence(result))
    assert results[0] == results[1]


@pytest.mark.parametrize("empty", [True, False])
def test_empty_input_is_error_but_completed_no_order_run_is_valid(empty):
    class NoOrders(BaseBacktestStrategy):
        def on_bar(self, bar):
            pass

    result = engine(NoOrders(symbol="TEST")).run([] if empty else bars())
    assert result.error == ("No bars provided" if empty else "")
    assert result.total_bars == (0 if empty else 3)
    assert result.orders == result.trades == []
    assert len(result.equity_curve) == (0 if empty else 3)
    assert result.final_equity == Decimal(1000)


class EntryNotificationFailure(FailingBarStrategy):
    def __init__(self, cleanup_fails=False) -> None:
        super().__init__()
        self.cleanup_fails = cleanup_fails
        self.updates = []
        self.generated = []

    def on_bar(self, bar) -> None:
        self.seen.append(bar.timestamp)
        if len(self.seen) == 1:
            self.enter_long(quantity=1)
            self.enter_long(quantity=1, symbol="UNREACHED")

    def generate_orders(self):
        self.generated.append(self.seen[-1])
        return super().generate_orders()

    def on_order_update(self, order) -> None:
        self.updates.append(order)
        raise RuntimeError("entry notification failed")

    def stop(self) -> None:
        super().stop()
        if self.cleanup_fails:
            raise RuntimeError("cleanup failed")


@pytest.mark.parametrize("mode", [FillMode.NEXT_OPEN, FillMode.CURRENT_CLOSE])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_entry_notification_failure_stops_at_executed_fill(mode, cleanup_fails):
    results = []
    for suffix in (999, 1):
        strategy = EntryNotificationFailure(cleanup_fails)
        instance = engine(strategy, mode)
        instance.config.commission_per_order = Decimal(2)
        history = bars(suffix)
        if mode == FillMode.CURRENT_CLOSE:
            history[1] = {**history[1], "open": suffix, "close": suffix}
        result = instance.run(history)
        assert "on_order_update" in result.error
        assert "entry notification failed" in result.error
        assert "cleanup failed" not in result.error
        next_open = mode == FillMode.NEXT_OPEN
        assert result.total_bars == (1 if next_open else 0)
        assert strategy.seen == strategy.generated == ["2025-01-01"]
        assert strategy.stopped
        assert len(strategy.updates) == 1
        assert len(result.orders) == 2
        filled, untouched = result.orders
        assert strategy.updates == [filled]
        assert filled.side == OrderSide.BUY
        assert filled.status == OrderStatus.FILLED
        assert filled.filled_quantity == 1
        assert filled.avg_fill_price == Decimal(106 if next_open else 100)
        assert str(filled.filled_at) == ("2025-01-02 00:00:00" if next_open else "2025-01-01 00:00:00")
        assert untouched.status == OrderStatus.SUBMITTED
        assert untouched.filled_quantity == 0
        assert untouched.filled_at is None
        assert strategy.get_open_orders() == [untouched]
        assert instance.get_position("UNREACHED") is None
        position = instance.get_position("TEST")
        assert position is not None and position.quantity == 1
        assert position.last_price == Decimal(110 if next_open else 100)
        assert instance.get_cash() == Decimal(892 if next_open else 898)
        assert result.trades == []
        assert [point.timestamp for point in result.equity_curve] == (
            ["2025-01-01", "2025-01-02"] if next_open else ["2025-01-01"]
        )
        assert result.final_equity == result.equity_curve[-1].equity == instance.get_equity()
        assert result.equity_curve[-1].cash == instance.get_cash()
        results.append(evidence(result))
    assert results[0] == results[1]


class ClosingNotificationStrategy(FailingBarStrategy):
    def __init__(self, callback="", close_quantity=2, short=False) -> None:
        super().__init__()
        self.callback = callback
        self.close_quantity = close_quantity
        self.short = short
        self.notifications = []

    def on_bar(self, bar) -> None:
        self.seen.append(bar.timestamp)
        if len(self.seen) == 1:
            if self.short:
                self.enter_short(quantity=2)
            else:
                self.enter_long(quantity=2)
        elif len(self.seen) == 2:
            self.exit_position(quantity=self.close_quantity)

    def on_order_update(self, order) -> None:
        self.notifications.append(("on_order_update", order.side))
        closing_side = OrderSide.BUY if self.short else OrderSide.SELL
        if self.callback and order.side == closing_side:
            raise RuntimeError("closing order notification failed")

    def on_trade(self, trade) -> None:
        self.notifications.append(("on_trade", trade.side))
        if self.callback == "on_trade":
            raise RuntimeError("closing trade notification failed")

    def stop(self) -> None:
        super().stop()
        # Also freezes the healthy control before partial terminal liquidation.
        raise RuntimeError("cleanup failed")


@pytest.mark.parametrize("mode", [FillMode.NEXT_OPEN, FillMode.CURRENT_CLOSE])
@pytest.mark.parametrize("callback", ["on_trade", "on_order_update"])
@pytest.mark.parametrize(("short", "close_quantity"), [(False, 1), (False, 2), (True, 2)])
def test_closing_notification_failure_retains_the_whole_reached_fill(mode, callback, short, close_quantity):
    next_open = mode == FillMode.NEXT_OPEN
    frontier = 3 if next_open else 2
    control_strategy = ClosingNotificationStrategy(close_quantity=close_quantity, short=short)
    control_engine = engine(control_strategy, mode)
    control_engine.config.commission_per_order = Decimal(2)
    control_engine.config.allow_short = short
    control = control_engine.run(bars(120)[:frontier])
    assert "cleanup failed" in control.error
    assert len(control.trades) == 1
    assert control.trades[0].charges == Decimal(2)

    results = []
    for suffix in (999, 1):
        history = bars(120)[:frontier]
        history.append({"timestamp": f"2025-01-0{frontier + 1}", "open": suffix, "high": suffix,
                        "low": suffix, "close": suffix, "volume": 1000})
        strategy = ClosingNotificationStrategy(callback, close_quantity, short)
        instance = engine(strategy, mode)
        instance.config.commission_per_order = Decimal(2)
        instance.config.allow_short = short
        result = instance.run(history)
        assert callback in result.error
        assert ("closing trade notification failed" if callback == "on_trade"
                else "closing order notification failed") in result.error
        assert "cleanup failed" not in result.error
        assert result.total_bars == frontier - 1
        assert strategy.seen == ["2025-01-01", "2025-01-02"]
        assert strategy.stopped
        entry_side = OrderSide.SELL if short else OrderSide.BUY
        expected_notifications = [("on_order_update", entry_side), ("on_trade", entry_side)]
        if callback == "on_order_update":
            expected_notifications.append(("on_order_update", OrderSide.BUY if short else OrderSide.SELL))
        assert strategy.notifications == expected_notifications
        assert len(result.trades) == 1
        assert len(result.orders) == 2
        assert [order.status for order in result.orders] == [OrderStatus.FILLED, OrderStatus.FILLED]
        assert result.orders[1].filled_quantity == close_quantity
        assert result.trades[0].quantity == close_quantity
        assert result.trades[0].id == result.orders[1].id
        assert str(result.trades[0].exit_time) == f"2025-01-0{frontier} 00:00:00"
        assert strategy.get_open_orders() == []
        # Callback failure must not interrupt position removal, fees or order finalisation.
        assert instance.get_cash() == control_engine.get_cash()
        assert instance.get_position("TEST") == control_engine.get_position("TEST")
        if close_quantity == 1:
            position = instance.get_position("TEST")
            assert position is not None and position.quantity == 1
        else:
            assert instance.get_position("TEST") is None
        assert result.final_equity == control.final_equity == instance.get_equity()
        assert result.equity_curve[-1] == control.equity_curve[-1]
        assert evidence(result)[4:] == evidence(control)[4:]
        results.append(evidence(result))
    assert results[0] == results[1]


@pytest.mark.parametrize("mode", [FillMode.NEXT_OPEN, FillMode.CURRENT_CLOSE])
def test_terminal_trade_notification_failure_retains_only_reached_liquidation(mode):
    class TerminalNotificationFailure(FailingBarStrategy):
        def __init__(self):
            super().__init__()
            self.trades = []
            self.stop_count = 0

        def on_bar(self, bar):
            self.seen.append(bar.timestamp)
            if len(self.seen) == 1:
                self.enter_long(quantity=1)
                self.enter_long(quantity=1, symbol="UNREACHED")

        def on_trade(self, trade):
            assert self.stopped
            self.trades.append(trade)
            raise RuntimeError("terminal trade notification failed")

        def stop(self):
            self.stop_count += 1
            super().stop()

    strategy = TerminalNotificationFailure()
    instance = engine(strategy, mode)
    instance.config.commission_per_order = Decimal(2)
    result = instance.run(bars(120))
    assert "on_trade" in result.error
    assert "terminal trade notification failed" in result.error
    assert result.total_bars == 3  # Completed bars do not imply successful finalisation.
    assert strategy.seen == ["2025-01-01", "2025-01-02", "2025-01-03"]
    assert strategy.stop_count == 1
    assert result.trades == strategy.trades
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.symbol == "TEST" and trade.quantity == 1
    assert trade.exit_price == Decimal(120)
    assert str(trade.exit_time) == "2025-01-03 00:00:00"
    assert trade.charges == Decimal(2)
    assert len(result.orders) == 2
    assert all(order.status == OrderStatus.FILLED and order.filled_quantity == 1 for order in result.orders)
    assert instance.get_position("TEST") is None
    untouched = instance.get_position("UNREACHED")
    assert untouched is not None and untouched.quantity == 1 and untouched.last_price == Decimal(120)
    entry_price = Decimal(106 if mode == FillMode.NEXT_OPEN else 100)
    # Existing fee/equity model retained; the first close is never double-counted.
    expected_cash = Decimal(1000) - entry_price * 2 - Decimal(4) + Decimal(120) - Decimal(2)
    assert instance.get_cash() == expected_cash
    assert result.final_equity == expected_cash + untouched.unrealized_pnl == instance.get_equity()
    assert len(result.equity_curve) == 3
    assert result.equity_curve[-1].timestamp == "2025-01-03"


@pytest.mark.parametrize("mode", [FillMode.NEXT_OPEN, FillMode.CURRENT_CLOSE])
def test_notification_failure_refuses_new_entry_submission_during_cleanup(mode):
    class CleanupEntry(EntryNotificationFailure):
        def set_engine(self, engine):
            super().set_engine(engine)
            self.bound_engine = engine

        def stop(self):
            super().stop()
            self.cleanup_order = EngineOrder(symbol="AFTER_FAILURE", quantity=1)
            self.accepted = self.bound_engine.submit_order(self.cleanup_order)

    strategy = CleanupEntry()
    instance = engine(strategy, mode)
    result = instance.run(bars())
    assert "entry notification failed" in result.error
    assert strategy.accepted is False
    assert strategy.cleanup_order.status == OrderStatus.REJECTED
    assert strategy.cleanup_order.filled_quantity == 0
    assert strategy.cleanup_order not in strategy.get_open_orders()
    assert result.orders[-1] is strategy.cleanup_order
    assert instance.get_position("AFTER_FAILURE") is None
    assert sum(order.filled_quantity for order in result.orders) == 1
    after_run = EngineOrder(symbol="AFTER_RUN", quantity=1)
    assert instance.submit_order(after_run) is False
    assert after_run.status == OrderStatus.REJECTED


@pytest.mark.parametrize("mode", [FillMode.NEXT_OPEN, FillMode.CURRENT_CLOSE])
def test_progress_observer_failure_does_not_change_strategy_success(mode):
    class Hold(BaseBacktestStrategy):
        def on_bar(self, bar):
            if bar.timestamp == "2025-01-01":
                self.enter_long(quantity=1)

    control = engine(Hold(symbol="TEST"), mode).run(bars(120))
    instance = engine(Hold(symbol="TEST"), mode)
    observed = []

    def failed_progress(status):
        observed.append(status)
        raise RuntimeError("UI progress observer failed")

    instance.set_progress_callback(failed_progress)
    result = instance.run(bars(120))
    assert observed
    assert result.error == ""
    assert result.total_bars == 3
    assert len(result.trades) == 1
    assert evidence(result) == evidence(control)
