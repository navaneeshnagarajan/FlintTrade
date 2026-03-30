"""Options Butterfly and Iron Butterfly strategies.

Long Butterfly: Buy ITM call, sell 2 ATM calls, buy OTM call.
Iron Butterfly: Sell ATM straddle, buy OTM strangle wings.

Both profit from low volatility / range-bound market near expiry.
Modelled via synthetic combined-premium instrument in backtest.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._indicators import bollinger_bands
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.options_butterfly")


class OptionsButterfly(BaseStrategy, _BacktestStrategyMixin):
    """Long butterfly spread strategy.

    Enters when Bollinger Band width is narrow (low vol expected).
    Modelled as a single synthetic debit position.

    Args:
        entry_time: Entry HH:MM (default "10:00").
        exit_time: Force-exit HH:MM (default "15:10").
        bb_period: Bollinger Band period for vol filter (default 20).
        bb_squeeze_pct: Band width % threshold for "narrow" (default 2.0).
        target_pct: Move % in underlying to take profit (default 1.5).
        stop_pct: Move % in underlying to stop (default 3.0).
        symbol: Synthetic spread symbol.
    """

    def __init__(
        self,
        name: str = "OptionsButterfly",
        exchange: str = "NFO",
        product: str = "NRML",
        entry_time: str = "10:00",
        exit_time: str = "15:10",
        bb_period: int = 20,
        bb_squeeze_pct: float = 2.0,
        target_pct: float = 1.5,
        stop_pct: float = 3.0,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.entry_time = entry_time
        self.exit_time = exit_time
        self.bb_period = bb_period
        self.bb_squeeze_pct = bb_squeeze_pct
        self.target_pct = target_pct
        self.stop_pct = stop_pct
        self._symbol = symbol
        self._init_history()
        self._entry_price: float = 0.0


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
            if len(self._closes) >= self.bb_period:
                upper, mid, lower = bollinger_bands(self._closes, self.bb_period)
                if mid[-1] > 0:
                    bw_pct = (upper[-1] - lower[-1]) / mid[-1] * 100
                    if bw_pct <= self.bb_squeeze_pct:
                        self._buy()  # enter butterfly (long debit)
                        self._entry_price = bar.close
            return

        if self._position == 1 and self._entry_price > 0:
            move_pct = abs(bar.close - self._entry_price) / self._entry_price * 100
            if move_pct >= self.target_pct or move_pct >= self.stop_pct:
                self._sell()
                self._entry_price = 0.0

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


class OptionsIronButterfly(BaseStrategy, _BacktestStrategyMixin):
    """Iron Butterfly: short ATM straddle + long OTM strangle wings.

    Modelled as short combined premium. Profits from time decay and
    low-volatility range-bound market.

    Args:
        entry_time: Entry HH:MM (default "09:45").
        exit_time: Force-exit HH:MM (default "15:10").
        target_pct: Premium decay % to take profit (default 50.0).
        stop_pct: Premium expansion % to stop (default 100.0).
        symbol: Synthetic instrument symbol.
    """

    def __init__(
        self,
        name: str = "OptionsIronButterfly",
        exchange: str = "NFO",
        product: str = "NRML",
        entry_time: str = "09:45",
        exit_time: str = "15:10",
        target_pct: float = 50.0,
        stop_pct: float = 100.0,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.entry_time = entry_time
        self.exit_time = exit_time
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


__all__ = ["OptionsButterfly", "OptionsIronButterfly"]
