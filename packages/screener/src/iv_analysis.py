"""Implied Volatility analysis — skew, smile, percentile, term structure.

All functions operate on option chain data. No direct API calls — the
option_chain module handles fetching.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .option_chain import OptionChainSnapshot, StrikeData

logger = logging.getLogger("flinttrade.screener.iv_analysis")


@dataclass
class IVSkewPoint:
    """Single point in an IV skew chart."""

    strike_price: float = 0.0
    ce_iv: float = 0.0
    pe_iv: float = 0.0
    moneyness: float = 0.0  # strike / spot — <1 ITM calls, >1 OTM calls


@dataclass
class IVSkewResult:
    """IV across strikes for a given expiry (skew/smile)."""

    underlying: str = ""
    spot_price: float = 0.0
    atm_iv: float = 0.0
    points: list[IVSkewPoint] = field(default_factory=list)

    @property
    def skew_slope(self) -> float:
        """Approximate skew slope: IV difference between OTM puts and OTM calls.

        Positive = put skew (typical equity markets).
        """
        if len(self.points) < 3:
            return 0.0
        sorted_pts = sorted(self.points, key=lambda p: p.strike_price)
        lowest = sorted_pts[0]
        highest = sorted_pts[-1]
        return lowest.pe_iv - highest.ce_iv


@dataclass
class IVPercentileResult:
    """IV percentile — where current IV sits in historical range."""

    current_iv: float = 0.0
    iv_history: list[float] = field(default_factory=list)
    percentile: float = 0.0     # 0-100
    iv_rank: float = 0.0        # (current - min) / (max - min) * 100
    iv_min: float = 0.0
    iv_max: float = 0.0
    iv_mean: float = 0.0

    @property
    def is_high(self) -> bool:
        """IV > 80th percentile."""
        return self.percentile > 80

    @property
    def is_low(self) -> bool:
        """IV < 20th percentile."""
        return self.percentile < 20


@dataclass
class IVTermPoint:
    """Single point in IV term structure."""

    expiry: str = ""
    days_to_expiry: int = 0
    atm_ce_iv: float = 0.0
    atm_pe_iv: float = 0.0
    avg_iv: float = 0.0


@dataclass
class IVTermStructure:
    """IV across expiries for ATM strike (term structure)."""

    underlying: str = ""
    points: list[IVTermPoint] = field(default_factory=list)

    @property
    def is_contango(self) -> bool:
        """Near-term IV < far-term IV (normal term structure)."""
        if len(self.points) < 2:
            return False
        return self.points[0].avg_iv < self.points[-1].avg_iv

    @property
    def is_backwardation(self) -> bool:
        """Near-term IV > far-term IV (inverted — event expected)."""
        if len(self.points) < 2:
            return False
        return self.points[0].avg_iv > self.points[-1].avg_iv


class IVAnalysis:
    """Implied Volatility analysis on option chain data.

    Usage::

        iv = IVAnalysis()
        skew = iv.skew(snapshot)
        percentile = iv.iv_percentile(current_iv=18.5, history=[12, 14, 16, 18, 20, 22, 25])
    """

    # ------------------------------------------------------------------
    # IV Skew / Smile
    # ------------------------------------------------------------------

    @staticmethod
    def skew(
        snapshot: OptionChainSnapshot,
        num_strikes: int = 10,
    ) -> IVSkewResult:
        """Build IV skew data across strikes near ATM.

        Returns IV for each strike along with moneyness.
        """
        near = snapshot.strikes_near_atm(num_strikes)
        spot = snapshot.spot_price

        points: list[IVSkewPoint] = []
        atm_iv = 0.0

        for s in near:
            moneyness = s.strike_price / spot if spot > 0 else 0.0
            points.append(IVSkewPoint(
                strike_price=s.strike_price,
                ce_iv=s.ce_iv,
                pe_iv=s.pe_iv,
                moneyness=moneyness,
            ))
            # ATM IV = average of ATM CE and PE IV
            if s.strike_price == snapshot.atm_strike:
                atm_iv = (s.ce_iv + s.pe_iv) / 2 if (s.ce_iv + s.pe_iv) > 0 else 0.0

        return IVSkewResult(
            underlying=snapshot.underlying,
            spot_price=spot,
            atm_iv=atm_iv,
            points=sorted(points, key=lambda p: p.strike_price),
        )

    # ------------------------------------------------------------------
    # IV Percentile / Rank
    # ------------------------------------------------------------------

    @staticmethod
    def iv_percentile(
        current_iv: float,
        history: list[float],
    ) -> IVPercentileResult:
        """Calculate IV percentile and IV rank.

        IV Percentile = % of historical readings below current IV.
        IV Rank = (current - min) / (max - min) * 100.
        """
        if not history:
            return IVPercentileResult(current_iv=current_iv)

        sorted_hist = sorted(history)
        count_below = sum(1 for v in sorted_hist if v < current_iv)
        percentile = (count_below / len(sorted_hist)) * 100

        iv_min = sorted_hist[0]
        iv_max = sorted_hist[-1]
        iv_range = iv_max - iv_min
        iv_rank = ((current_iv - iv_min) / iv_range * 100) if iv_range > 0 else 50.0
        iv_mean = sum(history) / len(history)

        return IVPercentileResult(
            current_iv=current_iv,
            iv_history=history,
            percentile=percentile,
            iv_rank=iv_rank,
            iv_min=iv_min,
            iv_max=iv_max,
            iv_mean=iv_mean,
        )

    # ------------------------------------------------------------------
    # IV Term Structure
    # ------------------------------------------------------------------

    @staticmethod
    def term_structure(
        snapshots: list[tuple[str, int, OptionChainSnapshot]],
    ) -> IVTermStructure:
        """Build IV term structure from multiple expiry snapshots.

        Each tuple: (expiry_label, days_to_expiry, snapshot)
        """
        if not snapshots:
            return IVTermStructure()

        underlying = snapshots[0][2].underlying
        points: list[IVTermPoint] = []

        for expiry, dte, snap in snapshots:
            atm = snap.get_strike(snap.atm_strike)
            if atm:
                ce_iv = atm.ce_iv
                pe_iv = atm.pe_iv
                avg = (ce_iv + pe_iv) / 2 if (ce_iv + pe_iv) > 0 else 0.0
            else:
                ce_iv = pe_iv = avg = 0.0

            points.append(IVTermPoint(
                expiry=expiry,
                days_to_expiry=dte,
                atm_ce_iv=ce_iv,
                atm_pe_iv=pe_iv,
                avg_iv=avg,
            ))

        return IVTermStructure(
            underlying=underlying,
            points=sorted(points, key=lambda p: p.days_to_expiry),
        )

    # ------------------------------------------------------------------
    # ATM IV shortcut
    # ------------------------------------------------------------------

    @staticmethod
    def atm_iv(snapshot: OptionChainSnapshot) -> float:
        """Get ATM IV as average of ATM CE and PE IV."""
        atm = snapshot.get_strike(snapshot.atm_strike)
        if atm and (atm.ce_iv + atm.pe_iv) > 0:
            return (atm.ce_iv + atm.pe_iv) / 2
        return 0.0
