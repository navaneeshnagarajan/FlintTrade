"""Tests for enhanced portfolio Greeks module.

Covers:
- iv_percentile — range, edge cases
- iv_rank — range, edge cases, normalisation
- greeks_pnl_attribution — delta/gamma/theta/vega P&L, sign conventions
- portfolio_pcr — PCR from positions
- max_pain_enhanced — full pain surface, POC, edge cases
- EnhancedPortfolioGreeks — calculate_enhanced, attribute_pnl, pcr, rho

All tests use synthetic data — no API calls required.
"""

from __future__ import annotations

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_position(
    symbol: str,
    action: str,
    option_type: str,
    lots: int = 1,
    lot_size: int = 75,
    underlying: str = "NIFTY",
):
    from packages.screener.src.greeks import OptionPosition

    return OptionPosition(
        symbol=symbol,
        exchange="NFO",
        option_type=option_type,
        action=action,
        lots=lots,
        lot_size=lot_size,
        underlying=underlying,
    )


def _make_greeks_override(
    symbol: str,
    delta: float = 0.5,
    gamma: float = 0.01,
    theta: float = -5.0,
    vega: float = 10.0,
    iv: float = 15.0,
) -> dict:
    from packages.core.src.models import OptionGreek

    return {symbol: OptionGreek(delta=delta, gamma=gamma, theta=theta, vega=vega, iv=iv)}


# ---------------------------------------------------------------------------
# IV Percentile
# ---------------------------------------------------------------------------


class TestIVPercentile:
    def test_returns_zero_for_single_element(self):
        from packages.screener.src.portfolio_greeks import iv_percentile

        result = iv_percentile(np.array([15.0]))
        assert result == pytest.approx(0.0)

    def test_current_at_historical_high(self):
        from packages.screener.src.portfolio_greeks import iv_percentile

        history = np.array([10.0, 12.0, 14.0, 16.0, 20.0])
        result = iv_percentile(history)
        # current (20) > all previous (10,12,14,16) → 100%
        assert result == pytest.approx(1.0)

    def test_current_at_historical_low(self):
        from packages.screener.src.portfolio_greeks import iv_percentile

        history = np.array([20.0, 18.0, 16.0, 14.0, 10.0])
        result = iv_percentile(history)
        # current (10) < all previous → 0%
        assert result == pytest.approx(0.0)

    def test_midrange_value(self):
        from packages.screener.src.portfolio_greeks import iv_percentile

        history = np.array([10.0, 15.0, 20.0, 25.0, 30.0, 15.5])
        result = iv_percentile(history)
        # current=15.5; previous=[10,15,20,25,30] → 2/5 < 15.5 → 0.4
        assert result == pytest.approx(0.4)

    def test_range_0_to_1(self):
        from packages.screener.src.portfolio_greeks import iv_percentile

        rng = np.random.default_rng(42)
        history = rng.uniform(10, 30, 252)
        result = iv_percentile(history)
        assert 0.0 <= result <= 1.0

    def test_empty_array_returns_zero(self):
        from packages.screener.src.portfolio_greeks import iv_percentile

        result = iv_percentile(np.array([]))
        assert result == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# IV Rank
# ---------------------------------------------------------------------------


