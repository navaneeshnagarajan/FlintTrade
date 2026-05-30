"""IV analytics — smile, skew, ATM IV, and term structure from raw chain dicts.

This module provides the P1 analytics layer for implied volatility analysis.
It operates on raw ``list[dict]`` option chain data (the format used by
OpenAlgo's IV smile service and the FlintTrade ``/ft-api/v1/ivsmile`` route)
rather than the ``OptionChainSnapshot`` dataclass used internally by
``iv_smile.py``.

The four public functions mirror the analytics computed by OpenAlgo's
``iv_smile_service.py`` and ``iv_chart_service.py``:

1. :func:`compute_iv_smile`    — per-strike IV (calls + puts, with moneyness).
2. :func:`compute_iv_skew`     — 25-delta put IV minus 25-delta call IV.
3. :func:`compute_atm_iv`      — at-the-money IV (average of ATM CE and PE IV).
4. :func:`compute_iv_term_structure` — ATM IV versus days-to-expiry.

Input ``option_chain`` dict format::

    {
        "strike":    float,
        "call_iv":   float,   # % (e.g. 15.5 means 15.5%)  — 0 if unavailable
        "put_iv":    float,   # % — 0 if unavailable
        "call_delta": float,  # optional, 0–1 for calls
        "put_delta":  float,  # optional, −1–0 for puts
        "call_oi":   int,     # optional, used for ATM fallback
        "put_oi":    int,     # optional
    }

Typical usage::

    from flinttrade_screener.iv_analytics import (
        compute_iv_smile,
        compute_iv_skew,
        compute_atm_iv,
        compute_iv_term_structure,
    )

    chain = [{"strike": 24000, "call_iv": 16.2, "put_iv": 16.8, ...}, ...]
    smile = compute_iv_smile(chain, spot=24050.0)
    skew  = compute_iv_skew(smile)
    atm   = compute_atm_iv(smile, spot=24050.0)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("flinttrade.screener.iv_analytics")


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def compute_iv_smile(
    option_chain: list[dict[str, Any]],
    spot: float,
) -> list[dict[str, Any]]:
    """Build the IV smile curve from a per-strike option chain.

    Each output row contains the strike, moneyness, call IV, put IV, mid IV,
    and the call/put deltas (when supplied by the caller).

    Args:
        option_chain: List of per-strike dicts.  Required keys: ``strike``,
                      ``call_iv``, ``put_iv``.  Optional: ``call_delta``,
                      ``put_delta``.  All IV values must be expressed as
                      percentages (e.g. 15.5 for 15.5%), not decimals.
        spot:         Current spot / futures price.

    Returns:
        List of dicts sorted by strike ascending, each with:
        - ``strike``      (float)
        - ``moneyness``   (float) — (strike − spot) / spot × 100
        - ``call_iv``     (float) — call implied volatility (%)
        - ``put_iv``      (float) — put implied volatility (%)
        - ``mid_iv``      (float) — (call_iv + put_iv) / 2, or max if one is 0
        - ``call_delta``  (float) — call delta (0 to 1)
        - ``put_delta``   (float) — put delta (−1 to 0)
        - ``is_atm``      (bool)  — True for the strike nearest to spot

    Examples:
        >>> chain = [{"strike": 24000, "call_iv": 16.0, "put_iv": 17.0,
        ...           "call_delta": 0.5, "put_delta": -0.5}]
        >>> smile = compute_iv_smile(chain, spot=24000.0)
        >>> smile[0]["mid_iv"]
        16.5
        >>> smile[0]["is_atm"]
        True
    """
    if not option_chain or spot <= 0:
        return []

    rows: list[dict[str, Any]] = []
    for item in option_chain:
        strike = float(item.get("strike", 0))
        if strike <= 0:
            continue

        call_iv = float(item.get("call_iv", item.get("ce_iv", 0)) or 0)
        put_iv = float(item.get("put_iv", item.get("pe_iv", 0)) or 0)
        call_delta = float(item.get("call_delta", item.get("ce_delta", 0)) or 0)
        put_delta = float(item.get("put_delta", item.get("pe_delta", 0)) or 0)

        if call_iv > 0 and put_iv > 0:
            mid_iv = (call_iv + put_iv) / 2.0
        else:
            mid_iv = max(call_iv, put_iv)

        moneyness = (strike - spot) / spot * 100.0

        rows.append({
            "strike": strike,
            "moneyness": round(moneyness, 3),
            "call_iv": round(call_iv, 4),
            "put_iv": round(put_iv, 4),
            "mid_iv": round(mid_iv, 4),
            "call_delta": round(call_delta, 4),
            "put_delta": round(put_delta, 4),
            "is_atm": False,  # filled in below
        })

    if not rows:
        return []

    rows.sort(key=lambda r: r["strike"])

    # Flag the ATM strike (nearest to spot)
    atm_idx = min(range(len(rows)), key=lambda i: abs(rows[i]["strike"] - spot))
    rows[atm_idx]["is_atm"] = True

    return rows


def compute_iv_skew(smile: list[dict[str, Any]]) -> float:
    """Calculate the 25-delta IV skew (put IV minus call IV at ±25 delta).

    Skew > 0 → puts are more expensive than equivalent calls (typical for
    Indian equity indices — downside fear premium).

    The function first looks for strikes where ``call_delta`` and
    ``put_delta`` are populated (closest to ±0.25 delta).  If delta values
    are absent or zero, it falls back to a ±5% moneyness approximation.

    Args:
        smile: Output of :func:`compute_iv_smile`.

    Returns:
        IV skew in percentage points.  Returns ``0.0`` when the smile is
        empty or when either the 25-delta call or 25-delta put IV cannot be
        determined.

    Examples:
        >>> smile = [
        ...     {"strike": 21600, "moneyness": -2.0, "call_iv": 14.0,
        ...      "put_iv": 18.0, "mid_iv": 16.0,
        ...      "call_delta": 0.2, "put_delta": -0.28, "is_atm": False},
        ...     {"strike": 22000, "moneyness": -0.18, "call_iv": 15.5,
        ...      "put_iv": 16.0, "mid_iv": 15.75,
        ...      "call_delta": 0.5, "put_delta": -0.5, "is_atm": True},
        ...     {"strike": 22400, "moneyness": 1.6, "call_iv": 13.5,
        ...      "put_iv": 14.0, "mid_iv": 13.75,
        ...      "call_delta": 0.26, "put_delta": -0.22, "is_atm": False},
        ... ]
        >>> skew = compute_iv_skew(smile)
        >>> isinstance(skew, float)
        True
    """
    if not smile:
        return 0.0

    # Separate OTM candidates by side
    atm_row = next((r for r in smile if r.get("is_atm")), None)
    atm_strike = atm_row["strike"] if atm_row else None

    target_delta = 0.25

    # Try delta-based search first
    call_iv_25d = _find_iv_by_delta(smile, "call", target_delta, atm_strike)
    put_iv_25d = _find_iv_by_delta(smile, "put", target_delta, atm_strike)

    # Fall back to moneyness-based search (±5% OTM)
    if call_iv_25d == 0.0 or put_iv_25d == 0.0:
        call_iv_25d, put_iv_25d = _find_iv_by_moneyness(smile, atm_strike)

    if call_iv_25d > 0 and put_iv_25d > 0:
        return round(put_iv_25d - call_iv_25d, 4)

    return 0.0


def compute_atm_iv(smile: list[dict[str, Any]], spot: float) -> float:
    """Return the at-the-money implied volatility.

    The ATM IV is the average of the call IV and put IV at the strike
    nearest to ``spot``.  If only one side is available (e.g. deep expiry
    data), the available IV is returned.

    Args:
        smile: Output of :func:`compute_iv_smile`.
        spot:  Current spot / futures price.

    Returns:
        ATM IV in percentage points.  Returns ``0.0`` if the smile is
        empty or if no IV data is available at the ATM strike.

    Examples:
        >>> smile = compute_iv_smile(
        ...     [{"strike": 24000, "call_iv": 16.0, "put_iv": 17.0}],
        ...     spot=24000.0,
        ... )
        >>> compute_atm_iv(smile, spot=24000.0)
        16.5
    """
    if not smile or spot <= 0:
        return 0.0

    atm = min(smile, key=lambda r: abs(r["strike"] - spot))
    call_iv = atm.get("call_iv", 0.0)
    put_iv = atm.get("put_iv", 0.0)

    if call_iv > 0 and put_iv > 0:
        return round((call_iv + put_iv) / 2.0, 4)
    return round(max(call_iv, put_iv), 4)


def compute_iv_term_structure(
    chains_by_expiry: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the IV term structure (ATM IV across multiple expiries).

    The term structure shows how ATM IV varies with time-to-expiry.  Typical
    shapes: contango (near-term IV lower than far-term IV) vs backwardation
    (near-term IV elevated due to event risk or high vol regime).

    Args:
        chains_by_expiry: Dict mapping expiry label → chain data dict.
            Each value must contain:
            - ``"dte"``    (int)   — days to expiry
            - ``"spot"``   (float) — spot price for this expiry (optional,
                                     falls back to the top-level spot key)
            - ``"strikes"`` (list[dict]) — per-strike dicts with
                                          ``call_iv`` / ``put_iv`` keys

    Returns:
        List of dicts sorted by ``dte`` ascending, each with:
        - ``"expiry"``   (str)   — expiry label
        - ``"dte"``      (int)   — days to expiry
        - ``"atm_iv"``   (float) — ATM IV for this expiry (%)
        - ``"call_iv"``  (float) — ATM call IV (%)
        - ``"put_iv"``   (float) — ATM put IV (%)

    Examples:
        >>> ts = compute_iv_term_structure({
        ...     "26MAR26": {"dte": 7, "spot": 24000,
        ...                 "strikes": [{"strike": 24000,
        ...                              "call_iv": 15.0, "put_iv": 16.0}]},
        ...     "24APR26": {"dte": 35, "spot": 24000,
        ...                 "strikes": [{"strike": 24000,
        ...                              "call_iv": 13.5, "put_iv": 14.0}]},
        ... })
        >>> ts[0]["dte"] <= ts[1]["dte"]
        True
    """
    if not chains_by_expiry:
        return []

    results: list[dict[str, Any]] = []

    for expiry_label, chain_data in chains_by_expiry.items():
        dte = int(chain_data.get("dte", 0))
        spot = float(chain_data.get("spot", 0) or 0)
        strikes = chain_data.get("strikes", [])

        if not strikes or spot <= 0:
            logger.debug("Skipping expiry %s — missing data", expiry_label)
            continue

        smile = compute_iv_smile(strikes, spot)
        if not smile:
            continue

        atm = min(smile, key=lambda r: abs(r["strike"] - spot))
        call_iv = atm.get("call_iv", 0.0)
        put_iv = atm.get("put_iv", 0.0)

        if call_iv > 0 and put_iv > 0:
            atm_iv = round((call_iv + put_iv) / 2.0, 4)
        else:
            atm_iv = round(max(call_iv, put_iv), 4)

        if atm_iv <= 0:
            continue

        results.append({
            "expiry": expiry_label,
            "dte": dte,
            "atm_iv": atm_iv,
            "call_iv": round(call_iv, 4),
            "put_iv": round(put_iv, 4),
        })

    results.sort(key=lambda r: r["dte"])
    return results


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _find_iv_by_delta(
    smile: list[dict[str, Any]],
    side: str,
    target_delta: float,
    atm_strike: float | None,
) -> float:
    """Find IV at the strike closest to ``target_delta`` on the given side.

    Args:
        smile:         Output of :func:`compute_iv_smile`.
        side:          ``"call"`` or ``"put"``.
        target_delta:  Absolute delta to search for (e.g. 0.25).
        atm_strike:    ATM strike price for OTM filtering.

    Returns:
        IV at the closest-to-target delta strike, or 0.0 if not found.
    """
    if side == "call":
        candidates = [
            r for r in smile
            if r.get("call_delta", 0) > 0
            and (atm_strike is None or r["strike"] > atm_strike)
        ]
        if not candidates:
            candidates = [r for r in smile if r.get("call_delta", 0) > 0]
        if candidates:
            best = min(candidates, key=lambda r: abs(r["call_delta"] - target_delta))
            return best.get("call_iv", 0.0)
    else:  # put
        candidates = [
            r for r in smile
            if r.get("put_delta", 0) < 0
            and (atm_strike is None or r["strike"] < atm_strike)
        ]
        if not candidates:
            candidates = [r for r in smile if r.get("put_delta", 0) < 0]
        if candidates:
            best = min(candidates, key=lambda r: abs(abs(r["put_delta"]) - target_delta))
            return best.get("put_iv", 0.0)

    return 0.0


