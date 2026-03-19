"""VectorBT integration for parameter sweeps, tearsheets, and optimization.

Wraps vectorbt's portfolio simulation behind a clean interface so the rest of
backtest-engine can use it without a hard dependency.  If vectorbt is not
installed the module still imports cleanly — callers receive a clear
``VectorBTNotAvailableError`` at call time rather than an ``ImportError`` at
import time.

Typical usage::

    runner = VectorBTRunner()
    results = runner.run_parameter_sweep(
        MyStrategy,
        symbol="NIFTY",
        data=ohlcv_df,
        param_grid={"fast": [5, 10, 20], "slow": [50, 100, 200]},
    )
    best = runner.optimize(MyStrategy, symbol="NIFTY", data=ohlcv_df, metric="sharpe")
"""

from __future__ import annotations

import itertools
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger("flinttrade.backtest.vectorbt")

# ---------------------------------------------------------------------------
# Optional vectorbt import
# ---------------------------------------------------------------------------

try:
    import vectorbt as vbt  # type: ignore[import-untyped]

    _VBT_AVAILABLE = True
except ImportError:
    vbt = None  # type: ignore[assignment]
    _VBT_AVAILABLE = False


class VectorBTNotAvailableError(RuntimeError):
    """Raised when vectorbt is not installed on this machine."""


# ---------------------------------------------------------------------------
# Tearsheet metric keys returned by generate_tearsheet
# ---------------------------------------------------------------------------

_METRIC_KEYS = (
    "total_return",
    "annualized_return",
    "sharpe_ratio",
    "sortino_ratio",
    "calmar_ratio",
    "max_drawdown",
    "win_rate",
    "profit_factor",
    "avg_winning_trade",
    "avg_losing_trade",
    "total_trades",
    "expectancy",
)


# ---------------------------------------------------------------------------
# VectorBTRunner
# ---------------------------------------------------------------------------


