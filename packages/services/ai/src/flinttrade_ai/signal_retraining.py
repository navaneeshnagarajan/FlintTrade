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
from datetime import date, datetime, time as wall_time, timedelta, timezone
from pathlib import Path
from queue import Empty, Queue
from statistics import fmean, pstdev
from typing import Any, Literal

from pydantic import BaseModel, Field

from .signals import (
    FeatureSet,
    SignalGenerator,
    TrainingCancelled,
    engineer_features,
    generate_labels,
    walk_forward_split_bounds,
)
from .pipeline import (
    MarketSessionProvider,
    _filter_closed_bars,
    _prepare_scheduled_bars,
)

try:
    from scipy.stats import ks_2samp as _scipy_ks_2samp
except (ImportError, OSError):
    _scipy_ks_2samp = None

logger = logging.getLogger("flinttrade.ai.signal_retraining")

DataFetcher = Callable[[str, str, int], list[dict[str, Any]]]
Clock = Callable[[], datetime]
CancellationCheck = Callable[[], bool]

_BUNDLE_VERSION = 1
_BASELINE_VERSION = 1
_BUNDLE_MEMBERS = frozenset({"metadata.json", "model.joblib", "model.sha256"})
_FETCH_CANCELLATION_POLL_SECONDS = 0.05
_IST = timezone(timedelta(hours=5, minutes=30))

RetrainRoster = Literal["regular", "late"]
SessionLookup = Callable[[str, str, date], tuple[wall_time, wall_time] | None]
ContinuousLookup = Callable[[str], bool]


def select_retraining_roster(
    instruments: list[dict[str, str]],
    *,
    roster: RetrainRoster,
    session_date: date,
    run_at: datetime | wall_time,
    is_continuous: ContinuousLookup,
    session_for: SessionLookup,
    regular_cutoff: wall_time = wall_time(16, 0),
) -> list[dict[str, str]]:
    """Select one non-overlapping regular or late/continuous training roster."""
    if roster not in {"regular", "late"}:
        raise ValueError("roster must be 'regular' or 'late'")
    cutoff = regular_cutoff.replace(tzinfo=None)
    selected: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for instrument in instruments:
        exchange = str(instrument.get("exchange") or "").strip().upper()
        symbol = str(instrument.get("symbol") or "").strip().upper()
        identity = (exchange, symbol)
        if not exchange or not symbol or identity in seen:
            continue
        try:
            continuous = bool(is_continuous(exchange))
        except Exception:  # noqa: BLE001 - unknown calendar state fails closed
            logger.exception("Retraining continuity lookup failed for %s:%s", exchange, symbol)
            continue
        if continuous:
            if roster == "late":
                selected.append({"symbol": symbol, "exchange": exchange})
                seen.add(identity)
            continue
        try:
            session = session_for(exchange, symbol, session_date)
        except Exception:  # noqa: BLE001 - unknown session state fails closed
            logger.exception("Retraining session lookup failed for %s:%s", exchange, symbol)
            continue
        if session is None:
            continue
        session_open, session_close = (
            value.replace(tzinfo=None) for value in session
        )
        if session_open == session_close:
            continue
        closes_at = datetime.combine(session_date, session_close, tzinfo=_IST)
        cross_midnight = session_close < session_open
        if cross_midnight:
            closes_at += timedelta(days=1)
        cutoff_at = datetime.combine(session_date, cutoff, tzinfo=_IST)
        intended_roster: RetrainRoster = "regular" if closes_at <= cutoff_at else "late"

        if isinstance(run_at, datetime):
            run_datetime = (
                run_at.replace(tzinfo=_IST)
                if run_at.tzinfo is None or run_at.utcoffset() is None
                else run_at.astimezone(_IST)
            )
        else:
            run_time = run_at.replace(tzinfo=None)
            run_datetime = datetime.combine(session_date, run_time, tzinfo=_IST)
            if cross_midnight and run_time < cutoff:
                run_datetime += timedelta(days=1)
        if intended_roster != roster or run_datetime < closes_at:
            continue
        selected.append({"symbol": symbol, "exchange": exchange})
        seen.add(identity)
    return selected


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
    bar_interval: str = Field(default="5m", min_length=1)
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
) -> tuple[bytes, str, FeatureSet, datetime]:
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
        raw_accepted_at = metadata.get("accepted_at")
        if not isinstance(raw_accepted_at, str):
            raise ValueError("Signal model bundle has no accepted timestamp")
        try:
            accepted_at = datetime.fromisoformat(
                raw_accepted_at[:-1] + "+00:00" if raw_accepted_at.endswith(("Z", "z")) else raw_accepted_at
            )
        except ValueError as exc:
            raise ValueError("Signal model bundle has an invalid accepted timestamp") from exc
        if accepted_at.tzinfo is None:
            raise ValueError("Signal model bundle accepted timestamp must include a timezone")
        accepted_at = accepted_at.astimezone(timezone.utc)
        raw_session_date = metadata.get("session_date")
        if raw_session_date is not None:
            if not isinstance(raw_session_date, str):
                raise ValueError("Signal model bundle has an invalid session date")
            try:
                date.fromisoformat(raw_session_date)
            except ValueError as exc:
                raise ValueError("Signal model bundle has an invalid session date") from exc

        model_bytes = bundle.read("model.joblib")
    actual_digest = hashlib.sha256(model_bytes).hexdigest()
    if not hmac.compare_digest(actual_digest, metadata_digest):
        raise RuntimeError(f"Refusing to load {path.name}: SHA-256 checksum mismatch")
    return model_bytes, metadata_digest, baseline, accepted_at


