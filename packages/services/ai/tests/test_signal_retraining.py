"""Task 2 contracts for canonical signal retraining."""

from __future__ import annotations

import json
import threading
import zipfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest


class _PredictableModel:
    """Picklable model placeholder used by guarded persistence tests."""

    def predict(self, rows: list[list[float]]) -> list[list[float]]:
        return [[0.1, 0.2, 0.7] for _ in rows]


class _SellModel:
    """Picklable model that emits a high-confidence SELL prediction."""

    def predict(self, rows: list[list[float]]) -> list[list[float]]:
        return [[0.8, 0.1, 0.1] for _ in rows]


def _full_day_session(
    _exchange: str,
    _symbol: str,
    _on: date,
) -> tuple[time, time]:
    """Deterministic effective session for tests unrelated to calendars."""
    return time(0, 0), time(23, 59)


class _RecordingPipeline:
    def __init__(self) -> None:
        self.installed: list[tuple[str, str, Any]] = []
        self.model_was_persisted = False
        self.interval = "5m"
        self.market_session_provider = _full_day_session

    def install_generator(self, symbol: str, exchange: str, generator: Any) -> None:
        self.installed.append((symbol, exchange, generator))

    def publish_generator(
        self,
        symbol: str,
        exchange: str,
        generator: Any,
        publish: Any,
    ) -> None:
        publish()
        self.install_generator(symbol, exchange, generator)


def _bars(
    count: int = 80,
    *,
    price_shift: float = 0.0,
    end_at: datetime | None = None,
) -> list[dict[str, float | str]]:
    final_stamp = (end_at or datetime.now(timezone.utc)) - timedelta(minutes=5)
    first_stamp = final_stamp - timedelta(minutes=5 * (count - 1))
    return [
        {
            "timestamp": (first_stamp + timedelta(minutes=5 * index)).isoformat(),
            "open": 100.0 + price_shift + index * 0.7,
            "high": 102.0 + price_shift + index * 0.8,
            "low": 99.0 + price_shift + index * 0.6,
            "close": 101.0 + price_shift + index * 0.75,
            "volume": 10_000.0 + index * 125,
        }
        for index in range(count)
    ]


def _distribution_shifted_bars(
    count: int = 120,
    *,
    end_at: datetime | None = None,
) -> list[dict[str, float | str]]:
    final_stamp = (end_at or datetime.now(timezone.utc)) - timedelta(minutes=5)
    first_stamp = final_stamp - timedelta(minutes=5 * (count - 1))
    rows: list[dict[str, float | str]] = []
    for index in range(count):
        close = 100.0 if index % 2 == 0 else 1000.0
        open_price = close * (1.3 if index % 3 == 0 else 0.7)
        rows.append(
            {
                "timestamp": (first_stamp + timedelta(minutes=5 * index)).isoformat(),
                "open": open_price,
                "high": max(open_price, close) * 1.5,
                "low": min(open_price, close) * 0.5,
                "close": close,
                "volume": 10_000_000.0 if index % 2 == 0 else 100.0,
            }
        )
    return rows


def _install_train_stub(monkeypatch: pytest.MonkeyPatch, *, test_accuracy: float = 0.75) -> list[dict[str, Any]]:
    from flinttrade_ai.signals import SignalGenerator, engineer_features

    calls: list[dict[str, Any]] = []

    def _train(self: SignalGenerator, bars: list[dict[str, Any]], **kwargs: Any) -> dict[str, float]:
        calls.append({"generator": self, "bars": bars, **kwargs})
        self._model = _PredictableModel()
        self._feature_names = engineer_features(bars).names
        return {"train_accuracy": 0.9, "test_accuracy": test_accuracy}

    monkeypatch.setattr(SignalGenerator, "train", _train)
    return calls


def _config(tmp_path: Path, **overrides: Any):
    from flinttrade_ai.signal_retraining import RetrainConfig

    values = {"model_dir": tmp_path, "min_accuracy": 0.55, "min_training_rows": 30, **overrides}
    return RetrainConfig(**values)


def _save_generator(path: Path, model: Any) -> Any:
    from flinttrade_ai.signals import SignalGenerator, engineer_features

    generator = SignalGenerator()
    generator._model = model
    generator._feature_names = engineer_features(_bars()).names
    generator.save(str(path))
    return generator


def _save_bundle(
    path: Path,
    model: Any,
    *,
    symbol: str,
    exchange: str,
    accepted_at: datetime | None = None,
    session_date: date | None = None,
) -> Any:
    from flinttrade_ai.signal_retraining import _write_model_bundle
    from flinttrade_ai.signals import FeatureSet, SignalGenerator, engineer_features

    generator = SignalGenerator()
    generator._model = model
    features = engineer_features(_bars(120))
    generator._feature_names = features.names
    split = int(len(features.values) * 0.8)
    baseline = FeatureSet(names=features.names, values=features.values[:split])
    bundle_kwargs: dict[str, Any] = {
        "symbol": symbol,
        "exchange": exchange,
        "accepted_at": accepted_at or datetime(2000, 1, 1, tzinfo=timezone.utc),
    }
    if session_date is not None:
        bundle_kwargs["session_date"] = session_date
    _write_model_bundle(path, generator, baseline, **bundle_kwargs)
    return generator


def test_retrain_config_preserves_reviewed_defaults() -> None:
    from flinttrade_ai.signal_retraining import RetrainConfig

    config = RetrainConfig()

    assert config.retrain_interval_hours == 24
    assert config.min_accuracy == 0.55
    assert config.min_training_rows == 100
    assert config.lookback_days == 365
    assert config.lookahead == 5
    assert config.buy_threshold_pct == 0.5
    assert config.sell_threshold_pct == -0.5
    assert config.validation_split == 0.2
    assert config.drift_threshold == 0.1
    assert config.persist_log is True
    assert config.max_history == 1000


def test_parent_retry_contract_is_exported_from_ai_package() -> None:
    from flinttrade_ai import (
        RetrainingRetry,
        RetrainingRosterPlan,
        plan_retraining_roster,
    )

    assert RetrainingRetry is not None
    assert RetrainingRosterPlan is not None
    assert callable(plan_retraining_roster)


def test_run_once_skips_bundle_newer_than_retrain_interval(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    from flinttrade_ai.signal_retraining import SignalRetrainer

    now = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
    fetcher = MagicMock(return_value=_bars())
    retrainer = SignalRetrainer(
        _config(tmp_path, retrain_interval_hours=168),
        instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}],
        data_fetcher=fetcher,
        clock=lambda: now,
    )
    _save_bundle(
        retrainer.model_path("NIFTY", "NSE_INDEX"),
        _PredictableModel(),
        symbol="NIFTY",
        exchange="NSE_INDEX",
        accepted_at=now - timedelta(hours=167),
    )

    result = retrainer.run_once("NIFTY", "NSE_INDEX")

    assert result.accepted is False
    assert result.reason.startswith("Skipped:")
    assert "168" in result.reason
    fetcher.assert_not_called()


