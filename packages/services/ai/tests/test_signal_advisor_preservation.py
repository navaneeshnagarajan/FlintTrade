"""Task 3a contracts for preserving legacy advisor refinements canonically."""

from __future__ import annotations

import hashlib
import math
import pickle
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


LEGACY_FEATURE_NAMES = [
    "rsi",
    "macd",
    "macd_signal",
    "macd_hist",
    "bb_position",
    "volume_ratio_5",
    "volume_ratio_20",
    "returns_1",
    "returns_5",
    "hl_range",
    "body_pct",
]


def _bars(count: int = 120) -> list[dict[str, float | str]]:
    return [
        {
            "timestamp": f"2026-07-10T09:{index:03d}:00+05:30",
            "open": 100.0 + index * 0.45,
            "high": 101.5 + index * 0.5,
            "low": 99.0 + index * 0.4,
            "close": 100.5 + index * 0.47,
            "volume": 10_000.0 + index * 125.0,
        }
        for index in range(count)
    ]


class _LegacySklearnModel:
    feature_importances_ = [float(index) for index in range(1, len(LEGACY_FEATURE_NAMES) + 1)]

    def __init__(self) -> None:
        self.rows: list[list[float]] = []

    def predict_proba(self, rows: list[list[float]]) -> list[list[float]]:
        self.rows.extend([list(row) for row in rows])
        return [[0.8, 0.15, 0.05] for _ in rows]


class _CanonicalBooster:
    def __init__(self, probabilities: list[float] | None = None) -> None:
        self.probabilities = probabilities or [0.05, 0.15, 0.8]
        self.rows: list[list[float]] = []

    def predict(self, rows: list[list[float]]) -> list[list[float]]:
        self.rows.extend([list(row) for row in rows])
        return [list(self.probabilities) for _ in rows]

    def feature_importance(self) -> list[float]:
        return [float(index + 10) for index in range(18)]


class _NoImportanceBooster:
    def predict(self, rows: list[list[float]]) -> list[list[float]]:
        return [[0.1, 0.8, 0.1] for _ in rows]


class _ExplodingModel:
    def predict(self, rows: list[list[float]]) -> list[list[float]]:
        raise RuntimeError("model exploded")


class _BareExplodingModel:
    def predict(self, rows: list[list[float]]) -> list[list[float]]:
        raise RuntimeError()


def _write_verified_payload(path: Path, payload: dict[str, Any]) -> None:
    with path.open("wb") as model_file:
        pickle.dump(payload, model_file)
    Path(f"{path}.sha256").write_text(
        hashlib.sha256(path.read_bytes()).hexdigest(),
        encoding="ascii",
    )


