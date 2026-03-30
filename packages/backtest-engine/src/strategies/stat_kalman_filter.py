"""Kalman Filter Dynamic Hedging strategy.

Implements a 1D Kalman filter to estimate a time-varying hedge ratio
between two instruments. Trades the spread based on innovation (prediction error).

Pure Python, no external dependencies.
"""

from __future__ import annotations

import logging
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.stat_kalman_filter")


class StatKalmanFilter(BaseStrategy, _BacktestStrategyMixin):
    """Kalman filter for dynamic hedge ratio estimation.

    The state vector is the hedge ratio beta. Observation: price_a = beta * price_b + spread.
    Trades are placed when the spread innovation exceeds the entry threshold.

    Args:
        delta: State noise variance (controls how fast beta adapts, default 1e-4).
        obs_noise: Observation noise variance (default 1e-3).
        entry_sigma: Innovation sigma multiples to enter (default 1.5).
        symbol: Symbol for leg A.
    """

    def __init__(
        self,
        name: str = "StatKalmanFilter",
        exchange: str = "NSE",
        product: str = "MIS",
        delta: float = 1e-4,
        obs_noise: float = 1e-3,
        entry_sigma: float = 1.5,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.delta = delta
        self.obs_noise = obs_noise
        self.entry_sigma = entry_sigma
        self._symbol = symbol
        self._init_history()
        self._b_closes: list[float] = []
        # Kalman state
        self._beta: float = 1.0
        self._P: float = 1.0  # error covariance
        self._innovations: list[float] = []


    def on_tick(self, quote: Quote) -> None:
        pass

    def _kalman_update(self, price_a: float, price_b: float) -> float:
        """One Kalman step; returns the spread innovation."""
        # Predict
        P_pred = self._P + self.delta

        # Innovation
        y_hat = self._beta * price_b
        innovation = price_a - y_hat

        # Innovation variance
        S = P_pred * price_b ** 2 + self.obs_noise

        # Kalman gain
        K = P_pred * price_b / S if S > 0 else 0.0

        # Update
        self._beta += K * innovation
        self._P = (1 - K * price_b) * P_pred

        return innovation

    def on_bar(self, bar: OHLCV, bars_b: list[OHLCV] | None = None) -> None:
        self._record_bar(bar)

        if bars_b:
            self._b_closes = [b.close for b in bars_b]

        if not self._b_closes or len(self._b_closes) < len(self._closes):
            return

        price_b = self._b_closes[len(self._closes) - 1]
        if price_b == 0:
            return

        innovation = self._kalman_update(self._closes[-1], price_b)
        self._innovations.append(innovation)

        if len(self._innovations) < 20:
            return

        window = self._innovations[-50:]
        mean = sum(window) / len(window)
        std = (sum((x - mean) ** 2 for x in window) / len(window)) ** 0.5
        if std == 0:
            return

        z = (innovation - mean) / std

        if z > self.entry_sigma and self._position >= 0:
            self._sell()  # spread too high, mean-revert
        elif z < -self.entry_sigma and self._position <= 0:
            self._buy()
        elif abs(z) < 0.5 and self._position != 0:
            if self._position > 0:
                self._sell()
            else:
                self._buy()
                self._flat()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["StatKalmanFilter"]