def _find_iv_by_moneyness(
    smile: list[dict[str, Any]],
    atm_strike: float | None,
) -> tuple[float, float]:
    """Fall back to ±5% moneyness for 25-delta proxy.

    Args:
        smile:       Output of :func:`compute_iv_smile`.
        atm_strike:  ATM strike price.

    Returns:
        Tuple of (call_iv_25d, put_iv_25d).  Either element is 0.0 if
        no suitable strike is found.
    """
    if not smile or atm_strike is None:
        return 0.0, 0.0

    otm_pct = 0.05  # 5% OTM as proxy for 25-delta
    target_call_k = atm_strike * (1 + otm_pct)
    target_put_k = atm_strike * (1 - otm_pct)

    # OTM call candidates (above ATM)
    call_candidates = [r for r in smile if r["strike"] > atm_strike and r["call_iv"] > 0]
    put_candidates = [r for r in smile if r["strike"] < atm_strike and r["put_iv"] > 0]

    call_iv_25d = 0.0
    put_iv_25d = 0.0

    if call_candidates:
        best_call = min(call_candidates, key=lambda r: abs(r["strike"] - target_call_k))
        call_iv_25d = best_call["call_iv"]

    if put_candidates:
        best_put = min(put_candidates, key=lambda r: abs(r["strike"] - target_put_k))
        put_iv_25d = best_put["put_iv"]

    return call_iv_25d, put_iv_25d
