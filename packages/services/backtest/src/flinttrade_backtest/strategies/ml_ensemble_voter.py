"""Machine Learning Ensemble Voter strategy.

Combines signals from 3+ sub-strategies via majority vote.
Any BaseStrategy + _BacktestStrategyMixin instances can be used as voters.
Falls back to using 3 built-in signal generators if no voters are provided.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import ema, macd, rsi
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.ml_ensemble_voter")


def _rsi_signal(closes: list[float]) -> int:
    if len(closes) < 16:
        return 0
    vals = rsi(closes, 14)
    if vals[-1] > 55 and vals[-2] <= 55:
        return 1
    if vals[-1] < 45 and vals[-2] >= 45:
        return -1
    return 0


def _ema_signal(closes: list[float]) -> int:
    if len(closes) < 22:
        return 0
    fast = ema(closes, 9)
    slow = ema(closes, 21)
    if fast[-1] > slow[-1] and fast[-2] <= slow[-2]:
        return 1
    if fast[-1] < slow[-1] and fast[-2] >= slow[-2]:
        return -1
    return 0


def _macd_signal(closes: list[float]) -> int:
    if len(closes) < 37:
        return 0
    line, sig, _ = macd(closes)
    if line[-1] > sig[-1] and line[-2] <= sig[-2]:
        return 1
    if line[-1] < sig[-1] and line[-2] >= sig[-2]:
        return -1
    return 0


class MLEnsembleVoter(BaseStrategy, _BacktestStrategyMixin):
    """Ensemble of 3+ strategies with majority vote signal aggregation.

    Built-in voters: RSI momentum, EMA crossover, MACD crossover.
    External voter strategies can be added via add_voter().
    Signal is taken only when vote count exceeds vote_threshold.

    Args:
        vote_threshold: Minimum majority votes to act (default 2).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "MLEnsembleVoter",
        exchange: str = "NSE",
        product: str = "MIS",
        vote_threshold: int = 2,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.vote_threshold = vote_threshold
        self._symbol = symbol
        self._init_history()
        self._voters: list[Any] = []  # external strategy instances


    def add_voter(self, strategy: Any) -> None:
        """Add an external strategy as a voter.

        Args:
            strategy: Any BaseStrategy + _BacktestStrategyMixin instance.
        """
        self._voters.append(strategy)

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)

        # Feed all external voters
        for voter in self._voters:
            try:
                voter.on_bar(bar)
            except Exception as exc:
                logger.warning("Voter %s failed: %s", getattr(voter, "name", "?"), exc)

        if len(self._closes) < 40:
            return

        # Built-in signals
        votes = [
            _rsi_signal(self._closes),
            _ema_signal(self._closes),
            _macd_signal(self._closes),
        ]

        # External voter signals (via pending orders inspection)
        for voter in self._voters:
            orders = []
            try:
                orders = voter.generate_orders()
            except Exception:
                pass
            if orders:
                last = orders[-1]
                if hasattr(last, "action"):
                    if last.action == "BUY":
                        votes.append(1)
                    elif last.action == "SELL":
                        votes.append(-1)
                    else:
                        votes.append(0)

        bull_votes = sum(1 for v in votes if v == 1)
        bear_votes = sum(1 for v in votes if v == -1)

        if bull_votes >= self.vote_threshold and self._position <= 0:
            self._buy()
        elif bear_votes >= self.vote_threshold and self._position >= 0:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["MLEnsembleVoter"]
