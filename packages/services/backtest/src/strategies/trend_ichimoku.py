"""Ichimoku Cloud strategy — Trend category.

Classic Ichimoku Kinko Hyo strategy using Tenkan/Kijun crossover confirmed
by price position relative to the Kumo (cloud).
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.trend_ichimoku")


def ichimoku(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_b_period: int = 52,
    displacement: int = 26,
) -> tuple[list[float], list[float], list[float], list[float], list[float]]:
    """Compute Ichimoku components.

    Args:
        highs: High prices.
        lows: Low prices.
        closes: Close prices.
        tenkan_period: Conversion line period (default 9).
        kijun_period: Base line period (default 26).
        senkou_b_period: Leading Span B period (default 52).
        displacement: Cloud displacement forward (default 26).

    Returns:
        Tuple of (tenkan, kijun, senkou_a, senkou_b, chikou) aligned to current index.
        Values before warm-up are 0.0.
    """
    n = len(closes)
    nan = 0.0

    def mid_range(period: int, i: int) -> float:
        if i < period - 1:
            return nan
        window_h = highs[i - period + 1: i + 1]
        window_l = lows[i - period + 1: i + 1]
        return (max(window_h) + min(window_l)) / 2

    tenkan: list[float] = [mid_range(tenkan_period, i) for i in range(n)]
    kijun: list[float] = [mid_range(kijun_period, i) for i in range(n)]

    # Senkou A displaced forward by 'displacement'
    senkou_a: list[float] = [0.0] * n
    for i in range(n):
        ta = tenkan[i]
        ki = kijun[i]
        if ta and ki:
            fwd = i + displacement
            if fwd < n:
                senkou_a[fwd] = (ta + ki) / 2

    # Senkou B displaced forward
    senkou_b: list[float] = [0.0] * n
    for i in range(n):
        sb = mid_range(senkou_b_period, i)
        if sb:
            fwd = i + displacement
            if fwd < n:
                senkou_b[fwd] = sb

    # Chikou: current close plotted 'displacement' bars back (align to current index)
    chikou: list[float] = [0.0] * n
    for i in range(n):
        back = i - displacement
        if back >= 0:
            chikou[i] = closes[back]

    return tenkan, kijun, senkou_a, senkou_b, chikou


class IchimokuCloud(BaseStrategy, _BacktestStrategyMixin):
    """Ichimoku Cloud trend-following strategy.

    Entry conditions:
    - Tenkan crosses above Kijun (bullish TK cross) — buy.
    - Price is above both Senkou A and Senkou B (above cloud) — confirmation.
    Exit: Tenkan crosses below Kijun or price enters cloud.

    Args:
        tenkan_period: Conversion line period (default 9).
        kijun_period: Base line period (default 26).
        senkou_b_period: Leading Span B lookback (default 52).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "IchimokuCloud",
        exchange: str = "NSE",
        product: str = "MIS",
        tenkan_period: int = 9,
        kijun_period: int = 26,
        senkou_b_period: int = 52,
        displacement: int = 26,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.tenkan_period = tenkan_period
        self.kijun_period = kijun_period
        self.senkou_b_period = senkou_b_period
        self.displacement = displacement
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        min_bars = self.senkou_b_period + self.displacement + 2
        if len(self._closes) < min_bars:
            return

        tenkan, kijun, sa, sb, _ = ichimoku(
            self._highs, self._lows, self._closes,
            self.tenkan_period, self.kijun_period, self.senkou_b_period, self.displacement,
        )

        cur = len(self._closes) - 1
        prev = cur - 1

        if not all([tenkan[cur], kijun[cur], tenkan[prev], kijun[prev]]):
            return

        close = self._closes[cur]
        cloud_top = max(sa[cur], sb[cur])
        cloud_bot = min(sa[cur], sb[cur])

        # Bullish TK cross above cloud
        tk_cross_up = tenkan[cur] > kijun[cur] and tenkan[prev] <= kijun[prev]
        # Bearish TK cross below cloud
        tk_cross_dn = tenkan[cur] < kijun[cur] and tenkan[prev] >= kijun[prev]

        if tk_cross_up and close > cloud_top:
            self._buy()
        elif tk_cross_dn and close < cloud_bot:
            self._sell()
        # Exit: price enters cloud
        elif self._position == 1 and close < cloud_bot:
            self._sell()
        elif self._position == -1 and close > cloud_top:
            self._buy()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
