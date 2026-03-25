"""MACD Histogram Divergence strategy — Momentum category.

Detects divergence between price and the MACD histogram:

    Bullish divergence:
        - Price makes a lower low over the lookback window.
        - MACD histogram makes a higher low (less negative).
        → Momentum turning up before price — BUY.

    Bearish divergence:
        - Price makes a higher high over the lookback window.
        - MACD histogram makes a lower high (less positive).
        → Momentum turning down before price — SELL.

This is different from MACDSignal (zero-line crossover): divergence signals
fire when momentum diverges from price, often giving earlier entries.

Exit: held for hold_bars bars then flat, or when MACD histogram flips sign.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._indicators import macd
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.momentum_macd_divergence")


class MACDDivergence(BaseStrategy, _BacktestStrategyMixin):
    """MACD histogram divergence strategy.

    Bullish: price lower low + histogram higher low → BUY.
    Bearish: price higher high + histogram lower high → SELL.
    Exit: after hold_bars bars or on histogram sign reversal.

    Args:
        fast: MACD fast EMA period (default 12).
        slow: MACD slow EMA period (default 26).
        signal: MACD signal EMA period (default 9).
        lookback: Bars to look back for divergence comparison (default 5).
        hold_bars: Maximum bars to hold the position (default 8).
        symbol: Instrument symbol (default "").
        exchange: Exchange code (default "NSE").
        product: Product type (default "MIS").
    """

    def __init__(
        self,
        name: str = "MACDDivergence",
        exchange: str = "NSE",
        product: str = "MIS",
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        lookback: int = 5,
        hold_bars: int = 8,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.fast = fast
        self.slow = slow
        self.signal_period = signal
        self.lookback = lookback
        self.hold_bars = hold_bars
        self._symbol = symbol
        self._init_history()
        self._bars_in_trade: int = 0

    def on_tick(self, quote: Quote) -> None:
        """Not used — bar-close strategy."""

    def on_bar(self, bar: OHLCV) -> None:
        """Process a completed bar and detect MACD histogram divergence.

        Args:
            bar: The just-closed OHLCV bar.
        """
        if not self.is_active:
            return
        self._record_bar(bar)

        min_bars = self.slow + self.signal_period + self.lookback + 2
        if len(self._closes) < min_bars:
            return

        _, _, hist = macd(self._closes, self.fast, self.slow, self.signal_period)
        prices = self._closes
        lb = self.lookback

        # Time-based exit: check before entry logic
        if self._position != 0:
            self._bars_in_trade += 1

            # Early exit: histogram flips sign (momentum has reversed fully)
            if self._position == 1 and hist[-1] < 0:
                logger.debug(
                    "Hist-flip exit (long) | hist=%.4f | %s",
                    hist[-1],
                    self._symbol,
                )
                self._sell()
                self._flat()
                self._bars_in_trade = 0
                return
            if self._position == -1 and hist[-1] > 0:
                logger.debug(
                    "Hist-flip exit (short) | hist=%.4f | %s",
                    hist[-1],
                    self._symbol,
                )
                self._buy()
                self._flat()
                self._bars_in_trade = 0
                return

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

        # --- Divergence detection ---
        # Window: the lb bars before the current bar
        price_window = prices[-lb - 1: -1]
        hist_window = hist[-lb - 1: -1]

        if not price_window or not hist_window:
            return

        cur_price = prices[-1]
        cur_hist = hist[-1]

        # Bullish divergence: price lower low, histogram higher low
        price_ll = cur_price < min(price_window)
        hist_hl = cur_hist > min(hist_window)
        if price_ll and hist_hl and self._position <= 0:
            logger.debug(
                "Bullish MACD divergence | price=%.2f hist=%.4f | %s",
                cur_price,
                cur_hist,
                self._symbol,
            )
            self._buy()
            self._bars_in_trade = 0

        # Bearish divergence: price higher high, histogram lower high
        price_hh = cur_price > max(price_window)
        hist_lh = cur_hist < max(hist_window)
        if price_hh and hist_lh and self._position >= 0:
            logger.debug(
                "Bearish MACD divergence | price=%.2f hist=%.4f | %s",
                cur_price,
                cur_hist,
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
