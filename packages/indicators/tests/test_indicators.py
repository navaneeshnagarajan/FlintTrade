"""Tests for packages/indicators — all pure Python/NumPy indicators.

Coverage targets:
- EMA: seeding, smoothing multiplier, NaN boundary
- SMA: rolling window correctness
- DEMA: faster response than plain EMA
- Supertrend: direction detection, band carryover
- VWAP: weighted average correctness, zero-volume guard
- RSI: overbought / oversold levels, Wilder smoothing seed
- MACD: line computation, signal EMA alignment, histogram sign
- Stochastic: %K range, %D smoothing
- Williams %R: inverse of stochastic, range constraint
- ATR: Wilder smoothing, True Range computation
- Bollinger Bands: band width, upper > middle > lower
- Keltner Channels: EMA centre, ATR-based width
- Utilities: type guard, length guard, OHLCV mismatch guard
"""

from __future__ import annotations

import numpy as np
import pytest
from numpy.testing import assert_array_almost_equal, assert_array_equal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _arange(n: int, start: float = 1.0, step: float = 1.0) -> np.ndarray:
    """Monotonically rising price series as float64."""
    return np.arange(start, start + n * step, step, dtype=np.float64)


def _flat(n: int, value: float = 100.0) -> np.ndarray:
    """Constant price series."""
    return np.full(n, value, dtype=np.float64)


# ---------------------------------------------------------------------------
# Trend — EMA
# ---------------------------------------------------------------------------


class TestEMA:
    def test_ema_shorter_than_period_returns_all_nan(self):
        from packages.indicators.src.trend import ema

        result = ema(np.array([1.0, 2.0], dtype=np.float64), period=5)
        assert np.all(np.isnan(result))

    def test_ema_seed_equals_mean_of_first_period_bars(self):
        from packages.indicators.src.trend import ema

        close = np.array([2.0, 4.0, 6.0, 8.0, 10.0, 12.0], dtype=np.float64)
        result = ema(close, period=3)
        # Seed at index 2 = mean([2, 4, 6]) = 4.0
        assert result[0] == pytest.approx(np.nan, nan_ok=True)
        assert result[2] == pytest.approx(4.0)

    def test_ema_smoothing_constant(self):
        """EMA[i] = close[i] * k + EMA[i-1] * (1-k)  where k = 2/(period+1)."""
        from packages.indicators.src.trend import ema

        close = np.array([10.0, 10.0, 10.0, 20.0], dtype=np.float64)
        result = ema(close, period=3)
        k = 2.0 / (3 + 1)
        expected = 20.0 * k + result[2] * (1.0 - k)
        assert result[3] == pytest.approx(expected)

    def test_ema_constant_series_equals_constant(self):
        from packages.indicators.src.trend import ema

        close = _flat(30, value=50.0)
        result = ema(close, period=5)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.full(len(valid), 50.0))

    def test_ema_invalid_period_raises(self):
        from packages.indicators.src.trend import ema

        with pytest.raises(ValueError):
            ema(np.array([1.0, 2.0], dtype=np.float64), period=0)


# ---------------------------------------------------------------------------
# Trend — SMA
# ---------------------------------------------------------------------------


class TestSMA:
    def test_sma_3_period_on_1_to_5(self):
        """SMA(3) on [1,2,3,4,5] = [nan, nan, 2, 3, 4]."""
        from packages.indicators.src.trend import sma

        close = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64)
        result = sma(close, period=3)
        assert np.isnan(result[0])
        assert np.isnan(result[1])
        assert result[2] == pytest.approx(2.0)
        assert result[3] == pytest.approx(3.0)
        assert result[4] == pytest.approx(4.0)

    def test_sma_1_period_equals_close(self):
        from packages.indicators.src.trend import sma

        close = _arange(10)
        result = sma(close, period=1)
        assert_array_almost_equal(result, close)

    def test_sma_constant_series(self):
        from packages.indicators.src.trend import sma

        close = _flat(20, 7.0)
        result = sma(close, period=5)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.full(len(valid), 7.0))


# ---------------------------------------------------------------------------
# Trend — DEMA
# ---------------------------------------------------------------------------


