"""RSI Mean Reversion strategy — Mean Reversion category.

Unlike RSIMomentum (which trades momentum), this strategy trades the reversion:
- Buy when RSI is deeply oversold and starts turning up.
- Sell when RSI is deeply overbought and starts turning down.
- Uses a higher-frequency RSI (shorter period) for faster reversion signals.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import rsi
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.mean_reversion_rsi")


class RSIMeanRevert(BaseStrategy, _BacktestStrategyMixin):
    """RSI mean-reversion strategy.

    Entry: RSI reaches extreme and reverses (turn-up from deep oversold,
           turn-down from deep overbought). Requires confirmation bar.
    Exit: RSI returns to neutral zone (40-60).

    Args:
        period: RSI period (default 5 — shorter for faster reversion).
        oversold: Oversold level (default 20).
        overbought: Overbought level (default 80).
        neutral_low: Lower bound of neutral exit zone (default 40).
        neutral_high: Upper bound of neutral exit zone (default 60).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "RSIMeanRevert",
        exchange: str = "NSE",
        product: str = "MIS",
        period: int = 5,
        oversold: float = 20.0,
        overbought: float = 80.0,
        neutral_low: float = 40.0,
        neutral_high: float = 60.0,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.neutral_low = neutral_low
        self.neutral_high = neutral_high
        self._symbol = symbol
        self._init_history()
        self._was_oversold = False
        self._was_overbought = False

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        if len(self._closes) < self.period + 2:
            return

        rsi_vals = rsi(self._closes, self.period)
        cur = rsi_vals[-1]

        # Track extreme state
        if cur <= self.oversold:
            self._was_oversold = True
            self._was_overbought = False
        elif cur >= self.overbought:
            self._was_overbought = True
            self._was_oversold = False

        # Entry: confirmation — RSI turning up from oversold
        if self._was_oversold and cur > self.oversold and self._position <= 0:
            self._buy()
            self._was_oversold = False

        # Entry: confirmation — RSI turning down from overbought
        if self._was_overbought and cur < self.overbought and self._position >= 0:
            self._sell()
            self._was_overbought = False

        # Exit: return to neutral zone
        if self._position == 1 and self.neutral_low <= cur <= self.neutral_high:
            self._sell()
        elif self._position == -1 and self.neutral_low <= cur <= self.neutral_high:
            self._buy()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
