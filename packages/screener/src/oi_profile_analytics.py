"""OI profile analytics — per-strike OI distribution, top movers, max pain, PCR.

This module provides the P1 analytics layer for OI profile analysis, operating
on raw ``list[dict]`` option chain data rather than the ``OptionChainSnapshot``
dataclass used by ``oi_profile.py``.

Key functions:

1. :func:`oi_profile_by_strike`  — per-strike call OI, put OI, net OI.
2. :func:`put_call_oi_ratio`     — PCR at chain level (total PE OI / CE OI).
3. :func:`max_pain`              — strike where total option buyer loss is maximised.
4. :func:`oi_change_top_movers`  — biggest OI additions and reductions vs previous.

Input ``option_chain`` dict format (per-strike)::

    {
        "strike":    float,
        "call_oi":   int,    # also accepted: "ce_oi"
        "put_oi":    int,    # also accepted: "pe_oi"
        "call_ltp":  float,  # optional, used for max_pain calculation
        "put_ltp":   float,  # optional
    }

Typical usage::

    from packages.screener.src.oi_profile_analytics import (
        oi_profile_by_strike,
        put_call_oi_ratio,
        max_pain,
        oi_change_top_movers,
    )

    chain = [{"strike": 24000, "call_oi": 100000, "put_oi": 80000, ...}, ...]
    profile = oi_profile_by_strike(chain)
    pcr     = put_call_oi_ratio(chain)
    pain    = max_pain(chain)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("flinttrade.screener.oi_profile_analytics")


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def oi_profile_by_strike(
    option_chain: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the per-strike OI profile (call OI, put OI, net OI).

    Args:
        option_chain: List of per-strike dicts.  Required keys: ``strike``,
                      ``call_oi`` (or ``ce_oi``), ``put_oi`` (or ``pe_oi``).

    Returns:
        List of dicts sorted by strike ascending, each with:
        - ``"strike"``       (float)
        - ``"call_oi"``      (int)
        - ``"put_oi"``       (int)
        - ``"net_oi"``       (int)  — call_oi − put_oi
        - ``"total_oi"``     (int)  — call_oi + put_oi
        - ``"pcr"``          (float) — put_oi / call_oi (0.0 if call_oi == 0)
        - ``"call_dominates"`` (bool) — True when net_oi > 0 (more call OI)
        - ``"put_dominates"``  (bool) — True when net_oi < 0 (more put OI)

    Examples:
        >>> chain = [{"strike": 24000, "call_oi": 100, "put_oi": 80}]
        >>> profile = oi_profile_by_strike(chain)
        >>> profile[0]["net_oi"]
        20
        >>> profile[0]["call_dominates"]
        True
    """
    if not option_chain:
        return []

    result: list[dict[str, Any]] = []
    for row in option_chain:
        strike = float(row.get("strike", 0))
        if strike <= 0:
            continue

        call_oi = int(row.get("call_oi", row.get("ce_oi", 0)) or 0)
        put_oi = int(row.get("put_oi", row.get("pe_oi", 0)) or 0)
        net_oi = call_oi - put_oi
        total_oi = call_oi + put_oi
        pcr = put_oi / call_oi if call_oi > 0 else 0.0

        result.append({
            "strike": strike,
            "call_oi": call_oi,
            "put_oi": put_oi,
            "net_oi": net_oi,
            "total_oi": total_oi,
            "pcr": round(pcr, 4),
            "call_dominates": net_oi > 0,
            "put_dominates": net_oi < 0,
        })

    result.sort(key=lambda r: r["strike"])
    return result