class TestDEMA:
    def test_dema_faster_lag_than_ema(self):
        """DEMA should track a rising series with less lag than plain EMA."""
        from packages.indicators.src.trend import dema, ema

        close = _arange(60, start=100.0, step=1.0)  # linearly rising
        period = 10
        e = ema(close, period)
        d = dema(close, period)

        # At the last bar, DEMA should be closer to close[-1] than plain EMA
        last_close = close[-1]
        e_lag = abs(last_close - e[-1])
        d_lag = abs(last_close - d[-1])
        assert d_lag < e_lag, "DEMA should exhibit less lag than EMA"

    def test_dema_constant_series_equals_constant(self):
        from packages.indicators.src.trend import dema

        close = _flat(60, 25.0)
        result = dema(close, period=5)
        valid = result[~np.isnan(result)]
        assert len(valid) > 0
        assert_array_almost_equal(valid, np.full(len(valid), 25.0))

    def test_dema_nan_count_is_double_ema_nan_count(self):
        """DEMA needs 2*(period-1) warmup bars, EMA needs period-1."""
        from packages.indicators.src.trend import dema, ema

        close = _arange(50)
        period = 5
        e_nans = int(np.sum(np.isnan(ema(close, period))))
        d_nans = int(np.sum(np.isnan(dema(close, period))))
        # DEMA is EMA of EMA, so it needs twice the warmup
        assert d_nans >= e_nans, "DEMA should have at least as many NaNs as EMA"
        assert d_nans == 2 * (period - 1)


# ---------------------------------------------------------------------------
# Trend — Supertrend
# ---------------------------------------------------------------------------


class TestSupertrend:
    def _make_ohlcv(self, n: int = 50) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Generate realistic OHLCV-like high/low/close arrays."""
        close = 100.0 + np.cumsum(np.random.default_rng(42).normal(0, 0.5, n))
        high = close + np.abs(np.random.default_rng(1).normal(0, 0.3, n))
        low = close - np.abs(np.random.default_rng(2).normal(0, 0.3, n))
        return (
            high.astype(np.float64),
            low.astype(np.float64),
            close.astype(np.float64),
        )

    def test_supertrend_returns_correct_shapes(self):
        from packages.indicators.src.trend import supertrend

        high, low, close = self._make_ohlcv(50)
        st, direction = supertrend(high, low, close, period=10, multiplier=3.0)
        assert st.shape == (50,)
        assert direction.shape == (50,)

    def test_supertrend_direction_is_bool(self):
        from packages.indicators.src.trend import supertrend

        high, low, close = self._make_ohlcv(30)
        _, direction = supertrend(high, low, close, period=5)
        assert direction.dtype == np.bool_

    def test_supertrend_uptrend_st_below_close(self):
        """In uptrend bars, supertrend value must be <= close."""
        from packages.indicators.src.trend import supertrend

        high, low, close = self._make_ohlcv(100)
        st, direction = supertrend(high, low, close, period=10, multiplier=3.0)

        for i in range(len(close)):
            if np.isnan(st[i]):
                continue
            if direction[i]:  # uptrend: ST should be support (below close)
                assert st[i] <= close[i] + 1e-9, (
                    f"Bar {i}: uptrend but ST={st[i]:.2f} > close={close[i]:.2f}"
                )
            else:  # downtrend: ST should be resistance (above close)
                assert st[i] >= close[i] - 1e-9, (
                    f"Bar {i}: downtrend but ST={st[i]:.2f} < close={close[i]:.2f}"
                )

    def test_supertrend_short_series_returns_nan(self):
        from packages.indicators.src.trend import supertrend

        n = 5
        h = np.full(n, 101.0, dtype=np.float64)
        l = np.full(n, 99.0, dtype=np.float64)
        c = np.full(n, 100.0, dtype=np.float64)
        st, _ = supertrend(h, l, c, period=10)
        # Insufficient data — all ST values should be NaN
        assert np.all(np.isnan(st))


# ---------------------------------------------------------------------------
# Trend — VWAP
# ---------------------------------------------------------------------------


class TestVWAP:
    def test_vwap_equal_volume_equals_typical_price(self):
        """When all volumes are equal, VWAP = mean of typical prices."""
        from packages.indicators.src.trend import vwap

        high = np.array([102.0, 103.0, 101.0], dtype=np.float64)
        low = np.array([98.0, 97.0, 99.0], dtype=np.float64)
        close = np.array([100.0, 101.0, 100.0], dtype=np.float64)
        volume = np.array([100.0, 100.0, 100.0], dtype=np.float64)

        result = vwap(high, low, close, volume)
        typical = (high + low + close) / 3.0
        expected_last = np.cumsum(typical * volume)[-1] / np.cumsum(volume)[-1]
        assert result[-1] == pytest.approx(expected_last)

    def test_vwap_first_bar_equals_typical_price(self):
        """VWAP at bar 0 should equal the first bar's typical price."""
        from packages.indicators.src.trend import vwap

        h = np.array([105.0], dtype=np.float64)
        l = np.array([95.0], dtype=np.float64)
        c = np.array([100.0], dtype=np.float64)
        vol = np.array([500.0], dtype=np.float64)
        result = vwap(h, l, c, vol)
        assert result[0] == pytest.approx((105 + 95 + 100) / 3.0)

    def test_vwap_zero_volume_returns_nan(self):
        from packages.indicators.src.trend import vwap

        h = np.array([100.0, 101.0], dtype=np.float64)
        l = np.array([99.0, 100.0], dtype=np.float64)
        c = np.array([100.0, 100.5], dtype=np.float64)
        vol = np.array([0.0, 0.0], dtype=np.float64)
        result = vwap(h, l, c, vol)
        assert np.all(np.isnan(result))


