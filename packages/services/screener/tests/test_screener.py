"""Tests for FlintTrade screener package.

DO NOT RUN — written for pytest. All tests use synthetic data, no API calls.
"""

from __future__ import annotations

import os

import pytest


# ======================================================================
# Helpers — build test option chain snapshots
# ======================================================================

def _make_strikes(
    center: float = 24000,
    step: float = 100,
    count: int = 10,
    ce_oi_base: int = 50000,
    pe_oi_base: int = 40000,
):
    """Generate synthetic strike data around a center."""
    from flinttrade_screener.option_chain import StrikeData

    strikes = []
    for i in range(-count, count + 1):
        sp = center + i * step
        # OI peaks at the center and diminishes outward
        distance = abs(i)
        ce_oi = max(1000, ce_oi_base - distance * 5000)
        pe_oi = max(1000, pe_oi_base - distance * 4000)
        strikes.append(StrikeData(
            strike_price=sp,
            ce_ltp=max(1.0, (center - sp) + 200) if sp < center else max(1.0, 200 - (sp - center)),
            ce_oi=ce_oi,
            ce_volume=ce_oi // 10,
            ce_iv=15.0 + distance * 0.5,
            ce_delta=max(0.05, 0.5 - i * 0.05) if i <= 0 else max(0.05, 0.5 - i * 0.05),
            pe_ltp=max(1.0, (sp - center) + 200) if sp > center else max(1.0, 200 - (center - sp)),
            pe_oi=pe_oi,
            pe_volume=pe_oi // 10,
            pe_iv=15.0 + distance * 0.5,
            pe_delta=-max(0.05, 0.5 + i * 0.05) if i >= 0 else -max(0.05, 0.5 + i * 0.05),
        ))
    return strikes


def _make_snapshot(center: float = 24000, **kwargs):
    from flinttrade_screener.option_chain import OptionChainSnapshot
    strikes = _make_strikes(center=center, **kwargs)
    return OptionChainSnapshot(
        underlying="NIFTY",
        exchange="NFO",
        spot_price=center,
        atm_strike=center,
        strikes=strikes,
    )


# ======================================================================
# PCR
# ======================================================================


class TestPCR:
    """Test Put-Call Ratio calculation."""

    def test_pcr_basic(self):
        from flinttrade_screener.oi_analysis import OIAnalysis
        snap = _make_snapshot()
        pcr = OIAnalysis.pcr(snap)
        assert pcr.pcr_oi > 0
        assert pcr.total_ce_oi > 0
        assert pcr.total_pe_oi > 0

    def test_pcr_equal_oi(self):
        from flinttrade_screener.oi_analysis import OIAnalysis
        # With equal bases, PE diminishes slower (4000/step vs 5000/step)
        # so PCR > 1.0. Use matching decay by setting PE base lower to compensate.
        snap = _make_snapshot(ce_oi_base=50000, pe_oi_base=50000)
        pcr = OIAnalysis.pcr(snap)
        # PCR ~1.215 due to asymmetric decay in _make_strikes
        assert pcr.pcr_oi == pytest.approx(1.2, abs=0.1)

    def test_pcr_bullish_sentiment(self):
        from flinttrade_screener.oi_analysis import OIAnalysis
        # More puts than calls → bullish
        snap = _make_snapshot(ce_oi_base=30000, pe_oi_base=60000)
        pcr = OIAnalysis.pcr(snap)
        assert pcr.pcr_oi > 1.0
        assert pcr.sentiment == "BULLISH"

    def test_pcr_bearish_sentiment(self):
        from flinttrade_screener.oi_analysis import OIAnalysis
        # More calls than puts → bearish
        snap = _make_snapshot(ce_oi_base=80000, pe_oi_base=20000)
        pcr = OIAnalysis.pcr(snap)
        assert pcr.pcr_oi < 0.7
        assert pcr.sentiment == "BEARISH"

    def test_pcr_neutral_sentiment(self):
        from flinttrade_screener.oi_analysis import OIAnalysis
        snap = _make_snapshot(ce_oi_base=50000, pe_oi_base=40000)
        pcr = OIAnalysis.pcr(snap)
        assert pcr.sentiment == "NEUTRAL"

    def test_pcr_volume(self):
        from flinttrade_screener.oi_analysis import OIAnalysis
        snap = _make_snapshot()
        pcr = OIAnalysis.pcr(snap)
        assert pcr.pcr_volume > 0
        assert pcr.total_ce_volume > 0
        assert pcr.total_pe_volume > 0

    def test_pcr_zero_ce_oi(self):
        from flinttrade_screener.oi_analysis import OIAnalysis
        # ce_oi_base=0 still produces min 1000 per strike due to max(1000, ...)
        # so total CE OI > 0 and PCR is high (PE total / CE total)
        snap = _make_snapshot(ce_oi_base=0)
        pcr = OIAnalysis.pcr(snap)
        assert pcr.pcr_oi > 1.0  # PE OI >> CE OI (which is clamped to 1000/strike)


