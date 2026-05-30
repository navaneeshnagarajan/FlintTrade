"""Crypto Volume Profile Breakout strategy.

Detects breakouts confirmed by volume on 24/7 crypto markets.
Uses Donchian Channel for breakout level and OBV for volume confirmation.

24/7 market: no session-time checks.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import donchian_channel, ema
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.crypto_breakout_volume")


def _obv(closes: list[float], volumes: list[int]) -> list[float]:
    """On-Balance Volume."""
    result: list[float] = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            result.append(result[-1] + volumes[i])
        elif closes[i] < closes[i - 1]:
            result.append(result[-1] - volumes[i])
        else:
            result.append(result[-1])
    return result


class CryptoBreakoutVolume(BaseStrategy, _BacktestStrategyMixin):
    """Volume profile breakout on 24/7 crypto markets.

    Enters on Donchian Channel breakout confirmed by rising OBV.
    Exits when price drops back into the channel.

    24/7 market: no session-time checks.

    Args:
        period: Donchian Channel period (default 20).
        obv_ema_period: OBV EMA smoothing period (default 9).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "CryptoBreakoutVolume",
        exchange: str = "NSE",
        product: str = "MIS",
        period: int = 20,
        obv_ema_period: int = 9,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.period = period
        self.obv_ema_period = obv_ema_period
        self._symbol = symbol
        self._init_history()


    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        if len(self._closes) < self.period + self.obv_ema_period + 2:
            return

        upper, _, lower = donchian_channel(self._highs, self._lows, self.period)
        obv_vals = _obv(self._closes, self._volumes)
        obv_ema = ema(obv_vals, self.obv_ema_period)

        close = self._closes[-1]
        obv_rising = obv_vals[-1] > obv_ema[-1]
        obv_falling = obv_vals[-1] < obv_ema[-1]

        prev_close = self._closes[-2]
        breakout_up = close > upper[-2] and prev_close <= upper[-3]
        breakout_dn = close < lower[-2] and prev_close >= lower[-3]

        if breakout_up and obv_rising and self._position <= 0:
            self._buy()
        elif breakout_dn and obv_falling and self._position >= 0:
            self._sell()
        elif self._position == 1 and close < upper[-1]:
            self._sell()
        elif self._position == -1 and close > lower[-1]:
            self._buy()
            self._flat()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["CryptoBreakoutVolume"]
