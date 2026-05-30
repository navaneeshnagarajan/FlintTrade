"""Machine Learning Regime Classifier strategy.

Uses a Random Forest to classify market regime (bull/bear/sideways) from
technical features. Falls back to a simple volatility-based regime if
sklearn is not installed.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import rsi, ema, atr, bollinger_bands
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.ml_regime_classifier")

try:
    from sklearn.ensemble import RandomForestClassifier  # type: ignore[import]
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False
    logger.info("sklearn not installed; using volatility-based fallback regime")


class MLRegimeClassifier(BaseStrategy, _BacktestStrategyMixin):
    """Random Forest market regime classifier.

    Classifies the current bar into: 1 (bull), -1 (bear), 0 (sideways).
    Enters long in bull regime, short in bear, flat in sideways.

    Without sklearn, falls back to BB width + RSI regime heuristic.

    Args:
        warmup: Bars before classification (default 60).
        retrain_interval: Bars between model retraining (default 100).
        lookback: Feature window (default 20).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "MLRegimeClassifier",
        exchange: str = "NSE",
        product: str = "MIS",
        warmup: int = 60,
        retrain_interval: int = 100,
        lookback: int = 20,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.warmup = warmup
        self.retrain_interval = retrain_interval
        self.lookback = lookback
        self._symbol = symbol
        self._init_history()
        self._model: Any = None
        self._last_retrain: int = 0
        self._X: list[list[float]] = []
        self._y: list[int] = []


    def _make_features(self) -> list[float]:
        closes = self._closes
        if len(closes) < self.lookback + 2:
            return []
        rsi_val = rsi(closes, 14)[-1]
        ema20 = ema(closes, 20)[-1]
        ema50 = ema(closes, 50)[-1] if len(closes) >= 52 else ema20
        ema_ratio = ema20 / ema50 if ema50 != 0 else 1.0
        atr_vals = atr(self._highs, self._lows, closes, 14)
        atr_norm = atr_vals[-1] / closes[-1] if closes[-1] != 0 else 0.0
        upper, mid, lower = bollinger_bands(closes, 20)
        bw = (upper[-1] - lower[-1]) / mid[-1] if mid[-1] != 0 else 0.0
        ret5 = (closes[-1] - closes[-6]) / closes[-6] if len(closes) >= 6 and closes[-6] != 0 else 0.0
        return [rsi_val / 100.0, ema_ratio - 1.0, atr_norm, bw, ret5]

    def _label(self) -> int:
        """Simple forward return label for training."""
        if len(self._closes) < 6:
            return 0
        fwd = (self._closes[-1] - self._closes[-6]) / self._closes[-6] if self._closes[-6] != 0 else 0.0
        if fwd > 0.005:
            return 1
        if fwd < -0.005:
            return -1
        return 0

    def _fallback_regime(self) -> int:
        """Heuristic regime from BB width + RSI."""
        closes = self._closes
        rsi_val = rsi(closes, 14)[-1]
        ema50 = ema(closes, 50)[-1] if len(closes) >= 52 else closes[-1]
        if closes[-1] > ema50 and rsi_val > 55:
            return 1
        if closes[-1] < ema50 and rsi_val < 45:
            return -1
        return 0

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        n = len(self._closes)

        if n < self.warmup:
            return

        feats = self._make_features()
        if not feats:
            return

        # Collect training data
        label = self._label()
        self._X.append(feats)
        self._y.append(label)

        if _SKLEARN_AVAILABLE:
            # Retrain periodically
            if n - self._last_retrain >= self.retrain_interval and len(set(self._y)) >= 2:
                clf = RandomForestClassifier(n_estimators=50, max_depth=5, random_state=42)
                clf.fit(self._X[-200:], self._y[-200:])
                self._model = clf
                self._last_retrain = n

            if self._model is not None:
                try:
                    regime = int(self._model.predict([feats])[0])
                except Exception:
                    regime = self._fallback_regime()
            else:
                regime = self._fallback_regime()
        else:
            regime = self._fallback_regime()

        if regime == 1 and self._position <= 0:
            self._buy()
        elif regime == -1 and self._position >= 0:
            self._sell()
        elif regime == 0 and self._position != 0:
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


__all__ = ["MLRegimeClassifier"]
