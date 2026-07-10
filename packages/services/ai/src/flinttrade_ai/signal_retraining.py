"""Canonical per-instrument retraining for the scheduled signal pipeline."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import shutil
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any

from pydantic import BaseModel, Field

from .signals import FeatureSet, SignalGenerator, engineer_features

try:
    from scipy.stats import ks_2samp as _scipy_ks_2samp
except (ImportError, OSError):
    _scipy_ks_2samp = None

logger = logging.getLogger("flinttrade.ai.signal_retraining")

DataFetcher = Callable[[str, str, int], list[dict[str, Any]]]


def _default_model_dir() -> Path:
    from flinttrade_core.workspace import workspace_dir

    return workspace_dir() / "models"


class RetrainConfig(BaseModel):
    """Configuration for canonical signal-model retraining."""

    retrain_interval_hours: int = Field(default=24, ge=1)
    min_accuracy: float = Field(default=0.55, ge=0.0, le=1.0)
    lookback_days: int = Field(default=365, ge=30)
    validation_split: float = Field(default=0.2, gt=0.0, lt=1.0)
    drift_threshold: float = Field(default=0.1, gt=0.0, le=1.0)
    model_dir: Path = Field(default_factory=_default_model_dir)
    persist_log: bool = True
    max_history: int = Field(default=1000, ge=1)


class RetrainResult(BaseModel):
    """Outcome of one canonical per-instrument retraining attempt."""

    timestamp: datetime
    symbol: str
    exchange: str
    train_accuracy: float
    test_accuracy: float
    accepted: bool
    reason: str
    duration_seconds: float
    drift_detected: bool
    drift_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-compatible history record."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.symbol,
            "exchange": self.exchange,
            "train_accuracy": round(self.train_accuracy, 4),
            "test_accuracy": round(self.test_accuracy, 4),
            "accepted": self.accepted,
            "reason": self.reason,
            "duration_seconds": round(self.duration_seconds, 2),
            "drift_detected": self.drift_detected,
            "drift_score": round(self.drift_score, 4),
        }


def _feature_columns(features: FeatureSet | None) -> dict[str, list[float]]:
    if features is None or not features.names or not features.values:
        return {}

    columns: dict[str, list[float]] = {name: [] for name in features.names}
    for row in features.values:
        for name, value in zip(features.names, row, strict=False):
            numeric = float(value)
            if math.isfinite(numeric):
                columns[name].append(numeric)
    return columns


def _fallback_distribution_score(reference: list[float], current: list[float]) -> float:
    reference_std = pstdev(reference) if len(reference) > 1 else 0.0
    scale = reference_std or 1.0
    normalised_mean_shift = abs(fmean(reference) - fmean(current)) / scale
    return min(normalised_mean_shift / 3.0, 1.0)


def compute_feature_drift(
    reference: FeatureSet | None,
    current: FeatureSet | None,
    *,
    threshold: float,
) -> tuple[bool, float]:
    """Compare canonical feature distributions and return mean drift score."""
    reference_columns = _feature_columns(reference)
    current_columns = _feature_columns(current)
    shared_names = [name for name in reference_columns if name in current_columns]
    scores: list[float] = []

    for name in shared_names:
        reference_values = reference_columns[name]
        current_values = current_columns[name]
        if not reference_values or not current_values:
            continue
        if _scipy_ks_2samp is not None and len(reference_values) >= 5 and len(current_values) >= 5:
            result = _scipy_ks_2samp(reference_values, current_values)
            scores.append(float(result.statistic))
        else:
            scores.append(_fallback_distribution_score(reference_values, current_values))

    if not scores:
        return False, 0.0
    mean_score = fmean(scores)
    return mean_score > threshold, mean_score


def _safe_path_component(value: str) -> str:
    raw = value.strip()
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._")
    if not cleaned:
        cleaned = "UNKNOWN"
    if cleaned != raw or len(cleaned) > 80:
        suffix = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]
        cleaned = f"{cleaned[:71]}_{suffix}"
    return cleaned


def signal_model_path(model_dir: Path, symbol: str, exchange: str) -> Path:
    """Return the canonical deterministic path for one instrument model."""
    safe_exchange = _safe_path_component(exchange)
    safe_symbol = _safe_path_component(symbol)
    return model_dir / f"signal_model_{safe_exchange}_{safe_symbol}.joblib"


class SignalRetrainer:
    """Retrain fresh ``SignalGenerator`` instances for a pipeline roster."""

    def __init__(
        self,
        config: RetrainConfig,
        *,
        instruments: list[dict[str, str]],
        data_fetcher: DataFetcher,
        pipeline: Any | None = None,
    ) -> None:
        self.config = config
        self.instruments = [dict(instrument) for instrument in instruments]
        self._data_fetcher = data_fetcher
        self._pipeline = pipeline
        self._history: deque[RetrainResult] = deque(maxlen=config.max_history)
        self._history_lock = threading.Lock()
        self._promotion_lock = threading.Lock()
        self._live_generators: dict[str, SignalGenerator] = {}
        self.config.model_dir.mkdir(parents=True, exist_ok=True)

    def model_path(self, symbol: str, exchange: str) -> Path:
        """Return the deterministic per-instrument model path."""
        return signal_model_path(self.config.model_dir, symbol, exchange)

    def run_once(self, symbol: str, exchange: str) -> RetrainResult:
        """Fetch, train, validate, and conditionally promote one instrument."""
        started = time.monotonic()
        try:
            bars = self._data_fetcher(symbol, exchange, self.config.lookback_days)
        except Exception as exc:  # noqa: BLE001 - one instrument must not stop the roster
            return self._record_failure(started, symbol, exchange, f"Data fetch failed: {exc}")

        features = engineer_features(bars)
        if not features.values:
            return self._record_failure(started, symbol, exchange, f"Insufficient data: {len(bars)} bars")

        drift_detected = False
        drift_score = 0.0
        target = self.model_path(symbol, exchange)
        if target.exists():
            split = int(len(features.values) * (1 - self.config.validation_split))
            reference = FeatureSet(names=features.names, values=features.values[:split])
            current = FeatureSet(names=features.names, values=features.values[split:])
            drift_detected, drift_score = compute_feature_drift(
                reference,
                current,
                threshold=self.config.drift_threshold,
            )

        candidate = SignalGenerator()
        try:
            metrics = candidate.train(bars, test_ratio=self.config.validation_split)
        except Exception as exc:  # noqa: BLE001 - optional ML dependencies may be absent
            return self._record_failure(
                started,
                symbol,
                exchange,
                f"Training failed: {exc}",
                drift_detected=drift_detected,
                drift_score=drift_score,
            )

        train_accuracy = float(metrics.get("train_accuracy", 0.0))
        test_accuracy = float(metrics.get("test_accuracy", 0.0))
        if test_accuracy < self.config.min_accuracy:
            result = self._result(
                started,
                symbol,
                exchange,
                train_accuracy=train_accuracy,
                test_accuracy=test_accuracy,
                accepted=False,
                reason=(f"Rejected: test_accuracy={test_accuracy:.4f} < min={self.config.min_accuracy:.4f}"),
                drift_detected=drift_detected,
                drift_score=drift_score,
            )
            self._record(result)
            return result

        try:
            self._promote(symbol, exchange, candidate)
        except Exception as exc:  # noqa: BLE001 - failed promotion must remain advisory
            return self._record_failure(
                started,
                symbol,
                exchange,
                f"Persistence failed: {exc}",
                train_accuracy=train_accuracy,
                test_accuracy=test_accuracy,
                drift_detected=drift_detected,
                drift_score=drift_score,
            )

        result = self._result(
            started,
            symbol,
            exchange,
            train_accuracy=train_accuracy,
            test_accuracy=test_accuracy,
            accepted=True,
            reason=(f"Accepted: test_accuracy={test_accuracy:.4f} >= min={self.config.min_accuracy:.4f}"),
            drift_detected=drift_detected,
            drift_score=drift_score,
        )
        self._record(result)
        return result

    def run_all(self) -> list[RetrainResult]:
        """Retrain every pipeline instrument, continuing after any failure."""
        results: list[RetrainResult] = []
        for instrument in self.instruments:
            symbol = str(instrument.get("symbol", ""))
            exchange = str(instrument.get("exchange", ""))
            try:
                result = self.run_once(symbol, exchange)
            except Exception as exc:  # pragma: no cover - final containment guard
                result = self._record_failure(
                    time.monotonic(),
                    symbol,
                    exchange,
                    f"Retrain failed: {exc}",
                )
            results.append(result)
        return results

    def get_history(self) -> list[RetrainResult]:
        """Return a newest-first snapshot of bounded retraining history."""
        with self._history_lock:
            return list(self._history)

    def get_generator(self, symbol: str, exchange: str) -> SignalGenerator | None:
        """Return the retrainer's last accepted generator for an instrument."""
        with self._promotion_lock:
            return self._live_generators.get(f"{exchange}:{symbol}")

    def _promote(self, symbol: str, exchange: str, candidate: SignalGenerator) -> None:
        target = self.model_path(symbol, exchange)
        target_sidecar = SignalGenerator._checksum_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)

        with self._promotion_lock:
            temp_model = self._temporary_path(target, "candidate")
            temp_sidecar = SignalGenerator._checksum_path(temp_model)
            model_backup: Path | None = None
            sidecar_backup: Path | None = None
            try:
                model_backup = self._backup(target)
                sidecar_backup = self._backup(target_sidecar)
            except Exception:
                for path in (temp_model, temp_sidecar, model_backup, sidecar_backup):
                    if path is not None:
                        path.unlink(missing_ok=True)
                raise
            try:
                candidate.save(str(temp_model))
                if not temp_model.exists() or not temp_sidecar.exists():
                    raise OSError("candidate persistence did not produce model and checksum files")
                temp_model.replace(target)
                temp_sidecar.replace(target_sidecar)
                if self._pipeline is not None:
                    self._pipeline.install_generator(symbol, exchange, candidate)
                self._live_generators[f"{exchange}:{symbol}"] = candidate
            except Exception:
                self._restore(target, model_backup)
                self._restore(target_sidecar, sidecar_backup)
                raise
            finally:
                for path in (temp_model, temp_sidecar, model_backup, sidecar_backup):
                    if path is not None:
                        path.unlink(missing_ok=True)

    @staticmethod
    def _temporary_path(target: Path, label: str) -> Path:
        descriptor, name = tempfile.mkstemp(
            prefix=f"{target.name}.{label}.",
            suffix=".tmp",
            dir=target.parent,
        )
        os.close(descriptor)
        return Path(name)

    def _backup(self, path: Path) -> Path | None:
        if not path.exists():
            return None
        backup = self._temporary_path(path, "backup")
        try:
            shutil.copy2(path, backup)
        except Exception:
            backup.unlink(missing_ok=True)
            raise
        return backup

    @staticmethod
    def _restore(path: Path, backup: Path | None) -> None:
        if backup is None:
            path.unlink(missing_ok=True)
            return
        backup.replace(path)

    def _result(
        self,
        started: float,
        symbol: str,
        exchange: str,
        *,
        train_accuracy: float,
        test_accuracy: float,
        accepted: bool,
        reason: str,
        drift_detected: bool,
        drift_score: float,
    ) -> RetrainResult:
        return RetrainResult(
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            exchange=exchange,
            train_accuracy=train_accuracy,
            test_accuracy=test_accuracy,
            accepted=accepted,
            reason=reason,
            duration_seconds=time.monotonic() - started,
            drift_detected=drift_detected,
            drift_score=drift_score,
        )

    def _record_failure(
        self,
        started: float,
        symbol: str,
        exchange: str,
        reason: str,
        *,
        train_accuracy: float = 0.0,
        test_accuracy: float = 0.0,
        drift_detected: bool = False,
        drift_score: float = 0.0,
    ) -> RetrainResult:
        result = self._result(
            started,
            symbol,
            exchange,
            train_accuracy=train_accuracy,
            test_accuracy=test_accuracy,
            accepted=False,
            reason=reason,
            drift_detected=drift_detected,
            drift_score=drift_score,
        )
        self._record(result)
        return result

    def _record(self, result: RetrainResult) -> None:
        with self._history_lock:
            self._history.appendleft(result)
        if not self.config.persist_log:
            return
        try:
            self._append_log(result)
        except OSError as exc:
            logger.warning("Could not write signal retrain log: %s", exc)

    def _append_log(self, result: RetrainResult) -> None:
        log_path = self.config.model_dir / "signal_retrain_log.jsonl"
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(json.dumps(result.to_dict()) + "\n")