# ======================================================================
# Max Pain
# ======================================================================


class TestMaxPain:
    """Test Max Pain algorithm."""

    def test_max_pain_returns_strike(self):
        from flinttrade_screener.oi_analysis import OIAnalysis
        snap = _make_snapshot()
        result = OIAnalysis.max_pain(snap)
        assert result.max_pain_strike > 0
        assert result.total_loss_at_max_pain >= 0

    def test_max_pain_near_atm(self):
        from flinttrade_screener.oi_analysis import OIAnalysis
        snap = _make_snapshot(center=24000)
        result = OIAnalysis.max_pain(snap)
        # Max pain should be near ATM when OI is symmetric
        assert abs(result.max_pain_strike - 24000) <= 500

    def test_max_pain_strike_losses_count(self):
        from flinttrade_screener.oi_analysis import OIAnalysis
        snap = _make_snapshot(count=5)
        result = OIAnalysis.max_pain(snap)
        assert len(result.strike_losses) == len(snap.strikes)

    def test_max_pain_empty_chain(self):
        from flinttrade_screener.oi_analysis import OIAnalysis
        from flinttrade_screener.option_chain import OptionChainSnapshot
        empty = OptionChainSnapshot()
        result = OIAnalysis.max_pain(empty)
        assert result.max_pain_strike == 0

    def test_max_pain_is_minimum_loss(self):
        from flinttrade_screener.oi_analysis import OIAnalysis
        snap = _make_snapshot()
        result = OIAnalysis.max_pain(snap)
        all_losses = [sl["total_loss"] for sl in result.strike_losses]
        assert result.total_loss_at_max_pain == min(all_losses)

    def test_max_pain_skewed_oi(self):
        from flinttrade_screener.oi_analysis import OIAnalysis
        # Heavy put OI at 23500, heavy call OI at 24500
        from flinttrade_screener.option_chain import OptionChainSnapshot, StrikeData
        strikes = [
            StrikeData(strike_price=23500, ce_oi=1000, pe_oi=100000, ce_ltp=500, pe_ltp=10),
            StrikeData(strike_price=24000, ce_oi=5000, pe_oi=5000, ce_ltp=200, pe_ltp=200),
            StrikeData(strike_price=24500, ce_oi=100000, pe_oi=1000, ce_ltp=10, pe_ltp=500),
        ]
        snap = OptionChainSnapshot(underlying="NIFTY", strikes=strikes, spot_price=24000, atm_strike=24000)
        result = OIAnalysis.max_pain(snap)
        # Max pain should be around 24000 where both sides lose least
        assert result.max_pain_strike == 24000


# ======================================================================
# Futures Quadrant
# ======================================================================


