"""Tests for new indicators added in Task 3.4.

Covers:
  Trend:    TEMA, WMA, Hull, Ichimoku, Parabolic SAR
  Momentum: CCI, ROC, CMO, TRIX, StochRSI, BOP
  Volatility: Donchian Channels, NATR, Historical Volatility
  Volume:   OBV, AD, CMF, MFI, VWMA
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
    n: int = 60,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Generate realistic OHLCV arrays."""
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
# TEMA
# ---------------------------------------------------------------------------

class TestTEMA:
    def test_tema_shape(self):
        from packages.indicators.src.trend import tema
        close = _arange(60)
        result = tema(close, period=5)
        assert result.shape == (60,)

    def test_tema_constant_series_equals_constant(self):
        from packages.indicators.src.trend import tema
        close = _flat(80, 50.0)
        result = tema(close, period=5)
        valid = result[~np.isnan(result)]
        assert len(valid) > 0
        assert_array_almost_equal(valid, np.full(len(valid), 50.0))

    def test_tema_tracks_rising_series_closer_than_sma(self):
        """On a steadily rising series TEMA should be closer to close than SMA."""
        from packages.indicators.src.trend import sma, tema
        close = _arange(100, start=100.0, step=1.0)
        period = 10
        s = sma(close, period)
        t = tema(close, period)
        last_close = close[-1]
        s_lag = abs(last_close - s[-1])
        t_lag = abs(last_close - t[-1])
        assert t_lag < s_lag, "TEMA should exhibit less lag than SMA on a rising series"

    def test_tema_warmup_nans(self):
        """TEMA needs roughly 3*(period-1) warm-up bars."""
        from packages.indicators.src.trend import tema
        close = _arange(80)
        period = 5
        result = tema(close, period=period)
        # At minimum the first 2*(period-1) values must be NaN
        min_nans = 2 * (period - 1)
        assert np.all(np.isnan(result[:min_nans]))

    def test_tema_short_series_all_nan(self):
        from packages.indicators.src.trend import tema
        close = _arange(5)
        result = tema(close, period=10)
        assert np.all(np.isnan(result))


# ---------------------------------------------------------------------------
# WMA
# ---------------------------------------------------------------------------

class TestWMA:
    def test_wma_shape(self):
        from packages.indicators.src.trend import wma
        close = _arange(30)
        result = wma(close, period=5)
        assert result.shape == (30,)

    def test_wma_warmup_nans(self):
        from packages.indicators.src.trend import wma
        close = _arange(20)
        result = wma(close, period=5)
        assert np.all(np.isnan(result[:4]))
        assert not np.isnan(result[4])

    def test_wma_constant_series_equals_constant(self):
        from packages.indicators.src.trend import wma
        close = _flat(30, 42.0)
        result = wma(close, period=5)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.full(len(valid), 42.0))

    def test_wma_known_value(self):
        """WMA(3) on [1,2,3] = (1*1 + 2*2 + 3*3) / 6 = 14/6."""
        from packages.indicators.src.trend import wma
        close = np.array([1.0, 2.0, 3.0], dtype=np.float64)
        result = wma(close, period=3)
        assert result[2] == pytest.approx(14.0 / 6.0)

    def test_wma_invalid_period_raises(self):
        from packages.indicators.src.trend import wma
        with pytest.raises(ValueError):
            wma(_arange(5), period=0)


# ---------------------------------------------------------------------------
# Hull
# ---------------------------------------------------------------------------

