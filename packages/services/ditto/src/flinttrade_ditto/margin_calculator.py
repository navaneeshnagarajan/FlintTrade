"""Margin calculator — per-account margin requirements and availability.

Absorbs AlgoMirror's margin_calculator.py patterns. Fetches margin info from
each account's OpenAlgo instance and calculates whether orders can be placed.
Supports all product types (CNC, MIS, NRML) and all exchanges.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from .account_manager import BrokerAccount

logger = logging.getLogger("flinttrade.ditto.margin")


# MIS margin multipliers (approximate — actual varies by broker/exchange)
_MIS_MARGIN_PCT: dict[str, float] = {
    "NSE": 20.0,   # ~5x leverage for equity intraday
    "BSE": 20.0,
    "NFO": 15.0,   # ~6-7x for F&O
    "BFO": 15.0,
    "CDS": 5.0,    # ~20x for currency
    "BCD": 5.0,
    "MCX": 10.0,   # ~10x for commodities
    "NCDEX": 10.0,
}


@dataclass
class MarginInfo:
    """Margin information for a single account."""

    account_id: str
    available_balance: float = 0.0
    used_margin: float = 0.0
    total_balance: float = 0.0
    utilization_pct: float = 0.0

    @property
    def free_margin(self) -> float:
        return max(0, self.available_balance)


@dataclass
class OrderMarginEstimate:
    """Estimated margin requirement for a proposed order."""

    symbol: str = ""
    exchange: str = ""
    product: str = ""
    quantity: int = 0
    price: float = 0.0
    estimated_margin: float = 0.0
    margin_from_api: float | None = None  # If broker provides actual margin


@dataclass
class MultiLegMarginResult:
    """Margin for multi-leg positions with hedge benefit."""

    legs: list[OrderMarginEstimate] = field(default_factory=list)
    gross_margin: float = 0.0
    hedge_benefit: float = 0.0
    net_margin: float = 0.0

    @property
    def benefit_pct(self) -> float:
        if self.gross_margin <= 0:
            return 0.0
        return (self.hedge_benefit / self.gross_margin) * 100


class MarginCalculator:
    """Calculate and check margin requirements across accounts.

    Usage::

        calc = MarginCalculator()
        info = calc.get_margin_info(account)
        estimate = calc.estimate_order_margin("NIFTY", "NFO", "NRML", 75, 24000)
        can_trade = calc.has_sufficient_margin(account, estimate.estimated_margin)
    """

    # ------------------------------------------------------------------
    # Fetch margin from OpenAlgo
    # ------------------------------------------------------------------

    @staticmethod
    def get_margin_info(account: BrokerAccount) -> MarginInfo:
        """Fetch available margin for an account via OpenAlgo /api/v1/funds."""
        result = MarginInfo(account_id=account.account_id)
        url = f"{account.openalgo_host.rstrip('/')}/api/v1/funds"
        try:
            with httpx.Client(timeout=10.0) as http:
                resp = http.post(url, json={"apikey": account.api_key})
                if resp.status_code == 200:
                    data = resp.json()
                    result.available_balance = float(data.get("available_balance", 0))
                    result.used_margin = float(data.get("used_margin", 0))
                    result.total_balance = float(data.get("total_balance", 0))
                    if result.total_balance > 0:
                        result.utilization_pct = (result.used_margin / result.total_balance) * 100
        except Exception as exc:
            logger.error("Margin fetch failed for %s: %s", account.account_id, exc)

        return result

    @staticmethod
    def get_margin_info_batch(accounts: list[BrokerAccount]) -> dict[str, MarginInfo]:
        """Fetch margin for multiple accounts. Returns {account_id: MarginInfo}."""
        return {
            acc.account_id: MarginCalculator.get_margin_info(acc)
            for acc in accounts
            if acc.enabled
        }

    # ------------------------------------------------------------------
    # Estimate margin
    # ------------------------------------------------------------------

    @staticmethod
    def estimate_order_margin(
        symbol: str,
        exchange: str,
        product: str,
        quantity: int,
        price: float,
    ) -> OrderMarginEstimate:
        """Estimate margin required for a single order.

        For NRML F&O, margin is the full notional.
        For MIS, margin is reduced by the exchange-specific multiplier.
        For CNC, margin is the full order value.
        """
        notional = quantity * price

        if product == "CNC":
            margin = notional
        elif product == "MIS":
            pct = _MIS_MARGIN_PCT.get(exchange, 100.0)
            margin = notional * (pct / 100)
        elif product == "NRML":
            # NRML for F&O: SPAN + exposure margin (~15-20% of notional)
            if exchange in ("NFO", "BFO", "CDS", "MCX"):
                margin = notional * 0.15
            else:
                margin = notional
        else:
            margin = notional

        return OrderMarginEstimate(
            symbol=symbol,
            exchange=exchange,
            product=product,
            quantity=quantity,
            price=price,
            estimated_margin=margin,
        )

    @staticmethod
    def estimate_order_margin_api(
        account: BrokerAccount,
        positions: list[dict[str, Any]],
    ) -> float:
        """Get exact margin from OpenAlgo /api/v1/margin endpoint.

        The positions list follows the OpenAlgo margin API format.
        """
        url = f"{account.openalgo_host.rstrip('/')}/api/v1/margin"
        try:
            with httpx.Client(timeout=10.0) as http:
                resp = http.post(url, json={
                    "apikey": account.api_key,
                    "positions": positions,
                })
                if resp.status_code == 200:
                    data = resp.json()
                    return float(data.get("required_margin", data.get("margin", 0)))
        except Exception as exc:
            logger.error("Margin API call failed for %s: %s", account.account_id, exc)
        return 0.0

    # ------------------------------------------------------------------
    # Multi-leg margin with hedge benefit
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_multi_leg_margin(
        legs: list[dict[str, Any]],
    ) -> MultiLegMarginResult:
        """Calculate margin for a multi-leg position with hedge benefit.

        Each leg: {"symbol", "exchange", "product", "quantity", "price", "action"}
        Hedge benefit applies when there are opposing legs (e.g., bull spread).
        """
        estimates: list[OrderMarginEstimate] = []
        gross = 0.0

        for leg in legs:
            est = MarginCalculator.estimate_order_margin(
                symbol=leg.get("symbol", ""),
                exchange=leg.get("exchange", "NFO"),
                product=leg.get("product", "NRML"),
                quantity=int(leg.get("quantity", 0)),
                price=float(leg.get("price", 0)),
            )
            estimates.append(est)
            gross += est.estimated_margin

        # Hedge benefit: if there are both BUY and SELL legs, reduce margin
        actions = [leg.get("action", "").upper() for leg in legs]
        has_buy = "BUY" in actions
        has_sell = "SELL" in actions
        benefit = 0.0

        if has_buy and has_sell and len(legs) >= 2:
            # Approximate: hedged positions get ~60% margin benefit
            benefit = gross * 0.60
            # Cap benefit — can't reduce below the max single-leg margin
            max_single = max(e.estimated_margin for e in estimates) if estimates else 0
            benefit = min(benefit, gross - max_single)

        return MultiLegMarginResult(
            legs=estimates,
            gross_margin=gross,
            hedge_benefit=benefit,
            net_margin=gross - benefit,
        )

    # ------------------------------------------------------------------
    # Sufficiency check
    # ------------------------------------------------------------------

    @staticmethod
    def has_sufficient_margin(
        account: BrokerAccount,
        required_margin: float,
        margin_info: MarginInfo | None = None,
    ) -> bool:
        """Check if an account has enough margin for a trade."""
        info = margin_info or MarginCalculator.get_margin_info(account)
        return info.free_margin >= required_margin

    @staticmethod
    def max_affordable_quantity(
        available_margin: float,
        price: float,
        exchange: str = "NSE",
        product: str = "MIS",
    ) -> int:
        """Calculate maximum affordable quantity given available margin."""
        if price <= 0 or available_margin <= 0:
            return 0

        if product == "CNC":
            margin_per_unit = price
        elif product == "MIS":
            pct = _MIS_MARGIN_PCT.get(exchange, 100.0)
            margin_per_unit = price * (pct / 100)
        elif product == "NRML":
            if exchange in ("NFO", "BFO", "CDS", "MCX"):
                margin_per_unit = price * 0.15
            else:
                margin_per_unit = price
        else:
            margin_per_unit = price

        return int(available_margin / margin_per_unit) if margin_per_unit > 0 else 0
