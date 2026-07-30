"""Options payoff analysis engine.

Calculates P&L curves, Greeks aggregation, breakevens, and probability of
profit for multi-leg option strategies.

Adapted patterns:
- Black-Scholes Greeks from packages/services/screener/src/greeks.py (_bs_greeks)
- Pydantic model conventions from packages/core/core/src/models.py
- Standard normal helpers (_norm_cdf, _norm_pdf) already in this package

Supports:
- Payoff at expiry across a spot range (N_POINTS resolution)
- Payoff before expiry via Black-Scholes time value
- Monte Carlo probability of profit
- Net Greeks aggregation (delta, gamma, theta, vega) across all legs
"""

from __future__ import annotations

import logging
import math
import random
from typing import Literal

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger("flinttrade.screener.options_payoff")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_RISK_FREE_RATE: float = 0.065   # 6.5% India risk-free rate
_MC_SAMPLES: int = 10_000               # Monte Carlo draws for POP
_DEFAULT_N_POINTS: int = 200            # Spot range resolution
_EPSILON: float = 1e-9                  # Guard against division by zero


# ---------------------------------------------------------------------------
# Black-Scholes helpers (local, no external dependency)
# ---------------------------------------------------------------------------

def _norm_cdf(x: float) -> float:
    """Standard normal CDF via math.erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _bs_price(
    flag: Literal["c", "p"],
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
) -> float:
    """Black-Scholes option price.

    Args:
        flag: 'c' for call, 'p' for put.
        S: Spot price.
        K: Strike price.
        T: Time to expiry in years (> 0).
        r: Risk-free rate as decimal.
        sigma: Implied volatility as decimal.

    Returns:
        Option price.  Returns intrinsic value when T <= 0 or sigma <= 0.
    """
    if T <= 0 or sigma <= 0:
        if flag == "c":
            return max(0.0, S - K)
        return max(0.0, K - S)

    d1 = (math.log(S / K + _EPSILON) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if flag == "c":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def _bs_delta(flag: Literal["c", "p"], S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Black-Scholes delta."""
    if T <= 0 or sigma <= 0:
        if flag == "c":
            return 1.0 if S > K else 0.0
        return (-1.0 if S < K else 0.0)
    d1 = (math.log(S / K + _EPSILON) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    nd1 = _norm_cdf(d1)
    return nd1 if flag == "c" else nd1 - 1.0


def _bs_greeks_full(
    flag: Literal["c", "p"],
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
) -> tuple[float, float, float, float]:
    """Return (delta, gamma, theta, vega) from Black-Scholes.

    Args:
        flag: 'c' for call, 'p' for put.
        S: Spot price.
        K: Strike price.
        T: Time to expiry in years.
        r: Risk-free rate.
        sigma: Implied volatility.

    Returns:
        Tuple of (delta, gamma, theta, vega).  Theta is per calendar day.
        Vega is per 1% IV move.
    """
    if T <= 0 or sigma <= 0 or S <= 0:
        if flag == "c":
            delta = 1.0 if S > K else 0.0
        else:
            delta = -1.0 if S < K else 0.0
        return delta, 0.0, 0.0, 0.0

    d1 = (math.log(S / K + _EPSILON) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    nd1 = _norm_cdf(d1)
    nd2 = _norm_cdf(d2)
    npd1 = _norm_pdf(d1)

    if flag == "c":
        delta = nd1
        theta = (
            (-S * npd1 * sigma / (2.0 * math.sqrt(T)))
            - r * K * math.exp(-r * T) * nd2
        ) / 365.0
    else:
        delta = nd1 - 1.0
        theta = (
            (-S * npd1 * sigma / (2.0 * math.sqrt(T)))
            + r * K * math.exp(-r * T) * _norm_cdf(-d2)
        ) / 365.0

    gamma = npd1 / (S * sigma * math.sqrt(T))
    vega = S * npd1 * math.sqrt(T) / 100.0   # per 1% IV

    return (
        round(delta, 6),
        round(gamma, 8),
        round(theta, 4),
        round(vega, 4),
    )


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class OptionLeg(BaseModel):
    """A single option leg in a multi-leg strategy.

    Attributes:
        side: 'BUY' or 'SELL'.
        option_type: 'CE' (call) or 'PE' (put).
        strike: Strike price.
        lots: Number of lots.
        premium: Premium paid/received per unit.
        lot_size: Shares per lot (default 1 for index normalised).
    """

    side: Literal["BUY", "SELL"]
    option_type: Literal["CE", "PE"]
    strike: float = Field(gt=0)
    lots: int = Field(ge=1)
    premium: float = Field(ge=0)
    lot_size: int = Field(default=1, ge=1)

    @model_validator(mode="after")
    def _validate_fields(self) -> "OptionLeg":
        """Validate that strike and premium are non-negative."""
        if self.strike <= 0:
            raise ValueError("strike must be positive")
        return self

    @property
    def quantity(self) -> int:
        """Total contracts (lots × lot_size)."""
        return self.lots * self.lot_size

    @property
    def sign(self) -> int:
        """Position sign: +1 for BUY, -1 for SELL."""
        return 1 if self.side == "BUY" else -1

    def intrinsic_at_expiry(self, spot: float) -> float:
        """Intrinsic value per unit at expiry.

        Args:
            spot: Spot price at expiry.

        Returns:
            Intrinsic value (non-negative).
        """
        if self.option_type == "CE":
            return max(0.0, spot - self.strike)
        return max(0.0, self.strike - spot)

    def pnl_at_expiry(self, spot: float) -> float:
        """P&L per unit at expiry (before lot-size scaling).

        Args:
            spot: Spot price at expiry.

        Returns:
            P&L per unit.  Positive = profit.
        """
        intrinsic = self.intrinsic_at_expiry(spot)
        # BUY: paid premium, receive intrinsic → intrinsic - premium
        # SELL: received premium, pay intrinsic → premium - intrinsic
        return self.sign * (intrinsic - self.premium)


class PayoffPoint(BaseModel):
    """A single point on the P&L curve.

    Attributes:
        spot: Spot price at this point.
        pnl: Net P&L (in points, sum across all legs × quantity).
    """

    spot: float
    pnl: float


class PayoffAnalysis(BaseModel):
    """Full payoff analysis result for a multi-leg strategy.

    Attributes:
        legs: Input legs.
        points: P&L curve at expiry across spot range.
        max_profit: Maximum achievable profit (None = unlimited).
        max_loss: Maximum possible loss (None = unlimited).
        breakevens: List of spot prices where P&L crosses zero.
        net_premium: Net premium (positive = credit received, negative = debit paid).
        net_delta: Aggregated delta across all legs.
        net_gamma: Aggregated gamma across all legs.
        net_theta: Aggregated theta across all legs.
        net_vega: Aggregated vega across all legs.
        pop: Probability of profit estimate (0–1).
    """

    legs: list[OptionLeg]
    points: list[PayoffPoint]
    max_profit: float | None
    max_loss: float | None
    breakevens: list[float]
    net_premium: float
    net_delta: float
    net_gamma: float
    net_theta: float
    net_vega: float
    pop: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class OptionsPayoffEngine:
    """Full payoff analysis engine for multi-leg option strategies.

    Usage::

        engine = OptionsPayoffEngine()
        legs = [
            OptionLeg(side="SELL", option_type="CE", strike=24000, lots=1, premium=200),
            OptionLeg(side="SELL", option_type="PE", strike=24000, lots=1, premium=210),
        ]
        result = engine.calculate(legs, spot=24000)
        print(f"Net premium: {result.net_premium}")
        print(f"Breakevens: {result.breakevens}")
        print(f"POP: {result.pop:.1%}")
    """

    def calculate(
        self,
        legs: list[OptionLeg],
        spot: float,
        iv: float = 0.2,
        days_to_expiry: int = 30,
        risk_free_rate: float = _DEFAULT_RISK_FREE_RATE,
    ) -> PayoffAnalysis:
        """Full payoff analysis with Greeks and probability of profit.

        Args:
            legs: List of option legs.
            spot: Current spot price.
            iv: Implied volatility as decimal (e.g. 0.20 = 20%).
            days_to_expiry: Calendar days to expiry.
            risk_free_rate: Risk-free rate as decimal.

        Returns:
            PayoffAnalysis with all fields populated.
        """
        if not legs:
            return _empty_analysis(legs)

        # P&L curve at expiry
        lo = spot * 0.7
        hi = spot * 1.3
        points = self.payoff_at_expiry(legs, spot_range=(lo, hi), n_points=_DEFAULT_N_POINTS)

        # Net premium: sum of (sell → +premium, buy → -premium) × quantity
        net_premium = sum(
            (1 if leg.side == "SELL" else -1) * leg.premium * leg.quantity
            for leg in legs
        )

        # Breakevens from expiry curve
        breakevens = _find_breakevens(points)

        # Max profit / max loss from expiry curve
        pnl_values = [p.pnl for p in points]
        max_profit: float | None = max(pnl_values) if pnl_values else None
        max_loss: float | None = min(pnl_values) if pnl_values else None

        # Greeks at current spot
        T = max(days_to_expiry, 0) / 365.0
        net_delta = 0.0
        net_gamma = 0.0
        net_theta = 0.0
        net_vega = 0.0

        for leg in legs:
            flag: Literal["c", "p"] = "c" if leg.option_type == "CE" else "p"
            d, g, th, v = _bs_greeks_full(flag, spot, leg.strike, T, risk_free_rate, iv)
            qty_sign = leg.sign * leg.quantity
            net_delta += d * qty_sign
            net_gamma += g * qty_sign
            net_theta += th * qty_sign
            net_vega += v * qty_sign

        pop = self.probability_of_profit(legs, spot, iv, days_to_expiry)

        return PayoffAnalysis(
            legs=legs,
            points=points,
            max_profit=round(max_profit, 2) if max_profit is not None else None,
            max_loss=round(max_loss, 2) if max_loss is not None else None,
            breakevens=[round(b, 2) for b in breakevens],
            net_premium=round(net_premium, 2),
            net_delta=round(net_delta, 4),
            net_gamma=round(net_gamma, 8),
            net_theta=round(net_theta, 4),
            net_vega=round(net_vega, 4),
            pop=round(pop, 4),
        )

    def payoff_at_expiry(
        self,
        legs: list[OptionLeg],
        spot_range: tuple[float, float],
        n_points: int = _DEFAULT_N_POINTS,
    ) -> list[PayoffPoint]:
        """P&L curve at expiry across a spot price range.

        Args:
            legs: List of option legs.
            spot_range: (low, high) spot price bounds.
            n_points: Number of evaluation points.

        Returns:
            Sorted list of PayoffPoint objects.
        """
        if not legs or n_points < 2:
            return []

        lo, hi = spot_range
        if lo >= hi:
            return []

        step = (hi - lo) / (n_points - 1)
        points: list[PayoffPoint] = []

        for i in range(n_points):
            s = lo + i * step
            pnl = sum(
                leg.pnl_at_expiry(s) * leg.quantity
                for leg in legs
            )
            points.append(PayoffPoint(spot=round(s, 2), pnl=round(pnl, 2)))

        return points

    def payoff_before_expiry(
        self,
        legs: list[OptionLeg],
        spot: float,
        iv: float,
        days: int,
        risk_free_rate: float = _DEFAULT_RISK_FREE_RATE,
        n_points: int = _DEFAULT_N_POINTS,
    ) -> list[PayoffPoint]:
        """P&L curve before expiry using Black-Scholes time value.

        At each spot level the BS price is computed for every leg.
        P&L = (current BS price − entry premium) × quantity × sign.

        Args:
            legs: List of option legs.
            spot: Reference spot (used to derive range: ±30%).
            iv: Current implied volatility as decimal.
            days: Days remaining to expiry.
            risk_free_rate: Risk-free rate as decimal.
            n_points: Number of evaluation points.

        Returns:
            Sorted list of PayoffPoint objects.
        """
        if not legs or n_points < 2:
            return []

        T = max(days, 0) / 365.0
        lo = spot * 0.7
        hi = spot * 1.3
        step = (hi - lo) / (n_points - 1)
        points: list[PayoffPoint] = []

        for i in range(n_points):
            s = lo + i * step
            pnl = 0.0
            for leg in legs:
                flag: Literal["c", "p"] = "c" if leg.option_type == "CE" else "p"
                current_price = _bs_price(flag, s, leg.strike, T, risk_free_rate, iv)
                # BUY: paid premium, now worth current_price → current_price - premium
                # SELL: received premium, now costs current_price → premium - current_price
                leg_pnl = leg.sign * (current_price - leg.premium) * leg.quantity
                pnl += leg_pnl
            points.append(PayoffPoint(spot=round(s, 2), pnl=round(pnl, 2)))

        return points

    def probability_of_profit(
        self,
        legs: list[OptionLeg],
        spot: float,
        iv: float,
        days: int,
        risk_free_rate: float = _DEFAULT_RISK_FREE_RATE,
        n_samples: int = _MC_SAMPLES,
    ) -> float:
        """Monte Carlo probability of profit estimate.

        Simulates log-normal spot distribution at expiry under GBM and counts
        the fraction of paths where aggregate P&L > 0.

        Args:
            legs: List of option legs.
            spot: Current spot price.
            iv: Implied volatility as decimal.
            days: Days to expiry.
            risk_free_rate: Risk-free rate as decimal.
            n_samples: Number of Monte Carlo paths.

        Returns:
            Probability of profit in [0, 1].
        """
        if not legs or days <= 0 or iv <= 0 or spot <= 0:
            # Analytical fallback at expiry: fraction of expiry payoff curve > 0
            lo = spot * 0.7
            hi = spot * 1.3
            points = self.payoff_at_expiry(legs, (lo, hi), n_points=500)
            if not points:
                return 0.0
            profitable = sum(1 for p in points if p.pnl > 0)
            return profitable / len(points)

        T = days / 365.0
        # GBM: S_T = S * exp((r - 0.5*σ²)T + σ√T * Z)
        drift = (risk_free_rate - 0.5 * iv * iv) * T
        vol_sqrt_t = iv * math.sqrt(T)

        rng = random.Random(42)  # Deterministic seed for reproducibility
        profitable_paths = 0

        for _ in range(n_samples):
            z = rng.gauss(0.0, 1.0)
            simulated_spot = spot * math.exp(drift + vol_sqrt_t * z)
            pnl = sum(
                leg.pnl_at_expiry(simulated_spot) * leg.quantity
                for leg in legs
            )
            if pnl > 0:
                profitable_paths += 1

        return profitable_paths / n_samples


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _find_breakevens(points: list[PayoffPoint], tolerance: float = 5.0) -> list[float]:
    """Find spot prices where P&L crosses zero.

    Uses linear interpolation between adjacent points when a sign change is
    detected.  Points within `tolerance` of zero are also included.

    Args:
        points: Sorted list of PayoffPoint objects.
        tolerance: P&L magnitude below which a point is treated as breakeven.

    Returns:
        Deduplicated list of breakeven spot prices, sorted ascending.
    """
    if not points:
        return []

    breakevens: list[float] = []
    prev = points[0]

    for curr in points[1:]:
        # Sign change → interpolate zero crossing
        if prev.pnl * curr.pnl < 0:
            # Linear interpolation
            fraction = -prev.pnl / (curr.pnl - prev.pnl)
            be_spot = prev.spot + fraction * (curr.spot - prev.spot)
            breakevens.append(round(be_spot, 2))
        # Near-zero point
        elif abs(curr.pnl) <= tolerance:
            breakevens.append(curr.spot)
        prev = curr

    # Deduplicate: merge BEs within 0.5 points of each other
    if not breakevens:
        return []

    breakevens.sort()
    deduped: list[float] = [breakevens[0]]
    for be in breakevens[1:]:
        if be - deduped[-1] > 0.5:
            deduped.append(be)

    return deduped


def _empty_analysis(legs: list[OptionLeg]) -> PayoffAnalysis:
    """Return a zeroed PayoffAnalysis for edge cases (no legs).

    Args:
        legs: Legs list (may be empty).

    Returns:
        PayoffAnalysis with all-zero fields.
    """
    return PayoffAnalysis(
        legs=legs,
        points=[],
        max_profit=0.0,
        max_loss=0.0,
        breakevens=[],
        net_premium=0.0,
        net_delta=0.0,
        net_gamma=0.0,
        net_theta=0.0,
        net_vega=0.0,
        pop=0.0,
    )
