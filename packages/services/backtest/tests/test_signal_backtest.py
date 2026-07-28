"""Tests for the signal-array backtest and its optional tick_engine path.

Covers:
- Input validation and the pure-Python reference engine's fill semantics
  (next-bar-open fill, slippage, commission, forced last-bar close).
- EMA crossover signal generation.
- Fail-closed behaviour when the flinttrade-ticks wheel is absent (simulated
  by monkeypatching, so these tests run everywhere).
- Byte-equivalence between the pure-Python engine and the Rust tick_engine —
  skipped cleanly when the wheel is not installed (the desktop bootstrap
  excludes it via `uv sync --no-install-package flinttrade-ticks`).
"""

from __future__ import annotations

import random
import struct
from datetime import datetime, timezone

import pytest

import flinttrade_backtest.signal_backtest as sb
from flinttrade_backtest.signal_backtest import (
    SignalBacktestConfig,
    SignalBacktestResult,
    TickEngineNotAvailableError,
    bars_from_dicts,
    ema_crossover_signals,
    is_tick_engine_available,
    run_ema_crossover_backtest,
    run_signal_backtest,
)

pytestmark = pytest.mark.unit

_TICKS = pytest.mark.skipif(
    not is_tick_engine_available(),
    reason="flinttrade-ticks wheel not installed (excluded by the desktop bootstrap)",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_bars(n: int, start_price: float = 100.0, step: float = 1.0) -> list[list[float]]:
    """Generate n rising-price OHLCV bars, one minute apart."""
    bars = []
    for i in range(n):
        close = start_price + i * step
        bars.append([
            1_700_000_000 + i * 60,
            close - 0.5,
            close + 1.0,
            close - 1.0,
            close,
            100_000.0,
        ])
    return bars


def make_random_walk_bars(n: int, seed: int = 42, start_price: float = 500.0) -> list[list[float]]:
    """Generate n seeded random-walk OHLCV bars."""
    rng = random.Random(seed)
    bars = []
    price = start_price
    for i in range(n):
        open_ = price
        close = max(1.0, price + rng.uniform(-5.0, 5.0))
        high = max(open_, close) + rng.uniform(0.0, 2.0)
        low = min(open_, close) - rng.uniform(0.0, 2.0)
        bars.append([1_700_000_000 + i * 60, open_, high, low, close, float(rng.randint(1_000, 500_000))])
        price = close
    return bars


def make_random_signals(n: int, seed: int = 7) -> list[int]:
    """Generate n seeded signals weighted towards holding."""
    rng = random.Random(seed)
    return [rng.choices([-1, 0, 1], weights=[1, 6, 1])[0] for _ in range(n)]


def _float_bytes(value: float) -> bytes:
    """IEEE binary64 byte representation of a float."""
    return struct.pack("<d", value)


def assert_results_byte_equal(a: SignalBacktestResult, b: SignalBacktestResult) -> None:
    """Assert two results are byte-equivalent (ignoring the engine tag)."""
    assert _float_bytes(a.total_pnl) == _float_bytes(b.total_pnl)
    assert _float_bytes(a.sharpe_ratio) == _float_bytes(b.sharpe_ratio)
    assert _float_bytes(a.max_drawdown) == _float_bytes(b.max_drawdown)
    assert _float_bytes(a.win_rate) == _float_bytes(b.win_rate)
    assert a.total_trades == b.total_trades
    assert len(a.equity_curve) == len(b.equity_curve)
    for ea, eb in zip(a.equity_curve, b.equity_curve):
        assert _float_bytes(ea) == _float_bytes(eb)
    assert len(a.trades) == len(b.trades)
    for ta, tb in zip(a.trades, b.trades):
        assert ta.entry_time == tb.entry_time
        assert ta.exit_time == tb.exit_time
        assert _float_bytes(ta.entry_price) == _float_bytes(tb.entry_price)
        assert _float_bytes(ta.exit_price) == _float_bytes(tb.exit_price)
        assert _float_bytes(ta.qty) == _float_bytes(tb.qty)
        assert _float_bytes(ta.pnl) == _float_bytes(tb.pnl)
        assert ta.direction == tb.direction


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_length_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="must have the same length"):
            run_signal_backtest(make_bars(5), [0, 0, 0])

    def test_empty_bars_raise(self) -> None:
        with pytest.raises(ValueError, match="bars cannot be empty"):
            run_signal_backtest([], [])

    def test_malformed_row_raises(self) -> None:
        bars = make_bars(3)
        bars[1] = bars[1][:4]
        with pytest.raises(ValueError, match="exactly 6 values"):
            run_signal_backtest(bars, [0, 0, 0])

    def test_unknown_engine_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown engine"):
            run_signal_backtest(make_bars(3), [0, 0, 0], engine="rust")  # type: ignore[arg-type]

    def test_ema_zero_period_raises(self) -> None:
        with pytest.raises(ValueError, match="must be > 0"):
            ema_crossover_signals([1.0, 2.0], fast_period=0, slow_period=5)

    def test_ema_fast_not_below_slow_raises(self) -> None:
        with pytest.raises(ValueError, match="less than slow_period"):
            run_ema_crossover_backtest(make_bars(30), fast_period=9, slow_period=9)