def test_same_session_date_skips_even_after_hour_interval_elapsed(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    from flinttrade_ai.signal_retraining import SignalRetrainer

    now = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
    target_session = date(2026, 7, 11)
    fetcher = MagicMock(return_value=_bars())
    retrainer = SignalRetrainer(
        _config(tmp_path, retrain_interval_hours=1),
        instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}],
        data_fetcher=fetcher,
        clock=lambda: now,
    )
    _save_bundle(
        retrainer.model_path("NIFTY", "NSE_INDEX"),
        _PredictableModel(),
        symbol="NIFTY",
        exchange="NSE_INDEX",
        accepted_at=now - timedelta(hours=2),
        session_date=target_session,
    )

    result = retrainer.run_once(
        "NIFTY",
        "NSE_INDEX",
        session_date=target_session,
    )

    assert result.accepted is False
    assert result.reason == "Skipped: model already accepted for session 2026-07-11"
    fetcher.assert_not_called()


def test_next_session_date_retrains_even_within_elapsed_interval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock

    from flinttrade_ai.signal_retraining import SignalRetrainer

    _install_train_stub(monkeypatch, test_accuracy=0.8)
    now = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)
    fetcher = MagicMock(return_value=_bars(120, end_at=now))
    retrainer = SignalRetrainer(
        _config(tmp_path, retrain_interval_hours=24),
        instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}],
        data_fetcher=fetcher,
        pipeline=_RecordingPipeline(),
        clock=lambda: now,
    )
    _save_bundle(
        retrainer.model_path("NIFTY", "NSE_INDEX"),
        _PredictableModel(),
        symbol="NIFTY",
        exchange="NSE_INDEX",
        accepted_at=now - timedelta(hours=23),
        session_date=date(2026, 7, 10),
    )

    result = retrainer.run_once(
        "NIFTY",
        "NSE_INDEX",
        session_date=date(2026, 7, 11),
    )

    assert result.accepted is True
    fetcher.assert_called_once()


def test_run_all_cancels_before_training_and_stops_roster(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock

    from flinttrade_ai.signal_retraining import SignalRetrainer
    from flinttrade_ai.signals import SignalGenerator

    cancelled = False

    def fetcher(*_args: Any) -> list[dict[str, float | str]]:
        nonlocal cancelled
        cancelled = True
        return _bars()

    train = MagicMock()
    monkeypatch.setattr(SignalGenerator, "train", train)
    retrainer = SignalRetrainer(
        _config(tmp_path),
        instruments=[
            {"symbol": "NIFTY", "exchange": "NSE_INDEX"},
            {"symbol": "BANKNIFTY", "exchange": "NSE_INDEX"},
        ],
        data_fetcher=fetcher,
        cancel_requested=lambda: cancelled,
    )

    results = retrainer.run_all()

    assert len(results) == 1
    assert results[0].reason == "Cancelled"
    train.assert_not_called()


def test_run_once_reports_pending_cancellation_until_single_fetch_owner_stops(tmp_path: Path) -> None:
    from flinttrade_ai.signal_retraining import SignalRetrainer

    fetch_started = threading.Event()
    release_fetch = threading.Event()
    cancel_requested = threading.Event()
    fetch_workers: list[threading.Thread] = []
    results: list[Any] = []

    def stalled_fetch(*_args: Any) -> list[dict[str, float | str]]:
        fetch_workers.append(threading.current_thread())
        fetch_started.set()
        release_fetch.wait(timeout=5.0)
        return _bars()

    retrainer = SignalRetrainer(
        _config(tmp_path, persist_log=False),
        instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}],
        data_fetcher=stalled_fetch,
        cancel_requested=cancel_requested.is_set,
    )
    runner = threading.Thread(
        target=lambda: results.append(retrainer.run_once("NIFTY", "NSE_INDEX")),
    )
    runner.start()
    assert fetch_started.wait(timeout=1.0)

    try:
        cancel_requested.set()
        runner.join(timeout=0.5)

        assert not runner.is_alive()
        assert results[0].completed is False
        assert results[0].reason == "Cancellation pending: data fetch still running"
        assert retrainer.has_active_fetch_owner is True
        assert fetch_workers[0].daemon is True
        assert fetch_workers[0].is_alive()

        second = retrainer.run_once("BANKNIFTY", "NSE_INDEX")
        assert second.completed is False
        assert "NSE_INDEX:NIFTY" in second.reason
        assert len(fetch_workers) == 1

        batch = retrainer.run_all()
        assert len(batch) == 1
        assert batch[0].completed is False
        assert "NSE_INDEX:NIFTY" in batch[0].reason
        assert len(fetch_workers) == 1
    finally:
        release_fetch.set()
        runner.join(timeout=1.0)
        assert retrainer.wait_for_fetch_owner(timeout=1.0) is True

    completed = retrainer.run_once("NIFTY", "NSE_INDEX")
    assert completed.completed is True
    assert completed.reason == "Cancelled"
    assert retrainer.has_active_fetch_owner is False


def test_feature_drift_uses_mean_score_and_has_deterministic_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import flinttrade_ai.signal_retraining as retraining
    from flinttrade_ai.signals import FeatureSet

    monkeypatch.setattr(retraining, "_scipy_ks_2samp", None)
    reference = FeatureSet(names=["stable", "shifted"], values=[[1.0, float(i)] for i in range(10)])
    current = FeatureSet(names=["stable", "shifted"], values=[[1.0, 100.0 + i] for i in range(10)])

    detected, score = retraining.compute_feature_drift(reference, current, threshold=0.1)

    assert detected is True
    assert score == pytest.approx(0.5)


def test_feature_drift_uses_scipy_statistic_and_threshold_equality_is_not_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import flinttrade_ai.signal_retraining as retraining
    from flinttrade_ai.signals import FeatureSet

    ks_2samp = MagicMock(return_value=SimpleNamespace(statistic=0.25))
    monkeypatch.setattr(retraining, "_scipy_ks_2samp", ks_2samp)
    reference = FeatureSet(names=["feature"], values=[[float(index)] for index in range(5)])
    current = FeatureSet(names=["feature"], values=[[float(index + 10)] for index in range(5)])

    detected, score = retraining.compute_feature_drift(reference, current, threshold=0.25)

    assert detected is False
    assert score == pytest.approx(0.25)
    ks_2samp.assert_called_once_with(
        [0.0, 1.0, 2.0, 3.0, 4.0],
        [10.0, 11.0, 12.0, 13.0, 14.0],
    )


@pytest.mark.parametrize(
    ("reference", "current"),
    [
        (None, None),
        ([], []),
    ],
)
def test_feature_drift_returns_no_drift_for_empty_or_missing_features(reference: Any, current: Any) -> None:
    from flinttrade_ai.signal_retraining import compute_feature_drift
    from flinttrade_ai.signals import FeatureSet

    reference_set = FeatureSet() if reference is not None else None
    current_set = FeatureSet() if current is not None else None

    assert compute_feature_drift(reference_set, current_set, threshold=0.1) == (False, 0.0)


