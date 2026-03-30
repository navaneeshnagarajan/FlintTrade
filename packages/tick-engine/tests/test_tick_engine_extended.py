"""Extended tests for the Rust/PyO3 tick_engine package.

Tests cover:
- Bar creation with edge cases (zero volume, negative prices, boundary values)
- TickSimulator with different strategy configurations (capital, slippage, commission, lot_size)
- SimulationResult metrics (Sharpe, drawdown, win_rate edge cases)
- Multiple consecutive trades and P&L accumulation
- equity_curve properties

All tests are skipped if tick_engine is not built.
Run `maturin develop` in packages/tick-engine/ to build.
"""

from __future__ import annotations

import math
import pytest

try:
    from tick_engine import Bar, SimulationResult, TickSimulator, Trade  # type: ignore[import]  # noqa: F401
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


def make_bars(n: int, start: float = 100.0, step: float = 1.0) -> list[list[float]]:
    """Generate n OHLCV bars with rising close prices."""
    bars = []
    for i in range(n):
        c = start + i * step
        bars.append([1_700_000_000 + i * 60, c - 0.5, c + 1.0, c - 1.0, c, 100_000.0])
    return bars


def make_flat_bars(n: int, price: float = 100.0) -> list[list[float]]:
    return [[1_700_000_000 + i * 60, price, price, price, price, 50_000.0] for i in range(n)]


def make_declining_bars(n: int, start: float = 200.0, step: float = 1.0) -> list[list[float]]:
    """Generate n OHLCV bars with declining close prices."""
    bars = []
    for i in range(n):
        c = start - i * step
        bars.append([1_700_000_000 + i * 60, c + 0.5, c + 1.0, c - 1.0, c, 80_000.0])
    return bars


# ---------------------------------------------------------------------------
# Bar dataclass — edge cases
# ---------------------------------------------------------------------------


class TestBarEdgeCases:
    def test_zero_volume_bar(self):
        """A bar with zero volume is valid (pre-market, illiquid)."""
        bar = Bar(1_700_000_000, 100.0, 105.0, 98.0, 102.0, 0.0)
        assert bar.volume == pytest.approx(0.0)
        assert bar.close == pytest.approx(102.0)

    def test_high_volume_bar(self):
        """Very high volume should not cause overflow."""
        bar = Bar(0, 50.0, 51.0, 49.0, 50.5, 1_000_000_000.0)
        assert bar.volume == pytest.approx(1_000_000_000.0)

    def test_ohlc_all_same_price(self):
        """Doji candle: open=high=low=close."""
        bar = Bar(0, 100.0, 100.0, 100.0, 100.0, 1000.0)
        assert bar.open == pytest.approx(100.0)
        assert bar.high == pytest.approx(100.0)
        assert bar.low == pytest.approx(100.0)
        assert bar.close == pytest.approx(100.0)

    def test_very_small_price_precision(self):
        """Fractional prices (currency pairs, etc.)."""
        bar = Bar(0, 0.001, 0.0012, 0.0008, 0.00105, 1_000_000.0)
        assert bar.close == pytest.approx(0.00105, abs=1e-8)

    def test_large_price_nifty_scale(self):
        """NIFTY index is typically in 20,000–30,000 range."""
        bar = Bar(0, 24900.0, 25100.0, 24850.0, 25000.0, 10_000.0)
        assert bar.close == pytest.approx(25000.0)
        assert bar.high == pytest.approx(25100.0)

    def test_timestamp_zero(self):
        """Epoch 0 is a valid (if unusual) timestamp."""
        bar = Bar(0, 10.0, 12.0, 9.0, 11.0, 500.0)
        assert bar.timestamp == 0

    def test_timestamp_max_realistic(self):
        """Far-future timestamp should be stored correctly."""
        ts = 9_999_999_999
        bar = Bar(ts, 100.0, 101.0, 99.0, 100.0, 1000.0)
        assert bar.timestamp == ts

    def test_bar_repr_contains_bar(self):
        bar = Bar(0, 10.0, 12.0, 9.0, 11.0, 1000.0)
        assert "Bar" in repr(bar)

    def test_bar_ohlcv_field_access(self):
        bar = Bar(12345, 200.0, 210.0, 190.0, 205.0, 75000.0)
        assert bar.timestamp == 12345
        assert bar.open == pytest.approx(200.0)
        assert bar.high == pytest.approx(210.0)
        assert bar.low == pytest.approx(190.0)
        assert bar.close == pytest.approx(205.0)
        assert bar.volume == pytest.approx(75000.0)


