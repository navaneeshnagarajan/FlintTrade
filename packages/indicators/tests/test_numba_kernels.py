"""Tests for packages/indicators/src/numba_kernels.py

Verifies that the Numba JIT kernels (_ema_core, _rsi_core, _atr_core) produce
results identical to the pure-Python implementations in trend.py, momentum.py,
and volatility.py.

Tests also exercise the no-Numba fallback path by monkeypatching HAS_NUMBA.

Coverage targets:
- _ema_core: seed correctness, smoothing, constant series, short series
- _rsi_core: Wilder seed, smoothing, edge cases (all gains, all losses)
- _atr_core: true range, seed, Wilder smoothing, known values
- HAS_NUMBA fallback: identical results when kernels run as pure Python
- Integration: indicators produce same output regardless of JIT availability
"""

from __future__ import annotations

import math
from unittest import mock

import numpy as np
import pytest
from numpy.testing import assert_array_almost_equal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rising(n: int, start: float = 100.0, step: float = 1.0) -> np.ndarray:
    """Monotonically rising price series as float64."""
    return np.arange(start, start + n * step, step, dtype=np.float64)


def _flat(n: int, value: float = 100.0) -> np.ndarray:
    """Constant price series."""
    return np.full(n, value, dtype=np.float64)


def _random_prices(n: int, seed: int = 42) -> np.ndarray:
    """Random walk price series (always positive)."""
    rng = np.random.default_rng(seed)
    changes = rng.normal(0, 2, n)
    prices = 100.0 + np.cumsum(changes)
    # Ensure all positive
    prices = np.maximum(prices, 1.0)
    return prices.astype(np.float64)


# ---------------------------------------------------------------------------
# Test _ema_core
# ---------------------------------------------------------------------------


class TestEmaCore:
    """Tests for the _ema_core JIT kernel."""

    def test_ema_core_constant_series(self):
        """EMA of a constant series should equal that constant."""
        from packages.indicators.src.numba_kernels import _ema_core

        close = np.full(20, 50.0, dtype=np.float64)
        k = 2.0 / (5 + 1)
        seed = 50.0
        result = _ema_core(close, k, seed)
        for v in result:
            assert v == pytest.approx(50.0)

    def test_ema_core_seed_value(self):
        """First element should equal the seed value."""
        from packages.indicators.src.numba_kernels import _ema_core

        result = _ema_core(np.array([10.0, 20.0, 30.0], dtype=np.float64), 0.5, 15.0)
        assert result[0] == pytest.approx(15.0)

    def test_ema_core_smoothing(self):
        """Verify EMA formula: result[i] = close[i] * k + result[i-1] * (1-k)."""
        from packages.indicators.src.numba_kernels import _ema_core

        close = np.array([10.0, 10.0, 10.0, 20.0], dtype=np.float64)
        k = 2.0 / (3 + 1)
        seed = 10.0
        result = _ema_core(close, k, seed)
        expected_3 = 20.0 * k + result[2] * (1.0 - k)
        assert result[3] == pytest.approx(expected_3)

    def test_ema_core_matches_pure_python(self):
        """JIT kernel must produce identical results to the trend.py loop."""
        from packages.indicators.src.numba_kernels import _ema_core

        close = _random_prices(200, seed=123)
        period = 10
        k = 2.0 / (period + 1)
        seed = float(np.mean(close[:period]))

        # JIT path
        sliced = np.ascontiguousarray(close[period - 1 :], dtype=np.float64)
        jit_result = _ema_core(sliced, k, seed)

        # Pure-Python path
        py_result = [float("nan")] * len(close)
        py_result[period - 1] = seed
        for i in range(period, len(close)):
            py_result[i] = close[i] * k + py_result[i - 1] * (1.0 - k)

        # Compare from period-1 onward
        for i in range(len(sliced)):
            assert jit_result[i] == pytest.approx(py_result[period - 1 + i], rel=1e-10)

    def test_ema_core_single_element(self):
        """Single element should just return the seed."""
        from packages.indicators.src.numba_kernels import _ema_core

        result = _ema_core(np.array([42.0], dtype=np.float64), 0.5, 42.0)
        assert len(result) == 1
        assert result[0] == pytest.approx(42.0)


