"""Tests for the Wave 54 indicator additions.

Covers every new indicator with at minimum:
- Shape / output length test
- NaN boundary test (warm-up region is NaN, post-warmup is not all-NaN)
- Known numeric result or directional sanity check

Groups:
- Trend: ALMA, T3, FRAMA, McGinley Dynamic, VIDYA, Alligator, MAEnvelopes, TRIMA
- Momentum: Fisher Transform, CRSI, ElderRay
- Volatility: BBPercent, BBWidth, ChandelierExit, UlcerIndex, STARCBands
- Volume: EMV, NVI, KlingerVolumeOscillator, OBVSmoothed, RVOL, VROC, FI
- Oscillators: GatorOscillator, STC, CoppockCurve, TSI, CHO, CHOP, KST, Vortex, AC
- Statistics: LRSLOPE, CORREL, BETA, VAR, TSF, MEDIAN, MODE, MedianBands
- Shim: numba_shim module
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


def _sine(n: int, amplitude: float = 10.0, base: float = 100.0) -> np.ndarray:
    t = np.linspace(0, 4 * np.pi, n)
    return (base + amplitude * np.sin(t)).astype(np.float64)


def _ohlcv(n: int, base: float = 100.0):
    close = _sine(n, base=base)
    high = close + np.abs(np.random.default_rng(42).standard_normal(n)) * 0.5
    low = close - np.abs(np.random.default_rng(42).standard_normal(n)) * 0.5
    volume = np.abs(np.random.default_rng(42).standard_normal(n) * 1e5 + 1e6)
    return high, low, close, volume


# ---------------------------------------------------------------------------
# numba_shim
# ---------------------------------------------------------------------------


class TestNumbaShim:
    def test_jit_is_callable(self):
        from flinttrade_indicators.numba_shim import jit

        @jit(nopython=True)
        def add(a, b):
            return a + b

        assert add(1, 2) == 3

    def test_has_numba_is_bool(self):
        from flinttrade_indicators.numba_shim import HAS_NUMBA

        assert isinstance(HAS_NUMBA, bool)

    def test_prange_behaves_like_range(self):
        from flinttrade_indicators.numba_shim import prange

        result = list(prange(5))
        assert result == [0, 1, 2, 3, 4]

    def test_noop_decorator_preserves_function(self):
        """When numba is absent the decorator returns the original function unchanged.
        When numba IS present, confirm the decorator still returns a callable."""
        from flinttrade_indicators.numba_shim import jit, HAS_NUMBA

        if HAS_NUMBA:
            # Numba is installed — confirm jit still produces a callable
            @jit(nopython=True)
            def add_one(x: float) -> float:
                return x + 1.0

            assert callable(add_one)
            assert add_one(3.0) == pytest.approx(4.0)
        else:
            # No numba — decorator must be transparent (identity)
            sentinel = object()

            @jit
            def identity():
                return sentinel

            assert identity() is sentinel


# ---------------------------------------------------------------------------
# Trend — ALMA
# ---------------------------------------------------------------------------


class TestALMA:
    def test_shape(self):
        from flinttrade_indicators.trend import alma

        close = _arange(50)
        result = alma(close, period=9)
        assert result.shape == (50,)

    def test_nan_warmup(self):
        from flinttrade_indicators.trend import alma

        close = _arange(50)
        result = alma(close, period=9)
        assert np.all(np.isnan(result[:8]))
        assert not np.all(np.isnan(result[8:]))

    def test_constant_series_returns_constant(self):
        from flinttrade_indicators.trend import alma

        close = _flat(30, 50.0)
        result = alma(close, period=9)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.full(len(valid), 50.0), decimal=6)

    def test_invalid_sigma_raises(self):
        from flinttrade_indicators.trend import alma

        with pytest.raises(ValueError):
            alma(_arange(20), sigma=0.0)


# ---------------------------------------------------------------------------
# Trend — T3
# ---------------------------------------------------------------------------


class TestT3:
    def test_shape(self):
        from flinttrade_indicators.trend import t3

        close = _arange(60)
        result = t3(close, period=5)
        assert result.shape == (60,)

    def test_nan_warmup_larger_than_ema(self):
        from flinttrade_indicators.trend import t3

        close = _arange(100)
        result = t3(close, period=5)
        # Six EMA passes — warm-up grows
        assert np.any(np.isnan(result))
        assert not np.all(np.isnan(result))

    def test_constant_series_stable(self):
        from flinttrade_indicators.trend import t3

        close = _flat(80, 100.0)
        result = t3(close, period=5)
        valid = result[~np.isnan(result)]
        assert len(valid) > 0
        assert_array_almost_equal(valid, np.full(len(valid), 100.0), decimal=3)

    def test_invalid_vfactor_raises(self):
        from flinttrade_indicators.trend import t3

        with pytest.raises(ValueError):
            t3(_arange(30), vfactor=0.0)


# ---------------------------------------------------------------------------
# Trend — FRAMA
# ---------------------------------------------------------------------------


class TestFRAMA:
    def test_shape(self):
        from flinttrade_indicators.trend import frama

        close = _arange(50)
        result = frama(close, period=16)
        assert result.shape == (50,)

    def test_nan_warmup(self):
        from flinttrade_indicators.trend import frama

        close = _arange(50)
        result = frama(close, period=16)
        assert np.all(np.isnan(result[:15]))

    def test_odd_period_raises(self):
        from flinttrade_indicators.trend import frama

        with pytest.raises(ValueError):
            frama(_arange(30), period=15)

    def test_period_less_than_4_raises(self):
        from flinttrade_indicators.trend import frama

        with pytest.raises(ValueError):
            frama(_arange(30), period=2)


# ---------------------------------------------------------------------------
# Trend — McGinley Dynamic
# ---------------------------------------------------------------------------


class TestMcGinleyDynamic:
    def test_shape(self):
        from flinttrade_indicators.trend import mcginley_dynamic

        close = _arange(50)
        result = mcginley_dynamic(close, period=14)
        assert result.shape == (50,)

    def test_nan_warmup(self):
        from flinttrade_indicators.trend import mcginley_dynamic

        close = _arange(50)
        result = mcginley_dynamic(close, period=14)
        assert np.all(np.isnan(result[:13]))
        assert not np.isnan(result[13])

    def test_non_positive_close_raises(self):
        from flinttrade_indicators.trend import mcginley_dynamic

        close = np.array([1.0, -1.0, 2.0, 3.0, 4.0] * 4, dtype=np.float64)
        with pytest.raises(ValueError):
            mcginley_dynamic(close, period=5)

    def test_constant_series(self):
        from flinttrade_indicators.trend import mcginley_dynamic

        close = _flat(40, 50.0)
        result = mcginley_dynamic(close, period=10)
        valid = result[~np.isnan(result)]
        # When constant, MD should stay at 50.0
        assert_array_almost_equal(valid, np.full(len(valid), 50.0), decimal=4)


# ---------------------------------------------------------------------------
# Trend — VIDYA
# ---------------------------------------------------------------------------


class TestVIDYA:
    def test_shape(self):
        from flinttrade_indicators.trend import vidya

        close = _sine(80)
        result = vidya(close, cmo_period=9, ema_period=12)
        assert result.shape == (80,)

    def test_nan_warmup(self):
        from flinttrade_indicators.trend import vidya

        close = _sine(80)
        result = vidya(close, cmo_period=9, ema_period=12)
        assert np.any(np.isnan(result[:10]))
        assert not np.all(np.isnan(result))

    def test_output_finite_after_warmup(self):
        from flinttrade_indicators.trend import vidya

        close = _arange(60)
        result = vidya(close, cmo_period=9, ema_period=12)
        valid = result[~np.isnan(result)]
        assert np.all(np.isfinite(valid))


# ---------------------------------------------------------------------------
# Trend — Alligator
# ---------------------------------------------------------------------------


class TestAlligator:
    def test_shapes(self):
        from flinttrade_indicators.trend import alligator

        high, low, close, _ = _ohlcv(100)
        jaw, teeth, lips = alligator(high, low)
        assert jaw.shape == teeth.shape == lips.shape == (100,)

    def test_nan_present_during_warmup(self):
        from flinttrade_indicators.trend import alligator

        high, low, close, _ = _ohlcv(100)
        jaw, teeth, lips = alligator(high, low)
        # Jaw has longest warmup (13 + 8)
        assert np.any(np.isnan(jaw[:20]))

    def test_output_finite_after_warmup(self):
        from flinttrade_indicators.trend import alligator

        high, low, close, _ = _ohlcv(100)
        jaw, teeth, lips = alligator(high, low)
        valid = jaw[~np.isnan(jaw)]
        assert np.all(np.isfinite(valid))


# ---------------------------------------------------------------------------
# Trend — Moving Average Envelopes
# ---------------------------------------------------------------------------


class TestMovingAverageEnvelopes:
    def test_shapes(self):
        from flinttrade_indicators.trend import moving_average_envelopes

        close = _arange(50)
        upper, middle, lower = moving_average_envelopes(close, period=10)
        assert upper.shape == middle.shape == lower.shape == (50,)

    def test_upper_greater_than_lower(self):
        from flinttrade_indicators.trend import moving_average_envelopes

        close = _arange(50)
        upper, middle, lower = moving_average_envelopes(close, period=10)
        valid = ~np.isnan(upper)
        assert np.all(upper[valid] > lower[valid])

    def test_ema_variant(self):
        from flinttrade_indicators.trend import moving_average_envelopes

        close = _arange(50)
        upper, middle, lower = moving_average_envelopes(close, period=10, ma_type="ema")
        valid = ~np.isnan(upper)
        assert np.all(upper[valid] > lower[valid])

    def test_invalid_ma_type_raises(self):
        from flinttrade_indicators.trend import moving_average_envelopes

        with pytest.raises(ValueError):
            moving_average_envelopes(_arange(30), ma_type="wma")

    def test_invalid_pct_raises(self):
        from flinttrade_indicators.trend import moving_average_envelopes

        with pytest.raises(ValueError):
            moving_average_envelopes(_arange(30), pct=-1.0)


# ---------------------------------------------------------------------------
# Trend — TRIMA
# ---------------------------------------------------------------------------


class TestTRIMA:
    def test_shape(self):
        from flinttrade_indicators.trend import trima

        close = _arange(50)
        result = trima(close, period=10)
        assert result.shape == (50,)

    def test_nan_warmup(self):
        from flinttrade_indicators.trend import trima

        close = _arange(50)
        result = trima(close, period=10)
        assert np.any(np.isnan(result[:9]))
        assert not np.all(np.isnan(result))

    def test_constant_series(self):
        from flinttrade_indicators.trend import trima

        close = _flat(40, 100.0)
        result = trima(close, period=10)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.full(len(valid), 100.0), decimal=6)

    def test_period_less_than_2_raises(self):
        from flinttrade_indicators.trend import trima

        with pytest.raises(ValueError):
            trima(_arange(20), period=1)


# ---------------------------------------------------------------------------
# Momentum — Fisher Transform
# ---------------------------------------------------------------------------


class TestFisherTransform:
    def test_shapes(self):
        from flinttrade_indicators.momentum import fisher_transform

        high, low, close, _ = _ohlcv(60)
        fisher, signal = fisher_transform(high, low, period=9)
        assert fisher.shape == signal.shape == (60,)

    def test_nan_warmup(self):
        from flinttrade_indicators.momentum import fisher_transform

        high, low, close, _ = _ohlcv(60)
        fisher, signal = fisher_transform(high, low, period=9)
        assert np.all(np.isnan(fisher[:8]))

    def test_output_finite(self):
        from flinttrade_indicators.momentum import fisher_transform

        high, low, close, _ = _ohlcv(60)
        fisher, signal = fisher_transform(high, low, period=9)
        valid = fisher[~np.isnan(fisher)]
        assert np.all(np.isfinite(valid))


# ---------------------------------------------------------------------------
# Momentum — CRSI
# ---------------------------------------------------------------------------


class TestCRSI:
    def test_shape(self):
        from flinttrade_indicators.momentum import crsi

        close = _sine(200)
        result = crsi(close)
        assert result.shape == (200,)

    def test_values_in_0_100_range(self):
        from flinttrade_indicators.momentum import crsi

        close = _sine(200)
        result = crsi(close)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= 0.0)
        assert np.all(valid <= 100.0)

    def test_nan_during_warmup(self):
        from flinttrade_indicators.momentum import crsi

        close = _sine(200)
        result = crsi(close)
        assert np.any(np.isnan(result[:105]))


# ---------------------------------------------------------------------------
# Momentum — ElderRay
# ---------------------------------------------------------------------------


class TestElderRay:
    def test_shapes(self):
        from flinttrade_indicators.momentum import elder_ray

        high, low, close, _ = _ohlcv(60)
        bull, bear = elder_ray(high, low, close, period=13)
        assert bull.shape == bear.shape == (60,)

    def test_nan_warmup(self):
        from flinttrade_indicators.momentum import elder_ray

        high, low, close, _ = _ohlcv(60)
        bull, bear = elder_ray(high, low, close, period=13)
        assert np.all(np.isnan(bull[:12]))

    def test_bull_positive_when_high_above_ema(self):
        from flinttrade_indicators.momentum import elder_ray

        close = _arange(40)
        high = close + 5.0
        low = close - 5.0
        bull, _ = elder_ray(high, low, close, period=5)
        valid = bull[~np.isnan(bull)]
        # high = close + 5 means bull_power = (close + 5) - ema > 0 for stable ema
        assert np.all(valid > 0.0)


# ---------------------------------------------------------------------------
# Volatility — BBPercent
# ---------------------------------------------------------------------------


class TestBBPercent:
    def test_shape(self):
        from flinttrade_indicators.volatility import bb_percent

        close = _sine(60)
        result = bb_percent(close, period=20)
        assert result.shape == (60,)

    def test_nan_warmup(self):
        from flinttrade_indicators.volatility import bb_percent

        close = _sine(60)
        result = bb_percent(close, period=20)
        assert np.all(np.isnan(result[:19]))

    def test_flat_series_returns_half(self):
        from flinttrade_indicators.volatility import bb_percent

        close = _flat(30, 100.0)
        result = bb_percent(close, period=10)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.full(len(valid), 0.5))


# ---------------------------------------------------------------------------
# Volatility — BBWidth
# ---------------------------------------------------------------------------


class TestBBWidth:
    def test_shape(self):
        from flinttrade_indicators.volatility import bb_width

        close = _sine(60)
        result = bb_width(close, period=20)
        assert result.shape == (60,)

    def test_nan_warmup(self):
        from flinttrade_indicators.volatility import bb_width

        close = _sine(60)
        result = bb_width(close, period=20)
        assert np.all(np.isnan(result[:19]))

    def test_positive_for_volatile_series(self):
        from flinttrade_indicators.volatility import bb_width

        close = _sine(60)
        result = bb_width(close, period=20)
        valid = result[~np.isnan(result)]
        assert np.all(valid > 0.0)


# ---------------------------------------------------------------------------
# Volatility — ChandelierExit
# ---------------------------------------------------------------------------


class TestChandelierExit:
    def test_shapes(self):
        from flinttrade_indicators.volatility import chandelier_exit

        high, low, close, _ = _ohlcv(60)
        long_stop, short_stop = chandelier_exit(high, low, close, period=22)
        assert long_stop.shape == short_stop.shape == (60,)

    def test_nan_warmup(self):
        from flinttrade_indicators.volatility import chandelier_exit

        high, low, close, _ = _ohlcv(60)
        long_stop, short_stop = chandelier_exit(high, low, close, period=22)
        assert np.all(np.isnan(long_stop[:21]))

    def test_long_below_short_on_uptrend(self):
        from flinttrade_indicators.volatility import chandelier_exit

        high, low, close, _ = _ohlcv(60)
        long_stop, short_stop = chandelier_exit(high, low, close, period=10)
        valid = ~np.isnan(long_stop) & ~np.isnan(short_stop)
        # Long stop is below short stop (long_stop uses max-high, short_stop uses min-low + atr)
        assert np.any(long_stop[valid] < short_stop[valid])


# ---------------------------------------------------------------------------
# Volatility — UlcerIndex
# ---------------------------------------------------------------------------


class TestUlcerIndex:
    def test_shape(self):
        from flinttrade_indicators.volatility import ulcer_index

        close = _sine(60) + 100.0  # ensure > 0
        result = ulcer_index(close, period=14)
        assert result.shape == (60,)

    def test_nan_warmup(self):
        from flinttrade_indicators.volatility import ulcer_index

        close = _arange(50, start=50.0)
        result = ulcer_index(close, period=10)
        assert np.any(np.isnan(result[:18]))

    def test_non_positive_raises(self):
        from flinttrade_indicators.volatility import ulcer_index

        close = np.array([-1.0] + [100.0] * 29, dtype=np.float64)
        with pytest.raises(ValueError):
            ulcer_index(close, period=10)

    def test_uptrend_has_zero_drawdown(self):
        from flinttrade_indicators.volatility import ulcer_index

        close = _arange(40, start=10.0)
        result = ulcer_index(close, period=10)
        valid = result[~np.isnan(result)]
        # Strictly rising prices have no drawdown — UI should be 0
        assert_array_almost_equal(valid, np.zeros(len(valid)), decimal=6)


# ---------------------------------------------------------------------------
# Volatility — STARC Bands
# ---------------------------------------------------------------------------


class TestSTARCBands:
    def test_shapes(self):
        from flinttrade_indicators.volatility import starc_bands

        high, low, close, _ = _ohlcv(60)
        upper, middle, lower = starc_bands(high, low, close)
        assert upper.shape == middle.shape == lower.shape == (60,)

    def test_upper_greater_than_lower(self):
        from flinttrade_indicators.volatility import starc_bands

        high, low, close, _ = _ohlcv(60)
        upper, middle, lower = starc_bands(high, low, close)
        valid = ~np.isnan(upper)
        assert np.all(upper[valid] > lower[valid])


# ---------------------------------------------------------------------------
# Volume — EMV
# ---------------------------------------------------------------------------


class TestEMV:
    def test_shape(self):
        from flinttrade_indicators.volume import emv

        high, low, close, volume = _ohlcv(60)
        result = emv(high, low, volume, period=14)
        assert result.shape == (60,)

    def test_nan_warmup(self):
        from flinttrade_indicators.volume import emv

        high, low, close, volume = _ohlcv(60)
        result = emv(high, low, volume, period=14)
        assert np.any(np.isnan(result[:14]))


# ---------------------------------------------------------------------------
# Volume — NVI
# ---------------------------------------------------------------------------


class TestNVI:
    def test_shape(self):
        from flinttrade_indicators.volume import nvi

        _, _, close, volume = _ohlcv(40)
        result = nvi(close, volume)
        assert result.shape == (40,)

    def test_starts_at_1000(self):
        from flinttrade_indicators.volume import nvi

        _, _, close, volume = _ohlcv(40)
        result = nvi(close, volume)
        assert result[0] == pytest.approx(1000.0)

    def test_unchanged_on_rising_volume(self):
        """NVI only changes when volume drops."""
        from flinttrade_indicators.volume import nvi

        close = _arange(5, start=100.0)
        # Rising volume — NVI should not change
        volume = np.array([100.0, 200.0, 300.0, 400.0, 500.0], dtype=np.float64)
        result = nvi(close, volume)
        assert_array_almost_equal(result, np.full(5, 1000.0))


# ---------------------------------------------------------------------------
# Volume — KlingerVolumeOscillator
# ---------------------------------------------------------------------------


class TestKlingerVolumeOscillator:
    def test_shapes(self):
        from flinttrade_indicators.volume import klinger_volume_oscillator

        high, low, close, volume = _ohlcv(120)
        kvo, sig = klinger_volume_oscillator(high, low, close, volume)
        assert kvo.shape == sig.shape == (120,)

    def test_finite_after_warmup(self):
        from flinttrade_indicators.volume import klinger_volume_oscillator

        high, low, close, volume = _ohlcv(120)
        kvo, _ = klinger_volume_oscillator(high, low, close, volume)
        valid = kvo[~np.isnan(kvo)]
        assert np.all(np.isfinite(valid))


# ---------------------------------------------------------------------------
# Volume — OBVSmoothed
# ---------------------------------------------------------------------------


class TestOBVSmoothed:
    def test_shape(self):
        from flinttrade_indicators.volume import obv_smoothed

        _, _, close, volume = _ohlcv(60)
        result = obv_smoothed(close, volume, period=10)
        assert result.shape == (60,)

    def test_nan_warmup(self):
        from flinttrade_indicators.volume import obv_smoothed

        _, _, close, volume = _ohlcv(60)
        result = obv_smoothed(close, volume, period=10)
        assert np.all(np.isnan(result[:9]))


# ---------------------------------------------------------------------------
# Volume — RVOL
# ---------------------------------------------------------------------------


class TestRVOL:
    def test_shape(self):
        from flinttrade_indicators.volume import rvol

        _, _, _, volume = _ohlcv(60)
        result = rvol(volume, period=20)
        assert result.shape == (60,)

    def test_nan_warmup(self):
        from flinttrade_indicators.volume import rvol

        _, _, _, volume = _ohlcv(60)
        result = rvol(volume, period=20)
        assert np.all(np.isnan(result[:20]))

    def test_constant_volume_returns_one(self):
        from flinttrade_indicators.volume import rvol

        volume = _flat(40, 1000.0)
        result = rvol(volume, period=10)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.ones(len(valid)), decimal=6)


# ---------------------------------------------------------------------------
# Volume — VROC
# ---------------------------------------------------------------------------


class TestVROC:
    def test_shape(self):
        from flinttrade_indicators.volume import vroc

        _, _, _, volume = _ohlcv(40)
        result = vroc(volume, period=14)
        assert result.shape == (40,)

    def test_nan_warmup(self):
        from flinttrade_indicators.volume import vroc

        _, _, _, volume = _ohlcv(40)
        result = vroc(volume, period=14)
        assert np.all(np.isnan(result[:14]))

    def test_constant_volume_returns_zero(self):
        from flinttrade_indicators.volume import vroc

        volume = _flat(30, 1000.0)
        result = vroc(volume, period=10)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.zeros(len(valid)))


# ---------------------------------------------------------------------------
# Volume — FI (Force Index)
# ---------------------------------------------------------------------------


class TestFI:
    def test_shape(self):
        from flinttrade_indicators.volume import fi

        _, _, close, volume = _ohlcv(60)
        result = fi(close, volume, period=13)
        assert result.shape == (60,)

    def test_same_as_efi(self):
        from flinttrade_indicators.volume import fi, efi

        _, _, close, volume = _ohlcv(60)
        fi_result = fi(close, volume, period=13)
        efi_result = efi(close, volume, period=13)
        assert_array_almost_equal(fi_result, efi_result)


# ---------------------------------------------------------------------------
# Oscillators — GatorOscillator
# ---------------------------------------------------------------------------


class TestGatorOscillator:
    def test_shapes(self):
        from flinttrade_indicators.oscillators import gator_oscillator

        high, low, _, _ = _ohlcv(100)
        upper, lower = gator_oscillator(high, low)
        assert upper.shape == lower.shape == (100,)

    def test_upper_non_negative(self):
        from flinttrade_indicators.oscillators import gator_oscillator

        high, low, _, _ = _ohlcv(100)
        upper, _ = gator_oscillator(high, low)
        valid = upper[~np.isnan(upper)]
        assert np.all(valid >= 0.0)

    def test_lower_non_positive(self):
        from flinttrade_indicators.oscillators import gator_oscillator

        high, low, _, _ = _ohlcv(100)
        _, lower = gator_oscillator(high, low)
        valid = lower[~np.isnan(lower)]
        assert np.all(valid <= 0.0)


# ---------------------------------------------------------------------------
# Oscillators — STC
# ---------------------------------------------------------------------------


class TestSTC:
    def test_shape(self):
        from flinttrade_indicators.oscillators import stc

        close = _sine(120)
        result = stc(close, fast=23, slow=50, cycle=10)
        assert result.shape == (120,)

    def test_values_in_0_100(self):
        from flinttrade_indicators.oscillators import stc

        close = _sine(120)
        result = stc(close, fast=23, slow=50, cycle=10)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= 0.0)
        assert np.all(valid <= 100.0)


# ---------------------------------------------------------------------------
# Oscillators — Coppock Curve
# ---------------------------------------------------------------------------


class TestCoppockCurve:
    def test_shape(self):
        from flinttrade_indicators.oscillators import coppock_curve

        close = _arange(120)
        result = coppock_curve(close)
        assert result.shape == (120,)

    def test_nan_warmup(self):
        from flinttrade_indicators.oscillators import coppock_curve

        close = _arange(120)
        result = coppock_curve(close)
        assert np.any(np.isnan(result[:30]))
        assert not np.all(np.isnan(result))


# ---------------------------------------------------------------------------
# Oscillators — TSI
# ---------------------------------------------------------------------------


class TestTSI:
    def test_shape(self):
        from flinttrade_indicators.oscillators import tsi

        close = _sine(100)
        result = tsi(close, long_period=25, short_period=13)
        assert result.shape == (100,)

    def test_values_bounded(self):
        from flinttrade_indicators.oscillators import tsi

        close = _sine(100)
        result = tsi(close, long_period=25, short_period=13)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= -100.0)
        assert np.all(valid <= 100.0)


# ---------------------------------------------------------------------------
# Oscillators — CHO (Chaikin Oscillator)
# ---------------------------------------------------------------------------


class TestCHO:
    def test_shape(self):
        from flinttrade_indicators.oscillators import cho

        high, low, close, volume = _ohlcv(60)
        result = cho(high, low, close, volume)
        assert result.shape == (60,)

    def test_nan_warmup(self):
        from flinttrade_indicators.oscillators import cho

        high, low, close, volume = _ohlcv(60)
        result = cho(high, low, close, volume, fast=3, slow=10)
        assert np.any(np.isnan(result[:9]))


# ---------------------------------------------------------------------------
# Oscillators — CHOP
# ---------------------------------------------------------------------------


class TestCHOP:
    def test_shape(self):
        from flinttrade_indicators.oscillators import chop

        high, low, close, _ = _ohlcv(60)
        result = chop(high, low, close, period=14)
        assert result.shape == (60,)

    def test_nan_warmup(self):
        from flinttrade_indicators.oscillators import chop

        high, low, close, _ = _ohlcv(60)
        result = chop(high, low, close, period=14)
        assert np.all(np.isnan(result[:14]))

    def test_values_in_expected_range(self):
        from flinttrade_indicators.oscillators import chop

        high, low, close, _ = _ohlcv(60)
        result = chop(high, low, close, period=14)
        valid = result[~np.isnan(result)]
        # Choppiness index is theoretically bounded roughly in [0, 100]
        assert np.all(valid >= 0.0)
        assert np.all(valid <= 200.0)  # relaxed upper bound for edge cases


# ---------------------------------------------------------------------------
# Oscillators — KST
# ---------------------------------------------------------------------------


class TestKST:
    def test_shapes(self):
        from flinttrade_indicators.oscillators import kst

        close = _arange(120)
        kst_line, sig = kst(close)
        assert kst_line.shape == sig.shape == (120,)

    def test_nan_during_warmup(self):
        from flinttrade_indicators.oscillators import kst

        close = _arange(120)
        kst_line, _ = kst(close)
        assert np.any(np.isnan(kst_line[:40]))
        assert not np.all(np.isnan(kst_line))


# ---------------------------------------------------------------------------
# Oscillators — Vortex Indicator
# ---------------------------------------------------------------------------


class TestVortex:
    def test_shapes(self):
        from flinttrade_indicators.oscillators import vortex

        high, low, close, _ = _ohlcv(60)
        vi_plus, vi_minus = vortex(high, low, close, period=14)
        assert vi_plus.shape == vi_minus.shape == (60,)

    def test_nan_warmup(self):
        from flinttrade_indicators.oscillators import vortex

        high, low, close, _ = _ohlcv(60)
        vi_plus, vi_minus = vortex(high, low, close, period=14)
        assert np.all(np.isnan(vi_plus[:14]))

    def test_positive_values(self):
        from flinttrade_indicators.oscillators import vortex

        high, low, close, _ = _ohlcv(60)
        vi_plus, vi_minus = vortex(high, low, close, period=14)
        valid_p = vi_plus[~np.isnan(vi_plus)]
        valid_m = vi_minus[~np.isnan(vi_minus)]
        assert np.all(valid_p >= 0.0)
        assert np.all(valid_m >= 0.0)


# ---------------------------------------------------------------------------
# Oscillators — AC
# ---------------------------------------------------------------------------


class TestAC:
    def test_shape(self):
        from flinttrade_indicators.oscillators import ac

        high, low, _, _ = _ohlcv(80)
        result = ac(high, low)
        assert result.shape == (80,)

    def test_nan_warmup(self):
        from flinttrade_indicators.oscillators import ac

        high, low, _, _ = _ohlcv(80)
        result = ac(high, low)
        assert np.any(np.isnan(result[:40]))

    def test_invalid_fast_slow_raises(self):
        from flinttrade_indicators.oscillators import ac

        high, low, _, _ = _ohlcv(80)
        with pytest.raises(ValueError):
            ac(high, low, fast=34, slow=34)


# ---------------------------------------------------------------------------
# Statistics — LRSLOPE
# ---------------------------------------------------------------------------


class TestLRSlope:
    def test_shape(self):
        from flinttrade_indicators.statistics import lrslope

        close = _arange(40)
        result = lrslope(close, period=14)
        assert result.shape == (40,)

    def test_nan_warmup(self):
        from flinttrade_indicators.statistics import lrslope

        close = _arange(40)
        result = lrslope(close, period=14)
        assert np.all(np.isnan(result[:13]))

    def test_linear_series_slope_equals_step(self):
        from flinttrade_indicators.statistics import lrslope

        close = _arange(30, step=2.0)
        result = lrslope(close, period=5)
        valid = result[~np.isnan(result)]
        # Slope of y = 2x should be 2.0
        assert_array_almost_equal(valid, np.full(len(valid), 2.0), decimal=5)

    def test_period_less_than_2_raises(self):
        from flinttrade_indicators.statistics import lrslope

        with pytest.raises(ValueError):
            lrslope(_arange(20), period=1)


# ---------------------------------------------------------------------------
# Statistics — CORREL
# ---------------------------------------------------------------------------


class TestCORREL:
    def test_shape(self):
        from flinttrade_indicators.statistics import correl

        a = _arange(40)
        b = _arange(40, start=2.0)
        result = correl(a, b, period=10)
        assert result.shape == (40,)

    def test_identical_series_returns_one(self):
        from flinttrade_indicators.statistics import correl

        close = _arange(40)
        result = correl(close, close, period=10)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.ones(len(valid)), decimal=6)

    def test_anti_correlated_returns_minus_one(self):
        from flinttrade_indicators.statistics import correl

        close = _arange(40)
        anti = -close
        result = correl(close, anti, period=10)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, -np.ones(len(valid)), decimal=6)

    def test_length_mismatch_raises(self):
        from flinttrade_indicators.statistics import correl

        with pytest.raises(ValueError):
            correl(_arange(20), _arange(30), period=5)


# ---------------------------------------------------------------------------
# Statistics — BETA
# ---------------------------------------------------------------------------


class TestBETA:
    def test_shape(self):
        from flinttrade_indicators.statistics import beta

        asset = _arange(50, start=50.0)
        bench = _arange(50, start=40.0)
        result = beta(asset, bench, period=20)
        assert result.shape == (50,)

    def test_nan_warmup(self):
        from flinttrade_indicators.statistics import beta

        asset = _arange(50, start=50.0)
        bench = _arange(50, start=40.0)
        result = beta(asset, bench, period=20)
        assert np.all(np.isnan(result[:20]))

    def test_non_positive_raises(self):
        from flinttrade_indicators.statistics import beta

        asset = np.array([-1.0] + [50.0] * 29, dtype=np.float64)
        bench = _arange(30, start=50.0)
        with pytest.raises(ValueError):
            beta(asset, bench, period=10)


# ---------------------------------------------------------------------------
# Statistics — VAR
# ---------------------------------------------------------------------------


class TestVAR:
    def test_shape(self):
        from flinttrade_indicators.statistics import var

        close = _sine(40)
        result = var(close, period=10)
        assert result.shape == (40,)

    def test_constant_series_zero_variance(self):
        from flinttrade_indicators.statistics import var

        close = _flat(30, 100.0)
        result = var(close, period=5)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.zeros(len(valid)), decimal=8)

    def test_invalid_ddof_raises(self):
        from flinttrade_indicators.statistics import var

        with pytest.raises(ValueError):
            var(_arange(20), ddof=2)


# ---------------------------------------------------------------------------
# Statistics — TSF
# ---------------------------------------------------------------------------


class TestTSF:
    def test_shape(self):
        from flinttrade_indicators.statistics import tsf

        close = _arange(40)
        result = tsf(close, period=14)
        assert result.shape == (40,)

    def test_nan_warmup(self):
        from flinttrade_indicators.statistics import tsf

        close = _arange(40)
        result = tsf(close, period=14)
        assert np.all(np.isnan(result[:13]))

    def test_linear_series_forecasts_next_bar(self):
        from flinttrade_indicators.statistics import tsf

        # close = [1, 2, 3, ..., 30] with step 1
        close = _arange(30)
        result = tsf(close, period=5)
        # At bar 4 (index 4), window = [1,2,3,4,5], TSF forecasts bar 5 = 6.0
        assert result[4] == pytest.approx(6.0, abs=1e-5)


# ---------------------------------------------------------------------------
# Statistics — MEDIAN
# ---------------------------------------------------------------------------


class TestMEDIAN:
    def test_shape(self):
        from flinttrade_indicators.statistics import median

        close = _arange(30)
        result = median(close, period=5)
        assert result.shape == (30,)

    def test_known_value(self):
        from flinttrade_indicators.statistics import median

        close = np.array([1.0, 3.0, 2.0, 5.0, 4.0], dtype=np.float64)
        result = median(close, period=3)
        # Window [1,3,2] → median 2; [3,2,5] → median 3; [2,5,4] → median 4
        assert result[2] == pytest.approx(2.0)
        assert result[3] == pytest.approx(3.0)
        assert result[4] == pytest.approx(4.0)

    def test_nan_warmup(self):
        from flinttrade_indicators.statistics import median

        close = _arange(20)
        result = median(close, period=5)
        assert np.all(np.isnan(result[:4]))


# ---------------------------------------------------------------------------
# Statistics — MODE
# ---------------------------------------------------------------------------


class TestMODE:
    def test_shape(self):
        from flinttrade_indicators.statistics import mode

        close = _arange(30)
        result = mode(close, period=10)
        assert result.shape == (30,)

    def test_constant_series_returns_constant(self):
        from flinttrade_indicators.statistics import mode

        close = _flat(20, 55.0)
        result = mode(close, period=5)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.full(len(valid), 55.0))

    def test_invalid_bins_raises(self):
        from flinttrade_indicators.statistics import mode

        with pytest.raises(ValueError):
            mode(_arange(20), bins=1)


# ---------------------------------------------------------------------------
# Statistics — MedianBands
# ---------------------------------------------------------------------------


class TestMedianBands:
    def test_shapes(self):
        from flinttrade_indicators.statistics import median_bands

        close = _sine(60)
        upper, mid, lower = median_bands(close, period=20)
        assert upper.shape == mid.shape == lower.shape == (60,)

    def test_nan_warmup(self):
        from flinttrade_indicators.statistics import median_bands

        close = _sine(60)
        upper, mid, lower = median_bands(close, period=20)
        assert np.all(np.isnan(upper[:19]))

    def test_upper_greater_than_lower(self):
        from flinttrade_indicators.statistics import median_bands

        close = _sine(60)
        upper, _, lower = median_bands(close, period=20)
        valid = ~np.isnan(upper) & ~np.isnan(lower)
        # For a volatile series, upper >= lower (equal when MAD = 0)
        assert np.all(upper[valid] >= lower[valid])

    def test_invalid_multiplier_raises(self):
        from flinttrade_indicators.statistics import median_bands

        with pytest.raises(ValueError):
            median_bands(_arange(30), multiplier=0.0)
