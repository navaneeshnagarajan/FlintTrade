"""Rolling-window ensemble model selector for adaptive signal generation.

Absorbs patterns from:
- **FinRL** ``DRLEnsembleAgent``: trains multiple models (A2C, PPO, DDPG),
  validates each on a rolling window, and selects the best-performing one
  for the next trading period based on Sharpe ratio.
- **freqtrade FreqAI**: ``train_period_days`` / ``backtest_period_days``
  rolling retrain with dissimilarity index (DI) for novelty detection.

FlintTrade adaptation:
- Multiple LightGBM configurations (varying features, hyperparams) are
  trained on the same data.  Each is validated on a held-out window.
- The model with the best validation Sharpe (or accuracy) is selected
  for live prediction.
- A ``staleness_check`` detects when live data distribution has drifted
  too far from training data (DI threshold), triggering a retrain.

No RL / PyTorch dependency -- uses the existing ``SignalGenerator`` and
``engineer_features`` from ``packages.ai.src.signals``.

Usage::

    from packages.ai.src.ensemble_selector import EnsembleSelector

    selector = EnsembleSelector()
    best_name = selector.train_ensemble(bars, configs=[
        {"num_leaves": 31, "learning_rate": 0.05},
        {"num_leaves": 63, "learning_rate": 0.03},
        {"num_leaves": 15, "learning_rate": 0.1},
    ])
    signal = selector.predict(recent_bars)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from .signals import (
    Signal,
    engineer_features,
    generate_labels,
)

# Re-export calculate_di so callers can import it from this module directly.
__all__ = [
    "ModelCandidate",
    "EnsembleResult",
    "EnsembleSelector",
    "calculate_di",
    "compute_dissimilarity_index",
]

logger = logging.getLogger("flinttrade.ai.ensemble_selector")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ModelCandidate:
    """A trained model candidate within the ensemble.

    Attributes:
        name: Identifier for this model variant.
        params: LightGBM parameters used for training.
        model: The trained LightGBM Booster (or None if failed).
        feature_names: Feature column names.
        val_accuracy: Validation accuracy on the holdout window.
        val_sharpe: Validation Sharpe ratio on the holdout window.
        train_samples: Number of training samples.
        val_samples: Number of validation samples.
    """

    name: str
    params: dict[str, Any]
    model: Any = None
    feature_names: list[str] = field(default_factory=list)
    val_accuracy: float = 0.0
    val_sharpe: float = 0.0
    train_samples: int = 0
    val_samples: int = 0


@dataclass
class EnsembleResult:
    """Result of an ensemble training and selection cycle.

    Attributes:
        best_model_name: Name of the selected best model.
        candidates: All model candidates with their metrics.
        selection_metric: Which metric was used for selection.
    """

    best_model_name: str = ""
    candidates: list[ModelCandidate] = field(default_factory=list)
    selection_metric: str = "val_sharpe"


# ---------------------------------------------------------------------------
# Dissimilarity Index (from freqtrade FreqAI)
# ---------------------------------------------------------------------------


def _pca_reduce(
    matrix: list[list[float]],
    n_components: int,
) -> list[list[float]]:
    """Reduce a feature matrix to ``n_components`` dimensions via PCA.

    Pure-Python implementation that avoids a NumPy/sklearn dependency by
    using the standard library's ``statistics`` module.  Centred data is
    projected onto the top ``n_components`` principal components derived
    from the covariance matrix via power iteration.

    Falls back to the original matrix when ``n_components`` ≥ the number
    of features, or when fewer than 2 samples are present.

    Args:
        matrix: 2D list ``[n_samples x n_features]``.
        n_components: Target dimensionality.

    Returns:
        Reduced matrix ``[n_samples x n_components]``.
    """
    n_samples = len(matrix)
    if n_samples < 2 or not matrix[0]:
        return matrix

    n_features = len(matrix[0])
    if n_components >= n_features:
        return matrix

    # Centre each feature
    col_means = [
        sum(matrix[r][c] for r in range(n_samples)) / n_samples
        for c in range(n_features)
    ]
    centred = [
        [matrix[r][c] - col_means[c] for c in range(n_features)]
        for r in range(n_samples)
    ]

    def _mat_mul(A: list[list[float]], B: list[list[float]]) -> list[list[float]]:
        rows_a, cols_a = len(A), len(A[0])
        cols_b = len(B[0])
        result = [[0.0] * cols_b for _ in range(rows_a)]
        for i in range(rows_a):
            for k in range(cols_a):
                if A[i][k] == 0.0:
                    continue
                for j in range(cols_b):
                    result[i][j] += A[i][k] * B[k][j]
        return result

    def _transpose(M: list[list[float]]) -> list[list[float]]:
        if not M:
            return M
        rows, cols = len(M), len(M[0])
        return [[M[r][c] for r in range(rows)] for c in range(cols)]

    def _norm(v: list[float]) -> float:
        return math.sqrt(sum(x * x for x in v))

    # Covariance matrix (n_features × n_features) = centred^T · centred / n_samples
    cT = _transpose(centred)
    cov: list[list[float]] = [
        [sum(cT[i][k] * cT[j][k] for k in range(n_samples)) / n_samples
         for j in range(n_features)]
        for i in range(n_features)
    ]

    # Extract top-k PCs via deflated power iteration (100 iterations each)
    components: list[list[float]] = []
    mat = [row[:] for row in cov]
    for _ in range(n_components):
        # Random-ish starting vector (deterministic seed)
        vec = [float((i * 31 + 17) % 97 + 1) for i in range(n_features)]
        for _iter in range(100):
            new_vec = [
                sum(mat[i][j] * vec[j] for j in range(n_features))
                for i in range(n_features)
            ]
            magnitude = _norm(new_vec)
            if magnitude == 0.0:
                break
            vec = [x / magnitude for x in new_vec]

        components.append(vec)

        # Deflate: mat = mat - (vec · vec^T) * eigenvalue
        eigenvalue = sum(
            sum(mat[i][j] * vec[j] for j in range(n_features)) * vec[i]
            for i in range(n_features)
        )
        for i in range(n_features):
            for j in range(n_features):
                mat[i][j] -= eigenvalue * vec[i] * vec[j]

    # Project centred matrix onto components
    comps_T = components  # shape: n_components × n_features
    reduced = [
        [sum(centred[r][c] * comps_T[k][c] for c in range(n_features))
         for k in range(n_components)]
        for r in range(n_samples)
    ]
    return reduced


def calculate_di(
    train_features: list[list[float]],
    live_features: list[list[float]],
    n_pca_components: int = 3,
) -> float:
    """Compute the Dissimilarity Index (DI) between training and live distributions.

    Implements freqtrade FreqAI's DataKitchen DI pattern: features are
    first reduced via PCA, then the average Euclidean distance from each
    live sample to its nearest training neighbour is computed and
    normalised by the average intra-training spread.

    The PCA step removes correlated noise dimensions so that the distance
    metric is meaningful even with high-dimensional feature vectors (50+
    columns after TA-Lib engineering).

    Args:
        train_features: 2D list ``[n_train × n_features]`` — feature
            vectors from the training window.
        live_features: 2D list ``[n_live × n_features]`` — feature
            vectors from recent live data.
        n_pca_components: Number of principal components to retain before
            computing distances.  Defaults to 3.

    Returns:
        Dissimilarity index ``float ≥ 0``.  Values above the configured
        threshold (default 2.0) indicate distribution drift and should
        trigger a retrain.
    """
    if not train_features or not live_features:
        return 0.0

    # Reduce both sets to the same PCA space fitted on training data
    combined = train_features + live_features
    all_reduced = _pca_reduce(combined, n_components=n_pca_components)
    n_train = len(train_features)
    train_reduced = all_reduced[:n_train]
    live_reduced = all_reduced[n_train:]

    def _euclidean(a: list[float], b: list[float]) -> float:
        return math.sqrt(sum((ai - bi) ** 2 for ai, bi in zip(a, b)))

    # Average distance from each live point to its nearest training neighbour
    live_to_train: list[float] = []
    for lp in live_reduced:
        min_dist = min(_euclidean(lp, tp) for tp in train_reduced)
        live_to_train.append(min_dist)
    avg_live_dist = sum(live_to_train) / len(live_to_train)

    # Average intra-training spread (sampled for efficiency)
    sample_size = min(50, len(train_reduced))
    intra_dists: list[float] = []
    for i in range(sample_size):
        for j in range(i + 1, min(i + 5, len(train_reduced))):
            intra_dists.append(_euclidean(train_reduced[i], train_reduced[j]))

    if not intra_dists:
        return 0.0

    avg_intra_dist = sum(intra_dists) / len(intra_dists)
    if avg_intra_dist == 0.0:
        return 0.0

    return avg_live_dist / avg_intra_dist


# Keep backward-compatible alias
def compute_dissimilarity_index(
    train_features: list[list[float]],
    live_features: list[list[float]],
) -> float:
    """Backward-compatible wrapper around ``calculate_di``.

    Absorbs freqtrade FreqAI's DI_threshold pattern.

    Args:
        train_features: 2D list of training feature vectors.
        live_features: 2D list of live/recent feature vectors.

    Returns:
        Dissimilarity index (float).  Values > 1.0 suggest distribution
        drift; values > 2.0 (default threshold) trigger retrain.
    """
    return calculate_di(train_features, live_features)


# ---------------------------------------------------------------------------
# Validation Sharpe calculation
# ---------------------------------------------------------------------------


def _compute_validation_sharpe(
    model: Any,
    val_features: list[list[float]],
    val_closes: list[float],
    lookahead: int = 5,
) -> float:
    """Compute Sharpe ratio of model predictions on validation data.

    Simulates: if model says BUY, we earn the forward return;
    if SELL, we earn the negative; if HOLD, we earn 0.

    Absorbs FinRL's ensemble selection: pick the model with best
    validation-period Sharpe ratio.

    Args:
        model: Trained LightGBM model.
        val_features: Validation feature rows.
        val_closes: Close prices aligned with validation features.
        lookahead: Number of bars to compute forward return.

    Returns:
        Annualised Sharpe ratio (assuming 252 trading days).
    """
    if not val_features or not val_closes or len(val_closes) < lookahead + 1:
        return 0.0

    probs_list = model.predict(val_features)
    strategy_returns: list[float] = []

    for i, probs in enumerate(probs_list):
        if i + lookahead >= len(val_closes):
            break

        pred_class = max(range(3), key=lambda c: probs[c])
        fwd_return = (val_closes[i + lookahead] - val_closes[i]) / val_closes[i]

        if pred_class == 2:  # BUY
            strategy_returns.append(fwd_return)
        elif pred_class == 0:  # SELL
            strategy_returns.append(-fwd_return)
        else:  # HOLD
            strategy_returns.append(0.0)

    if len(strategy_returns) < 2:
        return 0.0

    mean_ret = sum(strategy_returns) / len(strategy_returns)
    variance = sum((r - mean_ret) ** 2 for r in strategy_returns) / (len(strategy_returns) - 1)
    std_ret = math.sqrt(variance) if variance > 0 else 0.0

    if std_ret == 0:
        return 0.0

    daily_sharpe = mean_ret / std_ret
    return daily_sharpe * math.sqrt(252)


# ---------------------------------------------------------------------------
# EnsembleSelector
# ---------------------------------------------------------------------------


class EnsembleSelector:
    """Rolling-window ensemble model selector.

    Trains multiple LightGBM model variants on the same data, validates
    each on a holdout window, and selects the best performer.

    Absorbs FinRL's ``DRLEnsembleAgent`` pattern (rolling rebalance +
    validation-based selection) and freqtrade's FreqAI dissimilarity
    index for staleness detection.

    Args:
        lookahead: Forward return window for label generation.
        threshold_pct: Return threshold for BUY/SELL labelling.
        val_ratio: Fraction of data used for validation (walk-forward).
        di_threshold: Dissimilarity index threshold for staleness.
            Values above this trigger a retrain recommendation.
            Defaults to 2.0 (aligned with FreqAI's DataKitchen DI).
        di_pca_components: Number of PCA components used when computing
            the DI distance in reduced feature space.  Defaults to 3.
    """

    def __init__(
        self,
        lookahead: int = 5,
        threshold_pct: float = 0.5,
        val_ratio: float = 0.2,
        di_threshold: float = 2.0,
        di_pca_components: int = 3,
    ) -> None:
        self._lookahead = lookahead
        self._threshold_pct = threshold_pct
        self._val_ratio = val_ratio
        self._di_threshold = di_threshold
        self._di_pca_components = di_pca_components
        self._candidates: list[ModelCandidate] = []
        self._best: ModelCandidate | None = None
        self._train_features: list[list[float]] = []

    @property
    def best_model(self) -> ModelCandidate | None:
        """Return the currently selected best model."""
        return self._best

    @property
    def candidates(self) -> list[ModelCandidate]:
        """Return all trained candidates."""
        return list(self._candidates)

    def train_ensemble(
        self,
        bars: list[dict[str, Any]],
        configs: list[dict[str, Any]] | None = None,
        selection_metric: str = "val_sharpe",
    ) -> EnsembleResult:
        """Train multiple model variants and select the best.

        Args:
            bars: OHLCV bar dicts for training + validation.
            configs: List of LightGBM parameter dicts.  Each becomes a
                candidate.  Defaults to three standard configurations.
            selection_metric: ``"val_sharpe"`` or ``"val_accuracy"``.

        Returns:
            ``EnsembleResult`` with the best model name and all candidates.
        """
        try:
            import lightgbm as lgb
        except (ImportError, OSError):
            raise ImportError("lightgbm required -- pip install lightgbm")

        try:
            import numpy as np
            _has_numpy = True
        except ImportError:
            _has_numpy = False

        if configs is None:
            configs = [
                {"num_leaves": 31, "learning_rate": 0.05, "n_estimators": 200},
                {"num_leaves": 63, "learning_rate": 0.03, "n_estimators": 300},
                {"num_leaves": 15, "learning_rate": 0.1, "n_estimators": 150},
            ]

        features = engineer_features(bars)
        if not features.values:
            raise ValueError("Not enough bars to generate features (need 30+)")

        closes = [float(b["close"]) for b in bars]
        labels = generate_labels(closes, self._lookahead, self._threshold_pct)

        n = min(len(features.values), len(labels))
        all_x = features.values[:n]
        all_y = labels[:n]

        # Walk-forward split
        split = int(len(all_x) * (1 - self._val_ratio))
        x_train, x_val = all_x[:split], all_x[split:]
        y_train, y_val = all_y[:split], all_y[split:]
        val_closes = closes[20 + split: 20 + split + len(x_val)]

        # Convert to numpy arrays for LightGBM compatibility
        if _has_numpy:
            x_train = np.array(x_train, dtype=np.float64)
            x_val = np.array(x_val, dtype=np.float64)
            y_train = np.array(y_train, dtype=np.int32)
            y_val = np.array(y_val, dtype=np.int32)

        # Store training features for DI calculation
        self._train_features = list(all_x[:split])

        self._candidates = []

        for idx, cfg in enumerate(configs):
            name = cfg.pop("name", f"model_{idx}")
            candidate = ModelCandidate(
                name=name,
                params=dict(cfg),
                feature_names=features.names,
                train_samples=len(x_train),
                val_samples=len(x_val),
            )

            try:
                params = {
                    "objective": "multiclass",
                    "num_class": 3,
                    "metric": "multi_logloss",
                    "verbosity": -1,
                    **cfg,
                }
                # Remove n_estimators from params if present (passed to train)
                n_estimators = params.pop("n_estimators", 200)

                train_data = lgb.Dataset(
                    x_train, label=y_train, feature_name=features.names,
                )
                valid_data = lgb.Dataset(x_val, label=y_val, reference=train_data)

                model = lgb.train(
                    params,
                    train_data,
                    num_boost_round=n_estimators,
                    valid_sets=[valid_data],
                    callbacks=[lgb.log_evaluation(period=0)],
                )

                candidate.model = model

                # Validation accuracy
                val_preds = [
                    max(range(3), key=lambda c: row[c])
                    for row in model.predict(x_val)
                ]
                candidate.val_accuracy = (
                    sum(1 for a, b in zip(val_preds, y_val) if a == b) / len(y_val)
                    if y_val else 0.0
                )

                # Validation Sharpe
                candidate.val_sharpe = _compute_validation_sharpe(
                    model, x_val, val_closes, self._lookahead,
                )

                logger.info(
                    "Candidate '%s': val_acc=%.3f, val_sharpe=%.3f",
                    name, candidate.val_accuracy, candidate.val_sharpe,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Candidate '%s' training failed: %s", name, exc)

            self._candidates.append(candidate)

        # Select best
        trained = [c for c in self._candidates if c.model is not None]
        if not trained:
            return EnsembleResult(candidates=self._candidates)

        if selection_metric == "val_accuracy":
            self._best = max(trained, key=lambda c: c.val_accuracy)
        else:
            self._best = max(trained, key=lambda c: c.val_sharpe)

        logger.info(
            "Best model: '%s' (%s=%.3f)",
            self._best.name,
            selection_metric,
            getattr(self._best, selection_metric),
        )

        return EnsembleResult(
            best_model_name=self._best.name,
            candidates=self._candidates,
            selection_metric=selection_metric,
        )

    def predict(
        self,
        bars: list[dict[str, Any]],
        symbol: str = "",
    ) -> Signal:
        """Generate a signal using the best model in the ensemble.

        Args:
            bars: Recent OHLCV bars.
            symbol: Instrument symbol for the signal.

        Returns:
            A ``Signal`` from the best model.
        """
        if self._best is None or self._best.model is None:
            return Signal(action="HOLD", confidence=0.0, symbol=symbol)

        features = engineer_features(bars)
        if not features.values:
            return Signal(action="HOLD", confidence=0.0, symbol=symbol)

        row = features.values[-1]
        probs = self._best.model.predict([row])[0]
        pred_class = max(range(3), key=lambda c: probs[c])
        confidence = float(probs[pred_class])

        action_map = {0: "SELL", 1: "HOLD", 2: "BUY"}

        return Signal(
            action=action_map[pred_class],
            confidence=confidence,
            symbol=symbol,
            features=dict(zip(self._best.feature_names, row)),
        )

    def check_staleness(
        self,
        recent_bars: list[dict[str, Any]],
    ) -> tuple[bool, float]:
        """Check if the live data has drifted from training distribution.

        Absorbs freqtrade FreqAI's DI_threshold pattern.

        Args:
            recent_bars: Recent OHLCV bars to check against training data.

        Returns:
            Tuple of ``(is_stale, di_score)``.  ``is_stale`` is True if
            ``di_score`` exceeds the configured threshold.
        """
        if not self._train_features:
            return False, 0.0

        features = engineer_features(recent_bars)
        if not features.values:
            return False, 0.0

        di = calculate_di(
            self._train_features,
            features.values[-10:],  # Check last 10 feature rows
            n_pca_components=self._di_pca_components,
        )

        is_stale = di > self._di_threshold
        if is_stale:
            logger.warning(
                "Data staleness detected: DI=%.3f > threshold=%.3f. Retrain recommended.",
                di, self._di_threshold,
            )

        return is_stale, di