class TestHull:
    def test_hull_shape(self):
        from packages.indicators.src.trend import hull
        close = _arange(60)
        result = hull(close, period=9)
        assert result.shape == (60,)

    def test_hull_constant_series_equals_constant(self):
        from packages.indicators.src.trend import hull
        close = _flat(60, 75.0)
        result = hull(close, period=9)
        valid = result[~np.isnan(result)]
        assert len(valid) > 0
        assert_array_almost_equal(valid, np.full(len(valid), 75.0), decimal=5)

    def test_hull_less_lag_than_sma(self):
        """HMA should track a rising series closer to close than plain SMA."""
        from packages.indicators.src.trend import hull, sma
        close = _arange(100, start=100.0, step=1.0)
        period = 9
        h = hull(close, period)
        s = sma(close, period)
        last_close = close[-1]
        h_lag = abs(last_close - h[-1])
        s_lag = abs(last_close - s[-1])
        assert h_lag < s_lag, "HMA should exhibit less lag than SMA"


# ---------------------------------------------------------------------------
# Ichimoku
# ---------------------------------------------------------------------------

class TestIchimoku:
    def test_ichimoku_returns_five_arrays(self):
        from packages.indicators.src.trend import ichimoku
        h, lo, c, _, _ = _ohlcv(100)
        result = ichimoku(h, lo, c)
        assert len(result) == 5
        for arr in result:
            assert arr.shape == (100,)

    def test_ichimoku_tenkan_is_finite(self):
        """Tenkan-sen values where not NaN should be finite positive numbers."""
        from packages.indicators.src.trend import ichimoku
        h, lo, c, _, _ = _ohlcv(100)
        tenkan, _, _, _, _ = ichimoku(h, lo, c, conversion_period=9)
        valid = ~np.isnan(tenkan)
        assert np.all(np.isfinite(tenkan[valid]))
        assert np.all(tenkan[valid] > 0)

    def test_ichimoku_senkou_a_is_mean_of_tenkan_kijun(self):
        from packages.indicators.src.trend import ichimoku
        h, lo, c, _, _ = _ohlcv(100)
        tenkan, kijun, senkou_a, _, _ = ichimoku(h, lo, c)
        valid = ~np.isnan(tenkan) & ~np.isnan(kijun) & ~np.isnan(senkou_a)
        expected = (tenkan[valid] + kijun[valid]) / 2.0
        assert_array_almost_equal(senkou_a[valid], expected)

    def test_ichimoku_chikou_shift(self):
        from packages.indicators.src.trend import ichimoku
        h, lo, c, _, _ = _ohlcv(100)
        displacement = 26
        _, _, _, _, chikou = ichimoku(h, lo, c, displacement=displacement)
        # chikou[0] should equal close[displacement]
        assert chikou[0] == pytest.approx(c[displacement])

    def test_ichimoku_warmup_nans(self):
        from packages.indicators.src.trend import ichimoku
        h, lo, c, _, _ = _ohlcv(100)
        tenkan, _, _, _, _ = ichimoku(h, lo, c, conversion_period=9)
        assert np.all(np.isnan(tenkan[:8]))
        assert not np.isnan(tenkan[8])


# ---------------------------------------------------------------------------
# Parabolic SAR
# ---------------------------------------------------------------------------

class TestParabolicSAR:
    def test_psar_shape(self):
        from packages.indicators.src.trend import parabolic_sar
        h, lo, _, _, _ = _ohlcv(60)
        sar, direction = parabolic_sar(h, lo)
        assert sar.shape == (60,)
        assert direction.shape == (60,)

    def test_psar_first_bar_is_nan(self):
        from packages.indicators.src.trend import parabolic_sar
        h, lo, _, _, _ = _ohlcv(60)
        sar, _ = parabolic_sar(h, lo)
        assert np.isnan(sar[0])

    def test_psar_direction_is_bool(self):
        from packages.indicators.src.trend import parabolic_sar
        h, lo, _, _, _ = _ohlcv(60)
        _, direction = parabolic_sar(h, lo)
        assert direction.dtype == np.bool_

    def test_psar_uptrend_sar_below_low(self):
        """In uptrend bars, SAR must be below the low of that bar."""
        from packages.indicators.src.trend import parabolic_sar
        h, lo, _, _, _ = _ohlcv(100, seed=7)
        sar, direction = parabolic_sar(h, lo)
        for i in range(1, len(sar)):
            if np.isnan(sar[i]):
                continue
            if direction[i]:  # uptrend
                assert sar[i] <= lo[i] + 1e-9, (
                    f"Bar {i}: uptrend but SAR={sar[i]:.4f} > low={lo[i]:.4f}"
                )

    def test_psar_downtrend_sar_above_high(self):
        """In downtrend bars, SAR must be above the high of that bar."""
        from packages.indicators.src.trend import parabolic_sar
        h, lo, _, _, _ = _ohlcv(100, seed=7)
        sar, direction = parabolic_sar(h, lo)
        for i in range(1, len(sar)):
            if np.isnan(sar[i]):
                continue
            if not direction[i]:  # downtrend
                assert sar[i] >= h[i] - 1e-9, (
                    f"Bar {i}: downtrend but SAR={sar[i]:.4f} < high={h[i]:.4f}"
                )