# ---------------------------------------------------------------------------
# Pure-Python engine semantics
# ---------------------------------------------------------------------------


class TestPythonEngine:
    def test_no_signals_no_trades(self) -> None:
        result = run_signal_backtest(make_bars(10), [0] * 10)
        assert result.engine == "python"
        assert result.total_trades == 0
        assert result.total_pnl == 0.0
        assert result.trades == []
        assert len(result.equity_curve) == 11
        assert all(e == 100_000.0 for e in result.equity_curve)

    def test_single_long_round_trip_hand_computed(self) -> None:
        # Bars with known opens; slippage 1%, commission 10, lot 2.
        bars = [
            [1_000.0, 100.0, 101.0, 99.0, 100.5, 1_000.0],
            [1_060.0, 100.0, 102.0, 99.5, 101.0, 1_000.0],  # entry fills here
            [1_120.0, 103.0, 104.0, 102.0, 103.5, 1_000.0],
            [1_180.0, 110.0, 111.0, 109.0, 110.5, 1_000.0],  # exit fills here
        ]
        signals = [1, 0, -1, 0]
        cfg = SignalBacktestConfig(
            initial_capital=10_000.0, slippage_pct=0.01, commission=10.0, lot_size=2.0,
        )
        result = run_signal_backtest(bars, signals, config=cfg)

        assert result.total_trades == 1
        trade = result.trades[0]
        entry = 100.0 * 1.01   # open of bar 1 + slippage
        exit_ = 110.0 * 0.99   # open of bar 3 - slippage
        assert trade.entry_price == entry
        assert trade.exit_price == exit_
        assert trade.direction == 1
        assert trade.entry_time == 1_060
        assert trade.exit_time == 1_180
        expected_pnl = (exit_ - entry) * 1.0 * 2.0
        assert trade.pnl == expected_pnl
        # Two commissions paid (entry + exit); approx because total_pnl
        # accumulates through the running capital rather than in one step.
        assert result.total_pnl == pytest.approx(expected_pnl - 20.0)

    def test_short_trade_slippage_signs(self) -> None:
        bars = make_bars(4, start_price=100.0, step=-1.0)
        cfg = SignalBacktestConfig(slippage_pct=0.01, commission=0.0)
        result = run_signal_backtest(bars, [-1, 0, 1, 0], config=cfg)
        assert result.total_trades == 1
        trade = result.trades[0]
        assert trade.direction == -1
        # Short entry fills below the open; short exit (buy back) above it.
        assert trade.entry_price < bars[1][1]
        assert trade.exit_price > bars[3][1]

    def test_open_position_force_closed_at_last_close(self) -> None:
        bars = make_bars(5)
        cfg = SignalBacktestConfig(slippage_pct=0.0, commission=0.0, lot_size=1.0)
        result = run_signal_backtest(bars, [1, 0, 0, 0, 0], config=cfg)
        assert result.total_trades == 1
        trade = result.trades[0]
        assert trade.exit_price == bars[-1][4]  # last close, no slippage
        assert trade.exit_time == int(bars[-1][0])

    def test_winning_run_has_positive_metrics(self) -> None:
        bars = make_bars(60, start_price=100.0, step=1.0)
        signals = [0] * 60
        signals[5] = 1
        signals[30] = -1
        signals[35] = 1
        signals[55] = -1
        cfg = SignalBacktestConfig(commission=0.0)  # avoid commission drag on small moves
        result = run_signal_backtest(bars, signals, config=cfg)
        assert result.total_trades == 2
        assert result.total_pnl > 0.0
        assert result.win_rate == 1.0
        assert 0.0 <= result.max_drawdown < 1.0

    def test_ema_crossover_generates_signals_on_reversal(self) -> None:
        closes = [100.0 + i for i in range(40)] + [140.0 - i for i in range(40)]
        signals = ema_crossover_signals(closes, fast_period=5, slow_period=15)
        assert len(signals) == len(closes)
        assert -1 in signals  # the downtrend must produce a bearish cross
        assert all(s in (-1, 0, 1) for s in signals)

    def test_ema_backtest_runs_on_python_engine(self) -> None:
        bars = make_random_walk_bars(300, seed=11)
        result = run_ema_crossover_backtest(bars, fast_period=9, slow_period=21)
        assert result.engine == "python"
        assert len(result.equity_curve) == 301


