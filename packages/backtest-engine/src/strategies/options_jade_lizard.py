"""Options Jade Lizard strategy.

Jade Lizard: Short OTM put + Short OTM call spread.
- Sells a put below current price (undefined downside risk).
- Sells a call spread above current price (capped upside risk).
- Net premium received; no upside risk if premium > call spread width.

In backtest mode, modelled as a single synthetic combined-premium instrument.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._indicators import rsi
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.options_jade_lizard")


class OptionsJadeLizard(BaseStrategy, _BacktestStrategyMixin):
    """Short put + short call spread (Jade Lizard).

    Enters when RSI indicates neutral-to-slightly-bullish market conditions.
    Target: premium decays by target_pct. Stop: premium expands by stop_pct.

    Args:
        entry_time: Entry time HH:MM (default "09:45").
        exit_time: Force-exit HH:MM (default "15:10").
        rsi_period: RSI for entry filter (default 14).
        rsi_min: Minimum RSI for entry (default 40).
        rsi_max: Maximum RSI for entry (default 65).
        target_pct: Premium decay % to take profit (default 50.0).
        stop_pct: Premium expansion % to cut loss (default 100.0).
        symbol: Synthetic instrument symbol.
    """

    def __init__(
        self,
        name: str = "OptionsJadeLizard",
        exchange: str = "NFO",
        product: str = "NRML",
        entry_time: str = "09:45",
        exit_time: str = "15:10",
        rsi_period: int = 14,
        rsi_min: float = 40.0,
        rsi_max: float = 65.0,
        target_pct: float = 50.0,
        stop_pct: float = 100.0,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.entry_time = entry_time
        self.exit_time = exit_time
        self.rsi_period = rsi_period
        self.rsi_min = rsi_min
        self.rsi_max = rsi_max
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
            self._buy()
            self._flat()
            self._entry_premium = 0.0
            return

        if tp == self.entry_time and self._position == 0:
            if len(self._closes) >= self.rsi_period + 2:
                rsi_vals = rsi(self._closes, self.rsi_period)
                if self.rsi_min <= rsi_vals[-1] <= self.rsi_max:
                    self._sell()
                    self._entry_premium = bar.close
            return

        if self._position == -1 and self._entry_premium > 0:
            pnl_pct = (self._entry_premium - bar.close) / self._entry_premium * 100
            if pnl_pct >= self.target_pct:
                self._buy()
                self._flat()
                self._entry_premium = 0.0
            elif -pnl_pct >= self.stop_pct:
                self._buy()
                self._flat()
                self._entry_premium = 0.0

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["OptionsJadeLizard"]
