"""Portfolio-level Greeks calculator.

Adapts openalgo-portfoliogreeks patterns. Supports:
- Fetching Greeks via OpenAlgo /api/v1/optiongreeks and /api/v1/multioptiongreeks
- Position-aware signs: BUY CE = +delta, SELL CE = -delta, BUY PE = -delta, SELL PE = +delta
- Aggregate Delta, Gamma, Theta, Vega across entire portfolio
- Lot-based calculations (NIFTY=75, BANKNIFTY=30, etc.)
- Local Black-Scholes via py_vollib_vectorized when API is slow
- Exchange-specific expiry times: MCX 23:30, CDS 12:30 PM
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

from flinttrade_core.models import OptionGreek
from flinttrade_core.openalgo_client import OpenAlgoClient

from .option_chain import LOT_SIZES

logger = logging.getLogger("flinttrade.screener.greeks")


@dataclass
class OptionPosition:
    """A single option position for Greeks calculation."""

    symbol: str                     # e.g. "NIFTY26MAR2524000CE"
    exchange: str = "NFO"
    option_type: str = "CE"         # "CE" or "PE"
    action: str = "BUY"             # "BUY" or "SELL"
    lots: int = 1
    lot_size: int = 75              # Per lot
    underlying: str = ""            # e.g. "NIFTY" for lot size lookup

    @property
    def quantity(self) -> int:
        return self.lots * self.lot_size

    @property
    def sign(self) -> int:
        """Position sign: +1 for long, -1 for short."""
        return 1 if self.action.upper() == "BUY" else -1


@dataclass
class PositionGreeks:
    """Greeks for a single position (quantity-adjusted, sign-adjusted)."""

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
    """Aggregate Greeks across all positions."""

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
        """Roughly delta-neutral if |net_delta| < 5."""
        return abs(self.net_delta) < 5.0


def apply_position_sign(
    greek: OptionGreek,
    position: OptionPosition,
) -> PositionGreeks:
    """Apply position-aware signs and lot scaling to raw Greeks.

    Sign rules:
    - BUY CE: delta=+, gamma=+, theta=-, vega=+
    - SELL CE: delta=-, gamma=-, theta=+, vega=-
    - BUY PE: delta=- (PE delta is already negative from API), gamma=+, theta=-, vega=+
    - SELL PE: delta=+ (flip negative PE delta), gamma=-, theta=+, vega=-

    The OpenAlgo API returns raw per-unit Greeks. We multiply by quantity
    and apply the buy/sell sign.
    """
    sign = position.sign
    qty = position.quantity

    return PositionGreeks(
        symbol=position.symbol,
        option_type=position.option_type,
        action=position.action,
        lots=position.lots,
        quantity=qty,
        delta=greek.delta * qty * sign,
        gamma=greek.gamma * qty * sign,
        theta=greek.theta * qty * sign,
        vega=greek.vega * qty * sign,
        iv=greek.iv,
    )


# Exchange-specific expiry times (hour, minute) in IST
EXPIRY_TIMES: dict[str, tuple[int, int]] = {
    "NFO": (15, 30),    # 3:30 PM
    "BFO": (15, 30),    # 3:30 PM
    "CDS": (12, 30),    # 12:30 PM
    "MCX": (23, 30),    # 11:30 PM
}


class PortfolioGreeks:
    """Portfolio-level Greeks aggregator.

    Usage::

        pg = PortfolioGreeks(client)
        positions = [
            OptionPosition(symbol="NIFTY26MAR2524000CE", action="SELL", lots=2, lot_size=75),
            OptionPosition(symbol="NIFTY26MAR2524000PE", action="SELL", lots=2, lot_size=75),
        ]
        result = pg.calculate(positions)
        print(f"Net delta: {result.net_delta}, Net theta: {result.net_theta}")
    """

    def __init__(self, client: OpenAlgoClient | None = None) -> None:
        self._client = client

    def calculate(
        self,
        positions: list[OptionPosition],
        greeks_override: dict[str, OptionGreek] | None = None,
    ) -> PortfolioGreeksResult:
        """Calculate aggregate Greeks for a portfolio.

        Args:
            positions: list of option positions.
            greeks_override: optional pre-fetched Greeks keyed by symbol.
                If not provided, fetches from API.
        """
        if greeks_override:
            greeks_map = greeks_override
        elif self._client:
            greeks_map = self._fetch_greeks(positions)
        else:
            greeks_map = {}

        result = PortfolioGreeksResult()

        for pos in positions:
            greek = greeks_map.get(pos.symbol, OptionGreek())
            pg = apply_position_sign(greek, pos)
            result.positions.append(pg)
            result.net_delta += pg.delta
            result.net_gamma += pg.gamma
            result.net_theta += pg.theta
            result.net_vega += pg.vega

        logger.info(
            "Portfolio Greeks: %d positions, delta=%.1f gamma=%.2f theta=%.1f vega=%.1f",
            result.position_count, result.net_delta,
            result.net_gamma, result.net_theta, result.net_vega,
        )
        return result

    def _fetch_greeks(
        self, positions: list[OptionPosition],
    ) -> dict[str, OptionGreek]:
        """Fetch Greeks from OpenAlgo API for all positions."""
        if not self._client or not positions:
            return {}

        symbols = [
            {"symbol": p.symbol, "exchange": p.exchange}
            for p in positions
        ]

        try:
            greeks_list = self._client.multi_option_greeks(symbols)
            return {g.symbol: g for g in greeks_list}
        except Exception as exc:
            logger.warning("Batch Greeks fetch failed, falling back to individual: %s", exc)

        # Fallback: fetch individually
        result: dict[str, OptionGreek] = {}
        for pos in positions:
            try:
                g = self._client.option_greeks(pos.symbol, pos.exchange)
                result[pos.symbol] = g
            except Exception as exc:
                logger.error("Greeks fetch failed for %s: %s", pos.symbol, exc)
        return result

    @staticmethod
    def from_lot_size(underlying: str, lots: int = 1) -> int:
        """Get total quantity from underlying name and lots."""
        lot_size = LOT_SIZES.get(underlying.upper(), 1)
        return lots * lot_size

    # ------------------------------------------------------------------
    # Local Black-Scholes via py_vollib_vectorized
    # ------------------------------------------------------------------

    @staticmethod
    def local_greeks(
        option_type: str,
        spot: float,
        strike: float,
        time_to_expiry: float,
        risk_free_rate: float = 0.07,
        iv: float = 0.20,
    ) -> OptionGreek:
        """Calculate Greeks locally using py_vollib_vectorized.

        Falls back to a basic Black-Scholes if the library is unavailable.

        Args:
            option_type: "CE" or "PE"
            spot: underlying spot price
            strike: strike price
            time_to_expiry: years to expiry (e.g. 7/365 for 7 days)
            risk_free_rate: annualized risk-free rate (default 7% for India)
            iv: implied volatility as decimal (0.20 = 20%)
        """
        flag = "c" if option_type.upper() == "CE" else "p"

        try:
            from py_vollib_vectorized import vectorized_implied_volatility as viv  # noqa: F401
            from py_vollib_vectorized.api import price, delta, gamma, theta, vega  # noqa: F401

            d = delta(flag, spot, strike, time_to_expiry, risk_free_rate, iv, model="black_scholes")
            g = gamma(flag, spot, strike, time_to_expiry, risk_free_rate, iv, model="black_scholes")
            t = theta(flag, spot, strike, time_to_expiry, risk_free_rate, iv, model="black_scholes")
            v = vega(flag, spot, strike, time_to_expiry, risk_free_rate, iv, model="black_scholes")

            return OptionGreek(delta=d, gamma=g, theta=t, vega=v, iv=iv * 100)
        except ImportError:
            pass

        # Fallback: manual Black-Scholes
        return _bs_greeks(flag, spot, strike, time_to_expiry, risk_free_rate, iv)


def _bs_greeks(
    flag: str,
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
) -> OptionGreek:
    """Basic Black-Scholes Greeks (fallback when py_vollib unavailable)."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return OptionGreek(iv=sigma * 100)

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    nd1 = _norm_cdf(d1)
    nd2 = _norm_cdf(d2)
    npd1 = _norm_pdf(d1)

    if flag == "c":
        delta = nd1
        theta = (
            (-S * npd1 * sigma / (2 * math.sqrt(T)))
            - r * K * math.exp(-r * T) * nd2
        ) / 365
    else:
        delta = nd1 - 1
        theta = (
            (-S * npd1 * sigma / (2 * math.sqrt(T)))
            + r * K * math.exp(-r * T) * _norm_cdf(-d2)
        ) / 365

    gamma = npd1 / (S * sigma * math.sqrt(T))
    vega = S * npd1 * math.sqrt(T) / 100  # per 1% IV move

    return OptionGreek(
        delta=round(delta, 4),
        gamma=round(gamma, 6),
        theta=round(theta, 2),
        vega=round(vega, 2),
        iv=round(sigma * 100, 2),
    )


def _norm_cdf(x: float) -> float:
    """Standard normal CDF approximation."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)
