"""Tests for volatility surface interpolation module.

All tests use synthetic multi-expiry chain data — no API calls required.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chain_data(
    dte: int,
    spot: float = 24000.0,
    step: float = 100.0,
    count: int = 10,
    iv_base: float = 15.0,
) -> dict:
    """Create synthetic chain data dict for a single expiry."""
    strikes = []
    for i in range(-count, count + 1):
        k = spot + i * step
        dist = abs(i)
        iv = iv_base + dist * 0.6
        ce_ltp = max(1.0, 200 - max(0, i) * 15)
        pe_ltp = max(1.0, 200 + min(0, i) * 15)
        strikes.append({
            "strike": k,
            "ce_ltp": ce_ltp,
            "pe_ltp": pe_ltp,
            "ce_iv": iv,
            "pe_iv": iv + 0.5,
        })
    return {"dte": dte, "spot": spot, "strikes": strikes}


def _make_multi_expiry(spot: float = 24000.0) -> dict:
    """Create three expiry chains (near, mid, far)."""
    return {
        "26MAR26": _make_chain_data(dte=7, spot=spot, iv_base=14.0),
        "24APR26": _make_chain_data(dte=37, spot=spot, iv_base=16.0),
        "29MAY26": _make_chain_data(dte=67, spot=spot, iv_base=18.0),
    }


# ---------------------------------------------------------------------------
# Surface structure
# ---------------------------------------------------------------------------


class TestVolSurfaceStructure:
    """Verify the shape and structure of the vol surface output."""

    def test_result_has_strikes(self):
        from packages.screener.src.vol_surface import calculate_vol_surface
        chains = _make_multi_expiry()
        result = calculate_vol_surface(chains, spot=24000.0)
        assert len(result.strikes) > 0

    def test_result_has_expiries(self):
        from packages.screener.src.vol_surface import calculate_vol_surface
        chains = _make_multi_expiry()
        result = calculate_vol_surface(chains, spot=24000.0)
        assert len(result.expiries_dte) == 3

    def test_expiries_sorted_ascending(self):
        from packages.screener.src.vol_surface import calculate_vol_surface
        chains = _make_multi_expiry()
        result = calculate_vol_surface(chains, spot=24000.0)
        dtes = result.expiries_dte
        assert dtes == sorted(dtes)

    def test_iv_matrix_dimensions(self):
        """iv_matrix should have shape [n_expiries][n_strikes]."""
        from packages.screener.src.vol_surface import calculate_vol_surface
        chains = _make_multi_expiry()
        result = calculate_vol_surface(chains, spot=24000.0)
        n_expiries = len(result.expiries_dte)
        n_strikes = len(result.strikes)
        assert len(result.iv_matrix) == n_expiries
        for row in result.iv_matrix:
            assert len(row) == n_strikes

    def test_atm_ivs_count_matches_expiries(self):
        from packages.screener.src.vol_surface import calculate_vol_surface
        chains = _make_multi_expiry()
        result = calculate_vol_surface(chains, spot=24000.0)
        assert len(result.atm_ivs) == len(result.expiries_dte)

    def test_expiry_labels_match_expiries(self):
        from packages.screener.src.vol_surface import calculate_vol_surface
        chains = _make_multi_expiry()
        result = calculate_vol_surface(chains, spot=24000.0)
        assert len(result.expiry_labels) == len(result.expiries_dte)
        assert "26MAR26" in result.expiry_labels


# ---------------------------------------------------------------------------
# IV values
# ---------------------------------------------------------------------------


class TestVolSurfaceIVValues:
    """Verify IV values are reasonable."""

    def test_iv_values_are_positive(self):
        from packages.screener.src.vol_surface import calculate_vol_surface
        chains = _make_multi_expiry()
        result = calculate_vol_surface(chains, spot=24000.0)
        for row in result.iv_matrix:
            for iv in row:
                assert iv >= 0, f"IV should be non-negative, got {iv}"

    def test_atm_ivs_positive(self):
        from packages.screener.src.vol_surface import calculate_vol_surface
        chains = _make_multi_expiry()
        result = calculate_vol_surface(chains, spot=24000.0)
        for atm_iv in result.atm_ivs:
            assert atm_iv > 0

    def test_term_structure_increasing(self):
        """Longer expiries should have higher base IV (normal term structure)."""
        from packages.screener.src.vol_surface import calculate_vol_surface
        chains = _make_multi_expiry()
        result = calculate_vol_surface(chains, spot=24000.0)
        # Our synthetic data has iv_base 14, 16, 18 for near, mid, far
        atm_ivs = result.atm_ivs
        assert atm_ivs[0] < atm_ivs[-1], "Near expiry ATM IV should be less than far expiry"

    def test_strike_count_limit_applied(self):
        from packages.screener.src.vol_surface import calculate_vol_surface
        chains = _make_multi_expiry()
        result = calculate_vol_surface(chains, spot=24000.0, strike_count=10)
        assert len(result.strikes) <= 10


# ---------------------------------------------------------------------------
# Black-76 IV solver
# ---------------------------------------------------------------------------


class TestBlack76IV:
    """Test the internal Black-76 IV bisection solver."""

    def test_iv_solver_atm_option(self):
        from packages.screener.src.vol_surface import _black76_iv, _black76_call
        # For ATM option, IV should round-trip
        iv = 0.20  # 20%
        price = _black76_call(F=24000, K=24000, T=30 / 365, sigma=iv)
        recovered_iv = _black76_iv(price, F=24000, K=24000, T=30 / 365)
        assert recovered_iv == pytest.approx(iv, abs=0.005)

    def test_iv_solver_zero_time_returns_zero(self):
        from packages.screener.src.vol_surface import _black76_iv
        iv = _black76_iv(100.0, F=24000, K=24000, T=0)
        assert iv == 0.0

    def test_iv_solver_zero_price_returns_zero(self):
        from packages.screener.src.vol_surface import _black76_iv
        iv = _black76_iv(0.0, F=24000, K=24000, T=30 / 365)
        assert iv == 0.0

    def test_black76_call_price_positive(self):
        from packages.screener.src.vol_surface import _black76_call
        price = _black76_call(F=24000, K=24000, T=30 / 365, sigma=0.15)
        assert price > 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestVolSurfaceEdgeCases:
    """Edge case handling for vol surface calculation."""

    def test_empty_chains_returns_empty(self):
        from packages.screener.src.vol_surface import calculate_vol_surface
        result = calculate_vol_surface({}, spot=24000.0)
        assert result.strikes == []
        assert result.iv_matrix == []

    def test_zero_spot_returns_empty(self):
        from packages.screener.src.vol_surface import calculate_vol_surface
        chains = _make_multi_expiry()
        result = calculate_vol_surface(chains, spot=0.0)
        assert result.strikes == []

    def test_single_expiry_works(self):
        from packages.screener.src.vol_surface import calculate_vol_surface
        chains = {"26MAR26": _make_chain_data(dte=7)}
        result = calculate_vol_surface(chains, spot=24000.0)
        assert len(result.expiries_dte) == 1
        assert len(result.iv_matrix) == 1

    def test_fallback_when_iv_missing(self):
        """When ce_iv/pe_iv are 0, Black-76 fallback should still produce IVs."""
        from packages.screener.src.vol_surface import calculate_vol_surface
        chain = {
            "26MAR26": {
                "dte": 15,
                "spot": 24000.0,
                "strikes": [
                    {"strike": 24000, "ce_ltp": 200.0, "pe_ltp": 210.0, "ce_iv": 0, "pe_iv": 0},
                    {"strike": 24100, "ce_ltp": 150.0, "pe_ltp": 250.0, "ce_iv": 0, "pe_iv": 0},
                ],
            }
        }
        result = calculate_vol_surface(chain, spot=24000.0)
        # Surface should be built even without pre-computed IVs
        assert len(result.strikes) > 0
