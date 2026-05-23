"""Tests for extended streaming indicator classes.

Covers:
- StreamingMACD        — warm-up, convergence to batch, reset
- StreamingBollingerBands — warm-up, bandwidth/percentB, convergence, reset
- StreamingSupertrend  — warm-up, direction flips, reset
- StreamingVWAP        — cumulative, anchor reset, reset
- StreamingCumulativeDelta — up/down/flat bars, reset
"""

from __future__ import annotations

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rng_prices(n: int, seed: int = 42, start: float = 100.0) -> list[float]:
    rng = np.random.default_rng(seed)
    return list(start + np.cumsum(rng.normal(0, 0.5, n)))


def _rng_hlcv(n: int, seed: int = 42) -> tuple[list, list, list, list]:
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + np.abs(rng.normal(0, 0.3, n))
    low = close - np.abs(rng.normal(0, 0.3, n))
    vol = np.abs(rng.normal(50000, 10000, n))
    return list(high), list(low), list(close), list(vol)


# ---------------------------------------------------------------------------
# StreamingMACD
# ---------------------------------------------------------------------------


class TestStreamingMACD:
    def test_warmup_returns_none_for_all_three(self):
        from flinttrade_indicators.streaming import StreamingMACD

        macd = StreamingMACD(fast_period=12, slow_period=26, signal_period=9)
        prices = _rng_prices(25)
        for p in prices:
            ml, sl, h = macd.update(p)
        # After 25 ticks (< slow_period 26): all should still be None
        assert ml is None
        assert sl is None
        assert h is None

    def test_first_valid_macd_line_after_slow_warmup(self):
        from flinttrade_indicators.streaming import StreamingMACD

        macd = StreamingMACD(fast_period=12, slow_period=26, signal_period=9)
        prices = _rng_prices(40)
        results = [macd.update(p) for p in prices]
        # After slow_period ticks the MACD line should appear
        non_none = [(i, r) for i, r in enumerate(results) if r[0] is not None]
        assert len(non_none) > 0

    def test_signal_appears_after_macd_plus_signal_warmup(self):
        from flinttrade_indicators.streaming import StreamingMACD

        macd = StreamingMACD(fast_period=3, slow_period=6, signal_period=4)
        prices = _rng_prices(20)
        results = [macd.update(p) for p in prices]
        # Signal should appear after at least slow+signal-1 ticks
        signal_values = [r[1] for r in results if r[1] is not None]
        assert len(signal_values) > 0

    def test_histogram_equals_macd_minus_signal(self):
        from flinttrade_indicators.streaming import StreamingMACD

        macd = StreamingMACD(fast_period=3, slow_period=6, signal_period=4)
        prices = _rng_prices(30)
        for p in prices:
            ml, sl, h = macd.update(p)
            if ml is not None and sl is not None and h is not None:
                assert h == pytest.approx(ml - sl, abs=1e-10)

    def test_properties_match_last_update(self):
        from flinttrade_indicators.streaming import StreamingMACD

        macd = StreamingMACD(fast_period=3, slow_period=6, signal_period=4)
        prices = _rng_prices(30)
        last_ml, last_sl, last_h = None, None, None
        for p in prices:
            last_ml, last_sl, last_h = macd.update(p)
        assert macd.macd == last_ml
        assert macd.signal == last_sl
        assert macd.histogram == last_h

    def test_converges_to_batch_macd(self):
        from flinttrade_indicators.streaming import StreamingMACD
        from flinttrade_indicators.momentum import macd as batch_macd

        prices = _rng_prices(100, seed=7)
        close = np.array(prices, dtype=np.float64)

        fast, slow, signal = 12, 26, 9
        streaming = StreamingMACD(fast, slow, signal)
        stream_results = [streaming.update(p) for p in prices]

        batch_ml, batch_sl, batch_h = batch_macd(close, fast, slow, signal)

        for i, (ml, sl, h) in enumerate(stream_results):
            if ml is not None:
                assert ml == pytest.approx(batch_ml[i], abs=1e-8)
            if sl is not None and not np.isnan(batch_sl[i]):
                assert sl == pytest.approx(batch_sl[i], abs=1e-8)
            if h is not None and not np.isnan(batch_h[i]):
                assert h == pytest.approx(batch_h[i], abs=1e-8)

    def test_invalid_fast_ge_slow_raises(self):
        from flinttrade_indicators.streaming import StreamingMACD

        with pytest.raises(ValueError, match="fast_period"):
            StreamingMACD(fast_period=26, slow_period=12)

    def test_invalid_fast_equal_slow_raises(self):
        from flinttrade_indicators.streaming import StreamingMACD

        with pytest.raises(ValueError):
            StreamingMACD(fast_period=12, slow_period=12)

    def test_reset_clears_state(self):
        from flinttrade_indicators.streaming import StreamingMACD

        macd = StreamingMACD(3, 6, 4)
        for p in _rng_prices(30):
            macd.update(p)
        macd.reset()
        assert macd.macd is None
        assert macd.signal is None
        assert macd.histogram is None
        ml, sl, h = macd.update(100.0)
        assert ml is None


