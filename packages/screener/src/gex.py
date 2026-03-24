"""Gamma Exposure (GEX) calculation for option chains.

GEX measures the aggregate gamma risk held by market makers (dealers).
Dealers are assumed to be short options (buying from retail), so:
- Call GEX is positive  (dealers long gamma on calls they've sold puts on)
- Put GEX is negative   (dealers short gamma on puts they've sold)

Formula (per strike):
    GEX = gamma * OI * lot_size * spot^2 / 100

Net GEX = sum(call_gex) + sum(put_gex)

Positive net GEX → dealers are long gamma → mean-reverting, stable market.
Negative net GEX → dealers are short gamma → trend-following, volatile market.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .option_chain import OptionChainSnapshot, StrikeData

logger = logging.getLogger("flinttrade.screener.gex")


@dataclass
class GEXStrike:
    """GEX components for a single strike."""

    strike_price: float = 0.0
    call_gex: float = 0.0
    put_gex: float = 0.0
    net_gex: float = 0.0
    call_oi: int = 0
    put_oi: int = 0
    call_gamma: float = 0.0
    put_gamma: float = 0.0


@dataclass
class OIWall:
    """OI concentration acting as support or resistance."""

    strike_price: float = 0.0
    option_type: str = ""   # "CE" or "PE"
    oi: int = 0
    gex: float = 0.0


@dataclass
class GEXResult:
    """Full Gamma Exposure analysis result.

    Attributes:
        strikes: Per-strike GEX breakdown.
        total_call_gex: Sum of call-side GEX across all strikes.
        total_put_gex: Sum of put-side GEX across all strikes (negative).
        total_net_gex: Net dealer GEX (positive = long gamma / stable).
        top_gamma_strikes: Top 5 strikes by absolute net GEX (highest gamma exposure).
        oi_walls: Strikes with OI concentration acting as barriers.
        spot: Spot price used for calculation.
        lot_size: Lot size used for calculation.
    """

    strikes: list[GEXStrike] = field(default_factory=list)
    total_call_gex: float = 0.0
    total_put_gex: float = 0.0
    total_net_gex: float = 0.0
    top_gamma_strikes: list[GEXStrike] = field(default_factory=list)
    oi_walls: list[OIWall] = field(default_factory=list)
    spot: float = 0.0
    lot_size: int = 0

    @property
    def is_long_gamma(self) -> bool:
        """Dealers are long gamma — expect mean-reversion, stable price action."""
        return self.total_net_gex > 0

    @property
    def is_short_gamma(self) -> bool:
        """Dealers are short gamma — expect trending, volatile price action."""
        return self.total_net_gex < 0


def _gex_for_strike(
    strike: StrikeData,
    spot: float,
    lot_size: int,
) -> GEXStrike:
    """Calculate GEX components for a single strike.

    Args:
        strike: Strike data with OI and gamma values.
        spot: Current spot price of the underlying.
        lot_size: Lot size for the contract.

    Returns:
        GEXStrike with call and put GEX values.
    """
    spot_sq_factor = (spot ** 2) / 100.0

    call_gex = strike.ce_gamma * strike.ce_oi * lot_size * spot_sq_factor
    put_gex = -(strike.pe_gamma * strike.pe_oi * lot_size * spot_sq_factor)

    return GEXStrike(
        strike_price=strike.strike_price,
        call_gex=call_gex,
        put_gex=put_gex,
        net_gex=call_gex + put_gex,
        call_oi=strike.ce_oi,
        put_oi=strike.pe_oi,
        call_gamma=strike.ce_gamma,
        put_gamma=strike.pe_gamma,
    )


def _detect_oi_walls(
    snapshot: OptionChainSnapshot,
    n: int = 3,
) -> list[OIWall]:
    """Identify top N OI concentration strikes as walls.

    Args:
        snapshot: Option chain snapshot with strike data.
        n: Number of top OI walls to return per side.

    Returns:
        List of OIWall entries sorted by OI descending.
    """
    walls: list[OIWall] = []

    sorted_ce = sorted(snapshot.strikes, key=lambda s: s.ce_oi, reverse=True)
    for s in sorted_ce[:n]:
        if s.ce_oi > 0:
            walls.append(OIWall(
                strike_price=s.strike_price,
                option_type="CE",
                oi=s.ce_oi,
                gex=0.0,
            ))

    sorted_pe = sorted(snapshot.strikes, key=lambda s: s.pe_oi, reverse=True)
    for s in sorted_pe[:n]:
        if s.pe_oi > 0:
            walls.append(OIWall(
                strike_price=s.strike_price,
                option_type="PE",
                oi=s.pe_oi,
                gex=0.0,
            ))

    return walls


def calculate_gex(
    snapshot: OptionChainSnapshot,
    spot: float,
    lot_size: int,
) -> GEXResult:
    """Calculate Gamma Exposure (GEX) from an option chain snapshot.

    GEX per strike:
        call_gex =  gamma * CE_OI * lot_size * spot^2 / 100  (positive)
        put_gex  = -gamma * PE_OI * lot_size * spot^2 / 100  (negative)

    Args:
        snapshot: Full option chain snapshot with gamma and OI per strike.
        spot: Current spot/futures price of the underlying.
        lot_size: Contract lot size (e.g. 75 for NIFTY, 30 for BANKNIFTY).

    Returns:
        GEXResult with per-strike breakdown, totals, and key levels.
    """
    if not snapshot.strikes or spot <= 0 or lot_size <= 0:
        return GEXResult(spot=spot, lot_size=lot_size)

    gex_strikes: list[GEXStrike] = []
    total_call_gex = 0.0
    total_put_gex = 0.0

    for s in snapshot.strikes:
        gs = _gex_for_strike(s, spot, lot_size)
        gex_strikes.append(gs)
        total_call_gex += gs.call_gex
        total_put_gex += gs.put_gex

    total_net_gex = total_call_gex + total_put_gex

    # Top 5 gamma strikes by absolute net GEX
    top_gamma = sorted(gex_strikes, key=lambda g: abs(g.net_gex), reverse=True)[:5]

    oi_walls = _detect_oi_walls(snapshot)

    return GEXResult(
        strikes=gex_strikes,
        total_call_gex=total_call_gex,
        total_put_gex=total_put_gex,
        total_net_gex=total_net_gex,
        top_gamma_strikes=top_gamma,
        oi_walls=oi_walls,
        spot=spot,
        lot_size=lot_size,
    )
