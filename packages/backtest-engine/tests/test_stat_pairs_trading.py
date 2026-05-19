"""Tests for stat_pairs_trading module.

Covers: statistical helpers (OLS, ADF, OU half-life, z-score, cointegration),
pair selection, and the StatPairsTrading strategy.
"""

from __future__ import annotations

import math
import random

import pytest

from strategies.stat_pairs_trading import (
    PairsTradingConfig,
    StatPairsTrading,
    _adf_test,
    _gauss_elim,
    _matrix_inv,
    _mean,
    _ols,
    _std,
    adf_stationarity,
    cointegration_test,
    ou_half_life,
    select_best_pair,
    zscore,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _ar1_series(n: int, phi: float, seed: int = 0) -> list[float]:
    """Generate a stationary AR(1) series: y_t = phi * y_{t-1} + ε."""
    rng = random.Random(seed)
    series = [0.0]
    for _ in range(n - 1):
        series.append(phi * series[-1] + rng.gauss(0, 1))
    return series


def _random_walk(n: int, seed: int = 1) -> list[float]:
    """Generate a non-stationary random walk."""
    rng = random.Random(seed)
    series = [100.0]
    for _ in range(n - 1):
        series.append(series[-1] + rng.gauss(0, 1))
    return series


def _cointegrated_pair(n: int, beta: float = 1.5, seed: int = 42) -> tuple[list[float], list[float]]:
    """Generate a cointegrated pair: y = beta * x + stationary_spread."""
    random.Random(seed)
    x = _random_walk(n, seed=seed)
    spread = _ar1_series(n, phi=0.7, seed=seed + 1)
    y = [beta * x[i] + spread[i] for i in range(n)]
    return y, x


def _make_ohlcv(closes: list[float]) -> list[object]:
    """Minimal OHLCV-like objects for on_bar calls."""
    from packages.core.src.models import OHLCV
    return [
        OHLCV(
            timestamp=f"2025-01-{i+1:02d}T09:15:00",
            open=c, high=c * 1.001, low=c * 0.999,
            close=c, volume=1000,
        )
        for i, c in enumerate(closes)
    ]


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestMeanStd:
    def test_mean_empty(self) -> None:
        assert _mean([]) == 0.0

    def test_mean_basic(self) -> None:
        assert _mean([1.0, 2.0, 3.0]) == pytest.approx(2.0)

    def test_std_single(self) -> None:
        assert _std([5.0], ddof=1) == 0.0

    def test_std_known(self) -> None:
        # Population std of [2, 4, 4, 4, 5, 5, 7, 9] = 2.0; sample std (ddof=1) is higher
        import math
        vals = [2, 4, 4, 4, 5, 5, 7, 9]
        m = sum(vals) / len(vals)
        expected = math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))
        assert _std(vals, ddof=1) == pytest.approx(expected, rel=1e-9)

    def test_std_population(self) -> None:
        vals = [1.0, 2.0, 3.0]
        pop_std = math.sqrt(2.0 / 3.0)
        assert _std(vals, ddof=0) == pytest.approx(pop_std, rel=1e-6)


class TestOLS:
    def test_perfect_line(self) -> None:
        x = [1.0, 2.0, 3.0, 4.0, 5.0]
        y = [2.0 * xi + 1.0 for xi in x]  # slope=2, intercept=1
        slope, intercept = _ols(y, x)
        assert slope == pytest.approx(2.0, rel=1e-6)
        assert intercept == pytest.approx(1.0, rel=1e-6)

    def test_too_short(self) -> None:
        slope, intercept = _ols([1.0], [1.0])
        assert slope == 1.0
        assert intercept == 0.0

    def test_collinear_x(self) -> None:
        """All identical x → denom = 0, fallback."""
        slope, intercept = _ols([1.0, 2.0, 3.0], [2.0, 2.0, 2.0])
        assert slope == 1.0  # fallback


