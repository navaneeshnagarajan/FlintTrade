"""RSI Overbought/Oversold strategy — Momentum category.

Classic mean-reversion/momentum RSI approach:
- Buy when RSI crosses above oversold threshold (momentum turns up).
- Sell when RSI crosses below overbought threshold (momentum turns down).

Also includes RSIDivergence: detects price/RSI divergence for contrarian signals.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import rsi
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.momentum_rsi")


class RSIMomentum(BaseStrategy, _BacktestStrategyMixin):
    """RSI crossover momentum strategy.

    Buy on RSI crossing up through oversold; sell on crossing down through overbought.

    Args:
        period: RSI lookback period (default 14).
        oversold: RSI level to trigger buy (default 30).
        overbought: RSI level to trigger sell (default 70).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "RSIMomentum",
        exchange: str = "NSE",
        product: str = "MIS",
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        if len(self._closes) < self.period + 2:
            return
        rsi_vals = rsi(self._closes, self.period)
        # Crossed above oversold → momentum turning up
        if rsi_vals[-1] > self.oversold and rsi_vals[-2] <= self.oversold:
            self._buy()
        # Crossed below overbought → momentum turning down
        elif rsi_vals[-1] < self.overbought and rsi_vals[-2] >= self.overbought:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


class RSIDivergence(BaseStrategy, _BacktestStrategyMixin):
    """RSI price divergence strategy.

    Detects bullish divergence (price makes lower low but RSI higher low)
    and bearish divergence (price higher high but RSI lower high).
    Uses a simple 2-bar divergence window for efficiency.

    Args:
        period: RSI period (default 14).
        lookback: Bars to look back for divergence (default 5).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "RSIDivergence",
        exchange: str = "NSE",
        product: str = "MIS",
        period: int = 14,
        lookback: int = 5,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.period = period
        self.lookback = lookback
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        min_bars = self.period + self.lookback + 2
        if len(self._closes) < min_bars:
            return

        rsi_vals = rsi(self._closes, self.period)
        prices = self._closes

        lb = self.lookback
        # Bullish divergence: price lower low, RSI higher low
        price_ll = prices[-1] < min(prices[-lb - 1: -1])
        rsi_hl = rsi_vals[-1] > min(rsi_vals[-lb - 1: -1])
        if price_ll and rsi_hl and self._position <= 0:
            self._buy()

        # Bearish divergence: price higher high, RSI lower high
        price_hh = prices[-1] > max(prices[-lb - 1: -1])
        rsi_lh = rsi_vals[-1] < max(rsi_vals[-lb - 1: -1])
        if price_hh and rsi_lh and self._position >= 0:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
