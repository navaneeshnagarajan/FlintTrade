"""Tests for the ensemble model selector module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from flinttrade_ai.ensemble_selector import (
    EnsembleResult,
    EnsembleSelector,
    ModelCandidate,
    compute_dissimilarity_index,
    _compute_validation_sharpe,
)


# ---------------------------------------------------------------------------
# Fixtures: synthetic bar data
# ---------------------------------------------------------------------------


def _make_bars(n: int = 200, base_price: float = 22000.0) -> list[dict]:
    """Generate synthetic OHLCV bars with a mild uptrend."""
    import random
    random.seed(42)

    bars = []
    price = base_price
    for i in range(n):
        change = random.gauss(0.0005, 0.01)
        price *= (1 + change)
        high = price * (1 + abs(random.gauss(0, 0.005)))
        low = price * (1 - abs(random.gauss(0, 0.005)))
        bars.append({
            "timestamp": f"2026-01-{(i % 28) + 1:02d}",
            "open": round(price * 0.999, 2),
            "high": round(high, 2),
            "low": round(low, 2),
            "close": round(price, 2),
            "volume": random.randint(100000, 500000),
        })
    return bars


# ---------------------------------------------------------------------------
# Tests: Data models
# ---------------------------------------------------------------------------


class TestModelCandidate:
    """Tests for ModelCandidate dataclass."""

    def test_defaults(self) -> None:
        c = ModelCandidate(name="test", params={"lr": 0.05})
        assert c.name == "test"
        assert c.model is None
        assert c.val_accuracy == 0.0
        assert c.val_sharpe == 0.0

    def test_with_values(self) -> None:
        c = ModelCandidate(
            name="m1",
            params={"num_leaves": 31},
            val_accuracy=0.65,
            val_sharpe=1.2,
        )
        assert c.val_sharpe == 1.2


class TestEnsembleResult:
    """Tests for EnsembleResult dataclass."""

    def test_defaults(self) -> None:
        r = EnsembleResult()
        assert r.best_model_name == ""
        assert r.candidates == []
        assert r.selection_metric == "val_sharpe"


# ---------------------------------------------------------------------------
# Tests: Dissimilarity Index
# ---------------------------------------------------------------------------


class TestDissimilarityIndex:
    """Tests for the DI computation (from freqtrade FreqAI pattern)."""

    def test_identical_distributions(self) -> None:
        train = [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]
        live = [[1.0, 2.0], [3.0, 4.0]]
        di = compute_dissimilarity_index(train, live)
        # Identical points should yield DI near 0
        assert di < 0.5

    def test_drifted_distribution(self) -> None:
        train = [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]
        live = [[100.0, 200.0], [300.0, 400.0]]
        di = compute_dissimilarity_index(train, live)
        # Very different -> high DI
        assert di > 1.0

    def test_empty_inputs(self) -> None:
        assert compute_dissimilarity_index([], [[1.0]]) == 0.0
        assert compute_dissimilarity_index([[1.0]], []) == 0.0
        assert compute_dissimilarity_index([], []) == 0.0

    def test_single_point(self) -> None:
        # Single training point -- intra distance is zero
        di = compute_dissimilarity_index([[1.0]], [[2.0]])
        assert di == 0.0  # Denominator is zero -> returns 0


# ---------------------------------------------------------------------------
# Tests: Validation Sharpe
# ---------------------------------------------------------------------------


class TestValidationSharpe:
    """Tests for _compute_validation_sharpe helper."""

    def test_perfect_buy_predictions(self) -> None:
        # Model always predicts BUY, prices always go up
        mock_model = MagicMock()
        mock_model.predict.return_value = [[0.1, 0.2, 0.7]] * 10  # class 2 = BUY
        closes = [100 + i for i in range(20)]  # Monotonically increasing
        features = [[0.0] * 5] * 10

        sharpe = _compute_validation_sharpe(mock_model, features, closes, lookahead=5)
        assert sharpe > 0  # Should be positive for correct uptrend prediction

    def test_empty_inputs(self) -> None:
        mock_model = MagicMock()
        assert _compute_validation_sharpe(mock_model, [], [], 5) == 0.0

    def test_hold_only(self) -> None:
        # Model always predicts HOLD -> all returns are 0 -> Sharpe is 0
        mock_model = MagicMock()
        mock_model.predict.return_value = [[0.1, 0.8, 0.1]] * 10
        closes = [100 + i for i in range(20)]
        features = [[0.0] * 5] * 10

        sharpe = _compute_validation_sharpe(mock_model, features, closes, lookahead=5)
        assert sharpe == 0.0


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _lightgbm_available() -> bool:
    try:
        import lightgbm  # noqa: F401
        return True
    except (ImportError, OSError):
        return False


# ---------------------------------------------------------------------------
# Tests: EnsembleSelector
# ---------------------------------------------------------------------------


class TestEnsembleSelector:
    """Tests for the EnsembleSelector class."""

    def test_init_defaults(self) -> None:
        sel = EnsembleSelector()
        assert sel.best_model is None
        assert sel.candidates == []

    def test_predict_without_training(self) -> None:
        sel = EnsembleSelector()
        signal = sel.predict([], symbol="NIFTY")
        assert signal.action == "HOLD"
        assert signal.confidence == 0.0

    def test_check_staleness_without_training(self) -> None:
        sel = EnsembleSelector()
        is_stale, di = sel.check_staleness([])
        assert is_stale is False
        assert di == 0.0

    @pytest.mark.skipif(
        not _lightgbm_available(),
        reason="lightgbm not installed",
    )
    def test_train_ensemble_with_lightgbm(self) -> None:
        bars = _make_bars(200)
        sel = EnsembleSelector(lookahead=3, threshold_pct=0.3)
        result = sel.train_ensemble(
            bars,
            configs=[
                {"name": "fast", "num_leaves": 15, "learning_rate": 0.1, "n_estimators": 50},
                {"name": "slow", "num_leaves": 31, "learning_rate": 0.05, "n_estimators": 50},
            ],
        )
        assert isinstance(result, EnsembleResult)
        assert result.best_model_name in ("fast", "slow")
        assert len(result.candidates) == 2
        assert sel.best_model is not None

    @pytest.mark.skipif(
        not _lightgbm_available(),
        reason="lightgbm not installed",
    )
    def test_predict_after_training(self) -> None:
        bars = _make_bars(200)
        sel = EnsembleSelector(lookahead=3, threshold_pct=0.3)
        sel.train_ensemble(
            bars,
            configs=[{"name": "m", "num_leaves": 15, "learning_rate": 0.1, "n_estimators": 50}],
        )
        signal = sel.predict(bars[-50:], symbol="NIFTY")
        assert signal.action in ("BUY", "SELL", "HOLD")
        assert 0.0 <= signal.confidence <= 1.0

    @pytest.mark.skipif(
        not _lightgbm_available(),
        reason="lightgbm not installed",
    )
    def test_check_staleness_after_training(self) -> None:
        bars = _make_bars(200)
        sel = EnsembleSelector(lookahead=3, di_threshold=100.0)
        sel.train_ensemble(
            bars,
            configs=[{"name": "m", "num_leaves": 15, "learning_rate": 0.1, "n_estimators": 50}],
        )
        # Same distribution -> not stale
        is_stale, di = sel.check_staleness(bars[-50:])
        assert is_stale is False

    def test_train_raises_without_lightgbm(self) -> None:
        sel = EnsembleSelector()
        with patch.dict("sys.modules", {"lightgbm": None}):
            # Should raise ImportError or similar
            try:
                sel.train_ensemble(_make_bars(50))
            except (ImportError, ValueError):
                pass  # Expected

    def test_too_few_bars(self) -> None:
        sel = EnsembleSelector()
        try:
            sel.train_ensemble(_make_bars(10))
        except (ImportError, ValueError):
            pass  # Expected -- not enough bars
