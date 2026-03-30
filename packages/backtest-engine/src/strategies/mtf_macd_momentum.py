"""Multi-Timeframe MACD Momentum strategy.

Detects MACD histogram divergence across two timeframes: enters when the
higher-TF histogram is expanding in the same direction as a lower-TF crossover.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._indicators import macd
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.mtf_macd_momentum")


class MTFMACDMomentum(BaseStrategy, _BacktestStrategyMixin):
    """MACD histogram divergence across timeframes.

    LTF MACD signal line crossover triggers entry only when the HTF MACD
    histogram is expanding (positive momentum) in the same direction.

    Args:
        fast: MACD fast EMA period (default 12).
        slow: MACD slow EMA period (default 26).
        signal: MACD signal line period (default 9).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "MTFMACDMomentum",
        exchange: str = "NSE",
        product: str = "MIS",
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self._symbol = symbol
        self._init_history()
        self._htf_closes: list[float] = []


    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV, bars_htf: list[OHLCV] | None = None) -> None:
        self._record_bar(bar)

        if bars_htf:
            self._htf_closes = [b.close for b in bars_htf]

        warmup = self.slow + self.signal + 2
        if len(self._closes) < warmup:
            return

        ltf_line, ltf_sig, ltf_hist = macd(self._closes, self.fast, self.slow, self.signal)

        # LTF signal crossover
        ltf_cross_up = ltf_line[-1] > ltf_sig[-1] and ltf_line[-2] <= ltf_sig[-2]
        ltf_cross_dn = ltf_line[-1] < ltf_sig[-1] and ltf_line[-2] >= ltf_sig[-2]

        # HTF histogram expanding
        htf_hist_up = True
        htf_hist_dn = True
        if len(self._htf_closes) >= warmup:
            _, _, htf_hist = macd(self._htf_closes, self.fast, self.slow, self.signal)
            htf_hist_up = htf_hist[-1] > 0 and htf_hist[-1] > htf_hist[-2]
            htf_hist_dn = htf_hist[-1] < 0 and htf_hist[-1] < htf_hist[-2]

        if ltf_cross_up and htf_hist_up:
            self._buy()
        elif ltf_cross_dn and htf_hist_dn:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["MTFMACDMomentum"]
