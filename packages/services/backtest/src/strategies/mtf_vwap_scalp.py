"""Multi-Timeframe VWAP Scalp strategy.

Uses weekly VWAP as bias anchor; entries on 5-min VWAP reversion.
When price is above weekly VWAP, only take long reversion trades on intraday dips.
When price is below weekly VWAP, only take short reversion trades on intraday spikes.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.mtf_vwap_scalp")


def _vwap(closes: list[float], volumes: list[int]) -> list[float]:
    """Compute running VWAP from close * volume."""
    result: list[float] = []
    cum_pv = 0.0
    cum_v = 0.0
    for c, v in zip(closes, volumes):
        cum_pv += c * v
        cum_v += v
        result.append(cum_pv / cum_v if cum_v > 0 else c)
    return result


class MTFVWAPScalp(BaseStrategy, _BacktestStrategyMixin):
    """Weekly VWAP bias + intraday VWAP reversion scalp.

    Bias is determined by the price position relative to a higher-timeframe VWAP.
    Entries fire when the lower-timeframe price touches and bounces from its own VWAP.

    Args:
        touch_pct: How close to VWAP (as % of price) to consider a touch (default 0.1).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "MTFVWAPScalp",
        exchange: str = "NSE",
        product: str = "MIS",
        touch_pct: float = 0.1,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.touch_pct = touch_pct
        self._symbol = symbol
        self._init_history()
        self._htf_vwap: float = 0.0


    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV, bars_htf: list[OHLCV] | None = None) -> None:
        self._record_bar(bar)

        if bars_htf:
            htf_c = [b.close for b in bars_htf]
            htf_v = [b.volume for b in bars_htf]
            htf_vwap = _vwap(htf_c, htf_v)
            self._htf_vwap = htf_vwap[-1]

        if len(self._closes) < 5:
            return

        ltf_vwap = _vwap(self._closes, self._volumes)
        close = self._closes[-1]
        vwap_now = ltf_vwap[-1]
        touch_band = vwap_now * self.touch_pct / 100

        touching_vwap = abs(close - vwap_now) <= touch_band

        if not touching_vwap:
            return

        htf_bullish = self._htf_vwap == 0.0 or close > self._htf_vwap
        htf_bearish = self._htf_vwap == 0.0 or close < self._htf_vwap

        prev_close = self._closes[-2]
        bouncing_up = close > prev_close
        bouncing_dn = close < prev_close

        if htf_bullish and bouncing_up:
            self._buy()
        elif htf_bearish and bouncing_dn:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["MTFVWAPScalp"]
