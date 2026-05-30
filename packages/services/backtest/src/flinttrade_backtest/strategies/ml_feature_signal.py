"""Machine Learning Feature Signal strategy.

Uses LightGBM probability output to generate trade signals.
Falls back to simple RSI+EMA signal if lightgbm is not installed.

Features: returns, volatility, RSI, EMA ratio, volume change.
"""

from __future__ import annotations

import logging
from typing import Any

from flinttrade_core.models import OHLCV, Order, Quote
from flinttrade_engine.strategy import BaseStrategy

from ._indicators import rsi, ema, atr
from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.ml_feature_signal")

try:
    import lightgbm as lgb  # type: ignore[import]  # noqa: F401
    _LGBM_AVAILABLE = True
except (ImportError, OSError):
    lgb = None  # type: ignore[assignment]
    _LGBM_AVAILABLE = False
    logger.info("lightgbm unavailable; ML strategy uses RSI+EMA fallback")


def _make_features(
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[int],
    lookback: int = 20,
) -> list[float]:
    """Compute feature vector for the current bar."""
    if len(closes) < lookback + 2:
        return []
    c = closes[-lookback - 1:]
    ret1 = (c[-1] - c[-2]) / c[-2] if c[-2] != 0 else 0.0
    ret5 = (c[-1] - c[-6]) / c[-6] if len(c) >= 6 and c[-6] != 0 else 0.0
    rsi_val = rsi(closes, 14)[-1]
    ema20 = ema(closes, 20)[-1]
    ema_ratio = closes[-1] / ema20 if ema20 != 0 else 1.0
    atr_vals = atr(highs, lows, closes, 14)
    atr_val = atr_vals[-1] / closes[-1] if closes[-1] != 0 else 0.0
    vol_chg = 0.0
    if len(volumes) >= 6 and volumes[-6] > 0:
        vol_chg = (volumes[-1] - volumes[-6]) / volumes[-6]
    return [ret1, ret5, rsi_val / 100.0, ema_ratio - 1.0, atr_val, vol_chg]


class MLFeatureSignal(BaseStrategy, _BacktestStrategyMixin):
    """LightGBM probability → trade signal.

    If lightgbm is available, uses a pre-fitted model (set via set_model()).
    Without a model, trains online with a simple majority-vote heuristic.
    Fallback: RSI + EMA crossover signal.

    Args:
        warmup: Bars before first signal (default 50).
        prob_threshold: Probability threshold to enter long (default 0.6).
        lookback: Feature lookback window (default 20).
        symbol: Instrument symbol.
    """

    def __init__(
        self,
        name: str = "MLFeatureSignal",
        exchange: str = "NSE",
        product: str = "MIS",
        warmup: int = 50,
        prob_threshold: float = 0.6,
        lookback: int = 20,
        symbol: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self.warmup = warmup
        self.prob_threshold = prob_threshold
        self.lookback = lookback
        self._symbol = symbol
        self._init_history()
        self._model: Any = None


    def set_model(self, model: Any) -> None:
        """Inject a fitted LightGBM Booster or sklearn-compatible model.

        Args:
            model: Fitted model with predict_proba() or predict() method.
        """
        self._model = model

    def on_tick(self, quote: Quote) -> None:
        pass

    def on_bar(self, bar: OHLCV) -> None:
        self._record_bar(bar)
        if len(self._closes) < self.warmup:
            return

        feats = _make_features(
            self._closes, self._highs, self._lows, self._volumes, self.lookback
        )
        if not feats:
            return

        # LightGBM path
        if _LGBM_AVAILABLE and self._model is not None:
            try:
                prob = float(self._model.predict([feats])[0])
                if prob >= self.prob_threshold and self._position <= 0:
                    self._buy()
                elif prob <= (1 - self.prob_threshold) and self._position >= 0:
                    self._sell()
                return
            except Exception as exc:
                logger.warning("LightGBM predict failed: %s", exc)

        # Fallback: RSI + EMA crossover
        rsi_vals = rsi(self._closes, 14)
        ema_vals = ema(self._closes, 20)
        cross_up = self._closes[-1] > ema_vals[-1] and self._closes[-2] <= ema_vals[-2]
        cross_dn = self._closes[-1] < ema_vals[-1] and self._closes[-2] >= ema_vals[-2]
        if cross_up and rsi_vals[-1] > 50 and self._position <= 0:
            self._buy()
        elif cross_dn and rsi_vals[-1] < 50 and self._position >= 0:
            self._sell()

    def on_signal(self, signal: dict[str, Any]) -> None:
        pass

    def generate_orders(self) -> list[Order]:
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders


__all__ = ["MLFeatureSignal"]
