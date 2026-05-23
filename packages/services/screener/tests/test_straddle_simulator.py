"""Tests for straddle simulator module (straddle_simulator.py).

All tests use synthetic data — no API calls or broker connections required.
"""

from __future__ import annotations

import numpy as np

from flinttrade_screener.straddle_simulator import (
    simulate_short_straddle,
    simulate_iron_condor,
    simulate_iron_butterfly,
    straddle_pnl_curve,
    _short_straddle_pnl_at_expiry,
)


# ---------------------------------------------------------------------------
# simulate_short_straddle
# ---------------------------------------------------------------------------


class TestSimulateShortStraddle:
    def test_strategy_name(self) -> None:
        r = simulate_short_straddle(
            spot=24000, strike=24000, call_premium=180, put_premium=175, lot_size=75
        )
        assert r["strategy"] == "short_straddle"

    def test_max_profit_calculation(self) -> None:
        r = simulate_short_straddle(
            spot=24000, strike=24000, call_premium=180, put_premium=175, lot_size=75
        )
        assert r["max_profit"] == (180 + 175) * 75

    def test_breakeven_low(self) -> None:
        r = simulate_short_straddle(
            spot=24000, strike=24000, call_premium=180, put_premium=175, lot_size=75
        )
        expected = 24000 - (180 + 175)
        assert abs(r["breakeven_low"] - expected) < 0.01

    def test_breakeven_high(self) -> None:
        r = simulate_short_straddle(
            spot=24000, strike=24000, call_premium=180, put_premium=175, lot_size=75
        )
        expected = 24000 + (180 + 175)
        assert abs(r["breakeven_high"] - expected) < 0.01

    def test_loss_at_plus_n(self) -> None:
        r = simulate_short_straddle(
            spot=24000, strike=24000, call_premium=180, put_premium=175, lot_size=75,
            adjustment_points=100,
        )
        # At strike + 100: call loss = 100, put expires worthless
        expected_pnl = ((180 + 175) - 100) * 75
        assert abs(r["loss_at_plus_n"] - expected_pnl) < 0.01

    def test_loss_at_minus_n(self) -> None:
        r = simulate_short_straddle(
            spot=24000, strike=24000, call_premium=180, put_premium=175, lot_size=75,
            adjustment_points=100,
        )
        # At strike - 100: put loss = 100, call expires worthless
        expected_pnl = ((180 + 175) - 100) * 75
        assert abs(r["loss_at_minus_n"] - expected_pnl) < 0.01

    def test_is_atm_when_spot_equals_strike(self) -> None:
        r = simulate_short_straddle(
            spot=24000, strike=24000, call_premium=180, put_premium=175, lot_size=75
        )
        assert r["is_atm"] is True

    def test_is_not_atm_when_far_otm(self) -> None:
        r = simulate_short_straddle(
            spot=24000, strike=22000, call_premium=180, put_premium=175, lot_size=75
        )
        assert r["is_atm"] is False

    def test_total_premium_field(self) -> None:
        r = simulate_short_straddle(
            spot=24000, strike=24000, call_premium=180, put_premium=175, lot_size=75
        )
        assert r["total_premium"] == 355.0

    def test_lot_size_and_adjustment_stored(self) -> None:
        r = simulate_short_straddle(
            spot=24000, strike=24000, call_premium=180, put_premium=175, lot_size=75,
            adjustment_points=150,
        )
        assert r["lot_size"] == 75
        assert r["adjustment_points"] == 150

    def test_large_adjustment_beyond_premium_gives_loss(self) -> None:
        r = simulate_short_straddle(
            spot=24000, strike=24000, call_premium=100, put_premium=100, lot_size=75,
            adjustment_points=500,
        )
        # At ±500 with 200 premium: loss
        assert r["loss_at_plus_n"] < 0


# ---------------------------------------------------------------------------
# simulate_iron_condor
# ---------------------------------------------------------------------------


