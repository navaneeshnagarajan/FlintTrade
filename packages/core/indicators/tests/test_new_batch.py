"""Tests for new batch indicators: KAMA, ADX, DMI, LinReg, MOM, AO.

20+ tests covering shape, warm-up NaN boundaries, mathematical properties,
and edge cases.
"""

from __future__ import annotations

import numpy as np
import pytest
from numpy.testing import assert_array_almost_equal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _arange(n: int, start: float = 1.0, step: float = 1.0) -> np.ndarray:
    return np.arange(start, start + n * step, step, dtype=np.float64)


def _flat(n: int, value: float = 100.0) -> np.ndarray:
    return np.full(n, value, dtype=np.float64)


def _ohlcv(
    n: int = 100,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Realistic OHLCV arrays."""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + np.abs(rng.normal(0, 0.3, n))
    low = close - np.abs(rng.normal(0, 0.3, n))
    open_ = close + rng.normal(0, 0.2, n)
    volume = np.abs(rng.normal(1_000_000, 200_000, n))
    return (
        high.astype(np.float64),
        low.astype(np.float64),
        close.astype(np.float64),
        open_.astype(np.float64),
        volume.astype(np.float64),
    )


# ---------------------------------------------------------------------------
# KAMA
# ---------------------------------------------------------------------------


class TestKAMA:
    def test_kama_shape(self):
        from flinttrade_indicators.trend import kama

        close = _arange(50)
        result = kama(close, period=10)
        assert result.shape == (50,)

    def test_kama_warmup_nans(self):
        """First `period` values must be NaN."""
        from flinttrade_indicators.trend import kama

        close = _arange(50)
        result = kama(close, period=10)
        assert np.all(np.isnan(result[:10]))

    def test_kama_seed_equals_close_at_period(self):
        """KAMA is seeded with close[period] at the seed bar."""
        from flinttrade_indicators.trend import kama

        close = _arange(50)
        result = kama(close, period=10)
        assert not np.isnan(result[10])
        assert result[10] == pytest.approx(close[10])

    def test_kama_flat_market_stays_near_constant(self):
        """On a flat series KAMA should converge to that constant."""
        from flinttrade_indicators.trend import kama

        close = _flat(100, 50.0)
        result = kama(close, period=10)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.full(len(valid), 50.0), decimal=6)

    def test_kama_invalid_period_raises(self):
        from flinttrade_indicators.trend import kama

        with pytest.raises(ValueError, match="period"):
            kama(_arange(20), period=0)

    def test_kama_fast_not_less_than_slow_raises(self):
        from flinttrade_indicators.trend import kama

        with pytest.raises(ValueError):
            kama(_arange(20), period=10, fast_period=10, slow_period=10)

    def test_kama_returns_float64(self):
        from flinttrade_indicators.trend import kama

        close = _arange(50)
        result = kama(close, period=10)
        assert result.dtype == np.float64

    def test_kama_trending_market_follows_price(self):
        """KAMA should roughly track a strongly trending series."""
        from flinttrade_indicators.trend import kama

        close = _arange(100, start=100.0, step=1.0)
        result = kama(close, period=10)
        # Final KAMA should be within reasonable lag distance of final close
        assert result[-1] > 100.0  # above starting price


# ---------------------------------------------------------------------------
# ADX
# ---------------------------------------------------------------------------


class TestADX:
    def test_adx_shape(self):
        from flinttrade_indicators.trend import adx

        high, low, close, _, _ = _ohlcv(100)
        result = adx(high, low, close, period=14)
        assert result.shape == (100,)

    def test_adx_warmup_nans(self):
        """First 2*period-1 values must be NaN."""
        from flinttrade_indicators.trend import adx

        high, low, close, _, _ = _ohlcv(100)
        period = 14
        result = adx(high, low, close, period=period)
        # First 2*14-1 = 27 values should be NaN
        assert np.all(np.isnan(result[: 2 * period - 1]))

    def test_adx_range_0_to_100(self):
        """ADX should always be in [0, 100]."""
        from flinttrade_indicators.trend import adx

        high, low, close, _, _ = _ohlcv(200)
        result = adx(high, low, close)
        valid = result[~np.isnan(result)]
        assert len(valid) > 0
        assert float(np.min(valid)) >= 0.0
        assert float(np.max(valid)) <= 100.0

    def test_adx_returns_float64(self):
        from flinttrade_indicators.trend import adx

        high, low, close, _, _ = _ohlcv(100)
        assert adx(high, low, close).dtype == np.float64

    def test_adx_strong_trend_above_25(self):
        """A strongly trending series should produce ADX > 25."""
        from flinttrade_indicators.trend import adx

        n = 150
        close = np.linspace(100, 200, n, dtype=np.float64)
        high = close + 0.5
        low = close - 0.5
        result = adx(high, low, close, period=14)
        valid = result[~np.isnan(result)]
        # Eventually the trend should be detected
        assert float(np.max(valid)) > 25.0


# ---------------------------------------------------------------------------
# DMI
# ---------------------------------------------------------------------------


class TestDMI:
    def test_dmi_shape(self):
        from flinttrade_indicators.trend import dmi

        high, low, close, _, _ = _ohlcv(100)
        plus_di, minus_di = dmi(high, low, close)
        assert plus_di.shape == (100,)
        assert minus_di.shape == (100,)

    def test_dmi_warmup_nans(self):
        from flinttrade_indicators.trend import dmi

        high, low, close, _, _ = _ohlcv(100)
        period = 14
        plus_di, minus_di = dmi(high, low, close, period=period)
        # First `period` bars are NaN (period index is first valid)
        assert np.all(np.isnan(plus_di[:period]))
        assert np.all(np.isnan(minus_di[:period]))

    def test_dmi_range_0_to_100(self):
        """DI values are percentages: should be in [0, 100]."""
        from flinttrade_indicators.trend import dmi

        high, low, close, _, _ = _ohlcv(200)
        plus_di, minus_di = dmi(high, low, close)
        for arr in (plus_di, minus_di):
            valid = arr[~np.isnan(arr)]
            assert float(np.min(valid)) >= 0.0
            assert float(np.max(valid)) <= 100.0

    def test_dmi_uptrend_plusdi_dominates(self):
        """In a strong uptrend, +DI should generally exceed -DI."""
        from flinttrade_indicators.trend import dmi

        n = 100
        close = np.linspace(100, 200, n, dtype=np.float64)
        high = close + 0.5
        low = close - 0.5
        plus_di, minus_di = dmi(high, low, close, period=14)
        valid_plus = plus_di[~np.isnan(plus_di)]
        valid_minus = minus_di[~np.isnan(minus_di)]
        # Mean +DI should exceed mean -DI in a steady uptrend
        assert float(np.mean(valid_plus)) > float(np.mean(valid_minus))

    def test_dmi_returns_float64(self):
        from flinttrade_indicators.trend import dmi

        high, low, close, _, _ = _ohlcv(100)
        plus_di, minus_di = dmi(high, low, close)
        assert plus_di.dtype == np.float64
        assert minus_di.dtype == np.float64


# ---------------------------------------------------------------------------
# LinReg
# ---------------------------------------------------------------------------


class TestLinReg:
    def test_linreg_shape(self):
        from flinttrade_indicators.trend import linreg

        close = _arange(50)
        result = linreg(close, period=14)
        assert result.shape == (50,)

    def test_linreg_warmup_nans(self):
        from flinttrade_indicators.trend import linreg

        close = _arange(50)
        result = linreg(close, period=14)
        assert np.all(np.isnan(result[:13]))
        assert not np.isnan(result[13])

    def test_linreg_linear_series_equals_close(self):
        """For a perfectly linear series, linear regression = close exactly."""
        from flinttrade_indicators.trend import linreg

        close = _arange(50, start=10.0, step=2.0)
        result = linreg(close, period=5)
        valid_idx = ~np.isnan(result)
        assert_array_almost_equal(result[valid_idx], close[valid_idx], decimal=8)

    def test_linreg_constant_series_equals_constant(self):
        """For a flat series, LinReg should equal the constant."""
        from flinttrade_indicators.trend import linreg

        close = _flat(50, 100.0)
        result = linreg(close, period=5)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.full(len(valid), 100.0))

    def test_linreg_period_1_raises(self):
        from flinttrade_indicators.trend import linreg

        with pytest.raises(ValueError, match="period"):
            linreg(_arange(10), period=1)

    def test_linreg_returns_float64(self):
        from flinttrade_indicators.trend import linreg

        assert linreg(_arange(20), period=5).dtype == np.float64


# ---------------------------------------------------------------------------
# MOM
# ---------------------------------------------------------------------------


class TestMOM:
    def test_mom_shape(self):
        from flinttrade_indicators.momentum import mom

        result = mom(_arange(50))
        assert result.shape == (50,)

    def test_mom_warmup_nans(self):
        from flinttrade_indicators.momentum import mom

        result = mom(_arange(50), period=10)
        assert np.all(np.isnan(result[:10]))

    def test_mom_linear_series_equals_period_times_step(self):
        """On a+n*step series, MOM = period * step for all valid bars."""
        from flinttrade_indicators.momentum import mom

        step = 2.0
        close = _arange(50, start=10.0, step=step)
        period = 5
        result = mom(close, period=period)
        valid = result[~np.isnan(result)]
        expected = period * step
        assert_array_almost_equal(valid, np.full(len(valid), expected))

    def test_mom_flat_series_is_zero(self):
        from flinttrade_indicators.momentum import mom

        result = mom(_flat(30, 100.0), period=5)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.zeros(len(valid)))

    def test_mom_invalid_period_raises(self):
        from flinttrade_indicators.momentum import mom

        with pytest.raises(ValueError, match="period"):
            mom(_arange(20), period=0)

    def test_mom_returns_float64(self):
        from flinttrade_indicators.momentum import mom

        assert mom(_arange(20)).dtype == np.float64


# ---------------------------------------------------------------------------
# Awesome Oscillator
# ---------------------------------------------------------------------------


class TestAwesomeOscillator:
    def test_ao_shape(self):
        from flinttrade_indicators.momentum import awesome_oscillator

        high, low, close, _, _ = _ohlcv(100)
        result = awesome_oscillator(high, low, fast=5, slow=34)
        assert result.shape == (100,)

    def test_ao_warmup_nans(self):
        """First slow-1 values must be NaN."""
        from flinttrade_indicators.momentum import awesome_oscillator

        high, low, close, _, _ = _ohlcv(100)
        result = awesome_oscillator(high, low, fast=5, slow=34)
        assert np.all(np.isnan(result[:33]))
        assert not np.isnan(result[33])

    def test_ao_flat_series_is_zero(self):
        """On a constant H/L, midpoint SMA difference = 0."""
        from flinttrade_indicators.momentum import awesome_oscillator

        high = _flat(100, 110.0)
        low = _flat(100, 90.0)
        result = awesome_oscillator(high, low, fast=5, slow=34)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.zeros(len(valid)))

    def test_ao_fast_ge_slow_raises(self):
        from flinttrade_indicators.momentum import awesome_oscillator

        high, low, close, _, _ = _ohlcv(100)
        with pytest.raises(ValueError):
            awesome_oscillator(high, low, fast=34, slow=5)

    def test_ao_returns_float64(self):
        from flinttrade_indicators.momentum import awesome_oscillator

        high, low, close, _, _ = _ohlcv(100)
        assert awesome_oscillator(high, low).dtype == np.float64

    def test_ao_returns_array_not_scalar(self):
        from flinttrade_indicators.momentum import awesome_oscillator

        high, low, close, _, _ = _ohlcv(100)
        result = awesome_oscillator(high, low)
        assert isinstance(result, np.ndarray)