# ---------------------------------------------------------------------------
# CCI
# ---------------------------------------------------------------------------

class TestCCI:
    def test_cci_shape(self):
        from packages.indicators.src.momentum import cci
        h, lo, c, _, _ = _ohlcv(60)
        result = cci(h, lo, c, period=20)
        assert result.shape == (60,)

    def test_cci_warmup_nans(self):
        from packages.indicators.src.momentum import cci
        h, lo, c, _, _ = _ohlcv(60)
        result = cci(h, lo, c, period=20)
        assert np.all(np.isnan(result[:19]))
        assert not np.isnan(result[19])

    def test_cci_zero_on_flat_series(self):
        """Constant price -> zero mean deviation -> CCI = 0."""
        from packages.indicators.src.momentum import cci
        n = 30
        h = _flat(n, 102.0)
        lo = _flat(n, 98.0)
        c = _flat(n, 100.0)
        result = cci(h, lo, c, period=10)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.zeros(len(valid)))

    def test_cci_rising_series_positive(self):
        """Steadily rising typical prices should produce positive CCI."""
        from packages.indicators.src.momentum import cci
        n = 50
        close = _arange(n, start=100.0, step=1.0)
        high = close + 1.0
        low = close - 1.0
        result = cci(high.astype(np.float64), low.astype(np.float64), close, period=10)
        valid = result[~np.isnan(result)]
        assert np.all(valid > 0)


# ---------------------------------------------------------------------------
# ROC
# ---------------------------------------------------------------------------

class TestROC:
    def test_roc_shape(self):
        from packages.indicators.src.momentum import roc
        close = _arange(30)
        result = roc(close, period=12)
        assert result.shape == (30,)

    def test_roc_warmup_nans(self):
        from packages.indicators.src.momentum import roc
        close = _arange(30)
        result = roc(close, period=5)
        assert np.all(np.isnan(result[:5]))
        assert not np.isnan(result[5])

    def test_roc_constant_series_is_zero(self):
        from packages.indicators.src.momentum import roc
        close = _flat(30, 100.0)
        result = roc(close, period=5)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.zeros(len(valid)))

    def test_roc_known_value(self):
        """ROC(5) at index 5: (close[5] - close[0]) / close[0] * 100."""
        from packages.indicators.src.momentum import roc
        close = np.array([10.0, 11.0, 12.0, 13.0, 14.0, 15.0], dtype=np.float64)
        result = roc(close, period=5)
        expected = (15.0 - 10.0) / 10.0 * 100.0
        assert result[5] == pytest.approx(expected)

    def test_roc_rising_series_positive(self):
        from packages.indicators.src.momentum import roc
        close = _arange(40, start=100.0, step=1.0)
        result = roc(close, period=5)
        valid = result[~np.isnan(result)]
        assert np.all(valid > 0)


# ---------------------------------------------------------------------------
# CMO
# ---------------------------------------------------------------------------

