"""Straddle P&L simulation with dynamic re-hedging.

Simulates the intraday P&L of a short straddle (sell ATM CE + sell ATM PE).
The simulation:
1. Starts with combined premium received (ce_premium + pe_premium).
2. Tracks combined premium cost over time using candle OHLCV data.
3. When the net P&L moves by adjustment_points from the last hedge level,
   records an adjustment event (simulating re-entry at new ATM).
4. Returns full P&L series, adjustment timestamps, and summary stats.

Candle format (dict):
    {
        "time": int,    # Unix timestamp (seconds)
        "open": float,
        "high": float,
        "low": float,
        "close": float,
        "volume": float  # optional
    }

P&L is expressed in points (not ₹). Multiply by lot_size to get ₹ P&L.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("flinttrade.screener.straddle_pnl")


@dataclass
class AdjustmentEvent:
    """A single re-hedge / adjustment event during simulation.

    Attributes:
        timestamp: Unix timestamp when adjustment occurred.
        trigger_pnl: P&L value that triggered the adjustment.
        new_strike: Estimated new ATM strike after adjustment.
        direction: 'UP' if spot moved up, 'DOWN' if moved down.
    """

    timestamp: int = 0
    trigger_pnl: float = 0.0
    new_strike: float = 0.0
    direction: str = ""


@dataclass
class StraddlePnLResult:
    """Complete straddle P&L simulation result.

    Attributes:
        timestamps: Unix timestamps for each data point.
        pnl_series: P&L at each timestamp (in points).
        adjustments: List of re-hedge events.
        max_pnl: Best (highest) P&L achieved during simulation.
        min_pnl: Worst (lowest) P&L during simulation.
        final_pnl: P&L at end of simulation.
        initial_premium: Combined premium received at entry.
        lot_size: Lot size used for ₹ conversion.
        adjustment_count: Total number of adjustments made.
        strike: Initial strike used for the straddle.
    """

    timestamps: list[int] = field(default_factory=list)
    pnl_series: list[float] = field(default_factory=list)
    adjustments: list[AdjustmentEvent] = field(default_factory=list)
    max_pnl: float = 0.0
    min_pnl: float = 0.0
    final_pnl: float = 0.0
    initial_premium: float = 0.0
    lot_size: int = 0
    adjustment_count: int = 0
    strike: float = 0.0

    @property
    def pnl_rupees(self) -> list[float]:
        """P&L series in Indian Rupees (points × lot_size)."""
        return [p * self.lot_size for p in self.pnl_series]

    @property
    def max_pnl_rupees(self) -> float:
        """Best P&L in ₹."""
        return self.max_pnl * self.lot_size

    @property
    def min_pnl_rupees(self) -> float:
        """Worst P&L in ₹."""
        return self.min_pnl * self.lot_size

    @property
    def final_pnl_rupees(self) -> float:
        """Final P&L in ₹."""
        return self.final_pnl * self.lot_size


def _estimate_straddle_value(
    spot: float,
    strike: float,
    ce_premium_initial: float,
    pe_premium_initial: float,
    initial_spot: float,
) -> float:
    """Estimate current straddle premium using intrinsic value proxy.

    When real-time option prices are not available (candle-only simulation),
    we approximate straddle value using the intrinsic + a time value estimate.
    The approximation:
        straddle_value ≈ |spot - strike| + min(ce_premium, pe_premium) * decay

    This is a simplified model suitable for educational/analytical purposes.
    Real P&L tracking in production should use live option quotes.

    Args:
        spot: Current spot price.
        strike: Straddle strike.
        ce_premium_initial: Initial CE premium received.
        pe_premium_initial: Initial PE premium received.
        initial_spot: Spot price at entry.

    Returns:
        Estimated current straddle value (cost to buy back).
    """
    # Intrinsic value of the straddle = |spot - strike|
    intrinsic = abs(spot - strike)

    # ATM premium as proxy for time value (decays as spot moves away)
    atm_premium = (ce_premium_initial + pe_premium_initial) / 2.0
    spot_move = abs(spot - initial_spot)
    # Simple linear decay as spot moves (rough approximation)
    time_value_decay = max(0.0, atm_premium - spot_move * 0.5)

    return intrinsic + time_value_decay


def simulate_straddle_pnl(
    candles: list[dict[str, Any]],
    strike: float,
    ce_premium: float,
    pe_premium: float,
    adjustment_points: float,
    lot_size: int,
) -> StraddlePnLResult:
    """Simulate short straddle P&L with dynamic re-hedging.

    The simulation sells a straddle at the given strike and tracks P&L
    over the candle series. When P&L deteriorates by adjustment_points
    from the last adjustment level, a re-hedge event is recorded.

    Args:
        candles: List of OHLCV candle dicts, each with 'time', 'open',
                 'high', 'low', 'close' keys.
        strike: Straddle strike price (ideally ATM at entry).
        ce_premium: CE (call) premium received per lot.
        pe_premium: PE (put) premium received per lot.
        adjustment_points: P&L drawdown (in points) that triggers re-hedging.
        lot_size: Contract lot size for ₹ conversion.

    Returns:
        StraddlePnLResult with full P&L series and adjustment events.
    """
    if not candles or ce_premium <= 0 or pe_premium <= 0:
        return StraddlePnLResult(
            initial_premium=ce_premium + pe_premium,
            lot_size=lot_size,
            strike=strike,
        )

    initial_premium = ce_premium + pe_premium
    initial_spot = float(candles[0].get("open", strike))

    timestamps: list[int] = []
    pnl_series: list[float] = []
    adjustments: list[AdjustmentEvent] = []

    # Track last adjustment P&L level for re-hedge trigger
    last_adjustment_pnl = 0.0
    current_strike = strike
    current_premium = initial_premium

    max_pnl = float("-inf")
    min_pnl = float("inf")

    for candle in candles:
        ts = int(candle.get("time", 0))
        close = float(candle.get("close", current_strike))
        high = float(candle.get("high", close))
        low = float(candle.get("low", close))

        # Estimate current straddle value using close price
        current_value = _estimate_straddle_value(
            spot=close,
            strike=current_strike,
            ce_premium_initial=ce_premium,
            pe_premium_initial=pe_premium,
            initial_spot=initial_spot,
        )

        # P&L = premium received - current cost to close
        pnl = current_premium - current_value

        # Check if high/low triggered adjustment during this candle
        # (conservative: use the worst of high/low for adverse moves)
        high_value = _estimate_straddle_value(
            spot=high,
            strike=current_strike,
            ce_premium_initial=ce_premium,
            pe_premium_initial=pe_premium,
            initial_spot=initial_spot,
        )
        low_value = _estimate_straddle_value(
            spot=low,
            strike=current_strike,
            ce_premium_initial=ce_premium,
            pe_premium_initial=pe_premium,
            initial_spot=initial_spot,
        )

        # Worst intracandle P&L
        worst_pnl = current_premium - max(high_value, low_value)

        # Check adjustment trigger
        if adjustment_points > 0:
            drawdown_from_last = last_adjustment_pnl - worst_pnl
            if drawdown_from_last >= adjustment_points:
                # Determine direction from close vs initial spot
                direction = "UP" if close > initial_spot else "DOWN"
                adjustments.append(AdjustmentEvent(
                    timestamp=ts,
                    trigger_pnl=worst_pnl,
                    new_strike=round(close / 50) * 50,  # Round to nearest 50 for index
                    direction=direction,
                ))
                # After adjustment: reset to new ATM, recalculate premium
                current_strike = round(close / 50) * 50
                # Approximate new premium as reduced value
                current_premium = max(0.0, current_value * 0.9)
                last_adjustment_pnl = current_premium - current_value

        timestamps.append(ts)
        pnl_series.append(round(pnl, 2))
        max_pnl = max(max_pnl, pnl)
        min_pnl = min(min_pnl, pnl)

    final_pnl = pnl_series[-1] if pnl_series else 0.0
    if max_pnl == float("-inf"):
        max_pnl = 0.0
    if min_pnl == float("inf"):
        min_pnl = 0.0

    return StraddlePnLResult(
        timestamps=timestamps,
        pnl_series=pnl_series,
        adjustments=adjustments,
        max_pnl=round(max_pnl, 2),
        min_pnl=round(min_pnl, 2),
        final_pnl=round(final_pnl, 2),
        initial_premium=initial_premium,
        lot_size=lot_size,
        adjustment_count=len(adjustments),
        strike=strike,
    )
