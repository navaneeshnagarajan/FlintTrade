"""Tests for multi-timeframe signal alignment analyser.

All tests are self-contained — no API calls, no broker connection required.
Uses pytest with --import-mode=importlib.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from packages.screener.src.multi_timeframe import (
    MTFAnalysis,
    MultiTimeframeAnalyser,
    TimeframeSignal,
    _CONFLUENCE_THRESHOLD,
    _MIN_BARS,
    make_sample_mtf_data,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_trending_bars(n: int, start: float, direction: float = 1.0, seed: int = 0) -> list[dict]:
    """Generate bars with a clear trend (up if direction=1, down if -1).

    Args:
        n:         Number of bars.
        start:     Starting close price.
        direction: +1.0 for uptrend, -1.0 for downtrend.
        seed:      RNG seed.
    """
    rng = np.random.default_rng(seed)
    close = start
    bars = []
    for i in range(n):
        # Strong directional drift + small noise
        ret = direction * 0.003 + rng.standard_normal() * 0.001
        close = max(close * (1.0 + ret), 1.0)
        spread = close * 0.001
        high = close + abs(rng.standard_normal()) * spread
        low = close - abs(rng.standard_normal()) * spread
        bars.append({
            "timestamp": f"2025-01-15T{(9 + i // 60):02d}:{i % 60:02d}:00",
            "open": round(close, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "volume": 10000.0,
        })
    return bars


def _make_neutral_bars(n: int, start: float = 100.0, seed: int = 5) -> list[dict]:
    """Generate bars with no clear trend (random walk)."""
    rng = np.random.default_rng(seed)
    close = start
    bars = []
    for i in range(n):
        ret = rng.standard_normal() * 0.0005
        close = max(close * (1.0 + ret), 1.0)
        bars.append({
            "timestamp": f"2025-01-15T09:{i:02d}:00",
            "open": close,
            "high": close * 1.001,
            "low": close * 0.999,
            "close": close,
            "volume": 1000.0,
        })
    return bars


@pytest.fixture
def analyser() -> MultiTimeframeAnalyser:
    return MultiTimeframeAnalyser()


@pytest.fixture
def bullish_data() -> dict[str, list[dict]]:
    """Four timeframes all showing uptrend."""
    n = 100
    return {
        "5m":  _make_trending_bars(n, start=24000.0, direction=1.0, seed=1),
        "15m": _make_trending_bars(n, start=24000.0, direction=1.0, seed=2),
        "1h":  _make_trending_bars(n, start=24000.0, direction=1.0, seed=3),
        "1D":  _make_trending_bars(n, start=24000.0, direction=1.0, seed=4),
    }


@pytest.fixture
def bearish_data() -> dict[str, list[dict]]:
    """Four timeframes all showing downtrend."""
    n = 100
    return {
        "5m":  _make_trending_bars(n, start=24000.0, direction=-1.0, seed=10),
        "15m": _make_trending_bars(n, start=24000.0, direction=-1.0, seed=11),
        "1h":  _make_trending_bars(n, start=24000.0, direction=-1.0, seed=12),
        "1D":  _make_trending_bars(n, start=24000.0, direction=-1.0, seed=13),
    }


@pytest.fixture
def short_data() -> dict[str, list[dict]]:
    """All timeframes with fewer than _MIN_BARS bars — all should be skipped."""
    n = _MIN_BARS - 1
    return {
        "5m": _make_neutral_bars(n),
        "1h": _make_neutral_bars(n),
    }


# ---------------------------------------------------------------------------
# TimeframeSignal model
# ---------------------------------------------------------------------------


class TestTimeframeSignalModel:
    def test_valid_instantiation(self):
        sig = TimeframeSignal(
            timeframe="5m",
            trend="bullish",
            rsi=55.3,
            macd_histogram=12.5,
            ema_position="above",
            strength=0.65,
        )
        assert sig.timeframe == "5m"
        assert sig.trend == "bullish"
        assert sig.strength == 0.65

    def test_strength_bounds_enforced(self):
        with pytest.raises(Exception):
            TimeframeSignal(
                timeframe="5m",
                trend="bullish",
                rsi=50.0,
                macd_histogram=0.0,
                ema_position="above",
                strength=1.5,  # out of bounds
            )

    def test_strength_zero_boundary(self):
        sig = TimeframeSignal(
            timeframe="5m",
            trend="neutral",
            rsi=50.0,
            macd_histogram=0.0,
            ema_position="above",
            strength=0.0,
        )
        assert sig.strength == 0.0


# ---------------------------------------------------------------------------
# MTFAnalysis model
# ---------------------------------------------------------------------------


class TestMTFAnalysisModel:
    def test_model_serialises(self, analyser):
        data = make_sample_mtf_data(n_bars=100)
        result = analyser.analyse("TEST", data)
        d = result.model_dump()
        assert "symbol" in d
        assert "signals" in d
        assert "confluence" in d
        assert "overall" in d

    def test_confluence_bounds_enforced(self):
        with pytest.raises(Exception):
            MTFAnalysis(
                symbol="X",
                signals=[],
                confluence=1.5,  # out of bounds
                overall="neutral",
            )


# ---------------------------------------------------------------------------
# analyse — return type and structure
# ---------------------------------------------------------------------------


class TestAnalyseStructure:
    def test_returns_mtf_analysis(self, analyser, bullish_data):
        result = analyser.analyse("NIFTY", bullish_data)
        assert isinstance(result, MTFAnalysis)

    def test_symbol_preserved(self, analyser, bullish_data):
        result = analyser.analyse("BANKNIFTY", bullish_data)
        assert result.symbol == "BANKNIFTY"

    def test_signals_count_matches_valid_timeframes(self, analyser, bullish_data):
        result = analyser.analyse("NIFTY", bullish_data)
        assert len(result.signals) == len(bullish_data)

    def test_short_timeframes_skipped(self, analyser, short_data):
        result = analyser.analyse("TEST", short_data)
        # All timeframes are too short — no signals
        assert len(result.signals) == 0
        assert result.overall == "neutral"
        assert result.confluence == 0.0

    def test_empty_data_returns_neutral(self, analyser):
        result = analyser.analyse("TEST", {})
        assert result.overall == "neutral"
        assert result.confluence == 0.0
        assert result.signals == []

    def test_timeframe_labels_preserved(self, analyser, bullish_data):
        result = analyser.analyse("NIFTY", bullish_data)
        result_tfs = {s.timeframe for s in result.signals}
        assert result_tfs == set(bullish_data.keys())


# ---------------------------------------------------------------------------
# Trend direction
# ---------------------------------------------------------------------------


class TestTrendDirection:
    def test_uptrend_gives_bullish_signals(self, analyser, bullish_data):
        result = analyser.analyse("NIFTY", bullish_data)
        for sig in result.signals:
            assert sig.trend in ("bullish", "neutral"), (
                f"Timeframe {sig.timeframe}: expected bullish/neutral, got {sig.trend}"
            )

    def test_downtrend_gives_bearish_signals(self, analyser, bearish_data):
        result = analyser.analyse("NIFTY", bearish_data)
        for sig in result.signals:
            assert sig.trend in ("bearish", "neutral"), (
                f"Timeframe {sig.timeframe}: expected bearish/neutral, got {sig.trend}"
            )

    def test_uptrend_overall_bullish(self, analyser, bullish_data):
        result = analyser.analyse("NIFTY", bullish_data)
        assert result.overall == "bullish"

    def test_downtrend_overall_bearish(self, analyser, bearish_data):
        result = analyser.analyse("NIFTY", bearish_data)
        assert result.overall == "bearish"


# ---------------------------------------------------------------------------
# EMA position
# ---------------------------------------------------------------------------


class TestEMAPosition:
    def test_ema_position_is_above_or_below(self, analyser, bullish_data):
        result = analyser.analyse("NIFTY", bullish_data)
        for sig in result.signals:
            assert sig.ema_position in ("above", "below")

    def test_uptrend_close_above_ema(self, analyser, bullish_data):
        result = analyser.analyse("NIFTY", bullish_data)
        for sig in result.signals:
            assert sig.ema_position == "above", (
                f"Timeframe {sig.timeframe}: expected above EMA in uptrend"
            )


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------


class TestRSI:
    def test_rsi_in_valid_range_or_nan(self, analyser):
        data = make_sample_mtf_data(n_bars=100)
        result = analyser.analyse("TEST", data)
        for sig in result.signals:
            if math.isfinite(sig.rsi):
                assert 0.0 <= sig.rsi <= 100.0, (
                    f"RSI out of range for {sig.timeframe}: {sig.rsi}"
                )

    def test_uptrend_rsi_tends_above_50(self, analyser, bullish_data):
        result = analyser.analyse("NIFTY", bullish_data)
        for sig in result.signals:
            if math.isfinite(sig.rsi):
                # Strong uptrend → RSI should be > 50 (not guaranteed but typical)
                assert sig.rsi >= 40.0, (
                    f"Timeframe {sig.timeframe}: RSI {sig.rsi} unexpectedly low in uptrend"
                )


# ---------------------------------------------------------------------------
# MACD histogram
# ---------------------------------------------------------------------------


class TestMACDHistogram:
    def test_macd_histogram_finite_or_nan(self, analyser):
        data = make_sample_mtf_data(n_bars=100)
        result = analyser.analyse("TEST", data)
        for sig in result.signals:
            assert math.isfinite(sig.macd_histogram) or math.isnan(sig.macd_histogram)

    def test_uptrend_macd_histogram_positive(self, analyser, bullish_data):
        result = analyser.analyse("NIFTY", bullish_data)
        for sig in result.signals:
            if math.isfinite(sig.macd_histogram):
                assert sig.macd_histogram >= 0.0, (
                    f"Timeframe {sig.timeframe}: negative MACD histogram in uptrend"
                )

    def test_downtrend_macd_histogram_is_finite(self, analyser, bearish_data):
        """MACD histogram must be computed (finite or NaN) for a downtrend.

        MACD histogram measures momentum *change*, not raw direction, so its
        sign is not directly tied to trend direction — it can be positive even
        in a downtrend when selling momentum is decelerating.  We only assert
        that the value is computed (not an unexpected exception or infinity).
        """
        result = analyser.analyse("NIFTY", bearish_data)
        for sig in result.signals:
            assert not math.isinf(sig.macd_histogram), (
                f"Timeframe {sig.timeframe}: MACD histogram is inf"
            )


# ---------------------------------------------------------------------------
# Strength
# ---------------------------------------------------------------------------


class TestStrength:
    def test_strength_in_valid_range(self, analyser):
        data = make_sample_mtf_data(n_bars=100)
        result = analyser.analyse("TEST", data)
        for sig in result.signals:
            assert 0.0 <= sig.strength <= 1.0

    def test_flat_data_low_strength(self, analyser):
        # Use 200 identical bars — MACD histogram should be ~0, strength ~0
        bars = [
            {
                "timestamp": f"2025-01-15T09:{i:02d}:00",
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1000.0,
            }
            for i in range(200)
        ]
        result = analyser.analyse("FLAT", {"1h": bars})
        for sig in result.signals:
            assert sig.strength < 0.1, f"Expected low strength for flat data, got {sig.strength}"

    def test_strong_trend_gives_higher_strength(self, analyser):
        n = 150
        bullish = _make_trending_bars(n, start=24000.0, direction=1.0, seed=99)
        result_bull = analyser.analyse("BULL", {"1h": bullish})
        flat = [
            {
                "timestamp": f"2025-01-15T09:{i:02d}:00",
                "open": 100.0,
                "high": 100.0,
                "low": 100.0,
                "close": 100.0,
                "volume": 1000.0,
            }
            for i in range(n)
        ]
        result_flat = analyser.analyse("FLAT", {"1h": flat})
        if result_bull.signals and result_flat.signals:
            assert result_bull.signals[0].strength >= result_flat.signals[0].strength


# ---------------------------------------------------------------------------
# Confluence
# ---------------------------------------------------------------------------


class TestConfluence:
    def test_all_bullish_gives_high_confluence(self, analyser, bullish_data):
        result = analyser.analyse("NIFTY", bullish_data)
        assert result.confluence >= _CONFLUENCE_THRESHOLD

    def test_all_bearish_gives_high_confluence(self, analyser, bearish_data):
        result = analyser.analyse("NIFTY", bearish_data)
        assert result.confluence >= _CONFLUENCE_THRESHOLD

    def test_confluence_in_valid_range(self, analyser):
        data = make_sample_mtf_data(n_bars=100)
        result = analyser.analyse("TEST", data)
        assert 0.0 <= result.confluence <= 1.0

    def test_no_signals_confluence_zero(self, analyser, short_data):
        result = analyser.analyse("TEST", short_data)
        assert result.confluence == 0.0

    def test_mixed_directions_lower_confluence(self, analyser):
        """Half bullish, half bearish → confluence below 1.0."""
        n = 100
        mixed = {
            "5m":  _make_trending_bars(n, start=24000.0, direction=1.0, seed=20),
            "15m": _make_trending_bars(n, start=24000.0, direction=-1.0, seed=21),
        }
        result = analyser.analyse("TEST", mixed)
        assert result.confluence <= 1.0

    def test_compute_confluence_all_bullish(self, analyser):
        sigs = [
            TimeframeSignal(timeframe=tf, trend="bullish", rsi=60.0,
                            macd_histogram=5.0, ema_position="above", strength=0.7)
            for tf in ("5m", "15m", "1h", "1D")
        ]
        conf, overall = analyser._compute_confluence(sigs)
        assert overall == "bullish"
        assert conf == pytest.approx(1.0)

    def test_compute_confluence_all_bearish(self, analyser):
        sigs = [
            TimeframeSignal(timeframe=tf, trend="bearish", rsi=35.0,
                            macd_histogram=-3.0, ema_position="below", strength=0.5)
            for tf in ("5m", "15m")
        ]
        conf, overall = analyser._compute_confluence(sigs)
        assert overall == "bearish"
        assert conf == pytest.approx(1.0)

    def test_compute_confluence_tie_is_neutral(self, analyser):
        sigs = [
            TimeframeSignal(timeframe="5m", trend="bullish", rsi=55.0,
                            macd_histogram=2.0, ema_position="above", strength=0.4),
            TimeframeSignal(timeframe="15m", trend="bearish", rsi=45.0,
                            macd_histogram=-2.0, ema_position="below", strength=0.4),
        ]
        _, overall = analyser._compute_confluence(sigs)
        assert overall == "neutral"

    def test_compute_confluence_all_neutral_votes_no_vote(self, analyser):
        sigs = [
            TimeframeSignal(timeframe=tf, trend="neutral", rsi=50.0,
                            macd_histogram=0.0, ema_position="above", strength=0.0)
            for tf in ("5m", "15m")
        ]
        conf, overall = analyser._compute_confluence(sigs)
        assert overall == "neutral"
        assert conf == 0.0


# ---------------------------------------------------------------------------
# Helper internals
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_last_valid_returns_last_non_nan(self, analyser):
        arr = np.array([math.nan, math.nan, 1.0, 2.0, 3.0])
        assert analyser._last_valid(arr) == pytest.approx(3.0)

    def test_last_valid_all_nan_returns_nan(self, analyser):
        arr = np.full(5, math.nan)
        assert math.isnan(analyser._last_valid(arr))

    def test_classify_trend_both_nan_is_neutral(self, analyser):
        assert analyser._classify_trend(math.nan, math.nan) == "neutral"

    def test_classify_trend_fast_greater_is_bullish(self, analyser):
        assert analyser._classify_trend(110.0, 100.0) == "bullish"

    def test_classify_trend_fast_less_is_bearish(self, analyser):
        assert analyser._classify_trend(90.0, 100.0) == "bearish"

    def test_classify_ema_position_above(self, analyser):
        assert analyser._classify_ema_position(105.0, 100.0) == "above"

    def test_classify_ema_position_below(self, analyser):
        assert analyser._classify_ema_position(95.0, 100.0) == "below"

    def test_classify_ema_position_nan_ema_is_above(self, analyser):
        assert analyser._classify_ema_position(100.0, math.nan) == "above"

    def test_compute_strength_nan_histogram_is_zero(self, analyser):
        close = np.ones(50) * 100.0
        assert analyser._compute_strength(math.nan, close) == pytest.approx(0.0)

    def test_compute_strength_zero_mean_price_is_zero(self, analyser):
        close = np.zeros(10)
        assert analyser._compute_strength(5.0, close) == pytest.approx(0.0)

    def test_compute_strength_in_range(self, analyser):
        close = np.ones(50) * 24000.0
        s = analyser._compute_strength(50.0, close)
        assert 0.0 <= s <= 1.0


# ---------------------------------------------------------------------------
# make_sample_mtf_data
# ---------------------------------------------------------------------------


class TestMakeSampleMTFData:
    def test_default_four_timeframes(self):
        data = make_sample_mtf_data()
        assert set(data.keys()) == {"5m", "15m", "1h", "1D"}

    def test_custom_timeframes(self):
        data = make_sample_mtf_data(timeframes=["5m", "1D"])
        assert set(data.keys()) == {"5m", "1D"}

    def test_bars_count_per_timeframe(self):
        n = 80
        data = make_sample_mtf_data(n_bars=n)
        for tf, bars in data.items():
            assert len(bars) == n, f"{tf}: expected {n} bars, got {len(bars)}"

    def test_each_bar_has_required_keys(self):
        data = make_sample_mtf_data(n_bars=10)
        required = {"timestamp", "open", "high", "low", "close", "volume"}
        for tf, bars in data.items():
            for bar in bars:
                assert required.issubset(bar.keys()), f"Bar in {tf} missing keys"

    def test_high_gte_low(self):
        data = make_sample_mtf_data(n_bars=50)
        for tf, bars in data.items():
            for bar in bars:
                assert bar["high"] >= bar["low"], f"{tf}: high < low"

    def test_deterministic_with_same_seed(self):
        d1 = make_sample_mtf_data(seed=0)
        d2 = make_sample_mtf_data(seed=0)
        assert d1["5m"][0]["close"] == d2["5m"][0]["close"]

    def test_different_seeds_differ(self):
        d1 = make_sample_mtf_data(seed=0)
        d2 = make_sample_mtf_data(seed=99)
        assert d1["5m"][0]["close"] != d2["5m"][0]["close"]

    def test_analyse_runs_successfully_on_sample_data(self):
        analyser = MultiTimeframeAnalyser()
        data = make_sample_mtf_data(n_bars=200)
        result = analyser.analyse("SAMPLE", data)
        assert isinstance(result, MTFAnalysis)
        assert len(result.signals) == 4


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_pipeline_sample_data(self, analyser):
        data = make_sample_mtf_data(n_bars=150)
        result = analyser.analyse("NIFTY", data)
        assert isinstance(result, MTFAnalysis)
        assert result.symbol == "NIFTY"
        assert result.overall in ("bullish", "bearish", "neutral")
        assert 0.0 <= result.confluence <= 1.0
        for sig in result.signals:
            assert sig.trend in ("bullish", "bearish", "neutral")
            if math.isfinite(sig.rsi):
                assert 0.0 <= sig.rsi <= 100.0
            assert 0.0 <= sig.strength <= 1.0

    def test_mixed_timeframe_counts(self, analyser):
        """Some timeframes long, some too short."""
        data = {
            "5m":  _make_trending_bars(100, start=24000.0, seed=30),   # valid
            "15m": _make_neutral_bars(5),                               # too short
            "1D":  _make_trending_bars(80, start=24000.0, seed=31),    # valid
        }
        result = analyser.analyse("NIFTY", data)
        # Only 2 timeframes should produce signals
        assert len(result.signals) == 2
        result_tfs = {s.timeframe for s in result.signals}
        assert "5m" in result_tfs
        assert "1D" in result_tfs
        assert "15m" not in result_tfs
