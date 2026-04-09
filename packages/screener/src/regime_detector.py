"""Market regime detector.

Classifies the current market environment into one of seven regimes using a
weighted-voting approach across multiple macro signals:

Signals used:
- VIX level and percentile
- Nifty 20-day return
- Advance/Decline ratio
- FII net flow
- Market breadth (% stocks above 200 DMA)

Regime classification logic:
- VIX < 13 → calm
- VIX 13–20 → normal
- VIX > 20 → volatile; VIX > 30 → risk_off (strong)
- Nifty 20-day return > +5% → trending_up
- Nifty 20-day return < -5% → trending_down
- A/D ratio > 2.0 → risk_on breadth signal
- A/D ratio < 0.5 → risk_off breadth signal
- FII net > 0 + breadth > 1.0 → risk_on confirmation
- FII net < 0 + VIX > 20 → risk_off confirmation
- Conflicting signals → rotation

The final regime is determined by majority-weighted vote across active signals.
"""

from __future__ import annotations

import logging
from enum import StrEnum

from pydantic import BaseModel, Field

logger = logging.getLogger("flinttrade.screener.regime_detector")

# ---------------------------------------------------------------------------
# Enums and constants
# ---------------------------------------------------------------------------

class RegimeType(StrEnum):
    """Market regime classifications."""

    RISK_ON = "risk_on"
    RISK_OFF = "risk_off"
    ROTATION = "rotation"
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    VOLATILE = "volatile"
    CALM = "calm"


# Vote weights for each signal type.  Higher weight = stronger signal.
_VIX_WEIGHT: float = 3.0
_RETURN_WEIGHT: float = 2.5
_AD_WEIGHT: float = 1.5
_FII_WEIGHT: float = 1.5
_BREADTH_WEIGHT: float = 1.0

# VIX thresholds
_VIX_CALM: float = 13.0
_VIX_NORMAL_HI: float = 20.0
_VIX_RISK_OFF: float = 30.0

# Return thresholds (20-day cumulative)
_RETURN_UP: float = 0.05    # +5%
_RETURN_DOWN: float = -0.05  # -5%

# Advance/Decline thresholds
_AD_BULL: float = 2.0
_AD_BEAR: float = 0.5

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class RegimeSignal(BaseModel):
    """Current market regime signal with supporting data.

    Attributes:
        regime: Detected regime type.
        confidence: Confidence score in [0, 1].
        vix_level: Raw VIX value.
        vix_percentile: VIX percentile vs recent history (0–100).
        dxy_level: DXY (US Dollar Index) level, if available.
        advance_decline_ratio: NSE advance/decline ratio.
        fii_dii_net: Net FII flow (positive = buying).
        breadth: Fraction of stocks above 200 DMA (0–100%).
        rationale: Human-readable explanation of the detected regime.
    """

    regime: RegimeType
    confidence: float = Field(ge=0.0, le=1.0)
    vix_level: float
    vix_percentile: float = Field(ge=0.0, le=100.0)
    dxy_level: float | None = None
    advance_decline_ratio: float | None = None
    fii_dii_net: float | None = None
    breadth: float | None = None
    rationale: str


# ---------------------------------------------------------------------------
# Regime Detector
# ---------------------------------------------------------------------------