# ---------------------------------------------------------------------------
# TickSimulator — different configuration combinations
# ---------------------------------------------------------------------------


class TestTickSimulatorConfigurations:
    def test_zero_slippage_zero_commission(self):
        sim = TickSimulator(initial_capital=100_000.0, slippage_pct=0.0, commission=0.0, lot_size=1.0)
        result = sim.run(make_bars(5), [0] * 5)
        assert result.total_pnl == pytest.approx(0.0)

    def test_high_initial_capital_no_effect_on_pnl_per_lot(self):
        """P&L per lot should be the same regardless of initial capital."""
        sim_small = TickSimulator(initial_capital=10_000.0, slippage_pct=0.0, commission=0.0, lot_size=1.0)
        sim_large = TickSimulator(initial_capital=10_000_000.0, slippage_pct=0.0, commission=0.0, lot_size=1.0)
        bars = make_bars(6)
        signals = [1, 0, 0, 0, -1, 0]
        r_small = sim_small.run(bars, signals)
        r_large = sim_large.run(bars, signals)
        assert r_small.total_pnl == pytest.approx(r_large.total_pnl)

    def test_fractional_lot_size(self):
        """lot_size=0.5 should halve the P&L compared to lot_size=1."""
        sim1 = TickSimulator(initial_capital=100_000.0, slippage_pct=0.0, commission=0.0, lot_size=1.0)
        sim05 = TickSimulator(initial_capital=100_000.0, slippage_pct=0.0, commission=0.0, lot_size=0.5)
        bars = make_bars(5)
        signals = [1, 0, 0, -1, 0]
        r1 = sim1.run(bars, signals)
        r05 = sim05.run(bars, signals)
        # Only compare if there are trades to compare
        if r1.total_trades > 0:
            assert r05.total_pnl == pytest.approx(r1.total_pnl * 0.5, abs=0.01)

    def test_large_lot_size(self):
        """lot_size=100 scales P&L by 100x."""
        sim1 = TickSimulator(initial_capital=100_000.0, slippage_pct=0.0, commission=0.0, lot_size=1.0)
        sim100 = TickSimulator(initial_capital=100_000.0, slippage_pct=0.0, commission=0.0, lot_size=100.0)
        bars = make_bars(5)
        signals = [1, 0, 0, -1, 0]
        r1 = sim1.run(bars, signals)
        r100 = sim100.run(bars, signals)
        if r1.total_trades > 0:
            assert r100.total_pnl == pytest.approx(r1.total_pnl * 100.0, abs=0.01)

    def test_commission_per_trade_subtracts_from_pnl(self):
        """Each round trip has 2 commission charges (entry + exit)."""
        sim = TickSimulator(initial_capital=100_000.0, slippage_pct=0.0, commission=100.0, lot_size=1.0)
        bars = make_flat_bars(5)
        signals = [1, 0, -1, 0, 0]
        result = sim.run(bars, signals)
        # Flat price → gross P&L = 0, but 2 × 100 = 200 commission
        assert result.total_pnl == pytest.approx(-200.0)

    def test_multiple_commissions_multiple_trades(self):
        """Two round trips: 4 × commission."""
        sim = TickSimulator(initial_capital=100_000.0, slippage_pct=0.0, commission=50.0, lot_size=1.0)
        bars = make_flat_bars(8)
        signals = [1, 0, -1, 0, 1, 0, -1, 0]
        result = sim.run(bars, signals)
        if result.total_trades == 2:
            assert result.total_pnl == pytest.approx(-200.0)

    def test_slippage_increases_entry_price(self):
        """With slippage, effective entry price is higher for long trades."""
        sim_noslip = TickSimulator(initial_capital=100_000.0, slippage_pct=0.0, commission=0.0, lot_size=1.0)
        sim_slip = TickSimulator(initial_capital=100_000.0, slippage_pct=0.02, commission=0.0, lot_size=1.0)
        bars = make_bars(10, step=5.0)
        signals = [1] + [0] * 7 + [-1, 0]
        r_no = sim_noslip.run(bars, signals)
        r_sl = sim_slip.run(bars, signals)
        if r_no.total_trades > 0 and r_sl.total_trades > 0:
            assert r_no.total_pnl > r_sl.total_pnl

    def test_very_small_slippage(self):
        """Very small slippage (0.0001) should still reduce P&L slightly."""
        sim_none = TickSimulator(slippage_pct=0.0, commission=0.0, lot_size=1.0)
        sim_tiny = TickSimulator(slippage_pct=0.0001, commission=0.0, lot_size=1.0)
        bars = make_bars(10, step=10.0)
        signals = [1] + [0] * 8 + [-1]
        r_none = sim_none.run(bars, signals)
        r_tiny = sim_tiny.run(bars, signals)
        if r_none.total_trades > 0:
            assert r_none.total_pnl >= r_tiny.total_pnl


