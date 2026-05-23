"""Commodity Calendar Spread strategy.

Trades the price differential between near-month and far-month commodity futures.
When the spread (near - far) deviates beyond its historical range, trade reversion.

Contango: near < far → spread negative (normal for storable commodities).
Backwardation: near > far → spread positive (supply shortage signal).
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.commodity_spread")


class CommoditySpread(BaseStrategy, _BacktestStrategyMixin):
    """Calendar spread between near and far month commodity futures.

    Near-month bars come via on_bar(); far-month bars via bars_far parameter.
    Enters when spread z-score deviates beyond entry threshold.

    Args:
        lookback: Rolling window for spread statistics (default 40).
        z_entry: Z-score to enter trade (default 1.5).
        z_exit: Z-score to exit (default 0.3).
        symbol: Near-month instrument symbol.
    """

    def __init__(
        self,
        name: str = "CommoditySpread",
        exchange: str = "MCX",
        product: str = "NRML",
        lookback: int = 40,
        z_entry: float = 1.5,
        z_exit: float = 0.3,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.lookback = lookback
        self.z_entry = z_entry
        self.z_exit = z_exit
        self._symbol = symbol
        self._init_history()
        self._far_closes: list[float] = []
        self._spreads: list[float] = []


    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV, bars_far: list[OHLCV] | None = None) -> None:
        self._record_bar(bar)

        if bars_far:
            self._far_closes = [b.close for b in bars_far]

        if not self._far_closes:
            return

        far_close = self._far_closes[min(len(self._closes) - 1, len(self._far_closes) - 1)]
        spread = self._closes[-1] - far_close
        self._spreads.append(spread)

        if len(self._spreads) < self.lookback:
            return

        window = self._spreads[-self.lookback:]
        mean = sum(window) / self.lookback
        std = (sum((s - mean) ** 2 for s in window) / self.lookback) ** 0.5
        z = (spread - mean) / std if std > 0 else 0.0

        if z > self.z_entry and self._position >= 0:
            self._sell()  # spread too wide (near expensive): sell near, buy far
        elif z < -self.z_entry and self._position <= 0:
            self._buy()  # spread too narrow (near cheap): buy near, sell far
        elif abs(z) < self.z_exit and self._position != 0:
            if self._position > 0:
                self._sell()
            else:
                self._buy()
                self._flat()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["CommoditySpread"]