class TestSimulateIronCondor:
    def _default_condor(self) -> dict:
        return simulate_iron_condor(
            spot=24000,
            sell_call_strike=24500, buy_call_strike=24700,
            sell_put_strike=23500, buy_put_strike=23300,
            sell_call_premium=80, buy_call_premium=40,
            sell_put_premium=75, buy_put_premium=35,
            lot_size=75,
        )

    def test_strategy_name(self) -> None:
        r = self._default_condor()
        assert r["strategy"] == "iron_condor"

    def test_net_premium_calculation(self) -> None:
        r = self._default_condor()
        expected = (80 - 40) + (75 - 35)
        assert abs(r["net_premium"] - expected) < 0.01

    def test_max_profit_equals_net_premium_times_lot_size(self) -> None:
        r = self._default_condor()
        assert abs(r["max_profit"] - r["net_premium"] * 75) < 0.01

    def test_breakeven_low_below_sell_put(self) -> None:
        r = self._default_condor()
        assert r["breakeven_low"] < 23500

    def test_breakeven_high_above_sell_call(self) -> None:
        r = self._default_condor()
        assert r["breakeven_high"] > 24500

    def test_profit_zone_boundaries(self) -> None:
        r = self._default_condor()
        assert r["profit_zone_low"] == 23500
        assert r["profit_zone_high"] == 24500

    def test_max_loss_is_positive(self) -> None:
        r = self._default_condor()
        assert r["max_loss"] > 0

    def test_max_loss_at_most_wing_width_times_lot_size(self) -> None:
        """Max loss cannot exceed the full wing width."""
        r = self._default_condor()
        call_width = (24700 - 24500) * 75
        put_width = (23500 - 23300) * 75
        assert r["max_loss"] <= max(call_width, put_width)


# ---------------------------------------------------------------------------
# simulate_iron_butterfly
# ---------------------------------------------------------------------------


class TestSimulateIronButterfly:
    def _default_butterfly(self) -> dict:
        return simulate_iron_butterfly(
            spot=24000,
            atm_strike=24000,
            buy_call_strike=24300,
            buy_put_strike=23700,
            sell_call_premium=180,
            sell_put_premium=175,
            buy_call_premium=60,
            buy_put_premium=55,
            lot_size=75,
        )

    def test_strategy_name(self) -> None:
        r = self._default_butterfly()
        assert r["strategy"] == "iron_butterfly"

    def test_net_premium_calculation(self) -> None:
        r = self._default_butterfly()
        expected = (180 + 175) - (60 + 55)
        assert abs(r["net_premium"] - expected) < 0.01

    def test_max_profit_at_atm(self) -> None:
        r = self._default_butterfly()
        assert r["max_profit"] == r["net_premium"] * 75

    def test_breakeven_symmetry(self) -> None:
        r = self._default_butterfly()
        assert abs(r["breakeven_low"] - (24000 - r["net_premium"])) < 0.01
        assert abs(r["breakeven_high"] - (24000 + r["net_premium"])) < 0.01

    def test_max_loss_is_positive(self) -> None:
        r = self._default_butterfly()
        # At least one of the loss sides must be positive
        assert r["max_loss"] > 0

    def test_higher_wing_spread_higher_max_loss(self) -> None:
        narrow = simulate_iron_butterfly(
            spot=24000, atm_strike=24000,
            buy_call_strike=24200, buy_put_strike=23800,
            sell_call_premium=180, sell_put_premium=175,
            buy_call_premium=80, buy_put_premium=75, lot_size=75,
        )
        wide = simulate_iron_butterfly(
            spot=24000, atm_strike=24000,
            buy_call_strike=24500, buy_put_strike=23500,
            sell_call_premium=180, sell_put_premium=175,
            buy_call_premium=30, buy_put_premium=25, lot_size=75,
        )
        assert wide["max_loss"] > narrow["max_loss"]


# ---------------------------------------------------------------------------
# straddle_pnl_curve
# ---------------------------------------------------------------------------


