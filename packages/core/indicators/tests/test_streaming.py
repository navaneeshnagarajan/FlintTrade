"""Tests for streaming indicator classes.

15+ tests covering warm-up behaviour, mathematical correctness,
convergence to batch equivalents, reset, and edge cases.
"""

from __future__ import annotations

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _feed(cls_instance, prices):
    """Feed a list of prices through a streaming instance, return all outputs."""
    return [cls_instance.update(p) for p in prices]


def _arange(n: int, start: float = 1.0, step: float = 1.0) -> list[float]:
    return list(np.arange(start, start + n * step, step, dtype=np.float64))


# ---------------------------------------------------------------------------
# StreamingEMA
# ---------------------------------------------------------------------------


class TestStreamingEMA:
    def test_warmup_returns_none(self):
        from flinttrade_indicators.streaming import StreamingEMA

        ema = StreamingEMA(period=5)
        results = _feed(ema, [1.0, 2.0, 3.0, 4.0])  # 4 ticks < period
        assert all(r is None for r in results)

    def test_first_value_after_warmup_is_mean(self):
        from flinttrade_indicators.streaming import StreamingEMA

        ema = StreamingEMA(period=5)
        prices = [2.0, 4.0, 6.0, 8.0, 10.0]
        results = _feed(ema, prices)
        # After period ticks the first value = mean([2,4,6,8,10]) = 6.0
        assert results[-1] == pytest.approx(6.0)

    def test_converges_to_batch_ema(self):
        """StreamingEMA should match the batch ema() on the same data."""
        from flinttrade_indicators.streaming import StreamingEMA
        from flinttrade_indicators.trend import ema as batch_ema

        prices = list(np.linspace(100, 110, 50))
        period = 10
        streaming = StreamingEMA(period=period)
        stream_results = [streaming.update(p) for p in prices]

        close = np.array(prices, dtype=np.float64)
        batch = batch_ema(close, period)

        # Compare only values where both are not None/NaN
        for i, r in enumerate(stream_results):
            if r is not None:
                assert r == pytest.approx(batch[i], rel=1e-9)

    def test_value_property_matches_last_update(self):
        from flinttrade_indicators.streaming import StreamingEMA

        ema = StreamingEMA(5)
        for p in [10.0, 10.0, 10.0, 10.0, 10.0]:
            last = ema.update(p)
        assert ema.value == last

    def test_invalid_period_raises(self):
        from flinttrade_indicators.streaming import StreamingEMA

        with pytest.raises(ValueError):
            StreamingEMA(period=0)

    def test_reset_clears_state(self):
        from flinttrade_indicators.streaming import StreamingEMA

        ema = StreamingEMA(3)
        for p in [1.0, 2.0, 3.0, 4.0]:
            ema.update(p)
        ema.reset()
        assert ema.value is None
        assert ema.update(1.0) is None


# ---------------------------------------------------------------------------
# StreamingSMA
# ---------------------------------------------------------------------------


class TestStreamingSMA:
    def test_warmup_returns_none(self):
        from flinttrade_indicators.streaming import StreamingSMA

        sma = StreamingSMA(period=3)
        assert sma.update(1.0) is None
        assert sma.update(2.0) is None

    def test_first_value_is_mean_of_window(self):
        from flinttrade_indicators.streaming import StreamingSMA

        sma = StreamingSMA(period=3)
        sma.update(2.0)
        sma.update(4.0)
        result = sma.update(6.0)  # window full: mean([2,4,6]) = 4.0
        assert result == pytest.approx(4.0)

    def test_sliding_window_drops_oldest(self):
        from flinttrade_indicators.streaming import StreamingSMA

        sma = StreamingSMA(period=3)
        for p in [1.0, 1.0, 1.0]:
            sma.update(p)
        # Slide in 4.0: window=[1,1,4], mean=2.0
        result = sma.update(4.0)
        assert result == pytest.approx(2.0)

    def test_converges_to_batch_sma(self):
        from flinttrade_indicators.streaming import StreamingSMA
        from flinttrade_indicators.trend import sma as batch_sma

        prices = list(np.linspace(100, 120, 60))
        period = 10
        streaming = StreamingSMA(period)
        stream_results = [streaming.update(p) for p in prices]

        close = np.array(prices, dtype=np.float64)
        batch = batch_sma(close, period)

        for i, r in enumerate(stream_results):
            if r is not None:
                assert r == pytest.approx(batch[i], rel=1e-9)

    def test_reset_clears_state(self):
        from flinttrade_indicators.streaming import StreamingSMA

        sma = StreamingSMA(3)
        for p in [1.0, 2.0, 3.0]:
            sma.update(p)
        sma.reset()
        assert sma.value is None

    def test_invalid_period_raises(self):
        from flinttrade_indicators.streaming import StreamingSMA

        with pytest.raises(ValueError):
            StreamingSMA(0)


