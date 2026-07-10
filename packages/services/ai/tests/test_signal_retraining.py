"""Task 2 contracts for canonical signal retraining."""

from __future__ import annotations

import json
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


class _RecordingPipeline:
    def __init__(self) -> None:
        self.installed: list[tuple[str, str, Any]] = []
        self.model_was_persisted = False

    def install_generator(self, symbol: str, exchange: str, generator: Any) -> None:
        self.installed.append((symbol, exchange, generator))


def _bars(count: int = 80, *, price_shift: float = 0.0) -> list[dict[str, float | str]]:
    return [
        {
            "timestamp": f"2026-01-{index + 1:03d}",
            "open": 100.0 + price_shift + index * 0.7,
            "high": 102.0 + price_shift + index * 0.8,
            "low": 99.0 + price_shift + index * 0.6,
            "close": 101.0 + price_shift + index * 0.75,
            "volume": 10_000.0 + index * 125,
        }
        for index in range(count)
    ]


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

    values = {"model_dir": tmp_path, "min_accuracy": 0.55, **overrides}
    return RetrainConfig(**values)


def _save_generator(path: Path, model: Any) -> Any:
    from flinttrade_ai.signals import SignalGenerator, engineer_features

    generator = SignalGenerator()
    generator._model = model
    generator._feature_names = engineer_features(_bars()).names
    generator.save(str(path))
    return generator


def test_retrain_config_preserves_reviewed_defaults() -> None:
    from flinttrade_ai.signal_retraining import RetrainConfig

    config = RetrainConfig()

    assert config.retrain_interval_hours == 24
    assert config.min_accuracy == 0.55
    assert config.lookback_days == 365
    assert config.validation_split == 0.2
    assert config.drift_threshold == 0.1
    assert config.persist_log is True
    assert config.max_history == 1000


def test_feature_drift_uses_mean_score_and_has_deterministic_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    import flinttrade_ai.signal_retraining as retraining
    from flinttrade_ai.signals import FeatureSet

    monkeypatch.setattr(retraining, "_scipy_ks_2samp", None)
    reference = FeatureSet(names=["stable", "shifted"], values=[[1.0, float(i)] for i in range(10)])
    current = FeatureSet(names=["stable", "shifted"], values=[[1.0, 100.0 + i] for i in range(10)])

    detected, score = retraining.compute_feature_drift(reference, current, threshold=0.1)

    assert detected is True
    assert score == pytest.approx(0.5)


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
    assert model_path.suffix == ".joblib"
    assert "/" not in model_path.name
    assert " " not in model_path.name
    assert model_path.exists()
    assert Path(f"{model_path}.sha256").exists()
    assert not list(tmp_path.glob("*.tmp*"))


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


def test_failed_candidate_persistence_restores_existing_files_and_cleans_temporaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_ai.signal_retraining import SignalRetrainer
    from flinttrade_ai.signals import SignalGenerator

    _install_train_stub(monkeypatch, test_accuracy=0.8)
    retrainer = SignalRetrainer(
        _config(tmp_path),
        instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}],
        data_fetcher=lambda *_args: _bars(),
        pipeline=_RecordingPipeline(),
    )
    target = retrainer.model_path("NIFTY", "NSE_INDEX")
    sidecar = Path(f"{target}.sha256")
    target.write_bytes(b"old-model")
    sidecar.write_text("old-digest", encoding="ascii")

    def _broken_save(self: SignalGenerator, path: str) -> None:
        Path(path).write_bytes(b"partial-candidate")
        raise OSError("disk full")

    monkeypatch.setattr(SignalGenerator, "save", _broken_save)

    result = retrainer.run_once("NIFTY", "NSE_INDEX")

    assert result.accepted is False
    assert "Persistence failed" in result.reason
    assert target.read_bytes() == b"old-model"
    assert sidecar.read_text(encoding="ascii") == "old-digest"
    assert not list(tmp_path.glob("*.tmp*"))


def test_filesystem_safe_model_paths_do_not_collide_with_literal_safe_symbols(tmp_path: Path) -> None:
    from flinttrade_ai.signal_retraining import signal_model_path

    escaped = signal_model_path(tmp_path, "NIFTY/50", "NSE INDEX")
    literal = signal_model_path(tmp_path, "NIFTY_50", "NSE_INDEX")

    assert escaped != literal


def test_backup_setup_failure_cleans_all_temporary_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_ai.signal_retraining import SignalRetrainer

    _install_train_stub(monkeypatch, test_accuracy=0.8)
    retrainer = SignalRetrainer(
        _config(tmp_path),
        instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}],
        data_fetcher=lambda *_args: _bars(),
        pipeline=_RecordingPipeline(),
    )
    target = retrainer.model_path("NIFTY", "NSE_INDEX")
    sidecar = Path(f"{target}.sha256")
    target.write_bytes(b"old-model")
    sidecar.write_text("old-digest", encoding="ascii")
    real_backup = retrainer._backup
    calls = 0

    def _failing_backup(path: Path) -> Path | None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("backup unavailable")
        return real_backup(path)

    monkeypatch.setattr(retrainer, "_backup", _failing_backup)

    result = retrainer.run_once("NIFTY", "NSE_INDEX")

    assert result.accepted is False
    assert "Persistence failed" in result.reason
    assert target.read_bytes() == b"old-model"
    assert sidecar.read_text(encoding="ascii") == "old-digest"
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
    _save_generator(retrainer.model_path("NIFTY", "NSE_INDEX"), _SellModel())
    pipeline = SignalPipeline(model_path=str(shared_path), instruments=roster)
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
    pipeline = SignalPipeline(model_path=str(shared_path), instruments=roster)
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


def test_canonical_retraining_types_are_exported() -> None:
    import flinttrade_ai

    assert flinttrade_ai.SignalRetrainer is not None
    assert flinttrade_ai.RetrainConfig is not None
    assert flinttrade_ai.RetrainResult is not None
    assert {"SignalRetrainer", "RetrainConfig", "RetrainResult"} <= set(flinttrade_ai.__all__)


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
    assert set(calls) == {"ml_signal_cycle", "ml_signal_retrain"}
    retrain_call = calls["ml_signal_retrain"]
    assert retrain_call.kwargs["trigger_type"] == "cron"
    assert retrain_call.kwargs["trigger_args"] == {
        "hour": 16,
        "minute": 0,
        "day_of_week": "mon-fri",
        "timezone": "Asia/Kolkata",
    }
    assert isinstance(app.config["ML_SIGNAL_RETRAINER"], SignalRetrainer)
    assert app.config["ML_SIGNAL_RETRAIN_JOB"] == "ml_signal_retrain"
    assert app.config["ML_SIGNAL_JOB"] == "ml_signal_cycle"


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