class TestStraddlePnlCurve:
    def test_empty_spot_range_returns_empty(self) -> None:
        legs = [{"option_type": "CE", "action": "SELL", "strike": 24000, "premium": 180}]
        result = straddle_pnl_curve(np.array([]), legs)
        assert result.size == 0

    def test_empty_legs_returns_zeros(self) -> None:
        spots = np.array([23000.0, 24000.0, 25000.0])
        result = straddle_pnl_curve(spots, [])
        np.testing.assert_array_equal(result, np.zeros(3))

    def test_max_profit_at_strike_for_short_straddle(self) -> None:
        legs = [
            {"option_type": "CE", "action": "SELL", "strike": 24000, "premium": 180},
            {"option_type": "PE", "action": "SELL", "strike": 24000, "premium": 175},
        ]
        spots = np.array([24000.0])
        pnl = straddle_pnl_curve(spots, legs)
        assert float(pnl[0]) == 355.0  # 180 + 175 at ATM

    def test_loss_increases_below_breakeven(self) -> None:
        legs = [
            {"option_type": "CE", "action": "SELL", "strike": 24000, "premium": 200},
            {"option_type": "PE", "action": "SELL", "strike": 24000, "premium": 200},
        ]
        spots = np.array([22000.0, 23000.0, 24000.0])
        pnl = straddle_pnl_curve(spots, legs)
        # P&L should increase as spot approaches ATM
        assert pnl[0] < pnl[1] < pnl[2]

    def test_long_straddle_pnl_curve_concave_up(self) -> None:
        legs = [
            {"option_type": "CE", "action": "BUY", "strike": 24000, "premium": 180},
            {"option_type": "PE", "action": "BUY", "strike": 24000, "premium": 175},
        ]
        spots = np.linspace(22000, 26000, 100)
        pnl = straddle_pnl_curve(spots, legs)
        # Minimum at ATM, higher at wings
        assert float(pnl[len(pnl) // 2]) < float(pnl[0])
        assert float(pnl[len(pnl) // 2]) < float(pnl[-1])

    def test_iron_condor_legs(self) -> None:
        legs = [
            {"option_type": "CE", "action": "SELL", "strike": 24500, "premium": 80},
            {"option_type": "CE", "action": "BUY", "strike": 24700, "premium": 40},
            {"option_type": "PE", "action": "SELL", "strike": 23500, "premium": 75},
            {"option_type": "PE", "action": "BUY", "strike": 23300, "premium": 35},
        ]
        spots = np.array([23000.0, 24000.0, 25000.0])
        pnl = straddle_pnl_curve(spots, legs)
        # Max profit in middle region
        assert pnl[1] > pnl[0]
        assert pnl[1] > pnl[2]

    def test_output_same_length_as_spot_range(self) -> None:
        legs = [{"option_type": "CE", "action": "SELL", "strike": 24000, "premium": 180}]
        spots = np.linspace(22000, 26000, 250)
        pnl = straddle_pnl_curve(spots, legs)
        assert len(pnl) == 250

    def test_quantity_scaling(self) -> None:
        """quantity=2 should produce exactly 2× the P&L."""
        legs_1x = [{"option_type": "CE", "action": "SELL",
                    "strike": 24000, "premium": 180, "quantity": 1}]
        legs_2x = [{"option_type": "CE", "action": "SELL",
                    "strike": 24000, "premium": 180, "quantity": 2}]
        spots = np.array([24000.0, 24200.0])
        pnl_1x = straddle_pnl_curve(spots, legs_1x)
        pnl_2x = straddle_pnl_curve(spots, legs_2x)
        np.testing.assert_allclose(pnl_2x, pnl_1x * 2, rtol=1e-6)

    def test_skips_zero_strike_leg(self) -> None:
        legs = [
            {"option_type": "CE", "action": "SELL", "strike": 0, "premium": 180},
            {"option_type": "PE", "action": "SELL", "strike": 24000, "premium": 175},
        ]
        spots = np.array([24000.0])
        pnl = straddle_pnl_curve(spots, legs)
        # Only PE leg counted
        assert float(pnl[0]) == 175.0


# ---------------------------------------------------------------------------
# _short_straddle_pnl_at_expiry (private helper — sanity checks)
# ---------------------------------------------------------------------------


class TestShortStraddlePnlAtExpiry:
    def test_at_strike_full_profit(self) -> None:
        pnl = _short_straddle_pnl_at_expiry(
            spot=24000, strike=24000, call_premium=180, put_premium=175, lot_size=75
        )
        assert pnl == (180 + 175) * 75

    def test_far_otm_call_side(self) -> None:
        """Spot at strike + 500: call buyer exercises, put expires."""
        pnl = _short_straddle_pnl_at_expiry(
            spot=24500, strike=24000, call_premium=180, put_premium=175, lot_size=75
        )
        expected = ((180 + 175) - 500) * 75
        assert abs(pnl - expected) < 0.01
