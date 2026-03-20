"""Tests for the Rust/PyO3 tick_engine package.

Tests cover:
- Basic simulation correctness with known signals
- EMA crossover built-in strategy
- Metrics: total_pnl, sharpe_ratio, max_drawdown, win_rate
- Edge cases: empty input, length mismatch, single trade
- TickSimulator configuration: slippage, commission, lot_size
"""

from __future__ import annotations

import math
import pytest

try:
    from tick_engine import Bar, SimulationResult, TickSimulator, Trade  # type: ignore[import]
    TICK_ENGINE_AVAILABLE = True
except ImportError:
    TICK_ENGINE_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not TICK_ENGINE_AVAILABLE,
    reason="tick_engine Rust extension not built — run `maturin develop` in packages/tick-engine/",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_bars(n: int, start_price: float = 100.0, step: float = 1.0) -> list[list[float]]:
    """Generate n rising-price OHLCV bars."""
    bars = []
    for i in range(n):
        close = start_price + i * step
        bars.append([
            1_700_000_000 + i * 60,  # timestamp (1 min apart)
            close - 0.5,             # open
            close + 1.0,             # high
            close - 1.0,             # low
            close,                   # close
            100_000.0,               # volume
        ])
    return bars


def make_flat_bars(n: int, price: float = 100.0) -> list[list[float]]:
    """Generate n flat-price OHLCV bars."""
    return [
        [1_700_000_000 + i * 60, price, price, price, price, 50_000.0]
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Basic simulation
# ---------------------------------------------------------------------------

class TestBasicSimulation:
    def test_no_signals_no_trades(self) -> None:
        sim = TickSimulator(initial_capital=100_000.0)
        bars = make_bars(20)
        signals = [0] * 20
        result = sim.run(bars, signals)
        assert result.total_trades == 0
        assert result.win_rate == 0.0
        # Commission deducted even if no trades; capital should be close to initial
        # (actually no commission if no trades)
        assert result.total_pnl == pytest.approx(0.0, abs=50.0)

    def test_single_long_trade_profitable(self) -> None:
        """Buy at bar 1, sell at bar 3 — price rises."""
        sim = TickSimulator(initial_capital=100_000.0, slippage_pct=0.0, commission=0.0, lot_size=1.0)
        bars = [
            [1_700_000_000, 100.0, 101.0, 99.0,  100.0, 10_000.0],
            [1_700_000_060, 100.0, 102.0, 99.0,  101.0, 10_000.0],  # entry fill here
            [1_700_000_120, 101.0, 103.0, 100.0, 102.0, 10_000.0],
            [1_700_000_180, 102.0, 104.0, 101.0, 103.0, 10_000.0],  # exit fill here
            [1_700_000_240, 103.0, 105.0, 102.0, 104.0, 10_000.0],
        ]
        # signal=1 at bar 0 → entry at bar 1 open (100.0)
        # signal=-1 at bar 2 → exit at bar 3 open (102.0)
        signals = [1, 0, -1, 0, 0]
        result = sim.run(bars, signals)

        assert result.total_trades == 1
        assert len(result.trades) == 1
        trade = result.trades[0]
        assert trade.direction == 1
        assert trade.entry_price == pytest.approx(100.0)
        assert trade.exit_price == pytest.approx(102.0)
        assert trade.pnl == pytest.approx(2.0)
        assert result.total_pnl == pytest.approx(2.0)
        assert result.win_rate == pytest.approx(1.0)

    def test_single_long_trade_loss(self) -> None:
        """Buy high, sell low — results in a loss."""
        sim = TickSimulator(initial_capital=100_000.0, slippage_pct=0.0, commission=0.0, lot_size=1.0)
        bars = [
            [1_000, 110.0, 111.0, 109.0, 110.0, 5_000.0],
            [2_000, 110.0, 111.0, 109.0, 110.0, 5_000.0],  # entry fill
            [3_000, 105.0, 106.0, 104.0, 105.0, 5_000.0],
            [4_000, 100.0, 101.0,  99.0, 100.0, 5_000.0],  # exit fill
        ]
        signals = [1, 0, -1, 0]
        result = sim.run(bars, signals)
        assert result.total_trades == 1
        assert result.trades[0].pnl == pytest.approx(-10.0)
        assert result.total_pnl == pytest.approx(-10.0)
        assert result.win_rate == pytest.approx(0.0)

    def test_commission_deducted(self) -> None:
        sim = TickSimulator(initial_capital=100_000.0, slippage_pct=0.0, commission=50.0, lot_size=1.0)
        bars = make_flat_bars(5)
        signals = [1, 0, -1, 0, 0]
        result = sim.run(bars, signals)
        # 2 commissions (entry + exit), pnl = 0 (flat price)
        assert result.total_pnl == pytest.approx(-100.0)

    def test_slippage_reduces_pnl(self) -> None:
        sim_no_slip = TickSimulator(initial_capital=100_000.0, slippage_pct=0.0, commission=0.0)
        sim_slip = TickSimulator(initial_capital=100_000.0, slippage_pct=0.01, commission=0.0)
        bars = make_bars(10, start_price=100.0, step=2.0)
        signals = [1] + [0] * 7 + [-1, 0]
        r1 = sim_no_slip.run(bars, signals)
        r2 = sim_slip.run(bars, signals)
        assert r1.total_pnl > r2.total_pnl, "Slippage should reduce P&L"

    def test_lot_size_scales_pnl(self) -> None:
        sim1 = TickSimulator(initial_capital=100_000.0, slippage_pct=0.0, commission=0.0, lot_size=1.0)
        sim10 = TickSimulator(initial_capital=100_000.0, slippage_pct=0.0, commission=0.0, lot_size=10.0)
        bars = make_bars(5)
        signals = [1, 0, 0, -1, 0]
        r1 = sim1.run(bars, signals)
        r10 = sim10.run(bars, signals)
        assert r10.total_pnl == pytest.approx(r1.total_pnl * 10.0)


# ---------------------------------------------------------------------------
# EMA crossover strategy
# ---------------------------------------------------------------------------

class TestEmaCrossover:
    def test_returns_simulation_result(self) -> None:
        sim = TickSimulator()
        bars = make_bars(100)
        result = sim.run_ema_crossover(bars, fast_period=5, slow_period=15)
        assert isinstance(result, SimulationResult)
        assert result.total_trades >= 0
        assert len(result.equity_curve) > 0

    def test_default_periods(self) -> None:
        sim = TickSimulator()
        bars = make_bars(50)
        result = sim.run_ema_crossover(bars)
        assert isinstance(result, SimulationResult)

    def test_fast_must_be_less_than_slow(self) -> None:
        sim = TickSimulator()
        bars = make_bars(50)
        with pytest.raises(ValueError):
            sim.run_ema_crossover(bars, fast_period=20, slow_period=10)

    def test_zero_period_raises(self) -> None:
        sim = TickSimulator()
        bars = make_bars(50)
        with pytest.raises(ValueError):
            sim.run_ema_crossover(bars, fast_period=0, slow_period=10)

    def test_equity_curve_length(self) -> None:
        sim = TickSimulator(initial_capital=200_000.0)
        bars = make_bars(60)
        result = sim.run_ema_crossover(bars, fast_period=5, slow_period=20)
        # equity_curve has n+1 entries (initial + one per bar + final close)
        assert len(result.equity_curve) >= len(bars)

    def test_equity_starts_at_initial_capital(self) -> None:
        initial = 500_000.0
        sim = TickSimulator(initial_capital=initial)
        bars = make_bars(40)
        result = sim.run_ema_crossover(bars, fast_period=5, slow_period=15)
        assert result.equity_curve[0] == pytest.approx(initial)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class TestMetrics:
    def test_win_rate_range(self) -> None:
        sim = TickSimulator()
        bars = make_bars(100)
        result = sim.run_ema_crossover(bars, fast_period=5, slow_period=20)
        assert 0.0 <= result.win_rate <= 1.0

    def test_max_drawdown_range(self) -> None:
        sim = TickSimulator()
        bars = make_bars(100)
        result = sim.run_ema_crossover(bars)
        assert 0.0 <= result.max_drawdown <= 1.0

    def test_sharpe_finite(self) -> None:
        sim = TickSimulator()
        bars = make_bars(100)
        result = sim.run_ema_crossover(bars)
        assert math.isfinite(result.sharpe_ratio)

    def test_no_trades_zero_win_rate(self) -> None:
        sim = TickSimulator()
        bars = make_bars(10)
        result = sim.run(bars, [0] * 10)
        assert result.win_rate == pytest.approx(0.0)
        assert result.total_trades == 0

    def test_all_wins_win_rate_one(self) -> None:
        sim = TickSimulator(slippage_pct=0.0, commission=0.0, lot_size=1.0)
        # Steadily rising price: every long trade will profit
        bars = make_bars(20, start_price=100.0, step=5.0)
        # Alternate buy/sell every 2 bars
        signals = []
        for i in range(20):
            if i % 4 == 0:
                signals.append(1)
            elif i % 4 == 2:
                signals.append(-1)
            else:
                signals.append(0)
        result = sim.run(bars, signals)
        if result.total_trades > 0:
            assert result.win_rate == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Edge cases / error handling
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_length_mismatch_raises(self) -> None:
        sim = TickSimulator()
        bars = make_bars(10)
        with pytest.raises(ValueError, match="same length"):
            sim.run(bars, [0] * 5)

    def test_empty_bars_raises(self) -> None:
        sim = TickSimulator()
        with pytest.raises(ValueError, match="empty"):
            sim.run([], [])

    def test_single_bar_no_trades(self) -> None:
        sim = TickSimulator()
        bars = make_bars(1)
        result = sim.run(bars, [1])
        # Can't fill at next bar if there's only 1 bar
        assert result.total_trades == 0

    def test_repr_simulator(self) -> None:
        sim = TickSimulator(initial_capital=50_000.0)
        assert "50000" in repr(sim)

    def test_repr_result(self) -> None:
        sim = TickSimulator()
        result = sim.run(make_bars(10), [0] * 10)
        assert "SimulationResult" in repr(result)


# ---------------------------------------------------------------------------
# Bar and Trade dataclasses
# ---------------------------------------------------------------------------

class TestDataClasses:
    def test_bar_creation(self) -> None:
        bar = Bar(1_700_000_000, 100.0, 105.0, 98.0, 102.0, 50_000.0)
        assert bar.timestamp == 1_700_000_000
        assert bar.open == pytest.approx(100.0)
        assert bar.close == pytest.approx(102.0)

    def test_bar_repr(self) -> None:
        bar = Bar(0, 10.0, 12.0, 9.0, 11.0, 1000.0)
        assert "Bar" in repr(bar)

    def test_trade_fields(self) -> None:
        sim = TickSimulator(slippage_pct=0.0, commission=0.0, lot_size=1.0)
        bars = [
            [0, 100.0, 101.0, 99.0, 100.0, 1000.0],
            [60, 105.0, 106.0, 104.0, 105.0, 1000.0],  # entry fill
            [120, 110.0, 111.0, 109.0, 110.0, 1000.0],
            [180, 115.0, 116.0, 114.0, 115.0, 1000.0],  # exit fill
        ]
        signals = [1, 0, -1, 0]
        result = sim.run(bars, signals)
        assert len(result.trades) == 1
        t = result.trades[0]
        assert t.direction == 1
        assert t.entry_time == 60
        assert t.exit_time == 180
        assert t.entry_price == pytest.approx(105.0)
        assert t.exit_price == pytest.approx(115.0)
        assert t.pnl == pytest.approx(10.0)
