"""Crypto Grid Trading strategy.

Places buy and sell orders at fixed intervals (grid lines) around the current price.
Profits from oscillation within the grid range. Grid spacing is dynamically
adjusted based on ATR.

24/7 market: no session-time checks.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._indicators import atr
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.crypto_grid")


class CryptoGrid(BaseStrategy, _BacktestStrategyMixin):
    """Grid trading with dynamic ATR-based spacing.

    Divides a price range into N grid levels. Buys on downward crosses of a
    grid line; sells on upward crosses. ATR recalculates spacing periodically.

    24/7 market: no session-time checks.

    Args:
        grid_levels: Number of grid lines above and below current price (default 5).
        atr_period: ATR period for grid spacing (default 14).
        atr_mult: ATR multiple for each grid step (default 1.0).
        recalc_bars: Bars between grid recalculation (default 20).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "CryptoGrid",
        exchange: str = "NSE",
        product: str = "MIS",
        grid_levels: int = 5,
        atr_period: int = 14,
        atr_mult: float = 1.0,
        recalc_bars: int = 20,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.grid_levels = grid_levels
        self.atr_period = atr_period
        self.atr_mult = atr_mult
        self.recalc_bars = recalc_bars
        self._symbol = symbol
        self._init_history()
        self._grid_lines: list[float] = []
        self._last_recalc: int = 0
        self._last_grid_idx: int = -1  # which grid level we were last at


    def _recalculate_grid(self, center: float, step: float) -> None:
        self._grid_lines = [
            center + (i - self.grid_levels) * step
            for i in range(self.grid_levels * 2 + 1)
        ]
        logger.debug(
            "Grid recalc: center=%.2f step=%.4f lines=%s",
            center, step, [round(g, 2) for g in self._grid_lines],
        )

    def _current_grid_idx(self, price: float) -> int:
        """Return index of the grid line just below price."""
        for i in range(len(self._grid_lines) - 1, -1, -1):
            if price >= self._grid_lines[i]:
                return i
        return 0

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        n = len(self._closes)

        if n < self.atr_period + 2:
            return

        atr_vals = atr(self._highs, self._lows, self._closes, self.atr_period)
        step = self.atr_mult * atr_vals[-1]

        # Recalculate grid periodically
        if n - self._last_recalc >= self.recalc_bars or not self._grid_lines:
            self._recalculate_grid(bar.close, step)
            self._last_recalc = n
            self._last_grid_idx = self._current_grid_idx(bar.close)
            return

        cur_idx = self._current_grid_idx(bar.close)

        if cur_idx < self._last_grid_idx:
            # Price dropped to lower grid: buy
            self._buy()
        elif cur_idx > self._last_grid_idx:
            # Price rose to higher grid: sell
            self._sell()

        self._last_grid_idx = cur_idx

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["CryptoGrid"]