class TestFuturesQuadrant:
    """Test 4-quadrant classification."""

    def test_long_buildup(self):
        from flinttrade_screener.futures_quadrant import FuturesQuadrant, FuturesSnapshot
        curr = FuturesSnapshot(symbol="NIFTYFUT", exchange="NFO", price=24100, oi=500000)
        prev = FuturesSnapshot(symbol="NIFTYFUT", exchange="NFO", price=24000, oi=450000)
        result = FuturesQuadrant.classify(curr, prev)
        assert result.quadrant.value == "LONG_BUILDUP"
        assert result.is_bullish

    def test_short_buildup(self):
        from flinttrade_screener.futures_quadrant import FuturesQuadrant, FuturesSnapshot
        curr = FuturesSnapshot(symbol="NIFTYFUT", exchange="NFO", price=23900, oi=500000)
        prev = FuturesSnapshot(symbol="NIFTYFUT", exchange="NFO", price=24000, oi=450000)
        result = FuturesQuadrant.classify(curr, prev)
        assert result.quadrant.value == "SHORT_BUILDUP"
        assert result.is_bearish

    def test_short_covering(self):
        from flinttrade_screener.futures_quadrant import FuturesQuadrant, FuturesSnapshot
        curr = FuturesSnapshot(symbol="NIFTYFUT", exchange="NFO", price=24100, oi=400000)
        prev = FuturesSnapshot(symbol="NIFTYFUT", exchange="NFO", price=24000, oi=450000)
        result = FuturesQuadrant.classify(curr, prev)
        assert result.quadrant.value == "SHORT_COVERING"
        assert result.is_bullish

    def test_long_unwinding(self):
        from flinttrade_screener.futures_quadrant import FuturesQuadrant, FuturesSnapshot
        curr = FuturesSnapshot(symbol="NIFTYFUT", exchange="NFO", price=23900, oi=400000)
        prev = FuturesSnapshot(symbol="NIFTYFUT", exchange="NFO", price=24000, oi=450000)
        result = FuturesQuadrant.classify(curr, prev)
        assert result.quadrant.value == "LONG_UNWINDING"
        assert result.is_bearish

    def test_neutral(self):
        from flinttrade_screener.futures_quadrant import FuturesQuadrant, FuturesSnapshot
        curr = FuturesSnapshot(price=24000, oi=450000)
        prev = FuturesSnapshot(price=24000, oi=450000)
        result = FuturesQuadrant.classify(curr, prev)
        assert result.quadrant.value == "NEUTRAL"

    def test_price_change_pct(self):
        from flinttrade_screener.futures_quadrant import FuturesQuadrant, FuturesSnapshot
        curr = FuturesSnapshot(price=24240, oi=500000)
        prev = FuturesSnapshot(price=24000, oi=450000)
        result = FuturesQuadrant.classify(curr, prev)
        assert result.price_change_pct == pytest.approx(1.0, abs=0.01)

    def test_basis_premium(self):
        from flinttrade_screener.futures_quadrant import FuturesQuadrant
        result = FuturesQuadrant.basis(spot=24000, futures=24050, days_to_expiry=15)
        assert result.is_premium
        assert result.basis == 50.0
        assert result.basis_pct > 0
        assert result.annualized_basis_pct > 0

    def test_basis_discount(self):
        from flinttrade_screener.futures_quadrant import FuturesQuadrant
        result = FuturesQuadrant.basis(spot=24000, futures=23950)
        assert result.is_discount
        assert result.basis == -50.0

    def test_rollover(self):
        from flinttrade_screener.futures_quadrant import FuturesQuadrant
        result = FuturesQuadrant.rollover(current_series_oi=400000, next_series_oi=100000)
        assert result.rollover_pct == 20.0
        assert result.total_oi == 500000

    def test_rollover_zero(self):
        from flinttrade_screener.futures_quadrant import FuturesQuadrant
        result = FuturesQuadrant.rollover(current_series_oi=0, next_series_oi=0)
        assert result.rollover_pct == 0.0

    def test_classify_batch(self):
        from flinttrade_screener.futures_quadrant import FuturesQuadrant, FuturesSnapshot
        current = [
            FuturesSnapshot(symbol="NIFTYFUT", exchange="NFO", price=24100, oi=500000),
            FuturesSnapshot(symbol="BANKFUT", exchange="NFO", price=50000, oi=200000),
        ]
        prev_map = {
            "NFO:NIFTYFUT": FuturesSnapshot(symbol="NIFTYFUT", exchange="NFO", price=24000, oi=450000),
            "NFO:BANKFUT": FuturesSnapshot(symbol="BANKFUT", exchange="NFO", price=50200, oi=210000),
        }
        results = FuturesQuadrant.classify_batch(current, prev_map)
        assert len(results) == 2


# ======================================================================
# Portfolio Greeks
# ======================================================================


