"""Intraday Pre-Market OI and Delivery Data Bias strategy (India-specific).

Uses pre-market open interest data and delivery percentage to determine
directional bias for the trading day. Higher delivery % + OI build = bullish.
Lower delivery % + OI decline = bearish.

The pre-market data (oi_change_pct, delivery_pct) must be injected as
kwargs in on_bar() or set externally before market open.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import rsi
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.intraday_pre_market")


class IntradayPreMarket(BaseStrategy, _BacktestStrategyMixin):
    """Pre-market OI + delivery data directional bias strategy.

    Pre-market bias is updated by calling set_premarket_data() before each
    session. Strategy only trades in the direction of the bias.

    Args:
        oi_threshold: OI change % threshold to signal direction (default 5.0).
        delivery_threshold: Delivery % threshold for bullish/bearish (default 50.0).
        rsi_period: RSI period for entry timing (default 14).
        session_open: Session open time HH:MM (default "09:15").
        session_close: Force-exit HH:MM (default "15:15").
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "IntradayPreMarket",
        exchange: str = "NSE",
        product: str = "MIS",
        oi_threshold: float = 5.0,
        delivery_threshold: float = 50.0,
        rsi_period: int = 14,
        session_open: str = "09:15",
        session_close: str = "15:15",
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.oi_threshold = oi_threshold
        self.delivery_threshold = delivery_threshold
        self.rsi_period = rsi_period
        self.session_open = session_open
        self.session_close = session_close
        self._symbol = symbol
        self._init_history()
        self._daily_bias: int = 0  # +1 bullish, -1 bearish, 0 neutral


    def set_premarket_data(
        self,
        oi_change_pct: float = 0.0,
        delivery_pct: float = 50.0,
    ) -> None:
        """Inject pre-market data for next session.

        Args:
            oi_change_pct: OI change % vs previous session.
            delivery_pct: Delivery percentage of traded volume.
        """
        if oi_change_pct > self.oi_threshold and delivery_pct > self.delivery_threshold:
            self._daily_bias = 1
        elif oi_change_pct < -self.oi_threshold and delivery_pct < self.delivery_threshold:
            self._daily_bias = -1
        else:
            self._daily_bias = 0
        logger.debug("Pre-market bias set to %d", self._daily_bias)

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

        if self._daily_bias == 0 or len(self._closes) < self.rsi_period + 2:
            return

        rsi_vals = rsi(self._closes, self.rsi_period)

        if self._daily_bias == 1:
            # Bullish bias: enter long on RSI pullback
            if rsi_vals[-1] > 40 and rsi_vals[-2] <= 40 and self._position <= 0:
                self._buy()
        elif self._daily_bias == -1:
            # Bearish bias: enter short on RSI rally
            if rsi_vals[-1] < 60 and rsi_vals[-2] >= 60 and self._position >= 0:
                self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["IntradayPreMarket"]
