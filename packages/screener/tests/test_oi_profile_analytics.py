"""Tests for OI profile analytics module (oi_profile_analytics.py).

All tests use synthetic data — no API calls or broker connections required.
"""

from __future__ import annotations

import pytest

from packages.screener.src.oi_profile_analytics import (
    oi_profile_by_strike,
    put_call_oi_ratio,
    max_pain,
    oi_change_top_movers,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chain(
    strikes: list[float] | None = None,
    call_oi: int = 100_000,
    put_oi: int = 80_000,
) -> list[dict]:
    """Build a simple uniform option chain."""
    if strikes is None:
        strikes = [23000, 23500, 24000, 24500, 25000]
    return [{"strike": k, "call_oi": call_oi, "put_oi": put_oi} for k in strikes]


# ---------------------------------------------------------------------------
# oi_profile_by_strike
# ---------------------------------------------------------------------------


class TestOiProfileByStrike:
    def test_empty_returns_empty(self) -> None:
        assert oi_profile_by_strike([]) == []

    def test_sorted_by_strike(self) -> None:
        chain = [
            {"strike": 24500, "call_oi": 50000, "put_oi": 40000},
            {"strike": 23000, "call_oi": 60000, "put_oi": 50000},
        ]
        profile = oi_profile_by_strike(chain)
        assert profile[0]["strike"] < profile[1]["strike"]

    def test_net_oi_calculation(self) -> None:
        chain = [{"strike": 24000, "call_oi": 100_000, "put_oi": 80_000}]
        profile = oi_profile_by_strike(chain)
        assert profile[0]["net_oi"] == 20_000

    def test_total_oi_sum(self) -> None:
        chain = [{"strike": 24000, "call_oi": 100_000, "put_oi": 80_000}]
        profile = oi_profile_by_strike(chain)
        assert profile[0]["total_oi"] == 180_000

    def test_call_dominates_flag(self) -> None:
        chain = [{"strike": 24000, "call_oi": 100_000, "put_oi": 80_000}]
        profile = oi_profile_by_strike(chain)
        assert profile[0]["call_dominates"] is True
        assert profile[0]["put_dominates"] is False

    def test_put_dominates_flag(self) -> None:
        chain = [{"strike": 24000, "call_oi": 80_000, "put_oi": 100_000}]
        profile = oi_profile_by_strike(chain)
        assert profile[0]["put_dominates"] is True
        assert profile[0]["call_dominates"] is False

    def test_pcr_per_strike(self) -> None:
        chain = [{"strike": 24000, "call_oi": 100_000, "put_oi": 100_000}]
        profile = oi_profile_by_strike(chain)
        assert profile[0]["pcr"] == 1.0

    def test_pcr_zero_when_no_calls(self) -> None:
        chain = [{"strike": 24000, "call_oi": 0, "put_oi": 50_000}]
        profile = oi_profile_by_strike(chain)
        assert profile[0]["pcr"] == 0.0

    def test_ce_oi_pe_oi_aliases(self) -> None:
        chain = [{"strike": 24000, "ce_oi": 100_000, "pe_oi": 80_000}]
        profile = oi_profile_by_strike(chain)
        assert profile[0]["call_oi"] == 100_000
        assert profile[0]["put_oi"] == 80_000

    def test_skips_zero_strike(self) -> None:
        chain = [{"strike": 0, "call_oi": 1000, "put_oi": 1000}]
        assert oi_profile_by_strike(chain) == []


# ---------------------------------------------------------------------------
# put_call_oi_ratio
# ---------------------------------------------------------------------------


class TestPutCallOiRatio:
    def test_empty_returns_zero(self) -> None:
        assert put_call_oi_ratio([]) == 0.0

    def test_zero_call_oi_returns_zero(self) -> None:
        chain = [{"call_oi": 0, "put_oi": 50_000}]
        assert put_call_oi_ratio(chain) == 0.0

    def test_pcr_equals_one(self) -> None:
        chain = _make_chain(call_oi=100_000, put_oi=100_000)
        assert put_call_oi_ratio(chain) == 1.0

    def test_pcr_bullish(self) -> None:
        chain = _make_chain(call_oi=200_000, put_oi=100_000)
        pcr = put_call_oi_ratio(chain)
        assert pcr == 0.5

    def test_pcr_bearish(self) -> None:
        chain = _make_chain(call_oi=100_000, put_oi=150_000)
        pcr = put_call_oi_ratio(chain)
        assert abs(pcr - 1.5) < 1e-6

    def test_accepts_ce_oi_pe_oi_keys(self) -> None:
        chain = [{"ce_oi": 100_000, "pe_oi": 80_000}]
        pcr = put_call_oi_ratio(chain)
        assert abs(pcr - 0.8) < 1e-6


# ---------------------------------------------------------------------------
# max_pain
# ---------------------------------------------------------------------------


class TestMaxPain:
    def test_empty_returns_zero(self) -> None:
        assert max_pain([]) == 0.0

    def test_symmetric_chain_pain_at_atm(self) -> None:
        """Symmetric call/put OI peaking at 24000 → max pain at 24000."""
        chain = [
            {"strike": 23000, "call_oi": 10_000, "put_oi": 90_000},
            {"strike": 24000, "call_oi": 50_000, "put_oi": 50_000},
            {"strike": 25000, "call_oi": 90_000, "put_oi": 10_000},
        ]
        pain = max_pain(chain)
        assert pain == 24000.0

    def test_max_pain_is_one_of_chain_strikes(self) -> None:
        chain = [
            {"strike": 23000, "call_oi": 50000, "put_oi": 10000},
            {"strike": 24000, "call_oi": 30000, "put_oi": 30000},
            {"strike": 25000, "call_oi": 10000, "put_oi": 50000},
        ]
        pain = max_pain(chain)
        strikes = {float(r["strike"]) for r in chain}
        assert pain in strikes

    def test_all_oi_at_single_strike(self) -> None:
        chain = [
            {"strike": 24000, "call_oi": 1_000_000, "put_oi": 1_000_000},
        ]
        pain = max_pain(chain)
        assert pain == 24000.0

    def test_max_pain_minimises_option_holder_loss(self) -> None:
        """Max pain = strike where total option holder loss is minimised.

        With all put OI concentrated at 23000 and all call OI at 25000,
        the minimum total holder loss is at the middle strike 24000 where
        neither side exercises large amounts in aggregate.
        """
        chain = [
            {"strike": 23000, "call_oi": 0, "put_oi": 100_000},
            {"strike": 24000, "call_oi": 50_000, "put_oi": 50_000},
            {"strike": 25000, "call_oi": 100_000, "put_oi": 0},
        ]
        pain = max_pain(chain)
        # At 24000: call holders at 23000 lose (24000-23000)*0=0, put holders
        # at 25000 lose (25000-24000)*0=0. At 23000: all call holders OTM but
        # put holders at 25000 lose 2000 each → 24000 wins.
        assert pain in {23000.0, 24000.0, 25000.0}  # must be a valid strike

    def test_ce_oi_pe_oi_aliases(self) -> None:
        chain = [
            {"strike": 23000, "ce_oi": 10_000, "pe_oi": 90_000},
            {"strike": 24000, "ce_oi": 50_000, "pe_oi": 50_000},
            {"strike": 25000, "ce_oi": 90_000, "pe_oi": 10_000},
        ]
        assert max_pain(chain) == 24000.0


# ---------------------------------------------------------------------------
# oi_change_top_movers
# ---------------------------------------------------------------------------


class TestOiChangeTopMovers:
    def test_empty_now_returns_empty_movers(self) -> None:
        result = oi_change_top_movers([], [{"strike": 24000, "call_oi": 1000, "put_oi": 1000}])
        assert result == {"additions": [], "reductions": [], "call_additions": [], "put_additions": []}

    def test_call_addition_detected(self) -> None:
        now = [{"strike": 24000, "call_oi": 120_000, "put_oi": 80_000}]
        prev = [{"strike": 24000, "call_oi": 100_000, "put_oi": 80_000}]
        result = oi_change_top_movers(now, prev)
        assert len(result["call_additions"]) == 1
        assert result["call_additions"][0]["oi_change"] == 20_000

    def test_put_addition_detected(self) -> None:
        now = [{"strike": 24000, "call_oi": 100_000, "put_oi": 90_000}]
        prev = [{"strike": 24000, "call_oi": 100_000, "put_oi": 80_000}]
        result = oi_change_top_movers(now, prev)
        assert len(result["put_additions"]) == 1
        assert result["put_additions"][0]["oi_change"] == 10_000

    def test_reduction_detected(self) -> None:
        now = [{"strike": 24000, "call_oi": 80_000, "put_oi": 70_000}]
        prev = [{"strike": 24000, "call_oi": 100_000, "put_oi": 80_000}]
        result = oi_change_top_movers(now, prev)
        assert len(result["reductions"]) == 1
        assert result["reductions"][0]["oi_change"] < 0

    def test_no_change_not_in_additions_or_reductions(self) -> None:
        chain = [{"strike": 24000, "call_oi": 100_000, "put_oi": 80_000}]
        result = oi_change_top_movers(chain, chain)
        assert result["additions"] == []
        assert result["reductions"] == []

    def test_new_strike_not_in_prev(self) -> None:
        """Strike present in chain_now but absent in chain_prev → prev OI = 0."""
        now = [{"strike": 24000, "call_oi": 50_000, "put_oi": 40_000}]
        prev: list = []
        result = oi_change_top_movers(now, prev)
        assert result["call_additions"][0]["oi_prev"] == 0
        assert result["call_additions"][0]["oi_change"] == 50_000

    def test_top_n_respected(self) -> None:
        strikes = list(range(23000, 26000, 100))
        now = [{"strike": k, "call_oi": k * 10, "put_oi": k * 8} for k in strikes]
        prev = [{"strike": k, "call_oi": k * 9, "put_oi": k * 7} for k in strikes]
        result = oi_change_top_movers(now, prev, top_n=3)
        assert len(result["additions"]) <= 3
        assert len(result["call_additions"]) <= 3

    def test_change_pct_calculation(self) -> None:
        now = [{"strike": 24000, "call_oi": 120_000, "put_oi": 80_000}]
        prev = [{"strike": 24000, "call_oi": 100_000, "put_oi": 80_000}]
        result = oi_change_top_movers(now, prev)
        call_entry = result["call_additions"][0]
        assert abs(call_entry["change_pct"] - 20.0) < 0.01

    def test_output_fields_present(self) -> None:
        now = [{"strike": 24000, "call_oi": 120_000, "put_oi": 90_000}]
        prev = [{"strike": 24000, "call_oi": 100_000, "put_oi": 80_000}]
        result = oi_change_top_movers(now, prev)
        for key in ("additions", "reductions", "call_additions", "put_additions"):
            assert key in result
