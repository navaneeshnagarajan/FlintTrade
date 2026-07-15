"""Enhanced Open Interest analytics backend.

Provides heatmap generation, OI change interpretation (long build-up,
short covering, etc.), unusual OI activity detection, and multi-session
OI trend analysis.  Operates on :class:`OISnapshot` Pydantic models rather
than the dataclass-based :class:`OptionChainSnapshot` in ``oi_analysis.py``.

Use this module when the caller can supply per-strike OI and OI-change data
directly (e.g. from a stored snapshot or from a pre-processed option chain).
Use ``oi_analysis.py`` when working with live :class:`OptionChainSnapshot`
objects from the option chain fetcher.

Typical usage::

    from .oi_analytics import (
        OIAnalytics, OISnapshot,
    )

    analytics = OIAnalytics()
    snapshots = [OISnapshot(strike=24000, ce_oi=120000, pe_oi=95000, ...)]

    heatmap = analytics.oi_heatmap(snapshots)
    analysis = analytics.oi_change_analysis(snapshots)
    levels = analytics.support_resistance_from_oi(snapshots)
    unusual = analytics.unusual_oi_activity(snapshots)
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from pydantic import BaseModel, Field, computed_field

logger = logging.getLogger("flinttrade.screener.oi_analytics")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class OISnapshot(BaseModel):
    """Open Interest data for a single strike at a point in time.

    Attributes:
        strike:     Strike price.
        ce_oi:      Call open interest (contracts).
        pe_oi:      Put open interest (contracts).
        ce_change:  Change in call OI from the previous session.
        pe_change:  Change in put OI from the previous session.
        ce_volume:  Call trading volume for the session.
        pe_volume:  Put trading volume for the session.
        ce_ltp:     Call last traded price (optional, used for notional calc).
        pe_ltp:     Put last traded price (optional).
    """

    strike: float
    ce_oi: int = 0
    pe_oi: int = 0
    ce_change: int | None = None
    pe_change: int | None = None
    ce_volume: int = 0
    pe_volume: int = 0
    ce_ltp: float = 0.0
    pe_ltp: float = 0.0

    @computed_field  # type: ignore[misc]
    @property
    def pcr(self) -> float | None:
        """Per-strike Put-Call Ratio (OI-based).

        Returns:
            pe_oi / ce_oi, or ``None`` when call OI is zero.
        """
        return self.pe_oi / self.ce_oi if self.ce_oi > 0 else None

    @computed_field  # type: ignore[misc]
    @property
    def total_oi(self) -> int:
        """Total OI (CE + PE) at this strike."""
        return self.ce_oi + self.pe_oi


class OIHeatmapEntry(BaseModel):
    """Single row of heatmap data for one strike.

    Attributes:
        strike:        Strike price.
        ce_oi:         Call OI.
        pe_oi:         Put OI.
        ce_oi_pct:     CE OI as % of maximum CE OI across all strikes.
        pe_oi_pct:     PE OI as % of maximum PE OI across all strikes.
        ce_change:     CE OI change.
        pe_change:     PE OI change.
        pcr:           Per-strike PCR.
        is_atm:        True for the strike nearest to spot (if spot provided).
    """

    strike: float
    ce_oi: int
    pe_oi: int
    ce_oi_pct: float = Field(ge=0.0, le=100.0)
    pe_oi_pct: float = Field(ge=0.0, le=100.0)
    ce_change: int | None
    pe_change: int | None
    pcr: float | None
    is_atm: bool = False


class OIHeatmapData(BaseModel):
    """Full heatmap dataset for all strikes.

    Attributes:
        entries:          Per-strike heatmap rows.
        max_ce_oi_strike: Strike with highest call OI.
        max_pe_oi_strike: Strike with highest put OI.
        total_ce_oi:      Sum of all CE OI.
        total_pe_oi:      Sum of all PE OI.
        overall_pcr:      total_pe_oi / total_ce_oi.
    """

    entries: list[OIHeatmapEntry]
    max_ce_oi_strike: float | None
    max_pe_oi_strike: float | None
    total_ce_oi: int
    total_pe_oi: int
    overall_pcr: float | None


class OIChangeSignal(BaseModel):
    """OI change interpretation for a single strike.

    Attributes:
        strike:         Strike price.
        option_type:    "CE" or "PE".
        oi:             Current OI.
        oi_change:      OI change (positive = addition, negative = reduction).
        price_change:   Underlying price change context (up/down/flat).
        signal:         Interpretation label.
        signal_short:   Short code for colour-coding in the UI.
    """

    strike: float
    option_type: str
    oi:  int
    oi_change: int
    price_change: str  # "up", "down", "flat"
    signal: str
    signal_short: str  # "LB", "SC", "SB", "LU", "N"


_SIGNAL_MAP: dict[tuple[str, str], tuple[str, str]] = {
    # (price_direction, oi_direction): (long_label, short_code)
    ("up",   "up"):   ("Long Build-up",   "LB"),
    ("up",   "down"): ("Short Covering",  "SC"),
    ("down", "up"):   ("Short Build-up",  "SB"),
    ("down", "down"): ("Long Unwinding",  "LU"),
    ("flat", "up"):   ("OI Addition",     "OA"),
    ("flat", "down"): ("OI Reduction",    "OR"),
    ("up",   "flat"): ("Price Up, No OI", "N"),
    ("down", "flat"): ("Price Down, No OI", "N"),
    ("flat", "flat"): ("Neutral",         "N"),
}


def _classify_signal(price_change: str, oi_change: int) -> tuple[str, str]:
    """Map price direction and OI change to a trading signal.

    Args:
        price_change: "up", "down", or "flat".
        oi_change:    OI delta (positive, negative, or zero).

    Returns:
        Tuple of (signal_label, short_code).
    """
    oi_dir = "up" if oi_change > 0 else ("down" if oi_change < 0 else "flat")
    return _SIGNAL_MAP.get((price_change, oi_dir), ("Neutral", "N"))


class OIChangeAnalysis(BaseModel):
    """Full OI change analysis across all strikes.

    Attributes:
        signals:       Per-strike, per-option-type signal entries.
        long_buildups: Strikes showing long build-up.
        short_coverings: Strikes showing short covering.
        short_buildups:  Strikes showing short build-up.
        long_unwindings: Strikes showing long unwinding.
        summary:       Aggregate counts per signal type.
    """

    signals: list[OIChangeSignal]
    long_buildups: list[float]
    short_coverings: list[float]
    short_buildups: list[float]
    long_unwindings: list[float]
    summary: dict[str, int]


class UnusualOIEntry(BaseModel):
    """A strike/option-type combination with abnormal OI change.

    Attributes:
        strike:       Strike price.
        option_type:  "CE" or "PE".
        oi:           Current OI.
        oi_change:    OI change from previous session.
        change_pct:   OI change as a percentage of average absolute change.
        z_score:      Standard-deviations above/below average OI change.
        direction:    "addition" or "reduction".
    """

    strike: float
    option_type: str
    oi: int
    oi_change: int
    change_pct: float
    z_score: float
    direction: str


class SupportResistanceLevels(BaseModel):
    """Support and resistance levels derived from OI.

    Attributes:
        resistance_strike: Highest CE-OI strike (resistance).
        resistance_oi:     CE OI at resistance strike.
        support_strike:    Highest PE-OI strike (support).
        support_oi:        PE OI at support strike.
        secondary_resistance: Second-highest CE-OI strike.
        secondary_support:   Second-highest PE-OI strike.
    """

    resistance_strike: float | None
    resistance_oi: int | None
    support_strike: float | None
    support_oi: int | None
    secondary_resistance: float | None = None
    secondary_support: float | None = None


class OITrendEntry(BaseModel):
    """OI summary for one session in a multi-session trend.

    Attributes:
        session_idx:   Index (0 = oldest, n-1 = latest).
        total_ce_oi:   Sum of CE OI across all strikes.
        total_pe_oi:   Sum of PE OI across all strikes.
        overall_pcr:   Total PE OI / Total CE OI.
    """

    session_idx: int
    total_ce_oi: int
    total_pe_oi: int
    overall_pcr: float | None


# ---------------------------------------------------------------------------
# OIAnalytics
# ---------------------------------------------------------------------------


class OIAnalytics:
    """Enhanced Open Interest analytics operating on :class:`OISnapshot` lists.

    All methods are pure functions (no state, no I/O).  The caller is
    responsible for supplying snapshot data from the option chain or a cache.
    """

    # ------------------------------------------------------------------
    # OI Heatmap
    # ------------------------------------------------------------------

    def oi_heatmap(
        self,
        chain: list[OISnapshot],
        n_strikes: int = 20,
        spot: float | None = None,
    ) -> OIHeatmapData:
        """Generate heatmap data for OI across strikes.

        Selects the ``n_strikes`` strikes nearest to spot (or the most active
        if spot is not supplied), normalises OI values to a 0-100% scale, and
        flags the ATM strike.

        Args:
            chain:     List of :class:`OISnapshot` for all available strikes.
            n_strikes: Number of strikes to include in the heatmap (default 20).
            spot:      Current spot/futures price for ATM identification.

        Returns:
            :class:`OIHeatmapData` ready for the frontend heatmap widget.
        """
        if not chain:
            return OIHeatmapData(
                entries=[],
                max_ce_oi_strike=None,
                max_pe_oi_strike=None,
                total_ce_oi=0,
                total_pe_oi=0,
                overall_pcr=None,
            )

        # Select n_strikes centred around spot if given, else top by total OI
        if spot is not None and spot > 0:
            sorted_by_dist = sorted(chain, key=lambda s: abs(s.strike - spot))
            selected = sorted_by_dist[:n_strikes]
        else:
            sorted_by_oi = sorted(chain, key=lambda s: s.total_oi, reverse=True)
            selected = sorted_by_oi[:n_strikes]

        # Sort selected by strike ascending for display
        selected.sort(key=lambda s: s.strike)

        max_ce = max((s.ce_oi for s in selected), default=1) or 1
        max_pe = max((s.pe_oi for s in selected), default=1) or 1

        # ATM strike = closest to spot
        atm_strike: float | None = None
        if spot is not None and spot > 0 and selected:
            atm_strike = min(selected, key=lambda s: abs(s.strike - spot)).strike

        entries: list[OIHeatmapEntry] = []
        for s in selected:
            entries.append(OIHeatmapEntry(
                strike=s.strike,
                ce_oi=s.ce_oi,
                pe_oi=s.pe_oi,
                ce_oi_pct=round(s.ce_oi / max_ce * 100.0, 2),
                pe_oi_pct=round(s.pe_oi / max_pe * 100.0, 2),
                ce_change=s.ce_change,
                pe_change=s.pe_change,
                pcr=round(s.pcr, 4) if s.pcr is not None else None,
                is_atm=(atm_strike is not None and s.strike == atm_strike),
            ))

        total_ce = sum(s.ce_oi for s in chain)
        total_pe = sum(s.pe_oi for s in chain)
        max_ce_strike = max(chain, key=lambda s: s.ce_oi).strike if total_ce > 0 else None
        max_pe_strike = max(chain, key=lambda s: s.pe_oi).strike if total_pe > 0 else None

        return OIHeatmapData(
            entries=entries,
            max_ce_oi_strike=max_ce_strike,
            max_pe_oi_strike=max_pe_strike,
            total_ce_oi=total_ce,
            total_pe_oi=total_pe,
            overall_pcr=round(total_pe / total_ce, 4) if total_ce > 0 else None,
        )

    # ------------------------------------------------------------------
    # OI Change Analysis
    # ------------------------------------------------------------------

    def oi_change_analysis(
        self,
        chain: list[OISnapshot],
        price_change: str = "flat",
    ) -> OIChangeAnalysis:
        """Analyse OI changes across strikes and classify each position.

        Interpretation logic:
        - Price up + OI up   → Long Build-up    (bullish)
        - Price up + OI down → Short Covering   (weakly bullish)
        - Price down + OI up → Short Build-up   (bearish)
        - Price down + OI down → Long Unwinding (weakly bearish)

        The ``price_change`` argument represents the direction of the
        underlying's move since the previous session.  Use "up", "down",
        or "flat".

        Args:
            chain:        List of :class:`OISnapshot` with ce_change / pe_change
                          populated from the previous session.
            price_change: Underlying price movement direction: "up", "down",
                          or "flat" (default "flat").

        Returns:
            :class:`OIChangeAnalysis` with per-strike signals and summary.
        """
        signals: list[OIChangeSignal] = []
        long_buildups: list[float] = []
        short_coverings: list[float] = []
        short_buildups: list[float] = []
        long_unwindings: list[float] = []
        summary: dict[str, int] = {}

        for s in chain:
            for opt_type, oi_change in (("CE", s.ce_change), ("PE", s.pe_change)):
                if oi_change is None:
                    continue
                label, code = _classify_signal(price_change, oi_change)
                signals.append(OIChangeSignal(
                    strike=s.strike,
                    option_type=opt_type,
                    oi=s.ce_oi if opt_type == "CE" else s.pe_oi,
                    oi_change=oi_change,
                    price_change=price_change,
                    signal=label,
                    signal_short=code,
                ))
                summary[label] = summary.get(label, 0) + 1

                # Populate convenience lists (CE signals drive the price interpretation)
                if opt_type == "CE":
                    if code == "LB":
                        long_buildups.append(s.strike)
                    elif code == "SC":
                        short_coverings.append(s.strike)
                    elif code == "SB":
                        short_buildups.append(s.strike)
                    elif code == "LU":
                        long_unwindings.append(s.strike)

        return OIChangeAnalysis(
            signals=signals,
            long_buildups=sorted(long_buildups),
            short_coverings=sorted(short_coverings),
            short_buildups=sorted(short_buildups),
            long_unwindings=sorted(long_unwindings),
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Support / Resistance from OI
    # ------------------------------------------------------------------

    def support_resistance_from_oi(
        self,
        chain: list[OISnapshot],
    ) -> SupportResistanceLevels:
        """Identify support and resistance levels from max OI strikes.

        Highest CE OI strike → resistance (call writers expect price cap).
        Highest PE OI strike → support (put writers expect price floor).

        Args:
            chain: List of :class:`OISnapshot`.

        Returns:
            :class:`SupportResistanceLevels` with primary and secondary levels.
        """
        if not chain:
            return SupportResistanceLevels(
                resistance_strike=None,
                resistance_oi=None,
                support_strike=None,
                support_oi=None,
            )

        ce_sorted = sorted((snapshot for snapshot in chain if snapshot.ce_oi > 0), key=lambda s: s.ce_oi, reverse=True)
        pe_sorted = sorted((snapshot for snapshot in chain if snapshot.pe_oi > 0), key=lambda s: s.pe_oi, reverse=True)

        return SupportResistanceLevels(
            resistance_strike=ce_sorted[0].strike if ce_sorted else None,
            resistance_oi=ce_sorted[0].ce_oi if ce_sorted else None,
            support_strike=pe_sorted[0].strike if pe_sorted else None,
            support_oi=pe_sorted[0].pe_oi if pe_sorted else None,
            secondary_resistance=ce_sorted[1].strike if len(ce_sorted) > 1 else None,
            secondary_support=pe_sorted[1].strike if len(pe_sorted) > 1 else None,
        )

    # ------------------------------------------------------------------
    # Unusual OI Activity
    # ------------------------------------------------------------------

    def unusual_oi_activity(
        self,
        chain: list[OISnapshot],
        threshold: float = 2.0,
    ) -> list[UnusualOIEntry]:
        """Detect unusual OI changes using z-score analysis.

        A strike/option-type combination is flagged as unusual when its OI
        change z-score exceeds ``threshold`` (default 2.0 σ) above the mean
        absolute OI change across all strikes.

        Args:
            chain:     List of :class:`OISnapshot` with ce_change / pe_change set.
            threshold: Z-score threshold for flagging (default 2.0).

        Returns:
            List of :class:`UnusualOIEntry` sorted by |z_score| descending.
        """
        if not chain:
            return []

        # Collect all OI changes
        all_changes: list[tuple[float, str, int, int]] = []
        for s in chain:
            if s.ce_change not in (None, 0):
                all_changes.append((s.strike, "CE", s.ce_oi, s.ce_change))
            if s.pe_change not in (None, 0):
                all_changes.append((s.strike, "PE", s.pe_oi, s.pe_change))

        if not all_changes:
            return []

        change_values = np.array([abs(c[3]) for c in all_changes], dtype=float)
        mean_change = float(np.mean(change_values))
        std_change = float(np.std(change_values, ddof=1)) if len(change_values) > 1 else 0.0

        unusual: list[UnusualOIEntry] = []
        for strike, opt_type, oi, oi_change in all_changes:
            if std_change == 0:
                z = 0.0
            else:
                z = (abs(oi_change) - mean_change) / std_change

            if z < threshold:
                continue

            pct = (abs(oi_change) / mean_change * 100.0) if mean_change > 0 else 0.0
            unusual.append(UnusualOIEntry(
                strike=strike,
                option_type=opt_type,
                oi=oi,
                oi_change=oi_change,
                change_pct=round(pct, 2),
                z_score=round(z, 4),
                direction="addition" if oi_change > 0 else "reduction",
            ))

        unusual.sort(key=lambda e: abs(e.z_score), reverse=True)
        return unusual

    # ------------------------------------------------------------------
    # Multi-session OI Trend
    # ------------------------------------------------------------------

    def oi_trend(
        self,
        history: list[list[OISnapshot]],
        n_sessions: int = 5,
    ) -> dict[str, Any]:
        """Analyse OI trend across multiple sessions.

        Args:
            history:    List of :class:`OISnapshot` lists, one per session,
                        ordered oldest-to-newest.
            n_sessions: How many recent sessions to include (default 5).

        Returns:
            Dict with keys:
            - ``sessions`` (list[OITrendEntry]): Per-session totals.
            - ``ce_trend``  ("up" | "down" | "flat"): Direction of CE OI.
            - ``pe_trend``  ("up" | "down" | "flat"): Direction of PE OI.
            - ``pcr_trend`` ("up" | "down" | "flat"): Direction of PCR.
        """
        if not history:
            return {"sessions": [], "ce_trend": "flat", "pe_trend": "flat", "pcr_trend": "flat"}

        recent = history[-n_sessions:]
        sessions: list[OITrendEntry] = []
        for idx, snap_list in enumerate(recent):
            total_ce = sum(s.ce_oi for s in snap_list)
            total_pe = sum(s.pe_oi for s in snap_list)
            pcr = total_pe / total_ce if total_ce > 0 else None
            sessions.append(OITrendEntry(
                session_idx=idx,
                total_ce_oi=total_ce,
                total_pe_oi=total_pe,
                overall_pcr=round(pcr, 4) if pcr is not None else None,
            ))

        def _trend(observations: list[tuple[int, float]]) -> str:
            if len(observations) < 2:
                return "flat"
            x = np.array([idx for idx, _value in observations], dtype=float)
            arr = np.array([value for _idx, value in observations], dtype=float)
            # Simple linear regression slope sign
            slope = float(np.polyfit(x, arr, 1)[0])
            if slope > 0:
                return "up"
            if slope < 0:
                return "down"
            return "flat"

        ce_values = [(s.session_idx, float(s.total_ce_oi)) for s in sessions]
        pe_values = [(s.session_idx, float(s.total_pe_oi)) for s in sessions]
        pcr_values = [
            (s.session_idx, s.overall_pcr)
            for s in sessions
            if s.overall_pcr is not None
        ]

        return {
            "sessions": [s.model_dump() for s in sessions],
            "ce_trend": _trend(ce_values),
            "pe_trend": _trend(pe_values),
            "pcr_trend": _trend(pcr_values),
        }
