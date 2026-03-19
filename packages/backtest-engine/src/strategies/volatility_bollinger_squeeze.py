"""Bollinger Band Squeeze strategy — Volatility category.

A squeeze occurs when Bollinger Bands narrow (low volatility compression).
The breakout after the squeeze is often explosive. This strategy detects
squeezes and trades the subsequent expansion.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._indicators import bollinger_bands
from ._mixin import _BacktestStrategyMixin
from .mean_reversion_keltner import keltner_channel

logger = logging.getLogger("flinttrade.backtest.strategies.volatility_bollinger_squeeze")


class BollingerSqueeze(BaseStrategy, _BacktestStrategyMixin):
    """Bollinger Band Squeeze breakout strategy.

    Squeeze condition: Bollinger Bands are inside Keltner Channels.
    Entry: Price breaks out of Bollinger Bands after squeeze releases.
    Uses momentum bar direction to determine long/short.

    Args:
        bb_period: Bollinger Band period (default 20).
        bb_std: Bollinger Band standard deviation multiplier (default 2.0).
        kc_ema_period: Keltner Channel EMA period (default 20).
        kc_atr_period: Keltner Channel ATR period (default 14).
        kc_mult: Keltner Channel ATR multiplier (default 1.5).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "BollingerSqueeze",
        exchange: str = "NSE",
        product: str = "MIS",
        bb_period: int = 20,
        bb_std: float = 2.0,
        kc_ema_period: int = 20,
        kc_atr_period: int = 14,
        kc_mult: float = 1.5,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.kc_ema_period = kc_ema_period
        self.kc_atr_period = kc_atr_period
        self.kc_mult = kc_mult
        self._symbol = symbol
        self._init_history()
        self._squeeze_active = False

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        min_bars = max(self.bb_period, self.kc_ema_period, self.kc_atr_period) + 2
        if len(self._closes) < min_bars:
            return

        bb_upper, bb_mid, bb_lower = bollinger_bands(self._closes, self.bb_period, self.bb_std)
        kc_upper, _, kc_lower = keltner_channel(
            self._highs, self._lows, self._closes,
            self.kc_ema_period, self.kc_atr_period, self.kc_mult,
        )

        if not all([bb_upper[-1], bb_lower[-1], kc_upper[-1], kc_lower[-1]]):
            return

        # Squeeze: BB inside KC
        in_squeeze = bb_upper[-1] < kc_upper[-1] and bb_lower[-1] > kc_lower[-1]
        was_in_squeeze = self._squeeze_active
        self._squeeze_active = in_squeeze

        # Squeeze release: was in squeeze, now out
        squeeze_release = was_in_squeeze and not in_squeeze

        if squeeze_release and self._position == 0:
            close = self._closes[-1]
            mid = bb_mid[-1]
            if close > mid:
                self._buy()
            elif close < mid:
                self._sell()

        # Exit when price returns to midband
        if self._position == 1 and self._closes[-1] <= bb_mid[-1]:
            self._sell()
        elif self._position == -1 and self._closes[-1] >= bb_mid[-1]:
            self._buy()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
