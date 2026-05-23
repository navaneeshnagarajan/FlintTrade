"""Tests for the market breadth indicator module.

All tests are self-contained — no API calls, no broker connection required.
Uses pytest with --import-mode=importlib.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import pytest

from flinttrade_screener.market_breadth import (
    BreadthData,
    MarketBreadthCalculator,
    _ema,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def empty_calc() -> MarketBreadthCalculator:
    """Fresh, empty MarketBreadthCalculator."""
    return MarketBreadthCalculator()


@pytest.fixture
def loaded_calc() -> MarketBreadthCalculator:
    """Calculator seeded with 60 days of sample data."""
    calc = MarketBreadthCalculator()
    calc.generate_sample_data(days=60)
    return calc


# ---------------------------------------------------------------------------
# BreadthData model
# ---------------------------------------------------------------------------


class TestBreadthDataModel:
    """Validate BreadthData Pydantic constraints."""

    def test_basic_construction(self):
        d = BreadthData(
            date=date(2026, 4, 1),
            advances=1200,
            declines=600,
            unchanged=200,
        )
        assert d.advances == 1200
        assert d.declines == 600
        assert d.unchanged == 200

    def test_defaults_are_zero(self):
        d = BreadthData(date=date(2026, 4, 1), advances=500, declines=300, unchanged=100)
        assert d.new_highs == 0
        assert d.new_lows == 0
        assert d.ad_line == 0.0
        assert d.mcclellan_oscillator == 0.0
        assert d.breadth_thrust == 0.0

    def test_negative_advances_rejected(self):
        with pytest.raises(Exception):
            BreadthData(date=date(2026, 4, 1), advances=-1, declines=300, unchanged=100)

    def test_negative_declines_rejected(self):
        with pytest.raises(Exception):
            BreadthData(date=date(2026, 4, 1), advances=500, declines=-5, unchanged=100)


# ---------------------------------------------------------------------------
# EMA helper
# ---------------------------------------------------------------------------


class TestEMAHelper:
    """Unit tests for the internal _ema function."""

    def test_empty_input_returns_empty(self):
        assert _ema([], 10) == []

    def test_single_element(self):
        result = _ema([0.5], period=5)
        assert len(result) == 1
        assert result[0] == pytest.approx(0.5)

    def test_period_zero_returns_empty(self):
        assert _ema([1.0, 2.0], period=0) == []

    def test_constant_series_converges_to_constant(self):
        values = [1.0] * 50
        ema = _ema(values, period=10)
        # After convergence the EMA should stay at 1.0
        assert ema[-1] == pytest.approx(1.0, abs=1e-9)

    def test_ema_length_matches_input(self):
        values = [float(i) for i in range(30)]
        ema = _ema(values, period=10)
        assert len(ema) == len(values)

    def test_ema_series_is_all_finite(self):
        values = [0.01 * i for i in range(50)]
        ema = _ema(values, period=5)
        assert all(math.isfinite(v) for v in ema)


# ---------------------------------------------------------------------------
# Single update
# ---------------------------------------------------------------------------


class TestSingleUpdate:
    """Verify a single update call populates all fields correctly."""

    def test_update_returns_breadth_data(self, empty_calc):
        result = empty_calc.update(1200, 600, 200)
        assert isinstance(result, BreadthData)

    def test_ad_ratio_computed(self, empty_calc):
        result = empty_calc.update(1200, 600, 200)
        assert result.ad_ratio == pytest.approx(2.0)

    def test_ad_ratio_zero_declines(self, empty_calc):
        """ad_ratio should be 1.0 when declines is 0 to avoid division by zero."""
        result = empty_calc.update(1000, 0, 100)
        assert result.ad_ratio == 1.0

    def test_ad_line_equals_net_advances(self, empty_calc):
        result = empty_calc.update(1200, 600, 200)
        assert result.ad_line == pytest.approx(1200 - 600)

    def test_date_auto_assigned(self, empty_calc):
        result = empty_calc.update(1000, 500, 200)
        assert isinstance(result.date, date)

    def test_explicit_date_stored(self, empty_calc):
        d = date(2026, 1, 15)
        result = empty_calc.update(1000, 500, 200, trading_date=d)
        assert result.date == d

    def test_history_length_one_after_update(self, empty_calc):
        empty_calc.update(1000, 500, 200)
        assert len(empty_calc.get_history()) == 1


# ---------------------------------------------------------------------------
# A-D line
# ---------------------------------------------------------------------------


class TestADLine:
    """Tests for cumulative advance-decline line correctness."""

    def test_ad_line_cumulative(self, empty_calc):
        empty_calc.update(1000, 600, 200, trading_date=date(2026, 1, 1))  # net +400
        empty_calc.update(800, 900, 200, trading_date=date(2026, 1, 2))   # net -100
        empty_calc.update(1100, 500, 200, trading_date=date(2026, 1, 3))  # net +600

        ad = empty_calc.ad_line()
        assert ad[0] == pytest.approx(400.0)
        assert ad[1] == pytest.approx(300.0)   # 400 - 100
        assert ad[2] == pytest.approx(900.0)   # 300 + 600

    def test_ad_line_length_matches_history(self, loaded_calc):
        ad = loaded_calc.ad_line()
        assert len(ad) == len(loaded_calc.get_history(days=365))

    def test_all_rising_advances_grows_ad_line(self, empty_calc):
        for i in range(10):
            empty_calc.update(1500, 400, 100, trading_date=date(2026, 1, 1) + timedelta(days=i))
        ad = empty_calc.ad_line()
        assert ad[-1] > ad[0]

    def test_all_falling_declines_shrinks_ad_line(self, empty_calc):
        for i in range(10):
            empty_calc.update(300, 1500, 100, trading_date=date(2026, 1, 1) + timedelta(days=i))
        ad = empty_calc.ad_line()
        assert ad[-1] < ad[0]


# ---------------------------------------------------------------------------
# McClellan Oscillator
# ---------------------------------------------------------------------------


class TestMcClellanOscillator:
    """Tests for McClellan Oscillator computation."""

    def test_empty_calc_returns_zero(self, empty_calc):
        assert empty_calc.mcclellan_oscillator() == 0.0

    def test_oscillator_is_float(self, loaded_calc):
        assert isinstance(loaded_calc.mcclellan_oscillator(), float)

    def test_oscillator_is_finite(self, loaded_calc):
        assert math.isfinite(loaded_calc.mcclellan_oscillator())

    def test_strongly_rising_market_positive_oscillator(self, empty_calc):
        """Consistently high advances should produce a non-negative oscillator.

        When the net-advances ratio is strictly constant the short and long
        EMAs converge to the same value, giving an oscillator of exactly 0.
        We therefore test for >= 0 (non-negative) rather than strictly > 0.
        With a realistic noisy series the value will be clearly positive.
        """
        # Start with balanced breadth for 5 days, then drive strongly upward
        for i in range(5):
            empty_calc.update(1000, 1000, 0, trading_date=date(2026, 1, 1) + timedelta(days=i))
        for i in range(5, 50):
            empty_calc.update(1700, 200, 100, trading_date=date(2026, 1, 1) + timedelta(days=i))
        assert empty_calc.mcclellan_oscillator() > 0

    def test_strongly_falling_market_negative_oscillator(self, empty_calc):
        """Consistently high declines should produce a non-positive oscillator.

        Same EMA convergence reasoning as the rising-market test above.
        """
        # Start with balanced breadth for 5 days, then drive strongly downward
        for i in range(5):
            empty_calc.update(1000, 1000, 0, trading_date=date(2026, 1, 1) + timedelta(days=i))
        for i in range(5, 50):
            empty_calc.update(200, 1700, 100, trading_date=date(2026, 1, 1) + timedelta(days=i))
        assert empty_calc.mcclellan_oscillator() < 0

    def test_oscillator_stored_on_each_breadth_data(self, loaded_calc):
        history = loaded_calc.get_history(days=60)
        # All stored items should carry an oscillator value
        assert all(math.isfinite(d.mcclellan_oscillator) for d in history)


# ---------------------------------------------------------------------------
# Breadth Thrust
# ---------------------------------------------------------------------------


class TestBreadthThrust:
    """Tests for Breadth Thrust (Zweig) computation."""

    def test_empty_calc_returns_zero(self, empty_calc):
        assert empty_calc.breadth_thrust() == 0.0

    def test_thrust_between_zero_and_one(self, loaded_calc):
        thrust = loaded_calc.breadth_thrust()
        assert 0.0 <= thrust <= 1.0

    def test_thrust_stored_on_each_breadth_data(self, loaded_calc):
        history = loaded_calc.get_history(days=60)
        assert all(0.0 <= d.breadth_thrust <= 1.0 for d in history)

    def test_all_advances_thrust_near_one(self, empty_calc):
        for i in range(20):
            empty_calc.update(1999, 1, 0, trading_date=date(2026, 1, 1) + timedelta(days=i))
        # 1999 / 2000 ≈ 0.9995; EMA should converge near this
        assert empty_calc.breadth_thrust() > 0.9

    def test_all_declines_thrust_near_zero(self, empty_calc):
        for i in range(20):
            empty_calc.update(1, 1999, 0, trading_date=date(2026, 1, 1) + timedelta(days=i))
        assert empty_calc.breadth_thrust() < 0.1


# ---------------------------------------------------------------------------
# Sample data generation
# ---------------------------------------------------------------------------


class TestSampleDataGeneration:
    """Tests for generate_sample_data."""

    def test_generates_correct_count(self, empty_calc):
        data = empty_calc.generate_sample_data(days=45)
        assert len(data) == 45

    def test_default_90_days(self, empty_calc):
        data = empty_calc.generate_sample_data()
        assert len(data) == 90

    def test_dates_are_weekdays(self, empty_calc):
        data = empty_calc.generate_sample_data(days=20)
        for d in data:
            assert d.date.weekday() < 5, f"{d.date} is a weekend"

    def test_advances_positive(self, empty_calc):
        data = empty_calc.generate_sample_data(days=30)
        assert all(d.advances > 0 for d in data)

    def test_declines_positive(self, empty_calc):
        data = empty_calc.generate_sample_data(days=30)
        assert all(d.declines > 0 for d in data)

    def test_sample_data_deterministic(self):
        """Two calls with the same days should produce identical results."""
        c1, c2 = MarketBreadthCalculator(), MarketBreadthCalculator()
        d1, d2 = c1.generate_sample_data(days=20), c2.generate_sample_data(days=20)
        for a, b in zip(d1, d2):
            assert a.advances == b.advances
            assert a.declines == b.declines

    def test_all_indicators_populated_after_sample(self, empty_calc):
        data = empty_calc.generate_sample_data(days=50)
        for d in data:
            assert math.isfinite(d.ad_line)
            assert math.isfinite(d.mcclellan_oscillator)
            assert 0.0 <= d.breadth_thrust <= 1.0


# ---------------------------------------------------------------------------
# get_history
# ---------------------------------------------------------------------------


class TestGetHistory:
    """Tests for the get_history method."""

    def test_empty_returns_empty_list(self, empty_calc):
        assert empty_calc.get_history() == []

    def test_days_capped_to_available(self, loaded_calc):
        # loaded_calc has 60 days; requesting 200 should return 60
        history = loaded_calc.get_history(days=200)
        assert len(history) == 60

    def test_days_limits_correctly(self, loaded_calc):
        history = loaded_calc.get_history(days=10)
        assert len(history) == 10

    def test_most_recent_is_last(self, empty_calc):
        d1 = date(2026, 1, 1)
        d2 = date(2026, 1, 2)
        empty_calc.update(1000, 500, 100, trading_date=d1)
        empty_calc.update(1100, 450, 100, trading_date=d2)
        history = empty_calc.get_history(days=2)
        assert history[-1].date == d2
