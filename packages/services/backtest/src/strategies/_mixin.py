"""BacktestStrategyMixin — standalone definition for use in strategy sub-modules.

This module provides _BacktestStrategyMixin independently from strategies.py
so that strategy sub-packages can import it without triggering circular
imports through strategies/__init__.py.
"""

from __future__ import annotations

from flinttrade_core.models import OHLCV, Order


class _BacktestStrategyMixin:
    """Mixin providing bar history tracking for backtest strategies.

    Provides _init_history(), _record_bar(), _buy(), _sell(), _flat()
    helpers used by all backtest strategy classes.
    """

    def _init_history(self) -> None:
        self._opens: list[float] = []
        self._highs: list[float] = []
        self._lows: list[float] = []
        self._closes: list[float] = []
        self._volumes: list[int] = []
        self._timestamps: list[str] = []
        self._pending_orders: list[Order] = []
        self._position: int = 0  # +1=long, -1=short, 0=flat

    def _record_bar(self, bar: OHLCV) -> None:
        self._opens.append(bar.open)
        self._highs.append(bar.high)
        self._lows.append(bar.low)
        self._closes.append(bar.close)
        self._volumes.append(bar.volume)
        self._timestamps.append(bar.timestamp)

    def _buy(self, qty: str = "1") -> None:
        if self._position <= 0:
            self._pending_orders.append(Order(
                symbol=getattr(self, "_symbol", ""),
                action="BUY",
                exchange=getattr(self, "exchange", "NSE"),
                quantity=qty,
                strategy=getattr(self, "name", "Flint"),
            ))
            self._position = 1

    def _sell(self, qty: str = "1") -> None:
        if self._position >= 0:
            self._pending_orders.append(Order(
                symbol=getattr(self, "_symbol", ""),
                action="SELL",
                exchange=getattr(self, "exchange", "NSE"),
                quantity=qty,
                strategy=getattr(self, "name", "Flint"),
            ))
            self._position = -1

    def _flat(self) -> None:
        self._position = 0