# ---------------------------------------------------------------------------
# bars_from_dicts
# ---------------------------------------------------------------------------


class TestBarsFromDicts:
    def test_numeric_and_string_timestamps(self) -> None:
        rows = bars_from_dicts([
            {"timestamp": 1_700_000_000, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10},
            {"timestamp": "1700000060", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10},
        ])
        assert rows[0][0] == 1_700_000_000.0
        assert rows[1][0] == 1_700_000_060.0
        assert all(len(r) == 6 for r in rows)

    def test_iso_timestamp_naive_read_as_utc(self) -> None:
        rows = bars_from_dicts([
            {"timestamp": "2026-01-01T09:15:00", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        ])
        expected = datetime(2026, 1, 1, 9, 15, tzinfo=timezone.utc).timestamp()
        assert rows[0][0] == expected

    def test_missing_timestamp_raises(self) -> None:
        with pytest.raises(ValueError, match="missing a usable 'timestamp'"):
            bars_from_dicts([{"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}])

    def test_unparseable_timestamp_raises(self) -> None:
        with pytest.raises(ValueError, match="unparseable timestamp"):
            bars_from_dicts([
                {"timestamp": "not-a-time", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
            ])


# ---------------------------------------------------------------------------
# Fail-closed behaviour (runs with or without the wheel)
# ---------------------------------------------------------------------------


class TestFailClosed:
    def test_accelerated_raises_when_wheel_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sb, "_tick_engine", None)
        assert sb.is_tick_engine_available() is False
        with pytest.raises(TickEngineNotAvailableError, match="flinttrade-ticks"):
            sb.run_signal_backtest(make_bars(5), [0] * 5, engine="accelerated")
        with pytest.raises(TickEngineNotAvailableError):
            sb.run_ema_crossover_backtest(make_bars(30), engine="accelerated")

    def test_auto_falls_back_to_python_when_wheel_absent(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bars = make_bars(20)
        signals = make_random_signals(20)
        expected = sb.run_signal_backtest(bars, signals, engine="python")

        monkeypatch.setattr(sb, "_tick_engine", None)
        result = sb.run_signal_backtest(bars, signals, engine="auto")
        assert result.engine == "python"
        assert_results_byte_equal(result, expected)

    def test_python_engine_never_touches_the_wheel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sb, "_tick_engine", None)
        result = sb.run_signal_backtest(make_bars(10), [1] + [0] * 9, engine="python")
        assert result.engine == "python"
        assert result.total_trades == 1


# ---------------------------------------------------------------------------
# Byte-equivalence against the Rust engine (skips when the wheel is absent)
# ---------------------------------------------------------------------------


@_TICKS
class TestRustEquivalence:
    def test_random_walk_signals_byte_equal(self) -> None:
        bars = make_random_walk_bars(500, seed=42)
        signals = make_random_signals(500, seed=7)
        py = run_signal_backtest(bars, signals, engine="python")
        rust = run_signal_backtest(bars, signals, engine="accelerated")
        assert py.engine == "python"
        assert rust.engine == "tick-engine"
        assert rust.total_trades > 0  # the comparison must exercise real trades
        assert_results_byte_equal(py, rust)

    def test_alternate_config_byte_equal(self) -> None:
        bars = make_random_walk_bars(400, seed=99, start_price=2_500.0)
        signals = make_random_signals(400, seed=3)
        cfg = SignalBacktestConfig(
            initial_capital=1_000_000.0, slippage_pct=0.0025, commission=45.5, lot_size=25.0,
        )
        py = run_signal_backtest(bars, signals, config=cfg, engine="python")
        rust = run_signal_backtest(bars, signals, config=cfg, engine="accelerated")
        assert_results_byte_equal(py, rust)

    def test_zero_cost_config_byte_equal(self) -> None:
        bars = make_random_walk_bars(300, seed=5)
        signals = make_random_signals(300, seed=13)
        cfg = SignalBacktestConfig(slippage_pct=0.0, commission=0.0)
        py = run_signal_backtest(bars, signals, config=cfg, engine="python")
        rust = run_signal_backtest(bars, signals, config=cfg, engine="accelerated")
        assert_results_byte_equal(py, rust)

    def test_ema_crossover_byte_equal(self) -> None:
        bars = make_random_walk_bars(600, seed=21)
        py = run_ema_crossover_backtest(bars, fast_period=9, slow_period=21, engine="python")
        rust = run_ema_crossover_backtest(bars, fast_period=9, slow_period=21, engine="accelerated")
        assert rust.engine == "tick-engine"
        assert_results_byte_equal(py, rust)

    def test_ema_signals_match_rust_builtin_strategy(self) -> None:
        # The Python signal generator must reproduce the Rust built-in exactly:
        # running the generated signals must equal the raw TickSimulator
        # run_ema_crossover simulation state (curve/trades — the raw Rust
        # Sharpe is FMA-contraction-sensitive, so it is derived in Python).
        import tick_engine

        bars = make_random_walk_bars(600, seed=21)
        closes = [row[4] for row in bars]
        signals = ema_crossover_signals(closes, fast_period=9, slow_period=21)
        py = run_signal_backtest(bars, signals, engine="python")

        sim = tick_engine.TickSimulator()
        raw = sim.run_ema_crossover(bars, fast_period=9, slow_period=21)
        assert raw.total_trades == py.total_trades
        assert raw.total_trades > 0
        assert _float_bytes(raw.total_pnl) == _float_bytes(py.total_pnl)
        assert len(raw.equity_curve) == len(py.equity_curve)
        for ea, eb in zip(raw.equity_curve, py.equity_curve):
            assert _float_bytes(ea) == _float_bytes(eb)
        for ta, tb in zip(raw.trades, py.trades):
            assert ta.entry_time == tb.entry_time
            assert ta.exit_time == tb.exit_time
            assert _float_bytes(ta.entry_price) == _float_bytes(tb.entry_price)
            assert _float_bytes(ta.exit_price) == _float_bytes(tb.exit_price)
            assert _float_bytes(ta.pnl) == _float_bytes(tb.pnl)
            assert int(ta.direction) == tb.direction

    def test_open_position_at_end_byte_equal(self) -> None:
        bars = make_bars(50)
        signals = [0] * 50
        signals[10] = 1  # never closed — exercises the forced-close path
        py = run_signal_backtest(bars, signals, engine="python")
        rust = run_signal_backtest(bars, signals, engine="accelerated")
        assert py.total_trades == 1
        assert_results_byte_equal(py, rust)

    def test_single_bar_byte_equal(self) -> None:
        bars = make_bars(1)
        py = run_signal_backtest(bars, [1], engine="python")
        rust = run_signal_backtest(bars, [1], engine="accelerated")
        assert py.total_trades == 0
        assert len(py.equity_curve) == 2
        assert_results_byte_equal(py, rust)

    def test_auto_prefers_rust_when_available(self) -> None:
        result = run_signal_backtest(make_bars(10), [0] * 10, engine="auto")
        assert result.engine == "tick-engine"