class TestIVRank:
    def test_returns_zero_for_single_element(self):
        from packages.screener.src.portfolio_greeks import iv_rank

        result = iv_rank(np.array([15.0]))
        assert result == pytest.approx(0.0)

    def test_at_max_returns_one(self):
        from packages.screener.src.portfolio_greeks import iv_rank

        history = np.array([10.0, 15.0, 20.0, 25.0])
        result = iv_rank(history)
        # current=25, min=10, max=25 → IVR = 1.0
        assert result == pytest.approx(1.0)

    def test_at_min_returns_zero(self):
        from packages.screener.src.portfolio_greeks import iv_rank

        history = np.array([25.0, 20.0, 15.0, 10.0])
        result = iv_rank(history)
        # current=10, min=10, max=25 → IVR = 0.0
        assert result == pytest.approx(0.0)

    def test_midpoint_value(self):
        from packages.screener.src.portfolio_greeks import iv_rank

        history = np.array([10.0, 30.0, 20.0])
        result = iv_rank(history)
        # current=20, min=10, max=30 → (20-10)/(30-10) = 0.5
        assert result == pytest.approx(0.5)

    def test_uniform_history_returns_zero(self):
        from packages.screener.src.portfolio_greeks import iv_rank

        history = np.full(10, 15.0)
        result = iv_rank(history)
        # No range → 0.0
        assert result == pytest.approx(0.0)

    def test_range_0_to_1(self):
        from packages.screener.src.portfolio_greeks import iv_rank

        rng = np.random.default_rng(7)
        history = rng.uniform(10, 30, 252)
        result = iv_rank(history)
        assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# Greeks P&L Attribution
# ---------------------------------------------------------------------------


class TestGreeksPnlAttribution:
    def test_delta_pnl_proportional_to_spot_move(self):
        from packages.screener.src.portfolio_greeks import greeks_pnl_attribution

        attr = greeks_pnl_attribution(
            net_delta=10.0, net_gamma=0.0, net_theta=0.0, net_vega=0.0,
            spot_move=100.0, iv_change=0.0, days=0.0,
        )
        assert attr.delta_pnl == pytest.approx(1000.0)

    def test_gamma_pnl_is_half_gamma_times_spot_move_squared(self):
        from packages.screener.src.portfolio_greeks import greeks_pnl_attribution

        attr = greeks_pnl_attribution(
            net_delta=0.0, net_gamma=0.02, net_theta=0.0, net_vega=0.0,
            spot_move=50.0, iv_change=0.0, days=0.0,
        )
        expected = 0.5 * 0.02 * 50.0 ** 2  # 25
        assert attr.gamma_pnl == pytest.approx(expected)

    def test_theta_pnl_over_one_day(self):
        from packages.screener.src.portfolio_greeks import greeks_pnl_attribution

        attr = greeks_pnl_attribution(
            net_delta=0.0, net_gamma=0.0, net_theta=-500.0, net_vega=0.0,
            spot_move=0.0, iv_change=0.0, days=1.0,
        )
        assert attr.theta_pnl == pytest.approx(-500.0)

    def test_vega_pnl_proportional_to_iv_change(self):
        from packages.screener.src.portfolio_greeks import greeks_pnl_attribution

        attr = greeks_pnl_attribution(
            net_delta=0.0, net_gamma=0.0, net_theta=0.0, net_vega=200.0,
            spot_move=0.0, iv_change=2.0, days=0.0,
        )
        assert attr.vega_pnl == pytest.approx(400.0)

    def test_total_is_sum_of_components(self):
        from packages.screener.src.portfolio_greeks import greeks_pnl_attribution

        attr = greeks_pnl_attribution(
            net_delta=5.0, net_gamma=0.01, net_theta=-200.0, net_vega=50.0,
            spot_move=100.0, iv_change=1.0, days=1.0,
        )
        expected_total = attr.delta_pnl + attr.gamma_pnl + attr.theta_pnl + attr.vega_pnl
        assert attr.total_greek_pnl == pytest.approx(expected_total, abs=0.01)

    def test_zero_moves_zero_pnl(self):
        from packages.screener.src.portfolio_greeks import greeks_pnl_attribution

        attr = greeks_pnl_attribution(
            net_delta=100.0, net_gamma=0.5, net_theta=-100.0, net_vega=50.0,
            spot_move=0.0, iv_change=0.0, days=0.0,
        )
        assert attr.total_greek_pnl == pytest.approx(0.0)

    def test_negative_delta_negative_pnl_on_up_move(self):
        from packages.screener.src.portfolio_greeks import greeks_pnl_attribution

        attr = greeks_pnl_attribution(
            net_delta=-10.0, net_gamma=0.0, net_theta=0.0, net_vega=0.0,
            spot_move=50.0, iv_change=0.0, days=0.0,
        )
        assert attr.delta_pnl < 0.0


