"""Event-Driven FII/DII Daily Flow Directional Bias strategy (India-specific).

Foreign Institutional Investor (FII) and Domestic Institutional Investor (DII)
net buy/sell data is released daily post-market. Strong FII net buying on
prior day correlates with bullish next-day bias in NIFTY/BANKNIFTY.

Flow data is injected externally via set_flow_data() before the session.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import ema
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.event_fii_flow")


class EventFIIFlow(BaseStrategy, _BacktestStrategyMixin):
    """FII/DII daily flow-based directional bias strategy.

    Sets a bullish or bearish daily bias from prior-day FII/DII net flows.
    Trades intraday in the bias direction using EMA for entry timing.

    Args:
        fii_threshold: Net FII flow (Cr INR) to set strong bias (default 500.0).
        ema_period: EMA period for intraday entry (default 9).
        session_open: Session open HH:MM (default "09:15").
        session_close: Force-exit HH:MM (default "15:15").
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "EventFIIFlow",
        exchange: str = "NSE",
        product: str = "MIS",
        fii_threshold: float = 500.0,
        ema_period: int = 9,
        session_open: str = "09:15",
        session_close: str = "15:15",
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.fii_threshold = fii_threshold
        self.ema_period = ema_period
        self.session_open = session_open
        self.session_close = session_close
        self._symbol = symbol
        self._init_history()
        self._daily_bias: int = 0  # +1 bullish, -1 bearish, 0 neutral


    def set_flow_data(self, fii_net_cr: float, dii_net_cr: float = 0.0) -> None:
        """Set previous day FII/DII net flow for next session bias.

        Args:
            fii_net_cr: FII net buy (positive) / sell (negative) in Crore INR.
            dii_net_cr: DII net buy / sell in Crore INR.
        """
        combined = fii_net_cr + dii_net_cr * 0.3  # FII weighted heavier
        if combined > self.fii_threshold:
            self._daily_bias = 1
        elif combined < -self.fii_threshold:
            self._daily_bias = -1
        else:
            self._daily_bias = 0
        logger.debug("FII/DII bias: fii=%.0fCr combined=%.0fCr bias=%d",
                     fii_net_cr, combined, self._daily_bias)

    def on_tick(self, quote: Quote) -> None:
        pass

    def _time_part(self, ts: str) -> str:
        return ts[11:16] if len(ts) > 16 else ""

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        tp = self._time_part(bar.timestamp)

        if tp >= self.session_close and self._position != 0:
            if self._position > 0:
                self._sell()
            else:
                self._buy()
                self._flat()
            return

        if self._daily_bias == 0 or len(self._closes) < self.ema_period + 2:
            return

        ema_vals = ema(self._closes, self.ema_period)
        close = self._closes[-1]
        prev_close = self._closes[-2]
        ema_now = ema_vals[-1]
        ema_prev = ema_vals[-2]

        cross_up = close > ema_now and prev_close <= ema_prev
        cross_dn = close < ema_now and prev_close >= ema_prev

        if self._daily_bias == 1 and cross_up and self._position <= 0:
            self._buy()
        elif self._daily_bias == -1 and cross_dn and self._position >= 0:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["EventFIIFlow"]
