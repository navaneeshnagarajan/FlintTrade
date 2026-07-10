"""Task 1 contracts for canonical signal-advisor consolidation."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest


class RecordingModel:
    """Picklable prediction stub that records the supplied feature row."""

    def __init__(self) -> None:
        self.rows: list[list[float]] = []

    def predict(self, rows: list[list[float]]) -> list[list[float]]:
        self.rows.extend(rows)
        return [[0.1, 0.2, 0.7] for _ in rows]


def _bars(count: int = 40) -> list[dict[str, float | str]]:
    """Create deterministic OHLCV bars with non-zero candle bodies."""
    return [
        {
            "timestamp": f"2026-07-10T09:{index:02d}:00+05:30",
            "open": 100.0 + index * 0.8,
            "high": 103.0 + index,
            "low": 99.0 + index * 0.6,
            "close": 101.0 + index,
            "volume": 1_000.0 + index * 25,
        }
        for index in range(count)
    ]


def test_canonical_features_include_feature_engineer_refinements() -> None:
    """The wired list-based path carries the missing advisor feature union."""
    from flinttrade_ai.signals import compute_macd, engineer_features

    bars = _bars()
    features = engineer_features(bars)
    values = dict(zip(features.names, features.values[-1], strict=True))
    closes = [float(bar["close"]) for bar in bars]
    volumes = [float(bar["volume"]) for bar in bars]
    macd, macd_signal = compute_macd(closes)
    last = bars[-1]

    assert {"macd", "macd_signal", "volume_ratio_20", "body_pct"} <= set(features.names)
    assert values["macd"] == pytest.approx(macd[-1])
    assert values["macd_signal"] == pytest.approx(macd_signal[-1])
    assert values["volume_ratio_20"] == pytest.approx(volumes[-1] / (sum(volumes[-20:]) / 20))
    assert values["body_pct"] == pytest.approx(
        abs(float(last["close"]) - float(last["open"])) / (float(last["high"]) - float(last["low"]))
    )


def test_prediction_aligns_feature_row_to_persisted_names() -> None:
    """An older model receives its exact persisted column sequence."""
    from flinttrade_ai.signals import SignalGenerator, engineer_features

    generator = SignalGenerator()
    model = RecordingModel()
    generator._model = model
    generator._feature_names = ["ema_cross", "return_1", "macd_hist"]

    signal = generator.predict(_bars(), symbol="NIFTY")

    canonical = engineer_features(_bars())
    available = dict(zip(canonical.names, canonical.values[-1], strict=True))
    assert model.rows == [[available[name] for name in generator._feature_names]]
    assert signal.action == "BUY"
    assert signal.features == {name: available[name] for name in generator._feature_names}


def test_unknown_persisted_feature_fails_closed_without_model_prediction() -> None:
    """A model schema with an unknown field never receives a malformed row."""
    from flinttrade_ai.signals import SignalGenerator

    generator = SignalGenerator()
    model = RecordingModel()
    generator._model = model
    generator._feature_names = ["return_1", "removed_feature"]

    signal = generator.predict(_bars(), symbol="NIFTY")

    assert signal.action == "HOLD"
    assert signal.confidence == 0.0
    assert model.rows == []


def test_save_writes_sha256_sidecar_and_load_verifies_before_deserialising(tmp_path: Path) -> None:
    """Canonical joblib persistence writes and validates a digest sidecar."""
    from flinttrade_ai.signals import SignalGenerator

    model_path = tmp_path / "signal_model.joblib"
    saved = SignalGenerator()
    saved._model = RecordingModel()
    saved._feature_names = ["return_1"]
    saved.save(str(model_path))

    sidecar = Path(f"{model_path}.sha256")
    assert sidecar.read_text(encoding="ascii").strip() == hashlib.sha256(model_path.read_bytes()).hexdigest()

    loaded = SignalGenerator()
    loaded.load(str(model_path))
    assert loaded._feature_names == ["return_1"]
    assert loaded.is_trained


def test_load_rejects_missing_sidecar_before_joblib_load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unverified joblib files are rejected before their deserialiser runs."""
    import joblib

    from flinttrade_ai.signals import SignalGenerator

    model_path = tmp_path / "signal_model.joblib"
    model_path.write_bytes(b"untrusted")
    loader = MagicMock()
    monkeypatch.setattr(joblib, "load", loader)

    with pytest.raises(RuntimeError, match="no SHA-256 sidecar"):
        SignalGenerator().load(str(model_path))

    loader.assert_not_called()