def put_call_oi_ratio(chain: list[dict[str, Any]]) -> float:
    """Calculate the aggregate Put-Call OI Ratio across the full chain.

    PCR > 1.0  → more put OI than call OI → bearish sentiment / hedging.
    PCR < 1.0  → more call OI → bullish sentiment.
    PCR ≈ 1.0  → balanced market.

    Args:
        chain: List of per-strike option chain dicts.

    Returns:
        Total PE OI / Total CE OI, rounded to 4 decimal places.
        Returns ``0.0`` if total CE OI is zero.

    Examples:
        >>> put_call_oi_ratio([
        ...     {"call_oi": 100, "put_oi": 120},
        ...     {"call_oi": 80,  "put_oi": 60},
        ... ])
        1.0
    """
    total_call = sum(int(r.get("call_oi", r.get("ce_oi", 0)) or 0) for r in chain)
    total_put = sum(int(r.get("put_oi", r.get("pe_oi", 0)) or 0) for r in chain)

    if total_call == 0:
        return 0.0
    return round(total_put / total_call, 4)


def max_pain(chain: list[dict[str, Any]]) -> float:
    """Find the max-pain strike (minimum total option buyer P&L at expiry).

    Max pain is the strike price where the total financial loss to all option
    buyers (both calls and puts) is maximised — equivalently, the strike where
    option writers (sellers) retain the most premium.

    The algorithm sums, for each candidate expiry strike K:
        Σ_i  [ call_oi_i × max(0, K_i − K) + put_oi_i × max(0, K − K_i) ]
    across all strikes i.  The K that minimises this sum is max pain.

    When ``call_ltp`` / ``put_ltp`` are supplied, they are ignored — the
    standard max-pain formula uses only OI weights, not option premiums.

    Args:
        chain: List of per-strike dicts with ``strike``, ``call_oi`` /
               ``ce_oi``, ``put_oi`` / ``pe_oi``.

    Returns:
        Strike price with minimum total option holder loss at expiry.
        Returns ``0.0`` for empty chains.

    Examples:
        >>> chain = [
        ...     {"strike": 23000, "call_oi": 50000, "put_oi": 10000},
        ...     {"strike": 24000, "call_oi": 30000, "put_oi": 30000},
        ...     {"strike": 25000, "call_oi": 10000, "put_oi": 50000},
        ... ]
        >>> max_pain(chain)
        24000.0
    """
    if not chain:
        return 0.0

    strikes_data = [
        (
            float(r.get("strike", 0)),
            int(r.get("call_oi", r.get("ce_oi", 0)) or 0),
            int(r.get("put_oi", r.get("pe_oi", 0)) or 0),
        )
        for r in chain
        if float(r.get("strike", 0)) > 0
    ]

    if not strikes_data:
        return 0.0

    min_pain = float("inf")
    max_pain_strike = 0.0

    for candidate_k, _, _ in strikes_data:
        total = 0.0
        for s, call_oi, put_oi in strikes_data:
            # Call holders lose when spot (K) is below their strike
            total += call_oi * max(0.0, s - candidate_k)
            # Put holders lose when spot (K) is above their strike
            total += put_oi * max(0.0, candidate_k - s)

        if total < min_pain:
            min_pain = total
            max_pain_strike = candidate_k

    return max_pain_strike


