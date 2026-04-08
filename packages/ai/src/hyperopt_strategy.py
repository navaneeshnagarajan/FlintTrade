"""Optuna-based hyperparameter optimisation for signal models.

Absorbs freqtrade's hyperopt pattern:
- Pluggable loss functions (Sharpe, Calmar, MaxDrawdown, Accuracy)
- Optuna TPE sampler with early stopping
- Walk-forward validation to avoid overfitting

Uses FlintTrade's existing ``SignalGenerator`` and ``engineer_features``
rather than importing freqtrade machinery.

Usage::

    from packages.ai.src.hyperopt_strategy import StrategyOptimiser

    optimiser = StrategyOptimiser(bars=historical_bars)
    result = optimiser.optimise(n_trials=50, loss_fn="sharpe")
    print(result.best_params, result.best_score)
    signal_gen = result.best_generator
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Callable

from packages.ai.src.signals import (
    FeatureSet,
    SignalGenerator,
    engineer_features,
    generate_labels,
)

logger = logging.getLogger("flinttrade.ai.hyperopt_strategy")


# ---------------------------------------------------------------------------
# Loss functions (from freqtrade hyperopt_loss patterns)
# ---------------------------------------------------------------------------


def _accuracy_loss(
    preds: list[int],
    labels: list[int],
    closes: list[float],
    lookahead: int,
) -> float:
    """Negative accuracy -- lower is better for minimisation."""
    if not labels:
        return 0.0
    correct = sum(1 for a, b in zip(preds, labels) if a == b)
    return -(correct / len(labels))


def _sharpe_loss(
    preds: list[int],
    labels: list[int],
    closes: list[float],
    lookahead: int,
) -> float:
    """Negative Sharpe ratio of simulated strategy returns.

    Absorbs freqtrade's SharpeHyperOptLoss: if model predicts BUY, we earn
    the forward return; SELL earns the negative; HOLD earns zero.
    """
    returns: list[float] = []
    for i, pred in enumerate(preds):
        end_idx = i + lookahead
        if end_idx >= len(closes):
            break
        fwd = (closes[end_idx] - closes[i]) / closes[i] if closes[i] != 0 else 0.0
        if pred == 2:  # BUY
            returns.append(fwd)
        elif pred == 0:  # SELL
            returns.append(-fwd)
        else:
            returns.append(0.0)

    if len(returns) < 2:
        return 0.0

    mean_r = sum(returns) / len(returns)
    var = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var) if var > 0 else 0.0
    if std == 0:
        return 0.0

    sharpe = (mean_r / std) * math.sqrt(252)
    return -sharpe  # Minimise negative Sharpe


def _calmar_loss(
    preds: list[int],
    labels: list[int],
    closes: list[float],
    lookahead: int,
) -> float:
    """Negative Calmar ratio (annualised return / max drawdown).

    Absorbs freqtrade's CalmarHyperOptLoss.
    """
    equity = [1.0]
    for i, pred in enumerate(preds):
        end_idx = i + lookahead
        if end_idx >= len(closes):
            break
        fwd = (closes[end_idx] - closes[i]) / closes[i] if closes[i] != 0 else 0.0
        if pred == 2:  # BUY
            equity.append(equity[-1] * (1 + fwd))
        elif pred == 0:  # SELL
            equity.append(equity[-1] * (1 - fwd))
        else:
            equity.append(equity[-1])

    if len(equity) < 2:
        return 0.0

    # Annualised return
    total_return = equity[-1] / equity[0] - 1
    n_periods = len(equity) - 1
    if n_periods <= 0:
        return 0.0
    ann_return = total_return * (252 / n_periods)

    # Max drawdown
    peak = equity[0]
    max_dd = 0.0
    for val in equity:
        if val > peak:
            peak = val
        dd = (peak - val) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    if max_dd == 0:
        return -ann_return if ann_return > 0 else 0.0

    calmar = ann_return / max_dd
    return -calmar


def _max_drawdown_loss(
    preds: list[int],
    labels: list[int],
    closes: list[float],
    lookahead: int,
) -> float:
    """Max drawdown as the loss -- lower drawdown is better.

    Absorbs freqtrade's MaxDrawDownHyperOptLoss.
    """
    equity = [1.0]
    for i, pred in enumerate(preds):
        end_idx = i + lookahead
        if end_idx >= len(closes):
            break
        fwd = (closes[end_idx] - closes[i]) / closes[i] if closes[i] != 0 else 0.0
        if pred == 2:
            equity.append(equity[-1] * (1 + fwd))
        elif pred == 0:
            equity.append(equity[-1] * (1 - fwd))
        else:
            equity.append(equity[-1])

    peak = equity[0]
    max_dd = 0.0
    for val in equity:
        if val > peak:
            peak = val
        dd = (peak - val) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    return max_dd  # Minimise drawdown directly


# Registry of built-in loss functions
_LOSS_REGISTRY: dict[str, Callable[[list[int], list[int], list[float], int], float]] = {
    "accuracy": _accuracy_loss,
    "sharpe": _sharpe_loss,
    "calmar": _calmar_loss,
    "max_drawdown": _max_drawdown_loss,
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class OptimisationResult:
    """Result of a hyperparameter optimisation run.

    Attributes:
        best_params: Best LightGBM parameters found.
        best_score: Best loss value achieved (lower is better).
        best_generator: Trained ``SignalGenerator`` with optimal params.
        n_trials: Number of Optuna trials completed.
        loss_fn_name: Which loss function was used.
        all_trials: List of (params, score) for each trial.
    """

    best_params: dict[str, Any] = field(default_factory=dict)
    best_score: float = 0.0
    best_generator: SignalGenerator | None = None
    n_trials: int = 0
    loss_fn_name: str = ""
    all_trials: list[tuple[dict[str, Any], float]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# StrategyOptimiser
# ---------------------------------------------------------------------------


class StrategyOptimiser:
    """Optuna-based hyperparameter optimiser for LightGBM signal models.

    Absorbs freqtrade's hyperopt architecture:
    - Pluggable loss functions (Sharpe, Calmar, MaxDrawdown, Accuracy)
    - TPE sampler with optional early stopping
    - Walk-forward validation split

    Args:
        bars: Historical OHLCV bar dicts for training + validation.
        lookahead: Forward return window for label generation.
        threshold_pct: Return threshold for BUY/SELL labelling.
        val_ratio: Fraction of data for walk-forward validation.
    """

    def __init__(
        self,
        bars: list[dict[str, Any]],
        lookahead: int = 5,
        threshold_pct: float = 0.5,
        val_ratio: float = 0.2,
    ) -> None:
        self._bars = bars
        self._lookahead = lookahead
        self._threshold_pct = threshold_pct
        self._val_ratio = val_ratio

        # Pre-compute features and labels
        self._features = engineer_features(bars)
        closes = [float(b["close"]) for b in bars]
        self._closes = closes
        self._labels = generate_labels(closes, lookahead, threshold_pct)

        # Align
        n = min(len(self._features.values), len(self._labels))
        self._all_x = self._features.values[:n]
        self._all_y = self._labels[:n]

        # Walk-forward split
        split = int(len(self._all_x) * (1 - val_ratio))
        self._x_train = self._all_x[:split]
        self._y_train = self._all_y[:split]
        self._x_val = self._all_x[split:]
        self._y_val = self._all_y[split:]
        # Validation closes (offset by 20 for feature warm-up)
        self._val_closes = closes[20 + split: 20 + split + len(self._x_val)]

    def optimise(
        self,
        n_trials: int = 30,
        loss_fn: str = "sharpe",
        custom_loss_fn: Callable[[list[int], list[int], list[float], int], float] | None = None,
        timeout: int | None = None,
    ) -> OptimisationResult:
        """Run hyperparameter optimisation.

        Args:
            n_trials: Number of Optuna trials.
            loss_fn: Built-in loss function name: ``"sharpe"``, ``"calmar"``,
                ``"max_drawdown"``, or ``"accuracy"``.
            custom_loss_fn: Optional custom loss function.  Signature:
                ``(preds, labels, closes, lookahead) -> float`` (lower is better).
            timeout: Optional timeout in seconds.

        Returns:
            ``OptimisationResult`` with the best parameters and trained model.
        """
        try:
            import optuna
        except ImportError:
            raise ImportError("optuna required -- pip install optuna")

        if not self._features.values:
            raise ValueError("Not enough bars to generate features (need 30+)")

        loss_func = custom_loss_fn or _LOSS_REGISTRY.get(loss_fn)
        if loss_func is None:
            raise ValueError(
                f"Unknown loss function '{loss_fn}'. "
                f"Options: {sorted(_LOSS_REGISTRY.keys())}"
            )

        result = OptimisationResult(loss_fn_name=loss_fn)

        # Suppress Optuna's verbose logging
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        study = optuna.create_study(
            direction="minimize",
            sampler=optuna.samplers.TPESampler(seed=42),
        )

        def objective(trial: optuna.Trial) -> float:
            params = {
                "num_leaves": trial.suggest_int("num_leaves", 8, 128),
                "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
                "n_estimators": trial.suggest_int("n_estimators", 50, 500),
                "min_child_samples": trial.suggest_int("min_child_samples", 5, 50),
                "subsample": trial.suggest_float("subsample", 0.5, 1.0),
                "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
                "reg_alpha": trial.suggest_float("reg_alpha", 1e-8, 10.0, log=True),
                "reg_lambda": trial.suggest_float("reg_lambda", 1e-8, 10.0, log=True),
            }

            try:
                score = self._evaluate(params, loss_func)
                result.all_trials.append((dict(params), score))
                return score
            except Exception as exc:  # noqa: BLE001
                logger.debug("Trial failed: %s", exc)
                return 100000.0  # MAX_LOSS sentinel

        study.optimize(
            objective,
            n_trials=n_trials,
            timeout=timeout,
            show_progress_bar=False,
        )

        result.n_trials = len(study.trials)
        result.best_params = dict(study.best_params)
        result.best_score = study.best_value

        # Retrain on full data with best params
        try:
            result.best_generator = self._train_final(result.best_params)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Final model training failed: %s", exc)

        logger.info(
            "Optimisation complete: %d trials, best %s=%.4f, params=%s",
            result.n_trials,
            loss_fn,
            result.best_score,
            result.best_params,
        )

        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _evaluate(
        self,
        params: dict[str, Any],
        loss_fn: Callable[[list[int], list[int], list[float], int], float],
    ) -> float:
        """Train a model with given params and compute validation loss."""
        import lightgbm as lgb

        n_estimators = params.pop("n_estimators", 200)
        lgb_params = {
            "objective": "multiclass",
            "num_class": 3,
            "metric": "multi_logloss",
            "verbosity": -1,
            **params,
        }

        train_data = lgb.Dataset(
            self._x_train,
            label=self._y_train,
            feature_name=self._features.names,
        )
        valid_data = lgb.Dataset(
            self._x_val, label=self._y_val, reference=train_data,
        )

        model = lgb.train(
            lgb_params,
            train_data,
            num_boost_round=n_estimators,
            valid_sets=[valid_data],
            callbacks=[lgb.log_evaluation(period=0)],
        )

        # Generate predictions on validation set
        val_preds = [
            max(range(3), key=lambda c: row[c])
            for row in model.predict(self._x_val)
        ]

        return loss_fn(val_preds, self._y_val, self._val_closes, self._lookahead)

    def _train_final(self, params: dict[str, Any]) -> SignalGenerator:
        """Train final model on full dataset with best params."""
        # Re-merge params for SignalGenerator.train
        lgb_params = {k: v for k, v in params.items() if k != "n_estimators"}
        lgb_params["n_estimators"] = params.get("n_estimators", 200)

        gen = SignalGenerator()
        gen.train(
            self._bars,
            lookahead=self._lookahead,
            threshold_pct=self._threshold_pct,
            **lgb_params,
        )
        return gen
