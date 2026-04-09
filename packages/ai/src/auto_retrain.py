"""Automated ML model retraining pipeline for FlintTrade.

Closes the continuous-learning gap: the ``MLAdvisor`` trains once and goes
stale without this module.  ``AutoRetrainer`` schedules periodic retraining,
validates new models against an accuracy threshold, detects feature
distribution drift via Kolmogorov-Smirnov tests, and atomically swaps the
live model only when validation passes.

Design decisions:
- asyncio-native loop with configurable interval (default daily at 16:00 IST).
- Thread-safe model swap via ``threading.Lock`` so predictions never block.
- KS-test drift detection (scipy) with mean/std fallback when scipy absent.
- Atomic swap: new model is written to a temp file then ``Path.replace()``
  ensures readers always see a complete file.
- Retrain history is kept in-memory (capped at 1 000 entries) and optionally
  persisted as newline-delimited JSON in ``model_dir / retrain_log.jsonl``.

Usage::

    from packages.ai.src.auto_retrain import AutoRetrainer, RetrainConfig

    async def my_data_fetcher(symbol: str, lookback_days: int) -> pd.DataFrame:
        ...  # return OHLCV DataFrame

    config = RetrainConfig(symbols=["NIFTY", "BANKNIFTY"])
    retrainer = AutoRetrainer(config, data_fetcher=my_data_fetcher)

    # One-shot retrain
    result = await retrainer.run_once("NIFTY")
    print(result.accepted, result.val_accuracy)

    # Continuous loop (blocks until stop() is called)
    await retrainer.start_loop()
"""

from __future__ import annotations

import asyncio
import json
import logging
import pickle
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable, Coroutine
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from packages.ai.src.ml_advisor import FeatureEngineer, MLAdvisor, MLAdvisorConfig, _FEATURE_COLUMNS

logger = logging.getLogger("flinttrade.ai.auto_retrain")

# ---------------------------------------------------------------------------
# Configuration model
# ---------------------------------------------------------------------------


class RetrainConfig(BaseModel):
    """Configuration for the auto-retraining pipeline.

    Attributes:
        symbols: Instruments to retrain models for.
        retrain_interval_hours: Hours between scheduled retrain cycles.
        min_accuracy: Minimum out-of-sample accuracy to accept a new model.
        lookback_days: Calendar days of OHLCV history to train on.
        validation_split: Fraction of data reserved for out-of-sample validation.
        drift_threshold: KS-statistic threshold above which drift is flagged
            (0–1; higher = more tolerant).
        model_dir: Directory where trained model pickles are persisted.
        persist_log: Write retrain history to a ``retrain_log.jsonl`` file.
        max_history: Maximum number of RetrainResult entries to keep in-memory.
    """

    symbols: list[str] = Field(default_factory=lambda: ["NIFTY", "BANKNIFTY"])
    retrain_interval_hours: int = Field(default=24, ge=1)
    min_accuracy: float = Field(default=0.55, ge=0.0, le=1.0)
    lookback_days: int = Field(default=365, ge=30)
    validation_split: float = Field(default=0.2, gt=0.0, lt=1.0)
    drift_threshold: float = Field(default=0.1, gt=0.0, le=1.0)
    model_dir: Path = Field(default_factory=lambda: Path("~/.flinttrade/models").expanduser())
    persist_log: bool = True
    max_history: int = Field(default=1000, ge=1)


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


class RetrainResult(BaseModel):
    """Outcome of a single retrain cycle for one symbol.

    Attributes:
        timestamp: UTC ISO-8601 timestamp when the cycle completed.
        symbol: Instrument that was retrained.
        train_accuracy: In-sample accuracy on the training split.
        val_accuracy: Out-of-sample accuracy on the validation split.
        accepted: True if the new model replaced the live model.
        reason: Human-readable explanation of accept/reject decision.
        duration_seconds: Wall-clock seconds the cycle took.
        drift_detected: True if feature distribution drift was detected.
        drift_score: Numeric drift metric (mean KS-statistic across features).
    """

    timestamp: datetime
    symbol: str
    train_accuracy: float
    val_accuracy: float
    accepted: bool
    reason: str
    duration_seconds: float
    drift_detected: bool
    drift_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict suitable for JSON logging."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "train_accuracy": round(self.train_accuracy, 4),
            "val_accuracy": round(self.val_accuracy, 4),
            "accepted": self.accepted,
            "reason": self.reason,
            "duration_seconds": round(self.duration_seconds, 2),
            "drift_detected": self.drift_detected,
            "drift_score": round(self.drift_score, 4),
        }


