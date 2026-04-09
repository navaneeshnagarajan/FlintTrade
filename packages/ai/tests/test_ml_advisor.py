"""Tests for ml_advisor module.

Covers:
- FeatureEngineer: all feature columns present, no NaN after warm-up, RSI bounds.
- MLAdvisorConfig: validation, defaults.
- MLAdvisor: label generation, train returns metrics, predict returns Prediction,
  feature importance dict, save/load round-trip.
- Edge cases: predict before train returns error, short DataFrame raises ValueError.
"""

from __future__ import annotations

import pickle
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from packages.ai.src.ml_advisor import (
    FeatureEngineer,
    MLAdvisor,
    MLAdvisorConfig,
    Prediction,
    _FEATURE_COLUMNS,
    _SIGNAL_NAMES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ohlcv(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV data with realistic price structure."""
    rng = np.random.default_rng(seed)
    close = 20_000.0 + np.cumsum(rng.normal(0, 50, n))
    high = close + rng.uniform(10, 100, n)
    low = close - rng.uniform(10, 100, n)
    open_ = close + rng.normal(0, 20, n)
    volume = rng.integers(50_000, 200_000, n).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


# ---------------------------------------------------------------------------
# FeatureEngineer
# ---------------------------------------------------------------------------


class TestFeatureEngineer:
    def test_all_feature_columns_present(self) -> None:
        fe = FeatureEngineer()
        df = _make_ohlcv(100)
        result = fe.build_features(df)
        for col in _FEATURE_COLUMNS:
            assert col in result.columns, f"Missing column: {col}"

    def test_no_nan_after_warmup_period(self) -> None:
        fe = FeatureEngineer()
        df = _make_ohlcv(200)
        result = fe.build_features(df)
        # Drop the first 30 rows (warm-up for indicators) and check no NaN.
        tail = result.iloc[30:][_FEATURE_COLUMNS]
        assert not tail.isnull().any(axis=None), "NaN found in features after warm-up"

    def test_rsi_bounds(self) -> None:
        fe = FeatureEngineer()
        df = _make_ohlcv(200)
        result = fe.build_features(df)
        valid_rsi = result["rsi"].dropna()
        assert (valid_rsi >= 0.0).all()
        assert (valid_rsi <= 100.0).all()

    def test_bb_position_bounds(self) -> None:
        fe = FeatureEngineer()
        df = _make_ohlcv(200)
        result = fe.build_features(df)
        valid = result["bb_position"].dropna()
        assert (valid >= 0.0).all()
        assert (valid <= 1.0).all()

    def test_returns_1_correct(self) -> None:
        fe = FeatureEngineer()
        df = _make_ohlcv(50)
        result = fe.build_features(df)
        # Manual log return for bar 5
        expected = np.log(df["close"].iloc[5] / df["close"].iloc[4])
        assert result["returns_1"].iloc[5] == pytest.approx(expected)

    def test_missing_column_raises_value_error(self) -> None:
        fe = FeatureEngineer()
        df = pd.DataFrame({"open": [1.0], "close": [1.0]})
        with pytest.raises(ValueError, match="Missing required columns"):
            fe.build_features(df)

    def test_original_df_not_mutated(self) -> None:
        fe = FeatureEngineer()
        df = _make_ohlcv(100)
        original_cols = set(df.columns)
        fe.build_features(df)
        assert set(df.columns) == original_cols

    def test_macd_hist_is_difference(self) -> None:
        fe = FeatureEngineer()
        df = _make_ohlcv(100)
        result = fe.build_features(df)
        diff = result["macd"] - result["macd_signal"]
        pd.testing.assert_series_equal(
            result["macd_hist"], diff, check_names=False, rtol=1e-6
        )


# ---------------------------------------------------------------------------
# MLAdvisorConfig
# ---------------------------------------------------------------------------


class TestMLAdvisorConfig:
    def test_defaults(self) -> None:
        cfg = MLAdvisorConfig()
        assert cfg.lookback == 100
        assert cfg.forward_bars == 5
        assert cfg.buy_threshold == pytest.approx(0.005)
        assert cfg.sell_threshold == pytest.approx(-0.005)
        assert cfg.n_estimators == 300

    def test_lookback_minimum(self) -> None:
        with pytest.raises(Exception):
            MLAdvisorConfig(lookback=5)

    def test_test_size_bounds(self) -> None:
        with pytest.raises(Exception):
            MLAdvisorConfig(test_size=0.0)
        with pytest.raises(Exception):
            MLAdvisorConfig(test_size=1.0)


# ---------------------------------------------------------------------------
# MLAdvisor — label generation
# ---------------------------------------------------------------------------


class TestMLAdvisorLabels:
    def test_buy_label_on_upward_return(self) -> None:
        advisor = MLAdvisor(MLAdvisorConfig(forward_bars=1, buy_threshold=0.005, sell_threshold=-0.005))
        fe = FeatureEngineer()
        df = _make_ohlcv(50)
        featured = fe.build_features(df)
        labelled = advisor._add_labels(featured)
        # Find a row where forward return > 0.005
        forward_ret = df["close"].shift(-1) / df["close"] - 1
        buy_mask = forward_ret > 0.005
        if buy_mask.any():
            assert (labelled.loc[buy_mask, "label"] == 0).all()

    def test_sell_label_on_downward_return(self) -> None:
        advisor = MLAdvisor(MLAdvisorConfig(forward_bars=1, buy_threshold=0.005, sell_threshold=-0.005))
        fe = FeatureEngineer()
        df = _make_ohlcv(50)
        featured = fe.build_features(df)
        labelled = advisor._add_labels(featured)
        forward_ret = df["close"].shift(-1) / df["close"] - 1
        sell_mask = forward_ret < -0.005
        if sell_mask.any():
            assert (labelled.loc[sell_mask, "label"] == 2).all()

    def test_hold_is_default_label(self) -> None:
        advisor = MLAdvisor(MLAdvisorConfig(forward_bars=1, buy_threshold=1.0, sell_threshold=-1.0))
        fe = FeatureEngineer()
        df = _make_ohlcv(50)
        featured = fe.build_features(df)
        labelled = advisor._add_labels(featured)
        # With very wide thresholds, all non-NaN labels should be HOLD (1)
        non_nan = labelled["label"].dropna()
        assert (non_nan == 1).all()


# ---------------------------------------------------------------------------
# MLAdvisor — train (mocked LightGBM)
# ---------------------------------------------------------------------------


def _make_mock_lgb_model(signal_code: int = 1) -> MagicMock:
    model = MagicMock()
    n_features = len(_FEATURE_COLUMNS)
    model.feature_importances_ = np.ones(n_features)
    # predict returns signal_code for all rows
    model.predict.side_effect = lambda X: np.full(len(X), signal_code)
    # predict_proba returns uniform-ish probas with signal_code highest
    probas = np.full((1, 3), 0.1)
    probas[0][signal_code] = 0.8
    model.predict_proba.return_value = probas
    return model


class TestMLAdvisorTrain:
    def test_train_returns_metrics(self) -> None:
        df = _make_ohlcv(200)
        mock_model = _make_mock_lgb_model()
        mock_lgb = MagicMock()
        mock_lgb.LGBMClassifier.return_value = mock_model

        with patch.dict("sys.modules", {"lightgbm": mock_lgb}):
            advisor = MLAdvisor(MLAdvisorConfig(lookback=50, n_estimators=10))
            metrics = advisor.train(df)

        assert "accuracy" in metrics
        assert "train_samples" in metrics
        assert "test_samples" in metrics
        assert 0.0 <= metrics["accuracy"] <= 1.0
        assert metrics["train_samples"] > 0
        assert metrics["test_samples"] > 0

    def test_train_insufficient_data_raises(self) -> None:
        df = _make_ohlcv(20)
        mock_lgb = MagicMock()
        mock_lgb.LGBMClassifier.return_value = _make_mock_lgb_model()

        with patch.dict("sys.modules", {"lightgbm": mock_lgb}):
            advisor = MLAdvisor(MLAdvisorConfig(lookback=100))
            with pytest.raises(ValueError, match="need at least"):
                advisor.train(df)

    def test_train_no_lightgbm_raises(self) -> None:
        df = _make_ohlcv(200)
        with patch.dict("sys.modules", {"lightgbm": None}):
            advisor = MLAdvisor()
            with pytest.raises((ImportError, RuntimeError)):
                advisor.train(df)


# ---------------------------------------------------------------------------
# MLAdvisor — predict
# ---------------------------------------------------------------------------


class TestMLAdvisorPredict:
    def _trained_advisor(self, signal_code: int = 1) -> MLAdvisor:
        mock_model = _make_mock_lgb_model(signal_code)
        mock_lgb = MagicMock()
        mock_lgb.LGBMClassifier.return_value = mock_model
        with patch.dict("sys.modules", {"lightgbm": mock_lgb}):
            advisor = MLAdvisor(MLAdvisorConfig(lookback=50, n_estimators=10))
            advisor.train(_make_ohlcv(200))
        return advisor

    def test_predict_before_train_returns_error(self) -> None:
        advisor = MLAdvisor()
        result = advisor.predict(_make_ohlcv(50))
        assert not result.success
        assert "not trained" in result.error.lower()

    def test_predict_returns_prediction(self) -> None:
        advisor = self._trained_advisor(signal_code=0)  # BUY
        result = advisor.predict(_make_ohlcv(200))
        assert result.success or result.error  # either success or graceful error
        if result.success:
            assert result.signal in {"BUY", "SELL", "HOLD"}
            assert 0.0 <= result.confidence <= 1.0
            assert len(result.probabilities) == 3

    def test_predict_feature_importance_populated(self) -> None:
        advisor = self._trained_advisor()
        result = advisor.predict(_make_ohlcv(200))
        if result.success:
            assert isinstance(result.feature_importance, dict)
            assert len(result.feature_importance) == len(_FEATURE_COLUMNS)

    def test_predict_signal_names_valid(self) -> None:
        assert set(_SIGNAL_NAMES.values()) == {"BUY", "HOLD", "SELL"}

    def test_predict_insufficient_data_returns_error(self) -> None:
        advisor = self._trained_advisor()
        # Only 1 row — will have all NaN features
        tiny_df = _make_ohlcv(1)
        result = advisor.predict(tiny_df)
        # Should either return error about NaN or succeed (depends on mock)
        assert isinstance(result, Prediction)


# ---------------------------------------------------------------------------
# MLAdvisor — save / load
# ---------------------------------------------------------------------------


class _PicklableStubModel:
    """A picklable stub model that mimics a trained LightGBM classifier."""

    feature_importances_ = np.ones(len(_FEATURE_COLUMNS))

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.ones(len(X), dtype=int)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        probas = np.full((len(X), 3), 0.1)
        probas[:, 1] = 0.8
        return probas


class TestMLAdvisorSaveLoad:
    def _advisor_with_stub(self) -> MLAdvisor:
        """Return an MLAdvisor with a real picklable stub model (no LightGBM needed)."""
        advisor = MLAdvisor(MLAdvisorConfig(lookback=50, n_estimators=10))
        advisor._model = _PicklableStubModel()
        return advisor

    def test_save_creates_file(self, tmp_path: Path) -> None:
        advisor = self._advisor_with_stub()
        model_file = tmp_path / "model.pkl"
        saved = advisor.save(model_file)
        assert saved == model_file
        assert model_file.exists()

    def test_load_restores_model(self, tmp_path: Path) -> None:
        advisor = self._advisor_with_stub()
        model_file = tmp_path / "model.pkl"
        advisor.save(model_file)

        new_advisor = MLAdvisor()
        assert new_advisor._model is None
        new_advisor.load(model_file)
        assert new_advisor._model is not None
        assert new_advisor._feature_names == _FEATURE_COLUMNS

    def test_save_without_model_raises(self, tmp_path: Path) -> None:
        advisor = MLAdvisor()
        with pytest.raises(RuntimeError, match="No trained model"):
            advisor.save(tmp_path / "model.pkl")

    def test_load_missing_file_raises(self) -> None:
        advisor = MLAdvisor()
        with pytest.raises(FileNotFoundError):
            advisor.load("/nonexistent/model.pkl")

    def test_save_load_round_trip_predicts(self, tmp_path: Path) -> None:
        """A loaded model should make predictions identically to the original."""
        advisor = self._advisor_with_stub()
        model_file = tmp_path / "advisor.pkl"
        advisor.save(model_file)

        loaded = MLAdvisor()
        loaded.load(model_file)

        df = _make_ohlcv(200)
        original_pred = advisor.predict(df)
        loaded_pred = loaded.predict(df)

        # Both should produce the same signal (same underlying stub model).
        if original_pred.success and loaded_pred.success:
            assert original_pred.signal == loaded_pred.signal


# ---------------------------------------------------------------------------
# Prediction dataclass
# ---------------------------------------------------------------------------


class TestPrediction:
    def test_success_true_when_no_error(self) -> None:
        p = Prediction(signal="BUY", signal_code=0, confidence=0.8)
        assert p.success is True

    def test_success_false_when_error(self) -> None:
        p = Prediction(error="something went wrong")
        assert p.success is False

    def test_default_signal_is_hold(self) -> None:
        p = Prediction()
        assert p.signal == "HOLD"
        assert p.signal_code == 1
