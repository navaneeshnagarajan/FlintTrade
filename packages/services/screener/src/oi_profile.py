"""OI Profile with butterfly analysis.

The OI Profile shows Open Interest distribution across strikes and how it
changes over time. Key concepts:
- OI Butterfly = CE_OI - PE_OI per strike.
  Positive → more call OI (resistance). Negative → more put OI (support).
- OI Change = today's OI - yesterday's OI (fresh writing vs unwinding).
- Futures OHLCV overlay for price context against OI distribution.

This module accepts pre-fetched data (option chain dict + futures candles)
rather than making API calls directly, keeping it unit-testable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .option_chain import OptionChainSnapshot, StrikeData

logger = logging.getLogger("flinttrade.screener.oi_profile")


@dataclass
class OIProfileStrike:
    """OI profile data for a single strike.

    Attributes:
        strike_price: Strike price.
        ce_oi: Call open interest (current).
        pe_oi: Put open interest (current).
        oi_butterfly: CE_OI - PE_OI (positive = call heavy, negative = put heavy).
        ce_oi_change: Change in CE OI from previous snapshot.
        pe_oi_change: Change in PE OI from previous snapshot.
        ce_volume: CE trading volume.
        pe_volume: PE trading volume.
    """

    strike_price: float = 0.0
    ce_oi: int = 0
    pe_oi: int = 0
    oi_butterfly: int = 0
    ce_oi_change: int = 0
    pe_oi_change: int = 0
    ce_volume: int = 0
    pe_volume: int = 0

    @property
    def total_oi(self) -> int:
        """Combined CE + PE OI at this strike."""
        return self.ce_oi + self.pe_oi

    @property
    def is_call_heavy(self) -> bool:
        """More call OI than put OI at this strike."""
        return self.oi_butterfly > 0

    @property
    def is_put_heavy(self) -> bool:
        """More put OI than call OI at this strike (support zone)."""
        return self.oi_butterfly < 0


@dataclass
class FuturesOHLCV:
    """A single futures OHLCV candle.

    Attributes:
        timestamp: Unix timestamp (seconds).
        open: Open price.
        high: High price.
        low: Low price.
        close: Close price.
        volume: Volume traded.
        oi: Futures open interest at this bar (optional).
    """

    timestamp: int = 0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    oi: int = 0


@dataclass
class OIProfileResult:
    """Complete OI profile analysis result.

    Attributes:
        strikes: Strike prices in the profile.
        ce_oi: Call OI per strike (same order as strikes).
        pe_oi: Put OI per strike (same order as strikes).
        oi_butterfly: CE_OI - PE_OI per strike.
        oi_change: Net OI change (CE + PE) per strike vs previous snapshot.
        ce_oi_change: CE OI change per strike.
        pe_oi_change: PE OI change per strike.
        futures_ohlcv: Futures candles for price overlay.
        profile_strikes: Full per-strike profile data.
        max_ce_strike: Strike with highest CE OI (resistance).
        max_pe_strike: Strike with highest PE OI (support).
        spot: Spot price at snapshot time.
    """

    strikes: list[float] = field(default_factory=list)
    ce_oi: list[int] = field(default_factory=list)
    pe_oi: list[int] = field(default_factory=list)
    oi_butterfly: list[int] = field(default_factory=list)
    oi_change: list[int] = field(default_factory=list)
    ce_oi_change: list[int] = field(default_factory=list)
    pe_oi_change: list[int] = field(default_factory=list)
    futures_ohlcv: list[FuturesOHLCV] = field(default_factory=list)
    profile_strikes: list[OIProfileStrike] = field(default_factory=list)
    max_ce_strike: float = 0.0
    max_pe_strike: float = 0.0
    spot: float = 0.0


def _parse_futures_candles(
    raw_candles: list[dict[str, Any]],
) -> list[FuturesOHLCV]:
    """Parse raw futures candle dicts into FuturesOHLCV dataclasses.

    Args:
        raw_candles: List of dicts with keys: time, open, high, low, close,
                     volume, oi (all optional except time).

    Returns:
        List of FuturesOHLCV objects.
    """
    result: list[FuturesOHLCV] = []
    for c in raw_candles:
        result.append(FuturesOHLCV(
            timestamp=int(c.get("time", 0)),
            open=float(c.get("open", 0)),
            high=float(c.get("high", 0)),
            low=float(c.get("low", 0)),
            close=float(c.get("close", 0)),
            volume=float(c.get("volume", 0)),
            oi=int(c.get("oi", 0)),
        ))
    return result


def calculate_oi_profile(
    snapshot: OptionChainSnapshot,
    futures_candles: list[dict[str, Any]],
    previous_snapshot: OptionChainSnapshot | None = None,
) -> OIProfileResult:
    """Calculate OI profile with butterfly analysis.

    OI Butterfly = CE_OI - PE_OI per strike.
    OI Change    = current OI - previous OI per strike (if previous provided).

    Args:
        snapshot: Current option chain snapshot with OI per strike.
        futures_candles: List of futures OHLCV dicts for price overlay.
        previous_snapshot: Previous option chain snapshot for OI change
                           calculation. If None, OI change is reported as 0.

    Returns:
        OIProfileResult with butterfly, OI change, and futures overlay.
    """
    if not snapshot.strikes:
        return OIProfileResult(spot=snapshot.spot_price)

    # Build previous OI map for change calculation
    prev_map: dict[float, StrikeData] = {}
    if previous_snapshot:
        prev_map = {s.strike_price: s for s in previous_snapshot.strikes}

    sorted_strikes = sorted(snapshot.strikes, key=lambda s: s.strike_price)

    strikes: list[float] = []
    ce_oi: list[int] = []
    pe_oi: list[int] = []
    oi_butterfly: list[int] = []
    oi_change: list[int] = []
    ce_oi_change: list[int] = []
    pe_oi_change: list[int] = []
    profile_strikes: list[OIProfileStrike] = []

    for s in sorted_strikes:
        prev = prev_map.get(s.strike_price)
        prev_ce = prev.ce_oi if prev else 0
        prev_pe = prev.pe_oi if prev else 0

        butterfly = s.ce_oi - s.pe_oi
        delta_ce = s.ce_oi - prev_ce
        delta_pe = s.pe_oi - prev_pe
        net_change = delta_ce + delta_pe

        strikes.append(s.strike_price)
        ce_oi.append(s.ce_oi)
        pe_oi.append(s.pe_oi)
        oi_butterfly.append(butterfly)
        oi_change.append(net_change)
        ce_oi_change.append(delta_ce)
        pe_oi_change.append(delta_pe)

        profile_strikes.append(OIProfileStrike(
            strike_price=s.strike_price,
            ce_oi=s.ce_oi,
            pe_oi=s.pe_oi,
            oi_butterfly=butterfly,
            ce_oi_change=delta_ce,
            pe_oi_change=delta_pe,
            ce_volume=s.ce_volume,
            pe_volume=s.pe_volume,
        ))

    # Key levels
    max_ce_strike = 0.0
    max_pe_strike = 0.0
    if sorted_strikes:
        max_ce = max(sorted_strikes, key=lambda s: s.ce_oi)
        max_pe = max(sorted_strikes, key=lambda s: s.pe_oi)
        max_ce_strike = max_ce.strike_price
        max_pe_strike = max_pe.strike_price

    futures_ohlcv = _parse_futures_candles(futures_candles)

    return OIProfileResult(
        strikes=strikes,
        ce_oi=ce_oi,
        pe_oi=pe_oi,
        oi_butterfly=oi_butterfly,
        oi_change=oi_change,
        ce_oi_change=ce_oi_change,
        pe_oi_change=pe_oi_change,
        futures_ohlcv=futures_ohlcv,
        profile_strikes=profile_strikes,
        max_ce_strike=max_ce_strike,
        max_pe_strike=max_pe_strike,
        spot=snapshot.spot_price,
    )
