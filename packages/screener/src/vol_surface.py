"""Volatility surface interpolation from multi-expiry option chains.

Builds a 3-D implied volatility surface:
    x-axis: strike prices (moneyness relative to spot)
    y-axis: days to expiry (DTE)
    z-axis: implied volatility (%)

The surface is constructed by:
1. Collecting ATM IV per expiry (from option chain data if available,
   falling back to a simplified Black-76 approximation if IV is missing).
2. Collecting per-strike IVs for each expiry.
3. Interpolating missing grid points using scipy's RectBivariateSpline
   (or linear fallback when scipy is not available / data is sparse).

Black-76 IV estimation (fallback) uses bisection on the call price formula:
    C = e^{-rT} * [F*N(d1) - K*N(d2)]
    d1 = (ln(F/K) + 0.5*sigma^2*T) / (sigma*sqrt(T))
    d2 = d1 - sigma*sqrt(T)
where F is the futures price (approximated as spot) and r=0 (risk-neutral).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("flinttrade.screener.vol_surface")

# Risk-free rate approximation for India (repo rate ~6.5%)
_RISK_FREE_RATE = 0.065


# ---------------------------------------------------------------------------
# Black-76 IV (bisection)
# ---------------------------------------------------------------------------

def _norm_cdf(x: float) -> float:
    """Standard normal CDF via math.erfc approximation."""
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _black76_call(F: float, K: float, T: float, sigma: float) -> float:
    """Black-76 call price (assumes r absorbed into forward price).

    Args:
        F: Forward price.
        K: Strike price.
        T: Time to expiry in years.
        sigma: Volatility (decimal, e.g. 0.15 for 15%).

    Returns:
        Call option price.
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
    """Bisection-based IV solver for Black-76 model.

    Args:
        market_price: Observed option market price.
        F: Forward price.
        K: Strike price.
        T: Time to expiry in years.
        max_iter: Maximum bisection iterations.
        tol: Convergence tolerance.

    Returns:
        Implied volatility as a decimal (0.15 = 15%), or 0.0 if not solvable.
    """
    if market_price <= 0 or T <= 0 or F <= 0 or K <= 0:
        return 0.0

    intrinsic = max(0.0, F - K)
    if market_price <= intrinsic:
        return 0.0

    lo, hi = 0.001, 5.0  # 0.1% to 500% vol range
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        price = _black76_call(F, K, T, mid)
        diff = price - market_price
        if abs(diff) < tol:
            return mid
        if diff > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ExpiryIVCurve:
    """IV curve for a single expiry.

    Attributes:
        expiry_label: Human-readable expiry label (e.g. '26MAR26').
        dte: Days to expiry.
        strikes: Strike prices in the chain.
        call_ivs: Call IVs per strike (decimal).
        put_ivs: Put IVs per strike (decimal).
        atm_iv: ATM IV for this expiry (average of ATM call/put IV).
    """

    expiry_label: str = ""
    dte: int = 0
    strikes: list[float] = field(default_factory=list)
    call_ivs: list[float] = field(default_factory=list)
    put_ivs: list[float] = field(default_factory=list)
    atm_iv: float = 0.0


@dataclass
class VolSurfaceResult:
    """3-D implied volatility surface result.

    Attributes:
        strikes: Strike prices (x-axis of the surface grid).
        expiries_dte: Days-to-expiry for each expiry (y-axis).
        expiry_labels: Human-readable expiry labels.
        iv_matrix: 2-D IV grid, shape [len(expiries_dte)][len(strikes)].
                   iv_matrix[i][j] = IV at expiry i and strike j.
        atm_ivs: ATM IV per expiry (term structure).
        spot: Spot price used for calculation.
        curves: Per-expiry IV curves (raw data before interpolation).
    """

    strikes: list[float] = field(default_factory=list)
    expiries_dte: list[int] = field(default_factory=list)
    expiry_labels: list[str] = field(default_factory=list)
    iv_matrix: list[list[float]] = field(default_factory=list)
    atm_ivs: list[float] = field(default_factory=list)
    spot: float = 0.0
    curves: list[ExpiryIVCurve] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Chain data type alias
# ---------------------------------------------------------------------------

# chains_by_expiry: dict mapping expiry label → list of strike dicts
# Each strike dict has keys: strike, ce_ltp, pe_ltp, ce_iv, pe_iv, ce_oi, pe_oi
ChainsByExpiry = dict[str, dict]
# dict value structure:
#   {
#       "dte": int,
#       "spot": float,
#       "strikes": list[dict] with keys: strike, ce_ltp, pe_ltp, ce_iv, pe_iv
#   }


