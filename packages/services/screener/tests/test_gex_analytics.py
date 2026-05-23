"""Tests for GEX analytics module (gex_analytics.py).

All tests use synthetic data — no API calls or broker connections required.
"""

from __future__ import annotations


from flinttrade_screener.gex_analytics import (
    compute_gex_by_strike,
    find_gamma_walls,
    total_gex,
    zero_gamma_level,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_chain(
    strikes: list[float] | None = None,
    call_oi: int = 100_000,
    put_oi: int = 80_000,
    gamma: float = 0.003,
    contract_size: int = 75,
) -> list[dict]:
    """Build a synthetic option chain for GEX tests."""
    if strikes is None:
        strikes = [23800, 23900, 24000, 24100, 24200]
    return [
        {
            "strike": k,
            "call_oi": call_oi,
            "put_oi": put_oi,
            "call_gamma": gamma,
            "put_gamma": gamma,
            "lot_size": contract_size,
        }
        for k in strikes
    ]


# ---------------------------------------------------------------------------
# compute_gex_by_strike
# ---------------------------------------------------------------------------


class TestComputeGexByStrike:
    def test_empty_chain_returns_empty(self) -> None:
        result = compute_gex_by_strike([], spot=24000.0)
        assert result == []

    def test_zero_spot_returns_empty(self) -> None:
        chain = _make_chain()
        result = compute_gex_by_strike(chain, spot=0.0)
        assert result == []

    def test_negative_spot_returns_empty(self) -> None:
        chain = _make_chain()
        result = compute_gex_by_strike(chain, spot=-100.0)
        assert result == []

    def test_call_gex_is_positive(self) -> None:
        chain = _make_chain()
        result = compute_gex_by_strike(chain, spot=24000.0)
        assert all(r["call_gex"] > 0 for r in result)

    def test_put_gex_is_negative(self) -> None:
        chain = _make_chain()
        result = compute_gex_by_strike(chain, spot=24000.0)
        assert all(r["put_gex"] < 0 for r in result)

    def test_net_gex_equals_call_plus_put(self) -> None:
        chain = _make_chain()
        result = compute_gex_by_strike(chain, spot=24000.0)
        for row in result:
            expected = round(row["call_gex"] + row["put_gex"], 2)
            assert abs(row["net_gex"] - expected) < 1e-6

    def test_output_sorted_by_strike(self) -> None:
        chain = _make_chain(strikes=[24200, 23800, 24000, 24100, 23900])
        result = compute_gex_by_strike(chain, spot=24000.0)
        strikes = [r["strike"] for r in result]
        assert strikes == sorted(strikes)

    def test_skips_zero_strike_rows(self) -> None:
        chain = [{"strike": 0, "call_oi": 1000, "put_oi": 800,
                  "call_gamma": 0.003, "put_gamma": 0.003}]
        result = compute_gex_by_strike(chain, spot=24000.0)
        assert result == []

    def test_per_row_lot_size_override(self) -> None:
        """Per-row lot_size should override the global contract_size."""
        row_75 = {"strike": 24000, "call_oi": 1000, "put_oi": 1000,
                  "call_gamma": 0.003, "put_gamma": 0.003, "lot_size": 75}
        row_30 = {"strike": 24100, "call_oi": 1000, "put_oi": 1000,
                  "call_gamma": 0.003, "put_gamma": 0.003, "lot_size": 30}
        result = compute_gex_by_strike([row_75, row_30], spot=24000.0)
        assert result[0]["lot_size"] == 75
        assert result[1]["lot_size"] == 30
        # GEX scales with lot size
        assert result[0]["call_gex"] > result[1]["call_gex"]

    def test_ce_oi_pe_oi_aliases_accepted(self) -> None:
        """Keys ce_oi / pe_oi (OpenAlgo naming) should be accepted."""
        chain = [{"strike": 24000, "ce_oi": 100_000, "pe_oi": 80_000,
                  "ce_gamma": 0.003, "pe_gamma": 0.003}]
        result = compute_gex_by_strike(chain, spot=24000.0, contract_size=75)
        assert len(result) == 1
        assert result[0]["call_oi"] == 100_000
        assert result[0]["put_oi"] == 80_000

    def test_higher_oi_produces_higher_gex(self) -> None:
        chain_high = _make_chain(call_oi=200_000)
        chain_low = _make_chain(call_oi=100_000)
        res_high = compute_gex_by_strike(chain_high, spot=24000.0)
        res_low = compute_gex_by_strike(chain_low, spot=24000.0)
        assert res_high[0]["call_gex"] > res_low[0]["call_gex"]


# ---------------------------------------------------------------------------
# find_gamma_walls
# ---------------------------------------------------------------------------


class TestFindGammaWalls:
    def test_empty_input_returns_empty_walls(self) -> None:
        walls = find_gamma_walls([])
        assert walls == {"call_walls": [], "put_walls": []}

    def test_call_walls_sorted_by_call_gex_desc(self) -> None:
        chain = _make_chain()
        gex_data = compute_gex_by_strike(chain, spot=24000.0)
        walls = find_gamma_walls(gex_data, top_n=3)
        call_gex_vals = [w["call_gex"] for w in walls["call_walls"]]
        assert call_gex_vals == sorted(call_gex_vals, reverse=True)

    def test_put_walls_sorted_by_abs_put_gex_desc(self) -> None:
        chain = _make_chain()
        gex_data = compute_gex_by_strike(chain, spot=24000.0)
        walls = find_gamma_walls(gex_data, top_n=3)
        abs_vals = [abs(w["put_gex"]) for w in walls["put_walls"]]
        assert abs_vals == sorted(abs_vals, reverse=True)

    def test_top_n_respected(self) -> None:
        chain = _make_chain(strikes=list(range(23000, 26000, 100)))
        gex_data = compute_gex_by_strike(chain, spot=24000.0, contract_size=75)
        walls = find_gamma_walls(gex_data, top_n=5)
        assert len(walls["call_walls"]) <= 5
        assert len(walls["put_walls"]) <= 5

    def test_single_strike_chain(self) -> None:
        chain = [{"strike": 24000, "call_oi": 50000, "put_oi": 40000,
                  "call_gamma": 0.005, "put_gamma": 0.005, "lot_size": 75}]
        gex_data = compute_gex_by_strike(chain, spot=24000.0)
        walls = find_gamma_walls(gex_data)
        assert len(walls["call_walls"]) == 1
        assert len(walls["put_walls"]) == 1


# ---------------------------------------------------------------------------
# total_gex
# ---------------------------------------------------------------------------


class TestTotalGex:
    def test_empty_returns_zero(self) -> None:
        assert total_gex([]) == 0.0

    def test_sums_net_gex(self) -> None:
        data = [{"net_gex": 1000.0}, {"net_gex": -400.0}, {"net_gex": 250.0}]
        assert total_gex(data) == 850.0

    def test_all_positive_is_long_gamma(self) -> None:
        chain = _make_chain(call_oi=200_000, put_oi=50_000)
        gex_data = compute_gex_by_strike(chain, spot=24000.0)
        assert total_gex(gex_data) > 0

    def test_all_negative_is_short_gamma(self) -> None:
        chain = _make_chain(call_oi=50_000, put_oi=200_000)
        gex_data = compute_gex_by_strike(chain, spot=24000.0)
        assert total_gex(gex_data) < 0

    def test_balanced_oi_close_to_zero(self) -> None:
        chain = _make_chain(call_oi=100_000, put_oi=100_000)
        gex_data = compute_gex_by_strike(chain, spot=24000.0)
        # Net should be near zero (call_gex + put_gex ≈ 0)
        assert abs(total_gex(gex_data)) < 1  # < ₹1 rounding


# ---------------------------------------------------------------------------
# zero_gamma_level
# ---------------------------------------------------------------------------


class TestZeroGammaLevel:
    def test_empty_returns_none(self) -> None:
        assert zero_gamma_level([]) is None

    def test_all_positive_no_flip(self) -> None:
        data = [
            {"strike": 23000, "net_gex": 500.0},
            {"strike": 24000, "net_gex": 300.0},
        ]
        assert zero_gamma_level(data) is None

    def test_all_negative_no_flip(self) -> None:
        data = [
            {"strike": 23000, "net_gex": -500.0},
            {"strike": 24000, "net_gex": -300.0},
        ]
        assert zero_gamma_level(data) is None

    def test_flip_between_two_strikes(self) -> None:
        """Cumulative GEX crosses zero between two strikes."""
        # cumsum at 23000 = 500, at 24000 = 500 − 800 = −300 → sign flip
        data = [
            {"strike": 23000, "net_gex": 500.0},
            {"strike": 24000, "net_gex": -800.0},
        ]
        flip = zero_gamma_level(data)
        assert flip is not None
        assert 23000 < flip < 24000

    def test_flip_interpolated_correctly(self) -> None:
        """Zero crossing should be linearly interpolated between strikes."""
        # cumsum at 23000 = 200, at 24000 = 200 − 600 = −400
        # zero crossing at 23000 + 200 / (200 + 400) × 1000 ≈ 23333.33
        data = [
            {"strike": 23000, "net_gex": 200.0},
            {"strike": 24000, "net_gex": -600.0},
        ]
        flip = zero_gamma_level(data)
        assert flip is not None
        assert abs(flip - 23333.33) < 1.0

    def test_realistic_chain(self) -> None:
        """Realistic asymmetric chain should produce a zero-gamma flip."""
        # Structure: calls dominate at the first strike, puts dominate from second
        # This guarantees cumulative GEX starts positive then turns negative.
        data = [
            {"strike": 23500, "net_gex": 5_000_000.0},
            {"strike": 23600, "net_gex": -3_000_000.0},
            {"strike": 23700, "net_gex": -3_000_000.0},
        ]
        flip = zero_gamma_level(data)
        # cumsum: 5M → 2M → -1M — flip between 23600 and 23700
        assert flip is not None
        assert 23600 < flip < 23700