# ---------------------------------------------------------------------------
# Portfolio PCR
# ---------------------------------------------------------------------------


class TestPortfolioPcr:
    def test_equal_ce_and_pe_lots_returns_one(self):
        from packages.screener.src.portfolio_greeks import portfolio_pcr

        positions = [
            _make_position("NIFTY26MAR2524000CE", "BUY", "CE", lots=2),
            _make_position("NIFTY26MAR2524000PE", "BUY", "PE", lots=2),
        ]
        assert portfolio_pcr(positions) == pytest.approx(1.0)

    def test_only_puts_returns_zero_ce_denominator(self):
        from packages.screener.src.portfolio_greeks import portfolio_pcr

        positions = [
            _make_position("NIFTY26MAR2524000PE", "BUY", "PE", lots=2),
        ]
        # No CE positions → returns 0.0
        assert portfolio_pcr(positions) == pytest.approx(0.0)

    def test_only_calls_returns_zero(self):
        from packages.screener.src.portfolio_greeks import portfolio_pcr

        positions = [
            _make_position("NIFTY26MAR2524000CE", "BUY", "CE", lots=3),
        ]
        assert portfolio_pcr(positions) == pytest.approx(0.0)

    def test_sell_positions_excluded(self):
        from packages.screener.src.portfolio_greeks import portfolio_pcr

        positions = [
            _make_position("NIFTY26MAR2524000CE", "BUY", "CE", lots=2),
            _make_position("NIFTY26MAR2524000PE", "SELL", "PE", lots=4),  # SELL excluded
        ]
        # Only BUY CE=2 counted; PE BUY=0 → pcr=0
        assert portfolio_pcr(positions) == pytest.approx(0.0)

    def test_pcr_with_mixed_lots(self):
        from packages.screener.src.portfolio_greeks import portfolio_pcr

        positions = [
            _make_position("NIFTY26MAR2524000CE", "BUY", "CE", lots=1),
            _make_position("NIFTY26MAR2524500PE", "BUY", "PE", lots=3),
        ]
        # pcr = 3/1 = 3
        assert portfolio_pcr(positions) == pytest.approx(3.0)

    def test_empty_positions_returns_zero(self):
        from packages.screener.src.portfolio_greeks import portfolio_pcr

        assert portfolio_pcr([]) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Max Pain Enhanced
# ---------------------------------------------------------------------------


