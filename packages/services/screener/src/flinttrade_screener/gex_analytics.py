"""GEX (Gamma Exposure) analytics — pure-function API over raw option chain dicts.

This module provides the P1 analytics layer that sits above the existing
``gex.py`` (which operates on :class:`OptionChainSnapshot`).  Here the input
is the raw ``list[dict]`` format returned by ``/api/v1/gex`` or by OpenAlgo's
``gex_service.py``, allowing the frontend and backend routes to call these
functions without constructing dataclass objects.

GEX formula (per strike, dealer-centric):
    call_gex =  call_gamma * call_oi * contract_size * spot^2 / 100  (positive)
    put_gex  = -(put_gamma  * put_oi  * contract_size * spot^2 / 100) (negative)
    net_gex  = call_gex + put_gex

Positive net GEX → dealers are long gamma → mean-reverting, stable market.
Negative net GEX → dealers are short gamma → trending, volatile market.

The zero-gamma level (flip point) is the spot price where net cumulative GEX
transitions from positive to negative (or vice-versa) as you sweep strikes.
Market participants treat this level as a potential volatility regime boundary.

Typical usage::

    from flinttrade_screener.gex_analytics import (
        compute_gex_by_strike,
        find_gamma_walls,
        total_gex,
        zero_gamma_level,
    )

    chain = [
        {"strike": 24000, "call_oi": 120000, "put_oi": 95000,
         "call_gamma": 0.003, "put_gamma": 0.003},
        ...
    ]
    gex_data = compute_gex_by_strike(chain, spot=24050.0)
    walls     = find_gamma_walls(gex_data, top_n=5)
    net       = total_gex(gex_data)
    flip      = zero_gamma_level(gex_data)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("flinttrade.screener.gex_analytics")

# Default contract size when lot_size is not supplied in the chain dict.
_DEFAULT_CONTRACT_SIZE = 1


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def compute_gex_by_strike(
    option_chain: list[dict[str, Any]],
    spot: float,
    contract_size: int = _DEFAULT_CONTRACT_SIZE,
) -> list[dict[str, Any]]:
    """Compute per-strike Gamma Exposure from a raw option chain.

    Each item in ``option_chain`` must contain at minimum:
    - ``strike``       (float | int)
    - ``call_oi``      (int)
    - ``put_oi``       (int)
    - ``call_gamma``   (float)
    - ``put_gamma``    (float)

    Optional per-row override:
    - ``lot_size`` or ``lotsize`` (int) — overrides the global ``contract_size``
      argument when present (allows mixed lot-size chains, e.g. BANKEX vs NFO).

    Args:
        option_chain:   List of per-strike dicts from option chain data.
        spot:           Current spot / futures price of the underlying.
        contract_size:  Default lot size to use when the row doesn't supply one.

    Returns:
        List of dicts, one per input strike, with keys:
        - ``strike``        (float)
        - ``call_oi``       (int)
        - ``put_oi``        (int)
        - ``call_gamma``    (float)
        - ``put_gamma``     (float)
        - ``call_gex``      (float) — positive
        - ``put_gex``       (float) — negative
        - ``net_gex``       (float) — call_gex + put_gex
        - ``lot_size``      (int)   — lot size used for this strike

    Examples:
        >>> chain = [{"strike": 24000, "call_oi": 100, "put_oi": 80,
        ...           "call_gamma": 0.003, "put_gamma": 0.003}]
        >>> rows = compute_gex_by_strike(chain, spot=24000.0, contract_size=75)
        >>> rows[0]["call_gex"] > 0
        True
        >>> rows[0]["put_gex"] < 0
        True
    """
    if not option_chain or spot <= 0:
        return []

    spot_sq_factor = (spot ** 2) / 100.0
    result: list[dict[str, Any]] = []

    for row in option_chain:
        strike = float(row.get("strike", 0))
        if strike <= 0:
            logger.debug("Skipping row with non-positive strike: %s", row)
            continue

        call_oi = int(row.get("call_oi", row.get("ce_oi", 0)) or 0)
        put_oi = int(row.get("put_oi", row.get("pe_oi", 0)) or 0)
        call_gamma = float(row.get("call_gamma", row.get("ce_gamma", 0)) or 0)
        put_gamma = float(row.get("put_gamma", row.get("pe_gamma", 0)) or 0)

        # Per-row lot size takes precedence
        lot = int(
            row.get("lot_size", row.get("lotsize", contract_size)) or contract_size
        )

        call_gex = call_gamma * call_oi * lot * spot_sq_factor
        put_gex = -(put_gamma * put_oi * lot * spot_sq_factor)
        net_gex = call_gex + put_gex

        result.append({
            "strike": strike,
            "call_oi": call_oi,
            "put_oi": put_oi,
            "call_gamma": round(call_gamma, 6),
            "put_gamma": round(put_gamma, 6),
            "call_gex": round(call_gex, 2),
            "put_gex": round(put_gex, 2),
            "net_gex": round(net_gex, 2),
            "lot_size": lot,
        })

    result.sort(key=lambda r: r["strike"])
    return result


def find_gamma_walls(
    gex_data: list[dict[str, Any]],
    top_n: int = 5,
) -> dict[str, list[dict[str, Any]]]:
    """Identify the top-N call gamma walls and put gamma walls.

    A *call gamma wall* is the strike with the highest positive call GEX —
    dealers are long gamma there and will supply (sell) the underlying as
    price rises, capping upside momentum.

    A *put gamma wall* is the strike with the highest negative put GEX
    (largest absolute put GEX) — dealers are short gamma there and will buy
    the underlying as price falls, supporting downside momentum.

    Args:
        gex_data:   Output of :func:`compute_gex_by_strike`.
        top_n:      Number of walls to return per side (default 5).

    Returns:
        Dict with two keys:
        - ``"call_walls"`` — list of up to ``top_n`` dicts, sorted by
          ``call_gex`` descending.
        - ``"put_walls"``  — list of up to ``top_n`` dicts, sorted by
          ``|put_gex|`` descending (largest negative put GEX first).

        Each wall dict contains: ``strike``, ``call_gex`` (call walls) or
        ``put_gex`` (put walls), plus ``call_oi`` / ``put_oi``.

    Examples:
        >>> walls = find_gamma_walls(gex_data, top_n=3)
        >>> len(walls["call_walls"]) <= 3
        True
        >>> len(walls["put_walls"]) <= 3
        True
    """
    if not gex_data:
        return {"call_walls": [], "put_walls": []}

    call_walls = sorted(gex_data, key=lambda r: r.get("call_gex", 0.0), reverse=True)[:top_n]
    put_walls = sorted(gex_data, key=lambda r: abs(r.get("put_gex", 0.0)), reverse=True)[:top_n]

    return {
        "call_walls": [
            {
                "strike": r["strike"],
                "call_gex": r["call_gex"],
                "call_oi": r["call_oi"],
                "lot_size": r["lot_size"],
            }
            for r in call_walls
        ],
        "put_walls": [
            {
                "strike": r["strike"],
                "put_gex": r["put_gex"],
                "put_oi": r["put_oi"],
                "lot_size": r["lot_size"],
            }
            for r in put_walls
        ],
    }


def total_gex(gex_data: list[dict[str, Any]]) -> float:
    """Sum all per-strike net GEX to obtain the aggregate market gamma.

    Args:
        gex_data: Output of :func:`compute_gex_by_strike`.

    Returns:
        Net GEX across all strikes.  Positive → dealers long gamma (stable
        market).  Negative → dealers short gamma (volatile / trending market).

    Examples:
        >>> total_gex([])
        0.0
        >>> total_gex([{"net_gex": 1000.0}, {"net_gex": -400.0}])
        600.0
    """
    return round(sum(r.get("net_gex", 0.0) for r in gex_data), 2)


def zero_gamma_level(gex_data: list[dict[str, Any]]) -> float | None:
    """Find the strike where cumulative net GEX crosses zero (the flip point).

    The zero-gamma level is the spot price region where the aggregate dealer
    gamma transitions between long (stabilising) and short (destabilising).
    It is computed by:
    1. Sorting strikes ascending.
    2. Computing the running cumulative sum of net_gex.
    3. Finding the first sign change in the cumulative sum.
    4. Linearly interpolating between the two adjacent strikes.

    Args:
        gex_data: Output of :func:`compute_gex_by_strike` (already sorted
                  ascending by strike).

    Returns:
        Interpolated strike price of the flip point, or ``None`` if the
        cumulative GEX does not change sign across the chain (e.g. entirely
        long or entirely short gamma).

    Examples:
        >>> zero_gamma_level([])
        >>> zero_gamma_level([{"strike": 100, "net_gex": 500},
        ...                   {"strike": 200, "net_gex": -300}]) is not None
        True
    """
    if not gex_data:
        return None

    sorted_data = sorted(gex_data, key=lambda r: r["strike"])

    # Build cumulative net GEX from lowest to highest strike
    cumulative = 0.0
    prev_cum = 0.0
    prev_strike = sorted_data[0]["strike"]

    for row in sorted_data:
        strike = row["strike"]
        net = row.get("net_gex", 0.0)
        cumulative += net

        if prev_cum == 0.0 and cumulative == 0.0:
            # Both zero — exact zero gamma at this strike
            prev_strike = strike
            prev_cum = cumulative
            continue

        # Sign change detected
        if (prev_cum < 0 < cumulative) or (prev_cum > 0 > cumulative):
            # Linear interpolation: find x where cumulative crosses zero
            if (cumulative - prev_cum) == 0:
                return round(strike, 2)
            t = -prev_cum / (cumulative - prev_cum)
            flip_level = prev_strike + t * (strike - prev_strike)
            return round(flip_level, 2)

        prev_cum = cumulative
        prev_strike = strike

    return None
