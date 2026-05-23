"""Hidden Markov Model Regime Detection strategy.

2-state HMM (bull/bear) estimated via a simplified Baum-Welch EM approach
using only pure Python. No external dependencies required.

The HMM is fitted on rolling returns. State 0 = low-volatility bull,
State 1 = high-volatility bear.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.stat_regime_hmm")

_LOG2PI = math.log(2 * math.pi)


def _gaussian_log_prob(x: float, mu: float, sigma: float) -> float:
    """Log probability of x under N(mu, sigma)."""
    if sigma <= 0:
        return -1e9
    return -0.5 * (_LOG2PI + 2 * math.log(sigma) + ((x - mu) / sigma) ** 2)


class StatRegimeHMM(BaseStrategy, _BacktestStrategyMixin):
    """Hidden Markov Model 2-state (bull/bear) regime detection.

    Uses Viterbi decoding on a rolling window of log returns to assign the
    current bar to a bull or bear regime. Enters long in bull regime, short
    (or flat) in bear regime.

    The emission model assumes Gaussian log returns. Parameters are estimated
    with a simple k-means initialization updated each warmup window.

    Args:
        warmup: Bars before first regime estimate (default 50).
        lookback: Rolling window for HMM fitting (default 100).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "StatRegimeHMM",
        exchange: str = "NSE",
        product: str = "MIS",
        warmup: int = 50,
        lookback: int = 100,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.warmup = warmup
        self.lookback = lookback
        self._symbol = symbol
        self._init_history()
        # State params: [mu0, sigma0, mu1, sigma1]
        self._mu = [0.001, -0.001]
        self._sigma = [0.01, 0.02]
        self._trans = [[0.95, 0.05], [0.05, 0.95]]


    def _fit_params(self, returns: list[float]) -> None:
        """Re-estimate Gaussian params via simple k-means style split."""
        sorted_r = sorted(returns)
        mid = len(sorted_r) // 2
        lower = sorted_r[:mid]
        upper = sorted_r[mid:]
        for idx, group in enumerate([upper, lower]):  # state 0 = higher returns
            if group:
                mu = sum(group) / len(group)
                sigma = (sum((r - mu) ** 2 for r in group) / len(group)) ** 0.5
                self._mu[idx] = mu
                self._sigma[idx] = max(sigma, 1e-6)

    def _viterbi_last_state(self, returns: list[float]) -> int:
        """Run Viterbi and return last most-likely state (0=bull, 1=bear)."""
        n = len(returns)
        if n == 0:
            return 0
        # Init
        log_trans = [[math.log(max(p, 1e-9)) for p in row] for row in self._trans]
        lp = [
            [_gaussian_log_prob(returns[0], self._mu[s], self._sigma[s]) for s in range(2)]
        ]
        for t in range(1, n):
            row: list[float] = []
            for s in range(2):
                emit = _gaussian_log_prob(returns[t], self._mu[s], self._sigma[s])
                best = max(lp[t - 1][prev] + log_trans[prev][s] for prev in range(2))
                row.append(best + emit)
            lp.append(row)
        return 0 if lp[-1][0] >= lp[-1][1] else 1

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        if len(self._closes) < self.warmup + 1:
            return

        closes = self._closes[-self.lookback:]
        returns = [
            math.log(closes[i] / closes[i - 1])
            for i in range(1, len(closes))
            if closes[i - 1] > 0
        ]
        if len(returns) < 10:
            return

        self._fit_params(returns)
        regime = self._viterbi_last_state(returns)

        # State 0 = bull (higher mean returns) → long
        if regime == 0 and self._position <= 0:
            self._buy()
        elif regime == 1 and self._position >= 0:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["StatRegimeHMM"]