class TestCMO:
    def test_cmo_shape(self):
        from packages.indicators.src.momentum import cmo
        close = _arange(50)
        result = cmo(close, period=14)
        assert result.shape == (50,)

    def test_cmo_warmup_nans(self):
        from packages.indicators.src.momentum import cmo
        close = _arange(30)
        result = cmo(close, period=5)
        assert np.all(np.isnan(result[:5]))
        assert not np.isnan(result[5])

    def test_cmo_range_minus100_to_100(self):
        from packages.indicators.src.momentum import cmo
        rng = np.random.default_rng(17)
        close = (100.0 + np.cumsum(rng.normal(0, 0.5, 100))).astype(np.float64)
        result = cmo(close, period=14)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= -100.0) and np.all(valid <= 100.0)

    def test_cmo_constant_series_is_zero(self):
        from packages.indicators.src.momentum import cmo
        close = _flat(30, 100.0)
        result = cmo(close, period=5)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.zeros(len(valid)))

    def test_cmo_uptrend_is_positive(self):
        from packages.indicators.src.momentum import cmo
        close = _arange(40, start=100.0, step=1.0)
        result = cmo(close, period=5)
        valid = result[~np.isnan(result)]
        assert np.all(valid == pytest.approx(100.0))


# ---------------------------------------------------------------------------
# TRIX
# ---------------------------------------------------------------------------

class TestTRIX:
    def test_trix_shape(self):
        from packages.indicators.src.momentum import trix
        close = _arange(80, start=1.0)
        result = trix(close, period=5)
        assert result.shape == (80,)

    def test_trix_warmup_nans(self):
        from packages.indicators.src.momentum import trix
        close = _arange(60, start=1.0)
        result = trix(close, period=5)
        # First valid value appears after triple EMA warmup
        assert np.isnan(result[0])

    def test_trix_negative_close_raises(self):
        from packages.indicators.src.momentum import trix
        close = np.array([-1.0, 2.0, 3.0, 4.0, 5.0] * 10, dtype=np.float64)
        with pytest.raises(ValueError, match="strictly positive"):
            trix(close, period=5)

    def test_trix_oscillates_on_random_series(self):
        """TRIX should produce both positive and negative values on a mean-reverting series."""
        from packages.indicators.src.momentum import trix
        rng = np.random.default_rng(55)
        # Use a stationary random walk so TRIX crosses zero
        close = 100.0 + rng.normal(0, 1, 300)
        close = np.where(close <= 0, 1.0, close).astype(np.float64)
        result = trix(close, period=5)
        valid = result[~np.isnan(result)]
        assert len(valid) > 0, "TRIX should produce at least some valid values"
        assert np.any(valid > 0) and np.any(valid < 0)


# ---------------------------------------------------------------------------
# StochRSI
# ---------------------------------------------------------------------------

class TestStochRSI:
    def test_stoch_rsi_shape(self):
        from packages.indicators.src.momentum import stoch_rsi
        close = _arange(80)
        k, d = stoch_rsi(close)
        assert k.shape == (80,)
        assert d.shape == (80,)

    def test_stoch_rsi_k_range_0_to_100(self):
        from packages.indicators.src.momentum import stoch_rsi
        rng = np.random.default_rng(33)
        close = (100.0 + np.cumsum(rng.normal(0, 0.5, 100))).astype(np.float64)
        k, _ = stoch_rsi(close)
        valid = k[~np.isnan(k)]
        assert np.all(valid >= 0.0) and np.all(valid <= 100.0)

    def test_stoch_rsi_d_smoother_than_k(self):
        """D should be smoother (lower std dev) than K on same data."""
        from packages.indicators.src.momentum import stoch_rsi
        rng = np.random.default_rng(44)
        close = (100.0 + np.cumsum(rng.normal(0, 0.5, 150))).astype(np.float64)
        k, d = stoch_rsi(close)
        k_valid = k[~np.isnan(k)]
        d_valid = d[~np.isnan(d)]
        assert np.std(d_valid) <= np.std(k_valid)


# ---------------------------------------------------------------------------
# BOP
# ---------------------------------------------------------------------------