# ---------------------------------------------------------------------------
# StreamingBollingerBands
# ---------------------------------------------------------------------------


class TestStreamingBollingerBands:
    def test_warmup_returns_none(self):
        from flinttrade_indicators.streaming import StreamingBollingerBands

        bb = StreamingBollingerBands(period=5)
        for i in range(4):
            upper, mid, lower = bb.update(float(100 + i))
            assert upper is None and mid is None and lower is None

    def test_first_valid_after_period_ticks(self):
        from flinttrade_indicators.streaming import StreamingBollingerBands

        bb = StreamingBollingerBands(period=5)
        results = [bb.update(float(100 + i)) for i in range(5)]
        upper, mid, lower = results[-1]
        assert upper is not None
        assert mid is not None
        assert lower is not None
        assert upper > mid > lower

    def test_middle_band_equals_sma(self):
        from flinttrade_indicators.streaming import StreamingBollingerBands
        from flinttrade_indicators.trend import sma as batch_sma

        period = 10
        prices = _rng_prices(50)
        bb = StreamingBollingerBands(period=period)
        stream_mids = []
        for p in prices:
            _, mid, _ = bb.update(p)
            stream_mids.append(mid)

        close = np.array(prices, dtype=np.float64)
        batch_sma_vals = batch_sma(close, period)

        for i, mid in enumerate(stream_mids):
            if mid is not None and not np.isnan(batch_sma_vals[i]):
                assert mid == pytest.approx(batch_sma_vals[i], rel=1e-9)

    def test_converges_to_batch_bollinger_bands(self):
        from flinttrade_indicators.streaming import StreamingBollingerBands
        from flinttrade_indicators.volatility import bollinger_bands

        period, std_dev = 20, 2.0
        prices = _rng_prices(80, seed=99)
        close = np.array(prices, dtype=np.float64)

        bb = StreamingBollingerBands(period=period, std_dev=std_dev)
        stream_results = [bb.update(p) for p in prices]

        b_upper, b_mid, b_lower = bollinger_bands(close, period, std_dev)

        for i, (u, m, lo) in enumerate(stream_results):
            if u is not None and not np.isnan(b_upper[i]):
                assert u == pytest.approx(b_upper[i], rel=1e-9)
            if m is not None and not np.isnan(b_mid[i]):
                assert m == pytest.approx(b_mid[i], rel=1e-9)
            if lo is not None and not np.isnan(b_lower[i]):
                assert lo == pytest.approx(b_lower[i], rel=1e-9)

    def test_bandwidth_property(self):
        from flinttrade_indicators.streaming import StreamingBollingerBands

        bb = StreamingBollingerBands(period=5)
        for i in range(5):
            bb.update(float(100 + i * 0.5))
        assert bb.bandwidth is not None
        assert bb.bandwidth >= 0.0

    def test_percent_b_at_middle_is_approx_half(self):
        from flinttrade_indicators.streaming import StreamingBollingerBands

        bb = StreamingBollingerBands(period=5, std_dev=2.0)
        # Feed identical prices — middle == current price
        for _ in range(5):
            bb.update(100.0)
        # After uniform prices, std=0, bands collapse. percent_b should return 0.5
        pct_b = bb.percent_b
        # When band_width == 0 it returns 0.5
        assert pct_b == pytest.approx(0.5)

    def test_invalid_period_raises(self):
        from flinttrade_indicators.streaming import StreamingBollingerBands

        with pytest.raises(ValueError):
            StreamingBollingerBands(period=1)

    def test_reset_clears_state(self):
        from flinttrade_indicators.streaming import StreamingBollingerBands

        bb = StreamingBollingerBands(period=5)
        for i in range(10):
            bb.update(float(100 + i))
        bb.reset()
        assert bb.upper is None
        assert bb.middle is None
        assert bb.lower is None


