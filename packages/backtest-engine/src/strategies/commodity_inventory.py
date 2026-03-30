"""Commodity Inventory Report Directional strategy.

Crude oil, natural gas, and other commodities respond sharply to weekly inventory
reports (EIA, API). A surprise draw (less supply) is bullish; a surprise build
(more supply) is bearish.

Inventory data is injected via set_inventory_data() before the event bar.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._indicators import atr
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.commodity_inventory")


class CommodityInventory(BaseStrategy, _BacktestStrategyMixin):
    """Inventory report-based directional strategy for crude/natgas.

    Reacts to inventory surprises (actual vs expected). Positions are
    held for a fixed number of bars post-report.

    Args:
        bars_to_hold: Bars to hold post-event (default 4).
        atr_period: ATR for stop sizing (default 14).
        stop_mult: Stop distance as ATR multiple (default 2.0).
        symbol: Instrument symbol (e.g., CRUDEOIL, NATURALGAS).
    """

    def __init__(
        self,
        name: str = "CommodityInventory",
        exchange: str = "MCX",
        product: str = "NRML",
        bars_to_hold: int = 4,
        atr_period: int = 14,
        stop_mult: float = 2.0,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.bars_to_hold = bars_to_hold
        self.atr_period = atr_period
        self.stop_mult = stop_mult
        self._symbol = symbol
        self._init_history()
        self._event_bar_idx: int = -1
        self._direction: int = 0  # +1 bullish, -1 bearish
        self._bars_held: int = 0
        self._stop: float = 0.0


    def set_inventory_data(
        self,
        actual_mbbl: float,
        expected_mbbl: float,
        event_bar_idx: int,
    ) -> None:
        """Set inventory surprise data.

        Args:
            actual_mbbl: Actual inventory change in million barrels.
            expected_mbbl: Expected inventory change in million barrels.
            event_bar_idx: Bar index when report is released.
        """
        surprise = actual_mbbl - expected_mbbl
        self._direction = -1 if surprise > 0 else 1  # build=bearish, draw=bullish
        self._event_bar_idx = event_bar_idx
        logger.debug(
            "Inventory surprise=%.2f MMbbl direction=%d",
            surprise, self._direction,
        )

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        idx = len(self._closes) - 1

        if self._position != 0:
            self._bars_held += 1
            if self._stop > 0:
                if self._position == 1 and bar.close <= self._stop:
                    self._sell()
                    self._bars_held = 0
                    return
                elif self._position == -1 and bar.close >= self._stop:
                    self._buy()
                    self._flat()
                    self._bars_held = 0
                    return
            if self._bars_held >= self.bars_to_hold:
                if self._position > 0:
                    self._sell()
                else:
                    self._buy()
                    self._flat()
                self._bars_held = 0
            return

        if idx == self._event_bar_idx and self._direction != 0:
            if len(self._closes) >= self.atr_period + 1:
                atr_vals = atr(self._highs, self._lows, self._closes, self.atr_period)
                stop_dist = self.stop_mult * atr_vals[-1]
            else:
                stop_dist = bar.close * 0.01

            if self._direction == 1:
                self._buy()
                self._stop = bar.close - stop_dist
            else:
                self._sell()
                self._stop = bar.close + stop_dist
            self._bars_held = 0

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["CommodityInventory"]