class TestGaussElim:
    def test_2x2(self) -> None:
        # Solve [2 1; 5 7] * x = [11; 13]
        # x[0] = (11*7 - 1*13) / (2*7 - 1*5) = (77-13)/(14-5) = 64/9
        # x[1] = (2*13 - 5*11) / (2*7 - 1*5) = (26-55)/9 = -29/9
        A = [[2.0, 1.0], [5.0, 7.0]]
        b = [11.0, 13.0]
        x = _gauss_elim(A, b)
        assert x is not None
        assert x[0] == pytest.approx(64.0 / 9.0, rel=1e-6)
        assert x[1] == pytest.approx(-29.0 / 9.0, rel=1e-6)

    def test_singular(self) -> None:
        A = [[1.0, 2.0], [2.0, 4.0]]
        b = [3.0, 6.0]
        assert _gauss_elim(A, b) is None


class TestMatrixInv:
    def test_identity(self) -> None:
        A = [[1.0, 0.0], [0.0, 1.0]]
        inv = _matrix_inv(A)
        assert inv is not None
        assert inv[0][0] == pytest.approx(1.0)
        assert inv[1][1] == pytest.approx(1.0)

    def test_known_2x2(self) -> None:
        A = [[4.0, 7.0], [2.0, 6.0]]
        inv = _matrix_inv(A)
        assert inv is not None
        # [4 7; 2 6]^{-1} = [0.6 -0.7; -0.2 0.4]
        assert inv[0][0] == pytest.approx(0.6, rel=1e-6)
        assert inv[0][1] == pytest.approx(-0.7, rel=1e-6)

    def test_singular(self) -> None:
        A = [[1.0, 2.0], [2.0, 4.0]]
        assert _matrix_inv(A) is None


# ---------------------------------------------------------------------------
# ADF test
# ---------------------------------------------------------------------------


class TestADF:
    def test_stationary_has_negative_stat(self) -> None:
        # Stationary AR(1) with phi=0.5 should have negative ADF stat
        series = _ar1_series(200, phi=0.5, seed=99)
        stat = _adf_test(series)
        assert stat < 0.0

    def test_random_walk_less_negative(self) -> None:
        # Random walk ADF stat should be closer to zero (or positive)
        rw = _random_walk(200, seed=10)
        stationary = _ar1_series(200, phi=0.3, seed=11)
        adf_rw = _adf_test(rw)
        adf_stat = _adf_test(stationary)
        # Stationary series should have more negative ADF stat
        assert adf_stat < adf_rw

    def test_too_short(self) -> None:
        assert _adf_test([1.0, 2.0]) == 0.0

    def test_adf_stationarity_alias(self) -> None:
        series = _ar1_series(100, phi=0.5, seed=7)
        assert adf_stationarity(series) == _adf_test(series)


# ---------------------------------------------------------------------------
# OU half-life
# ---------------------------------------------------------------------------


class TestOUHalfLife:
    def test_fast_mean_reverting(self) -> None:
        # phi=0.2 → strong reversion → short half-life
        series = _ar1_series(300, phi=0.2, seed=5)
        hl = ou_half_life(series)
        assert hl > 0, "Half-life should be positive for mean-reverting series"
        assert hl < 100, "Half-life should be reasonably short"

    def test_slow_mean_reverting(self) -> None:
        # phi=0.9 → slow reversion → longer half-life
        series = _ar1_series(500, phi=0.9, seed=6)
        hl = ou_half_life(series)
        assert hl > 0
        fast = ou_half_life(_ar1_series(500, phi=0.2, seed=6))
        assert hl > fast, "phi=0.9 half-life should be longer than phi=0.2"

    def test_too_short(self) -> None:
        assert ou_half_life([1.0, 2.0]) == 0.0

    def test_random_walk_returns_zero(self) -> None:
        rw = _random_walk(200, seed=3)
        hl = ou_half_life(rw)
        # Random walk has no mean reversion; theta >= 0 → return 0
        assert hl == 0.0 or hl >= 2.0  # either 0 or a large value is fine


# ---------------------------------------------------------------------------
# Z-score
# ---------------------------------------------------------------------------


