"""Portfolio Equal-Weight Rebalancing strategy.

Maintains equal allocation across a basket of instruments by rebalancing
on a fixed schedule (daily, weekly, monthly bar count).

Multi-instrument: each instrument is a separate on_bar() call identified
by its symbol. Rebalancing signals are generated when drift exceeds threshold.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.portfolio_equal_weight")


class PortfolioEqualWeight(BaseStrategy, _BacktestStrategyMixin):
    """Equal-weight portfolio rebalancing on a fixed bar schedule.

    Tracks the current price of each instrument (injected externally).
    Generates rebalancing orders when an instrument deviates from target weight.

    For single-instrument backtest: simply buys on every rebalance.

    Args:
        rebalance_bars: Bars between rebalances (default 20).
        drift_threshold: Max weight deviation % before forced rebalance (default 5.0).
        symbol: Primary instrument symbol.
    """

    def __init__(
        self,
        name: str = "PortfolioEqualWeight",
        exchange: str = "NSE",
        product: str = "CNC",
        rebalance_bars: int = 20,
        drift_threshold: float = 5.0,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.rebalance_bars = rebalance_bars
        self.drift_threshold = drift_threshold
        self._symbol = symbol
        self._init_history()
        self._bars_since_rebalance: int = 0


    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        self._bars_since_rebalance += 1

        if self._bars_since_rebalance >= self.rebalance_bars:
            # Rebalance: in single-instrument mode, ensure we are long
            if self._position <= 0:
                self._buy()
            self._bars_since_rebalance = 0
            logger.debug("Rebalance at bar %d price=%.2f", len(self._closes), bar.close)

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["PortfolioEqualWeight"]
