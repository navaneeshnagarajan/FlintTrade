"""Tests for GEX (Gamma Exposure) calculation module.

All tests use synthetic data — no API calls or broker connections required.
"""

from __future__ import annotations

import pytest

from packages.screener.src.option_chain import OptionChainSnapshot, StrikeData


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chain(
    spot: float = 24000.0,
    step: float = 100.0,
    count: int = 5,
    gamma: float = 0.003,
    ce_oi: int = 50000,
    pe_oi: int = 40000,
) -> OptionChainSnapshot:
    """Build a synthetic option chain for GEX tests."""
    strikes = []
    for i in range(-count, count + 1):
        k = spot + i * step
        dist = abs(i)
        g = max(0.0001, gamma - dist * 0.0002)
        strikes.append(StrikeData(
            strike_price=k,
            ce_oi=max(1000, ce_oi - dist * 5000),
            pe_oi=max(1000, pe_oi - dist * 4000),
            ce_gamma=g,
            pe_gamma=g,
            ce_ltp=max(1.0, 200 - max(0, i) * 10),
            pe_ltp=max(1.0, 200 + min(0, i) * 10),
        ))
    return OptionChainSnapshot(
        underlying="NIFTY",
        exchange="NFO",
        spot_price=spot,
        atm_strike=spot,
        strikes=strikes,
    )


# ---------------------------------------------------------------------------
# GEX formula correctness
# ---------------------------------------------------------------------------


class TestGEXFormula:
    """Verify the GEX calculation formula and sign convention."""

    def test_call_gex_positive(self):
        from packages.screener.src.gex import calculate_gex
        chain = _make_chain(spot=24000, count=1)
        result = calculate_gex(chain, spot=24000, lot_size=75)
        for s in result.strikes:
            assert s.call_gex >= 0, f"Call GEX should be positive at {s.strike_price}"

    def test_put_gex_negative(self):
        from packages.screener.src.gex import calculate_gex
        chain = _make_chain(spot=24000, count=1)
        result = calculate_gex(chain, spot=24000, lot_size=75)
        for s in result.strikes:
            assert s.put_gex <= 0, f"Put GEX should be negative at {s.strike_price}"

    def test_gex_formula_single_strike(self):
        """Verify GEX = gamma * OI * lot_size * spot^2 / 100."""
        from packages.screener.src.gex import calculate_gex
        strike = StrikeData(
            strike_price=24000,
            ce_gamma=0.005,
            pe_gamma=0.005,
            ce_oi=50000,
            pe_oi=40000,
        )
        chain = OptionChainSnapshot(
            underlying="NIFTY",
            spot_price=24000,
            atm_strike=24000,
            strikes=[strike],
        )
        result = calculate_gex(chain, spot=24000, lot_size=75)
        assert len(result.strikes) == 1
        gs = result.strikes[0]

        expected_call = 0.005 * 50000 * 75 * (24000 ** 2) / 100
        expected_put = -(0.005 * 40000 * 75 * (24000 ** 2) / 100)

        assert gs.call_gex == pytest.approx(expected_call, rel=1e-6)
        assert gs.put_gex == pytest.approx(expected_put, rel=1e-6)

    def test_net_gex_equals_call_plus_put(self):
        from packages.screener.src.gex import calculate_gex
        chain = _make_chain()
        result = calculate_gex(chain, spot=24000, lot_size=75)
        for s in result.strikes:
            assert s.net_gex == pytest.approx(s.call_gex + s.put_gex, rel=1e-9)

    def test_total_net_gex_sums(self):
        from packages.screener.src.gex import calculate_gex
        chain = _make_chain()
        result = calculate_gex(chain, spot=24000, lot_size=75)
        expected_total = result.total_call_gex + result.total_put_gex
        assert result.total_net_gex == pytest.approx(expected_total, rel=1e-9)


# ---------------------------------------------------------------------------
# GEX result structure
# ---------------------------------------------------------------------------


class TestGEXResult:
    """Validate GEXResult structure and aggregation."""

    def test_result_has_strikes(self):
        from packages.screener.src.gex import calculate_gex
        chain = _make_chain(count=5)
        result = calculate_gex(chain, spot=24000, lot_size=75)
        assert len(result.strikes) == len(chain.strikes)

    def test_top_gamma_strikes_count(self):
        from packages.screener.src.gex import calculate_gex
        chain = _make_chain(count=10)
        result = calculate_gex(chain, spot=24000, lot_size=75)
        assert len(result.top_gamma_strikes) <= 5

    def test_top_gamma_strikes_ordered_by_abs_net_gex(self):
        from packages.screener.src.gex import calculate_gex
        chain = _make_chain(count=10)
        result = calculate_gex(chain, spot=24000, lot_size=75)
        top = result.top_gamma_strikes
        for i in range(len(top) - 1):
            assert abs(top[i].net_gex) >= abs(top[i + 1].net_gex)

    def test_oi_walls_contain_ce_and_pe(self):
        from packages.screener.src.gex import calculate_gex
        chain = _make_chain(count=5)
        result = calculate_gex(chain, spot=24000, lot_size=75)
        option_types = {w.option_type for w in result.oi_walls}
        assert "CE" in option_types
        assert "PE" in option_types

    def test_spot_and_lot_size_stored(self):
        from packages.screener.src.gex import calculate_gex
        chain = _make_chain()
        result = calculate_gex(chain, spot=24000, lot_size=75)
        assert result.spot == 24000
        assert result.lot_size == 75


# ---------------------------------------------------------------------------
# Long/short gamma detection
# ---------------------------------------------------------------------------


class TestGEXSentiment:
    """Test long/short gamma classification."""

    def test_long_gamma_when_call_oi_dominates(self):
        """When call OI >> put OI, net GEX should be positive."""
        from packages.screener.src.gex import calculate_gex
        chain = _make_chain(ce_oi=100000, pe_oi=10000)
        result = calculate_gex(chain, spot=24000, lot_size=75)
        assert result.is_long_gamma

    def test_short_gamma_when_put_oi_dominates(self):
        """When put OI >> call OI, net GEX should be negative."""
        from packages.screener.src.gex import calculate_gex
        chain = _make_chain(ce_oi=10000, pe_oi=100000)
        result = calculate_gex(chain, spot=24000, lot_size=75)
        assert result.is_short_gamma


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestGEXEdgeCases:
    """Edge case handling for GEX calculation."""

    def test_empty_chain_returns_empty_result(self):
        from packages.screener.src.gex import calculate_gex
        empty = OptionChainSnapshot()
        result = calculate_gex(empty, spot=24000, lot_size=75)
        assert result.strikes == []
        assert result.total_net_gex == 0.0

    def test_zero_spot_returns_empty_result(self):
        from packages.screener.src.gex import calculate_gex
        chain = _make_chain()
        result = calculate_gex(chain, spot=0, lot_size=75)
        assert result.total_net_gex == 0.0

    def test_zero_lot_size_returns_empty_result(self):
        from packages.screener.src.gex import calculate_gex
        chain = _make_chain()
        result = calculate_gex(chain, spot=24000, lot_size=0)
        assert result.total_net_gex == 0.0

    def test_zero_gamma_strikes_produce_zero_gex(self):
        from packages.screener.src.gex import calculate_gex
        strike = StrikeData(
            strike_price=24000, ce_gamma=0.0, pe_gamma=0.0,
            ce_oi=50000, pe_oi=40000,
        )
        chain = OptionChainSnapshot(strikes=[strike], spot_price=24000)
        result = calculate_gex(chain, spot=24000, lot_size=75)
        assert result.total_net_gex == pytest.approx(0.0)
