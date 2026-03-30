"""Portfolio Risk Parity strategy.

Allocates capital inversely proportional to each instrument's volatility
so each instrument contributes equally to total portfolio risk.

In single-instrument mode, adapts position sizing based on rolling volatility.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._indicators import atr
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.portfolio_risk_parity")


class PortfolioRiskParity(BaseStrategy, _BacktestStrategyMixin):
    """Risk parity allocation via inverse-volatility weighting.

    Computes rolling annualised volatility (ATR proxy) and sizes positions
    inversely. Rebalances on a fixed schedule.

    In multi-instrument use, call on_bar() for each symbol and use the
    generated orders. Position size is returned as a string in orders
    (normalised to lot_size units).

    Args:
        vol_period: Volatility lookback period in bars (default 20).
        rebalance_bars: Bars between rebalances (default 20).
        target_vol_pct: Target daily volatility % per instrument (default 1.0).
        lot_size: Minimum lot size for orders (default 1).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "PortfolioRiskParity",
        exchange: str = "NSE",
        product: str = "CNC",
        vol_period: int = 20,
        rebalance_bars: int = 20,
        target_vol_pct: float = 1.0,
        lot_size: int = 1,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.vol_period = vol_period
        self.rebalance_bars = rebalance_bars
        self.target_vol_pct = target_vol_pct
        self.lot_size = lot_size
        self._symbol = symbol
        self._init_history()
        self._bars_since_rebalance: int = 0


    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        self._bars_since_rebalance += 1

        if self._bars_since_rebalance < self.rebalance_bars:
            return
        if len(self._closes) < self.vol_period + 2:
            return

        atr_vals = atr(self._highs, self._lows, self._closes, self.vol_period)
        cur_atr = atr_vals[-1]
        if cur_atr <= 0 or bar.close <= 0:
            return

        # Daily vol proxy as % of price
        vol_pct = cur_atr / bar.close * 100

        # Target quantity: invest enough so position contributes target_vol_pct
        if vol_pct > 0:
            qty = max(self.lot_size, int(self.target_vol_pct / vol_pct))
        else:
            qty = self.lot_size

        qty_str = str(qty)
        if self._position <= 0:
            self._buy(qty_str)
        self._bars_since_rebalance = 0
        logger.debug(
            "RiskParity rebalance: vol=%.2f%% qty=%d", vol_pct, qty
        )

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["PortfolioRiskParity"]
