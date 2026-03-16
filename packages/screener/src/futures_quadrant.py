"""4-Quadrant Futures OI analysis, basis, and rollover tracking.

Quadrants:
  Long Buildup:    OI ↑ + Price ↑  (fresh longs)
  Short Buildup:   OI ↑ + Price ↓  (fresh shorts)
  Short Covering:  OI ↓ + Price ↑  (shorts exiting)
  Long Unwinding:  OI ↓ + Price ↓  (longs exiting)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger("flinttrade.screener.futures_quadrant")


class Quadrant(str, Enum):
    LONG_BUILDUP = "LONG_BUILDUP"
    SHORT_BUILDUP = "SHORT_BUILDUP"
    SHORT_COVERING = "SHORT_COVERING"
    LONG_UNWINDING = "LONG_UNWINDING"
    NEUTRAL = "NEUTRAL"


@dataclass
class FuturesSnapshot:
    """Point-in-time futures data for quadrant analysis."""

    symbol: str = ""
    exchange: str = ""
    price: float = 0.0
    oi: int = 0
    volume: int = 0


@dataclass
class QuadrantResult:
    """Result of futures quadrant classification."""

    symbol: str = ""
    exchange: str = ""
    quadrant: Quadrant = Quadrant.NEUTRAL
    price_current: float = 0.0
    price_prev: float = 0.0
    price_change: float = 0.0
    price_change_pct: float = 0.0
    oi_current: int = 0
    oi_prev: int = 0
    oi_change: int = 0
    oi_change_pct: float = 0.0

    @property
    def is_bullish(self) -> bool:
        return self.quadrant in (Quadrant.LONG_BUILDUP, Quadrant.SHORT_COVERING)

    @property
    def is_bearish(self) -> bool:
        return self.quadrant in (Quadrant.SHORT_BUILDUP, Quadrant.LONG_UNWINDING)


@dataclass
class BasisResult:
    """Futures basis (premium/discount) relative to spot."""

    symbol: str = ""
    spot_price: float = 0.0
    futures_price: float = 0.0
    basis: float = 0.0          # futures - spot
    basis_pct: float = 0.0      # (futures - spot) / spot * 100
    annualized_basis_pct: float = 0.0
    days_to_expiry: int = 0

    @property
    def is_premium(self) -> bool:
        return self.basis > 0

    @property
    def is_discount(self) -> bool:
        return self.basis < 0


@dataclass
class RolloverResult:
    """Series rollover tracking."""

    symbol: str = ""
    current_series_oi: int = 0
    next_series_oi: int = 0
    total_oi: int = 0
    rollover_pct: float = 0.0   # next_series_oi / total_oi * 100


def classify_quadrant(
    price_change: float,
    oi_change: int,
) -> Quadrant:
    """Classify into one of the 4 OI-Price quadrants."""
    if oi_change > 0 and price_change > 0:
        return Quadrant.LONG_BUILDUP
    if oi_change > 0 and price_change < 0:
        return Quadrant.SHORT_BUILDUP
    if oi_change < 0 and price_change > 0:
        return Quadrant.SHORT_COVERING
    if oi_change < 0 and price_change < 0:
        return Quadrant.LONG_UNWINDING
    return Quadrant.NEUTRAL


class FuturesQuadrant:
    """4-Quadrant Futures OI analysis with basis and rollover.

    Usage::

        fq = FuturesQuadrant()
        result = fq.classify(current_snapshot, prev_snapshot)
        basis = fq.basis(spot=24000, futures=24050, days_to_expiry=15)
        rollover = fq.rollover(current_oi=500000, next_oi=150000)
    """

    # ------------------------------------------------------------------
    # Quadrant classification
    # ------------------------------------------------------------------

    @staticmethod
    def classify(
        current: FuturesSnapshot,
        previous: FuturesSnapshot,
    ) -> QuadrantResult:
        """Classify futures OI + price movement into a quadrant."""
        price_change = current.price - previous.price
        oi_change = current.oi - previous.oi

        price_change_pct = (
            (price_change / previous.price * 100) if previous.price > 0 else 0.0
        )
        oi_change_pct = (
            (oi_change / previous.oi * 100) if previous.oi > 0 else 0.0
        )

        quadrant = classify_quadrant(price_change, oi_change)

        return QuadrantResult(
            symbol=current.symbol,
            exchange=current.exchange,
            quadrant=quadrant,
            price_current=current.price,
            price_prev=previous.price,
            price_change=price_change,
            price_change_pct=price_change_pct,
            oi_current=current.oi,
            oi_prev=previous.oi,
            oi_change=oi_change,
            oi_change_pct=oi_change_pct,
        )

    @staticmethod
    def classify_batch(
        current_list: list[FuturesSnapshot],
        previous_map: dict[str, FuturesSnapshot],
    ) -> list[QuadrantResult]:
        """Classify multiple futures at once.

        previous_map: keyed by "exchange:symbol", e.g. "NFO:NIFTY26MARFUT"
        """
        results: list[QuadrantResult] = []
        for curr in current_list:
            key = f"{curr.exchange}:{curr.symbol}"
            prev = previous_map.get(key)
            if prev:
                results.append(FuturesQuadrant.classify(curr, prev))
        return results

    # ------------------------------------------------------------------
    # Basis analysis
    # ------------------------------------------------------------------

    @staticmethod
    def basis(
        spot: float,
        futures: float,
        days_to_expiry: int = 0,
    ) -> BasisResult:
        """Calculate futures basis (premium/discount) vs spot.

        Annualized basis = (basis / spot) * (365 / days_to_expiry) * 100
        """
        b = futures - spot
        b_pct = (b / spot * 100) if spot > 0 else 0.0

        annualized = 0.0
        if spot > 0 and days_to_expiry > 0:
            annualized = (b / spot) * (365 / days_to_expiry) * 100

        return BasisResult(
            spot_price=spot,
            futures_price=futures,
            basis=b,
            basis_pct=b_pct,
            annualized_basis_pct=annualized,
            days_to_expiry=days_to_expiry,
        )

    # ------------------------------------------------------------------
    # Rollover tracking
    # ------------------------------------------------------------------

    @staticmethod
    def rollover(
        current_series_oi: int,
        next_series_oi: int,
        symbol: str = "",
    ) -> RolloverResult:
        """Calculate rollover percentage from current to next series.

        Rollover % = next_series_oi / (current + next) * 100
        High rollover → participants expect continuation.
        """
        total = current_series_oi + next_series_oi
        pct = (next_series_oi / total * 100) if total > 0 else 0.0

        return RolloverResult(
            symbol=symbol,
            current_series_oi=current_series_oi,
            next_series_oi=next_series_oi,
            total_oi=total,
            rollover_pct=pct,
        )