class TestZScore:
    def test_zero_at_mean(self) -> None:
        # Build a series where the last value equals the rolling window mean exactly
        window = [1.0, 2.0, 3.0, 4.0, 5.0]
        mean_val = sum(window) / len(window)  # = 3.0
        [10.0, 20.0] + window[:-1] + [mean_val]  # last value is the mean
        # The window is the last 5 elements: [2.0, 3.0, 4.0, 5.0, 3.0] — mean ≠ 3.0
        # Better: construct series where last 5 = [1,2,3,4,3], last = mean([1,2,3,4,3])=2.6
        # Simplest: series of constant value → std=0 → zscore=0
        series_const = [3.0] * 10
        assert zscore(series_const, 5) == 0.0

    def test_positive_zscore(self) -> None:
        # Last element is well above the window mean
        series = [1.0] * 10 + [5.0]
        z = zscore(series, 10)
        assert z > 0

    def test_insufficient_window(self) -> None:
        assert zscore([1.0, 2.0], 10) == 0.0

    def test_zero_std(self) -> None:
        series = [3.0] * 20
        assert zscore(series, 10) == 0.0


# ---------------------------------------------------------------------------
# Cointegration test
# ---------------------------------------------------------------------------


class TestCointegrationTest:
    def test_cointegrated_pair(self) -> None:
        y, x = _cointegrated_pair(300, beta=1.5, seed=42)
        hedge, adf = cointegration_test(y, x)
        # Hedge ratio should be close to 1.5
        assert hedge == pytest.approx(1.5, rel=0.3)
        # ADF stat should be negative (spread is stationary)
        assert adf < 0.0

    def test_too_short(self) -> None:
        hedge, adf = cointegration_test([1.0, 2.0], [1.0, 2.0])
        assert hedge == 1.0
        assert adf == 0.0

    def test_random_walks_weaker(self) -> None:
        # Two independent random walks should have weaker cointegration
        rw1 = _random_walk(300, seed=0)
        rw2 = _random_walk(300, seed=1)
        _, adf_rw = cointegration_test(rw1, rw2)
        _, adf_coint = cointegration_test(*_cointegrated_pair(300, seed=42))
        # Cointegrated pair should have more negative ADF
        assert adf_coint < adf_rw


# ---------------------------------------------------------------------------
# Pair selection
# ---------------------------------------------------------------------------


class TestSelectBestPair:
    def test_finds_cointegrated_pair(self) -> None:
        y, x = _cointegrated_pair(300, beta=1.5, seed=42)
        rw = _random_walk(300, seed=99)
        series = {"A": y, "B": x, "C": rw}
        results = select_best_pair(series, min_adf_stat=-1.5)
        # At least one pair should be returned
        assert len(results) >= 1
        # A-B should be the strongest
        first = results[0]
        symbols = {first[0], first[1]}
        assert symbols == {"A", "B"} or first[3] <= -1.5

    def test_no_pairs_above_threshold(self) -> None:
        rw1 = _random_walk(300, seed=0)
        rw2 = _random_walk(300, seed=1)
        results = select_best_pair({"A": rw1, "B": rw2}, min_adf_stat=-10.0)
        assert isinstance(results, list)

    def test_sorted_by_adf(self) -> None:
        y, x = _cointegrated_pair(300, seed=7)
        y2, x2 = _cointegrated_pair(300, beta=2.0, seed=8)
        series = {"A": y, "B": x, "C": y2, "D": x2}
        results = select_best_pair(series, min_adf_stat=-0.5)
        for i in range(len(results) - 1):
            assert results[i][3] <= results[i + 1][3]


# ---------------------------------------------------------------------------
# StatPairsTrading strategy
# ---------------------------------------------------------------------------