class RegimeDetector:
    """Detect current market regime from multiple macro signals.

    Usage::

        detector = RegimeDetector()
        signal = detector.detect(
            vix=14.5,
            nifty_returns=[0.003, -0.001, 0.005, ...],  # 20 daily returns
            advance_decline=(1400, 600),
            fii_net=2_500.0,
        )
        print(signal.regime)       # RegimeType.RISK_ON
        print(signal.confidence)   # 0.78
        print(signal.rationale)
    """

    def detect(
        self,
        vix: float,
        nifty_returns: list[float],
        advance_decline: tuple[int, int] | None = None,
        fii_net: float | None = None,
        breadth: float | None = None,
        vix_history: list[float] | None = None,
        dxy_level: float | None = None,
    ) -> RegimeSignal:
        """Detect current market regime from multiple signals.

        Args:
            vix: Current VIX level (e.g. 14.5).
            nifty_returns: List of daily Nifty returns (recent 20 preferred).
                Values as decimals (0.01 = 1% daily return).
            advance_decline: Optional (advances, declines) count tuple.
            fii_net: Optional net FII flow in crores. Positive = buying.
            breadth: Optional percentage of stocks above 200 DMA (0–100).
            vix_history: Optional list of past VIX values for percentile calc.
            dxy_level: Optional US Dollar Index level.

        Returns:
            RegimeSignal with regime type, confidence, and rationale.
        """
        # ------------------------------------------------------------------ #
        # Step 1: Derive individual signal scores                             #
        # ------------------------------------------------------------------ #
        votes: dict[RegimeType, float] = {}

        def _add_vote(regime: RegimeType, weight: float) -> None:
            votes[regime] = votes.get(regime, 0.0) + weight

        # VIX signal
        if vix < _VIX_CALM:
            _add_vote(RegimeType.CALM, _VIX_WEIGHT)
        elif vix <= _VIX_NORMAL_HI:
            pass  # neutral — no strong vote
        elif vix <= _VIX_RISK_OFF:
            _add_vote(RegimeType.VOLATILE, _VIX_WEIGHT)
        else:
            _add_vote(RegimeType.RISK_OFF, _VIX_WEIGHT * 1.5)  # extra weight > 30

        # 20-day return signal
        cum_return = _cumulative_return(nifty_returns)
        if cum_return > _RETURN_UP:
            _add_vote(RegimeType.TRENDING_UP, _RETURN_WEIGHT)
            _add_vote(RegimeType.RISK_ON, _RETURN_WEIGHT * 0.5)
        elif cum_return < _RETURN_DOWN:
            _add_vote(RegimeType.TRENDING_DOWN, _RETURN_WEIGHT)
            _add_vote(RegimeType.RISK_OFF, _RETURN_WEIGHT * 0.5)

        # Advance/Decline signal
        ad_ratio: float | None = None
        if advance_decline is not None:
            advances, declines = advance_decline
            if declines > 0:
                ad_ratio = advances / declines
            elif advances > 0:
                ad_ratio = float(advances)  # treat as very high ratio

            if ad_ratio is not None:
                if ad_ratio > _AD_BULL:
                    _add_vote(RegimeType.RISK_ON, _AD_WEIGHT)
                elif ad_ratio < _AD_BEAR:
                    _add_vote(RegimeType.RISK_OFF, _AD_WEIGHT)
                else:
                    _add_vote(RegimeType.ROTATION, _AD_WEIGHT * 0.3)

        # FII net flow signal
        if fii_net is not None:
            if fii_net > 0:
                fii_vote_weight = _FII_WEIGHT * min(1.0, abs(fii_net) / 5000.0)
                _add_vote(RegimeType.RISK_ON, max(0.2, fii_vote_weight))
            elif fii_net < 0:
                fii_vote_weight = _FII_WEIGHT * min(1.0, abs(fii_net) / 5000.0)
                _add_vote(RegimeType.RISK_OFF, max(0.2, fii_vote_weight))

        # Breadth signal
        if breadth is not None:
            if breadth > 60.0:
                _add_vote(RegimeType.RISK_ON, _BREADTH_WEIGHT)
            elif breadth < 40.0:
                _add_vote(RegimeType.RISK_OFF, _BREADTH_WEIGHT)

        # Composite: FII buying + strong breadth → confirm risk_on
        if fii_net is not None and breadth is not None:
            if fii_net > 0 and breadth > 50.0:
                _add_vote(RegimeType.RISK_ON, 0.5)
            elif fii_net < 0 and vix > _VIX_NORMAL_HI:
                _add_vote(RegimeType.RISK_OFF, 0.8)

        # ------------------------------------------------------------------ #
        # Step 2: Resolve winner                                              #
        # ------------------------------------------------------------------ #
        if not votes:
            # No data → rotation (uncertain)
            winner = RegimeType.ROTATION
            confidence = 0.3
        else:
            total_weight = sum(votes.values())
            winner = max(votes, key=lambda r: votes[r])
            confidence = min(1.0, votes[winner] / total_weight) if total_weight > 0 else 0.3

        # ------------------------------------------------------------------ #
        # Step 3: VIX percentile                                              #
        # ------------------------------------------------------------------ #
        vix_percentile = _compute_vix_percentile(vix, vix_history)

        # ------------------------------------------------------------------ #
        # Step 4: Build rationale                                             #
        # ------------------------------------------------------------------ #
        rationale = _build_rationale(
            winner,
            vix=vix,
            vix_percentile=vix_percentile,
            cum_return=cum_return,
            ad_ratio=ad_ratio,
            fii_net=fii_net,
            breadth=breadth,
        )

        logger.debug(
            "Regime: %s (confidence=%.2f) VIX=%.1f return=%.1f%% votes=%s",
            winner.value,
            confidence,
            vix,
            cum_return * 100,
            {k.value: round(v, 2) for k, v in votes.items()},
        )

        return RegimeSignal(
            regime=winner,
            confidence=round(confidence, 3),
            vix_level=round(vix, 2),
            vix_percentile=round(vix_percentile, 1),
            dxy_level=round(dxy_level, 2) if dxy_level is not None else None,
            advance_decline_ratio=round(ad_ratio, 3) if ad_ratio is not None else None,
            fii_dii_net=round(fii_net, 2) if fii_net is not None else None,
            breadth=round(breadth, 2) if breadth is not None else None,
            rationale=rationale,
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _cumulative_return(returns: list[float]) -> float:
    """Compute cumulative return from a list of daily returns.

    Args:
        returns: Daily returns as decimals (0.01 = 1%).  Uses last 20 values.

    Returns:
        Cumulative return as decimal.  0.0 if returns is empty.
    """
    if not returns:
        return 0.0

    recent = returns[-20:]
    # Compound: ∏(1 + r_i) - 1
    product = 1.0
    for r in recent:
        product *= 1.0 + r
    return product - 1.0


def _compute_vix_percentile(vix: float, history: list[float] | None) -> float:
    """Compute VIX percentile relative to historical values.

    Args:
        vix: Current VIX level.
        history: Optional list of historical VIX values.  When None or empty
            a heuristic range (8–40) is used.

    Returns:
        VIX percentile in [0, 100].
    """
    if history and len(history) >= 5:
        below = sum(1 for h in history if h <= vix)
        return round(100.0 * below / len(history), 1)

    # Heuristic: linear interpolation between 8 (0th pct) and 40 (100th pct)
    vix_min, vix_max = 8.0, 40.0
    clamped = max(vix_min, min(vix_max, vix))
    return round(100.0 * (clamped - vix_min) / (vix_max - vix_min), 1)


def _build_rationale(
    regime: RegimeType,
    vix: float,
    vix_percentile: float,
    cum_return: float,
    ad_ratio: float | None,
    fii_net: float | None,
    breadth: float | None,
) -> str:
    """Build a human-readable rationale string for the detected regime.

    Args:
        regime: The detected regime.
        vix: Current VIX level.
        vix_percentile: VIX percentile.
        cum_return: 20-day cumulative return as decimal.
        ad_ratio: Advance/Decline ratio if available.
        fii_net: Net FII flow if available.
        breadth: Breadth percentage if available.

    Returns:
        Single-sentence rationale string.
    """
    parts: list[str] = []

    # VIX context
    if vix > _VIX_RISK_OFF:
        parts.append(f"VIX at {vix:.1f} (above 30 — extreme fear, {vix_percentile:.0f}th pct)")
    elif vix > _VIX_NORMAL_HI:
        parts.append(f"VIX elevated at {vix:.1f} ({vix_percentile:.0f}th pct)")
    else:
        parts.append(f"VIX subdued at {vix:.1f} ({vix_percentile:.0f}th pct)")

    # Return context
    ret_pct = cum_return * 100
    if abs(ret_pct) >= 1.0:
        direction = "up" if ret_pct > 0 else "down"
        parts.append(f"Nifty {direction} {abs(ret_pct):.1f}% over 20 days")

    # Optional signals
    if ad_ratio is not None:
        parts.append(f"A/D ratio {ad_ratio:.2f}")

    if fii_net is not None:
        flow_dir = "inflow" if fii_net >= 0 else "outflow"
        parts.append(f"FII net {flow_dir} ₹{abs(fii_net):.0f} Cr")

    if breadth is not None:
        parts.append(f"{breadth:.0f}% stocks above 200 DMA")

    # Regime-specific closing
    regime_suffix: dict[RegimeType, str] = {
        RegimeType.RISK_ON: "pointing to risk-on environment.",
        RegimeType.RISK_OFF: "pointing to risk-off positioning.",
        RegimeType.ROTATION: "suggesting active sector rotation.",
        RegimeType.TRENDING_UP: "in a trending-up phase.",
        RegimeType.TRENDING_DOWN: "in a trending-down phase.",
        RegimeType.VOLATILE: "in a volatile, elevated-risk regime.",
        RegimeType.CALM: "in a calm, low-volatility regime.",
    }

    summary = "; ".join(parts)
    suffix = regime_suffix.get(regime, ".")
    return f"{summary} — {suffix}"