def test_accepted_candidate_uses_canonical_train_metrics_and_promotes_per_instrument(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_ai.signal_retraining import SignalRetrainer
    from flinttrade_ai.signals import SignalGenerator

    train_calls = _install_train_stub(monkeypatch, test_accuracy=0.75)
    fetch_calls: list[tuple[str, str, int]] = []
    pipeline = _RecordingPipeline()

    def _fetch(symbol: str, exchange: str, lookback_days: int) -> list[dict[str, Any]]:
        fetch_calls.append((symbol, exchange, lookback_days))
        return _bars()

    retrainer = SignalRetrainer(
        _config(tmp_path),
        instruments=[{"symbol": "NIFTY/50", "exchange": "NSE INDEX"}],
        data_fetcher=_fetch,
        pipeline=pipeline,
    )

    result = retrainer.run_once("NIFTY/50", "NSE INDEX")

    assert result.accepted is True
    assert result.train_accuracy == pytest.approx(0.9)
    assert result.test_accuracy == pytest.approx(0.75)
    assert fetch_calls == [("NIFTY/50", "NSE INDEX", 365)]
    assert train_calls[0]["test_ratio"] == pytest.approx(0.2)
    assert len(pipeline.installed) == 1
    assert isinstance(pipeline.installed[0][2], SignalGenerator)

    model_path = retrainer.model_path("NIFTY/50", "NSE INDEX")
    assert model_path.parent == tmp_path
    assert model_path.name.startswith("signal_model_")
    assert model_path.suffix == ".bundle"
    assert "/" not in model_path.name
    assert " " not in model_path.name
    assert model_path.exists()
    assert not Path(f"{model_path}.sha256").exists()
    assert not list(tmp_path.glob("*.tmp*"))

    with zipfile.ZipFile(model_path) as bundle:
        metadata = json.loads(bundle.read("metadata.json"))
        model_bytes = bundle.read("model.joblib")
        checksum = bundle.read("model.sha256").decode("ascii")
    assert metadata["bundle_version"] == 1
    assert metadata["identity"]["exchange"] == "NSE INDEX"
    assert metadata["identity"]["symbol"] == "NIFTY/50"
    assert metadata["baseline"]["version"] == 1
    assert metadata["baseline"]["model_sha256"] == checksum
    assert metadata["model_sha256"] == checksum
    from flinttrade_ai.signals import engineer_features

    expected_features = engineer_features(train_calls[0]["bars"])
    labelled_rows = len(expected_features.values) - retrainer.config.lookahead
    validation_start = int(labelled_rows * 0.8)
    expected_split = validation_start - retrainer.config.lookahead
    assert metadata["baseline"]["feature_names"] == expected_features.names
    assert metadata["baseline"]["values"] == expected_features.values[:expected_split]
    assert model_bytes


def test_retraining_trains_on_sorted_unique_closed_bars_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_ai.signal_retraining import SignalRetrainer

    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime(2026, 7, 10, 13, 0, tzinfo=ist)
    first_stamp = now - timedelta(minutes=5 * 40)
    closed_bars = [
        {
            "timestamp": (first_stamp + timedelta(minutes=5 * index)).isoformat(),
            "open": 100.0 + index,
            "high": 102.0 + index,
            "low": 99.0 + index,
            "close": 101.0 + index,
            "volume": 10_000.0 + index,
        }
        for index in range(40)
    ]
    duplicate = {**closed_bars[12], "close": 999.0}
    forming = {**closed_bars[-1], "timestamp": (now - timedelta(minutes=2)).isoformat()}
    future = {**closed_bars[-1], "timestamp": (now + timedelta(minutes=5)).isoformat()}
    source_bars = [future, forming, *reversed(closed_bars), duplicate]
    train_calls = _install_train_stub(monkeypatch, test_accuracy=0.8)
    retrainer = SignalRetrainer(
        _config(tmp_path),
        instruments=[],
        data_fetcher=lambda *_args: source_bars,
        clock=lambda: now,
        market_session_provider=lambda _exchange, _symbol, _on: (
            time(9, 15),
            time(15, 30),
        ),
    )

    result = retrainer.run_once("NIFTY", "NSE_INDEX")

    trained_bars = train_calls[0]["bars"]
    trained_timestamps = [datetime.fromisoformat(str(bar["timestamp"])) for bar in trained_bars]
    assert result.accepted is True
    assert len(trained_bars) == 40
    assert trained_timestamps == sorted(set(trained_timestamps))
    assert all(timestamp + timedelta(minutes=5) <= now for timestamp in trained_timestamps)


def test_retraining_compares_recent_features_with_verified_incumbent_training_baseline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_ai.signal_retraining as retraining

    monkeypatch.setattr(retraining, "_scipy_ks_2samp", None)
    _install_train_stub(monkeypatch, test_accuracy=0.8)
    now = [datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)]
    fetched = iter(
        [
            _bars(120, end_at=now[0]),
            _distribution_shifted_bars(end_at=now[0] + timedelta(hours=24)),
        ]
    )
    retrainer = retraining.SignalRetrainer(
        _config(tmp_path, drift_threshold=0.3),
        instruments=[],
        data_fetcher=lambda *_args: next(fetched),
        clock=lambda: now[0],
        market_session_provider=_full_day_session,
    )

    first = retrainer.run_once("NIFTY", "NSE_INDEX")
    now[0] += timedelta(hours=24)
    second = retrainer.run_once("NIFTY", "NSE_INDEX")

    assert first.accepted is True
    assert first.drift_detected is False
    assert second.accepted is True
    assert second.drift_detected is True
    assert second.drift_score > 0.3


@pytest.mark.parametrize("baseline_value", [None, {"version": 1, "model_sha256": "not-a-digest"}])
def test_missing_or_corrupt_incumbent_baseline_reports_no_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    baseline_value: Any,
) -> None:
    import flinttrade_ai.signal_retraining as retraining

    monkeypatch.setattr(retraining, "_scipy_ks_2samp", None)
    _install_train_stub(monkeypatch, test_accuracy=0.8)
    retrainer = retraining.SignalRetrainer(
        _config(tmp_path),
        instruments=[],
        data_fetcher=lambda *_args: _bars(120),
        market_session_provider=_full_day_session,
    )
    assert retrainer.run_once("NIFTY", "NSE_INDEX").accepted is True
    target = retrainer.model_path("NIFTY", "NSE_INDEX")

    with zipfile.ZipFile(target) as source:
        model_bytes = source.read("model.joblib")
        checksum = source.read("model.sha256")
        metadata = json.loads(source.read("metadata.json"))
    if baseline_value is None:
        metadata.pop("baseline")
    else:
        metadata["baseline"] = baseline_value
    with zipfile.ZipFile(target, "w") as corrupted:
        corrupted.writestr("model.joblib", model_bytes)
        corrupted.writestr("model.sha256", checksum)
        corrupted.writestr("metadata.json", json.dumps(metadata))

    retrainer._data_fetcher = lambda *_args: _distribution_shifted_bars()
    result = retrainer.run_once("NIFTY", "NSE_INDEX")

    assert result.accepted is True
    assert result.drift_detected is False
    assert result.drift_score == 0.0


@pytest.mark.parametrize("corruption", ["baseline", "model"])
def test_bundle_integrity_and_baseline_are_verified_before_joblib_deserialisation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
) -> None:
    from unittest.mock import MagicMock

    import joblib

    from flinttrade_ai.signal_retraining import load_signal_model_bundle, signal_model_path

    target = signal_model_path(tmp_path, "NIFTY", "NSE_INDEX")
    _save_bundle(target, _PredictableModel(), symbol="NIFTY", exchange="NSE_INDEX")
    with zipfile.ZipFile(target) as source:
        model_bytes = source.read("model.joblib")
        checksum = source.read("model.sha256")
        metadata = json.loads(source.read("metadata.json"))
    if corruption == "baseline":
        metadata["baseline"]["values"] = [[float("nan")]]
    else:
        model_bytes += b"tampered"
    with zipfile.ZipFile(target, "w") as corrupted:
        corrupted.writestr("model.joblib", model_bytes)
        corrupted.writestr("model.sha256", checksum)
        corrupted.writestr("metadata.json", json.dumps(metadata))
    loader = MagicMock()
    monkeypatch.setattr(joblib, "load", loader)

    with pytest.raises((RuntimeError, ValueError)):
        load_signal_model_bundle(target, symbol="NIFTY", exchange="NSE_INDEX")

    loader.assert_not_called()