def _install_fake_lightgbm(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Dataset:
        def __init__(self, data: Any, **kwargs: Any) -> None:
            self.data = data

    booster = _CanonicalBooster([0.1, 0.8, 0.1])
    module = SimpleNamespace(
        Dataset=_Dataset,
        train=lambda *_args, **_kwargs: booster,
        log_evaluation=lambda **_kwargs: object(),
    )
    monkeypatch.setitem(sys.modules, "lightgbm", module)


def _assert_error_hold(signal: Any, message: str) -> None:
    assert signal.action == "HOLD"
    assert signal.signal == "HOLD"
    assert signal.signal_code == 1
    assert signal.confidence == 0.0
    assert signal.probabilities == [0.0, 1.0, 0.0]
    assert signal.probability_labels == ["SELL", "HOLD", "BUY"]
    assert message.lower() in signal.error.lower()
    assert signal.success is False


def test_generate_labels_supports_asymmetric_percentage_thresholds() -> None:
    from flinttrade_ai.signals import generate_labels

    closes = [100.0, 100.75, 100.25]

    buy_sensitive = generate_labels(
        closes,
        lookahead=1,
        offset=0,
        buy_threshold_pct=0.5,
        sell_threshold_pct=-1.0,
    )
    sell_sensitive = generate_labels(
        closes,
        lookahead=1,
        offset=0,
        buy_threshold_pct=1.0,
        sell_threshold_pct=-0.25,
    )

    assert buy_sensitive == [2, 1, 1]
    assert sell_sensitive == [1, 0, 1]


def test_generate_labels_validates_threshold_signs() -> None:
    from flinttrade_ai.signals import generate_labels

    with pytest.raises(ValueError, match="threshold_pct must be positive"):
        generate_labels([100.0, 101.0], threshold_pct=0.0, offset=0)
    with pytest.raises(ValueError, match="buy_threshold_pct must be positive"):
        generate_labels([100.0, 101.0], buy_threshold_pct=-0.1, offset=0)
    with pytest.raises(ValueError, match="sell_threshold_pct must be negative"):
        generate_labels([100.0, 101.0], sell_threshold_pct=0.1, offset=0)
    with pytest.raises(ValueError, match="threshold_pct must be finite"):
        generate_labels([100.0, 101.0], threshold_pct=math.nan, offset=0)
    with pytest.raises(ValueError, match="buy_threshold_pct must be finite"):
        generate_labels([100.0, 101.0], buy_threshold_pct=math.nan, offset=0)
    with pytest.raises(ValueError, match="sell_threshold_pct must be finite"):
        generate_labels([100.0, 101.0], sell_threshold_pct=math.nan, offset=0)


def test_train_forwards_asymmetric_thresholds_and_returns_booster_importance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_ai.signals as signals

    _install_fake_lightgbm(monkeypatch)
    real_generate_labels = signals.generate_labels
    captured: dict[str, Any] = {}

    def _record_labels(
        closes: list[float],
        lookahead: int = 5,
        threshold_pct: float = 0.5,
        offset: int = 20,
        *,
        buy_threshold_pct: float | None = None,
        sell_threshold_pct: float | None = None,
    ) -> list[int]:
        captured.update(
            buy_threshold_pct=buy_threshold_pct,
            sell_threshold_pct=sell_threshold_pct,
        )
        return real_generate_labels(
            closes,
            lookahead,
            threshold_pct,
            offset,
            buy_threshold_pct=buy_threshold_pct,
            sell_threshold_pct=sell_threshold_pct,
        )

    monkeypatch.setattr(signals, "generate_labels", _record_labels)

    metrics = signals.SignalGenerator().train(
        _bars(60),
        buy_threshold_pct=0.75,
        sell_threshold_pct=-0.25,
    )

    assert captured == {"buy_threshold_pct": 0.75, "sell_threshold_pct": -0.25}
    assert len(metrics["feature_importances"]) == 18
    assert metrics["feature_importances"]["return_1"] == 10.0


def test_train_enforces_minimum_rows_before_feature_engineering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import flinttrade_ai.signals as signals

    feature_calls: list[list[dict[str, Any]]] = []

    def _record_features(bars: list[dict[str, Any]], **_kwargs: Any) -> Any:
        feature_calls.append(bars)
        return signals.FeatureSet()

    monkeypatch.setattr(signals, "engineer_features", _record_features)

    with pytest.raises(ValueError, match="29 rows; need at least 30"):
        signals.SignalGenerator().train(_bars(29))

    assert feature_calls == []


def test_untrained_prediction_returns_enriched_error_hold() -> None:
    from flinttrade_ai.signals import SignalGenerator

    signal = SignalGenerator().predict(_bars(60), symbol="NIFTY")

    _assert_error_hold(signal, "not trained")
    assert signal.symbol == "NIFTY"


def test_insufficient_features_return_enriched_error_hold() -> None:
    from flinttrade_ai.signals import SignalGenerator

    generator = SignalGenerator()
    generator._model = _CanonicalBooster()
    generator._feature_names = ["return_1"]

    signal = generator.predict(_bars(20), symbol="NIFTY")

    _assert_error_hold(signal, "insufficient")


def test_model_exception_returns_enriched_error_hold() -> None:
    from flinttrade_ai.signals import SignalGenerator

    generator = SignalGenerator()
    generator._model = _ExplodingModel()
    generator._feature_names = ["return_1"]

    signal = generator.predict(_bars(60), symbol="NIFTY")

    _assert_error_hold(signal, "model exploded")


def test_bare_model_exception_returns_nonempty_error_hold() -> None:
    from flinttrade_ai.signals import SignalGenerator

    generator = SignalGenerator()
    generator._model = _BareExplodingModel()
    generator._feature_names = ["return_1"]

    signal = generator.predict(_bars(60), symbol="NIFTY")

    _assert_error_hold(signal, "runtimeerror")


def test_canonical_prediction_exposes_complete_probability_contract() -> None:
    from flinttrade_ai.signals import SignalGenerator, engineer_features

    bars = _bars(60)
    features = engineer_features(bars)
    generator = SignalGenerator()
    generator._model = _CanonicalBooster()
    generator._feature_names = features.names

    signal = generator.predict(bars, symbol="NIFTY")

    assert signal.action == "BUY"
    assert signal.signal == "BUY"
    assert signal.signal_code == 2
    assert signal.confidence == pytest.approx(0.8)
    assert signal.probabilities == [0.05, 0.15, 0.8]
    assert signal.probability_labels == ["SELL", "HOLD", "BUY"]
    assert signal.feature_importance["return_1"] == 10.0
    assert signal.features == dict(zip(features.names, features.values[-1], strict=True))
    assert signal.timestamp == bars[-1]["timestamp"]
    assert signal.success is True


def test_prediction_without_model_importance_uses_empty_mapping() -> None:
    from flinttrade_ai.signals import SignalGenerator

    generator = SignalGenerator()
    generator._model = _NoImportanceBooster()
    generator._feature_names = ["return_1"]

    signal = generator.predict(_bars(60))

    assert signal.success is True
    assert signal.feature_importance == {}


def test_verified_legacy_payload_uses_adapted_features_and_old_class_order(tmp_path: Path) -> None:
    from flinttrade_ai.signals import SignalGenerator, engineer_features

    model_path = tmp_path / "ml_advisor.pkl"
    _write_verified_payload(
        model_path,
        {"model": _LegacySklearnModel(), "feature_names": LEGACY_FEATURE_NAMES},
    )

    generator = SignalGenerator()
    generator.load(str(model_path))
    bars = _bars(60)
    signal = generator.predict(bars, symbol="NIFTY")

    canonical = dict(zip(engineer_features(bars).names, engineer_features(bars).values[-1], strict=True))
    expected = {
        "rsi": canonical["rsi_14"] * 100.0,
        "macd": canonical["macd"],
        "macd_signal": canonical["macd_signal"],
        "macd_hist": canonical["macd"] - canonical["macd_signal"],
        "bb_position": canonical["bb_pct"],
        "volume_ratio_5": canonical["volume_ratio_5"],
        "volume_ratio_20": canonical["volume_ratio_20"],
        "returns_1": math.log1p(canonical["return_1"]),
        "returns_5": math.log1p(canonical["return_5"]),
        "hl_range": canonical["high_low_range"],
        "body_pct": canonical["body_pct"],
    }

    assert generator._model.rows == [[expected[name] for name in LEGACY_FEATURE_NAMES]]
    assert signal.action == "BUY"
    assert signal.signal_code == 0
    assert signal.probabilities == [0.8, 0.15, 0.05]
    assert signal.probability_labels == ["BUY", "HOLD", "SELL"]
    assert signal.features == expected
    assert signal.feature_importance == dict(
        zip(LEGACY_FEATURE_NAMES, _LegacySklearnModel.feature_importances_, strict=True)
    )
    assert signal.success is True


def test_metadata_less_old_canonical_payload_keeps_booster_class_order(tmp_path: Path) -> None:
    from flinttrade_ai.signals import SignalGenerator

    model_path = tmp_path / "old_canonical.joblib"
    _write_verified_payload(
        model_path,
        {"model": _CanonicalBooster([0.8, 0.15, 0.05]), "feature_names": ["return_1"]},
    )

    generator = SignalGenerator()
    generator.load(str(model_path))
    signal = generator.predict(_bars(60))

    assert signal.action == "SELL"
    assert signal.signal_code == 0
    assert signal.probability_labels == ["SELL", "HOLD", "BUY"]
    assert generator._model.rows


def test_legacy_ordinary_save_reload_retains_semantics_and_class_order(tmp_path: Path) -> None:
    from flinttrade_ai.signals import SignalGenerator

    old_path = tmp_path / "ml_advisor.pkl"
    _write_verified_payload(
        old_path,
        {"model": _LegacySklearnModel(), "feature_names": LEGACY_FEATURE_NAMES},
    )
    generator = SignalGenerator()
    generator.load(str(old_path))

    canonical_path = tmp_path / "canonical.joblib"
    generator.save(str(canonical_path))
    reloaded = SignalGenerator()
    reloaded.load(str(canonical_path))
    signal = reloaded.predict(_bars(60))

    assert signal.action == "BUY"
    assert signal.probability_labels == ["BUY", "HOLD", "SELL"]
    assert reloaded._model.rows


def test_legacy_guarded_bundle_round_trip_retains_semantics_and_class_order(tmp_path: Path) -> None:
    from flinttrade_ai.signal_retraining import (
        _write_model_bundle,
        load_signal_model_bundle,
        signal_model_path,
    )
    from flinttrade_ai.signals import SignalGenerator, engineer_features

    old_path = tmp_path / "ml_advisor.pkl"
    _write_verified_payload(
        old_path,
        {"model": _LegacySklearnModel(), "feature_names": LEGACY_FEATURE_NAMES},
    )
    generator = SignalGenerator()
    generator.load(str(old_path))
    bars = _bars(60)
    target = signal_model_path(tmp_path, "NIFTY", "NSE_INDEX")

    _write_model_bundle(
        target,
        generator,
        engineer_features(bars),
        symbol="NIFTY",
        exchange="NSE_INDEX",
    )
    reloaded = load_signal_model_bundle(target, symbol="NIFTY", exchange="NSE_INDEX")
    signal = reloaded.predict(bars)

    assert signal.action == "BUY"
    assert signal.probability_labels == ["BUY", "HOLD", "SELL"]
    assert reloaded._model.rows


def test_unknown_persisted_feature_returns_error_without_model_execution() -> None:
    from flinttrade_ai.signals import SignalGenerator

    model = _CanonicalBooster()
    generator = SignalGenerator()
    generator._model = model
    generator._feature_names = ["unknown_feature"]

    signal = generator.predict(_bars(60), symbol="NIFTY")

    _assert_error_hold(signal, "unsupported persisted features")
    assert model.rows == []


def test_retrain_config_and_candidates_use_stronger_training_minimum(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_ai.signal_retraining import RetrainConfig, SignalRetrainer
    from flinttrade_ai.signals import SignalGenerator, engineer_features

    assert RetrainConfig().min_training_rows == 100
    captured: dict[str, Any] = {}

    def _train(self: SignalGenerator, bars: list[dict[str, Any]], **kwargs: Any) -> dict[str, float]:
        captured.update(kwargs)
        self._model = _CanonicalBooster()
        self._feature_names = engineer_features(bars).names
        return {"train_accuracy": 0.8, "test_accuracy": 0.7}

    monkeypatch.setattr(SignalGenerator, "train", _train)
    retrainer = SignalRetrainer(
        RetrainConfig(model_dir=tmp_path),
        instruments=[],
        data_fetcher=lambda *_args: _bars(120),
    )

    result = retrainer.run_once("NIFTY", "NSE_INDEX")

    assert result.accepted is True
    assert captured["min_training_rows"] == 100


def test_get_generator_uses_exchange_and_symbol_identity(tmp_path: Path) -> None:
    from flinttrade_ai.signal_retraining import RetrainConfig, SignalRetrainer
    from flinttrade_ai.signals import SignalGenerator

    retrainer = SignalRetrainer(
        RetrainConfig(model_dir=tmp_path),
        instruments=[],
        data_fetcher=lambda *_args: [],
    )
    nse_generator = SignalGenerator()
    bse_generator = SignalGenerator()
    retrainer._live_generators[("NSE", "SHARED")] = nse_generator
    retrainer._live_generators[("BSE", "SHARED")] = bse_generator

    assert retrainer.get_generator("SHARED", "NSE") is nse_generator
    assert retrainer.get_generator("SHARED", "BSE") is bse_generator