# ---------------------------------------------------------------------------
# Momentum — RSI
# ---------------------------------------------------------------------------


class TestRSI:
    def _make_trending_up(self, n: int = 50) -> np.ndarray:
        """Steadily rising closes — RSI should be high (overbought)."""
        return _arange(n, start=100.0, step=1.0)

    def _make_trending_down(self, n: int = 50) -> np.ndarray:
        """Steadily falling closes — RSI should be low (oversold)."""
        return np.arange(100.0, 100.0 - n, -1.0, dtype=np.float64)

    def test_rsi_uptrend_overbought(self):
        from packages.indicators.src.momentum import rsi

        result = rsi(self._make_trending_up(50), period=14)
        valid = result[~np.isnan(result)]
        assert np.all(valid > 70), "Steady uptrend should produce RSI > 70"

    def test_rsi_downtrend_oversold(self):
        from packages.indicators.src.momentum import rsi

        result = rsi(self._make_trending_down(50), period=14)
        valid = result[~np.isnan(result)]
        assert np.all(valid < 30), "Steady downtrend should produce RSI < 30"

    def test_rsi_range_0_to_100(self):
        from packages.indicators.src.momentum import rsi

        rng = np.random.default_rng(99)
        close = 100.0 + np.cumsum(rng.normal(0, 1, 200)).astype(np.float64)
        result = rsi(close, period=14)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= 0.0) and np.all(valid <= 100.0)

    def test_rsi_first_period_values_are_nan(self):
        from packages.indicators.src.momentum import rsi

        close = _arange(30)
        result = rsi(close, period=14)
        # Indices 0 through 13 (14 values) should be NaN
        assert np.all(np.isnan(result[:14]))
        assert not np.isnan(result[14])


# ---------------------------------------------------------------------------
# Momentum — MACD
# ---------------------------------------------------------------------------


class TestMACD:
    def test_macd_uptrend_line_positive(self):
        """In a steady uptrend, fast EMA > slow EMA, so MACD line is positive."""
        from packages.indicators.src.momentum import macd

        close = _arange(100, start=100.0)
        macd_line, _, _ = macd(close, fast=12, slow=26, signal=9)
        valid = macd_line[~np.isnan(macd_line)]
        assert np.all(valid > 0)

    def test_macd_shapes_match_input(self):
        from packages.indicators.src.momentum import macd

        close = _arange(60)
        ml, sl, h = macd(close)
        assert ml.shape == close.shape
        assert sl.shape == close.shape
        assert h.shape == close.shape

    def test_macd_histogram_equals_line_minus_signal(self):
        from packages.indicators.src.momentum import macd

        close = _arange(80)
        ml, sl, h = macd(close)
        valid = ~np.isnan(ml) & ~np.isnan(sl)
        assert_array_almost_equal(h[valid], (ml - sl)[valid])

    def test_macd_signal_cross_detectable(self):
        """A fabricated crossover: declining then rising should produce a MACD cross."""
        from packages.indicators.src.momentum import macd

        rng = np.random.default_rng(7)
        down = 200.0 - np.arange(50, dtype=np.float64) + rng.normal(0, 0.5, 50)
        up = down[-1] + np.arange(50, dtype=np.float64) + rng.normal(0, 0.5, 50)
        close = np.concatenate([down, up])

        ml, sl, h = macd(close)
        valid = ~np.isnan(h)
        # Histogram should change sign somewhere
        signs = np.sign(h[valid])
        assert len(np.unique(signs)) > 1, "No MACD cross detected in test series"


