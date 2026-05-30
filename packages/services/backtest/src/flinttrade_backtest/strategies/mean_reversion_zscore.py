"""Z-Score Mean Reversion strategy — Mean Reversion category.

Computes a rolling Z-Score of closing prices relative to a lookback window.

    z = (close - mean(closes, period)) / std(closes, period)

Trading rules:
    BUY  when z < -z_entry  (price unusually far below mean)
    SELL when z > +z_entry  (price unusually far above mean)
    FLAT (exit) when |z| < z_exit (price has returned near the mean)
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.mean_reversion_zscore")


def _zscore(values: list[float], period: int) -> list[float]:
    """Rolling Z-Score over a fixed lookback window.

    Args:
        values: Price series.
        period: Rolling window size.

    Returns:
        Z-Score series; leading values are 0.0.
    """
    n = len(values)
    if n < period:
        return [0.0] * n
    result: list[float] = [0.0] * (period - 1)
    for i in range(period - 1, n):
        window = values[i - period + 1: i + 1]
        mean = sum(window) / period
        variance = sum((v - mean) ** 2 for v in window) / period
        std = variance ** 0.5
        if std == 0:
            result.append(0.0)
        else:
            result.append((values[i] - mean) / std)
    return result


class ZScoreMeanReversion(BaseStrategy, _BacktestStrategyMixin):
    """Z-Score mean-reversion strategy.

    Enters long when price is statistically cheap (z < -z_entry) and short
    when statistically expensive (z > +z_entry). Exits when price reverts
    close to the mean (|z| < z_exit).

    Args:
        period: Rolling lookback for mean and std computation (default 20).
        z_entry: Z-Score magnitude to trigger a new position (default 2.0).
        z_exit: Z-Score magnitude at which to flatten an existing position
            (default 0.5).
        symbol: Instrument symbol (default "").
        exchange: Exchange code (default "NSE").
        product: Product type (default "MIS").
    """

    def __init__(
        self,
        name: str = "ZScoreMeanReversion",
        exchange: str = "NSE",
        product: str = "MIS",
        period: int = 20,
        z_entry: float = 2.0,
        z_exit: float = 0.5,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.period = period
        self.z_entry = z_entry
        self.z_exit = z_exit
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        """Not used — bar-close strategy."""

    def on_bar(self, bar: OHLCV) -> None:
        """Process a completed bar and act on Z-Score thresholds.

        Args:
            bar: The just-closed OHLCV bar.
        """
        if not self.is_active:
            return
        self._record_bar(bar)
        if len(self._closes) < self.period + 1:
            return

        z_vals = _zscore(self._closes, self.period)
        z = z_vals[-1]

        # Exit logic (checked first so we can re-enter same bar if needed)
        if self._position == 1 and z >= -self.z_exit:
            logger.debug("Z-exit long | z=%.3f | %s", z, self._symbol)
            self._sell()
            self._flat()
            return
        if self._position == -1 and z <= self.z_exit:
            logger.debug("Z-exit short | z=%.3f | %s", z, self._symbol)
            self._buy()
            self._flat()
            return

        # Entry logic (only when flat)
        if self._position == 0:
            if z < -self.z_entry:
                logger.debug("Z-entry long | z=%.3f | %s", z, self._symbol)
                self._buy()
            elif z > self.z_entry:
                logger.debug("Z-entry short | z=%.3f | %s", z, self._symbol)
                self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        """Not used — strategy generates its own signals."""

    def generate_orders(self) -> list[Order]:
        """Return and clear all pending orders.

        Returns:
            List of Order objects to submit to the engine.
        """
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
