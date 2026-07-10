"""Canonical per-instrument retraining for the scheduled signal pipeline."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import os
import re
import tempfile
import threading
import time
import zipfile
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

_BUNDLE_VERSION = 1
_BASELINE_VERSION = 1
_BUNDLE_MEMBERS = frozenset({"metadata.json", "model.joblib", "model.sha256"})


def _default_model_dir() -> Path:
    from flinttrade_core.workspace import workspace_dir

    return workspace_dir() / "models"


class RetrainConfig(BaseModel):
    """Configuration for canonical signal-model retraining."""

    retrain_interval_hours: int = Field(default=24, ge=1)
    min_accuracy: float = Field(default=0.55, ge=0.0, le=1.0)
    min_training_rows: int = Field(default=100, ge=30)
    lookback_days: int = Field(default=365, ge=30)
    lookahead: int = Field(default=5, ge=1)
    buy_threshold_pct: float = Field(default=0.5, gt=0.0, allow_inf_nan=False)
    sell_threshold_pct: float = Field(default=-0.5, lt=0.0, allow_inf_nan=False)
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
    return cleaned[:48]


def _instrument_identity_digest(symbol: str, exchange: str) -> str:
    """Hash an unambiguous length-delimited ``(exchange, symbol)`` pair."""
    digest = hashlib.sha256()
    for value in (exchange, symbol):
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, byteorder="big"))
        digest.update(encoded)
    return digest.hexdigest()


def signal_model_path(model_dir: Path, symbol: str, exchange: str) -> Path:
    """Return the canonical deterministic path for one instrument model."""
    safe_exchange = _safe_path_component(exchange)
    safe_symbol = _safe_path_component(symbol)
    digest = _instrument_identity_digest(symbol, exchange)
    return model_dir / f"signal_model_{safe_exchange}_{safe_symbol}_{digest}.bundle"


def _temporary_path(target: Path, label: str) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f"{target.name}.{label}.",
        suffix=".tmp",
        dir=target.parent,
    )
    os.close(descriptor)
    return Path(name)


def _baseline_payload(baseline: FeatureSet, *, model_sha256: str) -> dict[str, Any]:
    return {
        "version": _BASELINE_VERSION,
        "model_sha256": model_sha256,
        "feature_names": list(baseline.names),
        "values": [list(row) for row in baseline.values],
    }


def _validate_baseline(payload: Any, *, model_sha256: str) -> FeatureSet:
    if not isinstance(payload, dict) or payload.get("version") != _BASELINE_VERSION:
        raise ValueError("Signal model bundle has missing or unsupported baseline metadata")
    baseline_digest = payload.get("model_sha256")
    if not isinstance(baseline_digest, str) or not hmac.compare_digest(baseline_digest, model_sha256):
        raise ValueError("Signal model bundle baseline is not associated with its model digest")

    names = payload.get("feature_names")
    values = payload.get("values")
    if (
        not isinstance(names, list)
        or not names
        or not all(isinstance(name, str) and name for name in names)
        or len(set(names)) != len(names)
    ):
        raise ValueError("Signal model bundle baseline has invalid feature names")
    if not isinstance(values, list) or not values:
        raise ValueError("Signal model bundle baseline has no feature values")

    validated_values: list[list[float]] = []
    for row in values:
        if not isinstance(row, list) or len(row) != len(names):
            raise ValueError("Signal model bundle baseline row does not match its feature names")
        validated_row: list[float] = []
        for value in row:
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError("Signal model bundle baseline contains a non-numeric value")
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValueError("Signal model bundle baseline contains a non-finite value")
            validated_row.append(numeric)
        validated_values.append(validated_row)
    return FeatureSet(names=list(names), values=validated_values)


def _read_verified_bundle(
    path: Path,
    *,
    symbol: str,
    exchange: str,
) -> tuple[bytes, str, FeatureSet]:
    """Validate one complete bundle without deserialising its joblib member."""
    with zipfile.ZipFile(path) as bundle:
        names = [member.filename for member in bundle.infolist()]
        if len(names) != len(_BUNDLE_MEMBERS) or set(names) != _BUNDLE_MEMBERS:
            raise ValueError("Signal model bundle has missing, duplicate, or unexpected members")
        try:
            metadata = json.loads(bundle.read("metadata.json").decode("utf-8"))
            checksum = bundle.read("model.sha256").decode("ascii").strip()
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Signal model bundle metadata is not valid JSON/ASCII") from exc

        if not isinstance(metadata, dict) or metadata.get("bundle_version") != _BUNDLE_VERSION:
            raise ValueError("Signal model bundle has an unsupported version")
        identity = metadata.get("identity")
        expected_identity_digest = _instrument_identity_digest(symbol, exchange)
        if not isinstance(identity, dict):
            raise ValueError("Signal model bundle has no instrument identity")
        if identity.get("exchange") != exchange or identity.get("symbol") != symbol:
            raise ValueError("Signal model bundle instrument identity does not match its requested instrument")
        identity_digest = identity.get("digest")
        if not isinstance(identity_digest, str) or not hmac.compare_digest(identity_digest, expected_identity_digest):
            raise ValueError("Signal model bundle instrument identity digest is invalid")

        metadata_digest = metadata.get("model_sha256")
        if not isinstance(metadata_digest, str) or re.fullmatch(r"[0-9a-f]{64}", metadata_digest) is None:
            raise ValueError("Signal model bundle has an invalid model digest")
        if re.fullmatch(r"[0-9a-f]{64}", checksum) is None or not hmac.compare_digest(checksum, metadata_digest):
            raise ValueError("Signal model bundle checksum metadata does not match")
        baseline = _validate_baseline(metadata.get("baseline"), model_sha256=metadata_digest)

        model_bytes = bundle.read("model.joblib")
    actual_digest = hashlib.sha256(model_bytes).hexdigest()
    if not hmac.compare_digest(actual_digest, metadata_digest):
        raise RuntimeError(f"Refusing to load {path.name}: SHA-256 checksum mismatch")
    return model_bytes, metadata_digest, baseline


def _write_model_bundle(
    path: Path,
    candidate: SignalGenerator,
    baseline: FeatureSet,
    *,
    symbol: str,
    exchange: str,
) -> None:
    """Write one complete guarded model bundle to ``path`` without publishing it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_model = _temporary_path(path, "joblib")
    temp_sidecar = SignalGenerator._checksum_path(temp_model)
    try:
        candidate.save(str(temp_model))
        if not temp_model.exists() or not temp_sidecar.exists():
            raise OSError("candidate persistence did not produce model and checksum files")
        model_bytes = temp_model.read_bytes()
        checksum = temp_sidecar.read_text(encoding="ascii").strip()
        actual_digest = hashlib.sha256(model_bytes).hexdigest()
        if not hmac.compare_digest(checksum, actual_digest):
            raise RuntimeError("candidate model checksum does not match its persisted bytes")

        baseline_payload = _baseline_payload(baseline, model_sha256=actual_digest)
        _validate_baseline(baseline_payload, model_sha256=actual_digest)
        metadata = {
            "bundle_version": _BUNDLE_VERSION,
            "accepted_at": datetime.now(timezone.utc).isoformat(),
            "identity": {
                "exchange": exchange,
                "symbol": symbol,
                "digest": _instrument_identity_digest(symbol, exchange),
            },
            "model_sha256": actual_digest,
            "baseline": baseline_payload,
        }
        metadata_bytes = json.dumps(
            metadata,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("metadata.json", metadata_bytes)
            bundle.writestr("model.joblib", model_bytes)
            bundle.writestr("model.sha256", actual_digest.encode("ascii"))
        with path.open("rb") as bundle_file:
            os.fsync(bundle_file.fileno())
    finally:
        temp_model.unlink(missing_ok=True)
        temp_sidecar.unlink(missing_ok=True)


def load_signal_model_bundle(path: Path, *, symbol: str, exchange: str) -> SignalGenerator:
    """Load a verified per-instrument bundle after validating all metadata."""
    model_bytes, model_sha256, _baseline = _read_verified_bundle(
        path,
        symbol=symbol,
        exchange=exchange,
    )
    generator = SignalGenerator()
    generator.load_guarded_bytes(model_bytes, model_sha256, source_name=path.name)
    return generator


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
        self._live_generators: dict[tuple[str, str], SignalGenerator] = {}
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

        if len(bars) < self.config.min_training_rows:
            return self._record_failure(
                started,
                symbol,
                exchange,
                f"Insufficient data: {len(bars)} bars; need at least {self.config.min_training_rows}",
            )

        features = engineer_features(bars)
        if not features.values:
            return self._record_failure(started, symbol, exchange, f"Insufficient data: {len(bars)} bars")

        drift_detected = False
        drift_score = 0.0
        target = self.model_path(symbol, exchange)
        if target.exists():
            try:
                _model_bytes, _model_sha256, incumbent_baseline = _read_verified_bundle(
                    target,
                    symbol=symbol,
                    exchange=exchange,
                )
            except Exception as exc:  # noqa: BLE001 - invalid baseline means no drift, not failed retraining
                logger.warning("Could not verify incumbent baseline for %s:%s: %s", exchange, symbol, exc)
            else:
                split = int(len(features.values) * (1 - self.config.validation_split))
                recent = FeatureSet(names=features.names, values=features.values[split:])
                drift_detected, drift_score = compute_feature_drift(
                    incumbent_baseline,
                    recent,
                    threshold=self.config.drift_threshold,
                )

        training_split = int(len(features.values) * (1 - self.config.validation_split))
        training_baseline = FeatureSet(
            names=list(features.names),
            values=[list(row) for row in features.values[:training_split]],
        )

        candidate = SignalGenerator()
        try:
            metrics = candidate.train(
                bars,
                lookahead=self.config.lookahead,
                buy_threshold_pct=self.config.buy_threshold_pct,
                sell_threshold_pct=self.config.sell_threshold_pct,
                test_ratio=self.config.validation_split,
                min_training_rows=self.config.min_training_rows,
            )
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
            self._promote(symbol, exchange, candidate, training_baseline)
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
            return self._live_generators.get((exchange, symbol))

    def _promote(
        self,
        symbol: str,
        exchange: str,
        candidate: SignalGenerator,
        training_baseline: FeatureSet,
    ) -> None:
        target = self.model_path(symbol, exchange)
        target.parent.mkdir(parents=True, exist_ok=True)

        with self._promotion_lock:
            temp_bundle = _temporary_path(target, "candidate")
            try:
                _write_model_bundle(
                    temp_bundle,
                    candidate,
                    training_baseline,
                    symbol=symbol,
                    exchange=exchange,
                )

                def _publish() -> None:
                    temp_bundle.replace(target)

                if self._pipeline is not None:
                    self._pipeline.publish_generator(symbol, exchange, candidate, _publish)
                else:
                    _publish()
                self._live_generators[(exchange, symbol)] = candidate
            finally:
                temp_bundle.unlink(missing_ok=True)

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