class TestBOP:
    def test_bop_shape(self):
        from packages.indicators.src.momentum import bop
        h, lo, c, o, _ = _ohlcv(40)
        result = bop(o, h, lo, c)
        assert result.shape == (40,)

    def test_bop_range_when_open_inside_range(self):
        """When open is clamped inside [low, high], BOP is in [-1, 1]."""
        from packages.indicators.src.momentum import bop
        n = 30
        rng = np.random.default_rng(19)
        low = np.abs(rng.normal(98.0, 0.3, n)).astype(np.float64)
        high = (low + np.abs(rng.normal(4.0, 0.3, n))).astype(np.float64)
        close = (low + rng.random(n) * (high - low)).astype(np.float64)
        open_ = (low + rng.random(n) * (high - low)).astype(np.float64)
        result = bop(open_, high, low, close)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= -1.0 - 1e-9) and np.all(valid <= 1.0 + 1e-9)

    def test_bop_close_minus_open_positive_means_positive(self):
        """When close > open and close < high, BOP should be positive."""
        from packages.indicators.src.momentum import bop
        n = 10
        open_ = _flat(n, 99.0)
        high = _flat(n, 102.0)
        low = _flat(n, 98.0)
        close = _flat(n, 101.0)
        result = bop(open_, high, low, close)
        assert np.all(result > 0)

    def test_bop_zero_range_returns_zero(self):
        from packages.indicators.src.momentum import bop
        n = 5
        h = _flat(n, 100.0)
        lo = _flat(n, 100.0)
        c = _flat(n, 100.0)
        o = _flat(n, 100.0)
        result = bop(o, h, lo, c)
        assert_array_almost_equal(result, np.zeros(n))

    def test_bop_length_mismatch_raises(self):
        from packages.indicators.src.momentum import bop
        with pytest.raises(ValueError):
            bop(
                np.array([1.0, 2.0], dtype=np.float64),
                np.array([2.0, 3.0], dtype=np.float64),
                np.array([0.5, 1.5], dtype=np.float64),
                np.array([1.5], dtype=np.float64),
            )


# ---------------------------------------------------------------------------
# Donchian Channels
# ---------------------------------------------------------------------------

class TestDonchianChannels:
    def test_donchian_shape(self):
        from packages.indicators.src.volatility import donchian_channels
        h, lo, _, _, _ = _ohlcv(60)
        upper, middle, lower = donchian_channels(h, lo, period=20)
        assert upper.shape == (60,)
        assert middle.shape == (60,)
        assert lower.shape == (60,)

    def test_donchian_warmup_nans(self):
        from packages.indicators.src.volatility import donchian_channels
        h, lo, _, _, _ = _ohlcv(60)
        upper, _, lower = donchian_channels(h, lo, period=20)
        assert np.all(np.isnan(upper[:19]))
        assert not np.isnan(upper[19])

    def test_donchian_upper_gt_lower(self):
        from packages.indicators.src.volatility import donchian_channels
        h, lo, _, _, _ = _ohlcv(60)
        upper, middle, lower = donchian_channels(h, lo, period=10)
        valid = ~np.isnan(upper) & ~np.isnan(lower)
        assert np.all(upper[valid] >= lower[valid])

    def test_donchian_middle_is_mean_of_bands(self):
        from packages.indicators.src.volatility import donchian_channels
        h, lo, _, _, _ = _ohlcv(60)
        upper, middle, lower = donchian_channels(h, lo, period=10)
        valid = ~np.isnan(upper) & ~np.isnan(lower) & ~np.isnan(middle)
        expected = (upper[valid] + lower[valid]) / 2.0
        assert_array_almost_equal(middle[valid], expected)

    def test_donchian_constant_series_has_zero_width(self):
        from packages.indicators.src.volatility import donchian_channels
        n = 30
        h = _flat(n, 102.0)
        lo = _flat(n, 102.0)
        upper, _, lower = donchian_channels(h, lo, period=5)
        valid = ~np.isnan(upper)
        assert_array_almost_equal(upper[valid], lower[valid])