class TestPortfolioGreeks:
    """Test portfolio Greeks aggregation with position signs."""

    def test_buy_ce_positive_delta(self):
        from flinttrade_core.models import OptionGreek
        from flinttrade_screener.greeks import OptionPosition, apply_position_sign
        pos = OptionPosition(symbol="NIFTY26MAR2524000CE", option_type="CE", action="BUY", lots=1, lot_size=75)
        greek = OptionGreek(delta=0.5, gamma=0.01, theta=-5.0, vega=10.0, iv=15.0)
        pg = apply_position_sign(greek, pos)
        assert pg.delta == pytest.approx(0.5 * 75)   # positive
        assert pg.gamma == pytest.approx(0.01 * 75)   # positive
        assert pg.theta == pytest.approx(-5.0 * 75)   # negative (time decay)
        assert pg.vega == pytest.approx(10.0 * 75)    # positive

    def test_sell_ce_negative_delta(self):
        from flinttrade_core.models import OptionGreek
        from flinttrade_screener.greeks import OptionPosition, apply_position_sign
        pos = OptionPosition(symbol="NIFTY26MAR2524000CE", option_type="CE", action="SELL", lots=1, lot_size=75)
        greek = OptionGreek(delta=0.5, gamma=0.01, theta=-5.0, vega=10.0)
        pg = apply_position_sign(greek, pos)
        assert pg.delta == pytest.approx(-0.5 * 75)  # flipped
        assert pg.gamma == pytest.approx(-0.01 * 75)  # flipped
        assert pg.theta == pytest.approx(5.0 * 75)    # seller earns theta

    def test_buy_pe_negative_delta(self):
        from flinttrade_core.models import OptionGreek
        from flinttrade_screener.greeks import OptionPosition, apply_position_sign
        pos = OptionPosition(symbol="NIFTY26MAR2524000PE", option_type="PE", action="BUY", lots=1, lot_size=75)
        # PE delta from API is already negative
        greek = OptionGreek(delta=-0.5, gamma=0.01, theta=-5.0, vega=10.0)
        pg = apply_position_sign(greek, pos)
        assert pg.delta == pytest.approx(-0.5 * 75)   # BUY sign=+1, delta stays negative
        assert pg.gamma == pytest.approx(0.01 * 75)

    def test_sell_pe_positive_delta(self):
        from flinttrade_core.models import OptionGreek
        from flinttrade_screener.greeks import OptionPosition, apply_position_sign
        pos = OptionPosition(symbol="NIFTY26MAR2524000PE", option_type="PE", action="SELL", lots=1, lot_size=75)
        greek = OptionGreek(delta=-0.5, gamma=0.01, theta=-5.0, vega=10.0)
        pg = apply_position_sign(greek, pos)
        assert pg.delta == pytest.approx(0.5 * 75)    # SELL sign=-1, flips negative to positive

    def test_portfolio_aggregate(self):
        from flinttrade_core.models import OptionGreek
        from flinttrade_screener.greeks import OptionPosition, PortfolioGreeks
        positions = [
            OptionPosition(symbol="CE1", action="SELL", lots=1, lot_size=75, option_type="CE"),
            OptionPosition(symbol="PE1", action="SELL", lots=1, lot_size=75, option_type="PE"),
        ]
        greeks_map = {
            "CE1": OptionGreek(delta=0.5, gamma=0.01, theta=-5.0, vega=10.0),
            "PE1": OptionGreek(delta=-0.5, gamma=0.01, theta=-5.0, vega=10.0),
        }
        pg = PortfolioGreeks()
        result = pg.calculate(positions, greeks_override=greeks_map)
        # Short straddle: CE delta(-37.5) + PE delta(37.5) = 0
        assert result.net_delta == pytest.approx(0.0, abs=0.01)
        assert result.is_delta_neutral
        assert result.position_count == 2

    def test_portfolio_lot_size_lookup(self):
        from flinttrade_screener.greeks import PortfolioGreeks
        assert PortfolioGreeks.from_lot_size("NIFTY", 2) == 150
        assert PortfolioGreeks.from_lot_size("BANKNIFTY", 1) == 30

    def test_local_greeks_fallback(self):
        from flinttrade_screener.greeks import PortfolioGreeks
        g = PortfolioGreeks.local_greeks(
            option_type="CE", spot=24000, strike=24000,
            time_to_expiry=7 / 365, iv=0.15,
        )
        assert g.delta > 0  # ATM CE delta ~0.5
        assert g.delta < 1.0
        assert g.gamma > 0
        assert g.vega > 0

    def test_local_greeks_pe(self):
        from flinttrade_screener.greeks import PortfolioGreeks
        g = PortfolioGreeks.local_greeks(
            option_type="PE", spot=24000, strike=24000,
            time_to_expiry=7 / 365, iv=0.15,
        )
        assert g.delta < 0  # ATM PE delta ~-0.5

    def test_local_greeks_deep_itm(self):
        from flinttrade_screener.greeks import PortfolioGreeks
        g = PortfolioGreeks.local_greeks(
            option_type="CE", spot=24000, strike=22000,
            time_to_expiry=30 / 365, iv=0.15,
        )
        assert g.delta > 0.9  # Deep ITM CE → delta near 1.0

    def test_local_greeks_zero_time(self):
        from flinttrade_screener.greeks import PortfolioGreeks
        g = PortfolioGreeks.local_greeks(
            option_type="CE", spot=24000, strike=24000,
            time_to_expiry=0, iv=0.15,
        )
        # Should not crash with T=0
        assert g.iv > 0

    def test_expiry_times(self):
        from flinttrade_screener.greeks import EXPIRY_TIMES
        assert EXPIRY_TIMES["MCX"] == (23, 30)
        assert EXPIRY_TIMES["CDS"] == (12, 30)
        assert EXPIRY_TIMES["NFO"] == (15, 30)