def _bundle_session_date(path: Path, accepted_at: datetime) -> date:
    """Read an explicit session date or infer it for pre-cadence bundles."""
    with zipfile.ZipFile(path) as bundle:
        metadata = json.loads(bundle.read("metadata.json").decode("utf-8"))
    raw_session_date = metadata.get("session_date") if isinstance(metadata, dict) else None
    if raw_session_date is None:
        return accepted_at.astimezone(_IST).date()
    return date.fromisoformat(raw_session_date)


def _write_model_bundle(
    path: Path,
    candidate: SignalGenerator,
    baseline: FeatureSet,
    *,
    symbol: str,
    exchange: str,
    accepted_at: datetime | None = None,
    session_date: date | None = None,
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
        accepted = accepted_at or datetime.now(timezone.utc)
        if accepted.tzinfo is None:
            raise ValueError("accepted_at must include a timezone")
        metadata = {
            "bundle_version": _BUNDLE_VERSION,
            "accepted_at": accepted.astimezone(timezone.utc).isoformat(),
            "identity": {
                "exchange": exchange,
                "symbol": symbol,
                "digest": _instrument_identity_digest(symbol, exchange),
            },
            "model_sha256": actual_digest,
            "baseline": baseline_payload,
        }
        if session_date is not None:
            if isinstance(session_date, datetime) or not isinstance(session_date, date):
                raise ValueError("session_date must be a date")
            metadata["session_date"] = session_date.isoformat()
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
    model_bytes, model_sha256, _baseline, _accepted_at = _read_verified_bundle(
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
        instrument_provider: Callable[[], list[dict[str, str]]] | None = None,
        clock: Clock | None = None,
        cancel_requested: CancellationCheck | None = None,
        market_session_provider: MarketSessionProvider | None = None,
    ) -> None:
        self.config = config
        self.instruments = [dict(instrument) for instrument in instruments]
        self._data_fetcher = data_fetcher
        self._pipeline = pipeline
        self._instrument_provider = instrument_provider
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._cancel_requested = cancel_requested or (lambda: False)
        pipeline_interval = getattr(pipeline, "interval", None)
        self._bar_interval = (
            pipeline_interval
            if isinstance(pipeline_interval, str) and pipeline_interval.strip()
            else config.bar_interval
        )
        pipeline_session_provider = getattr(
            pipeline,
            "market_session_provider",
            None,
        )
        self._market_session_provider = (
            market_session_provider
            if market_session_provider is not None
            else (
                pipeline_session_provider
                if callable(pipeline_session_provider)
                else None
            )
        )
        self._history: deque[RetrainResult] = deque(maxlen=config.max_history)
        self._history_lock = threading.Lock()
        self._promotion_lock = threading.Lock()
        self._live_generators: dict[tuple[str, str], SignalGenerator] = {}
        self.config.model_dir.mkdir(parents=True, exist_ok=True)

    def model_path(self, symbol: str, exchange: str) -> Path:
        """Return the deterministic per-instrument model path."""
        return signal_model_path(self.config.model_dir, symbol, exchange)

    def _now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None:
            raise ValueError("Signal retraining clock must return a timezone-aware datetime")
        return now.astimezone(timezone.utc)

    def _is_cancelled(self) -> bool:
        return bool(self._cancel_requested())

    def _fetch_bars_with_cancellation(
        self,
        symbol: str,
        exchange: str,
    ) -> list[dict[str, Any]] | None:
        """Fetch on a daemon worker and return ``None`` promptly on cancellation."""
        outcomes: Queue[tuple[list[dict[str, Any]] | None, Exception | None]] = Queue(maxsize=1)

        def fetch() -> None:
            try:
                bars = self._data_fetcher(symbol, exchange, self.config.lookback_days)
            except Exception as exc:  # noqa: BLE001 - marshalled back to the retraining thread
                outcomes.put_nowait((None, exc))
            else:
                outcomes.put_nowait((bars, None))

        worker = threading.Thread(
            target=fetch,
            name="flinttrade-signal-data-fetch",
            daemon=True,
        )
        worker.start()
        while worker.is_alive():
            worker.join(timeout=_FETCH_CANCELLATION_POLL_SECONDS)
            if self._is_cancelled():
                return None
        if self._is_cancelled():
            return None

        try:
            bars, error = outcomes.get_nowait()
        except Empty as exc:
            raise RuntimeError("Signal data fetch worker exited without a result") from exc
        if error is not None:
            raise error
        if bars is None:
            raise RuntimeError("Signal data fetcher returned no result")
        return bars

    def run_once(
        self,
        symbol: str,
        exchange: str,
        *,
        session_date: date | None = None,
    ) -> RetrainResult:
        """Fetch, train, validate, and conditionally promote one instrument."""
        if isinstance(session_date, datetime) or (
            session_date is not None and not isinstance(session_date, date)
        ):
            raise ValueError("session_date must be a date")
        started = time.monotonic()
        if self._is_cancelled():
            return self._record_failure(started, symbol, exchange, "Cancelled")

        target = self.model_path(symbol, exchange)
        incumbent_baseline: FeatureSet | None = None
        if target.exists():
            try:
                _model_bytes, _model_sha256, incumbent_baseline, accepted_at = _read_verified_bundle(
                    target,
                    symbol=symbol,
                    exchange=exchange,
                )
            except Exception as exc:  # noqa: BLE001 - corrupt incumbents should be replaced, not trusted
                logger.warning("Could not verify incumbent model for %s:%s: %s", exchange, symbol, exc)
            else:
                accepted_session_date = _bundle_session_date(target, accepted_at)
                age = self._now() - accepted_at
                interval = timedelta(hours=self.config.retrain_interval_hours)
                same_session = (
                    session_date is not None and accepted_session_date == session_date
                )
                within_interval = (
                    session_date is None and timedelta(0) <= age < interval
                )
                if same_session or within_interval:
                    reason = (
                        f"Skipped: model already accepted for session {session_date.isoformat()}"
                        if same_session
                        else (
                            f"Skipped: accepted model is {age.total_seconds() / 3600:.2f}h old; "
                            f"retrain interval is {self.config.retrain_interval_hours}h"
                        )
                    )
                    result = self._result(
                        started,
                        symbol,
                        exchange,
                        train_accuracy=0.0,
                        test_accuracy=0.0,
                        accepted=False,
                        reason=reason,
                        drift_detected=False,
                        drift_score=0.0,
                    )
                    self._record(result)
                    return result

        try:
            bars = self._fetch_bars_with_cancellation(symbol, exchange)
        except Exception as exc:  # noqa: BLE001 - one instrument must not stop the roster
            return self._record_failure(started, symbol, exchange, f"Data fetch failed: {exc}")
        if bars is None:
            return self._record_failure(started, symbol, exchange, "Cancelled")
        if self._is_cancelled():
            return self._record_failure(started, symbol, exchange, "Cancelled")

        bars = _filter_closed_bars(
            _prepare_scheduled_bars(bars),
            interval=self._bar_interval,
            now=self._now(),
            exchange=exchange,
            symbol=symbol,
            market_session_provider=self._market_session_provider,
        )

        if len(bars) < self.config.min_training_rows:
            return self._record_failure(
                started,
                symbol,
                exchange,
                f"Insufficient data: {len(bars)} bars; need at least {self.config.min_training_rows}",
            )

        features = engineer_features(bars)
        if self._is_cancelled():
            return self._record_failure(started, symbol, exchange, "Cancelled")
        if not features.values:
            return self._record_failure(started, symbol, exchange, f"Insufficient data: {len(bars)} bars")

        drift_detected = False
        drift_score = 0.0
        if incumbent_baseline is not None:
            split = int(len(features.values) * (1 - self.config.validation_split))
            recent = FeatureSet(names=features.names, values=features.values[split:])
            drift_detected, drift_score = compute_feature_drift(
                incumbent_baseline,
                recent,
                threshold=self.config.drift_threshold,
            )
        if self._is_cancelled():
            return self._record_failure(
                started,
                symbol,
                exchange,
                "Cancelled",
                drift_detected=drift_detected,
                drift_score=drift_score,
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
                cancel_requested=self._cancel_requested,
            )
        except TrainingCancelled:
            return self._record_failure(
                started,
                symbol,
                exchange,
                "Cancelled",
                drift_detected=drift_detected,
                drift_score=drift_score,
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
        if self._is_cancelled():
            return self._record_failure(
                started,
                symbol,
                exchange,
                "Cancelled",
                drift_detected=drift_detected,
                drift_score=drift_score,
            )

        try:
            labels = generate_labels(
                [float(bar["close"]) for bar in bars],
                lookahead=self.config.lookahead,
                buy_threshold_pct=self.config.buy_threshold_pct,
                sell_threshold_pct=self.config.sell_threshold_pct,
            )
            sample_count = min(len(features.values), len(labels))
            training_end, _validation_start = walk_forward_split_bounds(
                sample_count,
                test_ratio=self.config.validation_split,
                lookahead=self.config.lookahead,
            )
        except (KeyError, TypeError, ValueError) as exc:
            return self._record_failure(
                started,
                symbol,
                exchange,
                f"Training baseline failed: {exc}",
                drift_detected=drift_detected,
                drift_score=drift_score,
            )
        training_baseline = FeatureSet(
            names=list(features.names),
            values=[list(row) for row in features.values[:training_end]],
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
            self._promote(
                symbol,
                exchange,
                candidate,
                training_baseline,
                session_date=session_date,
            )
        except TrainingCancelled:
            return self._record_failure(
                started,
                symbol,
                exchange,
                "Cancelled",
                train_accuracy=train_accuracy,
                test_accuracy=test_accuracy,
                drift_detected=drift_detected,
                drift_score=drift_score,
            )
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

    def run_all(
        self,
        *,
        instruments: list[dict[str, str]] | None = None,
        session_date: date | None = None,
    ) -> list[RetrainResult]:
        """Retrain every pipeline instrument, continuing after any failure."""
        results: list[RetrainResult] = []
        if self._is_cancelled():
            return results
        selected_instruments = (
            [dict(instrument) for instrument in instruments]
            if instruments is not None
            else (
                self._instrument_provider()
                if self._instrument_provider is not None
                else [dict(instrument) for instrument in self.instruments]
            )
        )
        for instrument in selected_instruments:
            if self._is_cancelled():
                break
            symbol = str(instrument.get("symbol", ""))
            exchange = str(instrument.get("exchange", ""))
            try:
                if session_date is None:
                    result = self.run_once(symbol, exchange)
                else:
                    result = self.run_once(
                        symbol,
                        exchange,
                        session_date=session_date,
                    )
            except Exception as exc:  # pragma: no cover - final containment guard
                result = self._record_failure(
                    time.monotonic(),
                    symbol,
                    exchange,
                    f"Retrain failed: {exc}",
                )
            results.append(result)
            if result.reason == "Cancelled" or self._is_cancelled():
                break
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
        *,
        session_date: date | None = None,
    ) -> None:
        target = self.model_path(symbol, exchange)
        target.parent.mkdir(parents=True, exist_ok=True)

        with self._promotion_lock:
            temp_bundle = _temporary_path(target, "candidate")
            try:
                bundle_kwargs: dict[str, Any] = {
                    "symbol": symbol,
                    "exchange": exchange,
                    "accepted_at": self._now(),
                }
                if session_date is not None:
                    bundle_kwargs["session_date"] = session_date
                _write_model_bundle(
                    temp_bundle,
                    candidate,
                    training_baseline,
                    **bundle_kwargs,
                )
                if self._is_cancelled():
                    raise TrainingCancelled("Signal model promotion cancelled")

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
            timestamp=self._now(),
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
