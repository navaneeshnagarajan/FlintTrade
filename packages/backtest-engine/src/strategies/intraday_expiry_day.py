"""Intraday Weekly Expiry Day Straddle/Strangle Adjustments (India-specific).

On weekly expiry days (Thursday for NIFTY/BANKNIFTY), IV crush accelerates
near close. This strategy manages a synthetic short straddle representation
using underlying price and notional premium tracking.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._indicators import atr
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.intraday_expiry_day")


class IntradayExpiryDay(BaseStrategy, _BacktestStrategyMixin):
    """Weekly expiry day straddle/strangle adjustment strategy.

    Enters a synthetic short straddle (represented via underlying position)
    at a specified entry time. Adjusts/exits based on underlying movement
    beyond the straddle breakeven (approximated as ATR-based band).

    Args:
        entry_time: Entry time HH:MM (default "09:30").
        exit_time: Force-exit HH:MM before expiry close (default "15:10").
        atr_period: ATR period for breakeven approximation (default 14).
        breakeven_mult: ATR multiple defining straddle breakeven (default 1.5).
        symbol: Underlying index symbol.
    """

    def __init__(
        self,
        name: str = "IntradayExpiryDay",
        exchange: str = "NFO",
        product: str = "NRML",
        entry_time: str = "09:30",
        exit_time: str = "15:10",
        atr_period: int = 14,
        breakeven_mult: float = 1.5,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.entry_time = entry_time
        self.exit_time = exit_time
        self.atr_period = atr_period
        self.breakeven_mult = breakeven_mult
        self._symbol = symbol
        self._init_history()
        self._entry_price: float = 0.0
        self._entry_atr: float = 0.0


    def on_tick(self, quote: Quote) -> None:
        pass

    def _time_part(self, ts: str) -> str:
        return ts[11:16] if len(ts) > 16 else ""

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        tp = self._time_part(bar.timestamp)

        if tp >= self.exit_time and self._position != 0:
            if self._position > 0:
                self._sell()
            else:
                self._buy()
                self._flat()
            return

        if tp == self.entry_time and self._position == 0:
            if len(self._closes) >= self.atr_period + 1:
                atr_vals = atr(self._highs, self._lows, self._closes, self.atr_period)
                self._entry_atr = atr_vals[-1]
            else:
                self._entry_atr = bar.close * 0.005  # fallback: 0.5% of price
            self._sell()  # sell straddle (synthetic short via underlying)
            self._entry_price = bar.close
            return

        if self._position == -1 and self._entry_price > 0:
            upper = self._entry_price + self.breakeven_mult * self._entry_atr
            lower = self._entry_price - self.breakeven_mult * self._entry_atr
            if bar.close > upper or bar.close < lower:
                # Breakeven breached: buy back and go flat
                self._buy()
                self._flat()
                logger.info(
                    "Expiry straddle breakeven hit at %.2f (entry=%.2f)",
                    bar.close, self._entry_price,
                )
                self._entry_price = 0.0

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["IntradayExpiryDay"]
