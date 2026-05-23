"""Custom straddle and multi-leg options strategy simulator.

Provides static payoff and risk calculations for common short premium
strategies used in Indian F&O markets.  All functions are pure (no I/O,
no state) and operate on scalar inputs, making them fully unit-testable and
suitable for both the backend analytics routes and the frontend payoff widget.

Strategies covered:
- Short straddle  (sell ATM CE + sell ATM PE)
- Iron condor     (sell OTM CE + buy further OTM CE + sell OTM PE + buy further OTM PE)
- Iron butterfly  (sell ATM CE + sell ATM PE + buy OTM CE + buy OTM PE)

Additionally, :func:`straddle_pnl_curve` builds a P&L curve across a
continuous spot range for any multi-leg structure described as a list of
option leg dicts, enabling the frontend charting widget to render payoff
diagrams without making API calls.

Typical usage::

    from flinttrade_screener.straddle_simulator import (
        simulate_short_straddle,
        simulate_iron_condor,
        simulate_iron_butterfly,
        straddle_pnl_curve,
    )
    import numpy as np

    result = simulate_short_straddle(
        spot=24050.0, strike=24000.0,
        call_premium=180.0, put_premium=175.0,
        lot_size=75,
        adjustment_points=100,
    )
    print(result["max_profit"])       # ₹ 26,625

    spot_range = np.linspace(22000, 26000, 500)
    legs = [
        {"option_type": "CE", "action": "SELL", "strike": 24000, "premium": 180},
        {"option_type": "PE", "action": "SELL", "strike": 24000, "premium": 175},
    ]
    pnl = straddle_pnl_curve(spot_range, legs)
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger("flinttrade.screener.straddle_simulator")


# ---------------------------------------------------------------------------
# Short straddle
# ---------------------------------------------------------------------------


def simulate_short_straddle(
    spot: float,
    strike: float,
    call_premium: float,
    put_premium: float,
    lot_size: int,
    adjustment_points: int = 100,
) -> dict[str, Any]:
    """Calculate risk metrics for a short ATM straddle (sell CE + sell PE).

    The position receives total premium = call_premium + put_premium per unit.
    At expiry:
    - Max profit is achieved if spot settles exactly at ``strike``.
    - Breakeven points are strike ± total_premium.
    - Loss increases linearly beyond the breakeven levels.

    ``adjustment_points`` is used to compute the estimated P&L if the
    underlying moves by ±N points from the entry strike (useful for
    setting stop-loss / adjustment trigger levels).

    Args:
        spot:               Spot price at entry (used for ATM proximity check).
        strike:             Strike at which the straddle is sold.
        call_premium:       CE premium received per unit (₹ points).
        put_premium:        PE premium received per unit (₹ points).
        lot_size:           Contract lot size (quantity per lot).
        adjustment_points:  Points from strike to compute the loss estimate.
                            Default 100 points.

    Returns:
        Dict with keys:
        - ``"strategy"``              (str)   — "short_straddle"
        - ``"strike"``                (float)
        - ``"call_premium"``          (float)
        - ``"put_premium"``           (float)
        - ``"total_premium"``         (float) — CE + PE premium per unit
        - ``"max_profit"``            (float) — total_premium × lot_size (₹)
        - ``"max_profit_per_unit"``   (float) — in points
        - ``"breakeven_low"``         (float) — strike − total_premium
        - ``"breakeven_high"``        (float) — strike + total_premium
        - ``"loss_at_plus_n"``        (float) — P&L (₹) if spot = strike + adj
        - ``"loss_at_minus_n"``       (float) — P&L (₹) if spot = strike − adj
        - ``"adjustment_points"``     (int)
        - ``"lot_size"``              (int)
        - ``"is_atm"``                (bool)  — True if spot ≈ strike (±2%)

    Examples:
        >>> r = simulate_short_straddle(
        ...     spot=24000.0, strike=24000.0,
        ...     call_premium=180.0, put_premium=175.0,
        ...     lot_size=75,
        ... )
        >>> r["max_profit"]
        26625.0
        >>> r["breakeven_low"]
        23645.0
        >>> r["breakeven_high"]
        24355.0
    """
    total_premium = call_premium + put_premium
    max_profit_per_unit = total_premium
    max_profit = max_profit_per_unit * lot_size

    breakeven_low = strike - total_premium
    breakeven_high = strike + total_premium

    # P&L at ±adjustment_points from strike
    spot_up = strike + adjustment_points
    spot_down = strike - adjustment_points
    loss_at_plus_n = _short_straddle_pnl_at_expiry(
        spot_up, strike, call_premium, put_premium, lot_size
    )
    loss_at_minus_n = _short_straddle_pnl_at_expiry(
        spot_down, strike, call_premium, put_premium, lot_size
    )

    is_atm = abs(spot - strike) / max(spot, 1e-9) <= 0.02

    return {
        "strategy": "short_straddle",
        "strike": strike,
        "call_premium": call_premium,
        "put_premium": put_premium,
        "total_premium": round(total_premium, 2),
        "max_profit": round(max_profit, 2),
        "max_profit_per_unit": round(max_profit_per_unit, 2),
        "breakeven_low": round(breakeven_low, 2),
        "breakeven_high": round(breakeven_high, 2),
        "loss_at_plus_n": round(loss_at_plus_n, 2),
        "loss_at_minus_n": round(loss_at_minus_n, 2),
        "adjustment_points": adjustment_points,
        "lot_size": lot_size,
        "is_atm": is_atm,
    }


# ---------------------------------------------------------------------------
# Iron condor
# ---------------------------------------------------------------------------


def simulate_iron_condor(
    spot: float,
    sell_call_strike: float,
    buy_call_strike: float,
    sell_put_strike: float,
    buy_put_strike: float,
    sell_call_premium: float,
    buy_call_premium: float,
    sell_put_premium: float,
    buy_put_premium: float,
    lot_size: int,
) -> dict[str, Any]:
    """Calculate risk metrics for a short iron condor.

    An iron condor sells an OTM call spread and an OTM put spread:
    - Sell OTM CE at ``sell_call_strike``, buy further OTM CE at ``buy_call_strike``
    - Sell OTM PE at ``sell_put_strike``, buy further OTM PE at ``buy_put_strike``

    Args:
        spot:               Current spot price.
        sell_call_strike:   OTM call sold (upper body).
        buy_call_strike:    Further OTM call bought (upper wing hedge).
        sell_put_strike:    OTM put sold (lower body).
        buy_put_strike:     Further OTM put bought (lower wing hedge).
        sell_call_premium:  Premium received for selling the call.
        buy_call_premium:   Premium paid for buying the call hedge.
        sell_put_premium:   Premium received for selling the put.
        buy_put_premium:    Premium paid for buying the put hedge.
        lot_size:           Contract lot size.

    Returns:
        Dict with keys:
        - ``"strategy"``         (str)   — "iron_condor"
        - ``"net_premium"``      (float) — net credit received per unit
        - ``"max_profit"``       (float) — net_premium × lot_size (₹)
        - ``"max_loss_call"``    (float) — max loss from call spread × lot_size
        - ``"max_loss_put"``     (float) — max loss from put spread × lot_size
        - ``"max_loss"``         (float) — max(max_loss_call, max_loss_put) — the
                                           side that can lose more
        - ``"breakeven_low"``    (float) — sell_put_strike − net_premium
        - ``"breakeven_high"``   (float) — sell_call_strike + net_premium
        - ``"profit_zone_low"``  (float) — sell_put_strike
        - ``"profit_zone_high"`` (float) — sell_call_strike
        - ``"lot_size"``         (int)

    Examples:
        >>> r = simulate_iron_condor(
        ...     spot=24000, sell_call_strike=24500, buy_call_strike=24700,
        ...     sell_put_strike=23500, buy_put_strike=23300,
        ...     sell_call_premium=80, buy_call_premium=40,
        ...     sell_put_premium=75, buy_put_premium=35,
        ...     lot_size=75,
        ... )
        >>> r["net_premium"]
        80.0
        >>> r["max_profit"]
        6000.0
    """
    net_premium = (sell_call_premium - buy_call_premium) + (sell_put_premium - buy_put_premium)

    # Call spread max loss (if spot above buy_call_strike)
    call_spread_width = buy_call_strike - sell_call_strike
    max_loss_call_per_unit = call_spread_width - (sell_call_premium - buy_call_premium)
    max_loss_call = max_loss_call_per_unit * lot_size

    # Put spread max loss (if spot below buy_put_strike)
    put_spread_width = sell_put_strike - buy_put_strike
    max_loss_put_per_unit = put_spread_width - (sell_put_premium - buy_put_premium)
    max_loss_put = max_loss_put_per_unit * lot_size

    # Worst case is the larger of the two wings
    max_loss = max(max_loss_call, max_loss_put)

    breakeven_low = sell_put_strike - net_premium
    breakeven_high = sell_call_strike + net_premium

    return {
        "strategy": "iron_condor",
        "spot": spot,
        "sell_call_strike": sell_call_strike,
        "buy_call_strike": buy_call_strike,
        "sell_put_strike": sell_put_strike,
        "buy_put_strike": buy_put_strike,
        "net_premium": round(net_premium, 2),
        "max_profit": round(net_premium * lot_size, 2),
        "max_loss_call": round(max_loss_call, 2),
        "max_loss_put": round(max_loss_put, 2),
        "max_loss": round(max_loss, 2),
        "breakeven_low": round(breakeven_low, 2),
        "breakeven_high": round(breakeven_high, 2),
        "profit_zone_low": sell_put_strike,
        "profit_zone_high": sell_call_strike,
        "lot_size": lot_size,
    }


# ---------------------------------------------------------------------------
# Iron butterfly
# ---------------------------------------------------------------------------


def simulate_iron_butterfly(
    spot: float,
    atm_strike: float,
    buy_call_strike: float,
    buy_put_strike: float,
    sell_call_premium: float,
    sell_put_premium: float,
    buy_call_premium: float,
    buy_put_premium: float,
    lot_size: int,
) -> dict[str, Any]:
    """Calculate risk metrics for a short iron butterfly.

    An iron butterfly is like an iron condor but the sold call and put share
    the same ATM strike:
    - Sell ATM CE + Sell ATM PE at ``atm_strike``
    - Buy OTM CE at ``buy_call_strike`` (upper wing)
    - Buy OTM PE at ``buy_put_strike``  (lower wing)

    Args:
        spot:              Current spot price.
        atm_strike:        Strike for both sold legs (ideally ATM).
        buy_call_strike:   OTM call hedge strike (above atm_strike).
        buy_put_strike:    OTM put hedge strike (below atm_strike).
        sell_call_premium: CE premium received.
        sell_put_premium:  PE premium received.
        buy_call_premium:  OTM CE hedge premium paid.
        buy_put_premium:   OTM PE hedge premium paid.
        lot_size:          Contract lot size.

    Returns:
        Dict with keys:
        - ``"strategy"``         (str)   — "iron_butterfly"
        - ``"net_premium"``      (float) — net credit per unit
        - ``"max_profit"``       (float) — net_premium × lot_size (₹)
        - ``"max_loss_upside"``  (float) — (₹) if spot > buy_call_strike
        - ``"max_loss_downside"``(float) — (₹) if spot < buy_put_strike
        - ``"max_loss"``         (float) — max of upside/downside losses
        - ``"breakeven_low"``    (float) — atm_strike − net_premium
        - ``"breakeven_high"``   (float) — atm_strike + net_premium
        - ``"lot_size"``         (int)

    Examples:
        >>> r = simulate_iron_butterfly(
        ...     spot=24000, atm_strike=24000,
        ...     buy_call_strike=24300, buy_put_strike=23700,
        ...     sell_call_premium=180, sell_put_premium=175,
        ...     buy_call_premium=60, buy_put_premium=55,
        ...     lot_size=75,
        ... )
        >>> r["net_premium"]
        240.0
        >>> r["strategy"]
        'iron_butterfly'
    """
    net_premium = (
        (sell_call_premium + sell_put_premium)
        - (buy_call_premium + buy_put_premium)
    )

    # Upside max loss: spot settles above buy_call_strike
    call_wing_width = buy_call_strike - atm_strike
    max_loss_upside_per_unit = call_wing_width - net_premium
    max_loss_upside = max_loss_upside_per_unit * lot_size

    # Downside max loss: spot settles below buy_put_strike
    put_wing_width = atm_strike - buy_put_strike
    max_loss_downside_per_unit = put_wing_width - net_premium
    max_loss_downside = max_loss_downside_per_unit * lot_size

    max_loss = max(max_loss_upside, max_loss_downside)
    breakeven_low = atm_strike - net_premium
    breakeven_high = atm_strike + net_premium

    return {
        "strategy": "iron_butterfly",
        "spot": spot,
        "atm_strike": atm_strike,
        "buy_call_strike": buy_call_strike,
        "buy_put_strike": buy_put_strike,
        "net_premium": round(net_premium, 2),
        "max_profit": round(net_premium * lot_size, 2),
        "max_loss_upside": round(max_loss_upside, 2),
        "max_loss_downside": round(max_loss_downside, 2),
        "max_loss": round(max_loss, 2),
        "breakeven_low": round(breakeven_low, 2),
        "breakeven_high": round(breakeven_high, 2),
        "lot_size": lot_size,
    }


# ---------------------------------------------------------------------------
# Generic P&L curve
# ---------------------------------------------------------------------------


def straddle_pnl_curve(
    spot_range: NDArray[np.float64],
    legs: list[dict[str, Any]],
) -> NDArray[np.float64]:
    """Calculate at-expiry P&L curve across a spot price range.

    Each leg dict describes one option position.  The P&L is calculated
    at expiry (time value = 0) so it reflects intrinsic value only.  This
    is suitable for strategy visualisation and breakeven analysis.

    Leg dict format::

        {
            "option_type": "CE" | "PE",
            "action":      "BUY" | "SELL",
            "strike":      float,
            "premium":     float,  # premium received (SELL) or paid (BUY)
            "quantity":    int,    # optional, default 1
        }

    P&L per unit per leg at expiry:
    - SELL CE: premium_received − max(0, spot − strike)
    - BUY  CE: max(0, spot − strike) − premium_paid
    - SELL PE: premium_received − max(0, strike − spot)
    - BUY  PE: max(0, strike − spot) − premium_paid

    Args:
        spot_range: 1-D numpy array of spot prices to evaluate.
        legs:       List of option leg dicts (see format above).

    Returns:
        1-D numpy array of total P&L per unit (not multiplied by lot_size),
        same length as ``spot_range``.  The caller multiplies by lot_size
        for ₹ P&L.

    Examples:
        >>> import numpy as np
        >>> legs = [
        ...     {"option_type": "CE", "action": "SELL",
        ...      "strike": 24000, "premium": 180},
        ...     {"option_type": "PE", "action": "SELL",
        ...      "strike": 24000, "premium": 175},
        ... ]
        >>> spots = np.array([23000.0, 24000.0, 25000.0])
        >>> pnl = straddle_pnl_curve(spots, legs)
        >>> float(pnl[1])  # at strike — max profit
        355.0
        >>> pnl[0] < pnl[1]  # OTM is worse than ATM for short straddle
        True
    """
    if spot_range.size == 0 or not legs:
        return np.zeros_like(spot_range)

    total_pnl = np.zeros(len(spot_range), dtype=np.float64)

    for leg in legs:
        option_type = str(leg.get("option_type", "CE")).upper()
        action = str(leg.get("action", "SELL")).upper()
        strike = float(leg.get("strike", 0))
        premium = float(leg.get("premium", 0))
        quantity = float(leg.get("quantity", 1) or 1)

        if strike <= 0:
            logger.warning("Leg has non-positive strike: %s", leg)
            continue

        if option_type == "CE":
            intrinsic = np.maximum(0.0, spot_range - strike)
        else:  # PE
            intrinsic = np.maximum(0.0, strike - spot_range)

        if action == "SELL":
            leg_pnl = (premium - intrinsic) * quantity
        else:  # BUY
            leg_pnl = (intrinsic - premium) * quantity

        total_pnl += leg_pnl

    return np.round(total_pnl, 2)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _short_straddle_pnl_at_expiry(
    spot: float,
    strike: float,
    call_premium: float,
    put_premium: float,
    lot_size: int,
) -> float:
    """Compute short straddle P&L (₹) at a specific spot price at expiry.

    Args:
        spot:          Spot price at expiry.
        strike:        Straddle strike.
        call_premium:  CE premium received per unit.
        put_premium:   PE premium received per unit.
        lot_size:      Contract lot size.

    Returns:
        P&L in ₹.  Positive = profit, negative = loss.
    """
    call_loss = max(0.0, spot - strike)
    put_loss = max(0.0, strike - spot)
    pnl_per_unit = (call_premium + put_premium) - (call_loss + put_loss)
    return round(pnl_per_unit * lot_size, 2)