def test_rejected_candidate_changes_neither_disk_nor_live_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_ai.signal_retraining import SignalRetrainer

    _install_train_stub(monkeypatch, test_accuracy=0.54)
    pipeline = _RecordingPipeline()
    retrainer = SignalRetrainer(
        _config(tmp_path),
        instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}],
        data_fetcher=lambda *_args: _bars(),
        pipeline=pipeline,
    )

    result = retrainer.run_once("NIFTY", "NSE_INDEX")

    assert result.accepted is False
    assert "Rejected" in result.reason
    assert not retrainer.model_path("NIFTY", "NSE_INDEX").exists()
    assert pipeline.installed == []


def test_interrupted_candidate_write_preserves_atomic_bundle_and_restart_loads_old_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock

    import flinttrade_ai.signal_retraining as retraining
    from flinttrade_ai.pipeline import SignalPipeline

    _install_train_stub(monkeypatch, test_accuracy=0.8)
    retrainer = retraining.SignalRetrainer(
        _config(tmp_path),
        instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}],
        data_fetcher=lambda *_args: _bars(),
        market_session_provider=_full_day_session,
    )
    target = retrainer.model_path("NIFTY", "NSE_INDEX")
    _save_bundle(target, _SellModel(), symbol="NIFTY", exchange="NSE_INDEX")
    old_bundle = target.read_bytes()

    def _interrupted_write(path: Path, *_args: Any, **_kwargs: Any) -> None:
        path.write_bytes(b"partial-candidate-bundle")
        raise OSError("interrupted before publication")

    monkeypatch.setattr(retraining, "_write_model_bundle", _interrupted_write)

    result = retrainer.run_once("NIFTY", "NSE_INDEX")

    assert result.accepted is False
    assert "Persistence failed" in result.reason
    assert target.read_bytes() == old_bundle
    assert not list(tmp_path.glob("*.tmp*"))

    restarted = SignalPipeline(
        model_path=str(tmp_path / "missing-shared.joblib"),
        instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}],
        market_session_provider=_full_day_session,
    )
    restarted.fetch_bars = MagicMock(return_value=_bars())
    assert restarted.run_cycle()["NSE_INDEX:NIFTY"]["signal"] == "SELL"


def test_filesystem_safe_model_paths_include_pair_digest_and_avoid_all_reviewed_collisions(tmp_path: Path) -> None:
    import re

    from flinttrade_ai.signal_retraining import signal_model_path

    escaped = signal_model_path(tmp_path, "NIFTY/50", "NSE INDEX")
    literal = signal_model_path(tmp_path, "NIFTY_50", "NSE_INDEX")
    joined_left = signal_model_path(tmp_path, "NIFTY", "NSE_INDEX")
    joined_right = signal_model_path(tmp_path, "INDEX_NIFTY", "NSE")
    colon_left = signal_model_path(tmp_path, "NIFTY", "NSE:INDEX")
    colon_right = signal_model_path(tmp_path, "INDEX:NIFTY", "NSE")

    assert escaped != literal
    assert joined_left != joined_right
    assert colon_left != colon_right
    assert all(
        re.search(r"_[0-9a-f]{64}\.bundle$", path.name)
        for path in (escaped, literal, joined_left, joined_right, colon_left, colon_right)
    )


def test_retrainer_forwards_asymmetric_label_policy_to_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_ai.signal_retraining import SignalRetrainer

    train_calls = _install_train_stub(monkeypatch)
    retrainer = SignalRetrainer(
        _config(
            tmp_path,
            lookahead=9,
            buy_threshold_pct=0.8,
            sell_threshold_pct=-0.3,
        ),
        instruments=[],
        data_fetcher=lambda *_args: _bars(),
        market_session_provider=_full_day_session,
    )

    result = retrainer.run_once("NIFTY", "NSE_INDEX")

    assert result.accepted is True
    assert train_calls[0]["lookahead"] == 9
    assert train_calls[0]["buy_threshold_pct"] == pytest.approx(0.8)
    assert train_calls[0]["sell_threshold_pct"] == pytest.approx(-0.3)


def test_concurrent_uncached_reader_sees_old_until_atomic_publication_then_new(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_ai.signal_retraining as retraining
    from flinttrade_ai.pipeline import SignalPipeline
    from flinttrade_ai.signals import SignalGenerator, engineer_features

    target = retraining.signal_model_path(tmp_path, "NIFTY", "NSE_INDEX")
    old = _save_bundle(target, _PredictableModel(), symbol="NIFTY", exchange="NSE_INDEX")
    pipeline = SignalPipeline(
        model_path=str(tmp_path / "missing-shared.joblib"),
        instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}],
        market_session_provider=_full_day_session,
    )

    def _train(self: SignalGenerator, bars: list[dict[str, Any]], **_kwargs: Any) -> dict[str, float]:
        self._model = _SellModel()
        self._feature_names = engineer_features(bars).names
        return {"train_accuracy": 0.9, "test_accuracy": 0.8}

    monkeypatch.setattr(SignalGenerator, "train", _train)
    retrainer = retraining.SignalRetrainer(
        _config(tmp_path),
        instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}],
        data_fetcher=lambda *_args: _bars(),
        pipeline=pipeline,
    )
    candidate_ready = threading.Event()
    allow_publication = threading.Event()
    replace_started = threading.Event()
    allow_replace = threading.Event()
    reader_started = threading.Event()
    reader_finished = threading.Event()
    real_write = retraining._write_model_bundle
    real_replace = Path.replace

    def _paused_write(path: Path, *args: Any, **kwargs: Any) -> None:
        real_write(path, *args, **kwargs)
        candidate_ready.set()
        assert allow_publication.wait(timeout=5)

    def _paused_replace(source: Path, destination: Path) -> Path:
        if Path(destination) == target:
            replace_started.set()
            assert allow_replace.wait(timeout=5)
        return real_replace(source, destination)

    monkeypatch.setattr(retraining, "_write_model_bundle", _paused_write)
    monkeypatch.setattr(Path, "replace", _paused_replace)
    retrain_results: list[Any] = []
    publisher = threading.Thread(
        target=lambda: retrain_results.append(retrainer.run_once("NIFTY", "NSE_INDEX")),
    )
    publisher.start()
    assert candidate_ready.wait(timeout=5)

    during_build = retraining.load_signal_model_bundle(
        target,
        symbol="NIFTY",
        exchange="NSE_INDEX",
    )
    assert during_build._model.__class__ is old._model.__class__
    assert pipeline._symbol_generators == {}

    allow_publication.set()
    assert replace_started.wait(timeout=5)
    reader_results: list[Any] = []

    def _read_during_publication() -> None:
        reader_started.set()
        reader_results.append(pipeline._generator_for("NIFTY", "NSE_INDEX"))
        reader_finished.set()

    reader = threading.Thread(target=_read_during_publication)
    reader.start()
    assert reader_started.wait(timeout=5)
    assert not reader_finished.wait(timeout=0.1)

    allow_replace.set()
    publisher.join(timeout=5)
    reader.join(timeout=5)

    assert not publisher.is_alive()
    assert not reader.is_alive()
    assert retrain_results[0].accepted is True
    assert reader_results[0]._model.__class__ is _SellModel
    assert pipeline._generator_for("NIFTY", "NSE_INDEX") is reader_results[0]
    assert not list(tmp_path.glob("*.tmp*"))


