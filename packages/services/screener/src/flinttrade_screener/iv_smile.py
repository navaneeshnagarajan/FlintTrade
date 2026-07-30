"""IV smile curve extraction from option chain data.

The IV smile (or volatility smile/skew) shows how implied volatility varies
across strike prices for a single expiry. Key metrics:
- ATM IV: IV at the at-the-money strike.
- Skew: 25-delta put IV - 25-delta call IV. Positive skew = put skew (typical
  for equity indices — downside protection is more expensive than upside calls).
- Smile curvature: Wings have higher IV than ATM (V-shaped smile).

For Indian indices, the typical pattern is:
- Deep OTM puts (far below spot) have very high IV (crash risk premium).
- Calls are relatively cheaper OTM.
- This creates a negative / put skew.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .option_chain import OptionChainSnapshot, StrikeData

logger = logging.getLogger("flinttrade.screener.iv_smile")


@dataclass
class IVSmilePoint:
    """IV smile data for a single strike.

    Attributes:
        strike_price: Strike price.
        moneyness: (strike - spot) / spot * 100 (percent).
        call_iv: Call IV at this strike (%).
        put_iv: Put IV at this strike (%).
        mid_iv: Average of call and put IV.
        call_delta: Call delta (0 to 1).
        put_delta: Put delta (-1 to 0).
    """

    strike_price: float = 0.0
    moneyness: float = 0.0
    call_iv: float = 0.0
    put_iv: float = 0.0
    mid_iv: float = 0.0
    call_delta: float = 0.0
    put_delta: float = 0.0


@dataclass
class IVSmileResult:
    """Complete IV smile analysis for a single expiry.

    Attributes:
        strikes: Strike prices in the chain.
        call_iv: Call IVs per strike (%, same order as strikes).
        put_iv: Put IVs per strike (%, same order as strikes).
        atm_iv: ATM IV (average of ATM call and put IV).
        atm_strike: Nearest-to-spot strike.
        skew: 25-delta put IV - 25-delta call IV (positive = put skew).
        points: Full smile data with moneyness and delta per strike.
        spot: Spot price used.
        expiry_date: Expiry label or date string.
    """

    strikes: list[float] = field(default_factory=list)
    call_iv: list[float] = field(default_factory=list)
    put_iv: list[float] = field(default_factory=list)
    atm_iv: float = 0.0
    atm_strike: float = 0.0
    skew: float = 0.0
    points: list[IVSmilePoint] = field(default_factory=list)
    spot: float = 0.0
    expiry_date: str = ""

    @property
    def has_put_skew(self) -> bool:
        """True if puts are more expensive than equivalent calls (normal for indices)."""
        return self.skew > 0


def _find_atm_strike(strikes: list[StrikeData], spot: float) -> StrikeData | None:
    """Return the strike data closest to spot price.

    Args:
        strikes: Sorted list of StrikeData.
        spot: Current spot price.

    Returns:
        StrikeData closest to spot, or None if strikes is empty.
    """
    if not strikes:
        return None
    return min(strikes, key=lambda s: abs(s.strike_price - spot))


def _find_25delta_strike(
    strikes: list[StrikeData],
    option_type: str,
    spot: float,
) -> StrikeData | None:
    """Find the strike closest to 25-delta for calls or puts.

    For the skew calculation, we look for the strike where |delta| ≈ 0.25.
    This is typically about 5-10% OTM for most underlyings.

    Args:
        strikes: List of StrikeData ordered by strike price.
        option_type: "CE" for calls (delta 0-1) or "PE" for puts (delta -1 to 0).
        spot: Current spot price (used as fallback when delta is not available).

    Returns:
        StrikeData closest to 25-delta, or None.
    """
    if not strikes:
        return None

    target_delta = 0.25

    if option_type == "CE":
        # For calls, find strike where ce_delta ≈ 0.25 (OTM calls)
        candidates = [s for s in strikes if s.strike_price > spot and s.ce_delta > 0]
        if not candidates:
            candidates = [s for s in strikes if s.ce_delta > 0]
        if candidates:
            return min(candidates, key=lambda s: abs(s.ce_delta - target_delta))
        # Fallback: estimate ~10% OTM call
        target_k = spot * 1.10
        return min(strikes, key=lambda s: abs(s.strike_price - target_k))

    else:  # PE
        # For puts, find strike where |pe_delta| ≈ 0.25 (OTM puts)
        candidates = [s for s in strikes if s.strike_price < spot and s.pe_delta < 0]
        if not candidates:
            candidates = [s for s in strikes if s.pe_delta < 0]
        if candidates:
            return min(candidates, key=lambda s: abs(abs(s.pe_delta) - target_delta))
        # Fallback: estimate ~10% OTM put
        target_k = spot * 0.90
        return min(strikes, key=lambda s: abs(s.strike_price - target_k))


def calculate_iv_smile(
    snapshot: OptionChainSnapshot,
    spot: float,
    expiry_date: str = "",
) -> IVSmileResult:
    """Extract IV smile curve from an option chain snapshot.

    Args:
        snapshot: Full option chain snapshot with per-strike CE/PE IVs.
        spot: Current spot/futures price of the underlying.
        expiry_date: Expiry label or date string for annotation.

    Returns:
        IVSmileResult with IV per strike, ATM IV, skew, and full smile data.
    """
    if not snapshot.strikes or spot <= 0:
        return IVSmileResult(spot=spot, expiry_date=expiry_date)

    # Build sorted strike list
    sorted_strikes = sorted(snapshot.strikes, key=lambda s: s.strike_price)

    strikes: list[float] = []
    call_ivs: list[float] = []
    put_ivs: list[float] = []
    points: list[IVSmilePoint] = []

    for s in sorted_strikes:
        moneyness = (s.strike_price - spot) / spot * 100.0
        call_iv = s.ce_iv if s.ce_iv > 0 else 0.0
        put_iv = s.pe_iv if s.pe_iv > 0 else 0.0
        mid_iv = (call_iv + put_iv) / 2.0 if (call_iv > 0 and put_iv > 0) else max(call_iv, put_iv)

        strikes.append(s.strike_price)
        call_ivs.append(call_iv)
        put_ivs.append(put_iv)
        points.append(IVSmilePoint(
            strike_price=s.strike_price,
            moneyness=round(moneyness, 3),
            call_iv=call_iv,
            put_iv=put_iv,
            mid_iv=round(mid_iv, 4),
            call_delta=s.ce_delta,
            put_delta=s.pe_delta,
        ))

    # ATM IV
    atm_data = _find_atm_strike(sorted_strikes, spot)
    atm_strike = atm_data.strike_price if atm_data else spot
    if atm_data:
        call_iv_atm = atm_data.ce_iv if atm_data.ce_iv > 0 else 0.0
        put_iv_atm = atm_data.pe_iv if atm_data.pe_iv > 0 else 0.0
        atm_iv = (
            (call_iv_atm + put_iv_atm) / 2.0
            if (call_iv_atm > 0 and put_iv_atm > 0)
            else max(call_iv_atm, put_iv_atm)
        )
    else:
        atm_iv = 0.0

    # Skew = 25-delta put IV - 25-delta call IV
    skew = 0.0
    d25_put = _find_25delta_strike(sorted_strikes, "PE", spot)
    d25_call = _find_25delta_strike(sorted_strikes, "CE", spot)

    if d25_put and d25_call:
        put_iv_25d = d25_put.pe_iv if d25_put.pe_iv > 0 else 0.0
        call_iv_25d = d25_call.ce_iv if d25_call.ce_iv > 0 else 0.0
        if put_iv_25d > 0 and call_iv_25d > 0:
            skew = round(put_iv_25d - call_iv_25d, 4)

    return IVSmileResult(
        strikes=strikes,
        call_iv=call_ivs,
        put_iv=put_ivs,
        atm_iv=round(atm_iv, 4),
        atm_strike=atm_strike,
        skew=skew,
        points=points,
        spot=spot,
        expiry_date=expiry_date,
    )