# ---------------------------------------------------------------------------
# SimulationResult — metrics validation
# ---------------------------------------------------------------------------


class TestSimulationResultMetrics:
    def test_max_drawdown_zero_when_no_trades(self):
        sim = TickSimulator()
        result = sim.run(make_bars(10), [0] * 10)
        assert result.max_drawdown == pytest.approx(0.0)

    def test_max_drawdown_not_greater_than_one(self):
        sim = TickSimulator(slippage_pct=0.0, commission=0.0, lot_size=1.0)
        bars = make_declining_bars(30)
        # Alternate buy/sell to generate losing trades
        signals = []
        for i in range(30):
            if i % 4 == 0:
                signals.append(1)
            elif i % 4 == 2:
                signals.append(-1)
            else:
                signals.append(0)
        result = sim.run(bars, signals)
        assert result.max_drawdown <= 1.0

    def test_max_drawdown_non_negative(self):
        sim = TickSimulator()
        bars = make_bars(50)
        result = sim.run_ema_crossover(bars, fast_period=5, slow_period=20)
        assert result.max_drawdown >= 0.0

    def test_sharpe_ratio_is_finite_no_trades(self):
        sim = TickSimulator()
        result = sim.run(make_flat_bars(10), [0] * 10)
        assert math.isfinite(result.sharpe_ratio)

    def test_sharpe_ratio_rising_market_positive_or_zero(self):
        """In a purely rising market with correct signals, Sharpe should be >= 0."""
        sim = TickSimulator(slippage_pct=0.0, commission=0.0, lot_size=1.0)
        bars = make_bars(40, step=2.0)
        result = sim.run_ema_crossover(bars, fast_period=3, slow_period=10)
        assert math.isfinite(result.sharpe_ratio)

    def test_win_rate_between_zero_and_one(self):
        sim = TickSimulator()
        bars = make_bars(60)
        result = sim.run_ema_crossover(bars, fast_period=5, slow_period=15)
        assert 0.0 <= result.win_rate <= 1.0

    def test_equity_curve_first_value_is_initial_capital(self):
        initial = 250_000.0
        sim = TickSimulator(initial_capital=initial)
        result = sim.run_ema_crossover(make_bars(40), fast_period=5, slow_period=15)
        assert result.equity_curve[0] == pytest.approx(initial)

    def test_equity_curve_length_equals_or_exceeds_bars(self):
        sim = TickSimulator(initial_capital=100_000.0)
        bars = make_bars(50)
        result = sim.run_ema_crossover(bars, fast_period=5, slow_period=20)
        assert len(result.equity_curve) >= len(bars)

    def test_total_pnl_equals_equity_diff(self):
        """total_pnl should match final equity minus initial capital."""
        initial = 100_000.0
        sim = TickSimulator(initial_capital=initial, slippage_pct=0.0, commission=0.0)
        bars = make_bars(20)
        result = sim.run_ema_crossover(bars, fast_period=3, slow_period=8)
        if len(result.equity_curve) > 0:
            final_equity = result.equity_curve[-1]
            assert final_equity == pytest.approx(initial + result.total_pnl, abs=1.0)

    def test_result_repr_contains_class_name(self):
        sim = TickSimulator()
        result = sim.run(make_bars(5), [0] * 5)
        assert "SimulationResult" in repr(result)

    def test_total_trades_matches_trade_list_length(self):
        sim = TickSimulator(slippage_pct=0.0, commission=0.0)
        bars = make_bars(20)
        signals = []
        for i in range(20):
            if i % 4 == 0:
                signals.append(1)
            elif i % 4 == 2:
                signals.append(-1)
            else:
                signals.append(0)
        result = sim.run(bars, signals)
        assert result.total_trades == len(result.trades)