# ---------------------------------------------------------------------------
# Momentum — Stochastic
# ---------------------------------------------------------------------------


class TestStochastic:
    def test_stochastic_k_range_0_to_100(self):
        from packages.indicators.src.momentum import stochastic

        rng = np.random.default_rng(5)
        close = 100.0 + np.cumsum(rng.normal(0, 0.5, 60)).astype(np.float64)
        high = close + np.abs(rng.normal(0, 0.3, 60))
        low = close - np.abs(rng.normal(0, 0.3, 60))
        k, _ = stochastic(high.astype(np.float64), low.astype(np.float64), close)
        valid_k = k[~np.isnan(k)]
        assert np.all(valid_k >= 0.0) and np.all(valid_k <= 100.0)

    def test_stochastic_d_is_sma_of_k(self):
        """Spot-check that %D is the 3-period SMA of %K."""
        from packages.indicators.src.momentum import stochastic
        from packages.indicators.src.trend import sma

        rng = np.random.default_rng(13)
        close = 100.0 + np.cumsum(rng.normal(0, 0.5, 50)).astype(np.float64)
        high = (close + 1.0).astype(np.float64)
        low = (close - 1.0).astype(np.float64)
        k, d = stochastic(high, low, close)
        d_expected = sma(k, 3)
        valid = ~np.isnan(d) & ~np.isnan(d_expected)
        assert_array_almost_equal(d[valid], d_expected[valid])


# ---------------------------------------------------------------------------
# Momentum — Williams %R
# ---------------------------------------------------------------------------


class TestWilliamsR:
    def test_williams_r_range_minus100_to_0(self):
        from packages.indicators.src.momentum import williams_r

        rng = np.random.default_rng(21)
        close = 100.0 + np.cumsum(rng.normal(0, 0.5, 60)).astype(np.float64)
        high = (close + np.abs(rng.normal(0, 0.5, 60))).astype(np.float64)
        low = (close - np.abs(rng.normal(0, 0.5, 60))).astype(np.float64)

        result = williams_r(high, low, close, period=14)
        valid = result[~np.isnan(result)]
        assert np.all(valid >= -100.0) and np.all(valid <= 0.0)

    def test_williams_r_at_high_equals_zero(self):
        """When close equals the highest high, %R should be 0."""
        from packages.indicators.src.momentum import williams_r

        n = 20
        period = 5
        high = np.full(n, 110.0, dtype=np.float64)
        low = np.full(n, 90.0, dtype=np.float64)
        close = np.full(n, 110.0, dtype=np.float64)  # close == highest_high

        result = williams_r(high, low, close, period=period)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.zeros(len(valid)))

    def test_williams_r_at_low_equals_minus100(self):
        """When close equals the lowest low, %R should be -100."""
        from packages.indicators.src.momentum import williams_r

        n = 20
        period = 5
        high = np.full(n, 110.0, dtype=np.float64)
        low = np.full(n, 90.0, dtype=np.float64)
        close = np.full(n, 90.0, dtype=np.float64)  # close == lowest_low

        result = williams_r(high, low, close, period=period)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.full(len(valid), -100.0))


# ---------------------------------------------------------------------------
# Volatility — ATR
# ---------------------------------------------------------------------------


