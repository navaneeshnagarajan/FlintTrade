"""Tests for packages/services/screener/src/synthetic_future.py.

All tests are pure arithmetic — no network calls required.
"""

from __future__ import annotations

import math

import pytest

from flinttrade_screener.synthetic_future import (
    SyntheticFutureResult,
    compute_synthetic_future,
    cost_of_carry,
    implied_basis,
    synthetic_future_price,
    synthetic_vs_actual_spread,
)


# ---------------------------------------------------------------------------
# synthetic_future_price
# ---------------------------------------------------------------------------


class TestSyntheticFuturePrice:
    """Core PCR formula: C - P + K * e^(-r*t)."""

    def test_basic_calculation(self):
        """At-expiry (0 days): K*e^0 = K, so result = C - P + K."""
        price = synthetic_future_price(
            call_price=285.0,
            put_price=270.0,
            strike=24500.0,
            days_to_expiry=0,
            risk_free_rate=0.07,
        )
        # With t=0: e^0 = 1 → K*1 = 24500
        assert price == round(285.0 - 270.0 + 24500.0, 2)

    def test_with_positive_days(self):
        """Discounted strike lowers the synthetic price relative to t=0."""
        price_0 = synthetic_future_price(100, 90, 25000, 0)
        price_21 = synthetic_future_price(100, 90, 25000, 21)
        # At t=0 K=25000 exact, at t>0 PV(K)<K so synthetic is slightly lower
        assert price_21 < price_0

    def test_equal_call_put_price(self):
        """When C == P the result equals the discounted strike."""
        t = 30
        r = 0.065
        K = 25000.0
        pv_k = K * math.exp(-r * t / 365)
        price = synthetic_future_price(200.0, 200.0, K, t, r)
        assert abs(price - round(pv_k, 2)) < 0.01

    def test_result_is_rounded_to_2dp(self):
        price = synthetic_future_price(123.456, 100.111, 24500.0, 15)
        assert price == round(price, 2)

    def test_zero_call_and_put_price(self):
        """Zero premiums: synthetic = K * e^(-rt) (no cost carry)."""
        price = synthetic_future_price(0.0, 0.0, 25000.0, 30, 0.07)
        expected = round(25000.0 * math.exp(-0.07 * 30 / 365), 2)
        assert price == expected

    def test_negative_call_price_raises(self):
        with pytest.raises(ValueError, match="call_price"):
            synthetic_future_price(-1.0, 100.0, 25000.0, 21)

    def test_negative_put_price_raises(self):
        with pytest.raises(ValueError, match="put_price"):
            synthetic_future_price(100.0, -5.0, 25000.0, 21)

    def test_zero_strike_raises(self):
        with pytest.raises(ValueError, match="strike"):
            synthetic_future_price(100.0, 100.0, 0.0, 21)

    def test_negative_strike_raises(self):
        with pytest.raises(ValueError, match="strike"):
            synthetic_future_price(100.0, 100.0, -1000.0, 21)

    def test_negative_days_raises(self):
        with pytest.raises(ValueError, match="days_to_expiry"):
            synthetic_future_price(100.0, 100.0, 25000.0, -1)

    def test_negative_rate_raises(self):
        with pytest.raises(ValueError, match="risk_free_rate"):
            synthetic_future_price(100.0, 100.0, 25000.0, 21, -0.01)

    def test_zero_rate(self):
        """With r=0: pv(K) = K, result = C - P + K exactly."""
        price = synthetic_future_price(200.0, 180.0, 25000.0, 30, 0.0)
        assert price == round(200.0 - 180.0 + 25000.0, 2)


# ---------------------------------------------------------------------------
# synthetic_vs_actual_spread
# ---------------------------------------------------------------------------


class TestSyntheticVsActualSpread:
    """Arbitrage indicator: synthetic - actual."""

    def test_positive_spread(self):
        spread = synthetic_vs_actual_spread(24520.0, 24500.0)
        assert spread == 20.0

    def test_negative_spread(self):
        spread = synthetic_vs_actual_spread(24480.0, 24500.0)
        assert spread == -20.0

    def test_zero_spread(self):
        spread = synthetic_vs_actual_spread(24500.0, 24500.0)
        assert spread == 0.0

    def test_result_rounded_to_2dp(self):
        spread = synthetic_vs_actual_spread(24500.123, 24500.0)
        assert spread == round(spread, 2)

    def test_zero_synthetic_raises(self):
        with pytest.raises(ValueError, match="synthetic"):
            synthetic_vs_actual_spread(0.0, 24500.0)

    def test_zero_actual_raises(self):
        with pytest.raises(ValueError, match="actual_future"):
            synthetic_vs_actual_spread(24500.0, 0.0)


