"""Intraday VWAP Touch-and-Bounce strategy (India-specific).

Enters when price touches the intraday VWAP with a volume spike,
expecting a bounce back. Works best on trending stocks in range markets.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.intraday_vwap_bounce")


def _running_vwap(closes: list[float], volumes: list[int]) -> list[float]:
    """Cumulative VWAP from session start."""
    result: list[float] = []
    cum_pv = 0.0
    cum_v = 0.0
    for c, v in zip(closes, volumes):
        cum_pv += c * v
        cum_v += v
        result.append(cum_pv / cum_v if cum_v > 0 else c)
    return result


class IntradayVWAPBounce(BaseStrategy, _BacktestStrategyMixin):
    """VWAP touch and bounce with volume spike filter.

    Detects when price touches VWAP (within touch_pct band) with a volume
    spike (>= vol_mult * recent average) and then bounces in the expected
    direction (above VWAP: bounce up; below VWAP: bounce down).

    Args:
        touch_pct: Max distance from VWAP as % of price (default 0.15).
        vol_mult: Volume spike multiplier vs recent average (default 1.8).
        session_open: Session open HH:MM to reset VWAP (default "09:15").
        session_close: Force-exit HH:MM (default "15:15").
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "IntradayVWAPBounce",
        exchange: str = "NSE",
        product: str = "MIS",
        touch_pct: float = 0.15,
        vol_mult: float = 1.8,
        session_open: str = "09:15",
        session_close: str = "15:15",
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.touch_pct = touch_pct
        self.vol_mult = vol_mult
        self.session_open = session_open
        self.session_close = session_close
        self._symbol = symbol
        self._init_history()
        self._session_closes: list[float] = []
        self._session_vols: list[int] = []


    def on_tick(self, quote: Quote) -> None:
        pass

    def _time_part(self, ts: str) -> str:
        return ts[11:16] if len(ts) > 16 else ""

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        tp = self._time_part(bar.timestamp)

        if tp == self.session_open:
            self._session_closes = []
            self._session_vols = []

        self._session_closes.append(bar.close)
        self._session_vols.append(bar.volume)

        if tp >= self.session_close and self._position != 0:
            if self._position > 0:
                self._sell()
            else:
                self._buy()
                self._flat()
            return

        if len(self._session_closes) < 5:
            return

        vwap_series = _running_vwap(self._session_closes, self._session_vols)
        vwap = vwap_series[-1]
        close = bar.close
        band = vwap * self.touch_pct / 100
        touching = abs(close - vwap) <= band

        if not touching:
            return

        # Volume spike check
        avg_vol = sum(self._session_vols[-6:-1]) / 5
        vol_spike = bar.volume >= avg_vol * self.vol_mult if avg_vol > 0 else False

        if not vol_spike:
            return

        prev_close = self._session_closes[-2]
        bouncing_up = close > prev_close and close > vwap
        bouncing_dn = close < prev_close and close < vwap

        if bouncing_up and self._position <= 0:
            self._buy()
        elif bouncing_dn and self._position >= 0:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["IntradayVWAPBounce"]
