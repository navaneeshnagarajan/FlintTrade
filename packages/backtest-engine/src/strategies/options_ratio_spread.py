"""Options Ratio Spread strategy.

1:2 call or put ratio spread: buy 1 ATM option, sell 2 OTM options.
Profits from moderate directional move followed by time decay.
Max profit is between the strikes; risk is on the far side.

In backtest mode, modelled via the combined synthetic premium instrument.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._indicators import rsi
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.options_ratio_spread")


class OptionsRatioSpread(BaseStrategy, _BacktestStrategyMixin):
    """1:2 ratio call/put spread strategy.

    Enters directionally based on RSI: bullish RSI → call ratio spread;
    bearish RSI → put ratio spread. Modelled as single synthetic position.

    Args:
        entry_time: Entry HH:MM (default "10:00").
        exit_time: Force-exit HH:MM (default "15:10").
        rsi_period: RSI period for direction filter (default 14).
        bullish_rsi: RSI level above which to enter call spread (default 55).
        bearish_rsi: RSI level below which to enter put spread (default 45).
        target_pct: Premium decay % to take profit (default 60.0).
        stop_pct: Premium expansion % to cut loss (default 80.0).
        symbol: Synthetic spread symbol.
    """

    def __init__(
        self,
        name: str = "OptionsRatioSpread",
        exchange: str = "NFO",
        product: str = "NRML",
        entry_time: str = "10:00",
        exit_time: str = "15:10",
        rsi_period: int = 14,
        bullish_rsi: float = 55.0,
        bearish_rsi: float = 45.0,
        target_pct: float = 60.0,
        stop_pct: float = 80.0,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.entry_time = entry_time
        self.exit_time = exit_time
        self.rsi_period = rsi_period
        self.bullish_rsi = bullish_rsi
        self.bearish_rsi = bearish_rsi
        self.target_pct = target_pct
        self.stop_pct = stop_pct
        self._symbol = symbol
        self._init_history()
        self._entry_premium: float = 0.0


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
            self._entry_premium = 0.0
            return

        if tp == self.entry_time and self._position == 0:
            if len(self._closes) >= self.rsi_period + 2:
                rsi_vals = rsi(self._closes, self.rsi_period)
                cur_rsi = rsi_vals[-1]
                if cur_rsi >= self.bullish_rsi:
                    self._buy()  # call ratio spread: net debit, modelled long
                    self._entry_premium = bar.close
                elif cur_rsi <= self.bearish_rsi:
                    self._sell()  # put ratio spread: net credit, modelled short
                    self._entry_premium = bar.close
            return

        if self._entry_premium > 0:
            pnl_pct = abs(bar.close - self._entry_premium) / self._entry_premium * 100
            if pnl_pct >= self.target_pct or pnl_pct >= self.stop_pct:
                if self._position > 0:
                    self._sell()
                else:
                    self._buy()
                    self._flat()
                self._entry_premium = 0.0

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["OptionsRatioSpread"]
