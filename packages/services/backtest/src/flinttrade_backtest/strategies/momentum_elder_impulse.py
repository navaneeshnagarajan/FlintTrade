"""Elder Impulse System strategy — Momentum category.

The Elder Impulse System combines EMA direction with MACD histogram color to
classify each bar as:
    GREEN  — both EMA rising AND MACD histogram rising (trend + momentum aligned)
    RED    — both EMA falling AND MACD histogram falling
    BLUE   — mixed (no strong signal, exit zone)

Trading rules:
    BUY  on first GREEN bar (EMA slope up AND histogram slope up).
    SELL on first RED bar  (EMA slope down AND histogram slope down).
    FLAT when the bar is BLUE (neither condition) — do nothing with new entries.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import ema, macd
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.momentum_elder_impulse")


class ElderImpulse(BaseStrategy, _BacktestStrategyMixin):
    """Elder Impulse System — EMA direction + MACD histogram color.

    A GREEN bar (EMA rising + MACD histogram rising) triggers a BUY.
    A RED bar (EMA falling + MACD histogram falling) triggers a SELL.
    BLUE bars (mixed) block new entries and signal caution.

    Args:
        ema_period: EMA period for trend direction (default 13).
        macd_fast: MACD fast EMA period (default 12).
        macd_slow: MACD slow EMA period (default 26).
        macd_signal: MACD signal line EMA period (default 9).
        symbol: Instrument symbol (default "").
        exchange: Exchange code (default "NSE").
        product: Product type (default "MIS").
    """

    def __init__(
        self,
        name: str = "ElderImpulse",
        exchange: str = "NSE",
        product: str = "MIS",
        ema_period: int = 13,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.ema_period = ema_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        """Not used — bar-close strategy."""

    def on_bar(self, bar: OHLCV) -> None:
        """Process a completed bar and emit orders based on impulse color.

        Args:
            bar: The just-closed OHLCV bar.
        """
        if not self.is_active:
            return
        self._record_bar(bar)
        min_bars = self.macd_slow + self.macd_signal + 1
        if len(self._closes) < min_bars:
            return

        ema_vals = ema(self._closes, self.ema_period)
        _, _, hist = macd(self._closes, self.macd_fast, self.macd_slow, self.macd_signal)

        if len(ema_vals) < 2 or len(hist) < 2:
            return

        # EMA slope: rising when current > previous
        ema_rising = ema_vals[-1] > ema_vals[-2]
        ema_falling = ema_vals[-1] < ema_vals[-2]

        # Histogram slope: rising when current > previous
        hist_rising = hist[-1] > hist[-2]
        hist_falling = hist[-1] < hist[-2]

        is_green = ema_rising and hist_rising
        is_red = ema_falling and hist_falling

        if is_green:
            logger.debug(
                "GREEN bar | ema=%.4f hist=%.4f | %s",
                ema_vals[-1] - ema_vals[-2],
                hist[-1],
                self._symbol,
            )
            self._buy()
        elif is_red:
            logger.debug(
                "RED bar | ema=%.4f hist=%.4f | %s",
                ema_vals[-1] - ema_vals[-2],
                hist[-1],
                self._symbol,
            )
            self._sell()
        # BLUE bar: mixed signals — do not enter, hold existing position

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
