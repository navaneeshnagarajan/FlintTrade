"""Tests for packages/engine/src/options_multi_order.py.

Covers all 6 strategy builders: symbol construction, leg count, actions,
strike values, and quantity calculation.
"""

from __future__ import annotations

import pytest

from packages.engine.src.basket_orders import BasketLeg
from packages.engine.src.options_multi_order import (
    OptionsStrategyBuilder,
    _fmt_strike,
    _option_symbol,
)


# ---------------------------------------------------------------------------
# Symbol helper tests
# ---------------------------------------------------------------------------


class TestFmtStrike:
    """_fmt_strike formats strike prices as expected."""

    def test_whole_number(self):
        assert _fmt_strike(26000.0) == "26000"

    def test_fractional_strike(self):
        assert _fmt_strike(26050.5) == "26050.5"

    def test_large_whole(self):
        assert _fmt_strike(100000.0) == "100000"


class TestOptionSymbol:
    """_option_symbol produces correctly composed strings."""

    def test_call_symbol(self):
        sym = _option_symbol("NIFTY", "25MAY25", 26000.0, "CE")
        assert sym == "NIFTY25MAY2526000CE"

    def test_put_symbol(self):
        sym = _option_symbol("NIFTY", "25MAY25", 24500.0, "PE")
        assert sym == "NIFTY25MAY2524500PE"

    def test_lowercase_inputs_normalised(self):
        sym = _option_symbol("banknifty", "25may25", 52000.0, "ce")
        assert sym == "BANKNIFTY25MAY2552000CE"

    def test_banknifty_symbol(self):
        sym = _option_symbol("BANKNIFTY", "25MAY25", 52000.0, "PE")
        assert sym == "BANKNIFTY25MAY2552000PE"


# ---------------------------------------------------------------------------
# Short Straddle
# ---------------------------------------------------------------------------


class TestShortStraddle:
    """short_straddle: sell ATM call + sell ATM put."""

    def setup_method(self):
        self.legs = OptionsStrategyBuilder.short_straddle(
            underlying="NIFTY",
            expiry="25MAY25",
            strike=25000.0,
            lots=1,
            lot_size=50,
        )

    def test_returns_two_legs(self):
        assert len(self.legs) == 2

    def test_both_legs_are_sell(self):
        assert all(leg.action == "SELL" for leg in self.legs)

    def test_one_call_one_put(self):
        symbols = [leg.symbol for leg in self.legs]
        assert any("CE" in s for s in symbols)
        assert any("PE" in s for s in symbols)

    def test_quantity_equals_lots_times_lot_size(self):
        assert all(leg.quantity == 50 for leg in self.legs)

    def test_multi_lot_quantity(self):
        legs = OptionsStrategyBuilder.short_straddle("NIFTY", "25MAY25", 25000.0, lots=2)
        assert all(leg.quantity == 100 for leg in legs)

    def test_correct_strike_in_symbol(self):
        symbols = [leg.symbol for leg in self.legs]
        assert all("25000" in s for s in symbols)

    def test_default_product_nrml(self):
        assert all(leg.product == "NRML" for leg in self.legs)


# ---------------------------------------------------------------------------
# Long Strangle
# ---------------------------------------------------------------------------


class TestLongStrangle:
    """long_strangle: buy OTM call + buy OTM put."""

    def setup_method(self):
        self.legs = OptionsStrategyBuilder.long_strangle(
            underlying="NIFTY",
            expiry="25MAY25",
            call_strike=26000.0,
            put_strike=24000.0,
            lots=1,
            lot_size=50,
        )

    def test_returns_two_legs(self):
        assert len(self.legs) == 2

    def test_both_legs_are_buy(self):
        assert all(leg.action == "BUY" for leg in self.legs)

    def test_call_leg_strike(self):
        call_leg = next(leg for leg in self.legs if "CE" in leg.symbol)
        assert "26000" in call_leg.symbol

    def test_put_leg_strike(self):
        put_leg = next(leg for leg in self.legs if "PE" in leg.symbol)
        assert "24000" in put_leg.symbol

    def test_quantity(self):
        assert all(leg.quantity == 50 for leg in self.legs)


# ---------------------------------------------------------------------------
# Iron Condor
# ---------------------------------------------------------------------------


class TestIronCondor:
    """iron_condor: put spread + call spread = 4 legs."""

    def setup_method(self):
        self.legs = OptionsStrategyBuilder.iron_condor(
            underlying="NIFTY",
            expiry="25MAY25",
            put_short=24500.0,
            put_long=24000.0,
            call_short=26000.0,
            call_long=26500.0,
            lots=1,
            lot_size=50,
        )

    def test_returns_four_legs(self):
        assert len(self.legs) == 4

    def test_buy_legs_count(self):
        buy_legs = [leg for leg in self.legs if leg.action == "BUY"]
        assert len(buy_legs) == 2

    def test_sell_legs_count(self):
        sell_legs = [leg for leg in self.legs if leg.action == "SELL"]
        assert len(sell_legs) == 2

    def test_buy_legs_appear_before_sell_legs(self):
        """BUY (protection) legs must come before SELL legs in the list."""
        actions = [leg.action for leg in self.legs]
        last_buy = max(i for i, a in enumerate(actions) if a == "BUY")
        first_sell = min(i for i, a in enumerate(actions) if a == "SELL")
        assert last_buy < first_sell

    def test_strikes_present_in_symbols(self):
        symbols = [leg.symbol for leg in self.legs]
        for strike_str in ("24500", "24000", "26000", "26500"):
            assert any(strike_str in s for s in symbols)

    def test_uniform_quantity(self):
        assert all(leg.quantity == 50 for leg in self.legs)


