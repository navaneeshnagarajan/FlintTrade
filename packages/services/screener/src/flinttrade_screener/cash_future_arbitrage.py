"""Cash-future / cross-exchange arbitrage scanner (DP3).

Extends the single-instrument basis primitives in :mod:`synthetic_future`
(``cost_of_carry`` / ``implied_basis``) into a *universe scanner* that ranks
arbitrage opportunities across many underlyings:

  * **Cash-future basis** — for each underlying the observed basis
    (future − spot) is compared against the theoretical fair basis
    (cost-of-carry at the risk-free rate). The deviation is the mispricing; its
    annualised return says whether a cash-and-carry (buy spot / sell future) or
    reverse (sell spot / buy future) trade clears the funding cost.
  * **Cross-exchange** — for a dual-listed scrip the NSE vs BSE price gap is
    surfaced as a same-instrument spatial arbitrage.

All computation is pure — the caller supplies the observed prices (from the
connected registry's quotes, or a sample set in demo mode). No broker calls
live here, so the scanner is fully deterministic and testable.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

# A cash-and-carry only counts as an opportunity once the annualised edge over
# the funding rate clears this threshold (percentage points) — below it the
# basis is just normal cost-of-carry, not a tradeable dislocation.
_DEFAULT_EDGE_THRESHOLD_PCT = 1.0

_DAYS_PER_YEAR = 365.0


@dataclass
class CashFutureOpportunity:
    """A single cash-future basis dislocation."""

    underlying: str = ""
    exchange: str = ""
    spot: float = 0.0
    future_price: float = 0.0
    days_to_expiry: int = 0
    basis: float = 0.0
    basis_pct: float = 0.0
    fair_basis: float = 0.0
    mispricing: float = 0.0
    annualised_return_pct: float = 0.0
    signal: str = "fair"  # cash_and_carry | reverse | fair

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return asdict(self)


@dataclass
class CrossExchangeOpportunity:
    """A same-instrument price gap across two exchanges."""

    symbol: str = ""
    exchange_a: str = ""
    price_a: float = 0.0
    exchange_b: str = ""
    price_b: float = 0.0
    spread: float = 0.0
    spread_pct: float = 0.0
    buy_on: str = ""
    sell_on: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return asdict(self)


@dataclass
class ArbitrageScanResult:
    """Ranked arbitrage scan across both dimensions."""

    risk_free_rate: float = 0.07
    edge_threshold_pct: float = _DEFAULT_EDGE_THRESHOLD_PCT
    cash_future: list[CashFutureOpportunity] = field(default_factory=list)
    cross_exchange: list[CrossExchangeOpportunity] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dictionary."""
        return {
            "risk_free_rate": self.risk_free_rate,
            "edge_threshold_pct": self.edge_threshold_pct,
            "cash_future": [o.to_dict() for o in self.cash_future],
            "cross_exchange": [o.to_dict() for o in self.cross_exchange],
        }


def _fair_basis(spot: float, days_to_expiry: int, risk_free_rate: float) -> float:
    """Theoretical cost-of-carry basis = spot * (e^(r·t) − 1)."""
    t = max(days_to_expiry, 0) / _DAYS_PER_YEAR
    return spot * (math.exp(risk_free_rate * t) - 1)


def evaluate_cash_future(
    underlying: str,
    spot: float,
    future_price: float,
    days_to_expiry: int,
    risk_free_rate: float = 0.07,
    exchange: str = "NFO",
    edge_threshold_pct: float = _DEFAULT_EDGE_THRESHOLD_PCT,
) -> CashFutureOpportunity | None:
    """Evaluate one underlying's cash-future basis dislocation.

    Args:
        underlying: Underlying symbol.
        spot: Cash/spot price.
        future_price: Near-month futures price.
        days_to_expiry: Calendar days to the futures expiry.
        risk_free_rate: Annualised funding rate as a decimal.
        exchange: Futures exchange code.
        edge_threshold_pct: Minimum annualised edge over funding to flag.

    Returns:
        A :class:`CashFutureOpportunity`, or None if the inputs are unusable
        (non-positive prices).
    """
    if spot <= 0 or future_price <= 0 or days_to_expiry < 0:
        return None

    basis = future_price - spot
    fair = _fair_basis(spot, days_to_expiry, risk_free_rate)
    mispricing = basis - fair
    basis_pct = basis / spot * 100.0

    # Annualised return of capturing the *whole* basis to expiry via
    # cash-and-carry (the raw carry yield), for ranking the dislocation.
    t = max(days_to_expiry, 1) / _DAYS_PER_YEAR
    annualised_return_pct = (basis / spot) / t * 100.0

    # Signal: the annualised edge is the carry yield net of the funding rate.
    edge_pct = annualised_return_pct - risk_free_rate * 100.0
    if edge_pct >= edge_threshold_pct:
        signal = "cash_and_carry"  # future rich vs carry → buy spot, sell future
    elif edge_pct <= -edge_threshold_pct:
        signal = "reverse"  # future cheap vs carry → sell spot, buy future
    else:
        signal = "fair"

    return CashFutureOpportunity(
        underlying=underlying,
        exchange=exchange,
        spot=round(spot, 2),
        future_price=round(future_price, 2),
        days_to_expiry=days_to_expiry,
        basis=round(basis, 2),
        basis_pct=round(basis_pct, 3),
        fair_basis=round(fair, 2),
        mispricing=round(mispricing, 2),
        annualised_return_pct=round(annualised_return_pct, 2),
        signal=signal,
    )


