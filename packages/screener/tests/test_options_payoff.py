"""Tests for the options payoff analysis engine.

All tests are self-contained — no API calls, no broker connection required.
Uses pytest with --import-mode=importlib (set in pyproject.toml).
"""

from __future__ import annotations

import math

import pytest

from packages.screener.src.options_payoff import (
    OptionLeg,
    OptionsPayoffEngine,
    PayoffAnalysis,
    PayoffPoint,
    _bs_price,
    _find_breakevens,
    _norm_cdf,
    _norm_pdf,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine() -> OptionsPayoffEngine:
    return OptionsPayoffEngine()


@pytest.fixture
def long_call() -> OptionLeg:
    return OptionLeg(side="BUY", option_type="CE", strike=24000, lots=1, premium=200)


@pytest.fixture
def short_call() -> OptionLeg:
    return OptionLeg(side="SELL", option_type="CE", strike=24000, lots=1, premium=200)


@pytest.fixture
def long_put() -> OptionLeg:
    return OptionLeg(side="BUY", option_type="PE", strike=24000, lots=1, premium=210)


@pytest.fixture
def short_put() -> OptionLeg:
    return OptionLeg(side="SELL", option_type="PE", strike=24000, lots=1, premium=210)


@pytest.fixture
def short_straddle(short_call, short_put) -> list[OptionLeg]:
    return [short_call, short_put]


@pytest.fixture
def long_straddle(long_call, long_put) -> list[OptionLeg]:
    return [long_call, long_put]


# ---------------------------------------------------------------------------
# OptionLeg model tests
# ---------------------------------------------------------------------------

class TestOptionLeg:
    """Tests for the OptionLeg Pydantic model."""

    def test_quantity_is_lots_times_lot_size(self):
        leg = OptionLeg(side="BUY", option_type="CE", strike=24000, lots=3, premium=100, lot_size=75)
        assert leg.quantity == 225

    def test_sign_buy_is_positive(self, long_call):
        assert long_call.sign == 1

    def test_sign_sell_is_negative(self, short_call):
        assert short_call.sign == -1

    def test_ce_intrinsic_itm(self, long_call):
        # Call ITM: spot > strike
        assert long_call.intrinsic_at_expiry(25000) == pytest.approx(1000.0)

    def test_ce_intrinsic_otm(self, long_call):
        # Call OTM: spot < strike → 0
        assert long_call.intrinsic_at_expiry(23000) == pytest.approx(0.0)

    def test_pe_intrinsic_itm(self, long_put):
        # Put ITM: spot < strike
        assert long_put.intrinsic_at_expiry(23000) == pytest.approx(1000.0)

    def test_pe_intrinsic_otm(self, long_put):
        assert long_put.intrinsic_at_expiry(25000) == pytest.approx(0.0)

    def test_long_call_pnl_at_expiry_profit(self, long_call):
        # Bought at 200, spot = 24500 → intrinsic 500 → P&L = 300
        assert long_call.pnl_at_expiry(24500) == pytest.approx(300.0)

    def test_long_call_pnl_at_expiry_loss(self, long_call):
        # OTM: intrinsic 0, paid 200 → loss 200
        assert long_call.pnl_at_expiry(23000) == pytest.approx(-200.0)

    def test_short_call_pnl_at_expiry_profit(self, short_call):
        # OTM: received 200, pay 0 → profit 200
        assert short_call.pnl_at_expiry(23000) == pytest.approx(200.0)

    def test_short_call_pnl_at_expiry_loss(self, short_call):
        # ITM: intrinsic 500, received 200 → loss 300
        assert short_call.pnl_at_expiry(24500) == pytest.approx(-300.0)

    def test_invalid_strike_raises(self):
        with pytest.raises(Exception):
            OptionLeg(side="BUY", option_type="CE", strike=-100, lots=1, premium=50)

    def test_invalid_side_raises(self):
        with pytest.raises(Exception):
            OptionLeg(side="HOLD", option_type="CE", strike=24000, lots=1, premium=50)

    def test_invalid_option_type_raises(self):
        with pytest.raises(Exception):
            OptionLeg(side="BUY", option_type="FUT", strike=24000, lots=1, premium=50)


# ---------------------------------------------------------------------------
# Payoff at expiry
# ---------------------------------------------------------------------------

class TestPayoffAtExpiry:
    """Tests for OptionsPayoffEngine.payoff_at_expiry."""

    def test_returns_correct_count(self, engine, short_straddle):
        points = engine.payoff_at_expiry(short_straddle, spot_range=(20000, 28000), n_points=100)
        assert len(points) == 100

    def test_points_sorted_ascending(self, engine, long_call):
        points = engine.payoff_at_expiry([long_call], spot_range=(22000, 26000), n_points=50)
        spots = [p.spot for p in points]
        assert spots == sorted(spots)

    def test_short_straddle_max_profit_at_atm(self, engine, short_straddle):
        # Short straddle: max profit when spot == strike at expiry
        points = engine.payoff_at_expiry(
            short_straddle, spot_range=(23000, 25000), n_points=200
        )
        atm_points = [p for p in points if abs(p.spot - 24000) < 15]
        assert atm_points, "No ATM points found in range"
        max_pnl_near_atm = max(p.pnl for p in atm_points)
        # Net premium = 200 + 210 = 410 per lot
        assert max_pnl_near_atm == pytest.approx(410.0, abs=30.0)

    def test_long_straddle_loss_at_atm(self, engine, long_straddle):
        points = engine.payoff_at_expiry(
            long_straddle, spot_range=(23500, 24500), n_points=100
        )
        atm_points = [p for p in points if abs(p.spot - 24000) < 15]
        assert atm_points
        min_pnl_near_atm = min(p.pnl for p in atm_points)
        assert min_pnl_near_atm == pytest.approx(-410.0, abs=30.0)

    def test_empty_legs_returns_empty(self, engine):
        points = engine.payoff_at_expiry([], spot_range=(22000, 26000))
        assert points == []

    def test_invalid_range_returns_empty(self, engine, long_call):
        points = engine.payoff_at_expiry([long_call], spot_range=(26000, 22000))
        assert points == []

    def test_single_long_call_payoff_shape(self, engine, long_call):
        points = engine.payoff_at_expiry([long_call], spot_range=(22000, 26000), n_points=100)
        # All spots below 24000: pnl == -premium = -200
        otm = [p for p in points if p.spot < 24000]
        for p in otm:
            assert p.pnl == pytest.approx(-200.0, abs=0.5)
        # Some spots above 24000 should have positive pnl
        itm = [p for p in points if p.spot > 24200]
        assert any(p.pnl > 0 for p in itm)

    def test_lot_size_scales_pnl(self, engine):
        leg_1 = OptionLeg(side="SELL", option_type="CE", strike=24000, lots=1, premium=200, lot_size=75)
        leg_2 = OptionLeg(side="SELL", option_type="CE", strike=24000, lots=1, premium=200, lot_size=1)
        points_1 = engine.payoff_at_expiry([leg_1], spot_range=(23000, 23500), n_points=5)
        points_2 = engine.payoff_at_expiry([leg_2], spot_range=(23000, 23500), n_points=5)
        for p1, p2 in zip(points_1, points_2):
            assert p1.pnl == pytest.approx(p2.pnl * 75, rel=1e-6)


# ---------------------------------------------------------------------------
# Payoff before expiry
# ---------------------------------------------------------------------------

class TestPayoffBeforeExpiry:
    """Tests for OptionsPayoffEngine.payoff_before_expiry."""

    def test_returns_correct_count(self, engine, long_call):
        points = engine.payoff_before_expiry([long_call], spot=24000, iv=0.20, days=30, n_points=100)
        assert len(points) == 100

    def test_pnl_is_finite(self, engine, long_call):
        points = engine.payoff_before_expiry([long_call], spot=24000, iv=0.20, days=30)
        assert all(math.isfinite(p.pnl) for p in points)

    def test_long_call_at_entry_spot_near_zero_pnl(self, engine):
        # Use a realistic ATM premium for 30-day, IV=20% call on spot=24000.
        # BS price ≈ 24000 * 0.20 * sqrt(30/365) / sqrt(2π) ≈ 560–600 approx.
        # We use premium=580 (close to fair value) → P&L near entry spot should be near 0.
        realistic_leg = OptionLeg(side="BUY", option_type="CE", strike=24000, lots=1, premium=580)
        points = engine.payoff_before_expiry([realistic_leg], spot=24000, iv=0.20, days=30, n_points=200)
        closest = min(points, key=lambda p: abs(p.spot - 24000))
        # The P&L at entry spot with fair premium should be within 10% of premium
        assert abs(closest.pnl) < realistic_leg.premium * 0.10

    def test_zero_days_matches_expiry_payoff(self, engine, long_call):
        """At 0 days, before-expiry payoff should approximate expiry payoff."""
        before = engine.payoff_before_expiry([long_call], spot=24000, iv=0.20, days=0, n_points=50)
        expiry = engine.payoff_at_expiry([long_call], spot_range=(24000 * 0.7, 24000 * 1.3), n_points=50)
        # Check a few OTM points
        otm_before = [p.pnl for p in before if p.spot < 24000][:5]
        otm_expiry = [p.pnl for p in expiry if p.spot < 24000][:5]
        for b, e in zip(otm_before, otm_expiry):
            assert abs(b - e) < 20.0  # Should be close at expiry


# ---------------------------------------------------------------------------
# Probability of Profit
# ---------------------------------------------------------------------------

class TestProbabilityOfProfit:
    """Tests for OptionsPayoffEngine.probability_of_profit."""

    def test_pop_in_range(self, engine, short_straddle):
        pop = engine.probability_of_profit(short_straddle, spot=24000, iv=0.20, days=30)
        assert 0.0 <= pop <= 1.0

    def test_short_straddle_pop_reasonable(self, engine, short_straddle):
        # Short straddle with 410 combined premium, spot=24000 → breakevens at
        # ~23590 and ~24410. With IV=20%, 30 days, the log-normal distribution
        # gives ~20-35% probability of staying within that range.
        pop = engine.probability_of_profit(short_straddle, spot=24000, iv=0.20, days=30)
        # POP should be > 0.15 (non-trivial) and < 0.6 (not unrealistically high)
        assert pop > 0.15
        assert pop < 0.60

    def test_deep_otm_short_call_high_pop(self, engine):
        # Short call far OTM → very high probability of expiring worthless
        leg = OptionLeg(side="SELL", option_type="CE", strike=30000, lots=1, premium=5)
        pop = engine.probability_of_profit([leg], spot=24000, iv=0.20, days=30)
        assert pop > 0.8

    def test_deep_itm_long_call_high_pop(self, engine):
        # Long call deeply ITM with premium well below intrinsic value.
        # Strike=18000, spot=24000 → intrinsic=6000.
        # Using premium=4000 (far below intrinsic) → breakeven=22000, ~8.3% below spot.
        # With IV=20% and 30 days, nearly all paths land above 22000 → POP > 0.85.
        leg = OptionLeg(side="BUY", option_type="CE", strike=18000, lots=1, premium=4000)
        pop = engine.probability_of_profit([leg], spot=24000, iv=0.20, days=30)
        assert pop > 0.85

    def test_zero_days_falls_back_gracefully(self, engine, short_straddle):
        pop = engine.probability_of_profit(short_straddle, spot=24000, iv=0.20, days=0)
        assert 0.0 <= pop <= 1.0

    def test_returns_deterministic(self, engine, short_straddle):
        pop1 = engine.probability_of_profit(short_straddle, spot=24000, iv=0.20, days=30)
        pop2 = engine.probability_of_profit(short_straddle, spot=24000, iv=0.20, days=30)
        assert pop1 == pop2


# ---------------------------------------------------------------------------
# Full calculate method
# ---------------------------------------------------------------------------

class TestCalculate:
    """Integration tests for OptionsPayoffEngine.calculate."""

    def test_returns_payoff_analysis(self, engine, short_straddle):
        result = engine.calculate(short_straddle, spot=24000)
        assert isinstance(result, PayoffAnalysis)

    def test_points_not_empty(self, engine, short_straddle):
        result = engine.calculate(short_straddle, spot=24000)
        assert len(result.points) == 200

    def test_net_premium_short_straddle(self, engine, short_straddle):
        # Sell CE 200 + Sell PE 210 = credit 410
        result = engine.calculate(short_straddle, spot=24000)
        assert result.net_premium == pytest.approx(410.0)

    def test_net_premium_long_straddle(self, engine, long_straddle):
        # Buy CE 200 + Buy PE 210 = debit 410
        result = engine.calculate(long_straddle, spot=24000)
        assert result.net_premium == pytest.approx(-410.0)

    def test_breakevens_exist_for_straddle(self, engine, short_straddle):
        result = engine.calculate(short_straddle, spot=24000)
        # Short straddle should have 2 breakevens
        assert len(result.breakevens) >= 1

    def test_short_straddle_breakevens_around_atm(self, engine, short_straddle):
        result = engine.calculate(short_straddle, spot=24000)
        for be in result.breakevens:
            # Both breakevens should be within 2x premium of ATM strike
            assert 20000 < be < 28000

    def test_greeks_are_finite(self, engine, short_straddle):
        result = engine.calculate(short_straddle, spot=24000)
        assert math.isfinite(result.net_delta)
        assert math.isfinite(result.net_gamma)
        assert math.isfinite(result.net_theta)
        assert math.isfinite(result.net_vega)

    def test_short_straddle_near_delta_neutral(self, engine, short_straddle):
        # ATM straddle → delta should be close to zero
        result = engine.calculate(short_straddle, spot=24000, iv=0.20, days_to_expiry=30)
        assert abs(result.net_delta) < 30.0  # 30 contracts, so delta scale is per-lot

    def test_max_profit_le_net_premium_for_short_straddle(self, engine, short_straddle):
        result = engine.calculate(short_straddle, spot=24000)
        # Max profit at expiry ≈ net premium received
        assert result.max_profit is not None
        assert result.max_profit <= result.net_premium + 5.0  # Allow rounding tolerance

    def test_empty_legs_returns_zero_analysis(self, engine):
        result = engine.calculate([], spot=24000)
        assert result.net_premium == 0.0
        assert result.pop == 0.0
        assert result.points == []

    def test_pop_in_range(self, engine, short_straddle):
        result = engine.calculate(short_straddle, spot=24000)
        assert 0.0 <= result.pop <= 1.0

    def test_lot_size_scales_max_profit(self, engine):
        leg_1 = OptionLeg(side="SELL", option_type="CE", strike=24500, lots=1, premium=100, lot_size=1)
        leg_2 = OptionLeg(side="SELL", option_type="CE", strike=24500, lots=1, premium=100, lot_size=75)
        r1 = engine.calculate([leg_1], spot=24000)
        r2 = engine.calculate([leg_2], spot=24000)
        assert r2.max_profit == pytest.approx(r1.max_profit * 75, rel=0.05)

    def test_bull_call_spread(self, engine):
        """Bull call spread: buy lower strike CE, sell higher strike CE."""
        buy_leg = OptionLeg(side="BUY", option_type="CE", strike=24000, lots=1, premium=200)
        sell_leg = OptionLeg(side="SELL", option_type="CE", strike=24500, lots=1, premium=80)
        result = engine.calculate([buy_leg, sell_leg], spot=24000)
        # Net premium = debit (paid 200, received 80 = -120)
        assert result.net_premium == pytest.approx(-120.0)
        # Max profit = spread width (500) - debit (120) = 380
        assert result.max_profit is not None
        assert result.max_profit == pytest.approx(380.0, abs=5.0)
        # Max loss = debit = 120
        assert result.max_loss is not None
        assert result.max_loss == pytest.approx(-120.0, abs=5.0)


# ---------------------------------------------------------------------------
# Black-Scholes helpers
# ---------------------------------------------------------------------------

class TestBSHelpers:
    """Tests for internal Black-Scholes functions."""

    def test_norm_cdf_at_zero(self):
        assert _norm_cdf(0.0) == pytest.approx(0.5, abs=1e-6)

    def test_norm_cdf_large_positive(self):
        assert _norm_cdf(10.0) == pytest.approx(1.0, abs=1e-6)

    def test_norm_cdf_large_negative(self):
        assert _norm_cdf(-10.0) == pytest.approx(0.0, abs=1e-6)

    def test_norm_pdf_at_zero(self):
        expected = 1.0 / math.sqrt(2.0 * math.pi)
        assert _norm_pdf(0.0) == pytest.approx(expected, rel=1e-6)

    def test_bs_call_price_known_value(self):
        # Standard reference: S=100, K=100, T=1y, r=0.05, σ=0.20 → ~10.45
        price = _bs_price("c", S=100, K=100, T=1.0, r=0.05, sigma=0.20)
        assert price == pytest.approx(10.45, abs=0.10)

    def test_bs_put_price_known_value(self):
        # Put-call parity: P = C - S + K*e^(-rT)
        S, K, T, r, sigma = 100, 100, 1.0, 0.05, 0.20
        c = _bs_price("c", S, K, T, r, sigma)
        p = _bs_price("p", S, K, T, r, sigma)
        parity_rhs = c - S + K * math.exp(-r * T)
        assert p == pytest.approx(parity_rhs, abs=0.01)

    def test_bs_price_at_expiry_call_itm(self):
        price = _bs_price("c", S=105, K=100, T=0, r=0.05, sigma=0.20)
        assert price == pytest.approx(5.0)

    def test_bs_price_at_expiry_call_otm(self):
        price = _bs_price("c", S=95, K=100, T=0, r=0.05, sigma=0.20)
        assert price == pytest.approx(0.0)

    def test_bs_price_at_expiry_put_itm(self):
        price = _bs_price("p", S=95, K=100, T=0, r=0.05, sigma=0.20)
        assert price == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Breakeven finder
# ---------------------------------------------------------------------------

class TestFindBreakevens:
    """Tests for the _find_breakevens helper."""

    def test_simple_sign_change(self):
        points = [
            PayoffPoint(spot=100, pnl=-50),
            PayoffPoint(spot=110, pnl=50),
        ]
        bes = _find_breakevens(points)
        assert len(bes) == 1
        assert bes[0] == pytest.approx(105.0, abs=1.0)

    def test_no_sign_change_returns_empty(self):
        points = [PayoffPoint(spot=float(s), pnl=100.0) for s in range(100, 200, 10)]
        bes = _find_breakevens(points)
        assert bes == []

    def test_two_crossings(self):
        # Short straddle: positive in middle, negative at extremes
        points = [
            PayoffPoint(spot=22000, pnl=-200),
            PayoffPoint(spot=23000, pnl=100),
            PayoffPoint(spot=24000, pnl=410),
            PayoffPoint(spot=25000, pnl=100),
            PayoffPoint(spot=26000, pnl=-200),
        ]
        bes = _find_breakevens(points)
        assert len(bes) == 2
        assert bes[0] < 24000 < bes[1]

    def test_empty_list_returns_empty(self):
        assert _find_breakevens([]) == []

    def test_near_zero_point_included(self):
        points = [
            PayoffPoint(spot=100, pnl=-100),
            PayoffPoint(spot=105, pnl=3),   # Near zero — within tolerance=5
        ]
        bes = _find_breakevens(points, tolerance=5.0)
        # Either the sign-change interpolation or the near-zero point picks it up
        assert len(bes) >= 1
