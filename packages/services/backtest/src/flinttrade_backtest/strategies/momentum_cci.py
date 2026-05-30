"""CCI (Commodity Channel Index) strategy — Momentum category.

CCI measures deviation of price from its average. Values above +100 indicate
strong upward momentum; below -100 indicate downward momentum.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.momentum_cci")


def cci(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 20,
    constant: float = 0.015,
) -> list[float]:
    """Commodity Channel Index.

    Args:
        highs: High prices.
        lows: Low prices.
        closes: Close prices.
        period: CCI lookback (default 20).
        constant: Lambert's constant (default 0.015).

    Returns:
        CCI series; leading values are 0.0.
    """
    n = len(closes)
    typical = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(n)]
    result: list[float] = [0.0] * n

    for i in range(period - 1, n):
        window = typical[i - period + 1: i + 1]
        mean = sum(window) / period
        mad = sum(abs(v - mean) for v in window) / period
        result[i] = (typical[i] - mean) / (constant * mad) if mad != 0 else 0.0

    return result


class CCIStrategy(BaseStrategy, _BacktestStrategyMixin):
    """CCI momentum strategy.

    Buy when CCI crosses above upper threshold; sell when crosses below lower.
    Optionally exits when CCI returns to zero line.

    Args:
        period: CCI period (default 20).
        upper: Upper threshold for buy signal (default 100).
        lower: Lower threshold for sell signal (default -100).
        exit_on_zero: Close position when CCI crosses zero (default False).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "CCI",
        exchange: str = "NSE",
        product: str = "MIS",
        period: int = 20,
        upper: float = 100.0,
        lower: float = -100.0,
        exit_on_zero: bool = False,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.period = period
        self.upper = upper
        self.lower = lower
        self.exit_on_zero = exit_on_zero
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        if len(self._closes) < self.period + 1:
            return

        cci_vals = cci(self._highs, self._lows, self._closes, self.period)
        cur, prev = cci_vals[-1], cci_vals[-2]

        # Momentum entry
        if cur > self.upper and prev <= self.upper:
            self._buy()
        elif cur < self.lower and prev >= self.lower:
            self._sell()

        # Zero-line exit
        if self.exit_on_zero:
            if self._position == 1 and cur < 0 and prev >= 0:
                self._sell()
            elif self._position == -1 and cur > 0 and prev <= 0:
                self._buy()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
