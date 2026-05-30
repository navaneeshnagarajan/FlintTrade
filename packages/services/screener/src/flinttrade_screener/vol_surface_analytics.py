"""Volatility surface construction from multi-expiry option chain data.

Builds a 3-D implied volatility surface:
    x-axis: strike prices (or moneyness relative to spot)
    y-axis: days to expiry (DTE)
    z-axis: implied volatility (%)

This module supplements ``vol_surface.py`` (which uses :class:`ExpiryIVCurve`
dataclasses) with a pure-dict public API that matches the format used by the
FlintTrade ``/ft-api/v1/volsurface`` route and the frontend ``volsurface``
widget.

Cubic spline interpolation is used when ``scipy`` is available.  If scipy is
not installed, the module silently falls back to linear interpolation (the
same algorithm used by ``vol_surface.py``).

Typical usage::

    from flinttrade_screener.vol_surface_analytics import (
        build_vol_surface,
        surface_to_grid,
    )

    chains = {
        "26MAR26": {
            "dte": 7, "spot": 24050,
            "strikes": [{"strike": 24000, "call_iv": 15.0, "put_iv": 16.0}, ...]
        },
        "24APR26": {...},
    }
    surface = build_vol_surface(chains, spot=24050.0)
    strikes_arr, dte_arr, iv_matrix = surface_to_grid(surface)
"""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger("flinttrade.screener.vol_surface_analytics")

# Risk-free rate approximation for India (repo rate ~6.5%)
_RISK_FREE_RATE = 0.065

# --------------------------------------------------------------------------
# scipy optional import
# --------------------------------------------------------------------------
try:
    from scipy.interpolate import CubicSpline  # type: ignore[import-untyped]
    _SCIPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SCIPY_AVAILABLE = False
    logger.debug("scipy not available — vol surface will use linear interpolation")


