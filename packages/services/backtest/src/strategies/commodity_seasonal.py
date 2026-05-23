"""Commodity Seasonal Pattern strategy.

Exploits well-known seasonal tendencies in commodity markets:
- Gold: Bullish Oct–Feb (Diwali, wedding season demand in India).
- Crude Oil: Bullish May–Aug (US summer driving season).
- Agricultural: Crop cycle driven.

Seasonal months are configurable. Strategy goes long during bullish
seasonal window and exits outside it.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import ema
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.commodity_seasonal")

# Default seasonal windows (month numbers, 1=Jan, 12=Dec)
_GOLD_BULLISH_MONTHS = {10, 11, 12, 1, 2}
_CRUDE_BULLISH_MONTHS = {5, 6, 7, 8}


class CommoditySeasonal(BaseStrategy, _BacktestStrategyMixin):
    """Seasonal pattern strategy for commodities.

    Enters long during bullish seasonal months and exits outside the window.
    Uses EMA filter to avoid entering during counter-trend moves.

    Args:
        bullish_months: Set of month integers defining the bullish window.
        ema_period: EMA period for trend filter (default 20).
        seasonal_data: Optional dict mapping month to bias (1/-1/0). Overrides
                       bullish_months if provided.
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "CommoditySeasonal",
        exchange: str = "MCX",
        product: str = "NRML",
        bullish_months: set[int] | None = None,
        ema_period: int = 20,
        seasonal_data: dict[int, int] | None = None,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.bullish_months: set[int] = bullish_months or _GOLD_BULLISH_MONTHS
        self.ema_period = ema_period
        self.seasonal_data: dict[int, int] = seasonal_data or {}
        self._symbol = symbol
        self._init_history()


    def _month(self, ts: str) -> int:
        """Extract month from timestamp YYYY-MM-DD..."""
        try:
            return int(ts[5:7])
        except (ValueError, IndexError):
            return 0

    def _seasonal_bias(self, month: int) -> int:
        if self.seasonal_data:
            return self.seasonal_data.get(month, 0)
        if month in self.bullish_months:
            return 1
        return -1

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        if len(self._closes) < self.ema_period + 2:
            return

        month = self._month(bar.timestamp)
        bias = self._seasonal_bias(month)

        ema_vals = ema(self._closes, self.ema_period)
        close = self._closes[-1]
        above_ema = close > ema_vals[-1]
        below_ema = close < ema_vals[-1]

        if bias == 1 and above_ema and self._position <= 0:
            self._buy()
        elif bias == -1 and below_ema and self._position >= 0:
            self._sell()
        elif bias == 0 and self._position != 0:
            if self._position > 0:
                self._sell()
            else:
                self._buy()
                self._flat()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["CommoditySeasonal"]
