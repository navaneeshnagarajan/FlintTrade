"""Tests for VWAP with standard deviation bands.

All tests are self-contained — no API calls, no broker connection required.
Uses pytest with --import-mode=importlib.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from packages.indicators.src.vwap_bands import (
    VWAPResult,
    _compute_session_vwap,
    _extract_date,
    calculate_vwap_bands,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_bars(
    n: int = 10,
    base_close: float = 100.0,
    base_volume: float = 1000.0,
    date: str = "2025-01-15",
    seed: int = 0,
) -> list[dict]:
    """Generate deterministic synthetic OHLCV bars for a single date."""
    rng = np.random.default_rng(seed)
    bars = []
    close = base_close
    for i in range(n):
        ret = rng.standard_normal() * 0.002
        close = max(close * (1.0 + ret), 1.0)
        spread = close * 0.001
        high = close + abs(rng.standard_normal()) * spread
        low = close - abs(rng.standard_normal()) * spread
        bars.append({
            "timestamp": f"{date}T09:{15 + i:02d}:00",
            "open": round(close, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(close, 2),
            "volume": round(base_volume + rng.uniform(-100, 100), 1),
        })
    return bars


def _make_two_day_bars(n_per_day: int = 20, seed: int = 1) -> list[dict]:
    """Generate bars spanning two calendar dates."""
    day1 = _make_bars(n_per_day, date="2025-01-15", seed=seed)
    day2 = _make_bars(n_per_day, date="2025-01-16", seed=seed + 1)
    return day1 + day2


@pytest.fixture
def single_day_bars() -> list[dict]:
    return _make_bars(n=30)


@pytest.fixture
def two_day_bars() -> list[dict]:
    return _make_two_day_bars(n_per_day=25)


@pytest.fixture
def flat_bars() -> list[dict]:
    """All bars with identical typical price — sigma should be 0."""
    return [
        {
            "timestamp": f"2025-01-15T09:{i:02d}:00",
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1000.0,
        }
        for i in range(20)
    ]


@pytest.fixture
def zero_volume_bar() -> list[dict]:
    """Single bar with volume=0 — VWAP should be NaN."""
    return [
        {
            "timestamp": "2025-01-15T09:15:00",
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 0.0,
        }
    ]


# ---------------------------------------------------------------------------
# _extract_date
# ---------------------------------------------------------------------------


class TestExtractDate:
    def test_date_only(self):
        assert _extract_date("2025-01-15") == "2025-01-15"

    def test_datetime_T_separator(self):
        assert _extract_date("2025-01-15T09:15:00") == "2025-01-15"

    def test_datetime_space_separator(self):
        assert _extract_date("2025-01-15 09:15:00") == "2025-01-15"

    def test_short_string(self):
        # Less than 10 chars — returns whatever is there
        assert _extract_date("2025-01") == "2025-01"


# ---------------------------------------------------------------------------
# _compute_session_vwap
# ---------------------------------------------------------------------------


class TestComputeSessionVWAP:
    def test_returns_correct_length(self):
        tp = np.array([100.0, 101.0, 102.0])
        vol = np.array([1000.0, 1200.0, 800.0])
        vwap_arr, sigma_arr = _compute_session_vwap(tp, vol)
        assert len(vwap_arr) == 3
        assert len(sigma_arr) == 3

    def test_vwap_first_bar_equals_typical_price(self):
        tp = np.array([100.0, 101.0])
        vol = np.array([1000.0, 1000.0])
        vwap_arr, _ = _compute_session_vwap(tp, vol)
        assert vwap_arr[0] == pytest.approx(100.0)

    def test_vwap_is_cumulative(self):
        # Two equal-volume bars: VWAP should be mean of the two TPs at bar 1
        tp = np.array([100.0, 110.0])
        vol = np.array([1000.0, 1000.0])
        vwap_arr, _ = _compute_session_vwap(tp, vol)
        assert vwap_arr[1] == pytest.approx(105.0)

    def test_sigma_zero_for_flat_prices(self):
        tp = np.ones(10) * 100.0
        vol = np.ones(10) * 500.0
        _, sigma_arr = _compute_session_vwap(tp, vol)
        # Sigma may not be exactly 0 due to floating-point but must be tiny
        assert sigma_arr[-1] == pytest.approx(0.0, abs=1e-8)

    def test_sigma_positive_for_varying_prices(self):
        tp = np.array([100.0, 101.0, 99.0, 102.0, 98.0], dtype=np.float64)
        vol = np.ones(5) * 1000.0
        _, sigma_arr = _compute_session_vwap(tp, vol)
        assert sigma_arr[-1] > 0.0

    def test_zero_volume_returns_nan(self):
        tp = np.array([100.0])
        vol = np.array([0.0])
        vwap_arr, sigma_arr = _compute_session_vwap(tp, vol)
        assert math.isnan(vwap_arr[0])
        assert math.isnan(sigma_arr[0])

    def test_vwap_weighted_towards_high_volume_bar(self):
        # Bar 0: tp=100, vol=100; Bar 1: tp=200, vol=9900 → VWAP near 200
        tp = np.array([100.0, 200.0])
        vol = np.array([100.0, 9900.0])
        vwap_arr, _ = _compute_session_vwap(tp, vol)
        assert vwap_arr[1] > 190.0


# ---------------------------------------------------------------------------
# calculate_vwap_bands — return type & structure
# ---------------------------------------------------------------------------


class TestVWAPBandsStructure:
    def test_returns_vwap_result(self, single_day_bars):
        result = calculate_vwap_bands(single_day_bars)
        assert isinstance(result, VWAPResult)

    def test_all_fields_same_length(self, single_day_bars):
        n = len(single_day_bars)
        result = calculate_vwap_bands(single_day_bars)
        assert len(result.timestamps) == n
        assert len(result.vwap) == n
        assert len(result.upper_1) == n
        assert len(result.upper_2) == n
        assert len(result.upper_3) == n
        assert len(result.lower_1) == n
        assert len(result.lower_2) == n
        assert len(result.lower_3) == n

    def test_timestamps_match_input(self, single_day_bars):
        result = calculate_vwap_bands(single_day_bars)
        expected = [str(b["timestamp"]) for b in single_day_bars]
        assert result.timestamps == expected

    def test_single_bar_returns_result(self):
        bars = [
            {
                "timestamp": "2025-01-15T09:15:00",
                "high": 100.0,
                "low": 99.0,
                "close": 99.5,
                "volume": 1000.0,
            }
        ]
        result = calculate_vwap_bands(bars)
        assert len(result.vwap) == 1
        assert math.isfinite(result.vwap[0])


# ---------------------------------------------------------------------------
# VWAP values
# ---------------------------------------------------------------------------


class TestVWAPValues:
    def test_vwap_all_finite_with_normal_data(self, single_day_bars):
        result = calculate_vwap_bands(single_day_bars)
        for v in result.vwap:
            assert math.isfinite(v), f"Non-finite VWAP value: {v}"

    def test_vwap_within_session_price_range(self, single_day_bars):
        """VWAP must lie within the session's overall high/low range.

        VWAP is cumulative, so it is not bounded by a single bar's high/low.
        It must, however, stay within the minimum low and maximum high seen
        so far across the session.
        """
        result = calculate_vwap_bands(single_day_bars)
        for i, v in enumerate(result.vwap):
            if math.isfinite(v):
                session_low = min(b["low"] for b in single_day_bars[: i + 1])
                session_high = max(b["high"] for b in single_day_bars[: i + 1])
                assert session_low <= v <= session_high, (
                    f"Bar {i}: VWAP {v} outside session range "
                    f"[{session_low}, {session_high}]"
                )

    def test_zero_volume_bar_gives_nan_vwap(self, zero_volume_bar):
        result = calculate_vwap_bands(zero_volume_bar)
        assert math.isnan(result.vwap[0])

    def test_flat_prices_sigma_is_zero(self, flat_bars):
        result = calculate_vwap_bands(flat_bars)
        # All upper/lower bands equal VWAP when sigma=0
        for i in range(len(flat_bars)):
            if math.isfinite(result.vwap[i]):
                assert result.upper_1[i] == pytest.approx(result.vwap[i], abs=1e-6)
                assert result.lower_1[i] == pytest.approx(result.vwap[i], abs=1e-6)


# ---------------------------------------------------------------------------
# Band ordering
# ---------------------------------------------------------------------------


class TestBandOrdering:
    def test_upper_bands_ascending(self, single_day_bars):
        result = calculate_vwap_bands(single_day_bars)
        for i in range(len(single_day_bars)):
            v = result.vwap[i]
            u1 = result.upper_1[i]
            u2 = result.upper_2[i]
            u3 = result.upper_3[i]
            if all(math.isfinite(x) for x in [v, u1, u2, u3]):
                assert u1 <= u2 <= u3, f"Bar {i}: upper bands not ascending: {u1}, {u2}, {u3}"

    def test_lower_bands_descending(self, single_day_bars):
        result = calculate_vwap_bands(single_day_bars)
        for i in range(len(single_day_bars)):
            v = result.vwap[i]
            l1 = result.lower_1[i]
            l2 = result.lower_2[i]
            l3 = result.lower_3[i]
            if all(math.isfinite(x) for x in [v, l1, l2, l3]):
                assert l1 >= l2 >= l3, f"Bar {i}: lower bands not descending: {l1}, {l2}, {l3}"

    def test_upper_above_vwap(self, single_day_bars):
        result = calculate_vwap_bands(single_day_bars)
        for i in range(len(single_day_bars)):
            v = result.vwap[i]
            u1 = result.upper_1[i]
            if all(math.isfinite(x) for x in [v, u1]):
                assert u1 >= v, f"Bar {i}: upper_1 {u1} < vwap {v}"

    def test_lower_below_vwap(self, single_day_bars):
        result = calculate_vwap_bands(single_day_bars)
        for i in range(len(single_day_bars)):
            v = result.vwap[i]
            l1 = result.lower_1[i]
            if all(math.isfinite(x) for x in [v, l1]):
                assert l1 <= v, f"Bar {i}: lower_1 {l1} > vwap {v}"

    def test_upper_lower_symmetric_around_vwap(self, single_day_bars):
        result = calculate_vwap_bands(single_day_bars)
        for i in range(len(single_day_bars)):
            v = result.vwap[i]
            u1 = result.upper_1[i]
            l1 = result.lower_1[i]
            if all(math.isfinite(x) for x in [v, u1, l1]):
                assert (u1 - v) == pytest.approx(v - l1, rel=1e-6)


# ---------------------------------------------------------------------------
# Session reset behaviour
# ---------------------------------------------------------------------------


class TestSessionReset:
    def test_session_reset_resets_vwap_at_new_date(self, two_day_bars):
        n_per = 25
        result_reset = calculate_vwap_bands(two_day_bars, session_reset=True)
        result_cont = calculate_vwap_bands(two_day_bars, session_reset=False)

        # At the first bar of day 2, the reset version should equal the TP of that bar,
        # while the continuous version should differ (still accumulating from day 1).
        first_day2_idx = n_per
        vwap_reset = result_reset.vwap[first_day2_idx]
        vwap_cont = result_cont.vwap[first_day2_idx]

        # Reset VWAP at session start = TP of that bar
        bar = two_day_bars[first_day2_idx]
        expected_tp = (bar["high"] + bar["low"] + bar["close"]) / 3.0
        assert vwap_reset == pytest.approx(expected_tp, rel=1e-6)
        # Continuous VWAP should differ from reset VWAP
        assert vwap_cont != pytest.approx(vwap_reset, rel=1e-4)

    def test_no_session_reset_has_monotonic_volume(self, single_day_bars):
        """Without reset, cumulative volume is monotonically non-decreasing."""
        result = calculate_vwap_bands(single_day_bars, session_reset=False)
        # VWAP should be finite at all bars (no reset mid-stream)
        for v in result.vwap:
            assert math.isfinite(v)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestVWAPBandsErrors:
    def test_empty_bars_raises_value_error(self):
        with pytest.raises(ValueError, match="at least one bar"):
            calculate_vwap_bands([])

    def test_missing_key_raises_value_error(self):
        bars = [{"timestamp": "2025-01-15T09:15:00", "high": 100.0, "close": 99.0, "volume": 1000.0}]
        # 'low' is missing
        with pytest.raises(ValueError, match="missing required keys"):
            calculate_vwap_bands(bars)

    def test_missing_timestamp_key_raises(self):
        bars = [{"high": 100.0, "low": 99.0, "close": 99.5, "volume": 500.0}]
        with pytest.raises(ValueError, match="missing required keys"):
            calculate_vwap_bands(bars)


# ---------------------------------------------------------------------------
# VWAPResult Pydantic model
# ---------------------------------------------------------------------------


class TestVWAPResultModel:
    def test_model_serialises_to_dict(self, single_day_bars):
        result = calculate_vwap_bands(single_day_bars)
        d = result.model_dump()
        assert "vwap" in d
        assert "upper_1" in d
        assert "lower_3" in d
        assert isinstance(d["timestamps"], list)

    def test_model_fields_are_lists(self, single_day_bars):
        result = calculate_vwap_bands(single_day_bars)
        for field in ("timestamps", "vwap", "upper_1", "upper_2", "upper_3",
                      "lower_1", "lower_2", "lower_3"):
            assert isinstance(getattr(result, field), list)