# ---------------------------------------------------------------------------
# Test _rsi_core
# ---------------------------------------------------------------------------


class TestRsiCore:
    """Tests for the _rsi_core JIT kernel."""

    def test_rsi_core_all_gains(self):
        """When all changes are positive, RSI should be 100."""
        from packages.indicators.src.numba_kernels import _rsi_core

        changes = np.full(28, 1.0, dtype=np.float64)
        result = _rsi_core(changes, 14)
        # RSI at index 14 and beyond should be 100
        assert result[14] == pytest.approx(100.0)
        assert result[27] == pytest.approx(100.0)

    def test_rsi_core_all_losses(self):
        """When all changes are negative, RSI should be 0."""
        from packages.indicators.src.numba_kernels import _rsi_core

        changes = np.full(28, -1.0, dtype=np.float64)
        result = _rsi_core(changes, 14)
        assert result[14] == pytest.approx(0.0)
        assert result[27] == pytest.approx(0.0)

    def test_rsi_core_equal_gains_losses(self):
        """When gains and losses are symmetric, RSI should be near 50."""
        from packages.indicators.src.numba_kernels import _rsi_core

        # Alternating +1, -1
        changes = np.array([1.0, -1.0] * 14, dtype=np.float64)
        result = _rsi_core(changes, 14)
        # First RSI value should be 50 (equal avg gain and avg loss)
        assert result[14] == pytest.approx(50.0)

    def test_rsi_core_matches_pure_python(self):
        """JIT kernel must produce identical results to the momentum.py loop."""
        from packages.indicators.src.numba_kernels import _rsi_core

        close = _random_prices(200, seed=77)
        period = 14
        delta = np.diff(close)
        gain = np.where(delta > 0, delta, 0.0)
        loss = np.where(delta < 0, -delta, 0.0)

        # JIT path
        delta_c = np.ascontiguousarray(delta, dtype=np.float64)
        jit_result = _rsi_core(delta_c, period)

        # Pure-Python path
        n = len(close)
        py_result = [float("nan")] * n
        avg_gain = float(np.mean(gain[:period]))
        avg_loss = float(np.mean(loss[:period]))
        if avg_loss == 0.0:
            py_result[period] = 100.0
        else:
            rs = avg_gain / avg_loss
            py_result[period] = 100.0 - (100.0 / (1.0 + rs))

        for i in range(period, len(delta)):
            avg_gain = (avg_gain * (period - 1) + gain[i]) / period
            avg_loss = (avg_loss * (period - 1) + loss[i]) / period
            if avg_loss == 0.0:
                py_result[i + 1] = 100.0
            else:
                rs = avg_gain / avg_loss
                py_result[i + 1] = 100.0 - (100.0 / (1.0 + rs))

        # Compare valid indices
        for i in range(period, n):
            if math.isnan(py_result[i]):
                assert math.isnan(jit_result[i])
            else:
                assert jit_result[i] == pytest.approx(py_result[i], rel=1e-10)

    def test_rsi_core_nan_before_period(self):
        """Values before the period should be NaN."""
        from packages.indicators.src.numba_kernels import _rsi_core

        changes = np.array([1.0, -0.5, 0.3, -0.2, 1.5, -1.0, 0.8, -0.4] * 5, dtype=np.float64)
        result = _rsi_core(changes, 14)
        for i in range(14):
            assert math.isnan(result[i])


# ---------------------------------------------------------------------------
# Test _atr_core
# ---------------------------------------------------------------------------


