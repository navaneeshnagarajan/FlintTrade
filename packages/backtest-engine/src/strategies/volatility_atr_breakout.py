"""ATR Breakout strategy — Volatility category.

Trades breakouts that exceed ATR-based thresholds from the prior close.
Suitable for trending markets with expanding volatility.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin
from .mean_reversion_keltner import atr

logger = logging.getLogger("flinttrade.backtest.strategies.volatility_atr_breakout")


class ATRBreakout(BaseStrategy, _BacktestStrategyMixin):
    """ATR-based price breakout strategy.

    Buy: close > prev_close + atr_mult * ATR (upward breakout).
    Sell: close < prev_close - atr_mult * ATR (downward breakout).
    Stop-loss placed at atr_sl_mult * ATR below/above entry.

    Args:
        atr_period: ATR calculation period (default 14).
        atr_mult: Breakout multiplier (default 1.5).
        atr_sl_mult: Stop-loss multiplier (default 1.0).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "ATRBreakout",
        exchange: str = "NSE",
        product: str = "MIS",
        atr_period: int = 14,
        atr_mult: float = 1.5,
        atr_sl_mult: float = 1.0,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.atr_period = atr_period
        self.atr_mult = atr_mult
        self.atr_sl_mult = atr_sl_mult
        self._symbol = symbol
        self._init_history()
        self._entry_price: float = 0.0

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        if len(self._closes) < self.atr_period + 2:
            return

        atr_vals = atr(self._highs, self._lows, self._closes, self.atr_period)
        cur_atr = atr_vals[-1]
        prev_close = self._closes[-2]
        close = self._closes[-1]

        if cur_atr == 0:
            return

        up_threshold = prev_close + self.atr_mult * cur_atr
        dn_threshold = prev_close - self.atr_mult * cur_atr

        if self._position == 0:
            if close > up_threshold:
                self._buy()
                self._entry_price = close
            elif close < dn_threshold:
                self._sell()
                self._entry_price = close
        elif self._position == 1:
            sl = self._entry_price - self.atr_sl_mult * cur_atr
            if close < sl:
                self._sell()
                self._entry_price = 0.0
        elif self._position == -1:
            sl = self._entry_price + self.atr_sl_mult * cur_atr
            if close > sl:
                self._buy()
                self._entry_price = 0.0

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
