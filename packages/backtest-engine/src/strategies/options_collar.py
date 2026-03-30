"""Options Collar strategy.

Protective collar on equity holdings: long stock + long put + short call.
The short call finances the put. Limits both downside and upside.

In backtest mode, collar is modelled by tracking the underlying position
with ATR-based synthetic collar bounds.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._indicators import atr
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.options_collar")


class OptionsCollar(BaseStrategy, _BacktestStrategyMixin):
    """Protective collar on equity holdings.

    Assumes an existing long position is entered at session open.
    The collar cap (synthetic short call) and floor (synthetic long put)
    are set as ATR multiples from the entry price.

    Args:
        collar_atr_mult: ATR multiple for both cap and floor (default 2.0).
        atr_period: ATR period (default 14).
        entry_time: Entry HH:MM (default "09:15").
        exit_time: Exit / unwind HH:MM (default "15:15").
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "OptionsCollar",
        exchange: str = "NSE",
        product: str = "CNC",
        collar_atr_mult: float = 2.0,
        atr_period: int = 14,
        entry_time: str = "09:15",
        exit_time: str = "15:15",
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.collar_atr_mult = collar_atr_mult
        self.atr_period = atr_period
        self.entry_time = entry_time
        self.exit_time = exit_time
        self._symbol = symbol
        self._init_history()
        self._entry_price: float = 0.0
        self._collar_cap: float = 0.0
        self._collar_floor: float = 0.0


    def on_tick(self, quote: Quote) -> None:
        pass

    def _time_part(self, ts: str) -> str:
        return ts[11:16] if len(ts) > 16 else ""

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        tp = self._time_part(bar.timestamp)

        if tp >= self.exit_time and self._position != 0:
            self._sell()
            self._entry_price = 0.0
            return

        if tp == self.entry_time and self._position == 0:
            if len(self._closes) >= self.atr_period + 1:
                atr_vals = atr(self._highs, self._lows, self._closes, self.atr_period)
                cur_atr = atr_vals[-1]
            else:
                cur_atr = bar.close * 0.01
            self._buy()
            self._entry_price = bar.close
            self._collar_cap = self._entry_price + self.collar_atr_mult * cur_atr
            self._collar_floor = self._entry_price - self.collar_atr_mult * cur_atr
            logger.debug(
                "Collar set: floor=%.2f entry=%.2f cap=%.2f",
                self._collar_floor, self._entry_price, self._collar_cap,
            )
            return

        if self._position == 1:
            # Cap hit: sell (synthetic call exercise)
            if bar.close >= self._collar_cap:
                self._sell()
                self._entry_price = 0.0
                logger.info("Collar cap hit at %.2f", bar.close)
            # Floor hit: sell (synthetic put exercise)
            elif bar.close <= self._collar_floor:
                self._sell()
                self._entry_price = 0.0
                logger.info("Collar floor hit at %.2f", bar.close)

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["OptionsCollar"]