def oi_change_top_movers(
    chain_now: list[dict[str, Any]],
    chain_prev: list[dict[str, Any]],
    top_n: int = 10,
) -> dict[str, list[dict[str, Any]]]:
    """Identify the strikes with the largest OI increases and decreases.

    Compares current OI against a previous snapshot to find the biggest
    absolute movers (both additions and reductions) on each side (calls and
    puts combined as total OI, and separately by option type).

    Args:
        chain_now:  Current option chain snapshot (list of per-strike dicts).
        chain_prev: Previous option chain snapshot (same structure as ``chain_now``).
        top_n:      Number of top movers to return per direction (default 10).

    Returns:
        Dict with four keys:
        - ``"additions"``       — list of dicts for top OI additions (sorted
                                  by ``oi_change`` descending).
        - ``"reductions"``      — list of dicts for top OI reductions (sorted
                                  by ``oi_change`` ascending — most negative first).
        - ``"call_additions"``  — top call-side OI additions.
        - ``"put_additions"``   — top put-side OI additions.

        Each mover dict contains:
        - ``"strike"``      (float)
        - ``"option_type"`` ("CE" | "PE" | "total")
        - ``"oi_now"``      (int)
        - ``"oi_prev"``     (int)
        - ``"oi_change"``   (int)   — positive = addition, negative = reduction
        - ``"change_pct"``  (float) — percentage change vs previous OI

    Examples:
        >>> now  = [{"strike": 24000, "call_oi": 120000, "put_oi": 90000}]
        >>> prev = [{"strike": 24000, "call_oi": 100000, "put_oi": 95000}]
        >>> movers = oi_change_top_movers(now, prev, top_n=5)
        >>> movers["call_additions"][0]["oi_change"]
        20000
        >>> movers["put_additions"]  # put OI fell — no additions
        []
    """
    if not chain_now:
        return {
            "additions": [],
            "reductions": [],
            "call_additions": [],
            "put_additions": [],
        }

    # Build lookup for previous snapshot keyed by strike
    prev_map: dict[float, dict[str, Any]] = {
        float(r.get("strike", 0)): r for r in chain_prev if float(r.get("strike", 0)) > 0
    }

    total_changes: list[dict[str, Any]] = []
    call_changes: list[dict[str, Any]] = []
    put_changes: list[dict[str, Any]] = []

    for row in chain_now:
        strike = float(row.get("strike", 0))
        if strike <= 0:
            continue

        call_oi = int(row.get("call_oi", row.get("ce_oi", 0)) or 0)
        put_oi = int(row.get("put_oi", row.get("pe_oi", 0)) or 0)

        prev = prev_map.get(strike, {})
        prev_call = int(prev.get("call_oi", prev.get("ce_oi", 0)) or 0)
        prev_put = int(prev.get("put_oi", prev.get("pe_oi", 0)) or 0)

        # Call side
        call_change = call_oi - prev_call
        call_pct = (call_change / prev_call * 100.0) if prev_call > 0 else 0.0
        call_entry: dict[str, Any] = {
            "strike": strike,
            "option_type": "CE",
            "oi_now": call_oi,
            "oi_prev": prev_call,
            "oi_change": call_change,
            "change_pct": round(call_pct, 2),
        }
        call_changes.append(call_entry)

        # Put side
        put_change = put_oi - prev_put
        put_pct = (put_change / prev_put * 100.0) if prev_put > 0 else 0.0
        put_entry: dict[str, Any] = {
            "strike": strike,
            "option_type": "PE",
            "oi_now": put_oi,
            "oi_prev": prev_put,
            "oi_change": put_change,
            "change_pct": round(put_pct, 2),
        }
        put_changes.append(put_entry)

        # Total (net across both sides)
        total_change = call_change + put_change
        prev_total = prev_call + prev_put
        total_pct = (total_change / prev_total * 100.0) if prev_total > 0 else 0.0
        total_changes.append({
            "strike": strike,
            "option_type": "total",
            "oi_now": call_oi + put_oi,
            "oi_prev": prev_total,
            "oi_change": total_change,
            "change_pct": round(total_pct, 2),
        })

    # Sort and slice
    additions = sorted(
        [r for r in total_changes if r["oi_change"] > 0],
        key=lambda r: r["oi_change"],
        reverse=True,
    )[:top_n]

    reductions = sorted(
        [r for r in total_changes if r["oi_change"] < 0],
        key=lambda r: r["oi_change"],
    )[:top_n]

    call_additions = sorted(
        [r for r in call_changes if r["oi_change"] > 0],
        key=lambda r: r["oi_change"],
        reverse=True,
    )[:top_n]

    put_additions = sorted(
        [r for r in put_changes if r["oi_change"] > 0],
        key=lambda r: r["oi_change"],
        reverse=True,
    )[:top_n]

    return {
        "additions": additions,
        "reductions": reductions,
        "call_additions": call_additions,
        "put_additions": put_additions,
    }
