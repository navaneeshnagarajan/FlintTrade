"""OBV Divergence strategy — Volume category.

On Balance Volume (OBV) accumulates volume directionally.
OBV divergence from price signals potential reversals.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.volume_obv_divergence")


def on_balance_volume(closes: list[float], volumes: list[int]) -> list[float]:
    """On Balance Volume indicator.

    Args:
        closes: Close prices.
        volumes: Bar volumes.

    Returns:
        Cumulative OBV series.
    """
    n = len(closes)
    obv: list[float] = [0.0] * n
    for i in range(1, n):
        if closes[i] > closes[i - 1]:
            obv[i] = obv[i - 1] + volumes[i]
        elif closes[i] < closes[i - 1]:
            obv[i] = obv[i - 1] - volumes[i]
        else:
            obv[i] = obv[i - 1]
    return obv


class OBVDivergence(BaseStrategy, _BacktestStrategyMixin):
    """OBV price divergence strategy.

    Bullish divergence: price lower low, OBV higher low → buy.
    Bearish divergence: price higher high, OBV lower high → sell.
    Uses a rolling lookback window for peak/trough detection.

    Args:
        lookback: Bars to scan for divergence (default 10).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "OBVDivergence",
        exchange: str = "NSE",
        product: str = "MIS",
        lookback: int = 10,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.lookback = lookback
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        min_bars = self.lookback + 2
        if len(self._closes) < min_bars:
            return

        obv = on_balance_volume(self._closes, self._volumes)
        lb = self.lookback

        prices = self._closes
        price_window = prices[-lb - 1:-1]
        obv_window = obv[-lb - 1:-1]

        # Bullish divergence: price lower low, OBV higher low
        price_ll = prices[-1] < min(price_window)
        obv_hl = obv[-1] > min(obv_window)
        if price_ll and obv_hl and self._position <= 0:
            self._buy()

        # Bearish divergence: price higher high, OBV lower high
        price_hh = prices[-1] > max(price_window)
        obv_lh = obv[-1] < max(obv_window)
        if price_hh and obv_lh and self._position >= 0:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
