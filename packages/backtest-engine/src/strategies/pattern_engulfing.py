"""Engulfing Candlestick Pattern strategy — Pattern category.

Detects bullish and bearish engulfing candle patterns with an SMA trend filter
to improve signal quality.

Pattern definitions:
    Bullish engulfing: Current bar is bullish (close > open) AND completely
        engulfs the prior bearish bar (open >= prior close, close <= prior open).
        Requires price to be BELOW SMA (downtrend context for reversal).

    Bearish engulfing: Current bar is bearish (close < open) AND completely
        engulfs the prior bullish bar (open <= prior close, close >= prior open).
        Requires price to be ABOVE SMA (uptrend context for reversal).
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._indicators import sma
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.pattern_engulfing")


class EngulfingPattern(BaseStrategy, _BacktestStrategyMixin):
    """Bullish/Bearish engulfing pattern with SMA trend filter.

    Bullish engulfing below SMA → BUY (mean-reversion / trend-reversal).
    Bearish engulfing above SMA → SELL.
    Exit after a fixed number of bars (time-based exit).

    Args:
        sma_period: SMA period for trend context filter (default 20).
        hold_bars: Exit after this many bars if no prior exit (default 5).
        symbol: Instrument symbol (default "").
        exchange: Exchange code (default "NSE").
        product: Product type (default "MIS").
    """

    def __init__(
        self,
        name: str = "EngulfingPattern",
        exchange: str = "NSE",
        product: str = "MIS",
        sma_period: int = 20,
        hold_bars: int = 5,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.sma_period = sma_period
        self.hold_bars = hold_bars
        self._symbol = symbol
        self._init_history()
        self._bars_in_trade: int = 0

    def on_tick(self, quote: Quote) -> None:
        """Not used — bar-close strategy."""

    def on_bar(self, bar: OHLCV) -> None:
        """Process a completed bar and detect engulfing patterns.

        Args:
            bar: The just-closed OHLCV bar.
        """
        if not self.is_active:
            return
        self._record_bar(bar)
        if len(self._closes) < self.sma_period + 1:
            return

        sma_vals = sma(self._closes, self.sma_period)
        cur_ma = sma_vals[-1]
        if cur_ma == 0:
            return

        # Current bar OHLC
        c_open = self._opens[-1]
        c_close = self._closes[-1]
        # Previous bar OHLC
        p_open = self._opens[-2]
        p_close = self._closes[-2]

        cur_bullish = c_close > c_open
        cur_bearish = c_close < c_open
        prev_bearish = p_close < p_open
        prev_bullish = p_close > p_open

        close = c_close

        # Time-based exit
        if self._position != 0:
            self._bars_in_trade += 1
            if self._bars_in_trade >= self.hold_bars:
                logger.debug(
                    "Time-exit | bars=%d pos=%d | %s",
                    self._bars_in_trade,
                    self._position,
                    self._symbol,
                )
                if self._position == 1:
                    self._sell()
                elif self._position == -1:
                    self._buy()
                self._flat()
                self._bars_in_trade = 0
                return

        if self._position == 0:
            # Bullish engulfing: current bullish bar engulfs previous bearish bar,
            # price below SMA (buying the dip in a downtrend / reversal)
            bull_engulf = (
                cur_bullish
                and prev_bearish
                and c_open <= p_close
                and c_close >= p_open
                and close < cur_ma
            )
            # Bearish engulfing: current bearish bar engulfs previous bullish bar,
            # price above SMA (selling the rally in an uptrend / reversal)
            bear_engulf = (
                cur_bearish
                and prev_bullish
                and c_open >= p_close
                and c_close <= p_open
                and close > cur_ma
            )

            if bull_engulf:
                logger.debug(
                    "Bullish engulf | open=%.2f close=%.2f | %s",
                    c_open,
                    c_close,
                    self._symbol,
                )
                self._buy()
                self._bars_in_trade = 0
            elif bear_engulf:
                logger.debug(
                    "Bearish engulf | open=%.2f close=%.2f | %s",
                    c_open,
                    c_close,
                    self._symbol,
                )
                self._sell()
                self._bars_in_trade = 0

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