# ---------------------------------------------------------------------------
# Black-76 IV (bisection) — fallback when IV is absent from the chain
# ---------------------------------------------------------------------------


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via math.erfc."""
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _black76_call(F: float, K: float, T: float, sigma: float) -> float:
    """Black-76 call price formula.

    Args:
        F:     Forward price (spot used as proxy).
        K:     Strike price.
        T:     Time to expiry in years.
        sigma: Volatility as decimal (0.15 = 15%).

    Returns:
        Theoretical call option price.
    """
    if T <= 0 or sigma <= 0 or F <= 0 or K <= 0:
        return max(0.0, F - K)
    sqrt_T = math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma ** 2 * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T
    return math.exp(-_RISK_FREE_RATE * T) * (F * _norm_cdf(d1) - K * _norm_cdf(d2))


def _black76_iv(
    market_price: float,
    F: float,
    K: float,
    T: float,
    max_iter: int = 100,
    tol: float = 1e-6,
) -> float:
    """Bisection IV solver for Black-76.

    Returns:
        IV as a decimal (0.15 = 15%), or 0.0 if not solvable.
    """
    if market_price <= 0 or T <= 0 or F <= 0 or K <= 0:
        return 0.0
    intrinsic = max(0.0, F - K)
    if market_price <= intrinsic:
        return 0.0
    lo, hi = 0.001, 5.0
    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        diff = _black76_call(F, K, T, mid) - market_price
        if abs(diff) < tol:
            return mid
        if diff > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2.0


# ---------------------------------------------------------------------------
# Interpolation helpers
# ---------------------------------------------------------------------------


def _linear_interp(xs: list[float], ys: list[float], x: float) -> float:
    """Linear interpolation with nearest-boundary extrapolation."""
    if not xs:
        return 0.0
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            t = (x - xs[i]) / (xs[i + 1] - xs[i])
            return ys[i] + t * (ys[i + 1] - ys[i])
    return ys[-1]


def _spline_interp(xs: list[float], ys: list[float], x_targets: list[float]) -> list[float]:
    """Cubic spline interpolation with linear fallback for small datasets.

    Uses ``scipy.interpolate.CubicSpline`` when available and when the
    dataset is large enough (≥ 3 points).  Falls back to per-point linear
    interpolation otherwise.

    Args:
        xs:        Sorted x-values (e.g. strikes).
        ys:        Corresponding y-values (e.g. IVs).
        x_targets: Target x-values to evaluate.

    Returns:
        List of interpolated y-values, one per element of ``x_targets``.
    """
    if len(xs) < 2:
        return [ys[0] if ys else 0.0] * len(x_targets)

    if _SCIPY_AVAILABLE and len(xs) >= 3:
        try:
            cs = CubicSpline(xs, ys, extrapolate=True)
            # Clamp to 0 — negative IVs are non-sensical
            return [max(0.0, float(v)) for v in cs(x_targets)]
        except Exception as exc:  # pragma: no cover
            logger.debug("CubicSpline failed (%s), falling back to linear", exc)

    return [_linear_interp(xs, ys, x) for x in x_targets]


# ---------------------------------------------------------------------------
# Core surface builder
# ---------------------------------------------------------------------------


def build_vol_surface(
    chains_by_expiry: dict[str, dict[str, Any]],
    spot: float,
    strike_count: int = 20,
) -> dict[str, Any]:
    """Build a 2-D implied volatility surface from multiple expiry chains.

    For each expiry, per-strike IVs are extracted (using pre-computed IV
    fields when available, or Black-76 bisection as fallback).  A common
    strike grid is constructed from all expiries combined, then each expiry
    curve is interpolated (cubic spline or linear) onto the common grid.

    Args:
        chains_by_expiry: Dict mapping expiry label → chain data dict.
            Each value must contain:
            - ``"dte"``     (int)   — days to expiry
            - ``"spot"``    (float) — spot price (optional, defaults to ``spot``)
            - ``"strikes"`` (list[dict]) — per-strike dicts with:
                  strike, ce_ltp, pe_ltp, ce_iv, pe_iv
        spot:         Current spot price of the underlying.
        strike_count: Maximum number of strikes to include in the surface
                      grid (nearest to spot are preferred).

    Returns:
        Dict with keys:
        - ``"strikes"``       (list[float]) — common strike grid
        - ``"expiries_dte"``  (list[int])   — DTE per expiry, ascending
        - ``"expiry_labels"`` (list[str])   — expiry label strings
        - ``"iv_matrix"``     (list[list[float]]) — shape [n_expiries][n_strikes]
        - ``"atm_ivs"``       (list[float]) — ATM IV per expiry
        - ``"spot"``          (float)

    Examples:
        >>> surface = build_vol_surface(
        ...     {"26MAR26": {"dte": 7, "spot": 24000,
        ...                  "strikes": [{"strike": 24000,
        ...                               "call_iv": 15.0, "put_iv": 16.0}]}},
        ...     spot=24000.0,
        ... )
        >>> "iv_matrix" in surface
        True
    """
    if not chains_by_expiry or spot <= 0:
        return {
            "strikes": [],
            "expiries_dte": [],
            "expiry_labels": [],
            "iv_matrix": [],
            "atm_ivs": [],
            "spot": spot,
        }

    # Step 1: extract per-expiry curves
    curves: list[dict[str, Any]] = []
    for label, chain_data in chains_by_expiry.items():
        dte = int(chain_data.get("dte", 0))
        chain_spot = float(chain_data.get("spot", spot) or spot)
        T = max(dte / 365.0, 1 / 365.0)
        strike_rows = chain_data.get("strikes", [])

        strikes: list[float] = []
        mid_ivs: list[float] = []
        atm_distance = float("inf")
        atm_iv = 0.0

        for row in strike_rows:
            k = float(row.get("strike", 0))
            if k <= 0:
                continue

            ce_iv = float(row.get("ce_iv", row.get("call_iv", 0)) or 0)
            pe_iv = float(row.get("pe_iv", row.get("put_iv", 0)) or 0)

            # Fallback: compute IV from LTP using Black-76
            if ce_iv <= 0:
                ce_ltp = float(row.get("ce_ltp", row.get("call_ltp", 0)) or 0)
                if ce_ltp > 0:
                    ce_iv = _black76_iv(ce_ltp, chain_spot, k, T) * 100.0

            if pe_iv <= 0:
                pe_ltp = float(row.get("pe_ltp", row.get("put_ltp", 0)) or 0)
                if pe_ltp > 0:
                    # Put-call parity to convert to synthetic call
                    synth = max(0.0, pe_ltp + chain_spot - k)
                    pe_iv = _black76_iv(synth, chain_spot, k, T) * 100.0

            if ce_iv > 0 and pe_iv > 0:
                mid = (ce_iv + pe_iv) / 2.0
            else:
                mid = max(ce_iv, pe_iv)

            if mid <= 0:
                continue

            strikes.append(k)
            mid_ivs.append(mid)

            dist = abs(k - chain_spot)
            if dist < atm_distance:
                atm_distance = dist
                atm_iv = mid

        if strikes:
            curves.append({
                "label": label,
                "dte": dte,
                "strikes": strikes,
                "mid_ivs": mid_ivs,
                "atm_iv": atm_iv,
            })

    if not curves:
        return {
            "strikes": [],
            "expiries_dte": [],
            "expiry_labels": [],
            "iv_matrix": [],
            "atm_ivs": [],
            "spot": spot,
        }

    # Step 2: sort curves by DTE ascending
    curves.sort(key=lambda c: c["dte"])

    # Step 3: build common strike grid (nearest strike_count to spot)
    all_strikes: set[float] = set()
    for c in curves:
        all_strikes.update(c["strikes"])

    sorted_strikes = sorted(all_strikes)
    if len(sorted_strikes) > strike_count:
        sorted_strikes = sorted(
            sorted(sorted_strikes, key=lambda k: abs(k - spot))[:strike_count]
        )

    # Step 4: interpolate each curve onto the common strike grid
    iv_matrix: list[list[float]] = []
    for c in curves:
        row_ivs = _spline_interp(c["strikes"], c["mid_ivs"], sorted_strikes)
        iv_matrix.append([round(v, 4) for v in row_ivs])

    return {
        "strikes": sorted_strikes,
        "expiries_dte": [c["dte"] for c in curves],
        "expiry_labels": [c["label"] for c in curves],
        "iv_matrix": iv_matrix,
        "atm_ivs": [round(c["atm_iv"], 4) for c in curves],
        "spot": spot,
    }


def surface_to_grid(
    surface: dict[str, Any],
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Convert a surface dict into numpy arrays suitable for 3-D plotting.

    Args:
        surface: Output of :func:`build_vol_surface`.

    Returns:
        Tuple of three numpy arrays:
        - ``strikes_arr``  — 1-D array of strike prices, shape ``(n_strikes,)``
        - ``dte_arr``      — 1-D array of DTE values, shape ``(n_expiries,)``
        - ``iv_grid``      — 2-D array of IVs, shape ``(n_expiries, n_strikes)``

        All three arrays have dtype ``float64``.

    Examples:
        >>> surface = build_vol_surface(
        ...     {"26MAR26": {"dte": 7, "spot": 24000,
        ...                  "strikes": [{"strike": 24000,
        ...                               "call_iv": 15.0, "put_iv": 16.0}]}},
        ...     spot=24000.0,
        ... )
        >>> strikes, dte, grid = surface_to_grid(surface)
        >>> grid.shape == (len(dte), len(strikes))
        True
    """
    strikes_arr = np.array(surface.get("strikes", []), dtype=np.float64)
    dte_arr = np.array(surface.get("expiries_dte", []), dtype=np.float64)
    iv_list = surface.get("iv_matrix", [])

    if iv_list and strikes_arr.size and dte_arr.size:
        iv_grid = np.array(iv_list, dtype=np.float64)
    else:
        iv_grid = np.empty((0, 0), dtype=np.float64)

    return strikes_arr, dte_arr, iv_grid