class TestATR:
    def test_atr_constant_range_equals_range(self):
        """If high - low is constant and no gaps, ATR should converge to that range."""
        from packages.indicators.src.volatility import atr

        n = 50
        high = np.full(n, 102.0, dtype=np.float64)
        low = np.full(n, 98.0, dtype=np.float64)
        close = np.full(n, 100.0, dtype=np.float64)
        result = atr(high, low, close, period=14)
        # After warmup, ATR should be close to 4.0 (high-low)
        valid = result[~np.isnan(result)]
        assert_array_almost_equal(valid, np.full(len(valid), 4.0))

    def test_atr_returns_nan_for_warmup_period(self):
        from packages.indicators.src.volatility import atr

        n = 20
        h = np.full(n, 101.0, dtype=np.float64)
        l = np.full(n, 99.0, dtype=np.float64)
        c = np.full(n, 100.0, dtype=np.float64)
        result = atr(h, l, c, period=14)
        assert np.all(np.isnan(result[:13]))  # indices 0-12 should be NaN
        assert not np.isnan(result[13])

    def test_atr_shapes_match_input(self):
        from packages.indicators.src.volatility import atr

        n = 40
        h = np.full(n, 101.0, dtype=np.float64)
        l = np.full(n, 99.0, dtype=np.float64)
        c = np.full(n, 100.0, dtype=np.float64)
        result = atr(h, l, c)
        assert result.shape == (n,)


# ---------------------------------------------------------------------------
# Volatility — Bollinger Bands
# ---------------------------------------------------------------------------


class TestBollingerBands:
    def test_upper_gt_middle_gt_lower(self):
        """Upper band must always be above middle, lower always below."""
        from packages.indicators.src.volatility import bollinger_bands

        rng = np.random.default_rng(3)
        close = (100.0 + np.cumsum(rng.normal(0, 1.0, 50))).astype(np.float64)
        upper, middle, lower = bollinger_bands(close, period=20)
        valid = ~np.isnan(upper) & ~np.isnan(middle) & ~np.isnan(lower)
        assert np.all(upper[valid] >= middle[valid])
        assert np.all(middle[valid] >= lower[valid])

    def test_middle_equals_sma(self):
        from packages.indicators.src.volatility import bollinger_bands
        from packages.indicators.src.trend import sma

        close = _arange(40).astype(np.float64)
        _, middle, _ = bollinger_bands(close, period=10)
        expected_middle = sma(close, period=10)
        valid = ~np.isnan(middle)
        assert_array_almost_equal(middle[valid], expected_middle[valid])

    def test_constant_series_has_zero_width_bands(self):
        """Constant prices have zero std dev — bands should collapse to SMA."""
        from packages.indicators.src.volatility import bollinger_bands

        close = _flat(30, 50.0)
        upper, middle, lower = bollinger_bands(close, period=10)
        valid = ~np.isnan(upper)
        assert_array_almost_equal(upper[valid], middle[valid])
        assert_array_almost_equal(lower[valid], middle[valid])


# ---------------------------------------------------------------------------
# Volatility — Keltner Channels
# ---------------------------------------------------------------------------


class TestKeltnerChannels:
    def test_keltner_upper_gt_middle_gt_lower(self):
        from packages.indicators.src.volatility import keltner_channels

        rng = np.random.default_rng(8)
        close = (100.0 + np.cumsum(rng.normal(0, 0.5, 60))).astype(np.float64)
        high = (close + 1.0).astype(np.float64)
        low = (close - 1.0).astype(np.float64)
        upper, middle, lower = keltner_channels(high, low, close)
        valid = ~np.isnan(upper) & ~np.isnan(middle) & ~np.isnan(lower)
        assert np.all(upper[valid] > lower[valid])


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


class TestUtils:
    def test_validate_series_rejects_list(self):
        from packages.indicators.src.utils import validate_series

        with pytest.raises(TypeError):
            validate_series([1.0, 2.0, 3.0], min_length=1)  # type: ignore[arg-type]

    def test_validate_series_rejects_short_array(self):
        from packages.indicators.src.utils import validate_series

        with pytest.raises(ValueError):
            validate_series(np.array([1.0], dtype=np.float64), min_length=5)

    def test_validate_ohlcv_rejects_mismatched_lengths(self):
        from packages.indicators.src.utils import validate_ohlcv

        h = np.array([1.0, 2.0], dtype=np.float64)
        l = np.array([1.0], dtype=np.float64)
        c = np.array([1.0, 2.0], dtype=np.float64)
        with pytest.raises(ValueError, match="length mismatch"):
            validate_ohlcv(h, l, c)

    def test_validate_series_passes_for_valid_array(self):
        from packages.indicators.src.utils import validate_series

        validate_series(np.array([1.0, 2.0, 3.0], dtype=np.float64), min_length=3)