# ---------------------------------------------------------------------------
# StreamingSupertrend
# ---------------------------------------------------------------------------


class TestStreamingSupertrend:
    def test_warmup_returns_none(self):
        from flinttrade_indicators.streaming import StreamingSupertrend

        st = StreamingSupertrend(period=10, multiplier=3.0)
        highs, lows, closes, _ = _rng_hlcv(9)
        for h, lo, c in zip(highs, lows, closes):
            val, direction = st.update(h, lo, c)
        assert val is None
        assert direction is None

    def test_first_valid_after_atr_warmup(self):
        from flinttrade_indicators.streaming import StreamingSupertrend

        period = 5
        st = StreamingSupertrend(period=period, multiplier=3.0)
        highs, lows, closes, _ = _rng_hlcv(20)
        val_last, dir_last = None, None
        for h, lo, c in zip(highs, lows, closes):
            val_last, dir_last = st.update(h, lo, c)

        assert val_last is not None
        assert dir_last in (-1, 1)

    def test_direction_is_plus_or_minus_one(self):
        from flinttrade_indicators.streaming import StreamingSupertrend

        st = StreamingSupertrend(period=5, multiplier=2.0)
        highs, lows, closes, _ = _rng_hlcv(50)
        for h, lo, c in zip(highs, lows, closes):
            _, direction = st.update(h, lo, c)
            if direction is not None:
                assert direction in (-1, 1)

    def test_value_property_matches_last_update(self):
        from flinttrade_indicators.streaming import StreamingSupertrend

        st = StreamingSupertrend(period=5)
        highs, lows, closes, _ = _rng_hlcv(30)
        last_val = None
        for h, lo, c in zip(highs, lows, closes):
            last_val, _ = st.update(h, lo, c)
        assert st.value == last_val

    def test_invalid_period_raises(self):
        from flinttrade_indicators.streaming import StreamingSupertrend

        with pytest.raises(ValueError):
            StreamingSupertrend(period=0)

    def test_reset_clears_state(self):
        from flinttrade_indicators.streaming import StreamingSupertrend

        st = StreamingSupertrend(period=5)
        highs, lows, closes, _ = _rng_hlcv(20)
        for h, lo, c in zip(highs, lows, closes):
            st.update(h, lo, c)
        st.reset()
        assert st.value is None
        assert st.direction is None


# ---------------------------------------------------------------------------
# StreamingVWAP
# ---------------------------------------------------------------------------