class TestAtrCore:
    """Tests for the _atr_core JIT kernel."""

    def test_atr_core_constant_range(self):
        """When H-L is constant and no gaps, ATR should equal that range."""
        from packages.indicators.src.numba_kernels import _atr_core

        n = 30
        highs = np.full(n, 110.0, dtype=np.float64)
        lows = np.full(n, 100.0, dtype=np.float64)
        closes = np.full(n, 105.0, dtype=np.float64)
        result = _atr_core(highs, lows, closes, 14)
        # After warmup, ATR should converge to 10.0
        assert result[13] == pytest.approx(10.0)
        assert result[29] == pytest.approx(10.0)

    def test_atr_core_matches_pure_python(self):
        """JIT kernel must produce identical results to the volatility.py loop."""
        from packages.indicators.src.numba_kernels import _atr_core

        n = 200
        rng = np.random.default_rng(99)
        base = 100.0 + np.cumsum(rng.normal(0, 1, n))
        highs = (base + rng.uniform(0.5, 2.0, n)).astype(np.float64)
        lows = (base - rng.uniform(0.5, 2.0, n)).astype(np.float64)
        closes = base.astype(np.float64)
        period = 14

        # JIT path
        jit_result = _atr_core(highs, lows, closes, period)

        # Pure-Python path
        tr = [0.0] * n
        tr[0] = float(highs[0] - lows[0])
        for i in range(1, n):
            hl = float(highs[i] - lows[i])
            hc = abs(float(highs[i]) - float(closes[i - 1]))
            lc = abs(float(lows[i]) - float(closes[i - 1]))
            tr[i] = max(hl, hc, lc)

        py_result = [float("nan")] * n
        py_result[period - 1] = sum(tr[:period]) / period
        for i in range(period, n):
            py_result[i] = (py_result[i - 1] * (period - 1) + tr[i]) / period

        for i in range(period - 1, n):
            assert jit_result[i] == pytest.approx(py_result[i], rel=1e-10)

    def test_atr_core_nan_before_period(self):
        """Values before period - 1 should be NaN."""
        from packages.indicators.src.numba_kernels import _atr_core

        n = 20
        result = _atr_core(
            np.full(n, 110.0, dtype=np.float64),
            np.full(n, 100.0, dtype=np.float64),
            np.full(n, 105.0, dtype=np.float64),
            14,
        )
        for i in range(13):
            assert math.isnan(result[i])
        assert not math.isnan(result[13])


# ---------------------------------------------------------------------------
# Test HAS_NUMBA fallback — indicator-level integration
# ---------------------------------------------------------------------------


class TestNumbaFallback:
    """Verify indicators produce identical output with or without Numba."""

    def test_ema_with_and_without_numba(self):
        """EMA output must be identical regardless of HAS_NUMBA."""
        close = _random_prices(2000, seed=11)
        period = 20

        from packages.indicators.src import trend

        # With current HAS_NUMBA setting
        result_current = trend.ema(close, period)

        # Force HAS_NUMBA = False
        with mock.patch.object(trend, "HAS_NUMBA", False):
            result_no_numba = trend.ema(close, period)

        assert_array_almost_equal(result_current, result_no_numba, decimal=10)

    def test_rsi_with_and_without_numba(self):
        """RSI output must be identical regardless of HAS_NUMBA."""
        close = _random_prices(2000, seed=22)

        from packages.indicators.src import momentum

        result_current = momentum.rsi(close, 14)

        with mock.patch.object(momentum, "HAS_NUMBA", False):
            result_no_numba = momentum.rsi(close, 14)

        # Compare non-NaN values
        mask = ~np.isnan(result_current) & ~np.isnan(result_no_numba)
        assert_array_almost_equal(result_current[mask], result_no_numba[mask], decimal=10)

    def test_atr_with_and_without_numba(self):
        """ATR output must be identical regardless of HAS_NUMBA."""
        n = 2000
        rng = np.random.default_rng(33)
        base = 100.0 + np.cumsum(rng.normal(0, 1, n))
        high = (base + rng.uniform(0.5, 2.0, n)).astype(np.float64)
        low = (base - rng.uniform(0.5, 2.0, n)).astype(np.float64)
        close = base.astype(np.float64)

        from packages.indicators.src import volatility

        result_current = volatility.atr(high, low, close, 14)

        with mock.patch.object(volatility, "HAS_NUMBA", False):
            result_no_numba = volatility.atr(high, low, close, 14)

        mask = ~np.isnan(result_current) & ~np.isnan(result_no_numba)
        assert_array_almost_equal(result_current[mask], result_no_numba[mask], decimal=10)
