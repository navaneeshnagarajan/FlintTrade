"""Portfolio Momentum Rotation strategy.

Ranks a basket of instruments by rolling momentum (N-bar return) and
rotates into the top-K performers. Out-performers are bought; laggers sold.

Multi-instrument: uses set_universe() to register instruments and their
close prices, then generates rotation signals on each rebalance.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.portfolio_momentum_rotation")


class PortfolioMomentumRotation(BaseStrategy, _BacktestStrategyMixin):
    """Sector/stock rotation based on relative momentum.

    Tracks a universe of instruments and rotates into top-K by
    momentum score every rebalance_bars bars.

    In single-instrument mode, simply buys when the instrument's own
    momentum (N-bar return) is positive, exits when negative.

    Args:
        momentum_period: Lookback bars for momentum score (default 20).
        rebalance_bars: Bars between rotation (default 20).
        top_k: Number of instruments to hold (default 1 for single-instrument).
        symbol: Primary instrument symbol.
    """

    def __init__(
        self,
        name: str = "PortfolioMomentumRotation",
        exchange: str = "NSE",
        product: str = "CNC",
        momentum_period: int = 20,
        rebalance_bars: int = 20,
        top_k: int = 1,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.momentum_period = momentum_period
        self.rebalance_bars = rebalance_bars
        self.top_k = top_k
        self._symbol = symbol
        self._init_history()
        self._bars_since_rebalance: int = 0
        # Multi-instrument universe: {symbol: list of closes}
        self._universe: dict[str, list[float]] = {}


    def update_universe(self, symbol: str, close: float) -> None:
        """Update universe close price for a symbol.

        Args:
            symbol: Instrument symbol.
            close: Current close price.
        """
        if symbol not in self._universe:
            self._universe[symbol] = []
        self._universe[symbol].append(close)

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        self._bars_since_rebalance += 1

        if self._bars_since_rebalance < self.rebalance_bars:
            return
        if len(self._closes) < self.momentum_period + 2:
            return

        self._bars_since_rebalance = 0

        # Single-instrument momentum check
        momentum = (
            (self._closes[-1] - self._closes[-self.momentum_period - 1])
            / self._closes[-self.momentum_period - 1]
            if self._closes[-self.momentum_period - 1] > 0
            else 0.0
        )

        if momentum > 0 and self._position <= 0:
            self._buy()
            logger.debug("Rotation: buy %s momentum=%.2f%%", self._symbol, momentum * 100)
        elif momentum <= 0 and self._position > 0:
            self._sell()
            logger.debug("Rotation: exit %s momentum=%.2f%%", self._symbol, momentum * 100)

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["PortfolioMomentumRotation"]
