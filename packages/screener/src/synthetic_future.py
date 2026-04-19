"""Synthetic future pricing from put-call parity.

Put-call parity for European options states:

    C - P = S - K * e^(-r * t)

Rearranging for the synthetic future price (i.e. the expected future
price implied by the options market):

    Synthetic Future = C - P + K * e^(-r * t)

where:
- C = ATM call price
- P = ATM put price
- K = strike price
- r = risk-free rate (annualised, decimal)
- t = time to expiry (years)

When the ATM call and ATM put share the same strike (as they do at expiry),
this simplifies in the limit to:

    Synthetic Future ≈ K + C - P

The small discrepancy from ``K * e^(-r * t)`` versus ``K`` is the cost-of-carry
adjustment over the remaining life of the contract.

Usage::

    from packages.screener.src.synthetic_future import (
        synthetic_future_price,
        synthetic_vs_actual_spread,
        cost_of_carry,
        SyntheticFutureResult,
        compute_synthetic_future,
    )

    price = synthetic_future_price(
        call_price=285.50,
        put_price=270.00,
        strike=24500.0,
        days_to_expiry=21,
        risk_free_rate=0.065,
    )
    spread = synthetic_vs_actual_spread(price, actual_future=24523.75)
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Core formula functions
# ---------------------------------------------------------------------------


def synthetic_future_price(
    call_price: float,
    put_price: float,
    strike: float,
    days_to_expiry: int,
    risk_free_rate: float = 0.07,
) -> float:
    """Compute the synthetic future price from ATM call and put premiums.

    Applies put-call parity with continuous compounding:

        Synthetic Future = C - P + K * e^(-r * t)

    where ``t = days_to_expiry / 365``.

    Args:
        call_price: Market price (LTP) of the ATM call option.
        put_price: Market price (LTP) of the ATM put option.
        strike: Strike price of both ATM options.
        days_to_expiry: Calendar days remaining to expiry (must be >= 0).
        risk_free_rate: Annualised risk-free rate as a decimal (default 7%).

    Returns:
        Synthetic future price rounded to 2 decimal places.

    Raises:
        ValueError: When any price/rate/days parameter is invalid.

    Examples:
        >>> synthetic_future_price(285.50, 270.00, 24500.0, 21)
        24515.5  # approximate
    """
    if call_price < 0:
        raise ValueError(f"call_price must be >= 0, got {call_price}")
    if put_price < 0:
        raise ValueError(f"put_price must be >= 0, got {put_price}")
    if strike <= 0:
        raise ValueError(f"strike must be > 0, got {strike}")
    if days_to_expiry < 0:
        raise ValueError(f"days_to_expiry must be >= 0, got {days_to_expiry}")
    if risk_free_rate < 0:
        raise ValueError(f"risk_free_rate must be >= 0, got {risk_free_rate}")

    t = days_to_expiry / 365.0
    pv_strike = strike * math.exp(-risk_free_rate * t)
    synthetic = call_price - put_price + pv_strike
    return round(synthetic, 2)


def synthetic_vs_actual_spread(synthetic: float, actual_future: float) -> float:
    """Compute the spread between synthetic and actual futures price.

    A positive spread indicates the synthetic future trades *above* the
    actual — a potential cash-and-carry arbitrage opportunity.  A negative
    spread indicates the reverse.

    Args:
        synthetic: Synthetic future price (from :func:`synthetic_future_price`).
        actual_future: Live futures price from the exchange.

    Returns:
        ``synthetic - actual_future`` rounded to 2 decimal places.

    Raises:
        ValueError: When either price is non-positive.

    Examples:
        >>> synthetic_vs_actual_spread(24515.50, 24523.75)
        -8.25
    """
    if synthetic <= 0:
        raise ValueError(f"synthetic must be > 0, got {synthetic}")
    if actual_future <= 0:
        raise ValueError(f"actual_future must be > 0, got {actual_future}")
    return round(synthetic - actual_future, 2)


def cost_of_carry(
    strike: float,
    days_to_expiry: int,
    risk_free_rate: float = 0.07,
) -> float:
    """Compute the theoretical cost-of-carry adjustment for a given strike.

    This is the difference between the forward price implied by continuous
    compounding and the spot strike:

        CoC = K * (e^(r * t) - 1)

    where ``t = days_to_expiry / 365``.

    Args:
        strike: Strike price.
        days_to_expiry: Calendar days remaining to expiry.
        risk_free_rate: Annualised risk-free rate as a decimal.

    Returns:
        Cost-of-carry in points, rounded to 2 decimal places.

    Raises:
        ValueError: When any parameter is invalid.
    """
    if strike <= 0:
        raise ValueError(f"strike must be > 0, got {strike}")
    if days_to_expiry < 0:
        raise ValueError(f"days_to_expiry must be >= 0, got {days_to_expiry}")
    if risk_free_rate < 0:
        raise ValueError(f"risk_free_rate must be >= 0, got {risk_free_rate}")

    t = days_to_expiry / 365.0
    return round(strike * (math.exp(risk_free_rate * t) - 1), 2)


def implied_basis(
    call_price: float,
    put_price: float,
    spot: float,
    days_to_expiry: int,
    risk_free_rate: float = 0.07,
) -> float:
    """Compute implied basis = Synthetic Future - Spot.

    The basis represents the net cost-of-carry embedded in option prices.
    High absolute basis (relative to theoretical) may signal mispricing or
    corporate actions.

    Args:
        call_price: ATM call price.
        put_price: ATM put price.
        spot: Current spot/index price.
        days_to_expiry: Days to expiry.
        risk_free_rate: Annualised risk-free rate.

    Returns:
        Basis in points (positive = contango, negative = backwardation).

    Raises:
        ValueError: Delegates to :func:`synthetic_future_price`.
    """
    if spot <= 0:
        raise ValueError(f"spot must be > 0, got {spot}")
    synthetic = synthetic_future_price(
        call_price=call_price,
        put_price=put_price,
        strike=spot,  # ATM strike ≈ spot
        days_to_expiry=days_to_expiry,
        risk_free_rate=risk_free_rate,
    )
    return round(synthetic - spot, 2)


# ---------------------------------------------------------------------------
# Structured result
# ---------------------------------------------------------------------------


@dataclass
class SyntheticFutureResult:
    """Full result object for a synthetic future calculation.

    Attributes:
        call_price: ATM call price used.
        put_price: ATM put price used.
        strike: Strike price used.
        days_to_expiry: Calendar days to expiry.
        risk_free_rate: Risk-free rate used.
        synthetic_price: Computed synthetic future price.
        actual_future: Live futures price (0.0 if not provided).
        spread: ``synthetic_price - actual_future`` (0.0 if actual not provided).
        carry: Theoretical cost of carry for this strike.
    """

    call_price: float
    put_price: float
    strike: float
    days_to_expiry: int
    risk_free_rate: float
    synthetic_price: float
    actual_future: float = 0.0
    spread: float = 0.0
    carry: float = 0.0


def compute_synthetic_future(
    call_price: float,
    put_price: float,
    strike: float,
    days_to_expiry: int,
    risk_free_rate: float = 0.07,
    actual_future: float = 0.0,
) -> SyntheticFutureResult:
    """Compute synthetic future and return a fully populated result object.

    Convenience wrapper around :func:`synthetic_future_price`,
    :func:`synthetic_vs_actual_spread`, and :func:`cost_of_carry`.

    Args:
        call_price: ATM call price.
        put_price: ATM put price.
        strike: Strike price.
        days_to_expiry: Calendar days to expiry.
        risk_free_rate: Annualised risk-free rate (default 7%).
        actual_future: Live futures price for spread calculation (0 = skip).

    Returns:
        :class:`SyntheticFutureResult` populated with all computed values.
    """
    synth = synthetic_future_price(call_price, put_price, strike, days_to_expiry, risk_free_rate)
    carry = cost_of_carry(strike, days_to_expiry, risk_free_rate)

    spread = 0.0
    if actual_future > 0:
        spread = synthetic_vs_actual_spread(synth, actual_future)

    return SyntheticFutureResult(
        call_price=call_price,
        put_price=put_price,
        strike=strike,
        days_to_expiry=days_to_expiry,
        risk_free_rate=risk_free_rate,
        synthetic_price=synth,
        actual_future=actual_future,
        spread=spread,
        carry=carry,
    )