# ======================================================================
# IV Percentile
# ======================================================================


class TestIVAnalysis:
    """Test IV percentile, skew, and term structure."""

    def test_iv_percentile_basic(self):
        from flinttrade_screener.iv_analysis import IVAnalysis
        history = [10, 12, 14, 16, 18, 20, 22, 24, 26, 28]
        result = IVAnalysis.iv_percentile(current_iv=18, history=history)
        assert result.percentile > 0
        assert result.percentile < 100
        assert result.iv_min == 10
        assert result.iv_max == 28

    def test_iv_percentile_lowest(self):
        from flinttrade_screener.iv_analysis import IVAnalysis
        history = [10, 20, 30]
        result = IVAnalysis.iv_percentile(current_iv=5, history=history)
        assert result.percentile == 0.0  # below all
        assert result.is_low

    def test_iv_percentile_highest(self):
        from flinttrade_screener.iv_analysis import IVAnalysis
        history = [10, 20, 30]
        result = IVAnalysis.iv_percentile(current_iv=35, history=history)
        assert result.percentile == 100.0  # above all
        assert result.is_high

    def test_iv_rank(self):
        from flinttrade_screener.iv_analysis import IVAnalysis
        history = [10, 20, 30]
        result = IVAnalysis.iv_percentile(current_iv=20, history=history)
        assert result.iv_rank == pytest.approx(50.0)  # (20-10)/(30-10)*100

    def test_iv_percentile_empty_history(self):
        from flinttrade_screener.iv_analysis import IVAnalysis
        result = IVAnalysis.iv_percentile(current_iv=18, history=[])
        assert result.percentile == 0.0

    def test_iv_skew(self):
        from flinttrade_screener.iv_analysis import IVAnalysis
        snap = _make_snapshot()
        skew = IVAnalysis.skew(snap)
        assert len(skew.points) > 0
        assert skew.underlying == "NIFTY"
        assert skew.spot_price == 24000

    def test_iv_skew_slope(self):
        from flinttrade_screener.iv_analysis import IVAnalysis
        snap = _make_snapshot()
        skew = IVAnalysis.skew(snap)
        # Our synthetic data has higher IV at the wings, so slope should exist
        assert isinstance(skew.skew_slope, float)

    def test_atm_iv(self):
        from flinttrade_screener.iv_analysis import IVAnalysis
        snap = _make_snapshot()
        atm = IVAnalysis.atm_iv(snap)
        assert atm > 0

    def test_term_structure(self):
        from flinttrade_screener.iv_analysis import IVAnalysis
        snap1 = _make_snapshot()
        snap2 = _make_snapshot()
        # Override ATM IVs to simulate term structure
        for s in snap1.strikes:
            if s.strike_price == 24000:
                s.ce_iv = 18.0
                s.pe_iv = 18.5
        for s in snap2.strikes:
            if s.strike_price == 24000:
                s.ce_iv = 16.0
                s.pe_iv = 16.5
        ts = IVAnalysis.term_structure([
            ("26MAR26", 7, snap1),
            ("26APR26", 37, snap2),
        ])
        assert len(ts.points) == 2
        assert ts.points[0].days_to_expiry < ts.points[1].days_to_expiry


# ======================================================================
# OI Analysis — Support/Resistance, OI Change, Spurt
# ======================================================================


