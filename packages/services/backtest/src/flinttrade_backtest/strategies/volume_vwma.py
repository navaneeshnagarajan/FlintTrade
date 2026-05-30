"""VWMA (Volume-Weighted Moving Average) crossover strategy — Volume category.

The VWMA weights each bar's price by its volume, so high-volume bars carry
more influence than low-volume ones. This makes VWMA "sticky" near institutional
accumulation/distribution levels.

Trading rules:
    BUY  when close > VWMA (price above volume-weighted center of gravity).
    SELL when close < VWMA (price falls below volume-weighted support).
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.volume_vwma")


def vwma(prices: list[float], volumes: list[int], period: int) -> list[float]:
    """Volume-Weighted Moving Average.

    Args:
        prices: Close (or typical) price series.
        volumes: Volume series (same length as prices).
        period: Rolling window size.

    Returns:
        VWMA series; leading values where window is incomplete are 0.0.
    """
    n = len(prices)
    if n < period:
        return [0.0] * n
    result: list[float] = [0.0] * (period - 1)
    for i in range(period - 1, n):
        price_vol = sum(
            prices[i - period + 1 + j] * volumes[i - period + 1 + j]
            for j in range(period)
        )
        vol_sum = sum(volumes[i - period + 1: i + 1])
        result.append(price_vol / vol_sum if vol_sum > 0 else prices[i])
    return result


class VWMACrossover(BaseStrategy, _BacktestStrategyMixin):
    """VWMA crossover: price above VWMA is bullish, below is bearish.

    Args:
        period: VWMA window size (default 20).
        symbol: Instrument symbol (default "").
        exchange: Exchange code (default "NSE").
        product: Product type (default "MIS").
    """

    def __init__(
        self,
        name: str = "VWMACrossover",
        exchange: str = "NSE",
        product: str = "MIS",
        period: int = 20,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.period = period
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        """Not used — bar-close strategy."""

    def on_bar(self, bar: OHLCV) -> None:
        """Process a completed bar and emit orders on price/VWMA relationship.

        Args:
            bar: The just-closed OHLCV bar.
        """
        if not self.is_active:
            return
        self._record_bar(bar)
        if len(self._closes) < self.period + 1:
            return

        vwma_vals = vwma(self._closes, self._volumes, self.period)
        cur_vwma = vwma_vals[-1]
        prev_vwma = vwma_vals[-2]
        close = self._closes[-1]
        prev_close = self._closes[-2]

        if cur_vwma == 0 or prev_vwma == 0:
            return

        # Cross above VWMA → BUY
        if prev_close <= prev_vwma and close > cur_vwma:
            logger.debug(
                "VWMA cross-up | close=%.2f vwma=%.2f | %s",
                close,
                cur_vwma,
                self._symbol,
            )
            self._buy()
        # Cross below VWMA → SELL
        elif prev_close >= prev_vwma and close < cur_vwma:
            logger.debug(
                "VWMA cross-dn | close=%.2f vwma=%.2f | %s",
                close,
                cur_vwma,
                self._symbol,
            )
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        """Not used — strategy generates its own signals."""

    def generate_orders(self) -> list[Order]:
        """Return and clear all pending orders.

        Returns:
            List of Order objects to submit to the engine.
        """
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