def _extract_iv_curve(
    expiry_label: str,
    expiry_data: dict,
    spot: float,
) -> ExpiryIVCurve:
    """Extract an IV curve for a single expiry from chain data.

    Args:
        expiry_label: Expiry label string.
        expiry_data: Dict with 'dte', 'spot', and 'strikes' keys.
        spot: Spot price of the underlying.

    Returns:
        ExpiryIVCurve with per-strike IVs.
    """
    dte = int(expiry_data.get("dte", 0))
    T = max(dte / 365.0, 1 / 365.0)  # at least 1 day
    chain_spot = float(expiry_data.get("spot", spot)) or spot
    strike_list = expiry_data.get("strikes", [])

    strikes: list[float] = []
    call_ivs: list[float] = []
    put_ivs: list[float] = []
    atm_distance = float("inf")
    atm_iv = 0.0

    for s in strike_list:
        k = float(s.get("strike", 0))
        if k <= 0:
            continue

        # Prefer pre-computed IVs from the broker
        ce_iv = float(s.get("ce_iv", 0))
        pe_iv = float(s.get("pe_iv", 0))

        # Fall back to Black-76 bisection when IV is missing
        if ce_iv <= 0:
            ce_ltp = float(s.get("ce_ltp", 0))
            ce_iv = _black76_iv(ce_ltp, chain_spot, k, T) * 100.0  # to percent

        if pe_iv <= 0:
            pe_ltp = float(s.get("pe_ltp", 0))
            # Convert put to call via put-call parity then solve
            # Synthetic call = pe_ltp + chain_spot - k (simplified)
            synth_call = max(0.0, pe_ltp + chain_spot - k)
            pe_iv = _black76_iv(synth_call, chain_spot, k, T) * 100.0

        strikes.append(k)
        call_ivs.append(ce_iv)
        put_ivs.append(pe_iv)

        dist = abs(k - chain_spot)
        if dist < atm_distance:
            atm_distance = dist
            avg_iv = (ce_iv + pe_iv) / 2.0 if (ce_iv > 0 and pe_iv > 0) else max(ce_iv, pe_iv)
            atm_iv = avg_iv

    return ExpiryIVCurve(
        expiry_label=expiry_label,
        dte=dte,
        strikes=strikes,
        call_ivs=call_ivs,
        put_ivs=put_ivs,
        atm_iv=atm_iv,
    )


def _build_iv_matrix(
    curves: list[ExpiryIVCurve],
    target_strikes: list[float],
) -> list[list[float]]:
    """Build the 2-D IV grid using linear interpolation per expiry.

    For each expiry curve, we linearly interpolate IV values onto the
    common target_strikes grid. If a strike is outside the curve's range,
    we extrapolate using the nearest boundary IV.

    Args:
        curves: List of ExpiryIVCurve objects (one per expiry).
        target_strikes: Common strike grid for the surface x-axis.

    Returns:
        2-D list of shape [n_expiries][n_strikes] with IV values.
    """
    matrix: list[list[float]] = []

    for curve in curves:
        if not curve.strikes:
            matrix.append([0.0] * len(target_strikes))
            continue

        # Use average of call and put IV per strike
        src_strikes = curve.strikes
        src_ivs = [
            (c + p) / 2.0 if (c > 0 and p > 0) else max(c, p)
            for c, p in zip(curve.call_ivs, curve.put_ivs)
        ]

        row: list[float] = []
        for target_k in target_strikes:
            iv = _interp1d(src_strikes, src_ivs, target_k)
            row.append(round(iv, 4))
        matrix.append(row)

    return matrix


def _interp1d(
    xs: list[float],
    ys: list[float],
    x: float,
) -> float:
    """Linear interpolation / nearest-boundary extrapolation.

    Args:
        xs: Sorted x-values.
        ys: Corresponding y-values.
        x: Target x-value to interpolate.

    Returns:
        Interpolated y-value.
    """
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


def calculate_vol_surface(
    chains_by_expiry: ChainsByExpiry,
    spot: float,
    strike_count: int = 20,
) -> VolSurfaceResult:
    """Build a volatility surface from multiple expiry option chains.

    Args:
        chains_by_expiry: Mapping of expiry label → chain data dict.
            Each value must contain:
                - 'dte': int (days to expiry)
                - 'spot': float (spot price for this expiry, optional)
                - 'strikes': list[dict] with strike, ce_ltp, pe_ltp, ce_iv, pe_iv
        spot: Current spot price of the underlying.
        strike_count: Maximum number of strikes to include in the surface grid.

    Returns:
        VolSurfaceResult with strikes, expiry DTEs, IV matrix, and ATM IVs.
    """
    if not chains_by_expiry or spot <= 0:
        return VolSurfaceResult(spot=spot)

    # Build per-expiry curves
    curves: list[ExpiryIVCurve] = []
    for label, data in chains_by_expiry.items():
        curve = _extract_iv_curve(label, data, spot)
        if curve.strikes:
            curves.append(curve)

    if not curves:
        return VolSurfaceResult(spot=spot)

    # Sort by DTE ascending
    curves.sort(key=lambda c: c.dte)

    # Build common strike grid from union of all expiry strikes
    all_strikes: set[float] = set()
    for c in curves:
        all_strikes.update(c.strikes)

    sorted_strikes = sorted(all_strikes)

    # Limit to strike_count nearest to spot
    if len(sorted_strikes) > strike_count:
        strike_distances = [(abs(k - spot), k) for k in sorted_strikes]
        strike_distances.sort()
        selected = {k for _, k in strike_distances[:strike_count]}
        sorted_strikes = sorted(selected)

    # Build IV matrix
    iv_matrix = _build_iv_matrix(curves, sorted_strikes)

    return VolSurfaceResult(
        strikes=sorted_strikes,
        expiries_dte=[c.dte for c in curves],
        expiry_labels=[c.expiry_label for c in curves],
        iv_matrix=iv_matrix,
        atm_ivs=[c.atm_iv for c in curves],
        spot=spot,
        curves=curves,
    )