# ---------------------------------------------------------------------------
# NATR
# ---------------------------------------------------------------------------

class TestNATR:
    def test_natr_shape(self):
        from packages.indicators.src.volatility import natr
        h, lo, c, _, _ = _ohlcv(60)
        result = natr(h, lo, c, period=14)
        assert result.shape == (60,)

    def test_natr_warmup_nans(self):
        from packages.indicators.src.volatility import natr
        h, lo, c, _, _ = _ohlcv(60)
        result = natr(h, lo, c, period=14)
        assert np.all(np.isnan(result[:13]))
        assert not np.isnan(result[13])

    def test_natr_non_negative(self):
        from packages.indicators.src.volatility import natr
        h, lo, c, _, _ = _ohlcv(60)
        result = natr(h, lo, c, period=14)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= 0.0)

    def test_natr_proportional_to_atr(self):
        """NATR should equal ATR / close * 100 at every bar."""
        from packages.indicators.src.volatility import atr, natr
        h, lo, c, _, _ = _ohlcv(60)
        atr_vals = atr(h, lo, c, period=14)
        natr_vals = natr(h, lo, c, period=14)
        valid = ~np.isnan(atr_vals) & ~np.isnan(natr_vals) & (c != 0)
        expected = (atr_vals[valid] / c[valid]) * 100.0
        assert_array_almost_equal(natr_vals[valid], expected)


# ---------------------------------------------------------------------------
# Historical Volatility
# ---------------------------------------------------------------------------

class TestHistoricalVolatility:
    def test_hv_shape(self):
        from packages.indicators.src.volatility import historical_volatility
        close = _arange(60, start=100.0, step=0.1)
        result = historical_volatility(close, period=10)
        assert result.shape == (60,)

    def test_hv_warmup_nans(self):
        from packages.indicators.src.volatility import historical_volatility
        close = _arange(60, start=100.0, step=0.1)
        result = historical_volatility(close, period=10)
        assert np.all(np.isnan(result[:10]))
        assert not np.isnan(result[10])

    def test_hv_non_negative(self):
        from packages.indicators.src.volatility import historical_volatility
        close = _arange(60, start=100.0, step=0.1)
        result = historical_volatility(close, period=10)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= 0.0)

    def test_hv_zero_on_constant_series(self):
        """Constant prices have zero log returns — HV should be 0."""
        from packages.indicators.src.volatility import historical_volatility
        close = _flat(30, 100.0)
        result = historical_volatility(close, period=5)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.zeros(len(valid)))

    def test_hv_negative_close_raises(self):
        from packages.indicators.src.volatility import historical_volatility
        close = np.array([-1.0] + [100.0] * 20, dtype=np.float64)
        with pytest.raises(ValueError, match="strictly positive"):
            historical_volatility(close, period=5)

    def test_hv_higher_volatility_on_noisy_series(self):
        """Noisier series should produce higher HV than smooth series."""
        from packages.indicators.src.volatility import historical_volatility
        rng = np.random.default_rng(11)
        smooth = (100.0 + np.cumsum(rng.normal(0, 0.1, 100))).astype(np.float64)
        smooth = np.where(smooth <= 0, 1.0, smooth)
        noisy = (100.0 + np.cumsum(rng.normal(0, 2.0, 100))).astype(np.float64)
        noisy = np.where(noisy <= 0, 1.0, noisy)

        hv_smooth = historical_volatility(smooth, period=10)
        hv_noisy = historical_volatility(noisy, period=10)

        valid_s = hv_smooth[~np.isnan(hv_smooth)]
        valid_n = hv_noisy[~np.isnan(hv_noisy)]
        assert np.mean(valid_n) > np.mean(valid_s)


# ---------------------------------------------------------------------------
# OBV
# ---------------------------------------------------------------------------

