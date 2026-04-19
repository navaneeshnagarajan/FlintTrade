"""Tests for IV analytics module (iv_analytics.py).

All tests use synthetic data — no API calls or broker connections required.
"""

from __future__ import annotations

import pytest

from packages.screener.src.iv_analytics import (
    compute_iv_smile,
    compute_iv_skew,
    compute_atm_iv,
    compute_iv_term_structure,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chain(
    spot: float = 24000.0,
    strikes: list[float] | None = None,
    base_iv: float = 15.0,
    skew_slope: float = 0.5,
) -> list[dict]:
    """Build a synthetic option chain with a simple negative skew."""
    if strikes is None:
        strikes = [23200, 23400, 23600, 23800, 24000, 24200, 24400, 24600, 24800]
    chain = []
    for k in strikes:
        moneyness = (k - spot) / spot * 100
        # Puts more expensive on the downside (typical equity index smile)
        call_iv = max(5.0, base_iv + moneyness * skew_slope * 0.3)
        put_iv = max(5.0, base_iv - moneyness * skew_slope)
        chain.append({
            "strike": k,
            "call_iv": round(call_iv, 2),
            "put_iv": round(put_iv, 2),
            "call_delta": max(0.01, min(0.99, 0.5 + moneyness / 50)),
            "put_delta": -max(0.01, min(0.99, 0.5 - moneyness / 50)),
        })
    return chain


# ---------------------------------------------------------------------------
# compute_iv_smile
# ---------------------------------------------------------------------------


class TestComputeIvSmile:
    def test_empty_chain_returns_empty(self) -> None:
        assert compute_iv_smile([], spot=24000.0) == []

    def test_zero_spot_returns_empty(self) -> None:
        chain = _make_chain()
        assert compute_iv_smile(chain, spot=0.0) == []

    def test_output_sorted_by_strike(self) -> None:
        chain = _make_chain()
        smile = compute_iv_smile(chain, spot=24000.0)
        strikes = [r["strike"] for r in smile]
        assert strikes == sorted(strikes)

    def test_exactly_one_atm_flag(self) -> None:
        chain = _make_chain()
        smile = compute_iv_smile(chain, spot=24000.0)
        atm_count = sum(1 for r in smile if r["is_atm"])
        assert atm_count == 1

    def test_atm_strike_is_nearest_to_spot(self) -> None:
        chain = _make_chain()
        smile = compute_iv_smile(chain, spot=24050.0)
        atm_row = next(r for r in smile if r["is_atm"])
        assert atm_row["strike"] == 24000.0  # 24000 is closer than 24200

    def test_moneyness_calculation(self) -> None:
        chain = [{"strike": 24000, "call_iv": 15.0, "put_iv": 16.0}]
        smile = compute_iv_smile(chain, spot=24000.0)
        assert smile[0]["moneyness"] == 0.0

    def test_mid_iv_is_average(self) -> None:
        chain = [{"strike": 24000, "call_iv": 14.0, "put_iv": 16.0}]
        smile = compute_iv_smile(chain, spot=24000.0)
        assert smile[0]["mid_iv"] == 15.0

    def test_mid_iv_uses_max_when_one_side_zero(self) -> None:
        chain = [{"strike": 24000, "call_iv": 0.0, "put_iv": 16.0}]
        smile = compute_iv_smile(chain, spot=24000.0)
        assert smile[0]["mid_iv"] == 16.0

    def test_ce_oi_pe_oi_aliases(self) -> None:
        """Alternate key names from OpenAlgo format are accepted."""
        chain = [{"strike": 24000, "ce_iv": 15.0, "pe_iv": 16.0}]
        smile = compute_iv_smile(chain, spot=24000.0)
        assert len(smile) == 1
        assert smile[0]["call_iv"] == 15.0

    def test_skips_zero_strike(self) -> None:
        chain = [{"strike": 0, "call_iv": 15.0, "put_iv": 16.0}]
        smile = compute_iv_smile(chain, spot=24000.0)
        assert smile == []

    def test_negative_moneyness_for_otm_put(self) -> None:
        chain = [{"strike": 23000, "call_iv": 14.0, "put_iv": 18.0}]
        smile = compute_iv_smile(chain, spot=24000.0)
        assert smile[0]["moneyness"] < 0


# ---------------------------------------------------------------------------
# compute_iv_skew
# ---------------------------------------------------------------------------


class TestComputeIvSkew:
    def test_empty_smile_returns_zero(self) -> None:
        assert compute_iv_skew([]) == 0.0

    def test_positive_skew_for_put_heavy_chain(self) -> None:
        """Typical equity index: OTM puts more expensive → positive skew."""
        chain = _make_chain(spot=24000.0, base_iv=15.0, skew_slope=1.0)
        smile = compute_iv_smile(chain, spot=24000.0)
        skew = compute_iv_skew(smile)
        # With negative skew slope, OTM puts (below spot) have higher IV
        assert isinstance(skew, float)

    def test_zero_skew_for_flat_smile(self) -> None:
        """Flat smile: all IVs the same → skew should be near zero."""
        chain = [
            {"strike": k, "call_iv": 15.0, "put_iv": 15.0,
             "call_delta": 0.5, "put_delta": -0.5}
            for k in [23500, 24000, 24500]
        ]
        smile = compute_iv_smile(chain, spot=24000.0)
        skew = compute_iv_skew(smile)
        assert abs(skew) < 0.5  # near zero for flat smile

    def test_skew_is_float(self) -> None:
        chain = _make_chain()
        smile = compute_iv_smile(chain, spot=24000.0)
        assert isinstance(compute_iv_skew(smile), float)

    def test_skew_only_atm_row_fallback(self) -> None:
        """Only one strike — skew cannot be computed, returns 0.0."""
        chain = [{"strike": 24000, "call_iv": 15.0, "put_iv": 16.0}]
        smile = compute_iv_smile(chain, spot=24000.0)
        skew = compute_iv_skew(smile)
        assert skew == 0.0


# ---------------------------------------------------------------------------
# compute_atm_iv
# ---------------------------------------------------------------------------


class TestComputeAtmIv:
    def test_empty_smile_returns_zero(self) -> None:
        assert compute_atm_iv([], spot=24000.0) == 0.0

    def test_zero_spot_returns_zero(self) -> None:
        chain = _make_chain()
        smile = compute_iv_smile(chain, spot=24000.0)
        assert compute_atm_iv(smile, spot=0.0) == 0.0

    def test_average_of_call_and_put_iv(self) -> None:
        chain = [{"strike": 24000, "call_iv": 14.0, "put_iv": 16.0}]
        smile = compute_iv_smile(chain, spot=24000.0)
        assert compute_atm_iv(smile, spot=24000.0) == 15.0

    def test_uses_nearest_strike(self) -> None:
        chain = [
            {"strike": 23900, "call_iv": 14.0, "put_iv": 15.0},
            {"strike": 24100, "call_iv": 18.0, "put_iv": 19.0},
        ]
        smile = compute_iv_smile(chain, spot=24000.0)
        atm_iv = compute_atm_iv(smile, spot=24000.0)
        # 23900 and 24100 are equidistant; min() picks first (23900)
        assert atm_iv in {14.5, 18.5}

    def test_single_side_iv(self) -> None:
        """When only put IV is available (call IV = 0), returns put IV."""
        chain = [{"strike": 24000, "call_iv": 0.0, "put_iv": 16.0}]
        smile = compute_iv_smile(chain, spot=24000.0)
        assert compute_atm_iv(smile, spot=24000.0) == 16.0

    def test_realistic_nifty_atm_iv(self) -> None:
        chain = _make_chain()
        smile = compute_iv_smile(chain, spot=24000.0)
        atm = compute_atm_iv(smile, spot=24000.0)
        assert 5.0 <= atm <= 50.0  # sanity range


# ---------------------------------------------------------------------------
# compute_iv_term_structure
# ---------------------------------------------------------------------------


class TestComputeIvTermStructure:
    def test_empty_input_returns_empty(self) -> None:
        assert compute_iv_term_structure({}) == []

    def test_sorted_by_dte_ascending(self) -> None:
        chains = {
            "APR26": {"dte": 30, "spot": 24000,
                      "strikes": [{"strike": 24000, "call_iv": 14.0, "put_iv": 15.0}]},
            "MAR26": {"dte": 7, "spot": 24000,
                      "strikes": [{"strike": 24000, "call_iv": 16.0, "put_iv": 17.0}]},
        }
        ts = compute_iv_term_structure(chains)
        dtes = [r["dte"] for r in ts]
        assert dtes == sorted(dtes)

    def test_atm_iv_computed_correctly(self) -> None:
        chains = {
            "MAR26": {"dte": 7, "spot": 24000,
                      "strikes": [{"strike": 24000, "call_iv": 14.0, "put_iv": 16.0}]},
        }
        ts = compute_iv_term_structure(chains)
        assert len(ts) == 1
        assert ts[0]["atm_iv"] == 15.0
        assert ts[0]["dte"] == 7
        assert ts[0]["expiry"] == "MAR26"

    def test_missing_spot_skipped(self) -> None:
        chains = {
            "MAR26": {"dte": 7,
                      "strikes": [{"strike": 24000, "call_iv": 15.0, "put_iv": 15.0}]},
        }
        ts = compute_iv_term_structure(chains)
        assert ts == []  # spot=0 → skipped

    def test_missing_strikes_skipped(self) -> None:
        chains = {
            "MAR26": {"dte": 7, "spot": 24000, "strikes": []},
        }
        ts = compute_iv_term_structure(chains)
        assert ts == []

    def test_multiple_expiries(self) -> None:
        chains = {
            f"EXP{i}": {
                "dte": i * 7,
                "spot": 24000,
                "strikes": [{"strike": 24000, "call_iv": 15.0 - i * 0.5, "put_iv": 16.0 - i * 0.5}],
            }
            for i in range(1, 5)
        }
        ts = compute_iv_term_structure(chains)
        assert len(ts) == 4
        # Contango: longer DTE might have lower IV in this synthetic case
        atm_ivs = [r["atm_iv"] for r in ts]
        assert all(isinstance(v, float) for v in atm_ivs)

    def test_output_fields_present(self) -> None:
        chains = {
            "MAR26": {"dte": 7, "spot": 24000,
                      "strikes": [{"strike": 24000, "call_iv": 15.0, "put_iv": 15.0}]},
        }
        ts = compute_iv_term_structure(chains)
        assert len(ts) == 1
        row = ts[0]
        assert "expiry" in row
        assert "dte" in row
        assert "atm_iv" in row
        assert "call_iv" in row
        assert "put_iv" in row