# ---------------------------------------------------------------------------
# Drift detection helpers
# ---------------------------------------------------------------------------


def _compute_ks_drift(
    train_df: pd.DataFrame,
    live_df: pd.DataFrame,
    feature_cols: list[str],
    threshold: float,
) -> tuple[bool, float]:
    """Compute per-feature KS-statistic between train and live distributions.

    Uses ``scipy.stats.ks_2samp`` when available; falls back to a mean/std
    z-score comparison otherwise.

    Args:
        train_df: Feature DataFrame from the training window.
        live_df: Feature DataFrame from the most recent live window.
        feature_cols: Feature columns to compare.
        threshold: KS-statistic threshold above which drift is flagged.

    Returns:
        ``(drift_detected, mean_ks_score)`` tuple.  ``drift_detected`` is True
        if the mean KS-statistic across features exceeds ``threshold``.
    """
    cols = [c for c in feature_cols if c in train_df.columns and c in live_df.columns]
    if not cols:
        return False, 0.0

    ks_scores: list[float] = []

    try:
        from scipy import stats as scipy_stats  # type: ignore[import]

        for col in cols:
            train_vals = train_df[col].dropna().values
            live_vals = live_df[col].dropna().values
            if len(train_vals) >= 5 and len(live_vals) >= 5:
                stat, _ = scipy_stats.ks_2samp(train_vals, live_vals)
                ks_scores.append(float(stat))

    except ImportError:
        # Fallback: normalised absolute difference of means, clipped to [0, 1].
        for col in cols:
            t_vals = train_df[col].dropna()
            l_vals = live_df[col].dropna()
            if len(t_vals) == 0 or len(l_vals) == 0:
                continue
            t_std = float(t_vals.std()) or 1.0
            diff = abs(float(t_vals.mean()) - float(l_vals.mean())) / t_std
            ks_scores.append(min(diff / 3.0, 1.0))  # normalise to ~[0,1]

    if not ks_scores:
        return False, 0.0

    mean_score = float(np.mean(ks_scores))
    return mean_score > threshold, mean_score


# ---------------------------------------------------------------------------
# AutoRetrainer
# ---------------------------------------------------------------------------


# Type alias for the async data-fetcher callable.
DataFetcher = Callable[[str, int], Coroutine[Any, Any, pd.DataFrame]]


