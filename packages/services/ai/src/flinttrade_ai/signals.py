"""ML signal generator using LightGBM.

Features: OHLCV price action, technical indicators (RSI, MACD, Supertrend,
Bollinger), OI data (PCR, max pain change, OI spurt), IV data (IV percentile,
skew). Predicts BUY/SELL/HOLD for next N candles with a confidence score.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

try:
    from numpy.typing import NDArray
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:  # numpy not installed — use plain lists throughout
    _NUMPY_AVAILABLE = False
    NDArray = list  # type: ignore[misc,assignment]

logger = logging.getLogger("flinttrade.ai.signals")


class SignalAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class MLSignal:
    """A LightGBM classification result with confidence and feature values."""

    action: str = "HOLD"
    confidence: float = 0.0  # 0.0 to 1.0
    symbol: str = ""
    features: dict[str, float] = field(default_factory=dict)
    timestamp: str = ""

    @property
    def is_actionable(self) -> bool:
        return self.action != "HOLD" and self.confidence > 0.5


# Historical module-level import retained while callers migrate to ``MLSignal``.
Signal = MLSignal


@dataclass
class FeatureSet:
    """Engineered features ready for ML model input."""

    names: list[str] = field(default_factory=list)
    values: list[list[float]] = field(default_factory=list)  # rows of features
    labels: list[int] = field(default_factory=list)  # 0=SELL, 1=HOLD, 2=BUY


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def _safe_div(a: float, b: float) -> float:
    return a / b if b != 0 else 0.0


def compute_rsi(closes: list[float], period: int = 14) -> list[float]:
    """RSI indicator."""
    if len(closes) < period + 1:
        return [50.0] * len(closes)
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(0, d) for d in deltas]
    losses = [max(0, -d) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    result = [50.0] * (period + 1)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = _safe_div(avg_gain, avg_loss)
        result.append(100 - 100 / (1 + rs) if avg_loss > 0 else 100.0)
    return result


def compute_ema(values: list[float], period: int) -> list[float]:
    """Exponential Moving Average."""
    if not values:
        return []
    k = 2 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def compute_macd(
    closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9,
) -> tuple[list[float], list[float]]:
    """MACD line and signal line."""
    ema_fast = compute_ema(closes, fast)
    ema_slow = compute_ema(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast, ema_slow)]
    signal_line = compute_ema(macd_line, signal)
    return macd_line, signal_line


def compute_bollinger_pct(closes: list[float], period: int = 20) -> list[float]:
    """Bollinger Band %B — where price sits within the bands (0=lower, 1=upper)."""
    result: list[float] = [0.5] * min(period, len(closes))
    for i in range(period, len(closes)):
        window = closes[i - period: i]
        mean = sum(window) / period
        std = (sum((v - mean) ** 2 for v in window) / period) ** 0.5
        if std > 0:
            result.append((closes[i] - (mean - 2 * std)) / (4 * std))
        else:
            result.append(0.5)
    return result


def engineer_features(
    bars: list[dict[str, Any]],
    *,
    pcr_values: list[float] | None = None,
    max_pain_values: list[float] | None = None,
    iv_percentile_values: list[float] | None = None,
) -> FeatureSet:
    """Transform raw OHLCV bars + optional market data into ML features.

    Each bar: {"timestamp", "open", "high", "low", "close", "volume", "oi"}
    """
    if len(bars) < 30:
        return FeatureSet()

    closes = [float(b["close"]) for b in bars]
    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    volumes = [float(b.get("volume", 0)) for b in bars]

    # Technical indicators
    rsi_14 = compute_rsi(closes, 14)
    macd_line, macd_signal = compute_macd(closes)
    bb_pct = compute_bollinger_pct(closes, 20)
    ema_9 = compute_ema(closes, 9)
    ema_21 = compute_ema(closes, 21)

    feature_names = [
        "return_1", "return_5", "return_10",
        "high_low_range", "close_vs_high", "close_vs_low",
        "volume_ratio_5",
        "rsi_14", "macd_hist", "bb_pct",
        "ema_cross",  # ema9 - ema21 normalised
        "pcr", "max_pain_dist", "iv_percentile",
    ]

    rows: list[list[float]] = []
    lookback = 20  # Skip first 20 bars for indicators to stabilize

    for i in range(lookback, len(bars)):
        # Price-based
        ret_1 = _safe_div(closes[i] - closes[i - 1], closes[i - 1])
        ret_5 = _safe_div(closes[i] - closes[i - 5], closes[i - 5]) if i >= 5 else 0
        ret_10 = _safe_div(closes[i] - closes[i - 10], closes[i - 10]) if i >= 10 else 0
        hl_range = _safe_div(highs[i] - lows[i], closes[i])
        close_vs_h = _safe_div(closes[i] - lows[i], highs[i] - lows[i]) if highs[i] != lows[i] else 0.5
        close_vs_l = 1.0 - close_vs_h

        # Volume
        avg_vol_5 = sum(volumes[i - 5: i]) / 5 if i >= 5 else max(volumes[i], 1)
        vol_ratio = _safe_div(volumes[i], avg_vol_5) if avg_vol_5 > 0 else 1.0

        # Indicators
        rsi_val = rsi_14[i] / 100 if i < len(rsi_14) else 0.5
        macd_h = (macd_line[i] - macd_signal[i]) / closes[i] * 100 if i < len(macd_line) else 0
        bb_val = bb_pct[i] if i < len(bb_pct) else 0.5
        ema_c = _safe_div(ema_9[i] - ema_21[i], closes[i]) if i < min(len(ema_9), len(ema_21)) else 0

        # OI / IV features (default 0 if not provided)
        pcr = pcr_values[i] if pcr_values and i < len(pcr_values) else 0.0
        mp_dist = max_pain_values[i] if max_pain_values and i < len(max_pain_values) else 0.0
        iv_pct = iv_percentile_values[i] if iv_percentile_values and i < len(iv_percentile_values) else 0.0

        rows.append([
            ret_1, ret_5, ret_10, hl_range, close_vs_h, close_vs_l,
            vol_ratio, rsi_val, macd_h, bb_val, ema_c,
            pcr, mp_dist, iv_pct,
        ])

    return FeatureSet(names=feature_names, values=rows)


def generate_labels(
    closes: list[float],
    lookahead: int = 5,
    threshold_pct: float = 0.5,
    offset: int = 20,
) -> list[int]:
    """Generate labels: 2=BUY, 0=SELL, 1=HOLD based on future returns.

    A future return > threshold → BUY, < -threshold → SELL, else HOLD.
    """
    labels: list[int] = []
    for i in range(offset, len(closes)):
        future_idx = i + lookahead
        if future_idx >= len(closes):
            labels.append(1)  # HOLD for insufficient future data
            continue
        ret = (closes[future_idx] - closes[i]) / closes[i] * 100
        if ret > threshold_pct:
            labels.append(2)  # BUY
        elif ret < -threshold_pct:
            labels.append(0)  # SELL
        else:
            labels.append(1)  # HOLD
    return labels


# ---------------------------------------------------------------------------
# Sharpe labels
# ---------------------------------------------------------------------------


def generate_sharpe_labels(
    closes: NDArray,
    lookahead: int = 5,
    min_sharpe: float = 0.5,
    offset: int = 20,
) -> NDArray:
    """Alternative labeling: BUY only if forward Sharpe exceeds threshold.

    Computes the Sharpe ratio of forward returns over *lookahead* bars and
    labels each bar:
    - ``1``  — forward Sharpe > min_sharpe  (BUY)
    - ``0``  — forward Sharpe < -min_sharpe (SELL)
    - ``-1`` — otherwise                    (HOLD)

    Args:
        closes: 1-D sequence of close prices (list or numpy array).
        lookahead: Number of forward bars used to compute returns.
        min_sharpe: Sharpe ratio threshold that triggers a directional label.
        offset: Skip this many bars at the start (indicators warm-up).

    Returns:
        Integer array of length ``len(closes) - offset`` with values in
        ``{-1, 0, 1}``.
    """
    n = len(closes)
    labels: list[int] = []

    for i in range(offset, n):
        end_idx = i + lookahead
        if end_idx >= n:
            labels.append(-1)  # HOLD — not enough future data
            continue

        # Forward returns over the lookahead window
        fwd_returns: list[float] = []
        for j in range(i, end_idx):
            c_cur = float(closes[j])
            c_nxt = float(closes[j + 1])
            fwd_returns.append((c_nxt - c_cur) / c_cur if c_cur != 0 else 0.0)

        if not fwd_returns:
            labels.append(-1)
            continue

        mean_ret = sum(fwd_returns) / len(fwd_returns)
        variance = sum((r - mean_ret) ** 2 for r in fwd_returns) / ((len(fwd_returns) - 1) if len(fwd_returns) > 1 else 1)
        std_ret = math.sqrt(variance) if variance > 0 else 0.0

        if std_ret == 0:
            # Zero volatility — label by direction of mean return
            if mean_ret > 0:
                labels.append(1)
            elif mean_ret < 0:
                labels.append(0)
            else:
                labels.append(-1)
            continue

        sharpe = mean_ret / std_ret

        if sharpe > min_sharpe:
            labels.append(1)   # BUY
        elif sharpe < -min_sharpe:
            labels.append(0)   # SELL
        else:
            labels.append(-1)  # HOLD

    if _NUMPY_AVAILABLE:
        return np.array(labels, dtype=np.int8)
    return labels  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Turbulence index
# ---------------------------------------------------------------------------


def compute_turbulence(
    returns: NDArray,
    window: int = 60,
) -> NDArray:
    """Mahalanobis-distance-based turbulence index per bar.

    Measures how abnormal the current return is relative to the recent
    historical distribution.  High values indicate unusual / stressed market
    conditions.

    Single-asset formula (simplified Mahalanobis):
        turbulence[t] = (r[t] - mu)^2 / variance

    Multi-asset formula (full Mahalanobis, requires numpy):
        turbulence[t] = (r[t] - mu)^T * Sigma^{-1} * (r[t] - mu)

    Args:
        returns: 1-D (single asset) or 2-D (multi-asset, shape N x M) array
            of returns.  Plain Python lists treated as single-asset.
        window: Rolling window length for computing mean / covariance.

    Returns:
        1-D float array of turbulence scores, same length as the returns
        time-axis.  Values before the first full window are ``0.0``.
    """
    # Determine if multi-asset (2-D numpy array)
    is_multi = (
        _NUMPY_AVAILABLE
        and isinstance(returns, np.ndarray)
        and returns.ndim == 2
    )

    if is_multi:
        return _compute_turbulence_multi(returns, window)  # type: ignore[arg-type]
    return _compute_turbulence_single(returns, window)


def _compute_turbulence_single(returns: NDArray, window: int) -> NDArray:
    """Single-asset turbulence: (r - mean)^2 / variance over rolling window."""
    n = len(returns)
    scores: list[float] = [0.0] * n

    for i in range(window, n):
        hist = [float(returns[j]) for j in range(i - window, i)]
        mu = sum(hist) / window
        var = sum((r - mu) ** 2 for r in hist) / window
        r_cur = float(returns[i])
        scores[i] = (r_cur - mu) ** 2 / var if var > 0 else 0.0

    if _NUMPY_AVAILABLE:
        return np.array(scores, dtype=np.float64)
    return scores  # type: ignore[return-value]


def _compute_turbulence_multi(returns: "np.ndarray", window: int) -> "np.ndarray":
    """Multi-asset turbulence: full Mahalanobis distance over rolling window.

    Requires numpy.  ``returns`` must have shape (N, M) — N bars, M assets.
    """
    import numpy as np  # noqa: F811

    n, m = returns.shape
    scores = np.zeros(n, dtype=np.float64)

    for i in range(window, n):
        hist = returns[i - window: i]          # (window, M)
        mu = hist.mean(axis=0)                  # (M,)
        cov = np.cov(hist, rowvar=False)        # (M, M)

        # Add small jitter to avoid singular covariance matrix
        cov += np.eye(m) * 1e-8

        try:
            cov_inv = np.linalg.inv(cov)
        except np.linalg.LinAlgError:
            scores[i] = 0.0
            continue

        diff = returns[i] - mu                  # (M,)
        scores[i] = float(diff @ cov_inv @ diff)

    return scores


# ---------------------------------------------------------------------------
# Signal Generator
# ---------------------------------------------------------------------------


class SignalGenerator:
    """ML-based signal generator using LightGBM.

    Usage::

        sg = SignalGenerator()
        sg.train(bars, lookahead=5)
        signal = sg.predict(recent_bars)
        if signal.is_actionable:
            print(f"{signal.action} with {signal.confidence:.0%} confidence")
        sg.save("models/signal_model.joblib")
    """

    def __init__(self) -> None:
        self._model = None
        self._feature_names: list[str] = []

    @property
    def is_trained(self) -> bool:
        return self._model is not None

    def train(
        self,
        bars: list[dict[str, Any]],
        lookahead: int = 5,
        threshold_pct: float = 0.5,
        test_ratio: float = 0.2,
        **lgb_params: Any,
    ) -> dict[str, float]:
        """Train a LightGBM classifier on historical bar data.

        Returns dict with train_accuracy, test_accuracy, feature_importances.
        """
        try:
            import lightgbm as lgb
        except (ImportError, OSError):
            raise ImportError("lightgbm required — pip install lightgbm")

        features = engineer_features(bars)
        if not features.values:
            raise ValueError("Not enough bars to generate features (need 30+)")

        closes = [float(b["close"]) for b in bars]
        labels = generate_labels(closes, lookahead, threshold_pct)

        # Align feature rows and labels
        n = min(len(features.values), len(labels))
        X = features.values[:n]
        y = labels[:n]

        self._feature_names = features.names

        # Walk-forward split
        split = int(len(X) * (1 - test_ratio))
        X_train, X_test = X[:split], X[split:]
        y_train, y_test = y[:split], y[split:]

        params = {
            "objective": "multiclass",
            "num_class": 3,
            "metric": "multi_logloss",
            "verbosity": -1,
            "num_leaves": 31,
            "learning_rate": 0.05,
            "n_estimators": 200,
            **lgb_params,
        }

        train_data = lgb.Dataset(X_train, label=y_train, feature_name=self._feature_names)
        valid_data = lgb.Dataset(X_test, label=y_test, reference=train_data)

        self._model = lgb.train(
            params,
            train_data,
            valid_sets=[valid_data],
            callbacks=[lgb.log_evaluation(period=0)],
        )

        # Evaluate
        train_preds = [max(range(3), key=lambda c: row[c]) for row in self._model.predict(X_train)]
        test_preds = [max(range(3), key=lambda c: row[c]) for row in self._model.predict(X_test)]
        train_acc = sum(1 for a, b in zip(train_preds, y_train) if a == b) / len(y_train) if y_train else 0
        test_acc = sum(1 for a, b in zip(test_preds, y_test) if a == b) / len(y_test) if y_test else 0

        logger.info("Signal model trained: train_acc=%.2f, test_acc=%.2f", train_acc, test_acc)
        return {"train_accuracy": train_acc, "test_accuracy": test_acc}

    def predict(
        self,
        bars: list[dict[str, Any]],
        symbol: str = "",
        **market_data: Any,
    ) -> MLSignal:
        """Generate a signal from recent bars."""
        if not self._model:
            return MLSignal(action="HOLD", confidence=0.0, symbol=symbol)

        features = engineer_features(
            bars,
            pcr_values=market_data.get("pcr_values"),
            max_pain_values=market_data.get("max_pain_values"),
            iv_percentile_values=market_data.get("iv_percentile_values"),
        )
        if not features.values:
            return MLSignal(action="HOLD", confidence=0.0, symbol=symbol)

        # Use the last feature row
        row = features.values[-1]
        probs = self._model.predict([row])[0]
        pred_class = max(range(3), key=lambda c: probs[c])
        confidence = float(probs[pred_class])

        action_map = {0: "SELL", 1: "HOLD", 2: "BUY"}
        feat_dict = dict(zip(self._feature_names, row))

        return MLSignal(
            action=action_map[pred_class],
            confidence=confidence,
            symbol=symbol,
            features=feat_dict,
            timestamp=str(bars[-1].get("timestamp", "")) if bars else "",
        )

    def save(self, path: str) -> None:
        """Save trained model to disk."""
        try:
            import joblib
        except ImportError:
            raise ImportError("joblib required — pip install joblib")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": self._model, "feature_names": self._feature_names}, path)
        logger.info("Signal model saved to %s", path)

    def load(self, path: str) -> None:
        """Load a trained model from disk."""
        try:
            import joblib
        except ImportError:
            raise ImportError("joblib required — pip install joblib")
        data = joblib.load(path)
        self._model = data["model"]
        self._feature_names = data["feature_names"]
        logger.info("Signal model loaded from %s", path)
