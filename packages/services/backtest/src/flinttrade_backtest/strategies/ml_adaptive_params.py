"""Machine Learning Adaptive Parameters strategy.

Self-tuning strategy that adjusts EMA and RSI periods via a simplified
Bayesian-inspired optimization using rolling Sharpe ratio feedback.
Falls back to sensible defaults if scipy/optuna are not available.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import ema, rsi
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.ml_adaptive_params")


def _rolling_sharpe(returns: list[float], period: int = 20) -> float:
    """Annualised Sharpe estimate from recent returns."""
    if len(returns) < period:
        return 0.0
    r = returns[-period:]
    mean_r = sum(r) / period
    std_r = (sum((x - mean_r) ** 2 for x in r) / period) ** 0.5
    if std_r == 0:
        return 0.0
    return mean_r / std_r * (252 ** 0.5)


class MLAdaptiveParams(BaseStrategy, _BacktestStrategyMixin):
    """Self-tuning EMA + RSI strategy with parameter adaptation.

    Periodically evaluates recent performance (Sharpe) for a small grid of
    parameter combinations and switches to the best-performing set.
    This is a lightweight Bayesian optimization surrogate.

    Args:
        adapt_interval: Bars between parameter re-evaluation (default 50).
        fast_candidates: Fast EMA period candidates (default [5, 9, 12]).
        rsi_candidates: RSI period candidates (default [10, 14, 20]).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "MLAdaptiveParams",
        exchange: str = "NSE",
        product: str = "MIS",
        adapt_interval: int = 50,
        fast_candidates: list[int] | None = None,
        rsi_candidates: list[int] | None = None,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.adapt_interval = adapt_interval
        self.fast_candidates: list[int] = fast_candidates or [5, 9, 12]
        self.rsi_candidates: list[int] = rsi_candidates or [10, 14, 20]
        self._symbol = symbol
        self._init_history()
        self._fast_period: int = 9
        self._rsi_period: int = 14
        self._last_adapt: int = 0
        self._bar_returns: list[float] = []


    def _evaluate_params(self, fast: int, rsi_p: int, closes: list[float]) -> float:
        """Simulate N-bar signal return for a parameter set; return Sharpe."""
        window = closes[-60:] if len(closes) >= 60 else closes
        if len(window) < max(fast, rsi_p) + 5:
            return 0.0
        ema_vals = ema(window, fast)
        rsi_vals = rsi(window, rsi_p)
        sim_returns: list[float] = []
        pos = 0
        for i in range(1, len(window)):
            prev_in_up = window[i - 1] > ema_vals[i - 1] and rsi_vals[i - 1] > 50
            in_up = window[i] > ema_vals[i] and rsi_vals[i] > 50
            if in_up and not prev_in_up:
                pos = 1
            elif not in_up and prev_in_up:
                pos = -1
            if pos != 0 and window[i - 1] > 0:
                sim_returns.append(pos * (window[i] - window[i - 1]) / window[i - 1])
        return _rolling_sharpe(sim_returns)

    def _adapt(self) -> None:
        """Select best parameter combination."""
        best_sharpe = -999.0
        best_fast, best_rsi = self._fast_period, self._rsi_period
        for fast in self.fast_candidates:
            for rsi_p in self.rsi_candidates:
                s = self._evaluate_params(fast, rsi_p, self._closes)
                if s > best_sharpe:
                    best_sharpe = s
                    best_fast, best_rsi = fast, rsi_p
        if best_fast != self._fast_period or best_rsi != self._rsi_period:
            logger.debug(
                "Adapting params: fast=%d→%d rsi=%d→%d sharpe=%.2f",
                self._fast_period, best_fast, self._rsi_period, best_rsi, best_sharpe,
            )
            self._fast_period = best_fast
            self._rsi_period = best_rsi

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        n = len(self._closes)

        # Track bar returns
        if n >= 2 and self._closes[-2] > 0:
            self._bar_returns.append(
                (self._closes[-1] - self._closes[-2]) / self._closes[-2]
            )

        warmup = max(max(self.fast_candidates), max(self.rsi_candidates)) + 10
        if n < warmup:
            return

        # Periodic adaptation
        if n - self._last_adapt >= self.adapt_interval:
            self._adapt()
            self._last_adapt = n

        ema_vals = ema(self._closes, self._fast_period)
        rsi_vals = rsi(self._closes, self._rsi_period)
        close = self._closes[-1]
        prev_close = self._closes[-2]

        in_up = close > ema_vals[-1] and rsi_vals[-1] > 50
        was_up = prev_close > ema_vals[-2] and rsi_vals[-2] > 50

        if in_up and not was_up and self._position <= 0:
            self._buy()
        elif not in_up and was_up and self._position >= 0:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["MLAdaptiveParams"]
