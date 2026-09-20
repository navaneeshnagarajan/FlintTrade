"""Tests for the Optuna-based strategy hyperparameter optimiser."""

from __future__ import annotations


import pytest

from flinttrade_ai.hyperopt_strategy import (
    OptimisationResult,
    StrategyOptimiser,
    _accuracy_loss,
    _calmar_loss,
    _max_drawdown_loss,
    _sharpe_loss,
)


# ---------------------------------------------------------------------------
# Fixtures: synthetic bar data
# ---------------------------------------------------------------------------


def _make_bars(n: int = 200, base_price: float = 22000.0) -> list[dict]:
    """Generate synthetic OHLCV bars."""
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
# Tests: Loss functions
# ---------------------------------------------------------------------------


class TestLossFunctions:
    """Tests for the pluggable loss functions (from freqtrade pattern)."""

    def test_accuracy_loss_perfect(self) -> None:
        preds = [0, 1, 2, 0, 1]
        labels = [0, 1, 2, 0, 1]
        loss = _accuracy_loss(preds, labels, [100.0] * 10, 5)
        assert loss == pytest.approx(-1.0)

    def test_accuracy_loss_zero(self) -> None:
        preds = [2, 2, 2]
        labels = [0, 0, 0]
        loss = _accuracy_loss(preds, labels, [100.0] * 10, 5)
        assert loss == pytest.approx(0.0)

    def test_accuracy_loss_empty(self) -> None:
        assert _accuracy_loss([], [], [], 5) == 0.0

    def test_sharpe_loss_all_buy_uptrend(self) -> None:
        # All BUY predictions, prices go up monotonically
        preds = [2] * 10
        labels = [2] * 10
        closes = [100 + i * 2 for i in range(20)]
        loss = _sharpe_loss(preds, labels, closes, 5)
        assert loss < 0  # Negative Sharpe -> loss is < 0 (good)

    def test_sharpe_loss_all_hold(self) -> None:
        preds = [1] * 10
        labels = [1] * 10
        closes = [100 + i for i in range(20)]
        loss = _sharpe_loss(preds, labels, closes, 5)
        assert loss == 0.0  # HOLD => zero returns => zero Sharpe

    def test_calmar_loss_with_uptrend(self) -> None:
        preds = [2] * 10
        labels = [2] * 10
        closes = [100 + i * 2 for i in range(20)]
        loss = _calmar_loss(preds, labels, closes, 5)
        assert loss < 0  # Negative Calmar (good)

    def test_calmar_loss_empty(self) -> None:
        assert _calmar_loss([], [], [], 5) == 0.0

    def test_max_drawdown_loss_flat(self) -> None:
        preds = [1] * 10  # HOLD
        labels = [1] * 10
        closes = [100.0] * 20
        loss = _max_drawdown_loss(preds, labels, closes, 5)
        assert loss == pytest.approx(0.0)

    def test_max_drawdown_loss_losing_trades(self) -> None:
        # BUY predictions during a downtrend
        preds = [2] * 10
        labels = [0] * 10
        closes = [100 - i * 2 for i in range(20)]
        loss = _max_drawdown_loss(preds, labels, closes, 5)
        assert loss > 0  # Positive drawdown


# ---------------------------------------------------------------------------
# Tests: OptimisationResult
# ---------------------------------------------------------------------------


class TestOptimisationResult:
    """Tests for the OptimisationResult dataclass."""

    def test_defaults(self) -> None:
        r = OptimisationResult()
        assert r.best_params == {}
        assert r.best_score == 0.0
        assert r.best_generator is None
        assert r.n_trials == 0


# ---------------------------------------------------------------------------
# Tests: StrategyOptimiser
# ---------------------------------------------------------------------------


def _optuna_available() -> bool:
    try:
        import optuna  # noqa: F401
        return True
    except ImportError:
        return False


def _lightgbm_available() -> bool:
    try:
        import lightgbm  # noqa: F401
        return True
    except (ImportError, OSError):
        return False