def test_missing_sidecar_override_is_explicit_and_warned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """Only the documented signal-model trust override permits legacy files."""
    import joblib

    from flinttrade_ai.signals import SignalGenerator

    model_path = tmp_path / "signal_model.joblib"
    joblib.dump({"model": RecordingModel(), "feature_names": ["return_1"]}, model_path)
    monkeypatch.setenv("FLINTTRADE_SIGNAL_MODEL_TRUST_UNVERIFIED", "YeS")

    generator = SignalGenerator()
    generator.load(str(model_path))

    assert generator.is_trained
    assert "WITHOUT sha256 verification" in caplog.text


def test_checksum_mismatch_is_never_overrideable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Trust override does not bypass a digest mismatch."""
    from flinttrade_ai.signals import SignalGenerator

    model_path = tmp_path / "signal_model.joblib"
    model_path.write_bytes(b"corrupted")
    Path(f"{model_path}.sha256").write_text("0" * 64, encoding="ascii")
    monkeypatch.setenv("FLINTTRADE_SIGNAL_MODEL_TRUST_UNVERIFIED", "true")

    with pytest.raises(RuntimeError, match="checksum mismatch"):
        SignalGenerator().load(str(model_path))


def test_pipeline_uses_ema_fallback_when_model_integrity_is_rejected(tmp_path: Path) -> None:
    """A corrupt model does not stop scheduled signal publication."""
    from flinttrade_ai.pipeline import SignalPipeline

    model_path = tmp_path / "signal_model.joblib"
    model_path.write_bytes(b"untrusted")
    pipeline = SignalPipeline(
        model_path=str(model_path),
        instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}],
    )
    pipeline.fetch_bars = MagicMock(return_value=_bars(60))

    results = pipeline.run_cycle()

    assert pipeline._generator is not None
    assert not pipeline._generator.is_trained
    assert results["NSE_INDEX:NIFTY"]["method"] == "ema_crossover_fallback"


def test_pipeline_uses_ema_fallback_when_verified_payload_is_corrupt(tmp_path: Path) -> None:
    """A structurally invalid verified payload cannot partially train the generator."""
    import joblib

    from flinttrade_ai.pipeline import SignalPipeline

    model_path = tmp_path / "signal_model.joblib"
    joblib.dump({"model": RecordingModel()}, model_path)
    Path(f"{model_path}.sha256").write_text(
        hashlib.sha256(model_path.read_bytes()).hexdigest(),
        encoding="ascii",
    )
    pipeline = SignalPipeline(
        model_path=str(model_path),
        instruments=[{"symbol": "NIFTY", "exchange": "NSE_INDEX"}],
    )
    pipeline.fetch_bars = MagicMock(return_value=_bars(60))

    results = pipeline.run_cycle()

    assert not pipeline._generator.is_trained
    assert results["NSE_INDEX:NIFTY"]["method"] == "ema_crossover_fallback"


def test_signed_legacy_model_migrates_with_sidecar_and_loads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Workspace migration preserves verification for a signed legacy model."""
    import flinttrade_ai.pipeline as pipeline_mod
    from flinttrade_ai.pipeline import SignalPipeline
    from flinttrade_ai.signals import SignalGenerator

    legacy_home = tmp_path / "legacy-home" / ".flinttrade"
    legacy_model = legacy_home / "models" / "signal_model.joblib"
    workspace = tmp_path / "workspace"
    generator = SignalGenerator()
    generator._model = RecordingModel()
    generator._feature_names = ["return_1"]
    generator.save(str(legacy_model))

    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
    monkeypatch.delenv("FLINTTRADE_SIGNAL_MODEL_TRUST_UNVERIFIED", raising=False)
    monkeypatch.setattr(pipeline_mod, "_legacy_state_dir", lambda: legacy_home)

    pipeline = SignalPipeline()
    pipeline._ensure_generator()

    migrated_model = workspace / "models" / "signal_model.joblib"
    migrated_sidecar = Path(f"{migrated_model}.sha256")
    assert migrated_model.exists()
    assert migrated_sidecar.read_text(encoding="ascii") == Path(f"{legacy_model}.sha256").read_text(encoding="ascii")
    assert pipeline._generator.is_trained
    assert pipeline._generator._feature_names == ["return_1"]
