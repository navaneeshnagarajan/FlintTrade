"""Volatility Contraction Pattern (VCP) strategy — Volatility category.

The VCP (popularised by Mark Minervini) identifies stocks undergoing repeated
volatility contractions before a breakout move.

Detection logic:
    1. Compute ATR for each bar.
    2. Count consecutive bars where each bar's ATR < contraction_ratio * previous ATR.
    3. Once min_contractions consecutive contractions are detected, watch for a
       breakout: close > SMA(ma_period).
    4. BUY on breakout candle.
    5. SELL when close falls back below SMA (failed breakout / reversion exit).
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import atr, sma
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.volatility_vcp")


class VCPBreakout(BaseStrategy, _BacktestStrategyMixin):
    """Volatility Contraction Pattern breakout strategy.

    Waits for a sequence of ATR contractions followed by a price breakout
    above a moving average. Exits when price closes back below the MA.

    Args:
        atr_period: ATR calculation period (default 14).
        contraction_ratio: Each ATR must be less than this fraction of the
            previous ATR (default 0.8, i.e. 80% of prior bar's ATR).
        min_contractions: Minimum consecutive contraction bars required
            before watching for a breakout (default 3).
        ma_period: SMA period for the breakout level (default 20).
        symbol: Instrument symbol (default "").
        exchange: Exchange code (default "NSE").
        product: Product type (default "MIS").
    """

    def __init__(
        self,
        name: str = "VCPBreakout",
        exchange: str = "NSE",
        product: str = "MIS",
        atr_period: int = 14,
        contraction_ratio: float = 0.8,
        min_contractions: int = 3,
        ma_period: int = 20,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.atr_period = atr_period
        self.contraction_ratio = contraction_ratio
        self.min_contractions = min_contractions
        self.ma_period = ma_period
        self._symbol = symbol
        self._init_history()
        self._contraction_count: int = 0

    def on_tick(self, quote: Quote) -> None:
        """Not used — bar-close strategy."""

    def on_bar(self, bar: OHLCV) -> None:
        """Process a completed bar, track contractions, and fire on breakout.

        Args:
            bar: The just-closed OHLCV bar.
        """
        if not self.is_active:
            return
        self._record_bar(bar)
        min_bars = max(self.atr_period, self.ma_period) + 2
        if len(self._closes) < min_bars:
            return

        atr_vals = atr(self._highs, self._lows, self._closes, self.atr_period)
        ma_vals = sma(self._closes, self.ma_period)

        cur_atr = atr_vals[-1]
        prev_atr = atr_vals[-2]
        cur_ma = ma_vals[-1]
        close = self._closes[-1]

        if cur_atr == 0 or prev_atr == 0 or cur_ma == 0:
            return

        # Update contraction streak
        if cur_atr < self.contraction_ratio * prev_atr:
            self._contraction_count += 1
        else:
            self._contraction_count = 0

        vcp_setup = self._contraction_count >= self.min_contractions

        if self._position == 0:
            if vcp_setup and close > cur_ma:
                logger.debug(
                    "VCP breakout | contractions=%d atr=%.4f ma=%.2f close=%.2f | %s",
                    self._contraction_count,
                    cur_atr,
                    cur_ma,
                    close,
                    self._symbol,
                )
                self._buy()
        elif self._position == 1:
            # Exit when close falls back below MA
            if close < cur_ma:
                logger.debug(
                    "VCP exit | close=%.2f < ma=%.2f | %s", close, cur_ma, self._symbol
                )
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