def test_run_all_records_one_result_per_instrument_and_continues_after_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_ai.signal_retraining import SignalRetrainer

    train_calls = _install_train_stub(monkeypatch, test_accuracy=0.8)

    def _fetch(symbol: str, _exchange: str, _lookback_days: int) -> list[dict[str, Any]]:
        if symbol == "BROKEN":
            raise RuntimeError("history unavailable")
        return _bars()

    retrainer = SignalRetrainer(
        _config(tmp_path),
        instruments=[
            {"symbol": "BROKEN", "exchange": "NSE"},
            {"symbol": "NIFTY", "exchange": "NSE_INDEX"},
        ],
        data_fetcher=_fetch,
        pipeline=_RecordingPipeline(),
    )

    results = retrainer.run_all()

    assert [(result.symbol, result.exchange) for result in results] == [
        ("BROKEN", "NSE"),
        ("NIFTY", "NSE_INDEX"),
    ]
    assert results[0].accepted is False
    assert "Data fetch failed" in results[0].reason
    assert results[1].accepted is True
    assert len(train_calls) == 1


def test_history_is_bounded_newest_first_and_jsonl_is_append_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_ai.signal_retraining import SignalRetrainer

    _install_train_stub(monkeypatch, test_accuracy=0.5)
    retrainer = SignalRetrainer(
        _config(tmp_path, max_history=2),
        instruments=[],
        data_fetcher=lambda *_args: _bars(),
        market_session_provider=_full_day_session,
    )

    retrainer.run_once("FIRST", "NSE")
    retrainer.run_once("SECOND", "NSE")
    retrainer.run_once("THIRD", "NSE")

    assert [result.symbol for result in retrainer.get_history()] == ["THIRD", "SECOND"]
    log_lines = (tmp_path / "signal_retrain_log.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["symbol"] for line in log_lines] == ["FIRST", "SECOND", "THIRD"]


def test_log_write_error_is_warning_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from flinttrade_ai.signal_retraining import SignalRetrainer

    _install_train_stub(monkeypatch, test_accuracy=0.5)
    retrainer = SignalRetrainer(
        _config(tmp_path),
        instruments=[],
        data_fetcher=lambda *_args: _bars(),
        market_session_provider=_full_day_session,
    )
    monkeypatch.setattr(retrainer, "_append_log", lambda _result: (_ for _ in ()).throw(OSError("read-only")))

    result = retrainer.run_once("NIFTY", "NSE_INDEX")

    assert result.accepted is False
    assert retrainer.get_history() == [result]
    assert "Could not write signal retrain log" in caplog.text


def test_pipeline_fetch_bars_honours_requested_lookback_window() -> None:
    from datetime import date
    from unittest.mock import AsyncMock, MagicMock

    from flinttrade_ai.pipeline import SignalPipeline

    client = MagicMock()
    client.history = AsyncMock(return_value=[])
    client.close = AsyncMock()
    pipeline = SignalPipeline(openalgo_client=client)

    pipeline.fetch_bars("NIFTY", "NSE_INDEX", 365)

    request = client.history.await_args.kwargs
    start = date.fromisoformat(request["start_date"])
    end = date.fromisoformat(request["end_date"])
    assert (end - start).days == 365


def test_pipeline_prefers_verified_per_instrument_model_then_verified_shared_model(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    from flinttrade_ai.pipeline import SignalPipeline
    from flinttrade_ai.signal_retraining import SignalRetrainer

    shared_path = tmp_path / "signal_model.joblib"
    _save_generator(shared_path, _PredictableModel())
    roster = [
        {"symbol": "NIFTY", "exchange": "NSE_INDEX"},
        {"symbol": "BANKNIFTY", "exchange": "NSE_INDEX"},
    ]
    retrainer = SignalRetrainer(
        _config(tmp_path),
        instruments=roster,
        data_fetcher=lambda *_args: _bars(),
    )
    _save_bundle(
        retrainer.model_path("NIFTY", "NSE_INDEX"),
        _SellModel(),
        symbol="NIFTY",
        exchange="NSE_INDEX",
    )
    pipeline = SignalPipeline(
        model_path=str(shared_path),
        instruments=roster,
        market_session_provider=_full_day_session,
    )
    pipeline.fetch_bars = MagicMock(return_value=_bars())

    results = pipeline.run_cycle()

    assert results["NSE_INDEX:NIFTY"]["signal"] == "SELL"
    assert results["NSE_INDEX:BANKNIFTY"]["signal"] == "BUY"
    assert results["NSE_INDEX:NIFTY"]["method"] == "ml_model"
    assert results["NSE_INDEX:BANKNIFTY"]["method"] == "ml_model"


def test_pipeline_rejects_corrupt_per_instrument_model_and_uses_verified_shared_model(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    from flinttrade_ai.pipeline import SignalPipeline
    from flinttrade_ai.signal_retraining import SignalRetrainer

    shared_path = tmp_path / "signal_model.joblib"
    _save_generator(shared_path, _PredictableModel())
    roster = [{"symbol": "NIFTY", "exchange": "NSE_INDEX"}]
    retrainer = SignalRetrainer(
        _config(tmp_path),
        instruments=roster,
        data_fetcher=lambda *_args: _bars(),
    )
    per_instrument = retrainer.model_path("NIFTY", "NSE_INDEX")
    per_instrument.write_bytes(b"corrupt")
    Path(f"{per_instrument}.sha256").write_text("0" * 64, encoding="ascii")
    pipeline = SignalPipeline(
        model_path=str(shared_path),
        instruments=roster,
        market_session_provider=_full_day_session,
    )
    pipeline.fetch_bars = MagicMock(return_value=_bars())

    results = pipeline.run_cycle()

    assert results["NSE_INDEX:NIFTY"]["signal"] == "BUY"
    assert pipeline._generator.is_trained


def test_pipeline_installs_new_generator_for_only_the_target_instrument(tmp_path: Path) -> None:
    from flinttrade_ai.pipeline import SignalPipeline

    shared_path = tmp_path / "signal_model.joblib"
    shared = _save_generator(shared_path, _PredictableModel())
    replacement = _save_generator(tmp_path / "replacement.joblib", _SellModel())
    pipeline = SignalPipeline(model_path=str(shared_path))

    assert pipeline._generator_for("NIFTY", "NSE_INDEX")._model.__class__ is _PredictableModel
    assert pipeline._generator_for("BANKNIFTY", "NSE_INDEX")._model.__class__ is _PredictableModel

    pipeline.install_generator("NIFTY", "NSE_INDEX", replacement)

    assert pipeline._generator_for("NIFTY", "NSE_INDEX") is replacement
    assert pipeline._generator_for("BANKNIFTY", "NSE_INDEX")._model.__class__ is _PredictableModel
    assert pipeline._generator is not replacement
    assert pipeline._generator._model.__class__ is shared._model.__class__


def test_shared_training_replaces_fallback_for_previously_seen_symbols(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_ai.pipeline import SignalPipeline
    from flinttrade_ai.signals import SignalGenerator, engineer_features

    pipeline = SignalPipeline(model_path=str(tmp_path / "shared.joblib"))
    stale_fallback = pipeline._generator_for("NIFTY", "NSE_INDEX")

    def _train(self: SignalGenerator, bars: list[dict[str, Any]], **_kwargs: Any) -> dict[str, float]:
        self._model = _PredictableModel()
        self._feature_names = engineer_features(bars).names
        return {"train_accuracy": 0.9, "test_accuracy": 0.8}

    monkeypatch.setattr(SignalGenerator, "train", _train)

    assert pipeline.train_model([_bars(120)], lookahead=7) is True
    current = pipeline._generator_for("NIFTY", "NSE_INDEX")

    assert current is pipeline._generator
    assert current is not stale_fallback
    assert current.is_trained is True


def test_compatibility_training_refuses_ambiguous_instrument_histories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_ai.pipeline import SignalPipeline

    train_calls = _install_train_stub(monkeypatch, test_accuracy=0.8)
    pipeline = SignalPipeline(model_path=str(tmp_path / "shared.joblib"))

    assert pipeline.train_model(
        [_bars(120), _bars(120, price_shift=10_000.0)],
    ) is False
    assert train_calls == []


def test_shared_training_keeps_previous_model_visible_until_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_ai.pipeline import SignalPipeline
    from flinttrade_ai.signals import SignalGenerator, engineer_features

    target = tmp_path / "shared.joblib"
    _save_generator(target, _PredictableModel())
    pipeline = SignalPipeline(model_path=str(target))

    def _train(self: SignalGenerator, bars: list[dict[str, Any]], **_kwargs: Any) -> dict[str, float]:
        self._model = _SellModel()
        self._feature_names = engineer_features(bars).names
        return {"train_accuracy": 0.9, "test_accuracy": 0.8}

    real_save = SignalGenerator.save
    candidate_saved = threading.Event()
    allow_publication = threading.Event()

    def _paused_save(self: SignalGenerator, path: str) -> None:
        real_save(self, path)
        if isinstance(self._model, _SellModel):
            candidate_saved.set()
            assert allow_publication.wait(timeout=5)

    monkeypatch.setattr(SignalGenerator, "train", _train)
    monkeypatch.setattr(SignalGenerator, "save", _paused_save)
    outcomes: list[bool] = []
    publisher = threading.Thread(target=lambda: outcomes.append(pipeline.train_model([_bars(120)])))
    publisher.start()
    assert candidate_saved.wait(timeout=5)

    visible_during_publication = pipeline._generator_for("NIFTY", "NSE_INDEX")
    allow_publication.set()
    publisher.join(timeout=5)

    assert not publisher.is_alive()
    assert visible_during_publication._model.__class__ is _PredictableModel
    assert outcomes == [True]
    assert pipeline._generator_for("NIFTY", "NSE_INDEX")._model.__class__ is _SellModel


def test_pipeline_cache_uses_tuple_keys_for_colon_colliding_instruments(tmp_path: Path) -> None:
    from flinttrade_ai.pipeline import SignalPipeline

    pipeline = SignalPipeline(model_path=str(tmp_path / "missing-shared.joblib"))
    left = object()
    right = object()

    pipeline.install_generator("NIFTY", "NSE:INDEX", left)
    pipeline.install_generator("INDEX:NIFTY", "NSE", right)

    assert pipeline._symbol_generators[("NSE:INDEX", "NIFTY")] is left
    assert pipeline._symbol_generators[("NSE", "INDEX:NIFTY")] is right
    assert pipeline._generator_for("NIFTY", "NSE:INDEX") is left
    assert pipeline._generator_for("INDEX:NIFTY", "NSE") is right


def test_canonical_retraining_types_are_exported() -> None:
    import flinttrade_ai

    assert flinttrade_ai.SignalRetrainer is not None
    assert flinttrade_ai.RetrainConfig is not None
    assert flinttrade_ai.RetrainResult is not None
    assert flinttrade_ai.select_retraining_roster is not None
    assert {
        "SignalRetrainer",
        "RetrainConfig",
        "RetrainResult",
        "select_retraining_roster",
    } <= set(flinttrade_ai.__all__)


def test_runtime_wires_post_market_retraining_through_the_existing_cron_manager(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    from flask import Flask

    from flinttrade_ai.signal_retraining import SignalRetrainer
    from flinttrade_core.app import _wire_ml_signal_runtime

    app = Flask(__name__)
    pipeline = MagicMock()
    pipeline.model_path = str(tmp_path / "signal_model.joblib")
    pipeline.instruments = [{"symbol": "NIFTY", "exchange": "NSE_INDEX"}]
    app.config["ML_SIGNAL_PIPELINE"] = pipeline
    cron = MagicMock()

    assert _wire_ml_signal_runtime(app, cron, MagicMock()) is True

    calls = {call.args[0]: call for call in cron.register.call_args_list}
    assert set(calls) == {
        "ml_signal_cycle",
        "ml_signal_retrain",
        "ml_signal_retrain_late",
    }
    retrain_call = calls["ml_signal_retrain"]
    assert retrain_call.kwargs["trigger_type"] == "cron"
    assert retrain_call.kwargs["trigger_args"] == {
        "hour": 16,
        "minute": 0,
        "timezone": "Asia/Kolkata",
    }
    late_retrain_call = calls["ml_signal_retrain_late"]
    assert late_retrain_call.kwargs["trigger_type"] == "cron"
    assert late_retrain_call.kwargs["trigger_args"] == {
        "hour": 0,
        "minute": 30,
        "timezone": "Asia/Kolkata",
    }
    assert isinstance(app.config["ML_SIGNAL_RETRAINER"], SignalRetrainer)
    cancel_event = app.config["ML_SIGNAL_RETRAIN_CANCEL_EVENT"]
    assert cancel_event.is_set() is False
    assert app.config["ML_SIGNAL_RETRAINER"]._is_cancelled() is False
    cancel_event.set()
    assert app.config["ML_SIGNAL_RETRAINER"]._is_cancelled() is True
    assert app.config["ML_SIGNAL_RETRAIN_JOB"] == "ml_signal_retrain"
    assert app.config["ML_SIGNAL_RETRAIN_JOBS"] == (
        "ml_signal_retrain",
        "ml_signal_retrain_late",
    )
    assert app.config["ML_SIGNAL_JOB"] == "ml_signal_cycle"


def test_runtime_schedules_and_runs_dated_late_session_retry(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    from flask import Flask

    from flinttrade_core.app import _wire_ml_signal_runtime

    ist = timezone(timedelta(hours=5, minutes=30))
    session_date = date(2026, 4, 17)
    retry_at = datetime(2026, 4, 18, 0, 45, tzinfo=ist)
    app = Flask(__name__)
    pipeline = MagicMock()
    pipeline.model_path = str(tmp_path / "signal_model.joblib")
    pipeline.instruments = [{"symbol": "GOLDM", "exchange": "MCX"}]
    app.config["ML_SIGNAL_PIPELINE"] = pipeline
    cron = MagicMock()
    time_scheduler = MagicMock()
    time_scheduler.now_ist.return_value = datetime(2026, 4, 18, 0, 30, tzinfo=ist)
    time_scheduler.get_schedule.return_value = MagicMock(is_24x7=False)
    time_scheduler.get_market_session.return_value = (time(18, 0), time(0, 45))

    assert _wire_ml_signal_runtime(app, cron, time_scheduler) is True
    calls = {call.args[0]: call for call in cron.register.call_args_list}
    late_handler = calls["ml_signal_retrain_late"].kwargs["handler"]
    assert late_handler() == []

    cron.schedule_once.assert_called_once()
    retry_call = cron.schedule_once.call_args
    assert retry_call.kwargs["run_at"] == retry_at
    assert "MCX" in retry_call.kwargs["name"]
    assert "GOLDM" in retry_call.kwargs["name"]
    assert app.config["ML_SIGNAL_RETRAIN_RETRY_JOBS"] == {retry_call.kwargs["name"]}

    retrainer = app.config["ML_SIGNAL_RETRAINER"]
    completed = MagicMock(completed=True)
    retrainer.run_all = MagicMock(return_value=[completed])
    retry_call.kwargs["handler"]()

    retrainer.run_all.assert_called_once_with(
        instruments=[{"symbol": "GOLDM", "exchange": "MCX"}],
        session_date=session_date,
    )
    assert app.config["ML_SIGNAL_RETRAIN_RETRY_JOBS"] == set()


def test_retrainer_reads_the_pipeline_roster_at_execution_time(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    from flinttrade_ai.pipeline import SignalPipeline
    from flinttrade_ai.signal_retraining import RetrainConfig, SignalRetrainer

    pipeline = SignalPipeline(
        model_path=str(tmp_path / "signal_model.joblib"),
        instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}],
    )
    retrainer = SignalRetrainer(
        RetrainConfig(model_dir=tmp_path),
        instruments=pipeline.instruments,
        data_fetcher=MagicMock(),
        pipeline=pipeline,
        instrument_provider=pipeline.instrument_snapshot,
    )
    retrainer.run_once = MagicMock(return_value=MagicMock())
    pipeline.update_instruments(["NSE:RELIANCE"])

    retrainer.run_all()

    retrainer.run_once.assert_called_once_with("RELIANCE", "NSE")


def test_retrainer_explicit_roster_overrides_the_default_provider(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    from flinttrade_ai.signal_retraining import RetrainConfig, SignalRetrainer

    provider = MagicMock(return_value=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}])
    retrainer = SignalRetrainer(
        RetrainConfig(model_dir=tmp_path),
        instruments=[],
        data_fetcher=MagicMock(),
        instrument_provider=provider,
    )
    retrainer.run_once = MagicMock(return_value=MagicMock(reason="Accepted"))

    retrainer.run_all(instruments=[{"symbol": "GOLDM", "exchange": "MCX"}])

    provider.assert_not_called()
    retrainer.run_once.assert_called_once_with("GOLDM", "MCX")


def test_run_all_forwards_session_date_to_each_instrument(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    from flinttrade_ai.signal_retraining import RetrainConfig, SignalRetrainer

    retrainer = SignalRetrainer(
        RetrainConfig(model_dir=tmp_path),
        instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}],
        data_fetcher=MagicMock(),
    )
    retrainer.run_once = MagicMock(return_value=MagicMock(reason="Accepted"))
    session_date = date(2026, 7, 11)

    retrainer.run_all(session_date=session_date)

    retrainer.run_once.assert_called_once_with(
        "NIFTY",
        "NSE_INDEX",
        session_date=session_date,
    )


def test_retraining_rosters_separate_regular_from_late_and_continuous() -> None:
    from flinttrade_ai.signal_retraining import select_retraining_roster

    instruments = [
        {"symbol": "NIFTY", "exchange": "NSE_INDEX"},
        {"symbol": "GOLDM", "exchange": "MCX"},
        {"symbol": "EURUSD29JUL26FUT", "exchange": "CDS"},
        {"symbol": "BTCUSD", "exchange": "DELTA"},
    ]
    sessions = {
        ("NSE_INDEX", "NIFTY"): (time(9, 15), time(15, 30)),
        ("MCX", "GOLDM"): (time(9, 0), time(23, 55)),
        ("CDS", "EURUSD29JUL26FUT"): (time(9, 0), time(19, 30)),
    }

    regular = select_retraining_roster(
        instruments,
        roster="regular",
        session_date=date(2026, 7, 10),
        run_at=time(16, 0),
        is_continuous=lambda exchange: exchange == "DELTA",
        session_for=lambda exchange, symbol, _on: sessions.get((exchange, symbol)),
    )
    late = select_retraining_roster(
        instruments,
        roster="late",
        session_date=date(2026, 7, 10),
        run_at=time(23, 59),
        is_continuous=lambda exchange: exchange == "DELTA",
        session_for=lambda exchange, symbol, _on: sessions.get((exchange, symbol)),
    )

    assert regular == [instruments[0]]
    assert late == instruments[1:]


def test_cross_midnight_retraining_uses_dated_close_and_waits_for_session_end() -> None:
    from flinttrade_ai.signal_retraining import select_retraining_roster

    instrument = {"symbol": "GOLDM", "exchange": "MCX"}
    session_date = date(2026, 4, 17)
    ist = timezone(timedelta(hours=5, minutes=30))

    def select(roster: str, run_at: datetime):
        return select_retraining_roster(
            [instrument],
            roster=roster,
            session_date=session_date,
            run_at=run_at,
            is_continuous=lambda _exchange: False,
            session_for=lambda _exchange, _symbol, _on: (
                time(18, 0, 30),
                time(0, 15, 45),
            ),
        )

    assert select("regular", datetime(2026, 4, 17, 16, 0, tzinfo=ist)) == []
    assert select("late", datetime(2026, 4, 17, 23, 59, tzinfo=ist)) == []
    assert select("late", datetime(2026, 4, 18, 0, 15, 45, tzinfo=ist)) == [
        instrument
    ]


def test_late_retraining_plan_exposes_retry_for_session_closing_after_0030() -> None:
    from flinttrade_ai.signal_retraining import plan_retraining_roster

    instrument = {"symbol": "GOLDM", "exchange": "MCX"}
    session_date = date(2026, 4, 17)
    ist = timezone(timedelta(hours=5, minutes=30))

    def plan(at: datetime):
        return plan_retraining_roster(
            [instrument],
            roster="late",
            session_date=session_date,
            run_at=at,
            is_continuous=lambda _exchange: False,
            session_for=lambda _exchange, _symbol, _on: (
                time(18, 0),
                time(0, 45),
            ),
        )

    pending = plan(datetime(2026, 4, 18, 0, 30, tzinfo=ist))
    assert pending.ready_instruments == []
    assert len(pending.retries) == 1
    retry = pending.retries[0]
    assert retry.instrument == instrument
    assert retry.session_date == session_date
    assert retry.retry_at == datetime(2026, 4, 18, 0, 45, tzinfo=ist)

    ready = plan(retry.retry_at)
    assert ready.ready_instruments == [instrument]
    assert ready.retries == ()


def test_special_session_moves_equity_to_late_roster_and_closed_day_is_skipped() -> None:
    from flinttrade_ai.signal_retraining import select_retraining_roster

    instruments = [
        {"symbol": "NIFTY", "exchange": "NSE_INDEX"},
        {"symbol": "RELIANCE", "exchange": "NSE"},
    ]

    def session_for(exchange: str, _symbol: str, _on: date):
        if exchange == "NSE_INDEX":
            return time(18, 0), time(19, 0)
        return None

    regular = select_retraining_roster(
        instruments,
        roster="regular",
        session_date=date(2026, 11, 8),
        run_at=time(16, 0),
        is_continuous=lambda _exchange: False,
        session_for=session_for,
    )
    late = select_retraining_roster(
        instruments,
        roster="late",
        session_date=date(2026, 11, 8),
        run_at=time(23, 59),
        is_continuous=lambda _exchange: False,
        session_for=session_for,
    )

    assert regular == []
    assert late == [instruments[0]]


def test_runtime_retrains_only_closed_instruments_then_covers_late_and_continuous_markets(
    tmp_path: Path,
) -> None:
    from datetime import date, datetime, time, timedelta, timezone
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from flask import Flask

    from flinttrade_core.app import _wire_ml_signal_runtime

    instruments = [
        {"symbol": "NIFTY", "exchange": "NSE_INDEX"},
        {"symbol": "GOLDM", "exchange": "MCX"},
        {"symbol": "EURUSD29JUL26FUT", "exchange": "CDS"},
        {"symbol": "BTCUSD", "exchange": "DELTA"},
    ]
    app = Flask(__name__)
    pipeline = MagicMock()
    pipeline.model_path = str(tmp_path / "signal_model.joblib")
    pipeline.instruments = instruments
    app.config["ML_SIGNAL_PIPELINE"] = pipeline
    cron = MagicMock()
    time_scheduler = MagicMock()
    time_scheduler.get_schedule.side_effect = lambda exchange: SimpleNamespace(
        is_24x7=exchange == "DELTA"
    )
    sessions = {
        "NSE_INDEX": (time(9, 15), time(15, 30)),
        "MCX": (time(9, 0), time(23, 55)),
        "CDS": (time(9, 0), time(19, 30)),
    }
    time_scheduler.get_market_session.side_effect = (
        lambda exchange, *, on, symbol: sessions.get(exchange)
    )
    ist = timezone(timedelta(hours=5, minutes=30))
    # Saturday special sessions must still reach both daily roster jobs.
    regular_now = datetime(2026, 7, 11, 16, 0, tzinfo=ist)
    late_now = datetime(2026, 7, 11, 23, 59, tzinfo=ist)
    time_scheduler.now_ist.side_effect = [regular_now, late_now]

    assert _wire_ml_signal_runtime(app, cron, time_scheduler) is True
    retrainer = app.config["ML_SIGNAL_RETRAINER"]
    retrainer.run_all = MagicMock(return_value=[])
    calls = {call.args[0]: call for call in cron.register.call_args_list}

    calls["ml_signal_retrain"].kwargs["handler"]()
    retrainer.run_all.assert_called_once_with(
        instruments=[instruments[0]],
        session_date=date(2026, 7, 11),
    )

    retrainer.run_all.reset_mock()
    calls["ml_signal_retrain_late"].kwargs["handler"]()
    retrainer.run_all.assert_called_once_with(
        instruments=instruments[1:],
        session_date=date(2026, 7, 11),
    )


def test_runtime_late_job_uses_previous_session_date_after_midnight(
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from flask import Flask

    from flinttrade_core.app import _wire_ml_signal_runtime

    instrument = {"symbol": "GOLDM", "exchange": "MCX"}
    app = Flask(__name__)
    pipeline = MagicMock()
    pipeline.model_path = str(tmp_path / "signal_model.joblib")
    pipeline.instruments = [instrument]
    app.config["ML_SIGNAL_PIPELINE"] = pipeline
    cron = MagicMock()
    time_scheduler = MagicMock()
    time_scheduler.get_schedule.return_value = SimpleNamespace(is_24x7=False)
    time_scheduler.get_market_session.return_value = (
        time(18, 0),
        time(0, 15),
    )
    ist = timezone(timedelta(hours=5, minutes=30))
    time_scheduler.now_ist.return_value = datetime(2026, 4, 18, 0, 30, tzinfo=ist)

    assert _wire_ml_signal_runtime(app, cron, time_scheduler) is True
    retrainer = app.config["ML_SIGNAL_RETRAINER"]
    retrainer.run_all = MagicMock(return_value=[])
    calls = {call.args[0]: call for call in cron.register.call_args_list}

    calls["ml_signal_retrain_late"].kwargs["handler"]()

    retrainer.run_all.assert_called_once_with(
        instruments=[instrument],
        session_date=date(2026, 4, 17),
    )


def test_runtime_threads_configurable_label_policy_into_scheduled_retrainer(tmp_path: Path) -> None:
    from unittest.mock import MagicMock

    from flask import Flask

    from flinttrade_core.app import _wire_ml_signal_runtime

    app = Flask(__name__)
    pipeline = MagicMock()
    pipeline.model_path = str(tmp_path / "signal_model.joblib")
    pipeline.instruments = [{"symbol": "NIFTY", "exchange": "NSE_INDEX"}]
    app.config["ML_SIGNAL_PIPELINE"] = pipeline
    app.config["ML_SIGNAL_RETRAIN_CONFIG"] = {
        "lookahead": 9,
        "buy_threshold_pct": 0.8,
        "sell_threshold_pct": -0.3,
    }

    assert _wire_ml_signal_runtime(app, MagicMock(), MagicMock()) is True

    config = app.config["ML_SIGNAL_RETRAINER"].config
    assert config.lookahead == 9
    assert config.buy_threshold_pct == pytest.approx(0.8)
    assert config.sell_threshold_pct == pytest.approx(-0.3)
    assert config.model_dir == tmp_path


def test_retrain_handler_contains_unexpected_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from unittest.mock import MagicMock

    from flask import Flask

    from flinttrade_core.app import _wire_ml_signal_runtime

    app = Flask(__name__)
    pipeline = MagicMock()
    pipeline.model_path = str(tmp_path / "signal_model.joblib")
    pipeline.instruments = [{"symbol": "NIFTY", "exchange": "NSE_INDEX"}]
    app.config["ML_SIGNAL_PIPELINE"] = pipeline
    cron = MagicMock()
    _wire_ml_signal_runtime(app, cron, MagicMock())
    retrainer = app.config["ML_SIGNAL_RETRAINER"]
    monkeypatch.setattr(retrainer, "run_all", lambda: (_ for _ in ()).throw(RuntimeError("training crash")))
    retrain_call = next(call for call in cron.register.call_args_list if call.args[0] == "ml_signal_retrain")

    assert retrain_call.kwargs["handler"]() == []
    assert "Scheduled signal retraining failed" in caplog.text


def test_retrainer_construction_failure_preserves_existing_signal_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock

    from flask import Flask

    import flinttrade_ai.signal_retraining as retraining
    from flinttrade_core.app import _wire_ml_signal_runtime

    app = Flask(__name__)
    pipeline = MagicMock()
    pipeline.model_path = str(tmp_path / "signal_model.joblib")
    pipeline.instruments = [{"symbol": "NIFTY", "exchange": "NSE_INDEX"}]
    app.config["ML_SIGNAL_PIPELINE"] = pipeline
    cron = MagicMock()
    monkeypatch.setattr(
        retraining,
        "SignalRetrainer",
        MagicMock(side_effect=ImportError("optional ML dependency unavailable")),
    )

    assert _wire_ml_signal_runtime(app, cron, MagicMock()) is True

    assert [call.args[0] for call in cron.register.call_args_list] == ["ml_signal_cycle"]
    assert app.config["ML_SIGNAL_JOB"] == "ml_signal_cycle"
    assert "ML_SIGNAL_RETRAINER" not in app.config
    assert "ML_SIGNAL_RETRAIN_JOB" not in app.config