class TestStreamingVWAP:
    def test_single_bar_vwap_equals_typical_price(self):
        from flinttrade_indicators.streaming import StreamingVWAP

        vwap = StreamingVWAP()
        result = vwap.update(high=102.0, low=98.0, close=100.0, volume=10000.0)
        assert result == pytest.approx(100.0)  # (102+98+100)/3 = 100

    def test_cumulative_vwap_is_volume_weighted(self):
        from flinttrade_indicators.streaming import StreamingVWAP

        vwap = StreamingVWAP()
        # bar 1: tp=100, vol=1000
        vwap.update(101, 99, 100, 1000)
        # bar 2: tp=105, vol=3000  (higher vol)
        result = vwap.update(106, 104, 105, 3000)
        # expected = (100*1000 + 105*3000) / (1000+3000) = (100000+315000)/4000 = 103.75
        assert result == pytest.approx(103.75)

    def test_anchor_resets_accumulator(self):
        from flinttrade_indicators.streaming import StreamingVWAP

        vwap = StreamingVWAP()
        vwap.update(110, 100, 105, 1000)
        vwap.update(120, 110, 115, 1000)
        # anchor = True: reset, so VWAP should equal the typical price of this bar
        result = vwap.update(102, 98, 100, 5000, anchor=True)
        assert result == pytest.approx(100.0)

    def test_zero_volume_returns_none_on_reset(self):
        from flinttrade_indicators.streaming import StreamingVWAP

        vwap = StreamingVWAP()
        vwap.reset()  # cumulative_vol = 0
        result = vwap.update(100, 100, 100, 0.0)
        # After reset + zero volume, should be None
        assert result is None

    def test_value_property_matches_last_update(self):
        from flinttrade_indicators.streaming import StreamingVWAP

        vwap = StreamingVWAP()
        highs, lows, closes, vols = _rng_hlcv(20)
        last = None
        for h, lo, c, v in zip(highs, lows, closes, vols):
            last = vwap.update(h, lo, c, v)
        assert vwap.value == last

    def test_reset_clears_state(self):
        from flinttrade_indicators.streaming import StreamingVWAP

        vwap = StreamingVWAP()
        highs, lows, closes, vols = _rng_hlcv(10)
        for h, lo, c, v in zip(highs, lows, closes, vols):
            vwap.update(h, lo, c, v)
        vwap.reset()
        assert vwap.value is None


# ---------------------------------------------------------------------------
# StreamingCumulativeDelta
# ---------------------------------------------------------------------------