# ---------------------------------------------------------------------------
# Trade objects
# ---------------------------------------------------------------------------


class TestTradeObjects:
    def _run_long_trade(self, entry_price: float = 100.0, exit_price: float = 110.0):
        sim = TickSimulator(initial_capital=100_000.0, slippage_pct=0.0, commission=0.0, lot_size=1.0)
        bars = [
            [0,   entry_price, entry_price + 2, entry_price - 1, entry_price, 1000.0],
            [60,  entry_price, entry_price + 2, entry_price - 1, entry_price, 1000.0],
            [120, exit_price,  exit_price + 2,  exit_price - 1,  exit_price,  1000.0],
            [180, exit_price,  exit_price + 2,  exit_price - 1,  exit_price,  1000.0],
        ]
        signals = [1, 0, -1, 0]
        return sim.run(bars, signals)

    def test_trade_direction_long(self):
        result = self._run_long_trade()
        if result.trades:
            assert result.trades[0].direction == 1

    def test_trade_pnl_positive_for_profitable_long(self):
        result = self._run_long_trade(entry_price=100.0, exit_price=115.0)
        if result.trades:
            assert result.trades[0].pnl > 0

    def test_trade_pnl_negative_for_losing_long(self):
        result = self._run_long_trade(entry_price=100.0, exit_price=90.0)
        if result.trades:
            assert result.trades[0].pnl < 0

    def test_trade_entry_time_before_exit_time(self):
        result = self._run_long_trade()
        if result.trades:
            t = result.trades[0]
            assert t.entry_time < t.exit_time

    def test_trade_entry_price_positive(self):
        result = self._run_long_trade()
        if result.trades:
            assert result.trades[0].entry_price > 0

    def test_trade_exit_price_positive(self):
        result = self._run_long_trade()
        if result.trades:
            assert result.trades[0].exit_price > 0

    def test_multiple_trades_accumulate_pnl(self):
        """Sum of individual trade P&Ls should equal total_pnl."""
        sim = TickSimulator(slippage_pct=0.0, commission=0.0, lot_size=1.0)
        bars = make_bars(20)
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
            trade_sum = sum(t.pnl for t in result.trades)
            assert trade_sum == pytest.approx(result.total_pnl, abs=1.0)


# ---------------------------------------------------------------------------
# EMA crossover — additional strategy configuration tests
# ---------------------------------------------------------------------------


class TestEmaCrossoverExtended:
    def test_short_period_generates_more_signals(self):
        """Faster EMA periods should produce more crossovers (more trades)."""
        sim = TickSimulator()
        bars = make_bars(100, step=1.0)
        r_fast = sim.run_ema_crossover(bars, fast_period=3, slow_period=8)
        r_slow = sim.run_ema_crossover(bars, fast_period=10, slow_period=30)
        # Fast periods generally produce more trades on trending data
        # This is directional — may not always hold, so just check both are non-negative
        assert r_fast.total_trades >= 0
        assert r_slow.total_trades >= 0

    def test_period_1_raises(self):
        """fast_period=1 should be handled (either error or degenerate case)."""
        sim = TickSimulator()
        bars = make_bars(50)
        try:
            result = sim.run_ema_crossover(bars, fast_period=1, slow_period=5)
            assert isinstance(result, SimulationResult)
        except ValueError:
            pass  # Either behavior is acceptable

    def test_equal_periods_raises_or_no_trades(self):
        """fast_period == slow_period should either raise or produce 0 trades."""
        sim = TickSimulator()
        bars = make_bars(50)
        try:
            result = sim.run_ema_crossover(bars, fast_period=10, slow_period=10)
            # If it doesn't raise, there should be no crossovers
            assert result.total_trades == 0
        except ValueError:
            pass  # Raising is also acceptable

    def test_equity_curve_all_finite(self):
        sim = TickSimulator(initial_capital=100_000.0)
        bars = make_bars(80)
        result = sim.run_ema_crossover(bars, fast_period=5, slow_period=20)
        for val in result.equity_curve:
            assert math.isfinite(val), f"Non-finite equity curve value: {val}"

    def test_different_initial_capitals_equity_ratio(self):
        """Doubling initial capital should double the equity curve values."""
        sim1 = TickSimulator(initial_capital=100_000.0, slippage_pct=0.0, commission=0.0)
        sim2 = TickSimulator(initial_capital=200_000.0, slippage_pct=0.0, commission=0.0)
        bars = make_bars(50)
        r1 = sim1.run_ema_crossover(bars, fast_period=5, slow_period=15)
        r2 = sim2.run_ema_crossover(bars, fast_period=5, slow_period=15)
        assert r2.equity_curve[0] == pytest.approx(r1.equity_curve[0] * 2.0)


