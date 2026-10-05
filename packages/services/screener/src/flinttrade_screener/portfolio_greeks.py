"""Local portfolio sensitivities, volatility ranks and payoff surfaces.

The calculations consume supplied observations and mathematical option values.
They do not fetch broker data or choose live execution targets.
"""
from __future__ import annotations

import math
from bisect import bisect_left
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import NamedTuple

import numpy as np
from numpy.typing import NDArray

from flinttrade_core.models import OptionGreek
from flinttrade_core.symbol_utils import parse_option_symbol

from .greeks import OptionPosition, PortfolioGreeks, PortfolioGreeksResult, PositionGreeks, _option_value


@dataclass
class PositionGreeksEx(PositionGreeks):
    rho: float = 0.0


@dataclass
class PortfolioGreeksResultEx(PortfolioGreeksResult):
    net_rho: float = 0.0
    positions: list[PositionGreeksEx] = field(default_factory=list)  # type: ignore[assignment]


def _history(values: NDArray[np.float64]) -> list[float]:
    readings = [float(value) for value in values]
    if any(not math.isfinite(value) for value in readings):
        raise ValueError("IV history must contain finite readings")
    return readings


def iv_percentile(iv_history: NDArray[np.float64]) -> float:
    observations = _history(iv_history)
    if len(observations) < 2:
        return 0.0
    current, prior = observations[-1], sorted(observations[:-1])
    return bisect_left(prior, current) / len(prior)


def iv_rank(iv_history: NDArray[np.float64]) -> float:
    observations = _history(iv_history)
    if len(observations) < 2:
        return 0.0
    low, high = min(observations), max(observations)
    return (observations[-1] - low) / (high - low) if high > low else 0.0


class GreeksPnlAttribution(NamedTuple):
    delta_pnl: float
    gamma_pnl: float
    theta_pnl: float
    vega_pnl: float
    total_greek_pnl: float


def greeks_pnl_attribution(net_delta: float, net_gamma: float, net_theta: float, net_vega: float,
                           spot_move: float, iv_change: float, days: float = 1.0) -> GreeksPnlAttribution:
    components = (net_delta * spot_move, net_gamma * spot_move ** 2 / 2, net_theta * days, net_vega * iv_change)
    rounded = [round(value, digits) for value, digits in zip(components, (2, 4, 2, 2), strict=True)]
    return GreeksPnlAttribution(*rounded, round(math.fsum(components), 2))


def portfolio_pcr(positions: list[OptionPosition]) -> float:
    totals = Counter()
    for position in positions:
        if position.action.upper() == "BUY":
            totals[position.option_type.upper()] += position.lots
    return round(totals["PE"] / totals["CE"], 4) if totals["CE"] else 0.0


class MaxPainResult(NamedTuple):
    max_pain_strike: float
    pain_by_strike: dict[float, float]
    min_pain_strike: float


def max_pain_enhanced(strikes: list[float], ce_oi: list[int], pe_oi: list[int], lot_size: int = 1) -> MaxPainResult:
    """Return extrema of weighted intrinsic payouts for candidate strike prices.

    Field names retain the saved analytics contract: ``max_pain_strike`` is the
    largest payout, and ``min_pain_strike`` the smallest payout.
    """
    if not strikes:
        raise ValueError("strikes list must not be empty")
    if len(strikes) != len(ce_oi) or len(strikes) != len(pe_oi):
        raise ValueError("Length mismatch between strikes and open-interest observations")
    prices = np.asarray(strikes, dtype=np.float64)
    difference = prices[:, None] - prices[None, :]
    payouts = (np.maximum(difference, 0) @ np.asarray(ce_oi) +
               np.maximum(-difference, 0) @ np.asarray(pe_oi)) * lot_size
    surface = {float(price): round(float(payout), 2) for price, payout in zip(prices, payouts, strict=True)}
    return MaxPainResult(max(surface, key=surface.get), surface, min(surface, key=surface.get))


def _bs_rho(flag: str, S: float, K: float, T: float, r: float, sigma: float) -> float:
    """Central rate sensitivity of local option value, per percentage point."""
    if min(S, K, T, sigma) <= 0:
        return 0.0
    step = 1e-5
    lower = _option_value(flag, S, K, T, r - step, sigma)
    upper = _option_value(flag, S, K, T, r + step, sigma)
    return round((upper - lower) / (2 * step * 100), 4)


class EnhancedPortfolioGreeks(PortfolioGreeks):
    """Extend supplied position sensitivities with local rate sensitivity."""

    def calculate_enhanced(self, positions: list[OptionPosition], spot: float | None = None,
                           time_to_expiry: float | None = None, risk_free_rate: float = 0.07,
                           greeks_override: dict[str, OptionGreek] | None = None) -> PortfolioGreeksResultEx:
        base = self.calculate(positions, greeks_override)
        enhanced = []
        for observation in base.positions:
            rate_exposure = 0.0
            contract = parse_option_symbol(observation.symbol)
            if contract is not None and spot is not None and time_to_expiry is not None:
                value = _bs_rho("c" if observation.option_type.upper() == "CE" else "p", spot, contract.strike,
                                time_to_expiry, risk_free_rate, observation.iv / 100 if observation.iv > 0 else 0.2)
                rate_exposure = value * observation.quantity * (1 if observation.action.upper() == "BUY" else -1)
            enhanced.append(PositionGreeksEx(**asdict(observation), rho=rate_exposure))
        return PortfolioGreeksResultEx(net_delta=base.net_delta, net_gamma=base.net_gamma,
                                       net_theta=base.net_theta, net_vega=base.net_vega, positions=enhanced,
                                       net_rho=round(math.fsum(position.rho for position in enhanced), 4))

    @staticmethod
    def attribute_pnl(result: PortfolioGreeksResult | PortfolioGreeksResultEx, spot_move: float,
                      iv_change: float = 0.0, days: float = 1.0) -> GreeksPnlAttribution:
        return greeks_pnl_attribution(result.net_delta, result.net_gamma, result.net_theta, result.net_vega,
                                      spot_move, iv_change, days)

    @staticmethod
    def pcr(positions: list[OptionPosition]) -> float:
        return portfolio_pcr(positions)
