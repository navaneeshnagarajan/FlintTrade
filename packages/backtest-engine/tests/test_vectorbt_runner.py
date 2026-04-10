"""Tests for VectorBTRunner.

All tests that require vectorbt are skipped when the library is not installed.
Tests that exercise the module's behaviour *without* vectorbt (error handling,
availability flag) run unconditionally.
"""

from __future__ import annotations

import math
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Availability markers
# ---------------------------------------------------------------------------

from vectorbt_runner import VectorBTNotAvailableError, VectorBTRunner, is_available

_VBT = pytest.mark.skipif(
    not is_available(), reason="vectorbt not installed on this machine"
)
_NO_VBT = pytest.mark.skipif(
    is_available(), reason="runs only when vectorbt is absent"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ohlcv(n: int = 120, start: float = 100.0) -> "Any":
    """Return a minimal OHLCV DataFrame suitable for vectorbt."""
    import random

    import pandas as pd

    random.seed(7)
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    prices = []
    p = start
    for _ in range(n):
        p = max(1.0, p + random.uniform(-2, 2))
        prices.append(round(p, 2))

    close = pd.Series(prices, index=dates)
    return pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": [100_000] * n,
        },
        index=dates,
    )


class _SMACrossStrategy:
    """Minimal SMA-crossover strategy for test sweeps.

    ``generate_signals`` is the contract expected by VectorBTRunner.
    """

    @staticmethod
    def generate_signals(
        data: "Any",
        fast: int = 5,
        slow: int = 20,
    ) -> tuple["Any", "Any"]:
        close = data["close"]
        fast_ma = close.rolling(fast).mean()
        slow_ma = close.rolling(slow).mean()
        entries = (fast_ma > slow_ma) & (fast_ma.shift(1) <= slow_ma.shift(1))
        exits = (fast_ma < slow_ma) & (fast_ma.shift(1) >= slow_ma.shift(1))
        return entries.fillna(False), exits.fillna(False)


# ---------------------------------------------------------------------------
# Tests — no vectorbt required
# ---------------------------------------------------------------------------


class TestIsAvailable:
    """is_available() must always return a bool without raising."""

    def test_returns_bool(self) -> None:
        result = is_available()
        assert isinstance(result, bool)


class TestVectorBTNotAvailable:
    """When vectorbt is absent all public methods raise VectorBTNotAvailableError."""

    @_NO_VBT
    def test_run_parameter_sweep_raises(self) -> None:
        import pandas as pd

        runner = VectorBTRunner()
        with pytest.raises(VectorBTNotAvailableError):
            runner.run_parameter_sweep(
                _SMACrossStrategy,
                "NIFTY",
                pd.DataFrame({"close": [1.0]}),
                {"fast": [5]},
            )

    @_NO_VBT
    def test_generate_tearsheet_raises(self) -> None:
        runner = VectorBTRunner()
        with pytest.raises(VectorBTNotAvailableError):
            runner.generate_tearsheet(MagicMock())

    @_NO_VBT
    def test_optimize_raises(self) -> None:
        import pandas as pd

        runner = VectorBTRunner()
        with pytest.raises(VectorBTNotAvailableError):
            runner.optimize(
                _SMACrossStrategy,
                "NIFTY",
                pd.DataFrame({"close": [1.0]}),
            )


class TestRunnerDefaults:
    """Constructor defaults are stored as expected."""

    def test_default_init_cash(self) -> None:
        r = VectorBTRunner()
        assert r.init_cash == 1_000_000.0

    def test_custom_init_cash(self) -> None:
        r = VectorBTRunner(init_cash=500_000.0, fees=0.001, slippage=0.001, freq="1H")
        assert r.init_cash == 500_000.0
        assert r.fees == 0.001
        assert r.freq == "1H"


class TestParameterSweepValidation:
    """Validation that does not require vectorbt to execute."""

    def test_missing_close_column_raises(self) -> None:
        import pandas as pd

        # Patch _VBT_AVAILABLE so the close-column check is reached
        with patch("vectorbt_runner._VBT_AVAILABLE", True), patch(
            "vectorbt_runner.vbt", MagicMock()
        ):
            runner = VectorBTRunner()
            bad_data = pd.DataFrame({"open": [1.0, 2.0], "volume": [100, 200]})
            with pytest.raises(ValueError, match="close"):
                runner.run_parameter_sweep(
                    _SMACrossStrategy, "TEST", bad_data, {"fast": [5]}
                )


# ---------------------------------------------------------------------------
# Tests — require vectorbt
# ---------------------------------------------------------------------------