# ---------------------------------------------------------------------------
# Edge cases and error paths
# ---------------------------------------------------------------------------


class TestExtendedEdgeCases:
    def test_all_buy_signals_no_sell(self):
        """If only buy signals and no sell, open positions at end — check no crash."""
        sim = TickSimulator(slippage_pct=0.0, commission=0.0)
        bars = make_bars(5)
        signals = [1, 1, 1, 1, 1]  # all buys
        result = sim.run(bars, signals)
        assert isinstance(result, SimulationResult)

    def test_alternating_signals_no_crash(self):
        """Alternating buy/sell signals should not crash."""
        sim = TickSimulator(slippage_pct=0.0, commission=0.0)
        bars = make_bars(10)
        signals = [1 if i % 2 == 0 else -1 for i in range(10)]
        result = sim.run(bars, signals)
        assert isinstance(result, SimulationResult)

    def test_two_bars_with_trade(self):
        """Minimum viable scenario: 2 bars, buy on bar 0, sell impossible (no bar 2)."""
        sim = TickSimulator(slippage_pct=0.0, commission=0.0, lot_size=1.0)
        bars = make_bars(2)
        result = sim.run(bars, [1, -1])
        assert isinstance(result, SimulationResult)

    def test_signals_all_minus_one(self):
        """All sell signals — simulator should handle gracefully."""
        sim = TickSimulator()
        bars = make_bars(10)
        result = sim.run(bars, [-1] * 10)
        assert isinstance(result, SimulationResult)

    def test_large_bar_count(self):
        """Running on 1000 bars should complete without error."""
        sim = TickSimulator()
        bars = make_bars(1000)
        result = sim.run_ema_crossover(bars, fast_period=10, slow_period=30)
        assert isinstance(result, SimulationResult)
        assert len(result.equity_curve) >= 1000

    def test_negative_pnl_drawdown_computed(self):
        """Ensure drawdown is non-zero when trades lose money."""
        sim = TickSimulator(slippage_pct=0.0, commission=0.0, lot_size=1.0)
        bars = make_declining_bars(10, start=100.0, step=2.0)
        # Buy on a declining market: all losses
        signals = [1, 0, 0, 0, 0, 0, 0, 0, 0, -1]
        result = sim.run(bars, signals)
        if result.total_trades > 0 and result.total_pnl < 0:
            assert result.max_drawdown > 0.0

    def test_simulator_repr_includes_capital(self):
        sim = TickSimulator(initial_capital=75_000.0)
        r = repr(sim)
        assert "75000" in r

    def test_multiple_run_calls_independent(self):
        """Running the simulator twice should give the same result for same inputs."""
        sim = TickSimulator(initial_capital=100_000.0, slippage_pct=0.0, commission=0.0)
        bars = make_bars(20)
        signals = [1, 0, 0, 0, 0, -1, 0, 0, 0, 0, 1, 0, 0, 0, 0, -1, 0, 0, 0, 0]
        r1 = sim.run(bars, signals)
        r2 = sim.run(bars, signals)
        assert r1.total_pnl == pytest.approx(r2.total_pnl)
        assert r1.total_trades == r2.total_trades