class TestStreamingCumulativeDelta:
    def test_up_bar_adds_volume(self):
        from flinttrade_indicators.streaming import StreamingCumulativeDelta

        cd = StreamingCumulativeDelta()
        cd.update(100.0, 1000.0)   # seed close
        result = cd.update(101.0, 500.0)  # up bar
        assert result == pytest.approx(500.0)

    def test_down_bar_subtracts_volume(self):
        from flinttrade_indicators.streaming import StreamingCumulativeDelta

        cd = StreamingCumulativeDelta()
        cd.update(100.0, 1000.0)
        result = cd.update(99.0, 600.0)  # down bar
        assert result == pytest.approx(-600.0)

    def test_flat_bar_unchanged(self):
        from flinttrade_indicators.streaming import StreamingCumulativeDelta

        cd = StreamingCumulativeDelta()
        cd.update(100.0, 1000.0)
        result = cd.update(100.0, 800.0)  # flat
        assert result == pytest.approx(0.0)

    def test_first_bar_does_not_add_volume(self):
        """The first bar has no prior close — delta stays at 0."""
        from flinttrade_indicators.streaming import StreamingCumulativeDelta

        cd = StreamingCumulativeDelta()
        result = cd.update(100.0, 1000.0)
        assert result == pytest.approx(0.0)

    def test_cumulation_across_multiple_bars(self):
        from flinttrade_indicators.streaming import StreamingCumulativeDelta

        cd = StreamingCumulativeDelta()
        bars = [
            (100.0, 1000.0),   # seed
            (101.0, 500.0),    # +500 → 500
            (99.0,  300.0),    # -300 → 200
            (99.0,  400.0),    # flat → 200
            (100.0, 200.0),    # +200 → 400
        ]
        results = [cd.update(c, v) for c, v in bars]
        assert results[-1] == pytest.approx(400.0)

    def test_converges_to_batch_cumulative_delta(self):
        from flinttrade_indicators.streaming import StreamingCumulativeDelta
        from flinttrade_indicators.volume import cumulative_delta

        prices = _rng_prices(60, seed=11)
        rng = np.random.default_rng(11)
        vols = list(np.abs(rng.normal(10000, 2000, 60)))

        cd = StreamingCumulativeDelta()
        stream_results = [cd.update(c, v) for c, v in zip(prices, vols)]

        close = np.array(prices, dtype=np.float64)
        volume = np.array(vols, dtype=np.float64)
        batch = cumulative_delta(close, volume)

        for i, r in enumerate(stream_results):
            assert r == pytest.approx(float(batch[i]), abs=1e-9)

    def test_value_property_matches_update(self):
        from flinttrade_indicators.streaming import StreamingCumulativeDelta

        cd = StreamingCumulativeDelta()
        prices = _rng_prices(20)
        last = None
        for p in prices:
            last = cd.update(p, 1000.0)
        assert cd.value == last

    def test_reset_clears_state(self):
        from flinttrade_indicators.streaming import StreamingCumulativeDelta

        cd = StreamingCumulativeDelta()
        for p in _rng_prices(10):
            cd.update(p, 1000.0)
        cd.reset()
        assert cd.value == pytest.approx(0.0)
        # After reset, first bar again should not add
        assert cd.update(100.0, 500.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Batch volume indicators (cumulative_delta, volume_profile)
# ---------------------------------------------------------------------------


class TestBatchCumulativeDelta:
    def test_shape_preserved(self):
        from flinttrade_indicators.volume import cumulative_delta

        n = 50
        close = np.linspace(100, 110, n)
        volume = np.ones(n) * 1000
        result = cumulative_delta(close, volume)
        assert result.shape == (n,)

    def test_first_value_is_zero(self):
        from flinttrade_indicators.volume import cumulative_delta

        close = np.array([100.0, 101.0, 100.0])
        volume = np.array([1000.0, 500.0, 300.0])
        result = cumulative_delta(close, volume)
        assert result[0] == pytest.approx(0.0)

    def test_monotone_up_close_adds_all_volume(self):
        from flinttrade_indicators.volume import cumulative_delta

        close = np.array([100.0, 101.0, 102.0, 103.0])
        volume = np.array([1000.0, 500.0, 300.0, 200.0])
        result = cumulative_delta(close, volume)
        assert result[-1] == pytest.approx(1000.0)

    def test_mismatched_lengths_raises(self):
        from flinttrade_indicators.volume import cumulative_delta

        with pytest.raises(ValueError):
            cumulative_delta(np.array([1.0, 2.0]), np.array([1.0]))


class TestBatchVolumeProfile:
    def test_returns_correct_shapes(self):
        from flinttrade_indicators.volume import volume_profile

        n, bins = 100, 10
        close = np.linspace(100, 110, n)
        volume = np.ones(n) * 1000
        prices, vols, poc = volume_profile(close, volume, num_bins=bins)
        assert prices.shape == (bins,)
        assert vols.shape == (bins,)

    def test_total_volume_conserved(self):
        from flinttrade_indicators.volume import volume_profile

        close = np.linspace(100, 120, 50)
        volume = np.ones(50) * 2000
        _, bin_vols, _ = volume_profile(close, volume, num_bins=10)
        assert float(np.sum(bin_vols)) == pytest.approx(50 * 2000, rel=1e-9)

    def test_poc_is_highest_volume_bin(self):
        from flinttrade_indicators.volume import volume_profile

        # Concentrate all volume at a single price
        close = np.array([100.0] * 80 + [120.0] * 20)
        volume = np.array([1000.0] * 80 + [100.0] * 20)
        prices, bin_vols, poc = volume_profile(close, volume, num_bins=5)
        poc_idx = int(np.argmax(bin_vols))
        assert poc == pytest.approx(float(prices[poc_idx]))

    def test_price_levels_span_price_range(self):
        from flinttrade_indicators.volume import volume_profile

        close = np.linspace(100, 200, 50)
        volume = np.ones(50)
        prices, _, _ = volume_profile(close, volume, num_bins=10)
        # Bin centres should be within the price range
        assert float(prices[0]) >= 100.0
        assert float(prices[-1]) <= 200.0

    def test_single_price_uniform_volume(self):
        from flinttrade_indicators.volume import volume_profile

        close = np.full(10, 150.0)
        volume = np.ones(10) * 100
        prices, bin_vols, poc = volume_profile(close, volume, num_bins=5)
        assert poc == pytest.approx(150.0)
        assert float(np.sum(bin_vols)) == pytest.approx(1000.0)

    def test_num_bins_less_than_2_raises(self):
        from flinttrade_indicators.volume import volume_profile

        with pytest.raises(ValueError):
            volume_profile(np.array([100.0, 110.0]), np.array([1.0, 1.0]), num_bins=1)

    def test_mismatched_lengths_raises(self):
        from flinttrade_indicators.volume import volume_profile

        with pytest.raises(ValueError):
            volume_profile(np.array([100.0, 110.0]), np.array([1.0]))