# ---------------------------------------------------------------------------
# StreamingRSI
# ---------------------------------------------------------------------------


class TestStreamingRSI:
    def test_warmup_returns_none(self):
        from flinttrade_indicators.streaming import StreamingRSI

        rsi = StreamingRSI(period=14)
        results = [rsi.update(float(i)) for i in range(14)]  # need period+1 prices
        assert all(r is None for r in results)

    def test_first_value_emitted_after_period_plus_one_ticks(self):
        from flinttrade_indicators.streaming import StreamingRSI

        rsi = StreamingRSI(period=14)
        result = None
        for i in range(15):  # period+1 prices
            result = rsi.update(float(i))
        assert result is not None

    def test_range_0_to_100(self):
        from flinttrade_indicators.streaming import StreamingRSI

        rsi = StreamingRSI(period=5)
        rng = np.random.default_rng(42)
        prices = 100.0 + np.cumsum(rng.normal(0, 1, 100))
        for p in prices:
            r = rsi.update(float(p))
            if r is not None:
                assert 0.0 <= r <= 100.0, f"RSI out of range: {r}"

    def test_converges_to_batch_rsi(self):
        from flinttrade_indicators.streaming import StreamingRSI
        from flinttrade_indicators.momentum import rsi as batch_rsi

        rng = np.random.default_rng(7)
        close = 100.0 + np.cumsum(rng.normal(0, 0.5, 100))
        close = close.astype(np.float64)
        period = 14

        streaming = StreamingRSI(period)
        stream_results = [streaming.update(float(p)) for p in close]
        batch = batch_rsi(close, period)

        for i, r in enumerate(stream_results):
            if r is not None:
                assert r == pytest.approx(batch[i], abs=1e-8)

    def test_reset_clears_state(self):
        from flinttrade_indicators.streaming import StreamingRSI

        rsi = StreamingRSI(5)
        for i in range(10):
            rsi.update(float(i))
        rsi.reset()
        assert rsi.value is None


# ---------------------------------------------------------------------------
# StreamingATR
# ---------------------------------------------------------------------------


class TestStreamingATR:
    def test_warmup_returns_none(self):
        from flinttrade_indicators.streaming import StreamingATR

        atr = StreamingATR(period=14)
        results = []
        for i in range(13):
            results.append(atr.update(float(i + 1), float(i), float(i + 0.5)))
        assert all(r is None for r in results)

    def test_first_value_after_warmup(self):
        from flinttrade_indicators.streaming import StreamingATR

        period = 5
        atr = StreamingATR(period=period)
        result = None
        for i in range(period):
            result = atr.update(float(i + 2), float(i), float(i + 1))
        assert result is not None
        assert result > 0.0

    def test_converges_to_batch_atr(self):
        """StreamingATR should match batch atr() on the same OHLC data."""
        from flinttrade_indicators.streaming import StreamingATR
        from flinttrade_indicators.volatility import atr as batch_atr

        rng = np.random.default_rng(55)
        n = 100
        close = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
        high = close + np.abs(rng.normal(0, 0.3, n))
        low = close - np.abs(rng.normal(0, 0.3, n))
        high, low, close = high.astype(np.float64), low.astype(np.float64), close.astype(np.float64)

        period = 14
        streaming = StreamingATR(period)
        stream_results = [streaming.update(float(hi), float(lo), float(cl)) for hi, lo, cl in zip(high, low, close)]
        batch = batch_atr(high, low, close, period)

        for i, r in enumerate(stream_results):
            if r is not None:
                assert r == pytest.approx(batch[i], abs=1e-8)

    def test_reset_clears_state(self):
        from flinttrade_indicators.streaming import StreamingATR

        atr = StreamingATR(5)
        for i in range(10):
            atr.update(float(i + 2), float(i), float(i + 1))
        atr.reset()
        assert atr.value is None

    def test_invalid_period_raises(self):
        from flinttrade_indicators.streaming import StreamingATR

        with pytest.raises(ValueError):
            StreamingATR(period=0)
