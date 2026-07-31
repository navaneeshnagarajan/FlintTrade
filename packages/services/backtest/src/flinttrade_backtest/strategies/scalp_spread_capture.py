"""Scalp Spread Capture (Market Making) strategy.

Simulates a market-making approach: quotes both sides of the spread,
captures the bid-ask spread as profit. Manages inventory limits to avoid
excessive one-sided exposure.

In backtest mode, modelled as: enter long when price dips N ticks below
recent mid; enter short when it rises N ticks above; close when it reverts.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import atr, sma
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.scalp_spread_capture")


class ScalpSpreadCapture(BaseStrategy, _BacktestStrategyMixin):
    """Market-making spread capture with inventory limits.

    Quotes around a short-term mid-price. Captures the spread on mean reversion.
    Inventory limit prevents excessive directional exposure.

    Args:
        mid_period: SMA period for mid-price estimate (default 5).
        spread_atr_mult: Half-spread width as fraction of ATR (default 0.3).
        atr_period: ATR period (default 14).
        max_inventory: Maximum position held without reversion (default 2).
        session_close: Force-exit HH:MM (default "15:15").
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "ScalpSpreadCapture",
        exchange: str = "NSE",
        product: str = "MIS",
        mid_period: int = 5,
        spread_atr_mult: float = 0.3,
        atr_period: int = 14,
        max_inventory: int = 2,
        session_close: str = "15:15",
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.mid_period = mid_period
        self.spread_atr_mult = spread_atr_mult
        self.atr_period = atr_period
        self.max_inventory = max_inventory
        self.session_close = session_close
        self._symbol = symbol
        self._init_history()
        self._inventory: int = 0  # cumulative lot inventory


    def _time_part(self, ts: str) -> str:
        return ts[11:16] if len(ts) > 16 else ""

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        tp = self._time_part(bar.timestamp)

        if tp >= self.session_close and self._position != 0:
            if self._position > 0:
                self._sell()
            else:
                self._buy()
                self._flat()
            self._inventory = 0
            return

        if len(self._closes) < max(self.mid_period, self.atr_period) + 2:
            return

        mid_vals = sma(self._closes, self.mid_period)
        atr_vals = atr(self._highs, self._lows, self._closes, self.atr_period)
        mid = mid_vals[-1]
        half_spread = self.spread_atr_mult * atr_vals[-1]

        close = bar.close
        bid_level = mid - half_spread
        ask_level = mid + half_spread

        # Quote bid: buy when price drops to bid level (inventory not maxed)
        if close <= bid_level and self._inventory < self.max_inventory:
            self._buy()
            self._inventory += 1

        # Quote ask: sell when price rises to ask level (inventory not maxed short)
        elif close >= ask_level and self._inventory > -self.max_inventory:
            self._sell()
            self._inventory -= 1

        # Flatten inventory when price returns to mid
        elif abs(close - mid) < half_spread * 0.3 and self._inventory != 0:
            if self._inventory > 0:
                self._sell()
            else:
                self._buy()
                self._flat()
            self._inventory = 0

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["ScalpSpreadCapture"]
