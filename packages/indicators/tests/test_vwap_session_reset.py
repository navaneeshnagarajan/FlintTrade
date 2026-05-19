"""Tests for VWAP session reset functionality.

Verifies that the ``session_reset_times`` parameter correctly resets cumulative
price*volume and volume accumulators at each session boundary.

All tests are self-contained — no API calls, no broker required.
Run with: python -m pytest packages/indicators/tests/test_vwap_session_reset.py -v --import-mode=importlib
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from packages.indicators.src.trend import vwap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_uniform_bars(
    n: int,
    price: float = 100.0,
    volume: float = 1000.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (high, low, close, volume) arrays with uniform values."""
    h = np.full(n, price + 1.0, dtype=np.float64)
    lo = np.full(n, price - 1.0, dtype=np.float64)
    c = np.full(n, price, dtype=np.float64)
    v = np.full(n, volume, dtype=np.float64)
    return h, lo, c, v


# ---------------------------------------------------------------------------
# Basic behaviour (no timestamps) — backward compatibility
# ---------------------------------------------------------------------------


class TestVwapBackwardCompatibility:
    def test_no_timestamps_returns_cumulative_vwap(self):
        """Without timestamps, VWAP must behave exactly as before."""
        h, lo, c, v = _make_uniform_bars(5, price=100.0, volume=1000.0)
        result = vwap(h, lo, c, v)

        assert result.shape == (5,)
        assert not np.any(np.isnan(result))
        # Uniform price → VWAP should equal price at every bar
        np.testing.assert_allclose(result, 100.0)

    def test_no_timestamps_shape_matches_input(self):
        h, lo, c, v = _make_uniform_bars(20)
        result = vwap(h, lo, c, v)
        assert result.shape == (20,)

    def test_no_timestamps_zero_volume_gives_nan(self):
        h, lo, c, v = _make_uniform_bars(3, volume=0.0)
        result = vwap(h, lo, c, v)
        assert np.all(np.isnan(result))

    def test_no_timestamps_known_numeric(self):
        """Manual two-bar VWAP calculation."""
        h = np.array([110.0, 120.0], dtype=np.float64)
        lo = np.array([90.0, 80.0], dtype=np.float64)
        c = np.array([100.0, 100.0], dtype=np.float64)
        v = np.array([1000.0, 2000.0], dtype=np.float64)
        # TP: [100, 100], cum_tp_vol: [100000, 300000], cum_vol: [1000, 3000]
        # VWAP: [100, 100]
        result = vwap(h, lo, c, v)
        np.testing.assert_allclose(result, [100.0, 100.0])


# ---------------------------------------------------------------------------
# Session reset — single session boundary
# ---------------------------------------------------------------------------


class TestVwapSessionResetSingleBoundary:
    def test_reset_at_0915_resets_accumulator(self):
        """VWAP must restart accumulation when bar timestamp matches 09:15."""
        # 4 bars: 09:00, 09:05, 09:10, 09:15 (session start on last bar)
        h = np.array([105.0, 105.0, 105.0, 200.0], dtype=np.float64)
        lo = np.array([95.0, 95.0, 95.0, 190.0], dtype=np.float64)
        c = np.array([100.0, 100.0, 100.0, 195.0], dtype=np.float64)
        v = np.array([1000.0, 1000.0, 1000.0, 1000.0], dtype=np.float64)
        timestamps = ["09:00", "09:05", "09:10", "09:15"]

        result = vwap(h, lo, c, v, timestamps=timestamps, session_reset_times=["09:15"])

        # Bars 0-2: cumulative VWAP at price 100
        np.testing.assert_allclose(result[:3], 100.0)
        # Bar 3: accumulator was reset — VWAP must equal bar-3 TP only
        expected_tp_bar3 = (200.0 + 190.0 + 195.0) / 3.0
        np.testing.assert_allclose(result[3], expected_tp_bar3)

    def test_reset_on_clock_rollback(self):
        """Clock going backwards (new calendar day) must reset accumulator."""
        h = np.array([105.0, 105.0, 105.0, 105.0], dtype=np.float64)
        lo = np.array([95.0, 95.0, 95.0, 95.0], dtype=np.float64)
        c = np.array([100.0, 100.0, 100.0, 100.0], dtype=np.float64)
        v = np.array([1000.0, 2000.0, 3000.0, 500.0], dtype=np.float64)
        # Last bar is 09:15 on the next day (clock goes back from 15:30)
        timestamps = [
            "2025-01-10 09:30",
            "2025-01-10 12:00",
            "2025-01-10 15:30",
            "2025-01-11 09:15",  # new day — should reset
        ]
        result = vwap(h, lo, c, v, timestamps=timestamps, session_reset_times=["09:15"])

        # Bar 3 is on a new day AND matches 09:15 — full reset
        tp = 100.0  # (105 + 95 + 100) / 3
        assert not math.isnan(result[3])
        np.testing.assert_allclose(result[3], tp)

    def test_no_reset_between_boundaries(self):
        """Bars between resets must use the running cumulative average."""
        h = np.full(3, 105.0)
        lo = np.full(3, 95.0)
        c = np.full(3, 100.0)
        v = np.array([1000.0, 1000.0, 1000.0], dtype=np.float64)
        timestamps = ["09:20", "09:25", "09:30"]

        result = vwap(h, lo, c, v, timestamps=timestamps, session_reset_times=["09:15"])
        # No reset in this range — cumulative VWAP at uniform price = 100
        np.testing.assert_allclose(result, 100.0)