# ---------------------------------------------------------------------------
# cost_of_carry
# ---------------------------------------------------------------------------


class TestCostOfCarry:
    """CoC = K * (e^(rt) - 1)."""

    def test_zero_days_zero_carry(self):
        """At expiry there is no carry left."""
        coc = cost_of_carry(25000.0, 0, 0.07)
        assert coc == 0.0

    def test_positive_carry(self):
        coc = cost_of_carry(25000.0, 30, 0.07)
        expected = round(25000.0 * (math.exp(0.07 * 30 / 365) - 1), 2)
        assert coc == expected

    def test_zero_rate_zero_carry(self):
        coc = cost_of_carry(25000.0, 30, 0.0)
        assert coc == 0.0

    def test_invalid_strike_raises(self):
        with pytest.raises(ValueError, match="strike"):
            cost_of_carry(0.0, 30)

    def test_negative_days_raises(self):
        with pytest.raises(ValueError, match="days_to_expiry"):
            cost_of_carry(25000.0, -5)


# ---------------------------------------------------------------------------
# implied_basis
# ---------------------------------------------------------------------------


class TestImpliedBasis:
    """Implied basis = Synthetic Future - Spot."""

    def test_positive_basis(self):
        """When C > P the synthetic trades above spot (contango)."""
        basis = implied_basis(
            call_price=300.0,
            put_price=250.0,
            spot=25000.0,
            days_to_expiry=0,
            risk_free_rate=0.0,
        )
        # With r=0, t=0: basis = (C - P + K) - K = C - P = 50
        assert basis == 50.0

    def test_negative_basis(self):
        """When P > C the synthetic trades below spot (backwardation)."""
        basis = implied_basis(
            call_price=200.0,
            put_price=280.0,
            spot=25000.0,
            days_to_expiry=0,
            risk_free_rate=0.0,
        )
        assert basis == -80.0

    def test_zero_basis_equal_premiums(self):
        basis = implied_basis(
            call_price=150.0,
            put_price=150.0,
            spot=25000.0,
            days_to_expiry=0,
            risk_free_rate=0.0,
        )
        assert basis == 0.0

    def test_invalid_spot_raises(self):
        with pytest.raises(ValueError, match="spot"):
            implied_basis(100.0, 100.0, 0.0, 21)


# ---------------------------------------------------------------------------
# compute_synthetic_future (full result object)
# ---------------------------------------------------------------------------


class TestComputeSyntheticFuture:
    """compute_synthetic_future populates SyntheticFutureResult correctly."""

    def test_returns_synthetic_future_result(self):
        result = compute_synthetic_future(
            call_price=285.0,
            put_price=270.0,
            strike=24500.0,
            days_to_expiry=21,
            risk_free_rate=0.065,
        )
        assert isinstance(result, SyntheticFutureResult)

    def test_synthetic_price_matches_function(self):
        result = compute_synthetic_future(285.0, 270.0, 24500.0, 21, 0.065)
        expected = synthetic_future_price(285.0, 270.0, 24500.0, 21, 0.065)
        assert result.synthetic_price == expected

    def test_carry_populated(self):
        result = compute_synthetic_future(285.0, 270.0, 24500.0, 21, 0.065)
        expected_carry = cost_of_carry(24500.0, 21, 0.065)
        assert result.carry == expected_carry

    def test_spread_zero_when_no_actual(self):
        """Spread is 0.0 when actual_future is not provided."""
        result = compute_synthetic_future(285.0, 270.0, 24500.0, 21)
        assert result.spread == 0.0
        assert result.actual_future == 0.0

    def test_spread_computed_with_actual(self):
        synthetic = synthetic_future_price(285.0, 270.0, 24500.0, 21, 0.065)
        result = compute_synthetic_future(285.0, 270.0, 24500.0, 21, 0.065, actual_future=24520.0)
        assert result.spread == round(synthetic - 24520.0, 2)

    def test_fields_stored(self):
        result = compute_synthetic_future(285.0, 270.0, 24500.0, 21, 0.065)
        assert result.call_price == 285.0
        assert result.put_price == 270.0
        assert result.strike == 24500.0
        assert result.days_to_expiry == 21
        assert result.risk_free_rate == 0.065

    def test_default_rate_used(self):
        """Default risk_free_rate=0.07 should be applied."""
        result = compute_synthetic_future(100.0, 100.0, 25000.0, 30)
        assert result.risk_free_rate == 0.07
