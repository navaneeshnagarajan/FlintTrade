"""Tests for candlestick pattern detection (W4).

Pure, offline detection over hand-crafted bars.
"""

from __future__ import annotations

from flinttrade_screener.candlestick_patterns import (
    PatternScanResult,
    detect_patterns,
    make_sample_pattern_scan,
)


def _patterns(bars):
    return {m.pattern for m in detect_patterns(bars).matches}


class TestSingleBarPatterns:
    def test_doji_detected(self):
        bars = [{"open": 100, "high": 101, "low": 99, "close": 100.02}]
        assert "doji" in _patterns(bars)

    def test_hammer_detected(self):
        # Small body at top, long lower wick, negligible upper wick.
        bars = [{"open": 100.95, "high": 101.0, "low": 99.0, "close": 101.0}]
        assert "hammer" in _patterns(bars)

    def test_shooting_star_detected(self):
        # Small body at bottom, long upper wick, negligible lower wick.
        bars = [{"open": 100.05, "high": 102.0, "low": 100.0, "close": 100.0}]
        assert "shooting_star" in _patterns(bars)

    def test_strong_trend_bar_is_no_pattern(self):
        # Big body, no wicks → not a doji/hammer.
        bars = [{"open": 100, "high": 105, "low": 100, "close": 105}]
        assert _patterns(bars) == set()


class TestTwoBarPatterns:
    def test_bullish_engulfing(self):
        bars = [
            {"open": 100.5, "high": 101, "low": 99.5, "close": 99.8},  # bearish
            {"open": 99.5, "high": 102, "low": 99.4, "close": 101.8},  # bullish engulfs
        ]
        assert "bullish_engulfing" in _patterns(bars)

    def test_bearish_engulfing(self):
        bars = [
            {"open": 99.8, "high": 101, "low": 99.5, "close": 100.5},  # bullish
            {"open": 101.0, "high": 101.2, "low": 99.0, "close": 99.4},  # bearish engulfs
        ]
        assert "bearish_engulfing" in _patterns(bars)


class TestThreeBarPatterns:
    def test_morning_star(self):
        bars = [
            {"open": 105, "high": 105.5, "low": 100, "close": 100.5},  # big bearish
            {"open": 100.0, "high": 100.4, "low": 99.6, "close": 100.1},  # small star, gaps down
            {"open": 100.5, "high": 104.5, "low": 100.2, "close": 104.0},  # big bullish past midpoint
        ]
        assert "morning_star" in _patterns(bars)

    def test_evening_star(self):
        bars = [
            {"open": 100, "high": 105.5, "low": 99.5, "close": 105},  # big bullish
            {"open": 105.2, "high": 105.6, "low": 104.9, "close": 105.3},  # small star, gaps up
            {"open": 105.0, "high": 105.2, "low": 100.5, "close": 101.0},  # big bearish below midpoint
        ]
        assert "evening_star" in _patterns(bars)

    def test_three_white_soldiers(self):
        bars = [
            {"open": 100.0, "high": 101.05, "low": 99.95, "close": 101.0},
            {"open": 100.6, "high": 102.05, "low": 100.55, "close": 102.0},
            {"open": 101.6, "high": 103.05, "low": 101.55, "close": 103.0},
        ]
        assert "three_white_soldiers" in _patterns(bars)

    def test_three_black_crows(self):
        bars = [
            {"open": 103.0, "high": 103.05, "low": 101.95, "close": 102.0},
            {"open": 102.4, "high": 102.45, "low": 100.95, "close": 101.0},
            {"open": 101.4, "high": 101.45, "low": 99.95, "close": 100.0},
        ]
        assert "three_black_crows" in _patterns(bars)


class TestScanResult:
    def test_empty_bars(self):
        result = detect_patterns([])
        assert isinstance(result, PatternScanResult)
        assert result.bar_count == 0
        assert result.matches == []

    def test_match_carries_direction_and_index(self):
        bars = [{"time": "09:15", "open": 100, "high": 101, "low": 99, "close": 100.02}]
        match = detect_patterns(bars).matches[0]
        assert match.index == 0
        assert match.time == "09:15"
        assert match.direction in ("bullish", "bearish", "neutral")
        assert 0.0 <= match.strength <= 1.0

    def test_sample_scan_finds_multiple_patterns(self):
        result = make_sample_pattern_scan()
        assert result.bar_count == 8
        assert len(result.matches) >= 3

    def test_to_dict_json_serialisable(self):
        import json

        payload = make_sample_pattern_scan().to_dict()
        loaded = json.loads(json.dumps(payload))
        assert "matches" in loaded
        assert loaded["bar_count"] == 8