class TestOBV:
    def test_obv_shape(self):
        from packages.indicators.src.volume import obv
        h, lo, c, _, v = _ohlcv(40)
        result = obv(c, v)
        assert result.shape == (40,)

    def test_obv_starts_at_zero(self):
        from packages.indicators.src.volume import obv
        _, _, c, _, v = _ohlcv(40)
        result = obv(c, v)
        assert result[0] == pytest.approx(0.0)

    def test_obv_monotone_rising_close_adds_volume(self):
        """All up-bars: OBV should equal cumulative volume."""
        from packages.indicators.src.volume import obv
        n = 10
        close = _arange(n, start=100.0, step=1.0)
        volume = _flat(n, 1000.0)
        result = obv(close, volume)
        # Bar 0 = 0; bar 1 through n-1 each adds 1000
        for i in range(1, n):
            assert result[i] == pytest.approx(i * 1000.0)

    def test_obv_monotone_falling_close_subtracts_volume(self):
        """All down-bars: OBV should equal negative cumulative volume."""
        from packages.indicators.src.volume import obv
        n = 10
        close = _arange(n, start=100.0, step=-1.0)
        volume = _flat(n, 1000.0)
        result = obv(close, volume)
        for i in range(1, n):
            assert result[i] == pytest.approx(-i * 1000.0)

    def test_obv_length_mismatch_raises(self):
        from packages.indicators.src.volume import obv
        with pytest.raises(ValueError):
            obv(
                np.array([1.0, 2.0], dtype=np.float64),
                np.array([1.0], dtype=np.float64),
            )


# ---------------------------------------------------------------------------
# AD (Accumulation / Distribution)
# ---------------------------------------------------------------------------

class TestAD:
    def test_ad_shape(self):
        from packages.indicators.src.volume import ad
        h, lo, c, _, v = _ohlcv(40)
        result = ad(h, lo, c, v)
        assert result.shape == (40,)

    def test_ad_starts_at_zero(self):
        from packages.indicators.src.volume import ad
        h, lo, c, _, v = _ohlcv(40)
        result = ad(h, lo, c, v)
        assert result[0] == pytest.approx(0.0)

    def test_ad_close_at_high_adds_full_volume(self):
        """When close == high, CLV = 1, so MFV = volume added each bar."""
        from packages.indicators.src.volume import ad
        n = 5
        high = _flat(n, 102.0)
        low = _flat(n, 98.0)
        close = _flat(n, 102.0)  # close == high → CLV = 1
        volume = _flat(n, 1000.0)
        result = ad(high, low, close, volume)
        for i in range(1, n):
            assert result[i] == pytest.approx(i * 1000.0)

    def test_ad_close_at_low_subtracts_full_volume(self):
        """When close == low, CLV = -1, so MFV = -volume each bar."""
        from packages.indicators.src.volume import ad
        n = 5
        high = _flat(n, 102.0)
        low = _flat(n, 98.0)
        close = _flat(n, 98.0)  # close == low → CLV = -1
        volume = _flat(n, 1000.0)
        result = ad(high, low, close, volume)
        for i in range(1, n):
            assert result[i] == pytest.approx(-i * 1000.0)


# ---------------------------------------------------------------------------
# CMF
# ---------------------------------------------------------------------------

class TestCMF:
    def test_cmf_shape(self):
        from packages.indicators.src.volume import cmf
        h, lo, c, _, v = _ohlcv(60)
        result = cmf(h, lo, c, v, period=20)
        assert result.shape == (60,)

    def test_cmf_warmup_nans(self):
        from packages.indicators.src.volume import cmf
        h, lo, c, _, v = _ohlcv(60)
        result = cmf(h, lo, c, v, period=20)
        assert np.all(np.isnan(result[:19]))
        assert not np.isnan(result[19])

    def test_cmf_range_minus1_to_1(self):
        from packages.indicators.src.volume import cmf
        h, lo, c, _, v = _ohlcv(60)
        result = cmf(h, lo, c, v, period=20)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= -1.0 - 1e-9) and np.all(valid <= 1.0 + 1e-9)

    def test_cmf_full_accumulation(self):
        """Close == high on every bar → CMF should be 1.0."""
        from packages.indicators.src.volume import cmf
        n = 30
        high = _flat(n, 102.0)
        low = _flat(n, 98.0)
        close = _flat(n, 102.0)
        volume = _flat(n, 1000.0)
        result = cmf(high, low, close, volume, period=10)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.ones(len(valid)))


