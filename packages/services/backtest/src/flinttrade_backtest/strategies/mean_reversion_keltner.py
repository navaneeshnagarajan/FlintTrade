"""Keltner Channel strategy — Mean Reversion category.

Keltner Channels use ATR-based bands around an EMA.
Price reversions from the outer channels signal mean-reversion trades.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import ema, sma
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.mean_reversion_keltner")


def atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> list[float]:
    """Average True Range.

    Args:
        highs: High prices.
        lows: Low prices.
        closes: Close prices.
        period: ATR period (default 14).

    Returns:
        ATR series; leading values are 0.0.
    """
    n = len(closes)
    if n == 0:
        return []
    tr: list[float] = [highs[0] - lows[0]]
    for i in range(1, n):
        tr.append(max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        ))
    return sma(tr, period)


def keltner_channel(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    ema_period: int = 20,
    atr_period: int = 14,
    multiplier: float = 2.0,
) -> tuple[list[float], list[float], list[float]]:
    """Keltner Channel bands.

    Args:
        highs: High prices.
        lows: Low prices.
        closes: Close prices.
        ema_period: EMA period for midline (default 20).
        atr_period: ATR period for band width (default 14).
        multiplier: ATR multiplier (default 2.0).

    Returns:
        Tuple of (upper, middle, lower) channel bands.
    """
    mid = ema(closes, ema_period)
    atr_vals = atr(highs, lows, closes, atr_period)
    upper = [m + multiplier * a if m and a else 0.0 for m, a in zip(mid, atr_vals)]
    lower = [m - multiplier * a if m and a else 0.0 for m, a in zip(mid, atr_vals)]
    return upper, mid, lower


class KeltnerChannelReversion(BaseStrategy, _BacktestStrategyMixin):
    """Keltner Channel mean-reversion strategy.

    Buy when price touches lower channel and reverses; sell on upper channel touch.
    Exit at the midline (EMA).

    Args:
        ema_period: EMA period for midline (default 20).
        atr_period: ATR period (default 14).
        multiplier: ATR band multiplier (default 2.0).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "KeltnerReversion",
        exchange: str = "NSE",
        product: str = "MIS",
        ema_period: int = 20,
        atr_period: int = 14,
        multiplier: float = 2.0,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.ema_period = ema_period
        self.atr_period = atr_period
        self.multiplier = multiplier
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        min_bars = max(self.ema_period, self.atr_period) + 1
        if len(self._closes) < min_bars:
            return

        upper, mid, lower = keltner_channel(
            self._highs, self._lows, self._closes,
            self.ema_period, self.atr_period, self.multiplier,
        )

        if not all([upper[-1], mid[-1], lower[-1]]):
            return

        close = self._closes[-1]

        if close <= lower[-1] and self._closes[-2] > lower[-2]:
            self._buy()
        elif close >= upper[-1] and self._closes[-2] < upper[-2]:
            self._sell()
        # Exit at midline
        elif self._position == 1 and close >= mid[-1]:
            self._sell()
        elif self._position == -1 and close <= mid[-1]:
            self._buy()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