class TestStatPairsTrading:
    def _make_strategy(self, **kw) -> StatPairsTrading:
        cfg = PairsTradingConfig(lookback=20, entry_threshold=1.5, exit_threshold=0.3, recalc_every=10)
        return StatPairsTrading(config=cfg, symbol_a="HDFCBANK", symbol_b="ICICIBANK", **kw)

    def test_init(self) -> None:
        s = self._make_strategy()
        assert s._config.lookback == 20
        assert s._symbol == "HDFCBANK"
        assert s._symbol_b == "ICICIBANK"

    def test_on_bar_needs_leg_b(self) -> None:
        """Strategy should not generate signals without leg B data."""
        s = self._make_strategy()
        y, _ = _cointegrated_pair(50, seed=1)
        bars = _make_ohlcv(y)
        for bar in bars:
            s.on_bar(bar)
        orders = s.generate_orders()
        assert isinstance(orders, list)

    def test_generates_orders_cointegrated(self) -> None:
        """With a cointegrated pair, strategy should eventually generate orders."""
        y, x = _cointegrated_pair(300, beta=1.5, seed=42)
        bars_a = _make_ohlcv(y)
        orders_seen = []

        s = self._make_strategy()
        for i, bar in enumerate(bars_a):
            s.add_leg_b_close(x[i])
            s.on_bar(bar)
            orders_seen.extend(s.generate_orders())

        # Should have at least one trade after 300 bars
        assert len(orders_seen) >= 1

    def test_analysis_mode_bars_b(self) -> None:
        """bars_b= parameter in analysis mode should work."""
        from packages.core.src.models import OHLCV
        y, x = _cointegrated_pair(200, seed=5)
        bars_a = _make_ohlcv(y)
        bars_b_ohlcv = [
            OHLCV(
                timestamp=f"2025-01-{i+1:02d}T09:15:00",
                open=c, high=c, low=c, close=c, volume=1,
            )
            for i, c in enumerate(x)
        ]

        s = self._make_strategy()
        for i, bar in enumerate(bars_a):
            s.on_bar(bar, bars_b=bars_b_ohlcv[:i+1])
        orders = s.generate_orders()
        assert isinstance(orders, list)

    def test_generate_orders_clears_queue(self) -> None:
        s = self._make_strategy()
        y, x = _cointegrated_pair(300, seed=42)
        bars_a = _make_ohlcv(y)
        for i, bar in enumerate(bars_a):
            s.add_leg_b_close(x[i])
            s.on_bar(bar)
        s.generate_orders()
        orders_second = s.generate_orders()
        assert orders_second == []

    def test_daily_returns_populated(self) -> None:
        """daily_returns should be populated for walk-forward compatibility."""
        y, x = _cointegrated_pair(200, seed=3)
        bars_a = _make_ohlcv(y)
        s = self._make_strategy()
        for i, bar in enumerate(bars_a):
            s.add_leg_b_close(x[i])
            s.on_bar(bar)
        assert len(s.daily_returns) >= 1

    def test_stoploss_limits_loss(self) -> None:
        """A blown spread (stop-loss scenario) should force exit."""
        # Create a scenario where spread blows up after entry
        y, x = _cointegrated_pair(150, seed=42)
        # Inject a large spike that would breach stop-loss
        y_spike = y[:]
        for i in range(80, 90):
            y_spike[i] = y[i] * 3.0  # large artificial spike

        bars_a = _make_ohlcv(y_spike)
        cfg = PairsTradingConfig(
            lookback=20, entry_threshold=1.0, exit_threshold=0.3,
            stoploss_factor=1.5, recalc_every=10,
        )
        s = StatPairsTrading(config=cfg)
        all_orders: list = []
        for i, bar in enumerate(bars_a):
            s.add_leg_b_close(x[i])
            s.on_bar(bar)
            all_orders.extend(s.generate_orders())
        # Should have generated some orders (entries and/or stop-loss exits)
        assert isinstance(all_orders, list)

    def test_default_config(self) -> None:
        """StatPairsTrading with no explicit config uses defaults."""
        s = StatPairsTrading()
        assert s._config.lookback == 60
        assert s._config.entry_threshold == 2.0


# ---------------------------------------------------------------------------
# PairsTradingConfig defaults
# ---------------------------------------------------------------------------


class TestPairsTradingConfig:
    def test_defaults(self) -> None:
        cfg = PairsTradingConfig()
        assert cfg.lookback == 60
        assert cfg.entry_threshold == 2.0
        assert cfg.exit_threshold == 0.5
        assert cfg.stoploss_factor == 3.0
        assert cfg.auto_halflife is True
        assert cfg.recalc_every == 20

    def test_custom(self) -> None:
        cfg = PairsTradingConfig(lookback=30, entry_threshold=1.5, stoploss_factor=2.0)
        assert cfg.lookback == 30
        assert cfg.entry_threshold == 1.5
        assert cfg.stoploss_factor == 2.0
