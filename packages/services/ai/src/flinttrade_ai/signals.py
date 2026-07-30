"""ML signal generator using LightGBM.

Features: OHLCV price action, technical indicators (RSI, MACD, Supertrend,
Bollinger), OI data (PCR, max pain change, OI spurt), IV data (IV percentile,
skew). Predicts BUY/SELL/HOLD for next N candles with a confidence score.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import logging
import math
import os
from collections.abc import Callable
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

_CANONICAL_PROBABILITY_LABELS = ("SELL", "HOLD", "BUY")
_LEGACY_PROBABILITY_LABELS = ("BUY", "HOLD", "SELL")
_LEGACY_FEATURE_NAMES = frozenset({"rsi", "bb_position", "returns_1", "returns_5", "hl_range"})


class TrainingCancelled(RuntimeError):
    """Raised when cooperative model-training cancellation is requested."""


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
    signal_code: int = 1
    probabilities: list[float] = field(default_factory=lambda: [0.0, 1.0, 0.0])
    probability_labels: list[str] = field(default_factory=lambda: list(_CANONICAL_PROBABILITY_LABELS))
    feature_importance: dict[str, float] = field(default_factory=dict)
    error: str = ""

    @property
    def signal(self) -> str:
        """Return the prediction action under the former advisor name."""
        return self.action

    @property
    def success(self) -> bool:
        """Return whether prediction completed without an error."""
        return not self.error

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
    closes: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
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
        window = closes[i - period : i]
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
        "return_1",
        "return_5",
        "return_10",
        "high_low_range",
        "close_vs_high",
        "close_vs_low",
        "volume_ratio_5",
        "volume_ratio_20",
        "rsi_14",
        "macd",
        "macd_signal",
        "macd_hist",
        "bb_pct",
        "body_pct",
        "ema_cross",  # ema9 - ema21 normalised
        "pcr",
        "max_pain_dist",
        "iv_percentile",
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
        avg_vol_5 = sum(volumes[i - 5 : i]) / 5 if i >= 5 else max(volumes[i], 1)
        vol_ratio = _safe_div(volumes[i], avg_vol_5) if avg_vol_5 > 0 else 1.0
        avg_vol_20 = sum(volumes[i - 19 : i + 1]) / 20
        vol_ratio_20 = _safe_div(volumes[i], avg_vol_20) if avg_vol_20 > 0 else 1.0

        # Indicators
        rsi_val = rsi_14[i] / 100 if i < len(rsi_14) else 0.5
        macd_value = macd_line[i] if i < len(macd_line) else 0.0
        macd_signal_value = macd_signal[i] if i < len(macd_signal) else 0.0
        macd_h = (macd_line[i] - macd_signal[i]) / closes[i] * 100 if i < len(macd_line) else 0
        bb_val = bb_pct[i] if i < len(bb_pct) else 0.5
        ema_c = _safe_div(ema_9[i] - ema_21[i], closes[i]) if i < min(len(ema_9), len(ema_21)) else 0
        body_pct = _safe_div(abs(closes[i] - float(bars[i]["open"])), highs[i] - lows[i])

        # OI / IV features (default 0 if not provided)
        pcr = pcr_values[i] if pcr_values and i < len(pcr_values) else 0.0
        mp_dist = max_pain_values[i] if max_pain_values and i < len(max_pain_values) else 0.0
        iv_pct = iv_percentile_values[i] if iv_percentile_values and i < len(iv_percentile_values) else 0.0

        rows.append(
            [
                ret_1,
                ret_5,
                ret_10,
                hl_range,
                close_vs_h,
                close_vs_l,
                vol_ratio,
                vol_ratio_20,
                rsi_val,
                macd_value,
                macd_signal_value,
                macd_h,
                bb_val,
                body_pct,
                ema_c,
                pcr,
                mp_dist,
                iv_pct,
            ]
        )

    return FeatureSet(names=feature_names, values=rows)


def generate_labels(
    closes: list[float],
    lookahead: int = 5,
    threshold_pct: float = 0.5,
    offset: int = 20,
    *,
    buy_threshold_pct: float | None = None,
    sell_threshold_pct: float | None = None,
) -> list[int]:
    """Generate labels: 2=BUY, 0=SELL, 1=HOLD based on future returns.

    A future return above the positive BUY threshold is BUY, below the
    negative SELL threshold is SELL, and values between them are HOLD.
    """
    if not math.isfinite(threshold_pct):
        raise ValueError("threshold_pct must be finite")
    if threshold_pct <= 0:
        raise ValueError("threshold_pct must be positive")
    buy_threshold = threshold_pct if buy_threshold_pct is None else buy_threshold_pct
    sell_threshold = -threshold_pct if sell_threshold_pct is None else sell_threshold_pct
    if not math.isfinite(buy_threshold):
        raise ValueError("buy_threshold_pct must be finite")
    if buy_threshold <= 0:
        raise ValueError("buy_threshold_pct must be positive")
    if not math.isfinite(sell_threshold):
        raise ValueError("sell_threshold_pct must be finite")
    if sell_threshold >= 0:
        raise ValueError("sell_threshold_pct must be negative")

    labels: list[int] = []
    for i in range(offset, len(closes) - lookahead):
        future_idx = i + lookahead
        ret = (closes[future_idx] - closes[i]) / closes[i] * 100
        if ret > buy_threshold:
            labels.append(2)  # BUY
        elif ret < sell_threshold:
            labels.append(0)  # SELL
        else:
            labels.append(1)  # HOLD
    return labels


def walk_forward_split_bounds(
    sample_count: int,
    *,
    test_ratio: float,
    lookahead: int,
) -> tuple[int, int]:
    """Return purged training end and validation start indices.

    The final ``lookahead`` candidate training rows are excluded so none of
    their forward labels can observe a candle at or beyond validation start.
    """
    if lookahead < 1:
        raise ValueError("lookahead must be positive")
    if not 0.0 < test_ratio < 1.0:
        raise ValueError("test_ratio must be between 0 and 1")
    validation_start = int(sample_count * (1 - test_ratio))
    training_end = validation_start - lookahead
    if training_end <= 0 or validation_start >= sample_count:
        raise ValueError("Not enough labelled rows for a purged walk-forward split")
    return training_end, validation_start


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
        variance = sum((r - mean_ret) ** 2 for r in fwd_returns) / (
            (len(fwd_returns) - 1) if len(fwd_returns) > 1 else 1
        )
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
            labels.append(1)  # BUY
        elif sharpe < -min_sharpe:
            labels.append(0)  # SELL
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
    is_multi = _NUMPY_AVAILABLE and isinstance(returns, np.ndarray) and returns.ndim == 2

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
        hist = returns[i - window : i]  # (window, M)
        mu = hist.mean(axis=0)  # (M,)
        cov = np.cov(hist, rowvar=False)  # (M, M)

        # Add small jitter to avoid singular covariance matrix
        cov += np.eye(m) * 1e-8

        try:
            cov_inv = np.linalg.inv(cov)
        except np.linalg.LinAlgError:
            scores[i] = 0.0
            continue

        diff = returns[i] - mu  # (M,)
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
        self._feature_semantics = "canonical"
        self._probability_labels = _CANONICAL_PROBABILITY_LABELS

    @property
    def is_trained(self) -> bool:
        return self._model is not None

    def train(
        self,
        bars: list[dict[str, Any]],
        lookahead: int = 5,
        threshold_pct: float = 0.5,
        test_ratio: float = 0.2,
        buy_threshold_pct: float | None = None,
        sell_threshold_pct: float | None = None,
        min_training_rows: int = 30,
        cancel_requested: Callable[[], bool] | None = None,
        **lgb_params: Any,
    ) -> dict[str, Any]:
        """Train a LightGBM classifier on historical bar data.

        Returns dict with train_accuracy, test_accuracy, feature_importances.
        """
        def check_cancelled() -> None:
            if cancel_requested is not None and cancel_requested():
                raise TrainingCancelled("Signal model training cancelled")

        check_cancelled()
        if min_training_rows < 30:
            raise ValueError("min_training_rows must be at least 30")
        if len(bars) < min_training_rows:
            raise ValueError(f"Historical data has {len(bars)} rows; need at least {min_training_rows}")

        try:
            import lightgbm as lgb
        except (ImportError, OSError):
            raise ImportError("lightgbm required — pip install lightgbm")

        features = engineer_features(bars)
        check_cancelled()
        if not features.values:
            raise ValueError("Not enough bars to generate features (need 30+)")

        closes = [float(b["close"]) for b in bars]
        labels = generate_labels(
            closes,
            lookahead,
            threshold_pct,
            buy_threshold_pct=buy_threshold_pct,
            sell_threshold_pct=sell_threshold_pct,
        )
        check_cancelled()

        # Align feature rows and labels
        n = min(len(features.values), len(labels))
        X = features.values[:n]
        y = labels[:n]

        self._feature_names = features.names

        # Purge the label horizon before validation. Without this gap, the last
        # training labels are computed from closes inside the validation window.
        training_end, validation_start = walk_forward_split_bounds(
            len(X),
            test_ratio=test_ratio,
            lookahead=lookahead,
        )
        X_train, X_test = X[:training_end], X[validation_start:]
        y_train, y_test = y[:training_end], y[validation_start:]

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

        def cancel_callback(_environment: Any) -> None:
            check_cancelled()

        callbacks = [lgb.log_evaluation(period=0)]
        if cancel_requested is not None:
            callbacks.append(cancel_callback)
        model = lgb.train(
            params,
            train_data,
            valid_sets=[valid_data],
            callbacks=callbacks,
        )
        check_cancelled()
        self._model = model
        self._feature_semantics = "canonical"
        self._probability_labels = _CANONICAL_PROBABILITY_LABELS

        # Evaluate
        train_preds = [max(range(3), key=lambda c: row[c]) for row in self._model.predict(X_train)]
        check_cancelled()
        test_preds = [max(range(3), key=lambda c: row[c]) for row in self._model.predict(X_test)]
        check_cancelled()
        train_acc = sum(1 for a, b in zip(train_preds, y_train) if a == b) / len(y_train) if y_train else 0
        test_acc = sum(1 for a, b in zip(test_preds, y_test) if a == b) / len(y_test) if y_test else 0

        logger.info("Signal model trained: train_acc=%.2f, test_acc=%.2f", train_acc, test_acc)
        return {
            "train_accuracy": train_acc,
            "test_accuracy": test_acc,
            "training_rows": len(X_train),
            "validation_rows": len(X_test),
            "feature_importances": self._feature_importance(),
        }

    def predict(
        self,
        bars: list[dict[str, Any]],
        symbol: str = "",
        **market_data: Any,
    ) -> MLSignal:
        """Generate a signal from recent bars."""
        if self._model is None:
            return self._error_signal("Model not trained. Call train() or load() first.", symbol=symbol)

        try:
            features = engineer_features(
                bars,
                pcr_values=market_data.get("pcr_values"),
                max_pain_values=market_data.get("max_pain_values"),
                iv_percentile_values=market_data.get("iv_percentile_values"),
            )
            if not features.values:
                return self._error_signal("Insufficient data to generate prediction features.", symbol=symbol)

            available_features = self._model_feature_values(features)
            unknown_features = [name for name in self._feature_names if name not in available_features]
            if unknown_features:
                message = f"Unsupported persisted features: {', '.join(unknown_features)}"
                logger.error("Signal model for %s has %s", symbol or "<unknown>", message.lower())
                return self._error_signal(message, symbol=symbol)

            # Persisted model schemas are the source of truth: older models need
            # their original column order, while new models receive the full union.
            row = [available_features[name] for name in self._feature_names]
            if self._feature_semantics == "legacy":
                raw_probabilities = self._model.predict_proba([row])[0]
            else:
                raw_probabilities = self._model.predict([row])[0]
            probabilities = [float(value) for value in raw_probabilities]
            if len(probabilities) != len(self._probability_labels):
                raise ValueError(
                    f"Model returned {len(probabilities)} probabilities; expected {len(self._probability_labels)}"
                )
            pred_class = max(range(len(probabilities)), key=probabilities.__getitem__)
            feat_dict = dict(zip(self._feature_names, row, strict=True))

            return MLSignal(
                action=self._probability_labels[pred_class],
                confidence=probabilities[pred_class],
                symbol=symbol,
                features=feat_dict,
                timestamp=str(bars[-1].get("timestamp", "")) if bars else "",
                signal_code=pred_class,
                probabilities=probabilities,
                probability_labels=list(self._probability_labels),
                feature_importance=self._feature_importance(),
            )
        except Exception as exc:  # noqa: BLE001 - prediction is a fail-closed advisory path
            logger.error("Signal model prediction failed for %s: %s", symbol or "<unknown>", exc)
            error = str(exc).strip() or type(exc).__name__
            return self._error_signal(error, symbol=symbol)

    def save(self, path: str) -> None:
        """Save trained model to disk with a SHA-256 integrity sidecar."""
        if not self.is_trained:
            raise RuntimeError("No trained model to save.")
        try:
            import joblib
        except ImportError:
            raise ImportError("joblib required — pip install joblib")
        model_path = Path(path)
        model_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "model": self._model,
                "feature_names": self._feature_names,
                "feature_semantics": self._feature_semantics,
                "probability_labels": list(self._probability_labels),
            },
            model_path,
        )
        self._checksum_path(model_path).write_text(self._compute_sha256(model_path), encoding="ascii")
        logger.info("Signal model saved to %s", path)

    def load(self, path: str) -> None:
        """Load a trained model after validating its SHA-256 integrity sidecar."""
        model_path = Path(path)
        checksum_path = self._checksum_path(model_path)
        actual = self._compute_sha256(model_path)

        if checksum_path.exists():
            expected = checksum_path.read_text(encoding="ascii").strip()
            if not hmac.compare_digest(expected, actual):
                raise RuntimeError(f"Refusing to load {model_path.name}: SHA-256 checksum mismatch")
        elif not self._trust_unverified_model():
            raise RuntimeError(f"Refusing to load {model_path.name}: no SHA-256 sidecar found at {checksum_path.name}")
        else:
            logger.warning(
                "Loading %s WITHOUT sha256 verification because "
                "FLINTTRADE_SIGNAL_MODEL_TRUST_UNVERIFIED is set. Do not use in production.",
                model_path,
            )

        self._load_joblib_payload(model_path, source_name=model_path.name)
        logger.info("Signal model loaded from %s", path)

    def load_guarded_bytes(self, model_bytes: bytes, expected_sha256: str, *, source_name: str) -> None:
        """Load model bytes only after their supplied SHA-256 digest is verified."""
        actual = hashlib.sha256(model_bytes).hexdigest()
        if not hmac.compare_digest(expected_sha256, actual):
            raise RuntimeError(f"Refusing to load {source_name}: SHA-256 checksum mismatch")
        self._load_joblib_payload(io.BytesIO(model_bytes), source_name=source_name)
        logger.info("Signal model loaded from guarded bundle %s", source_name)

    def _load_joblib_payload(self, source: Any, *, source_name: str) -> None:
        """Validate a joblib payload before changing the live generator state."""
        try:
            import joblib
        except ImportError:
            raise ImportError("joblib required — pip install joblib")

        data = joblib.load(source)
        try:
            model = data["model"]
            feature_names = data["feature_names"]
        except (KeyError, TypeError) as exc:
            raise ValueError("Signal model payload is missing required fields") from exc
        if not isinstance(feature_names, list) or not all(isinstance(name, str) for name in feature_names):
            raise ValueError("Signal model payload has invalid feature names")

        feature_semantics = data.get("feature_semantics")
        if feature_semantics is None:
            feature_semantics = "legacy" if self._is_legacy_feature_schema(feature_names) else "canonical"
        if feature_semantics not in {"canonical", "legacy"}:
            raise ValueError("Signal model payload has invalid feature semantics")

        probability_labels = data.get("probability_labels")
        if probability_labels is None:
            probability_labels = (
                _LEGACY_PROBABILITY_LABELS if feature_semantics == "legacy" else _CANONICAL_PROBABILITY_LABELS
            )
        if tuple(probability_labels) not in {_CANONICAL_PROBABILITY_LABELS, _LEGACY_PROBABILITY_LABELS}:
            raise ValueError("Signal model payload has invalid probability labels")

        self._model = model
        self._feature_names = feature_names
        self._feature_semantics = feature_semantics
        self._probability_labels = tuple(probability_labels)

    def _model_feature_values(self, features: FeatureSet) -> dict[str, float]:
        """Adapt canonical values to a verified legacy schema when required."""
        values = dict(zip(features.names, features.values[-1], strict=True))
        if self._feature_semantics != "legacy":
            return values

        values.update(
            {
                "rsi": values["rsi_14"] * 100.0,
                "macd_hist": values["macd"] - values["macd_signal"],
                "bb_position": values["bb_pct"],
                "returns_1": math.log1p(values["return_1"]),
                "returns_5": math.log1p(values["return_5"]),
                "hl_range": values["high_low_range"],
            }
        )
        return values

    def _feature_importance(self) -> dict[str, float]:
        """Return model feature importance for Booster and sklearn-style models."""
        if self._model is None:
            return {}
        try:
            booster_importance = getattr(self._model, "feature_importance", None)
            if callable(booster_importance):
                importances = booster_importance()
            else:
                importances = self._model.feature_importances_
            if hasattr(importances, "tolist"):
                importances = importances.tolist()
            return {name: float(value) for name, value in zip(self._feature_names, importances, strict=False)}
        except (AttributeError, TypeError, ValueError):
            return {}

    def _error_signal(self, error: str, *, symbol: str) -> MLSignal:
        """Return the stable HOLD result for a failed prediction."""
        return MLSignal(
            action="HOLD",
            confidence=0.0,
            symbol=symbol,
            signal_code=1,
            probabilities=[0.0, 1.0, 0.0],
            probability_labels=list(self._probability_labels),
            error=error,
        )

    @staticmethod
    def _is_legacy_feature_schema(feature_names: list[str]) -> bool:
        """Return whether persisted names require former advisor semantics."""
        return bool(_LEGACY_FEATURE_NAMES.intersection(feature_names))

    @staticmethod
    def _checksum_path(model_path: Path) -> Path:
        """Return the SHA-256 sidecar path for a persisted model."""
        return Path(f"{model_path}.sha256")

    @staticmethod
    def _compute_sha256(path: Path) -> str:
        """Compute a model digest without deserialising its contents."""
        digest = hashlib.sha256()
        with path.open("rb") as model_file:
            for chunk in iter(lambda: model_file.read(1 << 16), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _trust_unverified_model() -> bool:
        """Return whether the explicit legacy-model trust override is set."""
        return os.environ.get("FLINTTRADE_SIGNAL_MODEL_TRUST_UNVERIFIED", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
