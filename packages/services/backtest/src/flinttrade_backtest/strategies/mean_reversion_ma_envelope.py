"""Moving Average Envelope strategy — Mean Reversion category.

MA Envelopes place bands at a fixed percentage above and below a moving average.
Price mean-reverts from the outer bands back to the MA centre.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import ema, sma
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.mean_reversion_ma_envelope")


class MAEnvelope(BaseStrategy, _BacktestStrategyMixin):
    """Moving Average Envelope mean-reversion strategy.

    Bands = MA ± (MA * envelope_pct / 100).
    Buy when close drops below lower envelope; sell when above upper.
    Exit when price returns to the moving average.

    Args:
        period: MA period (default 20).
        envelope_pct: Band distance as percentage of MA (default 2.5).
        use_ema: Use EMA instead of SMA (default True).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "MAEnvelope",
        exchange: str = "NSE",
        product: str = "MIS",
        period: int = 20,
        envelope_pct: float = 2.5,
        use_ema: bool = True,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.period = period
        self.envelope_pct = envelope_pct
        self.use_ema = use_ema
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        if len(self._closes) < self.period + 1:
            return

        ma = ema(self._closes, self.period) if self.use_ema else sma(self._closes, self.period)
        ma_cur = ma[-1]
        ma_prev = ma[-2]
        if not ma_cur or not ma_prev:
            return

        upper = ma_cur * (1 + self.envelope_pct / 100)
        lower = ma_cur * (1 - self.envelope_pct / 100)
        upper_prev = ma_prev * (1 + self.envelope_pct / 100)
        lower_prev = ma_prev * (1 - self.envelope_pct / 100)

        close = self._closes[-1]
        close_prev = self._closes[-2]

        # Entry: price crosses below lower envelope
        if close < lower and close_prev >= lower_prev:
            self._buy()
        # Entry: price crosses above upper envelope
        elif close > upper and close_prev <= upper_prev:
            self._sell()
        # Exit: price returns to MA
        elif self._position == 1 and close >= ma_cur:
            self._sell()
        elif self._position == -1 and close <= ma_cur:
            self._buy()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
