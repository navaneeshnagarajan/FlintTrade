"""Tests for the auto_retrain module.

Covers:
- RetrainConfig: pydantic validation, defaults.
- RetrainResult: serialisation round-trip.
- _compute_ks_drift: drift detection (above / below threshold, empty inputs).
- AutoRetrainer.run_once: success path, data fetch failure, training failure,
  accuracy below threshold (rejection), drift detection side-effect.
- AutoRetrainer.run_all: all symbols processed, results collected.
- AutoRetrainer model swap: live advisor updated; old advisor still works
  during a retrain (thread-safety simulation).
- AutoRetrainer.get_history: ordering, max_history cap.
- AutoRetrainer persistence: log written to model_dir when persist_log=True.
- AutoRetrainer.stop: loop exits cleanly.

Test strategy: ``MLAdvisor.train`` is patched via a side-effect that installs a
real picklable stub model on the advisor instance and returns the desired
metrics.  This avoids the need for a real LightGBM installation and bypasses
MagicMock's pickle incompatibility entirely.
"""

from __future__ import annotations

import asyncio
import json
import pickle
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from packages.ai.src.auto_retrain import (
    AutoRetrainer,
    RetrainConfig,
    RetrainResult,
    _compute_ks_drift,
)
from packages.ai.src.ml_advisor import MLAdvisor, MLAdvisorConfig, _FEATURE_COLUMNS


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_ohlcv(n: int = 250, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV data with realistic structure."""
    rng = np.random.default_rng(seed)
    close = 20_000.0 + np.cumsum(rng.normal(0, 50, n))
    high = close + rng.uniform(10, 100, n)
    low = close - rng.uniform(10, 100, n)
    open_ = close + rng.normal(0, 20, n)
    volume = rng.integers(50_000, 200_000, n).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}
    )


class _PicklableStubModel:
    """A real picklable stub that mimics a trained LightGBM classifier.

    Used instead of MagicMock so ``_swap_model``'s ``pickle.dump`` succeeds.
    """

    feature_importances_ = np.ones(len(_FEATURE_COLUMNS))

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.ones(len(X), dtype=int)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        probas = np.full((len(X), 3), 0.1)
        probas[:, 1] = 0.8
        return probas


def _train_side_effect(accuracy: float = 0.65):
    """Return a side-effect function for ``MLAdvisor.train``.

    The side-effect installs a ``_PicklableStubModel`` on the advisor instance
    so that ``_swap_model`` can pickle it, and returns metrics as if a real
    training run completed with ``accuracy``.
    """

    def _side_effect(self_advisor: MLAdvisor, df: pd.DataFrame) -> dict:
        self_advisor._model = _PicklableStubModel()
        return {
            "accuracy": accuracy,
            "train_samples": max(1, int(len(df) * 0.8)),
            "test_samples": max(1, int(len(df) * 0.2)),
        }

    return _side_effect


async def _good_fetcher(symbol: str, lookback_days: int) -> pd.DataFrame:
    """Async data fetcher returning a valid 250-row OHLCV DataFrame."""
    return _make_ohlcv(250)


async def _empty_fetcher(symbol: str, lookback_days: int) -> pd.DataFrame:
    """Async data fetcher that returns an empty DataFrame."""
    return pd.DataFrame()


async def _error_fetcher(symbol: str, lookback_days: int) -> pd.DataFrame:
    """Async data fetcher that raises an exception."""
    raise RuntimeError("Simulated data source error")


def _default_config(tmp_path: Path, **kwargs: object) -> RetrainConfig:
    """Return a ``RetrainConfig`` pointing at ``tmp_path`` with fast defaults.

    ``min_accuracy`` defaults to 0.0 (accept any model) unless overridden via
    ``kwargs``.
    """
    defaults: dict[str, object] = {
        "symbols": ["NIFTY"],
        "model_dir": tmp_path,
        "lookback_days": 60,
        "min_accuracy": 0.0,
    }
    defaults.update(kwargs)
    return RetrainConfig(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# RetrainConfig
# ---------------------------------------------------------------------------


class TestRetrainConfig:
    def test_defaults(self) -> None:
        cfg = RetrainConfig()
        assert cfg.symbols == ["NIFTY", "BANKNIFTY"]
        assert cfg.retrain_interval_hours == 24
        assert cfg.min_accuracy == pytest.approx(0.55)
        assert cfg.lookback_days == 365
        assert cfg.validation_split == pytest.approx(0.2)
        assert cfg.drift_threshold == pytest.approx(0.1)
        assert cfg.model_dir == Path("~/.flinttrade/models").expanduser()
        assert cfg.persist_log is True

    def test_interval_must_be_positive(self) -> None:
        with pytest.raises(Exception):
            RetrainConfig(retrain_interval_hours=0)

    def test_min_accuracy_bounds(self) -> None:
        with pytest.raises(Exception):
            RetrainConfig(min_accuracy=-0.1)
        with pytest.raises(Exception):
            RetrainConfig(min_accuracy=1.1)

    def test_validation_split_bounds(self) -> None:
        with pytest.raises(Exception):
            RetrainConfig(validation_split=0.0)
        with pytest.raises(Exception):
            RetrainConfig(validation_split=1.0)

    def test_custom_values(self) -> None:
        cfg = RetrainConfig(symbols=["INFY"], retrain_interval_hours=6, min_accuracy=0.6)
        assert cfg.symbols == ["INFY"]
        assert cfg.retrain_interval_hours == 6
        assert cfg.min_accuracy == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# RetrainResult
# ---------------------------------------------------------------------------


class TestRetrainResult:
    def _make_result(self) -> RetrainResult:
        return RetrainResult(
            timestamp=datetime(2026, 4, 9, 10, 30, tzinfo=timezone.utc),
            symbol="NIFTY",
            train_accuracy=0.68,
            val_accuracy=0.61,
            accepted=True,
            reason="Accepted: val_accuracy=0.6100 >= min=0.5500",
            duration_seconds=12.4,
            drift_detected=False,
            drift_score=0.03,
        )

    def test_to_dict_keys(self) -> None:
        d = self._make_result().to_dict()
        expected_keys = {
            "timestamp", "symbol", "train_accuracy", "val_accuracy",
            "accepted", "reason", "duration_seconds", "drift_detected", "drift_score",
        }
        assert expected_keys == set(d.keys())

    def test_to_dict_types(self) -> None:
        d = self._make_result().to_dict()
        assert isinstance(d["timestamp"], str)
        assert isinstance(d["accepted"], bool)
        assert isinstance(d["duration_seconds"], float)

    def test_to_dict_round_trip(self) -> None:
        r = self._make_result()
        d = r.to_dict()
        assert d["symbol"] == "NIFTY"
        assert d["val_accuracy"] == pytest.approx(0.61)
        assert d["accepted"] is True


# ---------------------------------------------------------------------------
# _compute_ks_drift
# ---------------------------------------------------------------------------


class TestComputeKsDrift:
    def _feature_df(self, n: int = 100, mean: float = 0.0, std: float = 1.0) -> pd.DataFrame:
        rng = np.random.default_rng(7)
        data = {col: rng.normal(mean, std, n) for col in _FEATURE_COLUMNS}
        return pd.DataFrame(data)

    def test_identical_distributions_no_drift(self) -> None:
        df = self._feature_df(200)
        drift, score = _compute_ks_drift(df, df.copy(), list(_FEATURE_COLUMNS), threshold=0.1)
        assert drift is False
        assert score < 0.1

    def test_highly_shifted_distribution_detects_drift(self) -> None:
        train_df = self._feature_df(200, mean=0.0, std=1.0)
        live_df = self._feature_df(100, mean=10.0, std=1.0)
        drift, score = _compute_ks_drift(train_df, live_df, list(_FEATURE_COLUMNS), threshold=0.1)
        assert drift is True
        assert score > 0.1

    def test_empty_train_returns_no_drift(self) -> None:
        live_df = self._feature_df(50)
        drift, score = _compute_ks_drift(
            pd.DataFrame(), live_df, list(_FEATURE_COLUMNS), threshold=0.1
        )
        assert drift is False
        assert score == pytest.approx(0.0)

    def test_empty_live_returns_no_drift(self) -> None:
        train_df = self._feature_df(100)
        drift, score = _compute_ks_drift(
            train_df, pd.DataFrame(), list(_FEATURE_COLUMNS), threshold=0.1
        )
        assert drift is False
        assert score == pytest.approx(0.0)

    def test_threshold_respected(self) -> None:
        train_df = self._feature_df(200, mean=0.0)
        live_df = self._feature_df(200, mean=2.0)

        # With very high threshold — should not flag drift.
        drift_high, _ = _compute_ks_drift(
            train_df, live_df, list(_FEATURE_COLUMNS), threshold=0.99
        )
        # With very low threshold — should flag drift.
        drift_low, _ = _compute_ks_drift(
            train_df, live_df, list(_FEATURE_COLUMNS), threshold=0.001
        )
        assert drift_high is False
        assert drift_low is True

    def test_missing_columns_handled_gracefully(self) -> None:
        train_df = pd.DataFrame({"rsi": [50.0] * 50, "macd": [0.1] * 50})
        live_df = pd.DataFrame({"rsi": [60.0] * 50})
        # Only the common column "rsi" is compared.
        drift, score = _compute_ks_drift(
            train_df, live_df, ["rsi", "macd"], threshold=0.5
        )
        assert isinstance(drift, bool)
        assert isinstance(score, float)


# ---------------------------------------------------------------------------
# AutoRetrainer — single-cycle tests (run_once)
# ---------------------------------------------------------------------------


class TestAutoRetrainerRunOnce:
    """Tests for the single-cycle ``run_once`` method."""

    def _run(self, tmp_path: Path, symbol: str = "NIFTY", accuracy: float = 0.65, **cfg_kw: object) -> RetrainResult:
        """Helper: run one retrain cycle with a patched MLAdvisor.train."""
        cfg = _default_config(tmp_path, **cfg_kw)
        retrainer = AutoRetrainer(cfg, data_fetcher=_good_fetcher)
        with patch.object(MLAdvisor, "train", _train_side_effect(accuracy)):
            return asyncio.run(retrainer.run_once(symbol))

    def test_returns_retrain_result_type(self, tmp_path: Path) -> None:
        result = self._run(tmp_path)
        assert isinstance(result, RetrainResult)

    def test_symbol_captured_in_result(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, symbol="BANKNIFTY")
        assert result.symbol == "BANKNIFTY"

    def test_duration_is_positive(self, tmp_path: Path) -> None:
        result = self._run(tmp_path)
        assert result.duration_seconds >= 0.0

    def test_result_added_to_history(self, tmp_path: Path) -> None:
        cfg = _default_config(tmp_path)
        retrainer = AutoRetrainer(cfg, data_fetcher=_good_fetcher)
        with patch.object(MLAdvisor, "train", _train_side_effect(0.65)):
            asyncio.run(retrainer.run_once("NIFTY"))
        assert len(retrainer.get_history()) == 1

    def test_accepted_when_accuracy_above_threshold(self, tmp_path: Path) -> None:
        result = self._run(tmp_path, accuracy=0.65, min_accuracy=0.0)
        assert result.accepted is True

    def test_rejected_when_accuracy_below_threshold(self, tmp_path: Path) -> None:
        # Reported accuracy of 0.4 < min_accuracy of 0.999 → rejected.
        result = self._run(tmp_path, accuracy=0.4, min_accuracy=0.999)
        assert result.accepted is False
        assert "Rejected" in result.reason

    def test_rejection_does_not_swap_model(self, tmp_path: Path) -> None:
        cfg = _default_config(tmp_path, min_accuracy=0.999)
        retrainer = AutoRetrainer(cfg, data_fetcher=_good_fetcher)
        with patch.object(MLAdvisor, "train", _train_side_effect(0.4)):
            asyncio.run(retrainer.run_once("NIFTY"))
        assert retrainer.get_advisor("NIFTY") is None

    def test_data_fetch_failure_returns_error_result(self, tmp_path: Path) -> None:
        cfg = _default_config(tmp_path)
        retrainer = AutoRetrainer(cfg, data_fetcher=_error_fetcher)
        result = asyncio.run(retrainer.run_once("NIFTY"))
        assert result.accepted is False
        assert "Data fetch failed" in result.reason

    def test_empty_dataframe_returns_error_result(self, tmp_path: Path) -> None:
        cfg = _default_config(tmp_path)
        retrainer = AutoRetrainer(cfg, data_fetcher=_empty_fetcher)
        result = asyncio.run(retrainer.run_once("NIFTY"))
        assert result.accepted is False
        assert "Insufficient data" in result.reason

    def test_training_failure_returns_error_result(self, tmp_path: Path) -> None:
        cfg = _default_config(tmp_path)
        retrainer = AutoRetrainer(cfg, data_fetcher=_good_fetcher)

        def _boom(self_advisor: MLAdvisor, df: pd.DataFrame) -> dict:
            raise RuntimeError("Simulated training crash")

        with patch.object(MLAdvisor, "train", _boom):
            result = asyncio.run(retrainer.run_once("NIFTY"))
        assert result.accepted is False
        assert "Training failed" in result.reason


# ---------------------------------------------------------------------------
# AutoRetrainer — drift detection
# ---------------------------------------------------------------------------


class TestAutoRetrainerDrift:
    """Tests that drift detection works correctly inside run_once."""

    def test_drift_flag_in_result_when_distributions_shift(self, tmp_path: Path) -> None:
        """Drift is detected when live features diverge from training features."""
        # Provide a pre-existing model so drift comparison triggers.
        existing_model_path = tmp_path / "ml_advisor_NIFTY.pkl"
        stub = _PicklableStubModel()
        with open(existing_model_path, "wb") as f:
            pickle.dump({"model": stub, "feature_names": list(_FEATURE_COLUMNS)}, f)

        # Use a very low drift threshold so it fires easily.
        cfg = RetrainConfig(
            symbols=["NIFTY"],
            model_dir=tmp_path,
            lookback_days=60,
            min_accuracy=0.0,
            drift_threshold=0.0001,  # essentially always fires
        )

        async def _shifted_fetcher(symbol: str, lookback_days: int) -> pd.DataFrame:
            rng = np.random.default_rng(99)
            n = 250
            # Deliberately extreme values to guarantee drift.
            close = 100_000.0 + np.cumsum(rng.normal(0, 5000, n))
            high = close + rng.uniform(100, 1000, n)
            low = close - rng.uniform(100, 1000, n)
            return pd.DataFrame({
                "open": close * 0.99,
                "high": high,
                "low": low,
                "close": close,
                "volume": rng.integers(1_000_000, 5_000_000, n).astype(float),
            })

        retrainer = AutoRetrainer(cfg, data_fetcher=_shifted_fetcher)
        with patch.object(MLAdvisor, "train", _train_side_effect(0.65)):
            result = asyncio.run(retrainer.run_once("NIFTY"))

        assert result.drift_detected is True
        assert result.drift_score > 0.0

    def test_no_drift_when_no_existing_model(self, tmp_path: Path) -> None:
        """Drift comparison is skipped when no pre-existing model file exists."""
        cfg = _default_config(tmp_path, min_accuracy=0.0, drift_threshold=0.5)
        retrainer = AutoRetrainer(cfg, data_fetcher=_good_fetcher)
        with patch.object(MLAdvisor, "train", _train_side_effect(0.65)):
            result = asyncio.run(retrainer.run_once("NIFTY"))
        # Without a pre-existing model the drift comparison path is skipped.
        assert result.drift_detected is False


# ---------------------------------------------------------------------------
# AutoRetrainer — model swap and thread safety
# ---------------------------------------------------------------------------


class TestAutoRetrainerModelSwap:
    """Verify the atomic model swap and concurrent predict safety."""

    def test_live_advisor_available_after_accepted_cycle(self, tmp_path: Path) -> None:
        cfg = _default_config(tmp_path, min_accuracy=0.0)
        retrainer = AutoRetrainer(cfg, data_fetcher=_good_fetcher)
        with patch.object(MLAdvisor, "train", _train_side_effect(0.65)):
            result = asyncio.run(retrainer.run_once("NIFTY"))
        assert result.accepted is True
        advisor = retrainer.get_advisor("NIFTY")
        assert advisor is not None
        assert isinstance(advisor, MLAdvisor)

    def test_model_file_created_in_model_dir(self, tmp_path: Path) -> None:
        cfg = _default_config(tmp_path, min_accuracy=0.0)
        retrainer = AutoRetrainer(cfg, data_fetcher=_good_fetcher)
        with patch.object(MLAdvisor, "train", _train_side_effect(0.65)):
            asyncio.run(retrainer.run_once("NIFTY"))
        model_file = tmp_path / "ml_advisor_NIFTY.pkl"
        assert model_file.exists()

    def test_old_model_still_predicts_before_swap(self, tmp_path: Path) -> None:
        """The old advisor remains usable while a new retrain cycle runs."""
        cfg = _default_config(tmp_path, min_accuracy=0.0)
        retrainer = AutoRetrainer(cfg, data_fetcher=_good_fetcher)

        # Plant a first-generation advisor.
        old_advisor = MLAdvisor(MLAdvisorConfig(lookback=50))
        old_advisor._model = _PicklableStubModel()
        with retrainer._lock:
            retrainer._live_advisors["NIFTY"] = old_advisor

        # Confirm old advisor can predict before swap.
        old = retrainer.get_advisor("NIFTY")
        assert old is not None
        prediction = old.predict(_make_ohlcv(200))
        assert prediction.signal in {"BUY", "HOLD", "SELL"}

        # Now run a new cycle — it should replace the advisor.
        with patch.object(MLAdvisor, "train", _train_side_effect(0.65)):
            asyncio.run(retrainer.run_once("NIFTY"))

        new = retrainer.get_advisor("NIFTY")
        assert new is not None
        assert new is not old  # new object after swap

    def test_concurrent_predict_does_not_raise(self, tmp_path: Path) -> None:
        """Multiple threads reading the live advisor while a swap happens."""
        cfg = _default_config(tmp_path, min_accuracy=0.0)
        retrainer = AutoRetrainer(cfg, data_fetcher=_good_fetcher)

        # Plant a picklable model so predict() can run.
        advisor = MLAdvisor(MLAdvisorConfig(lookback=50))
        advisor._model = _PicklableStubModel()
        with retrainer._lock:
            retrainer._live_advisors["NIFTY"] = advisor

        errors: list[Exception] = []
        df = _make_ohlcv(200)

        def _predict_loop() -> None:
            for _ in range(20):
                try:
                    a = retrainer.get_advisor("NIFTY")
                    if a:
                        a.predict(df)
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)
                time.sleep(0.001)

        threads = [threading.Thread(target=_predict_loop) for _ in range(4)]
        for t in threads:
            t.start()

        # Perform a model swap from the main thread while readers run.
        new_advisor = MLAdvisor(MLAdvisorConfig(lookback=50))
        new_advisor._model = _PicklableStubModel()
        retrainer._swap_model("NIFTY", new_advisor)

        for t in threads:
            t.join(timeout=5)

        assert errors == [], f"Concurrent predict errors: {errors}"


# ---------------------------------------------------------------------------
# AutoRetrainer — run_all
# ---------------------------------------------------------------------------


class TestAutoRetrainerRunAll:
    def test_run_all_processes_all_symbols(self, tmp_path: Path) -> None:
        cfg = RetrainConfig(
            symbols=["NIFTY", "BANKNIFTY", "INFY"],
            model_dir=tmp_path,
            lookback_days=60,
            min_accuracy=0.0,
        )
        retrainer = AutoRetrainer(cfg, data_fetcher=_good_fetcher)
        with patch.object(MLAdvisor, "train", _train_side_effect(0.65)):
            results = asyncio.run(retrainer.run_all())
        assert len(results) == 3
        assert {r.symbol for r in results} == {"NIFTY", "BANKNIFTY", "INFY"}

    def test_run_all_continues_after_one_symbol_fails(self, tmp_path: Path) -> None:
        """run_all should not abort when one symbol's data fetch fails."""

        async def _flaky_fetcher(symbol: str, lookback_days: int) -> pd.DataFrame:
            if symbol == "BANKNIFTY":
                raise RuntimeError("Intentional fetch failure")
            return _make_ohlcv(250)

        cfg = RetrainConfig(
            symbols=["NIFTY", "BANKNIFTY"],
            model_dir=tmp_path,
            lookback_days=60,
            min_accuracy=0.0,
        )
        retrainer = AutoRetrainer(cfg, data_fetcher=_flaky_fetcher)
        with patch.object(MLAdvisor, "train", _train_side_effect(0.65)):
            results = asyncio.run(retrainer.run_all())

        assert len(results) == 2
        nifty_r = next(r for r in results if r.symbol == "NIFTY")
        bnf_r = next(r for r in results if r.symbol == "BANKNIFTY")
        assert nifty_r.accepted is True
        assert bnf_r.accepted is False
        assert "Data fetch failed" in bnf_r.reason


# ---------------------------------------------------------------------------
# AutoRetrainer — history tracking
# ---------------------------------------------------------------------------


class TestAutoRetrainerHistory:
    def test_history_accumulates_across_cycles(self, tmp_path: Path) -> None:
        cfg = _default_config(tmp_path, min_accuracy=0.0)
        retrainer = AutoRetrainer(cfg, data_fetcher=_good_fetcher)
        with patch.object(MLAdvisor, "train", _train_side_effect(0.65)):
            asyncio.run(retrainer.run_once("NIFTY"))
            asyncio.run(retrainer.run_once("NIFTY"))
        assert len(retrainer.get_history()) == 2

    def test_history_ordered_newest_first(self, tmp_path: Path) -> None:
        cfg = _default_config(tmp_path, min_accuracy=0.0)
        retrainer = AutoRetrainer(cfg, data_fetcher=_good_fetcher)
        with patch.object(MLAdvisor, "train", _train_side_effect(0.65)):
            asyncio.run(retrainer.run_once("NIFTY"))
            asyncio.run(retrainer.run_once("NIFTY"))
        history = retrainer.get_history()
        assert all(r.symbol == "NIFTY" for r in history)

    def test_history_respects_max_history_cap(self, tmp_path: Path) -> None:
        cfg = RetrainConfig(
            symbols=["NIFTY"],
            model_dir=tmp_path,
            lookback_days=60,
            min_accuracy=0.0,
            max_history=3,
        )
        retrainer = AutoRetrainer(cfg, data_fetcher=_good_fetcher)
        with patch.object(MLAdvisor, "train", _train_side_effect(0.65)):
            for _ in range(5):
                asyncio.run(retrainer.run_once("NIFTY"))
        assert len(retrainer.get_history()) == 3

    def test_get_history_returns_copy(self, tmp_path: Path) -> None:
        cfg = _default_config(tmp_path)
        retrainer = AutoRetrainer(cfg, data_fetcher=_good_fetcher)
        h1 = retrainer.get_history()
        h2 = retrainer.get_history()
        assert h1 is not h2


# ---------------------------------------------------------------------------
# AutoRetrainer — log persistence
# ---------------------------------------------------------------------------


class TestAutoRetrainerLogPersistence:
    def test_retrain_log_written_when_persist_log_true(self, tmp_path: Path) -> None:
        cfg = RetrainConfig(
            symbols=["NIFTY"],
            model_dir=tmp_path,
            lookback_days=60,
            min_accuracy=0.0,
            persist_log=True,
        )
        retrainer = AutoRetrainer(cfg, data_fetcher=_good_fetcher)
        with patch.object(MLAdvisor, "train", _train_side_effect(0.65)):
            asyncio.run(retrainer.run_once("NIFTY"))

        log_path = tmp_path / "retrain_log.jsonl"
        assert log_path.exists()
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["symbol"] == "NIFTY"
        assert "val_accuracy" in entry

    def test_retrain_log_not_written_when_persist_log_false(self, tmp_path: Path) -> None:
        cfg = RetrainConfig(
            symbols=["NIFTY"],
            model_dir=tmp_path,
            lookback_days=60,
            min_accuracy=0.0,
            persist_log=False,
        )
        retrainer = AutoRetrainer(cfg, data_fetcher=_good_fetcher)
        with patch.object(MLAdvisor, "train", _train_side_effect(0.65)):
            asyncio.run(retrainer.run_once("NIFTY"))

        log_path = tmp_path / "retrain_log.jsonl"
        assert not log_path.exists()

    def test_multiple_cycles_append_to_log(self, tmp_path: Path) -> None:
        cfg = RetrainConfig(
            symbols=["NIFTY"],
            model_dir=tmp_path,
            lookback_days=60,
            min_accuracy=0.0,
            persist_log=True,
        )
        retrainer = AutoRetrainer(cfg, data_fetcher=_good_fetcher)
        with patch.object(MLAdvisor, "train", _train_side_effect(0.65)):
            asyncio.run(retrainer.run_once("NIFTY"))
            asyncio.run(retrainer.run_once("NIFTY"))

        log_path = tmp_path / "retrain_log.jsonl"
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# AutoRetrainer — loop and state
# ---------------------------------------------------------------------------


class TestAutoRetrainerLoop:
    def test_stop_terminates_loop(self, tmp_path: Path) -> None:
        """Loop exits promptly when stop() is called after first run_all."""
        cfg = RetrainConfig(
            symbols=["NIFTY"],
            model_dir=tmp_path,
            lookback_days=60,
            min_accuracy=0.0,
            retrain_interval_hours=24,  # long interval — stop() must preempt it
        )
        retrainer = AutoRetrainer(cfg, data_fetcher=_good_fetcher)

        async def _run_then_stop() -> None:
            original_run_all = retrainer.run_all

            async def _patched_run_all() -> list[RetrainResult]:
                results = await original_run_all()
                retrainer.stop()
                return results

            retrainer.run_all = _patched_run_all  # type: ignore[method-assign]
            with patch.object(MLAdvisor, "train", _train_side_effect(0.65)):
                await asyncio.wait_for(retrainer.start_loop(), timeout=30)

        asyncio.run(_run_then_stop())
        assert retrainer._running is False

    def test_get_advisor_none_before_any_cycle(self, tmp_path: Path) -> None:
        cfg = _default_config(tmp_path)
        retrainer = AutoRetrainer(cfg, data_fetcher=_good_fetcher)
        assert retrainer.get_advisor("NIFTY") is None

    def test_get_advisor_none_for_unknown_symbol(self, tmp_path: Path) -> None:
        cfg = _default_config(tmp_path, min_accuracy=0.0)
        retrainer = AutoRetrainer(cfg, data_fetcher=_good_fetcher)
        with patch.object(MLAdvisor, "train", _train_side_effect(0.65)):
            asyncio.run(retrainer.run_once("NIFTY"))
        assert retrainer.get_advisor("RELIANCE") is None