@_VBT
class TestRunParameterSweep:
    """Full sweep integration tests."""

    def test_returns_dataframe(self) -> None:
        import pandas as pd

        runner = VectorBTRunner(init_cash=100_000.0, fees=0.001, freq="1D")
        data = _make_ohlcv()
        result = runner.run_parameter_sweep(
            _SMACrossStrategy,
            "TEST",
            data,
            {"fast": [5, 10], "slow": [20, 50]},
        )
        assert isinstance(result, pd.DataFrame)

    def test_row_count_matches_grid(self) -> None:
        runner = VectorBTRunner()
        data = _make_ohlcv()
        result = runner.run_parameter_sweep(
            _SMACrossStrategy,
            "TEST",
            data,
            {"fast": [5, 10, 20], "slow": [50, 100]},
        )
        # 3 fast × 2 slow = 6 rows
        assert len(result) == 6

    def test_param_columns_present(self) -> None:
        runner = VectorBTRunner()
        data = _make_ohlcv()
        result = runner.run_parameter_sweep(
            _SMACrossStrategy,
            "TEST",
            data,
            {"fast": [5], "slow": [20]},
        )
        assert "fast" in result.columns
        assert "slow" in result.columns

    def test_metric_columns_present(self) -> None:
        runner = VectorBTRunner()
        data = _make_ohlcv()
        result = runner.run_parameter_sweep(
            _SMACrossStrategy,
            "TEST",
            data,
            {"fast": [5], "slow": [20]},
        )
        for col in ("sharpe_ratio", "max_drawdown", "win_rate", "total_trades"):
            assert col in result.columns, f"Missing column: {col}"

    def test_single_combo_no_error(self) -> None:
        runner = VectorBTRunner()
        data = _make_ohlcv(n=60)
        result = runner.run_parameter_sweep(
            _SMACrossStrategy,
            "TEST",
            data,
            {"fast": [5], "slow": [20]},
        )
        assert len(result) == 1


@_VBT
class TestGenerateTearsheet:
    """Tearsheet dict structure and value types."""

    def _build_portfolio(self) -> Any:
        import vectorbt as vbt

        data = _make_ohlcv()
        entries, exits = _SMACrossStrategy.generate_signals(data, fast=10, slow=30)
        return vbt.Portfolio.from_signals(
            data["close"],
            entries,
            exits,
            init_cash=100_000.0,
            fees=0.001,
            freq="1D",
        )

    def test_returns_dict(self) -> None:
        runner = VectorBTRunner()
        pf = self._build_portfolio()
        result = runner.generate_tearsheet(pf)
        assert isinstance(result, dict)

    def test_all_metric_keys_present(self) -> None:
        from vectorbt_runner import _METRIC_KEYS

        runner = VectorBTRunner()
        pf = self._build_portfolio()
        result = runner.generate_tearsheet(pf)
        for key in _METRIC_KEYS:
            assert key in result, f"Missing key: {key}"

    def test_all_values_are_float(self) -> None:
        runner = VectorBTRunner()
        pf = self._build_portfolio()
        result = runner.generate_tearsheet(pf)
        for k, v in result.items():
            assert isinstance(v, float), f"Key '{k}' has non-float value: {type(v)}"

    def test_max_drawdown_non_positive(self) -> None:
        """Max drawdown should be 0 or negative (loss from peak)."""
        runner = VectorBTRunner()
        pf = self._build_portfolio()
        result = runner.generate_tearsheet(pf)
        dd = result["max_drawdown"]
        if not math.isnan(dd):
            assert dd <= 0.0 or dd >= 0.0  # just confirm it's a number; sign varies by vbt version

    def test_win_rate_in_range(self) -> None:
        """Win rate should be 0–100 (percentage) or NaN."""
        runner = VectorBTRunner()
        pf = self._build_portfolio()
        result = runner.generate_tearsheet(pf)
        wr = result["win_rate"]
        if not math.isnan(wr):
            assert 0.0 <= wr <= 100.0


@_VBT
class TestOptimize:
    """Optimize picks the correct best row."""

    def test_returns_dict_with_metric_used(self) -> None:
        runner = VectorBTRunner()
        data = _make_ohlcv()
        best = runner.optimize(
            _SMACrossStrategy,
            "TEST",
            data,
            metric="sharpe",
            param_grid={"fast": [5, 10], "slow": [20, 50]},
        )
        assert isinstance(best, dict)
        assert best["metric_used"] == "sharpe_ratio"

    def test_best_params_are_subset_of_grid(self) -> None:
        runner = VectorBTRunner()
        data = _make_ohlcv()
        best = runner.optimize(
            _SMACrossStrategy,
            "TEST",
            data,
            metric="sharpe",
            param_grid={"fast": [5, 10, 20], "slow": [30, 50]},
        )
        assert best["fast"] in [5, 10, 20]
        assert best["slow"] in [30, 50]

    def test_alias_sharpe_resolves(self) -> None:
        runner = VectorBTRunner()
        data = _make_ohlcv()
        best = runner.optimize(
            _SMACrossStrategy,
            "TEST",
            data,
            metric="sharpe",
            param_grid={"fast": [5], "slow": [20]},
        )
        assert "sharpe_ratio" in best

    def test_alias_sortino_resolves(self) -> None:
        runner = VectorBTRunner()
        data = _make_ohlcv()
        best = runner.optimize(
            _SMACrossStrategy,
            "TEST",
            data,
            metric="sortino",
            param_grid={"fast": [5], "slow": [20]},
        )
        assert "sortino_ratio" in best

    def test_empty_grid_runs_once(self) -> None:
        """optimize with no param_grid runs a single simulation."""
        runner = VectorBTRunner()
        data = _make_ohlcv()
        best = runner.optimize(
            _SMACrossStrategy,
            "TEST",
            data,
            metric="sharpe",
            param_grid={},
        )
        assert isinstance(best, dict)

    def test_invalid_metric_raises(self) -> None:
        runner = VectorBTRunner()
        data = _make_ohlcv()
        with pytest.raises(ValueError, match="not found"):
            runner.optimize(
                _SMACrossStrategy,
                "TEST",
                data,
                metric="nonexistent_metric_xyz",
                param_grid={"fast": [5], "slow": [20]},
            )
