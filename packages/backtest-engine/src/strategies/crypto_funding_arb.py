"""Crypto Funding Rate Arbitrage strategy.

Captures the funding rate differential between perpetual futures and spot.
When funding rate is positive (longs pay shorts), go short perp + long spot.
When funding rate is negative (shorts pay longs), go long perp + short spot.

No market open/close checks — 24/7 market.
Funding rate is injected via set_funding_rate() every 8 hours.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.crypto_funding_arb")


class CryptoFundingArb(BaseStrategy, _BacktestStrategyMixin):
    """Funding rate arbitrage for perpetual futures vs spot.

    Takes the opposing side of the funding payment. Position is held until
    funding rate flips or the position decays below exit_threshold.

    24/7 market: no session-time checks.

    Args:
        entry_rate_pct: Minimum absolute funding rate % to enter (default 0.01).
        exit_rate_pct: Exit when rate drops below this (default 0.005).
        symbol: Perp instrument symbol.
    """

    def __init__(
        self,
        name: str = "CryptoFundingArb",
        exchange: str = "NSE",
        product: str = "MIS",
        entry_rate_pct: float = 0.01,
        exit_rate_pct: float = 0.005,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.entry_rate_pct = entry_rate_pct
        self.exit_rate_pct = exit_rate_pct
        self._symbol = symbol
        self._init_history()
        self._funding_rate: float = 0.0  # current 8h funding rate


    def set_funding_rate(self, rate_pct: float) -> None:
        """Update current funding rate.

        Args:
            rate_pct: Funding rate as % per 8h period. Positive = longs pay shorts.
        """
        self._funding_rate = rate_pct
        logger.debug("Funding rate updated: %.4f%%", rate_pct)

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)

        rate = self._funding_rate

        # Exit if rate dropped below threshold
        if self._position != 0 and abs(rate) < self.exit_rate_pct:
            if self._position > 0:
                self._sell()
            else:
                self._buy()
                self._flat()
            return

        if self._position == 0:
            if rate >= self.entry_rate_pct:
                # High positive rate: longs are paying → go short perp
                self._sell()
            elif rate <= -self.entry_rate_pct:
                # High negative rate: shorts are paying → go long perp
                self._buy()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["CryptoFundingArb"]