def evaluate_cross_exchange(
    symbol: str,
    exchange_a: str,
    price_a: float,
    exchange_b: str,
    price_b: float,
) -> CrossExchangeOpportunity | None:
    """Evaluate a same-instrument price gap between two exchanges."""
    if price_a <= 0 or price_b <= 0:
        return None
    spread = abs(price_a - price_b)
    mid = (price_a + price_b) / 2.0
    spread_pct = spread / mid * 100.0 if mid > 0 else 0.0
    # Buy where cheaper, sell where dearer.
    if price_a <= price_b:
        buy_on, sell_on = exchange_a, exchange_b
    else:
        buy_on, sell_on = exchange_b, exchange_a
    return CrossExchangeOpportunity(
        symbol=symbol,
        exchange_a=exchange_a,
        price_a=round(price_a, 2),
        exchange_b=exchange_b,
        price_b=round(price_b, 2),
        spread=round(spread, 2),
        spread_pct=round(spread_pct, 3),
        buy_on=buy_on,
        sell_on=sell_on,
    )


def scan_arbitrage(
    cash_future_rows: list[dict[str, Any]] | None = None,
    cross_exchange_rows: list[dict[str, Any]] | None = None,
    risk_free_rate: float = 0.07,
    edge_threshold_pct: float = _DEFAULT_EDGE_THRESHOLD_PCT,
) -> ArbitrageScanResult:
    """Scan a universe for cash-future and cross-exchange arbitrage.

    Args:
        cash_future_rows: Rows of ``{underlying, spot, future_price,
            days_to_expiry, exchange?}``.
        cross_exchange_rows: Rows of ``{symbol, exchange_a, price_a,
            exchange_b, price_b}``.
        risk_free_rate: Annualised funding rate as a decimal.
        edge_threshold_pct: Minimum annualised edge over funding to flag a
            cash-future signal (still ranks all rows).

    Returns:
        An :class:`ArbitrageScanResult` with both lists ranked by dislocation
        size (absolute annualised edge; absolute spread percentage).
    """
    cf: list[CashFutureOpportunity] = []
    for row in cash_future_rows or []:
        opp = evaluate_cash_future(
            underlying=str(row.get("underlying", "")),
            spot=float(row.get("spot", 0) or 0),
            future_price=float(row.get("future_price", 0) or 0),
            days_to_expiry=int(row.get("days_to_expiry", 0) or 0),
            risk_free_rate=risk_free_rate,
            exchange=str(row.get("exchange", "NFO")),
            edge_threshold_pct=edge_threshold_pct,
        )
        if opp is not None:
            cf.append(opp)
    cf.sort(key=lambda o: abs(o.annualised_return_pct - risk_free_rate * 100.0), reverse=True)

    cx: list[CrossExchangeOpportunity] = []
    for row in cross_exchange_rows or []:
        opp = evaluate_cross_exchange(
            symbol=str(row.get("symbol", "")),
            exchange_a=str(row.get("exchange_a", "")),
            price_a=float(row.get("price_a", 0) or 0),
            exchange_b=str(row.get("exchange_b", "")),
            price_b=float(row.get("price_b", 0) or 0),
        )
        if opp is not None:
            cx.append(opp)
    cx.sort(key=lambda o: o.spread_pct, reverse=True)

    return ArbitrageScanResult(
        risk_free_rate=risk_free_rate,
        edge_threshold_pct=edge_threshold_pct,
        cash_future=cf,
        cross_exchange=cx,
    )


def make_sample_arbitrage_scan() -> ArbitrageScanResult:
    """Synthetic arbitrage scan for demo/disconnected mode."""
    cash_future_rows = [
        {"underlying": "RELIANCE", "spot": 2850.0, "future_price": 2872.0, "days_to_expiry": 12, "exchange": "NFO"},
        {"underlying": "NIFTY", "spot": 24000.0, "future_price": 24055.0, "days_to_expiry": 5, "exchange": "NFO"},
        {"underlying": "HDFCBANK", "spot": 1680.0, "future_price": 1682.5, "days_to_expiry": 12, "exchange": "NFO"},
        {"underlying": "TATASTEEL", "spot": 165.0, "future_price": 164.2, "days_to_expiry": 12, "exchange": "NFO"},
    ]
    cross_exchange_rows = [
        {"symbol": "RELIANCE", "exchange_a": "NSE", "price_a": 2850.0, "exchange_b": "BSE", "price_b": 2851.4},
        {"symbol": "TATASTEEL", "exchange_a": "NSE", "price_a": 165.0, "exchange_b": "BSE", "price_b": 164.8},
    ]
    return scan_arbitrage(cash_future_rows, cross_exchange_rows)