class TestStrategyOptimiser:
    """Tests for the StrategyOptimiser class."""

    def test_seeded_tpe_preserves_independent_search_after_startup(self, monkeypatch) -> None:
        """The Optuna 5 upgrade retains the established sequential search."""
        pytest.importorskip("optuna")
        optimiser = StrategyOptimiser(bars=_make_bars(200), lookahead=3)
        monkeypatch.setattr(
            optimiser,
            "_evaluate",
            lambda params, loss_fn: (params["num_leaves"] - 40) ** 2 + (params["learning_rate"] - 0.1) ** 2,
        )
        monkeypatch.setattr(optimiser, "_train_final", lambda params: None)

        # Trials 0-9 use random startup sampling. These next two trials were
        # recorded with Optuna 4.9.0, seed 42 and the same synthetic objective;
        # checking only the first ten would miss the changed Optuna 5 defaults.
        expected = [
            {
                "num_leaves": 122,
                "learning_rate": 0.010206070557577017,
                "n_estimators": 216,
                "min_child_samples": 5,
                "subsample": 0.5105579858093708,
                "colsample_bytree": 0.7627332534279544,
                "reg_alpha": 4.3444691085504035,
                "reg_lambda": 0.01620963590242718,
            },
            {
                "num_leaves": 43,
                "learning_rate": 0.0552655524426594,
                "n_estimators": 227,
                "min_child_samples": 16,
                "subsample": 0.7628614131457857,
                "colsample_bytree": 0.9902698740804924,
                "reg_alpha": 9.393382777352836e-05,
                "reg_lambda": 7.3210985188372955e-06,
            },
        ]
        result = optimiser.optimise(n_trials=12, loss_fn="accuracy")

        assert result.n_trials == len(result.all_trials) == 12
        for (actual, _), prior in zip(result.all_trials[10:], expected, strict=True):
            assert actual == pytest.approx(prior)
        assert result.best_score == min(score for _, score in result.all_trials)

    def test_init_insufficient_bars(self) -> None:
        bars = _make_bars(10)
        optimiser = StrategyOptimiser(bars=bars)
        # Features will be empty but init should not raise
        assert optimiser._all_x == [] or len(optimiser._all_x) == 0

    @pytest.mark.skipif(
        not (_optuna_available() and _lightgbm_available()),
        reason="optuna and/or lightgbm not installed",
    )
    def test_optimise_sharpe(self) -> None:
        bars = _make_bars(200)
        optimiser = StrategyOptimiser(bars=bars, lookahead=3)
        result = optimiser.optimise(n_trials=5, loss_fn="sharpe")
        assert isinstance(result, OptimisationResult)
        assert result.n_trials == 5
        assert result.best_params  # Should have params
        assert result.loss_fn_name == "sharpe"

    @pytest.mark.skipif(
        not (_optuna_available() and _lightgbm_available()),
        reason="optuna and/or lightgbm not installed",
    )
    def test_optimise_accuracy(self) -> None:
        bars = _make_bars(200)
        optimiser = StrategyOptimiser(bars=bars, lookahead=3)
        result = optimiser.optimise(n_trials=3, loss_fn="accuracy")
        assert result.loss_fn_name == "accuracy"

    @pytest.mark.skipif(
        not (_optuna_available() and _lightgbm_available()),
        reason="optuna and/or lightgbm not installed",
    )
    def test_optimise_calmar(self) -> None:
        bars = _make_bars(200)
        optimiser = StrategyOptimiser(bars=bars, lookahead=3)
        result = optimiser.optimise(n_trials=3, loss_fn="calmar")
        assert result.loss_fn_name == "calmar"

    @pytest.mark.skipif(
        not (_optuna_available() and _lightgbm_available()),
        reason="optuna and/or lightgbm not installed",
    )
    def test_optimise_max_drawdown(self) -> None:
        bars = _make_bars(200)
        optimiser = StrategyOptimiser(bars=bars, lookahead=3)
        result = optimiser.optimise(n_trials=3, loss_fn="max_drawdown")
        assert result.loss_fn_name == "max_drawdown"

    def test_invalid_loss_fn(self) -> None:
        bars = _make_bars(200)
        optimiser = StrategyOptimiser(bars=bars)
        with pytest.raises((ValueError, ImportError)):
            optimiser.optimise(n_trials=1, loss_fn="nonexistent")

    @pytest.mark.skipif(
        not (_optuna_available() and _lightgbm_available()),
        reason="optuna and/or lightgbm not installed",
    )
    def test_custom_loss_fn(self) -> None:
        bars = _make_bars(200)
        optimiser = StrategyOptimiser(bars=bars, lookahead=3)

        def custom(preds, labels, closes, lookahead):
            # Dumb loss: just count non-HOLD predictions
            return sum(1 for p in preds if p != 1)

        result = optimiser.optimise(
            n_trials=3,
            loss_fn="accuracy",
            custom_loss_fn=custom,
        )
        assert result.n_trials == 3

    @pytest.mark.skipif(
        not (_optuna_available() and _lightgbm_available()),
        reason="optuna and/or lightgbm not installed",
    )
    def test_best_generator_is_trained(self) -> None:
        bars = _make_bars(200)
        optimiser = StrategyOptimiser(bars=bars, lookahead=3)
        result = optimiser.optimise(n_trials=3, loss_fn="accuracy")
        if result.best_generator is not None:
            assert result.best_generator.is_trained
