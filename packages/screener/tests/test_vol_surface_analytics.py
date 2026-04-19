"""Tests for volatility surface analytics module (vol_surface_analytics.py).

All tests use synthetic data — no API calls or broker connections required.
"""

from __future__ import annotations

import pytest
import numpy as np

from packages.screener.src.vol_surface_analytics import (
    build_vol_surface,
    surface_to_grid,
    _linear_interp,
    _spline_interp,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_expiry_chain(
    expiry: str,
    dte: int,
    spot: float,
    strikes: list[float] | None = None,
    base_iv: float = 15.0,
) -> dict:
    """Build a synthetic chain dict for one expiry."""
    if strikes is None:
        strikes = [s for s in range(int(spot) - 500, int(spot) + 600, 100)]
    return {
        "dte": dte,
        "spot": spot,
        "strikes": [
            {
                "strike": k,
                "call_iv": base_iv + abs(k - spot) / spot * 20,
                "put_iv": base_iv + abs(k - spot) / spot * 20 + 1.0,
            }
            for k in strikes
        ],
    }


def _make_multi_expiry_chains(
    spot: float = 24000.0,
    expiries: list[tuple[str, int]] | None = None,
) -> dict:
    """Build a multi-expiry chain dict."""
    if expiries is None:
        expiries = [("26MAR26", 7), ("24APR26", 35), ("29MAY26", 63)]
    return {label: _make_expiry_chain(label, dte, spot) for label, dte in expiries}


# ---------------------------------------------------------------------------
# build_vol_surface
# ---------------------------------------------------------------------------


class TestBuildVolSurface:
    def test_empty_chains_returns_empty_surface(self) -> None:
        surface = build_vol_surface({}, spot=24000.0)
        assert surface["strikes"] == []
        assert surface["iv_matrix"] == []

    def test_zero_spot_returns_empty_surface(self) -> None:
        chains = _make_multi_expiry_chains()
        surface = build_vol_surface(chains, spot=0.0)
        assert surface["strikes"] == []

    def test_output_keys_present(self) -> None:
        chains = _make_multi_expiry_chains()
        surface = build_vol_surface(chains, spot=24000.0)
        for key in ("strikes", "expiries_dte", "expiry_labels", "iv_matrix", "atm_ivs", "spot"):
            assert key in surface

    def test_expiries_sorted_by_dte(self) -> None:
        chains = _make_multi_expiry_chains()
        surface = build_vol_surface(chains, spot=24000.0)
        dtes = surface["expiries_dte"]
        assert dtes == sorted(dtes)

    def test_iv_matrix_shape_matches_metadata(self) -> None:
        chains = _make_multi_expiry_chains()
        surface = build_vol_surface(chains, spot=24000.0)
        n_exp = len(surface["expiries_dte"])
        n_strikes = len(surface["strikes"])
        assert len(surface["iv_matrix"]) == n_exp
        assert all(len(row) == n_strikes for row in surface["iv_matrix"])

    def test_strike_count_limit(self) -> None:
        chains = _make_multi_expiry_chains()
        surface = build_vol_surface(chains, spot=24000.0, strike_count=5)
        assert len(surface["strikes"]) <= 5

    def test_all_iv_values_non_negative(self) -> None:
        chains = _make_multi_expiry_chains()
        surface = build_vol_surface(chains, spot=24000.0)
        for row in surface["iv_matrix"]:
            assert all(v >= 0 for v in row)

    def test_atm_ivs_length_matches_expiries(self) -> None:
        chains = _make_multi_expiry_chains()
        surface = build_vol_surface(chains, spot=24000.0)
        assert len(surface["atm_ivs"]) == len(surface["expiries_dte"])

    def test_single_expiry(self) -> None:
        chains = {"26MAR26": _make_expiry_chain("26MAR26", 7, 24000.0)}
        surface = build_vol_surface(chains, spot=24000.0)
        assert len(surface["expiries_dte"]) == 1

    def test_black76_fallback_for_missing_iv(self) -> None:
        """When IV is absent, Black-76 bisection should be used."""
        chains = {
            "26MAR26": {
                "dte": 7,
                "spot": 24000,
                "strikes": [
                    {"strike": 24000, "ce_ltp": 180.0, "pe_ltp": 175.0},
                    {"strike": 24200, "ce_ltp": 100.0, "pe_ltp": 250.0},
                ],
            }
        }
        surface = build_vol_surface(chains, spot=24000.0)
        # Should have computed IVs from LTPs
        assert len(surface["strikes"]) > 0
        assert all(v >= 0 for row in surface["iv_matrix"] for v in row)

    def test_spot_stored_in_output(self) -> None:
        chains = _make_multi_expiry_chains(spot=22500.0)
        surface = build_vol_surface(chains, spot=22500.0)
        assert surface["spot"] == 22500.0


# ---------------------------------------------------------------------------
# surface_to_grid
# ---------------------------------------------------------------------------


class TestSurfaceToGrid:
    def test_empty_surface_returns_empty_arrays(self) -> None:
        surface = build_vol_surface({}, spot=24000.0)
        strikes, dtes, grid = surface_to_grid(surface)
        assert strikes.size == 0
        assert dtes.size == 0
        assert grid.shape == (0, 0)

    def test_grid_shape_correct(self) -> None:
        chains = _make_multi_expiry_chains()
        surface = build_vol_surface(chains, spot=24000.0)
        strikes, dtes, grid = surface_to_grid(surface)
        assert grid.shape == (len(dtes), len(strikes))

    def test_all_arrays_float64(self) -> None:
        chains = _make_multi_expiry_chains()
        surface = build_vol_surface(chains, spot=24000.0)
        strikes, dtes, grid = surface_to_grid(surface)
        assert strikes.dtype == np.float64
        assert dtes.dtype == np.float64
        assert grid.dtype == np.float64

    def test_strikes_sorted_ascending(self) -> None:
        chains = _make_multi_expiry_chains()
        surface = build_vol_surface(chains, spot=24000.0)
        strikes, _, _ = surface_to_grid(surface)
        assert np.all(np.diff(strikes) >= 0)

    def test_dtes_sorted_ascending(self) -> None:
        chains = _make_multi_expiry_chains()
        surface = build_vol_surface(chains, spot=24000.0)
        _, dtes, _ = surface_to_grid(surface)
        assert np.all(np.diff(dtes) >= 0)

    def test_iv_values_in_reasonable_range(self) -> None:
        chains = _make_multi_expiry_chains()
        surface = build_vol_surface(chains, spot=24000.0)
        _, _, grid = surface_to_grid(surface)
        assert np.all(grid >= 0)


# ---------------------------------------------------------------------------
# Interpolation helpers
# ---------------------------------------------------------------------------


class TestLinearInterp:
    def test_exact_match(self) -> None:
        assert _linear_interp([0.0, 1.0], [10.0, 20.0], 0.5) == 15.0

    def test_left_boundary(self) -> None:
        assert _linear_interp([1.0, 2.0], [5.0, 10.0], 0.5) == 5.0

    def test_right_boundary(self) -> None:
        assert _linear_interp([1.0, 2.0], [5.0, 10.0], 3.0) == 10.0

    def test_empty_returns_zero(self) -> None:
        assert _linear_interp([], [], 5.0) == 0.0


class TestSplineInterp:
    def test_returns_list_of_same_length(self) -> None:
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [2.0, 4.0, 3.0, 5.0, 4.0]
        targets = [1.5, 2.5, 3.5, 4.5]
        result = _spline_interp(xs, ys, targets)
        assert len(result) == 4

    def test_exact_node_values(self) -> None:
        xs = [1.0, 2.0, 3.0]
        ys = [10.0, 20.0, 30.0]
        result = _spline_interp(xs, ys, [1.0, 2.0, 3.0])
        assert abs(result[0] - 10.0) < 0.5
        assert abs(result[2] - 30.0) < 0.5

    def test_no_negative_values(self) -> None:
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [15.0, 14.0, 13.5, 14.0, 15.0]
        result = _spline_interp(xs, ys, list(np.linspace(1.0, 5.0, 20)))
        assert all(v >= 0 for v in result)
