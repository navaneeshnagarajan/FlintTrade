"""Native option exposure scaling and local Black–Scholes sensitivities.

Inputs are typed option positions and caller-supplied native Greek observations.
No broker endpoint or symbol inference is used to source missing observations.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import NormalDist

from flinttrade_core.broker_client import BrokerClient
from flinttrade_core.models import OptionGreek

from .option_chain import LOT_SIZES


@dataclass
class OptionPosition:
    symbol: str
    exchange: str = "NFO"
    option_type: str = "CE"
    action: str = "BUY"
    lots: int = 1
    lot_size: int = 65
    underlying: str = ""

    @property
    def quantity(self) -> int:
        return self.lots * self.lot_size

    @property
    def sign(self) -> int:
        return 1 if self.action.upper() == "BUY" else -1


@dataclass
class PositionGreeks:
    symbol: str = ""
    option_type: str = ""
    action: str = ""
    lots: int = 0
    quantity: int = 0
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    iv: float = 0.0


@dataclass
class PortfolioGreeksResult:
    net_delta: float = 0.0
    net_gamma: float = 0.0
    net_theta: float = 0.0
    net_vega: float = 0.0
    positions: list[PositionGreeks] = field(default_factory=list)

    @property
    def position_count(self) -> int:
        return len(self.positions)

    @property
    def is_delta_neutral(self) -> bool:
        return abs(self.net_delta) < 5


def apply_position_sign(greek: OptionGreek, position: OptionPosition) -> PositionGreeks:
    weight = position.sign * position.quantity
    exposures = {name: getattr(greek, name) * weight for name in ("delta", "gamma", "theta", "vega")}
    return PositionGreeks(symbol=position.symbol, option_type=position.option_type, action=position.action,
                          lots=position.lots, quantity=position.quantity, iv=greek.iv, **exposures)


EXPIRY_TIMES = {"NFO": (15, 30), "BFO": (15, 30), "CDS": (12, 30), "MCX": (23, 30)}
_STANDARD_NORMAL = NormalDist()


def _norm_cdf(x: float) -> float:
    return _STANDARD_NORMAL.cdf(x)


def _norm_pdf(x: float) -> float:
    return _STANDARD_NORMAL.pdf(x)


def _option_value(flag: str, spot: float, strike: float, years: float, rate: float, volatility: float) -> float:
    direction = 1 if flag == "c" else -1
    if years <= 0 or volatility <= 0 or min(spot, strike) <= 0:
        return max(direction * (spot - strike), 0)
    dispersion = volatility * math.sqrt(years)
    pivot = (math.log(spot / strike) + rate * years) / dispersion
    upper, lower = pivot + dispersion / 2, pivot - dispersion / 2
    discounted_strike = strike * math.exp(-rate * years)
    return direction * (spot * _norm_cdf(direction * upper) - discounted_strike * _norm_cdf(direction * lower))


def _bs_greeks(flag: str, S: float, K: float, T: float, r: float, sigma: float) -> OptionGreek:
    """Derivatives of the local option value; theta/day and vega/IV point."""
    if min(S, K, T, sigma) <= 0:
        return OptionGreek(iv=sigma * 100)
    direction = 1 if flag == "c" else -1
    root_time = math.sqrt(T)
    dispersion = sigma * root_time
    pivot = (math.log(S / K) + r * T) / dispersion
    upper, lower = pivot + dispersion / 2, pivot - dispersion / 2
    density = _norm_pdf(upper)
    time_decay = -S * density * sigma / (2 * root_time)
    rate_decay = -direction * r * K * math.exp(-r * T) * _norm_cdf(direction * lower)
    return OptionGreek(delta=round(direction * _norm_cdf(direction * upper), 4),
                       gamma=round(density / (S * dispersion), 6),
                       theta=round((time_decay + rate_decay) / 365, 2),
                       vega=round(S * density * root_time / 100, 2), iv=round(sigma * 100, 2))


class PortfolioGreeks:
    """Aggregate supplied native observations without guessing missing transport."""

    def __init__(self, client: BrokerClient | None = None) -> None:
        self._client = client

    def _fetch_greeks(self, positions: list[OptionPosition]) -> dict[str, OptionGreek]:
        if not positions:
            return {}
        raise RuntimeError("Native portfolio Greeks require an admitted typed snapshot")

    def calculate(self, positions: list[OptionPosition],
                  greeks_override: dict[str, OptionGreek] | None = None) -> PortfolioGreeksResult:
        observations = (greeks_override if greeks_override is not None else
                        self._fetch_greeks(positions) if self._client is not None else {})
        scaled = [apply_position_sign(observations.get(position.symbol, OptionGreek()), position) for position in positions]
        totals = {f"net_{name}": math.fsum(getattr(position, name) for position in scaled)
                  for name in ("delta", "gamma", "theta", "vega")}
        return PortfolioGreeksResult(positions=scaled, **totals)

    @staticmethod
    def from_lot_size(underlying: str, lots: int = 1) -> int:
        return lots * LOT_SIZES.get(underlying.upper(), 1)

    @staticmethod
    def local_greeks(option_type: str, spot: float, strike: float, time_to_expiry: float,
                     risk_free_rate: float = 0.07, iv: float = 0.20) -> OptionGreek:
        return _bs_greeks("c" if option_type.upper() == "CE" else "p", spot, strike,
                          time_to_expiry, risk_free_rate, iv)