# ---------------------------------------------------------------------------
# MFI
# ---------------------------------------------------------------------------

class TestMFI:
    def test_mfi_shape(self):
        from packages.indicators.src.volume import mfi
        h, lo, c, _, v = _ohlcv(60)
        result = mfi(h, lo, c, v, period=14)
        assert result.shape == (60,)

    def test_mfi_warmup_nans(self):
        from packages.indicators.src.volume import mfi
        h, lo, c, _, v = _ohlcv(60)
        result = mfi(h, lo, c, v, period=14)
        assert np.all(np.isnan(result[:14]))
        assert not np.isnan(result[14])

    def test_mfi_range_0_to_100(self):
        from packages.indicators.src.volume import mfi
        h, lo, c, _, v = _ohlcv(80)
        result = mfi(h, lo, c, v, period=14)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= 0.0) and np.all(valid <= 100.0)

    def test_mfi_rising_close_high_value(self):
        """Steadily rising typical prices → all money flow is positive → MFI high."""
        from packages.indicators.src.volume import mfi
        n = 40
        close = _arange(n, start=100.0, step=1.0)
        high = close + 1.0
        low = close - 1.0
        volume = _flat(n, 1000.0)
        result = mfi(
            high.astype(np.float64),
            low.astype(np.float64),
            close,
            volume,
            period=5,
        )
        valid = result[~np.isnan(result)]
        assert np.all(valid == pytest.approx(100.0))


# ---------------------------------------------------------------------------
# VWMA
# ---------------------------------------------------------------------------

class TestVWMA:
    def test_vwma_shape(self):
        from packages.indicators.src.volume import vwma
        _, _, c, _, v = _ohlcv(50)
        result = vwma(c, v, period=10)
        assert result.shape == (50,)

    def test_vwma_warmup_nans(self):
        from packages.indicators.src.volume import vwma
        _, _, c, _, v = _ohlcv(50)
        result = vwma(c, v, period=10)
        assert np.all(np.isnan(result[:9]))
        assert not np.isnan(result[9])

    def test_vwma_equal_volumes_equals_sma(self):
        """When all volumes are equal, VWMA should equal SMA."""
        from packages.indicators.src.trend import sma
        from packages.indicators.src.volume import vwma
        close = _arange(30, start=100.0)
        volume = _flat(30, 1000.0)
        result = vwma(close, volume, period=5)
        expected = sma(close, period=5)
        valid = ~np.isnan(result) & ~np.isnan(expected)
        assert_array_almost_equal(result[valid], expected[valid])

    def test_vwma_constant_close_and_volume_equals_close(self):
        from packages.indicators.src.volume import vwma
        close = _flat(30, 55.0)
        volume = _flat(30, 500.0)
        result = vwma(close, volume, period=5)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.full(len(valid), 55.0))

    def test_vwma_zero_volume_returns_nan(self):
        from packages.indicators.src.volume import vwma
        close = _arange(20)
        volume = np.zeros(20, dtype=np.float64)
        result = vwma(close, volume, period=5)
        valid_mask = ~np.isnan(result)
        # All bars with zero volume window should be NaN
        assert not np.any(valid_mask)

    def test_vwma_length_mismatch_raises(self):
        from packages.indicators.src.volume import vwma
        with pytest.raises(ValueError):
            vwma(
                np.array([1.0, 2.0, 3.0], dtype=np.float64),
                np.array([1.0, 2.0], dtype=np.float64),
                period=2,
            )