class TestMaxPainEnhanced:
    def _make_chain(self):
        """Simple 5-strike chain with peak OI at 24000."""
        strikes = [23500, 23750, 24000, 24250, 24500]
        ce_oi   = [5000, 8000, 15000, 10000, 6000]
        pe_oi   = [6000, 9000, 14000,  8000, 4000]
        return strikes, ce_oi, pe_oi

    def test_returns_max_pain_result(self):
        from packages.screener.src.portfolio_greeks import max_pain_enhanced, MaxPainResult

        strikes, ce_oi, pe_oi = self._make_chain()
        result = max_pain_enhanced(strikes, ce_oi, pe_oi)
        assert isinstance(result, MaxPainResult)

    def test_pain_by_strike_has_all_strikes(self):
        from packages.screener.src.portfolio_greeks import max_pain_enhanced

        strikes, ce_oi, pe_oi = self._make_chain()
        result = max_pain_enhanced(strikes, ce_oi, pe_oi)
        for s in strikes:
            assert float(s) in result.pain_by_strike

    def test_max_pain_is_valid_strike(self):
        from packages.screener.src.portfolio_greeks import max_pain_enhanced

        strikes, ce_oi, pe_oi = self._make_chain()
        result = max_pain_enhanced(strikes, ce_oi, pe_oi)
        assert result.max_pain_strike in [float(s) for s in strikes]

    def test_min_pain_is_valid_strike(self):
        from packages.screener.src.portfolio_greeks import max_pain_enhanced

        strikes, ce_oi, pe_oi = self._make_chain()
        result = max_pain_enhanced(strikes, ce_oi, pe_oi)
        assert result.min_pain_strike in [float(s) for s in strikes]

    def test_max_pain_gte_all_others(self):
        from packages.screener.src.portfolio_greeks import max_pain_enhanced

        strikes, ce_oi, pe_oi = self._make_chain()
        result = max_pain_enhanced(strikes, ce_oi, pe_oi)
        max_val = result.pain_by_strike[result.max_pain_strike]
        for val in result.pain_by_strike.values():
            assert max_val >= val

    def test_lot_size_scales_pain_values(self):
        from packages.screener.src.portfolio_greeks import max_pain_enhanced

        strikes = [100, 110, 120]
        ce_oi   = [100, 200, 100]
        pe_oi   = [100, 200, 100]
        r1 = max_pain_enhanced(strikes, ce_oi, pe_oi, lot_size=1)
        r2 = max_pain_enhanced(strikes, ce_oi, pe_oi, lot_size=75)
        # Pain values should scale by 75
        for s in strikes:
            assert r2.pain_by_strike[float(s)] == pytest.approx(
                r1.pain_by_strike[float(s)] * 75, rel=1e-6
            )

    def test_empty_strikes_raises(self):
        from packages.screener.src.portfolio_greeks import max_pain_enhanced

        with pytest.raises(ValueError):
            max_pain_enhanced([], [], [])

    def test_mismatched_oi_lengths_raise(self):
        from packages.screener.src.portfolio_greeks import max_pain_enhanced

        with pytest.raises(ValueError):
            max_pain_enhanced([100, 110], [100], [100, 200])

    def test_single_strike_chain(self):
        from packages.screener.src.portfolio_greeks import max_pain_enhanced

        result = max_pain_enhanced([24000], [100], [100])
        assert result.max_pain_strike == pytest.approx(24000.0)


# ---------------------------------------------------------------------------
# EnhancedPortfolioGreeks
# ---------------------------------------------------------------------------


