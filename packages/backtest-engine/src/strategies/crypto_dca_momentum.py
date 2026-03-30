"""Crypto DCA with Momentum Filter strategy.

Dollar-Cost Averaging with a momentum overlay: buy more aggressively when RSI
is low (oversold), buy less when RSI is high. Skips purchases when trend
is clearly bearish (EMA slope negative).

24/7 market: no session-time checks.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._indicators import rsi, ema
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.crypto_dca_momentum")


class CryptoDCAMomentum(BaseStrategy, _BacktestStrategyMixin):
    """DCA with momentum filter for crypto 24/7 markets.

    Buys every N bars (DCA interval). Multiplies buy size by momentum factor
    when RSI is below oversold threshold. Pauses DCA when EMA slope is negative.

    24/7 market: no session-time checks.

    Args:
        dca_interval: Bars between DCA purchases (default 24).
        rsi_period: RSI period (default 14).
        oversold_level: RSI threshold for increased DCA (default 35).
        ema_period: EMA period for trend filter (default 50).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "CryptoDCAMomentum",
        exchange: str = "NSE",
        product: str = "MIS",
        dca_interval: int = 24,
        rsi_period: int = 14,
        oversold_level: float = 35.0,
        ema_period: int = 50,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.dca_interval = dca_interval
        self.rsi_period = rsi_period
        self.oversold_level = oversold_level
        self.ema_period = ema_period
        self._symbol = symbol
        self._init_history()
        self._bars_since_dca: int = 0


    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        self._bars_since_dca += 1

        warmup = max(self.rsi_period, self.ema_period) + 2
        if len(self._closes) < warmup:
            return

        if self._bars_since_dca < self.dca_interval:
            return

        rsi_vals = rsi(self._closes, self.rsi_period)
        ema_vals = ema(self._closes, self.ema_period)

        # Trend filter: skip if EMA slope is negative
        ema_slope = ema_vals[-1] - ema_vals[-2]
        if ema_slope < 0:
            self._bars_since_dca = 0
            return

        # DCA buy; extra signal when oversold
        self._buy()
        self._bars_since_dca = 0

        if rsi_vals[-1] < self.oversold_level:
            # Double buy on oversold (send second order)
            self._buy()
            logger.debug("DCA double-buy: RSI=%.1f", rsi_vals[-1])

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["CryptoDCAMomentum"]
