"""MACD Signal strategy — Trend category.

Trades purely on MACD histogram crossover of the zero line,
without the RSI filter present in MACDRSIStrategy.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import macd
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.trend_macd_signal")


class MACDSignal(BaseStrategy, _BacktestStrategyMixin):
    """MACD histogram zero-line crossover strategy.

    Buy when MACD histogram crosses above zero; sell on reverse.
    Uses standard 12/26/9 parameters by default.

    Args:
        fast: Fast EMA period (default 12).
        slow: Slow EMA period (default 26).
        signal: Signal line EMA period (default 9).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "MACDSignal",
        exchange: str = "NSE",
        product: str = "MIS",
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.fast = fast
        self.slow = slow
        self.signal_period = signal
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        min_bars = self.slow + self.signal_period + 1
        if len(self._closes) < min_bars:
            return
        _, _, hist = macd(self._closes, self.fast, self.slow, self.signal_period)
        if hist[-1] > 0 and hist[-2] <= 0:
            self._buy()
        elif hist[-1] < 0 and hist[-2] >= 0:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