class TestEnhancedPortfolioGreeks:
    def test_calculate_enhanced_aggregates_greeks(self):
        from packages.screener.src.portfolio_greeks import EnhancedPortfolioGreeks
        from packages.core.src.models import OptionGreek

        epg = EnhancedPortfolioGreeks(client=None)
        positions = [
            _make_position("NIFTY26MAR2524000CE", "SELL", "CE", lots=2),
            _make_position("NIFTY26MAR2524000PE", "SELL", "PE", lots=2),
        ]
        override = {
            "NIFTY26MAR2524000CE": OptionGreek(delta=0.5, gamma=0.01, theta=-5.0, vega=10.0, iv=15.0),
            "NIFTY26MAR2524000PE": OptionGreek(delta=-0.5, gamma=0.01, theta=-5.0, vega=10.0, iv=15.0),
        }
        result = epg.calculate_enhanced(positions, greeks_override=override)
        assert result.position_count == 2
        # Short straddle: sell 2 CE + 2 PE
        # Net delta: SELL CE = -0.5*150, SELL PE = +0.5*150 → 0 (approx)
        assert abs(result.net_delta) < 1.0

    def test_net_theta_negative_for_long_straddle(self):
        from packages.screener.src.portfolio_greeks import EnhancedPortfolioGreeks
        from packages.core.src.models import OptionGreek

        epg = EnhancedPortfolioGreeks(client=None)
        positions = [
            _make_position("NIFTY26MAR2524000CE", "BUY", "CE", lots=1),
            _make_position("NIFTY26MAR2524000PE", "BUY", "PE", lots=1),
        ]
        override = {
            "NIFTY26MAR2524000CE": OptionGreek(delta=0.5, gamma=0.01, theta=-5.0, vega=10.0, iv=15.0),
            "NIFTY26MAR2524000PE": OptionGreek(delta=-0.5, gamma=0.01, theta=-5.0, vega=10.0, iv=15.0),
        }
        result = epg.calculate_enhanced(positions, greeks_override=override)
        # Long options → theta is negative (time decay works against buyer)
        assert result.net_theta < 0.0

    def test_rho_computed_when_spot_and_tte_provided(self):
        from packages.screener.src.portfolio_greeks import EnhancedPortfolioGreeks
        from packages.core.src.models import OptionGreek

        epg = EnhancedPortfolioGreeks(client=None)
        positions = [
            _make_position("NIFTY26MAR2524000CE", "BUY", "CE", lots=1, lot_size=75),
        ]
        override = {
            "NIFTY26MAR2524000CE": OptionGreek(delta=0.5, gamma=0.01, theta=-5.0, vega=10.0, iv=15.0),
        }
        result = epg.calculate_enhanced(
            positions,
            spot=24000.0,
            time_to_expiry=7 / 365,
            greeks_override=override,
        )
        # Rho should be non-zero when spot and tte provided
        assert result.net_rho != 0.0

    def test_attribute_pnl_via_static_method(self):
        from packages.screener.src.portfolio_greeks import EnhancedPortfolioGreeks
        from packages.screener.src.greeks import PortfolioGreeksResult

        result = PortfolioGreeksResult(
            net_delta=10.0,
            net_gamma=0.02,
            net_theta=-500.0,
            net_vega=200.0,
        )
        attr = EnhancedPortfolioGreeks.attribute_pnl(result, spot_move=100.0, iv_change=1.0, days=1.0)
        assert attr.delta_pnl == pytest.approx(1000.0)
        assert attr.theta_pnl == pytest.approx(-500.0)
        assert attr.vega_pnl == pytest.approx(200.0)

    def test_pcr_via_static_method(self):
        from packages.screener.src.portfolio_greeks import EnhancedPortfolioGreeks

        positions = [
            _make_position("NIFTY26MAR2524000CE", "BUY", "CE", lots=2),
            _make_position("NIFTY26MAR2524000PE", "BUY", "PE", lots=4),
        ]
        pcr = EnhancedPortfolioGreeks.pcr(positions)
        assert pcr == pytest.approx(2.0)

    def test_no_client_no_crash(self):
        from packages.screener.src.portfolio_greeks import EnhancedPortfolioGreeks

        epg = EnhancedPortfolioGreeks(client=None)
        positions = [_make_position("NIFTY26MAR2524000CE", "BUY", "CE")]
        # No greeks_override, no client → positions get default OptionGreek(0,0,0,0,0)
        result = epg.calculate_enhanced(positions)
        assert result.position_count == 1
        assert result.net_delta == pytest.approx(0.0)

    def test_is_delta_neutral_for_balanced_straddle(self):
        from packages.screener.src.portfolio_greeks import EnhancedPortfolioGreeks
        from packages.core.src.models import OptionGreek

        epg = EnhancedPortfolioGreeks(client=None)
        positions = [
            _make_position("NIFTY26MAR2524000CE", "SELL", "CE", lots=2),
            _make_position("NIFTY26MAR2524000PE", "SELL", "PE", lots=2),
        ]
        override = {
            "NIFTY26MAR2524000CE": OptionGreek(delta=0.5, gamma=0.01, theta=-5.0, vega=10.0, iv=15.0),
            "NIFTY26MAR2524000PE": OptionGreek(delta=-0.5, gamma=0.01, theta=-5.0, vega=10.0, iv=15.0),
        }
        result = epg.calculate_enhanced(positions, greeks_override=override)
        assert result.is_delta_neutral