# ---------------------------------------------------------------------------
# Iron Butterfly
# ---------------------------------------------------------------------------


class TestIronButterfly:
    """iron_butterfly: ATM short straddle + OTM wings = 4 legs."""

    def setup_method(self):
        self.legs = OptionsStrategyBuilder.iron_butterfly(
            underlying="BANKNIFTY",
            expiry="25MAY25",
            atm=52000.0,
            wing=500.0,
            lots=1,
            lot_size=15,
        )

    def test_returns_four_legs(self):
        assert len(self.legs) == 4

    def test_two_buy_two_sell(self):
        assert sum(1 for leg in self.legs if leg.action == "BUY") == 2
        assert sum(1 for leg in self.legs if leg.action == "SELL") == 2

    def test_atm_symbols_are_sell(self):
        sell_symbols = [leg.symbol for leg in self.legs if leg.action == "SELL"]
        assert all("52000" in s for s in sell_symbols)

    def test_wing_strikes(self):
        buy_symbols = [leg.symbol for leg in self.legs if leg.action == "BUY"]
        assert any("51500" in s for s in buy_symbols)
        assert any("52500" in s for s in buy_symbols)

    def test_quantity(self):
        assert all(leg.quantity == 15 for leg in self.legs)


# ---------------------------------------------------------------------------
# Bull Call Spread
# ---------------------------------------------------------------------------


class TestBullCallSpread:
    """bull_call_spread: buy lower CE + sell higher CE."""

    def setup_method(self):
        self.legs = OptionsStrategyBuilder.bull_call_spread(
            underlying="NIFTY",
            expiry="25MAY25",
            long_strike=25000.0,
            short_strike=26000.0,
            lots=1,
            lot_size=50,
        )

    def test_returns_two_legs(self):
        assert len(self.legs) == 2

    def test_all_calls(self):
        assert all("CE" in leg.symbol for leg in self.legs)

    def test_buy_lower_strike(self):
        buy_leg = next(leg for leg in self.legs if leg.action == "BUY")
        assert "25000" in buy_leg.symbol

    def test_sell_higher_strike(self):
        sell_leg = next(leg for leg in self.legs if leg.action == "SELL")
        assert "26000" in sell_leg.symbol

    def test_invalid_strikes_raise(self):
        with pytest.raises(ValueError, match="long_strike"):
            OptionsStrategyBuilder.bull_call_spread("NIFTY", "25MAY25", 26000.0, 25000.0, 1)

    def test_equal_strikes_raise(self):
        with pytest.raises(ValueError, match="long_strike"):
            OptionsStrategyBuilder.bull_call_spread("NIFTY", "25MAY25", 25000.0, 25000.0, 1)


# ---------------------------------------------------------------------------
# Bear Put Spread
# ---------------------------------------------------------------------------


class TestBearPutSpread:
    """bear_put_spread: buy higher PE + sell lower PE."""

    def setup_method(self):
        self.legs = OptionsStrategyBuilder.bear_put_spread(
            underlying="NIFTY",
            expiry="25MAY25",
            long_strike=25000.0,
            short_strike=24000.0,
            lots=1,
            lot_size=50,
        )

    def test_returns_two_legs(self):
        assert len(self.legs) == 2

    def test_all_puts(self):
        assert all("PE" in leg.symbol for leg in self.legs)

    def test_buy_higher_strike(self):
        buy_leg = next(leg for leg in self.legs if leg.action == "BUY")
        assert "25000" in buy_leg.symbol

    def test_sell_lower_strike(self):
        sell_leg = next(leg for leg in self.legs if leg.action == "SELL")
        assert "24000" in sell_leg.symbol

    def test_invalid_strikes_raise(self):
        with pytest.raises(ValueError, match="long_strike"):
            OptionsStrategyBuilder.bear_put_spread("NIFTY", "25MAY25", 24000.0, 25000.0, 1)

    def test_equal_strikes_raise(self):
        with pytest.raises(ValueError, match="long_strike"):
            OptionsStrategyBuilder.bear_put_spread("NIFTY", "25MAY25", 25000.0, 25000.0, 1)


# ---------------------------------------------------------------------------
# Strategy legs are valid BasketLeg instances
# ---------------------------------------------------------------------------


class TestLegsAreBasketLegs:
    """All strategy builders return valid BasketLeg lists."""

    def test_short_straddle_produces_basket_legs(self):
        legs = OptionsStrategyBuilder.short_straddle("NIFTY", "25MAY25", 25000.0, 1)
        assert all(isinstance(leg, BasketLeg) for leg in legs)

    def test_iron_condor_produces_basket_legs(self):
        legs = OptionsStrategyBuilder.iron_condor("NIFTY", "25MAY25", 24500, 24000, 26000, 26500, 1)
        assert all(isinstance(leg, BasketLeg) for leg in legs)

    def test_custom_exchange_propagated(self):
        legs = OptionsStrategyBuilder.short_straddle(
            "SENSEX", "25MAY25", 80000.0, 1, lot_size=10, exchange="BFO"
        )
        assert all(leg.exchange == "BFO" for leg in legs)