# ---------------------------------------------------------------------------
# Session reset — multiple sessions in one array
# ---------------------------------------------------------------------------


class TestVwapMultipleSessions:
    def test_two_sessions_independent_vwap(self):
        """VWAP for session 2 must not be affected by session 1 data."""
        # Session 1: bars at 09:15, 09:30 with price=100
        # Session 2: bars at 09:15, 09:30 (next day) with price=200
        h = np.array([105.0, 105.0, 205.0, 205.0], dtype=np.float64)
        lo = np.array([95.0, 95.0, 195.0, 195.0], dtype=np.float64)
        c = np.array([100.0, 100.0, 200.0, 200.0], dtype=np.float64)
        v = np.array([1000.0, 1000.0, 1000.0, 1000.0], dtype=np.float64)
        timestamps = ["09:15", "09:30", "09:15", "09:30"]

        result = vwap(h, lo, c, v, timestamps=timestamps, session_reset_times=["09:15"])

        # Session 1
        np.testing.assert_allclose(result[0], 100.0)
        np.testing.assert_allclose(result[1], 100.0)
        # Session 2 — must start fresh at 200, not bleed session 1
        np.testing.assert_allclose(result[2], 200.0)
        np.testing.assert_allclose(result[3], 200.0)

    def test_custom_reset_time(self):
        """Custom session_reset_times parameter must be respected."""
        h = np.array([105.0, 105.0, 205.0, 205.0], dtype=np.float64)
        lo = np.array([95.0, 95.0, 195.0, 195.0], dtype=np.float64)
        c = np.array([100.0, 100.0, 200.0, 200.0], dtype=np.float64)
        v = np.full(4, 1000.0, dtype=np.float64)
        # Commodity session starts at 09:00
        timestamps = ["09:00", "09:05", "09:00", "09:05"]

        result = vwap(h, lo, c, v, timestamps=timestamps, session_reset_times=["09:00"])

        np.testing.assert_allclose(result[0], 100.0)
        np.testing.assert_allclose(result[2], 200.0)

    def test_multiple_reset_times(self):
        """Multiple reset times (e.g. morning + afternoon sessions)."""
        h = np.full(6, 105.0)
        lo = np.full(6, 95.0)
        c = np.full(6, 100.0)
        v = np.full(6, 1000.0)
        timestamps = ["09:15", "10:00", "12:00", "13:00", "14:00", "09:15"]

        result = vwap(h, lo, c, v, timestamps=timestamps, session_reset_times=["09:15", "13:00"])

        # Bar 3 (13:00) resets → single-bar VWAP = TP = 100
        np.testing.assert_allclose(result[3], 100.0)
        # Bar 5 (09:15 again, clock rollback) resets → single-bar VWAP = 100
        np.testing.assert_allclose(result[5], 100.0)


# ---------------------------------------------------------------------------
# Timestamp format flexibility
# ---------------------------------------------------------------------------


class TestVwapTimestampFormats:
    def _run_single_reset(self, timestamps: list[str]) -> np.ndarray:
        h = np.array([105.0, 205.0], dtype=np.float64)
        lo = np.array([95.0, 195.0], dtype=np.float64)
        c = np.array([100.0, 200.0], dtype=np.float64)
        v = np.array([1000.0, 1000.0], dtype=np.float64)
        return vwap(h, lo, c, v, timestamps=timestamps, session_reset_times=["09:15"])

    def test_hhmm_format(self):
        result = self._run_single_reset(["09:00", "09:15"])
        np.testing.assert_allclose(result[1], 200.0)

    def test_hhmmss_format(self):
        result = self._run_single_reset(["09:00:00", "09:15:00"])
        np.testing.assert_allclose(result[1], 200.0)

    def test_date_space_time_format(self):
        result = self._run_single_reset(["2025-01-10 09:00", "2025-01-10 09:15"])
        np.testing.assert_allclose(result[1], 200.0)

    def test_iso8601_format(self):
        result = self._run_single_reset(["2025-01-10T09:00:00", "2025-01-10T09:15:00"])
        np.testing.assert_allclose(result[1], 200.0)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestVwapErrorHandling:
    def test_timestamps_length_mismatch_raises(self):
        h, lo, c, v = _make_uniform_bars(3)
        with pytest.raises(ValueError, match="timestamps length"):
            vwap(h, lo, c, v, timestamps=["09:15", "09:30"])  # only 2, need 3

    def test_empty_session_reset_times_no_resets(self):
        """Empty session_reset_times list means no explicit resets — only clock rollback."""
        h = np.full(3, 105.0)
        lo = np.full(3, 95.0)
        c = np.full(3, 100.0)
        v = np.full(3, 1000.0)
        # All on the same day, nothing matches empty list → no reset
        timestamps = ["09:15", "09:30", "09:45"]
        result = vwap(h, lo, c, v, timestamps=timestamps, session_reset_times=[])
        np.testing.assert_allclose(result, 100.0)
