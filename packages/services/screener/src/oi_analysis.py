"""Open Interest analysis — PCR, Max Pain, OI change, support/resistance, OI spurt.

All functions operate on OptionChainSnapshot from option_chain.py — no direct
API calls. The option_chain module handles fetching.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .option_chain import OptionChainSnapshot, StrikeData

logger = logging.getLogger("flinttrade.screener.oi_analysis")


@dataclass
class PCRResult:
    """Put-Call Ratio result."""

    pcr_oi: float = 0.0         # Total Put OI / Total Call OI
    pcr_volume: float = 0.0     # Total Put Volume / Total Call Volume
    total_ce_oi: int = 0
    total_pe_oi: int = 0
    total_ce_volume: int = 0
    total_pe_volume: int = 0

    @property
    def sentiment(self) -> str:
        """Market sentiment based on PCR OI.

        PCR > 1.0 → Bullish (more puts = hedging/support)
        PCR < 0.7 → Bearish (more calls = resistance)
        0.7-1.0   → Neutral
        """
        if self.pcr_oi > 1.0:
            return "BULLISH"
        if self.pcr_oi < 0.7:
            return "BEARISH"
        return "NEUTRAL"


@dataclass
class MaxPainResult:
    """Max Pain calculation result."""

    max_pain_strike: float = 0.0
    total_loss_at_max_pain: float = 0.0
    # Loss at each strike for visualisation
    strike_losses: list[dict[str, float]] = field(default_factory=list)


@dataclass
class OIChangeEntry:
    """OI change for a single strike."""

    strike_price: float = 0.0
    ce_oi: int = 0
    ce_oi_prev: int = 0
    ce_oi_change: int = 0
    pe_oi: int = 0
    pe_oi_prev: int = 0
    pe_oi_change: int = 0

    @property
    def ce_writing(self) -> bool:
        """Fresh call writing (OI increase)."""
        return self.ce_oi_change > 0

    @property
    def pe_writing(self) -> bool:
        """Fresh put writing (OI increase)."""
        return self.pe_oi_change > 0

    @property
    def ce_unwinding(self) -> bool:
        """Call unwinding (OI decrease)."""
        return self.ce_oi_change < 0

    @property
    def pe_unwinding(self) -> bool:
        """Put unwinding (OI decrease)."""
        return self.pe_oi_change < 0


@dataclass
class SupportResistance:
    """Support and resistance levels derived from OI."""

    resistance_strike: float = 0.0  # Highest call OI
    resistance_oi: int = 0
    support_strike: float = 0.0     # Highest put OI
    support_oi: int = 0


@dataclass
class OISpurtEntry:
    """Strike with abnormal OI change."""

    strike_price: float
    option_type: str  # "CE" or "PE"
    oi: int
    oi_change: int
    change_pct: float


class OIAnalysis:
    """Open Interest analysis on an OptionChainSnapshot.

    Usage::

        oi = OIAnalysis()
        pcr = oi.pcr(snapshot)
        max_pain = oi.max_pain(snapshot)
        sr = oi.support_resistance(snapshot)
    """

    # ------------------------------------------------------------------
    # PCR
    # ------------------------------------------------------------------

    @staticmethod
    def pcr(snapshot: OptionChainSnapshot) -> PCRResult:
        """Calculate Put-Call Ratio from the option chain."""
        total_ce_oi = snapshot.total_ce_oi
        total_pe_oi = snapshot.total_pe_oi
        total_ce_vol = snapshot.total_ce_volume
        total_pe_vol = snapshot.total_pe_volume

        pcr_oi = total_pe_oi / total_ce_oi if total_ce_oi > 0 else 0.0
        pcr_vol = total_pe_vol / total_ce_vol if total_ce_vol > 0 else 0.0

        return PCRResult(
            pcr_oi=pcr_oi,
            pcr_volume=pcr_vol,
            total_ce_oi=total_ce_oi,
            total_pe_oi=total_pe_oi,
            total_ce_volume=total_ce_vol,
            total_pe_volume=total_pe_vol,
        )

    # ------------------------------------------------------------------
    # Max Pain
    # ------------------------------------------------------------------

    @staticmethod
    def max_pain(snapshot: OptionChainSnapshot) -> MaxPainResult:
        """Calculate the Max Pain strike.

        Max Pain = strike where total loss for all option buyers is maximum.
        At each hypothetical expiry price (each strike):
        - CE buyer loss = max(0, strike - expiry) * OI for all CE strikes
        - PE buyer loss = max(0, expiry - strike) * OI for all PE strikes
        The strike with the MINIMUM total loss for writers (= max loss for buyers)
        is the max pain point. Convention: the strike where total intrinsic
        value payout by writers is minimized.
        """
        strikes = snapshot.strikes
        if not strikes:
            return MaxPainResult()

        strike_losses: list[dict[str, float]] = []
        min_loss = float("inf")
        max_pain_strike = 0.0

        for candidate in strikes:
            expiry_price = candidate.strike_price
            total_loss = 0.0

            for s in strikes:
                # Call buyer intrinsic at expiry
                ce_intrinsic = max(0, expiry_price - s.strike_price)
                total_loss += ce_intrinsic * s.ce_oi

                # Put buyer intrinsic at expiry
                pe_intrinsic = max(0, s.strike_price - expiry_price)
                total_loss += pe_intrinsic * s.pe_oi

            strike_losses.append({
                "strike": candidate.strike_price,
                "total_loss": total_loss,
            })

            if total_loss < min_loss:
                min_loss = total_loss
                max_pain_strike = candidate.strike_price

        return MaxPainResult(
            max_pain_strike=max_pain_strike,
            total_loss_at_max_pain=min_loss,
            strike_losses=strike_losses,
        )

    # ------------------------------------------------------------------
    # OI Change
    # ------------------------------------------------------------------

    @staticmethod
    def oi_change(
        current: OptionChainSnapshot,
        previous: OptionChainSnapshot,
    ) -> list[OIChangeEntry]:
        """Compare two snapshots to find OI changes per strike."""
        prev_map: dict[float, StrikeData] = {
            s.strike_price: s for s in previous.strikes
        }
        changes: list[OIChangeEntry] = []

        for s in current.strikes:
            prev = prev_map.get(s.strike_price)
            prev_ce_oi = prev.ce_oi if prev else 0
            prev_pe_oi = prev.pe_oi if prev else 0

            changes.append(OIChangeEntry(
                strike_price=s.strike_price,
                ce_oi=s.ce_oi,
                ce_oi_prev=prev_ce_oi,
                ce_oi_change=s.ce_oi - prev_ce_oi,
                pe_oi=s.pe_oi,
                pe_oi_prev=prev_pe_oi,
                pe_oi_change=s.pe_oi - prev_pe_oi,
            ))

        return changes

    # ------------------------------------------------------------------
    # Support / Resistance from OI
    # ------------------------------------------------------------------

    @staticmethod
    def support_resistance(snapshot: OptionChainSnapshot) -> SupportResistance:
        """Derive support and resistance from OI.

        Highest Call OI strike → Resistance (writers expect price won't go above)
        Highest Put OI strike → Support (writers expect price won't go below)
        """
        if not snapshot.strikes:
            return SupportResistance()

        max_ce = max(snapshot.strikes, key=lambda s: s.ce_oi)
        max_pe = max(snapshot.strikes, key=lambda s: s.pe_oi)

        return SupportResistance(
            resistance_strike=max_ce.strike_price,
            resistance_oi=max_ce.ce_oi,
            support_strike=max_pe.strike_price,
            support_oi=max_pe.pe_oi,
        )

    # ------------------------------------------------------------------
    # OI Spurt Detection
    # ------------------------------------------------------------------

    @staticmethod
    def oi_spurt(
        current: OptionChainSnapshot,
        previous: OptionChainSnapshot,
        threshold_pct: float = 20.0,
    ) -> list[OISpurtEntry]:
        """Detect strikes with OI change above a threshold percentage.

        Args:
            threshold_pct: minimum OI change % to flag (default 20%).
        """
        prev_map = {s.strike_price: s for s in previous.strikes}
        spurts: list[OISpurtEntry] = []

        for s in current.strikes:
            prev = prev_map.get(s.strike_price)
            if not prev:
                continue

            # CE OI spurt
            if prev.ce_oi > 0:
                ce_change = s.ce_oi - prev.ce_oi
                ce_pct = (ce_change / prev.ce_oi) * 100
                if abs(ce_pct) >= threshold_pct:
                    spurts.append(OISpurtEntry(
                        strike_price=s.strike_price,
                        option_type="CE",
                        oi=s.ce_oi,
                        oi_change=ce_change,
                        change_pct=ce_pct,
                    ))

            # PE OI spurt
            if prev.pe_oi > 0:
                pe_change = s.pe_oi - prev.pe_oi
                pe_pct = (pe_change / prev.pe_oi) * 100
                if abs(pe_pct) >= threshold_pct:
                    spurts.append(OISpurtEntry(
                        strike_price=s.strike_price,
                        option_type="PE",
                        oi=s.pe_oi,
                        oi_change=pe_change,
                        change_pct=pe_pct,
                    ))

        return sorted(spurts, key=lambda x: abs(x.change_pct), reverse=True)

    # ------------------------------------------------------------------
    # Multi-strike comparison
    # ------------------------------------------------------------------

    @staticmethod
    def top_oi_strikes(
        snapshot: OptionChainSnapshot,
        n: int = 5,
    ) -> dict[str, list[StrikeData]]:
        """Get top N strikes by OI for both CE and PE."""
        sorted_ce = sorted(snapshot.strikes, key=lambda s: s.ce_oi, reverse=True)
        sorted_pe = sorted(snapshot.strikes, key=lambda s: s.pe_oi, reverse=True)
        return {
            "top_ce_oi": sorted_ce[:n],
            "top_pe_oi": sorted_pe[:n],
        }