class VectorBTRunner:
    """High-level wrapper around vectorbt for strategy research.

    All heavy computation is delegated to vectorbt; this class only handles
    the interface contract expected by the rest of the backtest-engine package.

    Args:
        init_cash: Starting capital for each simulated portfolio.
        fees: Per-trade fee fraction (e.g. 0.001 = 0.1%).
        slippage: Per-trade slippage fraction applied to fill price.
        freq: Pandas frequency string for annualisation (e.g. ``"1D"``).
    """

    def __init__(
        self,
        init_cash: float = 1_000_000.0,
        fees: float = 0.0002,
        slippage: float = 0.0005,
        freq: str = "1D",
    ) -> None:
        self.init_cash = init_cash
        self.fees = fees
        self.slippage = slippage
        self.freq = freq

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_parameter_sweep(
        self,
        strategy_class: type,
        symbol: str,
        data: "pd.DataFrame",
        param_grid: dict[str, list[Any]],
    ) -> "pd.DataFrame":
        """Run a full Cartesian-product parameter sweep using vectorbt.

        Each parameter combination is evaluated in a single vectorbt
        portfolio simulation.  Results are returned as a DataFrame with one
        row per combination and columns for every metric key plus the
        parameter values.

        Args:
            strategy_class: A class with a ``generate_signals(data, **params)``
                static/class method that returns a tuple of
                ``(entries, exits)`` boolean Series/arrays.
            symbol: Instrument symbol string (used for logging only).
            data: OHLCV DataFrame.  Must contain at least a ``"close"``
                column.  Index should be a DatetimeIndex.
            param_grid: Dict mapping param name → list of candidate values.
                All combinations are evaluated (Cartesian product).

        Returns:
            DataFrame with columns: all param names + all metric keys.

        Raises:
            VectorBTNotAvailableError: If vectorbt is not installed.
            ValueError: If ``data`` does not contain a ``"close"`` column.
        """
        _require_vbt()
        import pandas as pd

        if "close" not in data.columns:
            raise ValueError("data must contain a 'close' column")

        close = data["close"]
        keys = list(param_grid.keys())
        combos = list(itertools.product(*[param_grid[k] for k in keys]))

        rows: list[dict[str, Any]] = []
        for combo in combos:
            params = dict(zip(keys, combo))
            try:
                entries, exits = strategy_class.generate_signals(data, **params)
                pf = vbt.Portfolio.from_signals(
                    close,
                    entries,
                    exits,
                    init_cash=self.init_cash,
                    fees=self.fees,
                    slippage=self.slippage,
                    freq=self.freq,
                )
                metrics = self.generate_tearsheet(pf)
                row: dict[str, Any] = {**params, **metrics}
            except Exception as exc:
                logger.warning(
                    "Sweep combo %s failed for %s: %s", params, symbol, exc
                )
                row = {**params, **{k: float("nan") for k in _METRIC_KEYS}}
            rows.append(row)

        result = pd.DataFrame(rows)
        logger.info(
            "Parameter sweep complete: %s — %d combos, %d successful",
            symbol,
            len(combos),
            result.dropna(subset=["sharpe_ratio"]).shape[0],
        )
        return result

    def generate_tearsheet(self, portfolio: Any) -> dict[str, float]:
        """Extract a standardised performance metrics dict from a vbt Portfolio.

        Args:
            portfolio: A ``vectorbt.Portfolio`` instance (already simulated).

        Returns:
            Dict with keys matching ``_METRIC_KEYS``.  Any metric that cannot
            be computed for this portfolio is stored as ``float("nan")``.

        Raises:
            VectorBTNotAvailableError: If vectorbt is not installed.
        """
        _require_vbt()

        def _safe(fn: Any) -> float:
            try:
                val = fn()
                if val is None:
                    return float("nan")
                return float(val)
            except Exception:
                return float("nan")

        stats = portfolio.stats()

        # vectorbt stats() returns a Series — build a name→value lookup
        stats_map: dict[str, Any] = {}
        if hasattr(stats, "to_dict"):
            stats_map = stats.to_dict()

        def _stat(key: str) -> float:
            """Case-insensitive substring search in stats Series index."""
            key_lower = key.lower()
            for k, v in stats_map.items():
                if key_lower in str(k).lower():
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        return float("nan")
            return float("nan")

        trades = portfolio.trades
        total_trades = _safe(lambda: len(trades.records_readable))
        win_count = _safe(
            lambda: (trades.records_readable["PnL"] > 0).sum()
        )
        loss_count = _safe(
            lambda: (trades.records_readable["PnL"] < 0).sum()
        )
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else float("nan")

        avg_win = _safe(
            lambda: trades.records_readable.loc[
                trades.records_readable["PnL"] > 0, "PnL"
            ].mean()
        )
        avg_loss = _safe(
            lambda: trades.records_readable.loc[
                trades.records_readable["PnL"] < 0, "PnL"
            ].mean()
        )

        gross_profit = _safe(
            lambda: trades.records_readable.loc[
                trades.records_readable["PnL"] > 0, "PnL"
            ].sum()
        )
        gross_loss_abs = _safe(
            lambda: abs(
                trades.records_readable.loc[
                    trades.records_readable["PnL"] < 0, "PnL"
                ].sum()
            )
        )
        profit_factor = (
            gross_profit / gross_loss_abs
            if gross_loss_abs > 0
            else float("nan")
        )

        expectancy = (
            (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss)
            if not (
                _isnan(win_rate) or _isnan(avg_win) or _isnan(avg_loss)
            )
            else float("nan")
        )

        return {
            "total_return": _stat("total return"),
            "annualized_return": _stat("annualized return"),
            "sharpe_ratio": _stat("sharpe"),
            "sortino_ratio": _stat("sortino"),
            "calmar_ratio": _stat("calmar"),
            "max_drawdown": _stat("max drawdown"),
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "avg_winning_trade": avg_win,
            "avg_losing_trade": avg_loss,
            "total_trades": total_trades,
            "expectancy": expectancy,
        }

    def optimize(
        self,
        strategy_class: type,
        symbol: str,
        data: "pd.DataFrame",
        metric: str = "sharpe",
        param_grid: dict[str, list[Any]] | None = None,
    ) -> dict[str, Any]:
        """Find the parameter combination that maximises *metric*.

        Runs ``run_parameter_sweep`` internally and returns the row with the
        highest value for *metric*.

        Args:
            strategy_class: Strategy class — same contract as
                ``run_parameter_sweep``.
            symbol: Instrument symbol (for logging).
            data: OHLCV DataFrame with ``"close"`` column.
            metric: Column name to maximise.  Must be one of the keys
                returned by ``generate_tearsheet`` (e.g. ``"sharpe_ratio"``,
                ``"sortino_ratio"``, ``"total_return"``).  Convenience
                aliases ``"sharpe"`` → ``"sharpe_ratio"`` and
                ``"sortino"`` → ``"sortino_ratio"`` are also accepted.
            param_grid: Parameter search space.  Defaults to an empty grid
                (single run with no parameters).

        Returns:
            Dict with the best parameter values and their metric scores.
            Keys: all param names + all metric keys + ``"metric_used"``.

        Raises:
            VectorBTNotAvailableError: If vectorbt is not installed.
            ValueError: If ``metric`` column is not present in sweep results
                or all rows have NaN for that metric.
        """
        _require_vbt()
        import pandas as pd

        # Resolve convenience aliases
        _aliases: dict[str, str] = {
            "sharpe": "sharpe_ratio",
            "sortino": "sortino_ratio",
            "calmar": "calmar_ratio",
            "return": "total_return",
            "drawdown": "max_drawdown",
        }
        resolved = _aliases.get(metric, metric)

        grid = param_grid or {}
        sweep = self.run_parameter_sweep(strategy_class, symbol, data, grid)

        if resolved not in sweep.columns:
            raise ValueError(
                f"Metric '{resolved}' not found in sweep results. "
                f"Available: {list(sweep.columns)}"
            )

        valid = sweep.dropna(subset=[resolved])
        if valid.empty:
            raise ValueError(
                f"All parameter combinations produced NaN for metric '{resolved}'."
            )

        # For drawdown, minimise (lower drawdown is better)
        if "drawdown" in resolved:
            best_row = valid.loc[valid[resolved].idxmin()]
        else:
            best_row = valid.loc[valid[resolved].idxmax()]

        best: dict[str, Any] = best_row.to_dict()
        best["metric_used"] = resolved

        logger.info(
            "Optimize %s on %s: best %s=%.4f — params=%s",
            strategy_class.__name__,
            symbol,
            resolved,
            float(best.get(resolved, float("nan"))),
            {k: best[k] for k in grid},
        )
        return best


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _require_vbt() -> None:
    """Raise VectorBTNotAvailableError if vectorbt is missing."""
    if not _VBT_AVAILABLE:
        raise VectorBTNotAvailableError(
            "vectorbt is not installed on this machine. "
            "Install it with: pip install vectorbt"
        )


def _isnan(value: float) -> bool:
    import math

    try:
        return math.isnan(value)
    except (TypeError, ValueError):
        return True


def is_available() -> bool:
    """Return True if vectorbt is installed and importable."""
    return _VBT_AVAILABLE
