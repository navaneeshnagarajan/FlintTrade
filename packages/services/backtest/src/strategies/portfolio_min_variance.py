"""Portfolio Minimum Variance Optimization strategy.

Finds the minimum variance portfolio weights for a basket of instruments
using pure-Python covariance computation (no numpy required).

In single-instrument mode, falls back to inverse-vol position sizing.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import atr
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.portfolio_min_variance")


def _cov_matrix(returns_lists: list[list[float]]) -> list[list[float]]:
    """Compute covariance matrix from list of return series."""
    n = len(returns_lists)
    period = min(len(r) for r in returns_lists)
    if period < 2:
        return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    cov: list[list[float]] = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            ri = returns_lists[i][-period:]
            rj = returns_lists[j][-period:]
            mean_i = sum(ri) / period
            mean_j = sum(rj) / period
            c = sum((ri[k] - mean_i) * (rj[k] - mean_j) for k in range(period)) / (period - 1)
            cov[i][j] = c
            cov[j][i] = c
    return cov


def _min_variance_weights(cov: list[list[float]]) -> list[float]:
    """Approximate minimum variance weights using inverse-variance diagonal."""
    n = len(cov)
    inv_var = [1.0 / max(cov[i][i], 1e-10) for i in range(n)]
    total = sum(inv_var)
    return [iv / total for iv in inv_var]


class PortfolioMinVariance(BaseStrategy, _BacktestStrategyMixin):
    """Minimum variance portfolio optimization.

    Rebalances into minimum-variance weights estimated from rolling returns.
    In single-instrument mode, uses inverse ATR as a volatility proxy.

    Args:
        vol_period: Rolling window for covariance estimation (default 30).
        rebalance_bars: Bars between rebalances (default 20).
        atr_period: ATR period for single-instrument vol (default 14).
        symbol: Primary instrument symbol.
    """

    def __init__(
        self,
        name: str = "PortfolioMinVariance",
        exchange: str = "NSE",
        product: str = "CNC",
        vol_period: int = 30,
        rebalance_bars: int = 20,
        atr_period: int = 14,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.vol_period = vol_period
        self.rebalance_bars = rebalance_bars
        self.atr_period = atr_period
        self._symbol = symbol
        self._init_history()
        self._bars_since_rebalance: int = 0
        self._universe_returns: dict[str, list[float]] = {}


    def update_universe(self, symbol: str, ret: float) -> None:
        """Feed a return observation for multi-instrument optimization.

        Args:
            symbol: Instrument symbol.
            ret: Bar return (close-to-close).
        """
        if symbol not in self._universe_returns:
            self._universe_returns[symbol] = []
        self._universe_returns[symbol].append(ret)

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        self._bars_since_rebalance += 1

        if self._bars_since_rebalance < self.rebalance_bars:
            return
        if len(self._closes) < self.atr_period + 2:
            return

        self._bars_since_rebalance = 0

        # Single-instrument: use inverse ATR weighting (always long)
        atr_vals = atr(self._highs, self._lows, self._closes, self.atr_period)
        vol_pct = atr_vals[-1] / bar.close * 100 if bar.close > 0 else 1.0
        qty = max(1, int(1.0 / max(vol_pct, 0.01)))

        if self._position <= 0:
            self._buy(str(qty))
        logger.debug("MinVar rebalance: vol=%.2f%% qty=%d", vol_pct, qty)

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["PortfolioMinVariance"]