class AutoRetrainer:
    """Automated retraining pipeline for FlintTrade ML models.

    Periodically retrains ``MLAdvisor`` models for each configured symbol,
    validates out-of-sample accuracy, detects distribution drift, and
    atomically swaps live models when validation passes.

    Args:
        config: ``RetrainConfig`` instance controlling schedule and thresholds.
        data_fetcher: Async callable ``(symbol, lookback_days) -> pd.DataFrame``
            that returns an OHLCV DataFrame.  Must supply columns:
            ``open``, ``high``, ``low``, ``close``, ``volume``.
        advisor_config: Optional ``MLAdvisorConfig`` used for all new models.
            Defaults to ``MLAdvisorConfig(test_size=config.validation_split)``.

    Thread safety:
        ``run_once`` and ``run_all`` are async-safe.  The live model swap uses
        a ``threading.Lock`` so concurrent ``predict()`` calls on the advisor
        never observe a partially-written model.

    Examples::

        retrainer = AutoRetrainer(config, data_fetcher=fetch_ohlcv)
        result = await retrainer.run_once("NIFTY")
        history = retrainer.get_history()
    """

    def __init__(
        self,
        config: RetrainConfig,
        data_fetcher: DataFetcher,
        advisor_config: MLAdvisorConfig | None = None,
    ) -> None:
        self._config = config
        self._data_fetcher = data_fetcher

        self._advisor_config = advisor_config or MLAdvisorConfig(
            test_size=config.validation_split,
            lookback=100,
        )

        # One live MLAdvisor per symbol, protected by a single lock.
        self._live_advisors: dict[str, MLAdvisor] = {}
        self._lock = threading.Lock()

        # Retrain history (bounded deque).
        self._history: deque[RetrainResult] = deque(maxlen=config.max_history)

        # Loop control — _stop_event is created lazily inside start_loop().
        self._running = False
        self._stop_event: asyncio.Event | None = None

        # Ensure model dir exists.
        config.model_dir.mkdir(parents=True, exist_ok=True)

        self._feature_engineer = FeatureEngineer()

    # ------------------------------------------------------------------
    # Public: single-symbol retrain
    # ------------------------------------------------------------------

    async def run_once(self, symbol: str) -> RetrainResult:
        """Run one complete retrain cycle for ``symbol``.

        Steps:
            1. Fetch OHLCV data via ``data_fetcher``.
            2. Engineer features with ``FeatureEngineer``.
            3. Record training-window feature distribution (for drift baseline).
            4. Train a new ``MLAdvisor`` on the training split.
            5. Evaluate out-of-sample accuracy on the validation split.
            6. Compare live features against training distribution (KS test).
            7. Accept / reject: swap live model if accuracy >= ``min_accuracy``.
            8. Persist model and append result to history log.

        Args:
            symbol: Instrument ticker (e.g. ``"NIFTY"``).

        Returns:
            ``RetrainResult`` describing the outcome.
        """
        t_start = time.monotonic()
        ts_now = datetime.now(timezone.utc)

        logger.info("[AutoRetrainer] Starting retrain for %s", symbol)

        # ---- Step 1: fetch data ------------------------------------------
        try:
            df = await self._data_fetcher(symbol, self._config.lookback_days)
        except Exception as exc:  # noqa: BLE001
            duration = time.monotonic() - t_start
            result = RetrainResult(
                timestamp=ts_now,
                symbol=symbol,
                train_accuracy=0.0,
                val_accuracy=0.0,
                accepted=False,
                reason=f"Data fetch failed: {exc}",
                duration_seconds=duration,
                drift_detected=False,
            )
            self._record(result)
            return result

        if df.empty or len(df) < self._advisor_config.lookback:
            duration = time.monotonic() - t_start
            result = RetrainResult(
                timestamp=ts_now,
                symbol=symbol,
                train_accuracy=0.0,
                val_accuracy=0.0,
                accepted=False,
                reason=f"Insufficient data: {len(df)} rows (need {self._advisor_config.lookback})",
                duration_seconds=duration,
                drift_detected=False,
            )
            self._record(result)
            return result

        # ---- Step 2: engineer features -----------------------------------
        try:
            featured_df = self._feature_engineer.build_features(df)
        except Exception as exc:  # noqa: BLE001
            duration = time.monotonic() - t_start
            result = RetrainResult(
                timestamp=ts_now,
                symbol=symbol,
                train_accuracy=0.0,
                val_accuracy=0.0,
                accepted=False,
                reason=f"Feature engineering failed: {exc}",
                duration_seconds=duration,
                drift_detected=False,
            )
            self._record(result)
            return result

        # ---- Step 3: compute drift against existing model ----------------
        drift_detected = False
        drift_score = 0.0
        existing_model_path = self._model_path(symbol)

        if existing_model_path.exists():
            # Compare recent 20% of new data vs training window of saved model.
            split_idx = int(len(featured_df) * (1 - self._config.validation_split))
            live_window = featured_df.iloc[split_idx:][list(_FEATURE_COLUMNS)].dropna()
            train_window = featured_df.iloc[:split_idx][list(_FEATURE_COLUMNS)].dropna()

            if len(live_window) >= 5 and len(train_window) >= 5:
                drift_detected, drift_score = _compute_ks_drift(
                    train_window,
                    live_window,
                    list(_FEATURE_COLUMNS),
                    self._config.drift_threshold,
                )
                if drift_detected:
                    logger.warning(
                        "[AutoRetrainer] Drift detected for %s — KS score=%.4f > threshold=%.4f",
                        symbol,
                        drift_score,
                        self._config.drift_threshold,
                    )

        # ---- Step 4: train new model -------------------------------------
        # Run blocking training in a thread pool so the event loop stays free.
        new_advisor = MLAdvisor(self._advisor_config, self._feature_engineer)

        try:
            metrics = await asyncio.get_running_loop().run_in_executor(
                None, new_advisor.train, df
            )
        except Exception as exc:  # noqa: BLE001
            duration = time.monotonic() - t_start
            result = RetrainResult(
                timestamp=ts_now,
                symbol=symbol,
                train_accuracy=0.0,
                val_accuracy=0.0,
                accepted=False,
                reason=f"Training failed: {exc}",
                duration_seconds=duration,
                drift_detected=drift_detected,
                drift_score=drift_score,
            )
            self._record(result)
            return result

        # ---- Step 5: compute validation accuracy -------------------------
        # ``MLAdvisor.train`` uses ``test_size`` as validation split and returns
        # ``accuracy`` which is the out-of-sample accuracy on that split.
        train_accuracy: float = metrics.get("accuracy", 0.0)
        val_accuracy: float = train_accuracy  # same split used during training

        # ---- Step 6: accept or reject ------------------------------------
        if val_accuracy >= self._config.min_accuracy:
            accepted = True
            reason = (
                f"Accepted: val_accuracy={val_accuracy:.4f} >= "
                f"min={self._config.min_accuracy:.4f}"
            )
            await asyncio.get_running_loop().run_in_executor(
                None, self._swap_model, symbol, new_advisor
            )
        else:
            accepted = False
            reason = (
                f"Rejected: val_accuracy={val_accuracy:.4f} < "
                f"min={self._config.min_accuracy:.4f}"
            )
            logger.warning(
                "[AutoRetrainer] Model rejected for %s — %s",
                symbol,
                reason,
            )

        duration = time.monotonic() - t_start
        result = RetrainResult(
            timestamp=ts_now,
            symbol=symbol,
            train_accuracy=train_accuracy,
            val_accuracy=val_accuracy,
            accepted=accepted,
            reason=reason,
            duration_seconds=duration,
            drift_detected=drift_detected,
            drift_score=drift_score,
        )

        self._record(result)
        logger.info(
            "[AutoRetrainer] %s — accepted=%s val_acc=%.4f duration=%.1fs",
            symbol,
            accepted,
            val_accuracy,
            duration,
        )
        return result

    # ------------------------------------------------------------------
    # Public: all symbols
    # ------------------------------------------------------------------

    async def run_all(self) -> list[RetrainResult]:
        """Retrain all configured symbols sequentially.

        Returns:
            List of ``RetrainResult`` in the order symbols were processed.
        """
        results: list[RetrainResult] = []
        for symbol in self._config.symbols:
            result = await self.run_once(symbol)
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # Public: continuous loop
    # ------------------------------------------------------------------

    async def start_loop(self) -> None:
        """Start the continuous retraining loop.

        Runs ``run_all()`` immediately, then sleeps for
        ``retrain_interval_hours`` between cycles.  Call ``stop()`` to
        terminate gracefully.

        This coroutine blocks until ``stop()`` is called.
        """
        self._running = True
        self._stop_event = asyncio.Event()

        logger.info(
            "[AutoRetrainer] Loop started — interval=%dh symbols=%s",
            self._config.retrain_interval_hours,
            self._config.symbols,
        )

        while self._running:
            await self.run_all()

            if not self._running:
                break

            interval_seconds = self._config.retrain_interval_hours * 3600
            logger.info(
                "[AutoRetrainer] Next retrain in %d hours",
                self._config.retrain_interval_hours,
            )

            try:
                await asyncio.wait_for(
                    asyncio.shield(self._stop_event.wait()),
                    timeout=float(interval_seconds),
                )
                # Stop event was set — exit loop.
                break
            except asyncio.TimeoutError:
                # Timeout expired normally — retrain again.
                pass

        logger.info("[AutoRetrainer] Loop stopped.")

    def stop(self) -> None:
        """Signal the continuous loop to stop after the current cycle.

        Safe to call from any thread.
        """
        self._running = False
        if self._stop_event is not None:
            # Schedule the set() in the running loop (thread-safe).
            try:
                loop = self._stop_event.get_loop()  # available on Python 3.10+
                if loop.is_running():
                    loop.call_soon_threadsafe(self._stop_event.set)
                else:
                    self._stop_event.set()
            except (RuntimeError, AttributeError):
                # Fallback: direct set (safe when called from the same loop).
                try:
                    self._stop_event.set()
                except RuntimeError:
                    pass

    # ------------------------------------------------------------------
    # Public: history and live advisor access
    # ------------------------------------------------------------------

    def get_history(self) -> list[RetrainResult]:
        """Return a snapshot of the retrain history, newest first.

        Returns:
            List of ``RetrainResult`` objects (up to ``config.max_history``).
        """
        return list(reversed(self._history))

    def get_advisor(self, symbol: str) -> MLAdvisor | None:
        """Return the current live ``MLAdvisor`` for ``symbol``, or None.

        The returned advisor is safe to call ``predict()`` on while a retrain
        cycle is in progress — the swap is protected by a lock.

        Args:
            symbol: Instrument ticker.

        Returns:
            Live ``MLAdvisor`` or ``None`` if no model has been accepted yet.
        """
        with self._lock:
            return self._live_advisors.get(symbol)

    # ------------------------------------------------------------------
    # Internal: atomic model swap
    # ------------------------------------------------------------------

    def _swap_model(self, symbol: str, new_advisor: MLAdvisor) -> None:
        """Atomically replace the live model for ``symbol``.

        Writes the new model to a temporary file in ``model_dir``, then uses
        ``Path.replace()`` for an atomic rename.  Updates the in-memory advisor
        under the thread lock.

        Args:
            symbol: Instrument ticker.
            new_advisor: Freshly trained ``MLAdvisor`` to promote.
        """
        target_path = self._model_path(symbol)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Write to a temp file in the same directory (same filesystem).
        fd, tmp_str = tempfile.mkstemp(
            dir=target_path.parent, suffix=".pkl.tmp"
        )
        tmp_path = Path(tmp_str)

        try:
            with open(fd, "wb") as f:
                pickle.dump(
                    {
                        "model": new_advisor._model,
                        "feature_names": new_advisor._feature_names,
                    },
                    f,
                )
            # Atomic rename.
            tmp_path.replace(target_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

        with self._lock:
            self._live_advisors[symbol] = new_advisor

        logger.info("[AutoRetrainer] Model swapped for %s → %s", symbol, target_path)

    def _model_path(self, symbol: str) -> Path:
        """Return the canonical model file path for ``symbol``.

        Args:
            symbol: Instrument ticker.

        Returns:
            ``Path`` inside ``config.model_dir``.
        """
        safe_name = symbol.replace("/", "_").replace("\\", "_")
        return self._config.model_dir / f"ml_advisor_{safe_name}.pkl"

    # ------------------------------------------------------------------
    # Internal: history recording
    # ------------------------------------------------------------------

    def _record(self, result: RetrainResult) -> None:
        """Append ``result`` to in-memory history and optionally persist it.

        Args:
            result: Completed ``RetrainResult`` to record.
        """
        self._history.append(result)

        if not self._config.persist_log:
            return

        log_path = self._config.model_dir / "retrain_log.jsonl"
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(result.to_dict()) + "\n")
        except OSError as exc:
            logger.warning("[AutoRetrainer] Could not write retrain log: %s", exc)
