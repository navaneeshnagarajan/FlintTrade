"""VIX-based volatility regime strategy — Volatility category.

Uses India VIX (or a synthetic VIX proxy from Nifty realised volatility)
to switch between trend-following and mean-reversion modes.

When VIX is high (fear), markets are volatile — use mean reversion.
When VIX is low (complacency), use trend-following.

In backtest mode, VIX is proxied from the rolling realised volatility
of the underlying instrument when no explicit VIX series is provided.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import bollinger_bands, ema
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.volatility_vix_based")


def realised_vol(closes: list[float], period: int = 20) -> list[float]:
    """Annualised realised volatility proxy (rolling log-return std * sqrt(252)).

    Args:
        closes: Close price series.
        period: Rolling window (default 20).

    Returns:
        Realised vol series as percentage (0-100 scale).
    """
    n = len(closes)
    result: list[float] = [0.0] * n
    for i in range(period, n):
        window = closes[i - period: i + 1]
        log_rets = [
            math.log(window[j] / window[j - 1])
            for j in range(1, len(window))
            if window[j - 1] > 0 and window[j] > 0
        ]
        if not log_rets:
            continue
        mean = sum(log_rets) / len(log_rets)
        variance = sum((r - mean) ** 2 for r in log_rets) / len(log_rets)
        result[i] = math.sqrt(variance * 252) * 100
    return result


class VIXRegime(BaseStrategy, _BacktestStrategyMixin):
    """VIX-regime switching strategy.

    High VIX (volatility > high_vix_threshold): mean-reversion mode
        - Buy on oversold (close < lower_bb), sell on overbought (close > upper_bb).
    Low VIX (volatility < low_vix_threshold): trend-following mode
        - Buy on EMA crossover up, sell on EMA crossover down.

    Args:
        vol_period: Realised vol lookback (default 20).
        high_vix: High volatility threshold in % (default 20).
        low_vix: Low volatility threshold in % (default 12).
        fast_ema: Fast EMA period for trend mode (default 9).
        slow_ema: Slow EMA period for trend mode (default 21).
        bb_std: Bollinger Band std for mean-reversion mode (default 2.0).
        bb_period: Bollinger Band period (default 20).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "VIXRegime",
        exchange: str = "NSE",
        product: str = "MIS",
        vol_period: int = 20,
        high_vix: float = 20.0,
        low_vix: float = 12.0,
        fast_ema: int = 9,
        slow_ema: int = 21,
        bb_std: float = 2.0,
        bb_period: int = 20,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.vol_period = vol_period
        self.high_vix = high_vix
        self.low_vix = low_vix
        self.fast_ema = fast_ema
        self.slow_ema = slow_ema
        self.bb_std = bb_std
        self.bb_period = bb_period
        self._symbol = symbol
        self._init_history()

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        min_bars = max(self.slow_ema, self.bb_period, self.vol_period) + 2
        if len(self._closes) < min_bars:
            return

        vol = realised_vol(self._closes, self.vol_period)
        cur_vol = vol[-1]

        if cur_vol >= self.high_vix:
            # Mean-reversion mode
            upper, mid, lower = bollinger_bands(self._closes, self.bb_period, self.bb_std)
            close = self._closes[-1]
            if close <= lower[-1] and self._closes[-2] > lower[-2]:
                self._buy()
            elif close >= upper[-1] and self._closes[-2] < upper[-2]:
                self._sell()
        elif cur_vol <= self.low_vix:
            # Trend-following mode
            fast = ema(self._closes, self.fast_ema)
            slow = ema(self._closes, self.slow_ema)
            if fast[-1] > slow[-1] and fast[-2] <= slow[-2]:
                self._buy()
            elif fast[-1] < slow[-1] and fast[-2] >= slow[-2]:
                self._sell()
        # In between: hold existing position, no new entries

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders
