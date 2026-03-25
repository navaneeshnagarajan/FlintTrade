"""Tests for composite indicators: Williams VIX Fix, Squeeze Momentum, DPO,
Elder Force Index, Price Volume Trend, Chaikin Volatility.

30+ tests total — 5+ per indicator — covering:
- Output shape matches input length
- NaN warmup boundaries (first N values NaN, N-th value not NaN)
- Known-value / mathematical properties
- Edge cases (flat series, zero denominator, length mismatches)
- dtype guarantees (float64)
"""

from __future__ import annotations

import numpy as np
import pytest
from numpy.testing import assert_array_almost_equal


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _arange(n: int, start: float = 1.0, step: float = 1.0) -> np.ndarray:
    """Linearly increasing array of float64."""
    return np.arange(start, start + n * step, step, dtype=np.float64)


def _flat(n: int, value: float = 100.0) -> np.ndarray:
    """Constant array of float64."""
    return np.full(n, value, dtype=np.float64)


def _ohlcv(
    n: int = 100,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Realistic OHLCV arrays (high, low, close, volume)."""
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + np.abs(rng.normal(0, 0.3, n))
    low = close - np.abs(rng.normal(0, 0.3, n))
    volume = np.abs(rng.normal(1_000_000, 200_000, n))
    return (
        high.astype(np.float64),
        low.astype(np.float64),
        close.astype(np.float64),
        volume.astype(np.float64),
    )


# ---------------------------------------------------------------------------
# A. Williams VIX Fix
# ---------------------------------------------------------------------------


class TestWilliamsVixFix:
    """Williams VIX Fix — composite volatility proxy."""

    def test_wvf_shape(self) -> None:
        """Output shape must match input length."""
        from packages.indicators.src.volatility import williams_vix_fix

        high, low, close, _ = _ohlcv(100)
        result = williams_vix_fix(close, low, period=22)
        assert result.shape == (100,)

    def test_wvf_warmup_nans(self) -> None:
        """First period-1 values must be NaN; index period-1 must not be NaN."""
        from packages.indicators.src.volatility import williams_vix_fix

        high, low, close, _ = _ohlcv(100)
        period = 22
        result = williams_vix_fix(close, low, period=period)
        assert np.all(np.isnan(result[: period - 1]))
        assert not np.isnan(result[period - 1])

    def test_wvf_range_0_to_100(self) -> None:
        """WVF values (percentage) must be in [0, 100]."""
        from packages.indicators.src.volatility import williams_vix_fix

        high, low, close, _ = _ohlcv(200)
        result = williams_vix_fix(close, low, period=22)
        valid = result[~np.isnan(result)]
        assert len(valid) > 0
        assert float(np.min(valid)) >= 0.0
        assert float(np.max(valid)) <= 100.0

    def test_wvf_when_low_equals_highest_close_result_is_zero(self) -> None:
        """When low == highest_close over window, WVF should be 0."""
        from packages.indicators.src.volatility import williams_vix_fix

        # Flat close = flat highest close; if low == close, numerator = 0
        n = 50
        close = _flat(n, 100.0)
        low = _flat(n, 100.0)
        result = williams_vix_fix(close, low, period=10)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.zeros(len(valid)))

    def test_wvf_large_low_drop_gives_high_value(self) -> None:
        """A dramatic low below the highest close should produce a high WVF reading."""
        from packages.indicators.src.volatility import williams_vix_fix

        n = 50
        close = _flat(n, 100.0)
        low = _flat(n, 100.0)
        # Override last bar: low collapses to 10, highest_close stays 100
        low[-1] = 10.0
        result = williams_vix_fix(close, low, period=10)
        # WVF[-1] = (100 - 10) / 100 * 100 = 90.0
        assert result[-1] == pytest.approx(90.0)

    def test_wvf_length_mismatch_raises(self) -> None:
        """Mismatched close and low lengths must raise ValueError."""
        from packages.indicators.src.volatility import williams_vix_fix

        close = _flat(50)
        low = _flat(40)
        with pytest.raises(ValueError, match="length mismatch"):
            williams_vix_fix(close, low, period=10)

    def test_wvf_returns_float64(self) -> None:
        """Output dtype must be float64."""
        from packages.indicators.src.volatility import williams_vix_fix

        high, low, close, _ = _ohlcv(100)
        result = williams_vix_fix(close, low)
        assert result.dtype == np.float64

    def test_wvf_period_1_warmup(self) -> None:
        """Period=1: every bar has the highest_close == close[i], warmup=0."""
        from packages.indicators.src.volatility import williams_vix_fix

        high, low, close, _ = _ohlcv(30)
        result = williams_vix_fix(close, low, period=1)
        # All values should be valid (no NaN)
        assert not np.any(np.isnan(result))


# ---------------------------------------------------------------------------
# B. Squeeze Momentum
# ---------------------------------------------------------------------------


class TestSqueezeMomentum:
    """Squeeze Momentum Indicator (LazyBear)."""

    def test_squeeze_shape(self) -> None:
        """Both outputs must match input length."""
        from packages.indicators.src.momentum import squeeze_momentum

        high, low, close, _ = _ohlcv(100)
        mom_vals, squeeze_on = squeeze_momentum(high, low, close)
        assert mom_vals.shape == (100,)
        assert squeeze_on.shape == (100,)

    def test_squeeze_on_is_bool_array(self) -> None:
        """squeeze_on must be a boolean array."""
        from packages.indicators.src.momentum import squeeze_momentum

        high, low, close, _ = _ohlcv(100)
        _, squeeze_on = squeeze_momentum(high, low, close)
        assert squeeze_on.dtype == np.bool_

    def test_squeeze_momentum_dtype_float64(self) -> None:
        """Momentum output must be float64."""
        from packages.indicators.src.momentum import squeeze_momentum

        high, low, close, _ = _ohlcv(100)
        mom_vals, _ = squeeze_momentum(high, low, close)
        assert mom_vals.dtype == np.float64

    def test_squeeze_has_nan_warmup(self) -> None:
        """Initial bars must be NaN in the momentum output."""
        from packages.indicators.src.momentum import squeeze_momentum

        high, low, close, _ = _ohlcv(100)
        mom_vals, _ = squeeze_momentum(high, low, close, bb_period=20, kc_period=20, mom_period=12)
        # At minimum the first bb_period-1 bars should be NaN
        assert np.all(np.isnan(mom_vals[:19]))

    def test_squeeze_on_false_when_bb_wider_than_kc(self) -> None:
        """When BB is wider than KC (volatile market), squeeze_on should be False."""
        from packages.indicators.src.momentum import squeeze_momentum

        # Highly volatile data: BB will be wide, KC narrower
        rng = np.random.default_rng(99)
        n = 100
        close = 100.0 + np.cumsum(rng.normal(0, 5.0, n))  # very noisy
        high = close + np.abs(rng.normal(0, 3.0, n))
        low = close - np.abs(rng.normal(0, 3.0, n))
        close = close.astype(np.float64)
        high = high.astype(np.float64)
        low = low.astype(np.float64)
        _, squeeze_on = squeeze_momentum(high, low, close, bb_mult=2.0, kc_mult=1.5)
        # At least some bars should NOT be in squeeze (high volatility)
        valid = squeeze_on[~np.isnan(close)]  # all bars valid
        assert not np.all(valid)

    def test_squeeze_momentum_valid_values_exist(self) -> None:
        """After warmup, momentum array must have non-NaN values."""
        from packages.indicators.src.momentum import squeeze_momentum

        high, low, close, _ = _ohlcv(150)
        mom_vals, _ = squeeze_momentum(high, low, close)
        valid = mom_vals[~np.isnan(mom_vals)]
        assert len(valid) > 0

    def test_squeeze_custom_periods(self) -> None:
        """Custom bb/kc/mom periods must produce correctly shaped output."""
        from packages.indicators.src.momentum import squeeze_momentum

        high, low, close, _ = _ohlcv(200)
        mom_vals, squeeze_on = squeeze_momentum(
            high, low, close, bb_period=14, kc_period=14, mom_period=8
        )
        assert mom_vals.shape == (200,)
        assert squeeze_on.shape == (200,)


# ---------------------------------------------------------------------------
# C. Detrended Price Oscillator (DPO)
# ---------------------------------------------------------------------------


class TestDPO:
    """Detrended Price Oscillator."""

    def test_dpo_shape(self) -> None:
        """Output shape must match input length."""
        from packages.indicators.src.momentum import dpo

        close = _arange(100)
        result = dpo(close, period=20)
        assert result.shape == (100,)

    def test_dpo_warmup_nans(self) -> None:
        """Leading bars must be NaN until the SMA warms up at the shifted index.

        shift = period // 2 + 1.
        SMA is first valid at index period-1 (past_idx).
        So result[i] is first valid when i - shift >= period - 1,
        i.e. i >= period + period // 2.  For period=20 that is bar 30.
        """
        from packages.indicators.src.momentum import dpo

        period = 20
        shift = period // 2 + 1  # 11
        first_valid = period - 1 + shift  # 30
        close = _arange(100)
        result = dpo(close, period=period)
        assert np.all(np.isnan(result[:first_valid]))
        assert not np.isnan(result[first_valid])

    def test_dpo_flat_series_is_zero(self) -> None:
        """On a constant series, DPO = close - SMA = 0."""
        from packages.indicators.src.momentum import dpo

        close = _flat(100, 50.0)
        result = dpo(close, period=10)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.zeros(len(valid)))

    def test_dpo_linear_series_known_value(self) -> None:
        """On a linear arange series, DPO = close[i-shift] - SMA of window around it.

        For y = i (0-indexed): SMA(y, period)[j] = j - (period-1)/2.
        At index j, close[j] = j, so DPO[j] = j - (j - (period-1)/2) = (period-1)/2.
        That is a constant for all valid bars.
        """
        from packages.indicators.src.momentum import dpo

        n = 100
        period = 10
        shift = period // 2 + 1  # 6
        # close[i] = i (0-indexed float)
        close = np.arange(n, dtype=np.float64)
        result = dpo(close, period=period)
        valid = result[~np.isnan(result)]
        # Expected: close[i - shift] - SMA over window ending at (i - shift)
        # For linear series with step=1, SMA(period) at position p = p - (period-1)/2
        # DPO = p - (p - (period-1)/2) = (period-1)/2
        expected_val = (period - 1) / 2.0
        assert_array_almost_equal(valid, np.full(len(valid), expected_val), decimal=6)

    def test_dpo_period_1_raises(self) -> None:
        """Period < 2 must raise ValueError."""
        from packages.indicators.src.momentum import dpo

        with pytest.raises(ValueError, match="period"):
            dpo(_arange(20), period=1)

    def test_dpo_returns_float64(self) -> None:
        """Output dtype must be float64."""
        from packages.indicators.src.momentum import dpo

        assert dpo(_arange(50), period=10).dtype == np.float64

    def test_dpo_oscillates_around_zero(self) -> None:
        """DPO of a random series should oscillate — mean near zero."""
        from packages.indicators.src.momentum import dpo

        rng = np.random.default_rng(7)
        close = (100.0 + np.cumsum(rng.normal(0, 0.5, 300))).astype(np.float64)
        result = dpo(close, period=20)
        valid = result[~np.isnan(result)]
        # Mean of DPO should be close to zero (detrended oscillator property)
        assert abs(float(np.mean(valid))) < 5.0


# ---------------------------------------------------------------------------
# D. Elder Force Index
# ---------------------------------------------------------------------------


class TestEFI:
    """Elder Force Index."""

    def test_efi_shape(self) -> None:
        """Output shape must match input length."""
        from packages.indicators.src.volume import efi

        _, _, close, volume = _ohlcv(100)
        result = efi(close, volume, period=13)
        assert result.shape == (100,)

    def test_efi_warmup_nans(self) -> None:
        """First period bars must be NaN (1 for diff + period-1 for EMA warmup)."""
        from packages.indicators.src.volume import efi

        _, _, close, volume = _ohlcv(100)
        period = 13
        result = efi(close, volume, period=period)
        # The raw diff has NaN at index 0; EMA then needs period bars
        # First valid EMA is at index period within the valid_raw slice,
        # which maps to index period in the result.
        assert np.all(np.isnan(result[:period]))
        assert not np.isnan(result[period])

    def test_efi_positive_on_up_move_with_volume(self) -> None:
        """Rising price with volume should produce positive EFI values."""
        from packages.indicators.src.volume import efi

        n = 50
        close = _arange(n, start=100.0, step=1.0)
        volume = _flat(n, 1_000_000.0)
        result = efi(close, volume, period=5)
        valid = result[~np.isnan(result)]
        assert len(valid) > 0
        assert float(np.mean(valid)) > 0.0

    def test_efi_negative_on_down_move_with_volume(self) -> None:
        """Falling price with volume should produce negative EFI values."""
        from packages.indicators.src.volume import efi

        n = 50
        close = _arange(n, start=100.0, step=-1.0)
        volume = _flat(n, 1_000_000.0)
        result = efi(close, volume, period=5)
        valid = result[~np.isnan(result)]
        assert len(valid) > 0
        assert float(np.mean(valid)) < 0.0

    def test_efi_flat_price_is_zero(self) -> None:
        """Zero price change means zero raw force → EFI converges to 0."""
        from packages.indicators.src.volume import efi

        n = 100
        close = _flat(n, 100.0)
        volume = _flat(n, 1_000_000.0)
        result = efi(close, volume, period=13)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.zeros(len(valid)))

    def test_efi_length_mismatch_raises(self) -> None:
        """Mismatched close and volume lengths must raise ValueError."""
        from packages.indicators.src.volume import efi

        close = _flat(50)
        volume = _flat(40)
        with pytest.raises(ValueError, match="length mismatch"):
            efi(close, volume, period=13)

    def test_efi_returns_float64(self) -> None:
        """Output dtype must be float64."""
        from packages.indicators.src.volume import efi

        _, _, close, volume = _ohlcv(100)
        assert efi(close, volume).dtype == np.float64

    def test_efi_period_0_raises(self) -> None:
        """Period < 1 must raise ValueError."""
        from packages.indicators.src.volume import efi

        _, _, close, volume = _ohlcv(50)
        with pytest.raises(ValueError, match="period"):
            efi(close, volume, period=0)


# ---------------------------------------------------------------------------
# E. Price Volume Trend
# ---------------------------------------------------------------------------


class TestPVT:
    """Price Volume Trend."""

    def test_pvt_shape(self) -> None:
        """Output shape must match input length."""
        from packages.indicators.src.volume import pvt

        _, _, close, volume = _ohlcv(100)
        result = pvt(close, volume)
        assert result.shape == (100,)

    def test_pvt_starts_at_zero(self) -> None:
        """PVT[0] must always be 0 (cumulative seed)."""
        from packages.indicators.src.volume import pvt

        _, _, close, volume = _ohlcv(100)
        result = pvt(close, volume)
        assert result[0] == pytest.approx(0.0)

    def test_pvt_no_nans(self) -> None:
        """PVT has no NaN warmup — every bar must be valid."""
        from packages.indicators.src.volume import pvt

        _, _, close, volume = _ohlcv(100)
        result = pvt(close, volume)
        assert not np.any(np.isnan(result))

    def test_pvt_rising_price_positive_trend(self) -> None:
        """Steadily rising price with constant volume → PVT increases monotonically."""
        from packages.indicators.src.volume import pvt

        n = 50
        close = _arange(n, start=100.0, step=1.0)
        volume = _flat(n, 1_000_000.0)
        result = pvt(close, volume)
        # PVT should be non-decreasing for a pure uptrend
        assert np.all(np.diff(result) >= 0.0)

    def test_pvt_falling_price_negative_trend(self) -> None:
        """Steadily falling price → PVT decreases monotonically."""
        from packages.indicators.src.volume import pvt

        n = 50
        close = _arange(n, start=100.0, step=-1.0)
        volume = _flat(n, 1_000_000.0)
        result = pvt(close, volume)
        assert np.all(np.diff(result) <= 0.0)

    def test_pvt_flat_price_stays_zero(self) -> None:
        """Zero price change → PVT stays at 0 throughout."""
        from packages.indicators.src.volume import pvt

        n = 50
        close = _flat(n, 100.0)
        volume = _flat(n, 1_000_000.0)
        result = pvt(close, volume)
        assert_array_almost_equal(result, np.zeros(n))

    def test_pvt_known_two_bar_value(self) -> None:
        """Manual check: 100 → 110, volume=1000. PVT[1] = 0 + (10/100)*1000 = 100."""
        from packages.indicators.src.volume import pvt

        close = np.array([100.0, 110.0], dtype=np.float64)
        volume = np.array([0.0, 1000.0], dtype=np.float64)
        result = pvt(close, volume)
        assert result[0] == pytest.approx(0.0)
        assert result[1] == pytest.approx(100.0)

    def test_pvt_length_mismatch_raises(self) -> None:
        """Mismatched close and volume lengths must raise ValueError."""
        from packages.indicators.src.volume import pvt

        close = _flat(50)
        volume = _flat(40)
        with pytest.raises(ValueError, match="length mismatch"):
            pvt(close, volume)

    def test_pvt_returns_float64(self) -> None:
        """Output dtype must be float64."""
        from packages.indicators.src.volume import pvt

        _, _, close, volume = _ohlcv(100)
        assert pvt(close, volume).dtype == np.float64


# ---------------------------------------------------------------------------
# F. Chaikin Volatility
# ---------------------------------------------------------------------------


class TestChaikinVolatility:
    """Chaikin Volatility."""

    def test_chaikin_vol_shape(self) -> None:
        """Output shape must match input length."""
        from packages.indicators.src.volatility import chaikin_volatility

        high, low, close, _ = _ohlcv(100)
        result = chaikin_volatility(high, low, period=10, roc_period=10)
        assert result.shape == (100,)

    def test_chaikin_vol_warmup_nans(self) -> None:
        """First period + roc_period - 1 bars must be NaN."""
        from packages.indicators.src.volatility import chaikin_volatility

        high, low, close, _ = _ohlcv(150)
        period = 10
        roc_period = 10
        result = chaikin_volatility(high, low, period=period, roc_period=roc_period)
        # EMA needs period-1 warmup, then ROC needs roc_period more → total = period-1+roc_period
        # At index (period - 1 + roc_period) we should have the first valid value
        warmup = period - 1 + roc_period
        assert np.all(np.isnan(result[:warmup]))
        assert not np.isnan(result[warmup])

    def test_chaikin_vol_flat_range_stays_near_zero(self) -> None:
        """Constant high-low range → EMA is constant → ROC = 0."""
        from packages.indicators.src.volatility import chaikin_volatility

        n = 100
        high = _flat(n, 105.0)
        low = _flat(n, 95.0)
        result = chaikin_volatility(high, low, period=10, roc_period=10)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.zeros(len(valid)), decimal=6)

    def test_chaikin_vol_expanding_range_positive(self) -> None:
        """Widening H-L range → ROC of EMA(range) should be positive."""
        from packages.indicators.src.volatility import chaikin_volatility

        n = 100
        # H-L grows linearly from 1 to 100
        range_vals = np.linspace(1.0, 100.0, n, dtype=np.float64)
        high = 100.0 + range_vals / 2.0
        low = 100.0 - range_vals / 2.0
        result = chaikin_volatility(high, low, period=5, roc_period=5)
        valid = result[~np.isnan(result)]
        assert len(valid) > 0
        # Mean should be clearly positive
        assert float(np.mean(valid)) > 0.0

    def test_chaikin_vol_length_mismatch_raises(self) -> None:
        """Mismatched high and low lengths must raise ValueError."""
        from packages.indicators.src.volatility import chaikin_volatility

        high = _flat(50, 110.0)
        low = _flat(40, 90.0)
        with pytest.raises(ValueError, match="length mismatch"):
            chaikin_volatility(high, low)

    def test_chaikin_vol_returns_float64(self) -> None:
        """Output dtype must be float64."""
        from packages.indicators.src.volatility import chaikin_volatility

        high, low, close, _ = _ohlcv(100)
        assert chaikin_volatility(high, low).dtype == np.float64

    def test_chaikin_vol_invalid_period_raises(self) -> None:
        """Period < 1 must raise ValueError."""
        from packages.indicators.src.volatility import chaikin_volatility

        high = _flat(50, 110.0)
        low = _flat(50, 90.0)
        with pytest.raises(ValueError, match="period"):
            chaikin_volatility(high, low, period=0)

    def test_chaikin_vol_invalid_roc_period_raises(self) -> None:
        """roc_period < 1 must raise ValueError."""
        from packages.indicators.src.volatility import chaikin_volatility

        high = _flat(50, 110.0)
        low = _flat(50, 90.0)
        with pytest.raises(ValueError, match="roc_period"):
            chaikin_volatility(high, low, period=10, roc_period=0)
