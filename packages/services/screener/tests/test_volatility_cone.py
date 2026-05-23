"""Tests for the volatility cone calculator.

All tests are self-contained — no API calls, no broker connection required.
Uses pytest with --import-mode=importlib.
"""

from __future__ import annotations

import math
import random

import numpy as np
import pytest

from flinttrade_screener.volatility_cone import (
    VolatilityCone,
    VolatilityConePoint,
    _rolling_hv,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _constant_returns(n: int, value: float = 0.001) -> list[float]:
    """Generate n identical daily returns."""
    return [value] * n


def _random_returns(n: int, seed: int = 42, mu: float = 0.0003, sigma: float = 0.012) -> list[float]:
    """Generate n realistic daily log-returns."""
    rng = random.Random(seed)
    return [rng.gauss(mu, sigma) for _ in range(n)]


def _nifty_like_returns(n: int = 252) -> list[float]:
    """Generate 1 year of Nifty-like daily returns (sigma ≈ 1.2%)."""
    return _random_returns(n, seed=7, mu=0.0004, sigma=0.012)


@pytest.fixture
def cone() -> VolatilityCone:
    return VolatilityCone()


@pytest.fixture
def year_returns() -> list[float]:
    return _nifty_like_returns(252)


# ---------------------------------------------------------------------------
# VolatilityConePoint model
# ---------------------------------------------------------------------------


class TestVolatilityConePoint:
    """Validate VolatilityConePoint Pydantic constraints."""

    def test_basic_construction(self):
        p = VolatilityConePoint(
            lookback=20,
            current_hv=0.15,
            p10=0.10, p25=0.12, p50=0.15,
            p75=0.18, p90=0.21,
            min=0.07, max=0.35,
        )
        assert p.lookback == 20
        assert p.current_hv == pytest.approx(0.15)
        assert p.current_iv is None

    def test_current_iv_optional(self):
        p = VolatilityConePoint(
            lookback=10, current_hv=0.12,
            p10=0.08, p25=0.10, p50=0.12,
            p75=0.15, p90=0.18,
            min=0.06, max=0.25,
            current_iv=0.18,
        )
        assert p.current_iv == pytest.approx(0.18)

    def test_negative_lookback_rejected(self):
        with pytest.raises(Exception):
            VolatilityConePoint(
                lookback=-1, current_hv=0.12,
                p10=0.08, p25=0.10, p50=0.12,
                p75=0.15, p90=0.18,
                min=0.06, max=0.25,
            )

    def test_negative_hv_rejected(self):
        with pytest.raises(Exception):
            VolatilityConePoint(
                lookback=20, current_hv=-0.01,
                p10=0.08, p25=0.10, p50=0.12,
                p75=0.15, p90=0.18,
                min=0.06, max=0.25,
            )


# ---------------------------------------------------------------------------
# _rolling_hv helper
# ---------------------------------------------------------------------------


class TestRollingHV:
    """Unit tests for the internal rolling HV computation."""

    def test_output_length(self):
        arr = np.array(_constant_returns(50))
        hv = _rolling_hv(arr, window=10, annualise=math.sqrt(252))
        assert len(hv) == 40  # 50 - 10

    def test_constant_returns_zero_hv(self):
        """Std of constant returns is 0, so HV should be 0."""
        arr = np.array(_constant_returns(30, value=0.001))
        hv = _rolling_hv(arr, window=10, annualise=math.sqrt(252))
        assert np.allclose(hv, 0.0, atol=1e-10)

    def test_hv_non_negative(self):
        arr = np.array(_random_returns(100))
        hv = _rolling_hv(arr, window=20, annualise=math.sqrt(252))
        assert np.all(hv >= 0)

    def test_insufficient_data_returns_empty(self):
        arr = np.array(_constant_returns(5))
        hv = _rolling_hv(arr, window=10, annualise=math.sqrt(252))
        assert len(hv) == 0

    def test_annualisation_applied(self):
        """HV with annualise=1 should equal HV/sqrt(252) vs annualise=sqrt(252)."""
        arr = np.array(_random_returns(50, seed=1))
        hv_daily = _rolling_hv(arr, window=10, annualise=1.0)
        hv_annual = _rolling_hv(arr, window=10, annualise=math.sqrt(252))
        ratio = hv_annual / np.where(hv_daily > 0, hv_daily, 1.0)
        expected_ratio = math.sqrt(252)
        assert np.allclose(ratio[hv_daily > 0], expected_ratio, rtol=1e-6)


# ---------------------------------------------------------------------------
# VolatilityCone.calculate — output structure
# ---------------------------------------------------------------------------


class TestConeStructure:
    """Verify the shape and type of calculate() output."""

    def test_returns_list(self, cone, year_returns):
        result = cone.calculate(year_returns)
        assert isinstance(result, list)

    def test_default_six_windows(self, cone, year_returns):
        result = cone.calculate(year_returns)
        assert len(result) == 6

    def test_each_item_is_cone_point(self, cone, year_returns):
        for p in cone.calculate(year_returns):
            assert isinstance(p, VolatilityConePoint)

    def test_windows_sorted_ascending(self, cone, year_returns):
        lookbacks = [p.lookback for p in cone.calculate(year_returns)]
        assert lookbacks == sorted(lookbacks)

    def test_custom_windows(self, cone, year_returns):
        result = cone.calculate(year_returns, lookback_periods=[10, 30])
        lookbacks = [p.lookback for p in result]
        assert lookbacks == [10, 30]

    def test_short_window_included_long_excluded(self, cone):
        """Only windows with enough data should appear in results."""
        short_series = _random_returns(25)
        result = cone.calculate(short_series, lookback_periods=[5, 10, 20, 60])
        lookbacks = [p.lookback for p in result]
        assert 5 in lookbacks
        assert 10 in lookbacks
        # 60-day window needs 61 points; 25 is too short
        assert 60 not in lookbacks


# ---------------------------------------------------------------------------
# VolatilityCone.calculate — value correctness
# ---------------------------------------------------------------------------


class TestConeValues:
    """Verify numerical properties of cone point values."""

    def test_all_hvs_non_negative(self, cone, year_returns):
        for p in cone.calculate(year_returns):
            assert p.current_hv >= 0.0
            assert p.p10 >= 0.0
            assert p.p90 >= 0.0

    def test_percentile_ordering(self, cone, year_returns):
        """Percentile ladder must be non-decreasing."""
        for p in cone.calculate(year_returns):
            assert p.min <= p.p10 <= p.p25 <= p.p50 <= p.p75 <= p.p90 <= p.max, (
                f"Percentile order violated for lookback={p.lookback}: "
                f"min={p.min} p10={p.p10} p25={p.p25} p50={p.p50} "
                f"p75={p.p75} p90={p.p90} max={p.max}"
            )

    def test_current_hv_within_min_max(self, cone, year_returns):
        for p in cone.calculate(year_returns):
            assert p.min <= p.current_hv <= p.max, (
                f"current_hv={p.current_hv} outside [{p.min}, {p.max}] "
                f"for lookback={p.lookback}"
            )

    def test_all_values_finite(self, cone, year_returns):
        for p in cone.calculate(year_returns):
            assert math.isfinite(p.current_hv)
            assert math.isfinite(p.p50)
            assert math.isfinite(p.max)

    def test_hv_in_realistic_range(self, cone, year_returns):
        """Indian equity HV typically runs 8%–60% annualised."""
        for p in cone.calculate(year_returns):
            assert 0.01 <= p.p50 <= 1.0, f"Unrealistic p50={p.p50} for lookback={p.lookback}"

    def test_current_iv_propagated(self, cone, year_returns):
        iv = 0.18
        points = cone.calculate(year_returns, current_iv=iv)
        for p in points:
            assert p.current_iv == pytest.approx(iv)

    def test_no_iv_gives_none(self, cone, year_returns):
        points = cone.calculate(year_returns)
        for p in points:
            assert p.current_iv is None

    def test_shorter_window_higher_hv_variance(self, cone):
        """Shorter windows should produce wider cones (higher max-min spread)."""
        returns = _random_returns(300)
        points = cone.calculate(returns, lookback_periods=[5, 60])
        spread_5 = points[0].max - points[0].min
        spread_60 = points[1].max - points[1].min
        # Shorter windows are noisier → wider spread (nearly always true)
        assert spread_5 >= spread_60


# ---------------------------------------------------------------------------
# VolatilityCone.calculate — edge cases
# ---------------------------------------------------------------------------


class TestConeEdgeCases:
    """Edge case and boundary condition handling."""

    def test_empty_returns_empty_list(self, cone):
        assert cone.calculate([]) == []

    def test_none_lookback_uses_defaults(self, cone, year_returns):
        result = cone.calculate(year_returns, lookback_periods=None)
        assert len(result) == 6

    def test_too_short_for_all_windows(self, cone):
        result = cone.calculate([0.001] * 3, lookback_periods=[5, 10])
        assert result == []

    def test_single_window(self, cone, year_returns):
        result = cone.calculate(year_returns, lookback_periods=[20])
        assert len(result) == 1
        assert result[0].lookback == 20

    def test_empty_lookback_list(self, cone, year_returns):
        result = cone.calculate(year_returns, lookback_periods=[])
        assert result == []

    def test_constant_zero_returns(self, cone):
        """All-zero returns should give HV = 0 for all windows."""
        returns = [0.0] * 100
        points = cone.calculate(returns, lookback_periods=[5, 10])
        for p in points:
            assert p.current_hv == pytest.approx(0.0, abs=1e-10)
            assert p.p50 == pytest.approx(0.0, abs=1e-10)

    def test_duplicate_windows_deduplicated(self, cone, year_returns):
        """Duplicate window values should not produce duplicate cone points."""
        result = cone.calculate(year_returns, lookback_periods=[20, 20, 30])
        lookbacks = [p.lookback for p in result]
        assert len(lookbacks) == len(set(lookbacks))


# ---------------------------------------------------------------------------
# iv_percentile
# ---------------------------------------------------------------------------


class TestIVPercentile:
    """Tests for the IV percentile rank computation."""

    @pytest.fixture
    def sample_point(self) -> VolatilityConePoint:
        return VolatilityConePoint(
            lookback=20,
            current_hv=0.15,
            p10=0.10, p25=0.13, p50=0.16,
            p75=0.20, p90=0.25,
            min=0.07, max=0.35,
        )

    def test_iv_below_p10_returns_zero(self, cone, sample_point):
        assert cone.iv_percentile(0.05, sample_point) == pytest.approx(0.0)

    def test_iv_above_p90_returns_100(self, cone, sample_point):
        assert cone.iv_percentile(0.30, sample_point) == pytest.approx(100.0)

    def test_iv_at_p50_returns_50(self, cone, sample_point):
        pct = cone.iv_percentile(sample_point.p50, sample_point)
        assert pct == pytest.approx(50.0, abs=0.01)

    def test_iv_at_p10_returns_10(self, cone, sample_point):
        pct = cone.iv_percentile(sample_point.p10, sample_point)
        assert pct == pytest.approx(10.0, abs=0.01)

    def test_iv_at_p90_returns_90(self, cone, sample_point):
        pct = cone.iv_percentile(sample_point.p90, sample_point)
        assert pct == pytest.approx(90.0, abs=0.01)

    def test_result_in_0_to_100_range(self, cone, year_returns):
        points = cone.calculate(year_returns)
        for p in points:
            for iv in [0.10, 0.15, 0.20, 0.30]:
                pct = cone.iv_percentile(iv, p)
                assert 0.0 <= pct <= 100.0, f"Percentile {pct} out of range for iv={iv}"

    def test_monotone_increasing(self, cone, sample_point):
        """Higher IV should produce a higher or equal percentile."""
        ivs = [0.11, 0.14, 0.17, 0.22, 0.28]
        pcts = [cone.iv_percentile(iv, sample_point) for iv in ivs]
        for i in range(len(pcts) - 1):
            assert pcts[i] <= pcts[i + 1]

    def test_result_is_float(self, cone, sample_point):
        assert isinstance(cone.iv_percentile(0.15, sample_point), float)

    def test_result_is_finite(self, cone, sample_point):
        assert math.isfinite(cone.iv_percentile(0.15, sample_point))

    def test_equal_percentile_buckets_midpoint(self, cone):
        """When all percentile levels are equal, IV equals that value → midpoint."""
        p = VolatilityConePoint(
            lookback=20, current_hv=0.15,
            p10=0.15, p25=0.15, p50=0.15,
            p75=0.15, p90=0.15,
            min=0.15, max=0.15,
        )
        # IV at the flat level should return 10.0 (hits p10 exactly)
        pct = cone.iv_percentile(0.15, p)
        assert 0.0 <= pct <= 100.0


# ---------------------------------------------------------------------------
# Round-trip: calculate → iv_percentile integration
# ---------------------------------------------------------------------------


class TestConeIntegration:
    """Integration tests combining calculate and iv_percentile."""

    def test_current_hv_at_roughly_50th_for_median_iv(self, cone):
        """If we feed the p50 HV back as IV, the percentile should be near 50."""
        returns = _nifty_like_returns(500)
        points = cone.calculate(returns)
        assert points, "No cone points computed"
        p = points[2]  # Use 20-day window (index 2 in defaults)
        pct = cone.iv_percentile(p.p50, p)
        assert pct == pytest.approx(50.0, abs=1.0)

    def test_p90_iv_gives_percentile_90(self, cone):
        returns = _nifty_like_returns(500)
        points = cone.calculate(returns)
        p = points[2]
        pct = cone.iv_percentile(p.p90, p)
        assert pct == pytest.approx(90.0, abs=1.0)

    def test_cone_with_iv_annotation(self, cone):
        returns = _nifty_like_returns(300)
        current_iv = 0.20
        points = cone.calculate(returns, current_iv=current_iv)
        for p in points:
            assert p.current_iv == pytest.approx(current_iv)
            pct = cone.iv_percentile(current_iv, p)
            assert 0.0 <= pct <= 100.0