class TestOIAnalysis:
    """Test OI analysis helpers."""

    def test_support_resistance(self):
        from flinttrade_screener.oi_analysis import OIAnalysis
        snap = _make_snapshot()
        sr = OIAnalysis.support_resistance(snap)
        assert sr.resistance_strike > 0
        assert sr.support_strike > 0
        assert sr.resistance_oi > 0
        assert sr.support_oi > 0

    def test_oi_change(self):
        from flinttrade_screener.oi_analysis import OIAnalysis
        prev = _make_snapshot()
        curr = _make_snapshot()
        # Increase some OI
        for s in curr.strikes:
            if s.strike_price == 24000:
                s.ce_oi += 10000
                s.pe_oi -= 5000
        changes = OIAnalysis.oi_change(curr, prev)
        assert len(changes) > 0
        atm_change = [c for c in changes if c.strike_price == 24000][0]
        assert atm_change.ce_oi_change == 10000
        assert atm_change.ce_writing
        assert atm_change.pe_oi_change == -5000
        assert atm_change.pe_unwinding

    def test_oi_spurt(self):
        from flinttrade_screener.oi_analysis import OIAnalysis
        prev = _make_snapshot(ce_oi_base=10000, pe_oi_base=10000)
        curr = _make_snapshot(ce_oi_base=10000, pe_oi_base=10000)
        # Create a big spurt at one strike
        for s in curr.strikes:
            if s.strike_price == 24000:
                s.ce_oi = 15000  # +50% from 10000
        spurts = OIAnalysis.oi_spurt(curr, prev, threshold_pct=20.0)
        ce_spurts = [sp for sp in spurts if sp.option_type == "CE" and sp.strike_price == 24000]
        assert len(ce_spurts) == 1
        assert ce_spurts[0].change_pct == pytest.approx(50.0, abs=1.0)

    def test_top_oi_strikes(self):
        from flinttrade_screener.oi_analysis import OIAnalysis
        snap = _make_snapshot()
        top = OIAnalysis.top_oi_strikes(snap, n=3)
        assert len(top["top_ce_oi"]) == 3
        assert len(top["top_pe_oi"]) == 3
        # Top should be sorted descending by OI
        assert top["top_ce_oi"][0].ce_oi >= top["top_ce_oi"][1].ce_oi


# ======================================================================
# Option Chain Helpers
# ======================================================================


class TestOptionChainHelpers:
    """Test option chain utilities."""

    def test_find_atm_strike(self):
        from flinttrade_screener.option_chain import find_atm_strike
        strikes = [23800, 23900, 24000, 24100, 24200]
        assert find_atm_strike(24050, strikes) == 24000 or find_atm_strike(24050, strikes) == 24100

    def test_find_atm_strike_exact(self):
        from flinttrade_screener.option_chain import find_atm_strike
        strikes = [23800, 23900, 24000, 24100, 24200]
        assert find_atm_strike(24000, strikes) == 24000

    def test_find_atm_strike_empty(self):
        from flinttrade_screener.option_chain import find_atm_strike
        assert find_atm_strike(24000, []) == 0.0

    def test_lot_sizes(self):
        from flinttrade_screener.option_chain import LOT_SIZES
        assert LOT_SIZES["NIFTY"] == 75
        assert LOT_SIZES["BANKNIFTY"] == 30
        assert LOT_SIZES["SENSEX"] == 20
        assert LOT_SIZES["CRUDEOIL"] == 100
        assert LOT_SIZES["USDINR"] == 1000

    def test_strikes_near_atm(self):
        snap = _make_snapshot(count=10)
        near = snap.strikes_near_atm(3)
        assert len(near) <= 7  # 3 above + ATM + 3 below
        assert any(s.strike_price == 24000 for s in near)

    def test_snapshot_totals(self):
        snap = _make_snapshot()
        assert snap.total_ce_oi > 0
        assert snap.total_pe_oi > 0
        assert snap.total_ce_volume > 0

    def test_get_strike(self):
        snap = _make_snapshot()
        s = snap.get_strike(24000)
        assert s is not None
        assert s.strike_price == 24000

    def test_get_strike_missing(self):
        snap = _make_snapshot()
        s = snap.get_strike(99999)
        assert s is None


# ======================================================================
# Package exports
# ======================================================================


class TestPackageExports:
    """Verify __init__.py exports."""

    def test_all_exports(self):
        from flinttrade_screener import __all__
        expected = [
            "OptionChainAnalyzer", "OIAnalysis", "FuturesQuadrant",
            "PortfolioGreeks", "IVAnalysis", "Quadrant",
            "PCRResult", "MaxPainResult", "LOT_SIZES",
        ]
        for name in expected:
            assert name in __all__, f"Missing export: {name}"

    def test_version(self):
        from flinttrade_screener import __version__
        from flinttrade_core.version import APP_VERSION

        assert __version__ == APP_VERSION

    def test_package_exists(self):
        pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert os.path.exists(os.path.join(pkg_dir, "src", "flinttrade_screener", "__init__.py"))
        assert os.path.exists(os.path.join(pkg_dir, "README.md"))
