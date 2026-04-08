"""Portfolio-level backtesting using VectorBT.

Absorbed from vectorbt-backtesting-skills dual_momentum pattern.
Supports multi-asset allocation, periodic rebalancing, and benchmark comparison.

Typical usage::

    backtester = PortfolioBacktester(
        symbols=["RELIANCE", "INFY", "TCS"],
        benchmark="NIFTY 50",
        rebalance_freq="quarterly",
        initial_capital=1_000_000,
    )
    result = backtester.run(
        start_date="2022-01-01",
        end_date="2024-01-01",
        allocation_strategy="equal_weight",
    )
    comparison = backtester.compare_benchmark(result)
    print(f"Alpha: {comparison.alpha:.2f}%")
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger("flinttrade.backtest.portfolio")

# ---------------------------------------------------------------------------
# Optional vectorbt import — same graceful pattern as vectorbt_runner.py
# ---------------------------------------------------------------------------

try:
    import vectorbt as vbt  # type: ignore[import-untyped]

    _VBT_AVAILABLE = True
except ImportError:
    vbt = None  # type: ignore[assignment]
    _VBT_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TRADING_DAYS_PER_YEAR = 252
_RISK_FREE_RATE = 0.07  # India — 7% annualised risk-free rate

_REBALANCE_FREQ_MAP: dict[str, str] = {
    "daily": "B",
    "weekly": "W-FRI",
    "monthly": "BMS",
    "quarterly": "QS",
    "yearly": "AS",
}


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RebalanceEntry:
    """A single rebalance event."""

    date: str
    old_weights: dict[str, float]
    new_weights: dict[str, float]
    trades: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PortfolioResult:
    """Outcome of a single portfolio backtest run.

    All return/ratio fields are annualised where applicable.
    Equity and drawdown curves are normalised to 1.0 (=100%) at start.
    """

    total_return: float
    annual_return: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    calmar_ratio: float
    equity_curve: list[float]
    drawdown_curve: list[float]
    rebalance_log: list[RebalanceEntry]

    # --- derived / supplementary ---
    final_equity: float = 0.0
    volatility: float = 0.0
    var_95: float = 0.0


@dataclass
class BenchmarkComparison:
    """Three-way comparison: strategy vs buy-and-hold vs index."""

    strategy: PortfolioResult
    buy_hold: PortfolioResult
    index: PortfolioResult
    alpha: float          # strategy annual_return − index annual_return (%)
    beta: float           # portfolio beta relative to index
    information_ratio: float  # (strategy_return − index_return) / tracking_error


# ---------------------------------------------------------------------------
# Allocation helpers
# ---------------------------------------------------------------------------


def _equal_weight(symbols: list[str], **_kwargs: Any) -> dict[str, float]:
    """1/N allocation — equal weight across all symbols.

    Args:
        symbols: List of symbol strings.

    Returns:
        Dict mapping each symbol to weight = 1 / len(symbols).
    """
    w = 1.0 / len(symbols)
    return {s: w for s in symbols}


def _inverse_volatility(
    symbols: list[str],
    price_data: "pd.DataFrame",
    lookback: int = 63,
) -> dict[str, float]:
    """Weight inversely proportional to historical daily volatility.

    Uses the most recent *lookback* trading days to estimate per-symbol vol.
    If vol cannot be computed for a symbol (e.g., insufficient data) that
    symbol falls back to equal weight.

    Args:
        symbols: List of symbol strings.
        price_data: DataFrame with symbols as columns, dates as index,
            containing close prices.
        lookback: Number of trading days for vol estimation.

    Returns:
        Dict of symbol → weight (weights sum to 1.0).
    """
    import pandas as pd  # noqa: PLC0415

    inv_vols: dict[str, float] = {}
    for sym in symbols:
        if sym not in price_data.columns:
            inv_vols[sym] = 1.0
            continue
        series: pd.Series = price_data[sym].dropna()
        if len(series) < 2:
            inv_vols[sym] = 1.0
            continue
        tail = series.iloc[-lookback:] if len(series) >= lookback else series
        daily_returns = tail.pct_change().dropna()
        vol = float(daily_returns.std())
        inv_vols[sym] = 1.0 / vol if vol > 0 else 1.0

    total = sum(inv_vols.values())
    if total <= 0:
        return _equal_weight(symbols)
    return {s: v / total for s, v in inv_vols.items()}


def _momentum_weight(
    symbols: list[str],
    price_data: "pd.DataFrame",
    lookback: int = 126,
    top_n: int | None = None,
) -> dict[str, float]:
    """Dual-momentum: rank by trailing return, overweight recent winners.

    Absorbed from the vectorbt-backtesting-skills dual_momentum pattern.
    Symbols with positive trailing momentum receive proportional weights;
    symbols with negative momentum receive zero weight (go to cash).

    Args:
        symbols: List of symbol strings.
        price_data: DataFrame with symbols as columns, close prices.
        lookback: Number of trading days for momentum computation.
        top_n: If set, only the top-N momentum symbols are held.

    Returns:
        Dict of symbol → weight (sums to ≤ 1.0; remainder is implicit cash).
    """
    import pandas as pd  # noqa: PLC0415

    momentum: dict[str, float] = {}
    for sym in symbols:
        if sym not in price_data.columns:
            momentum[sym] = 0.0
            continue
        series: pd.Series = price_data[sym].dropna()
        if len(series) < lookback + 1:
            momentum[sym] = 0.0
            continue
        ret = float(series.iloc[-1] / series.iloc[-lookback] - 1)
        momentum[sym] = max(0.0, ret)  # negative momentum → zero (cash)

    if top_n is not None:
        ranked = sorted(momentum.items(), key=lambda x: x[1], reverse=True)
        for sym, _ in ranked[top_n:]:
            momentum[sym] = 0.0

    total = sum(momentum.values())
    if total <= 0:
        return {s: 0.0 for s in symbols}
    return {s: v / total for s, v in momentum.items()}


# ---------------------------------------------------------------------------
# Pure-Python fallback portfolio simulator
# ---------------------------------------------------------------------------


def _simulate_portfolio_pure(
    price_matrix: "pd.DataFrame",
    rebalance_dates: "pd.DatetimeIndex",
    allocation_fn: Any,
    initial_capital: float,
    fees: float,
    allocation_kwargs: dict[str, Any],
) -> tuple[list[float], list[float], list[RebalanceEntry]]:
    """Simulate a multi-asset portfolio without vectorbt.

    Daily mark-to-market with rebalancing at specified dates.

    Args:
        price_matrix: DataFrame (dates × symbols) of close prices.
        rebalance_dates: DatetimeIndex of rebalance trigger dates.
        allocation_fn: Callable(symbols, price_data, **kwargs) → weights dict.
        initial_capital: Starting cash.
        fees: Round-trip fee fraction per trade.
        allocation_kwargs: Extra kwargs forwarded to allocation_fn.

    Returns:
        Tuple of (equity_curve, drawdown_curve, rebalance_log).
        equity_curve is normalised to 1.0 at start.
    """
    import pandas as pd  # noqa: PLC0415

    symbols = list(price_matrix.columns)
    shares: dict[str, float] = {s: 0.0 for s in symbols}
    cash = initial_capital
    equity_curve: list[float] = []
    rebalance_log: list[RebalanceEntry] = []
    rebalance_set = set(rebalance_dates.strftime("%Y-%m-%d"))

    for date, row in price_matrix.iterrows():
        date_str = str(date)[:10]

        # Rebalance
        if date_str in rebalance_set:
            # Current portfolio value
            portfolio_val = cash + sum(
                shares[s] * float(row[s]) for s in symbols if not math.isnan(float(row[s]))
            )
            old_weights: dict[str, float] = {}
            if portfolio_val > 0:
                old_weights = {
                    s: (shares[s] * float(row[s]) / portfolio_val if not math.isnan(float(row[s])) else 0.0)
                    for s in symbols
                }

            new_weights = allocation_fn(
                symbols, price_data=price_matrix.loc[:date], **allocation_kwargs
            )

            trades_log: list[dict[str, Any]] = []
            for sym in symbols:
                price = float(row[sym])
                if math.isnan(price) or price <= 0:
                    continue
                target_val = portfolio_val * new_weights.get(sym, 0.0)
                target_shares = target_val / price
                delta = target_shares - shares[sym]
                if abs(delta) > 1e-9:
                    trade_cost = abs(delta * price) * fees
                    cash -= delta * price + trade_cost
                    shares[sym] = target_shares
                    trades_log.append(
                        {"symbol": sym, "delta_shares": round(delta, 4), "price": price}
                    )

            rebalance_log.append(
                RebalanceEntry(
                    date=date_str,
                    old_weights=old_weights,
                    new_weights=new_weights,
                    trades=trades_log,
                )
            )

        # Mark to market
        portfolio_val = cash + sum(
            shares[s] * float(row[s])
            for s in symbols
            if not math.isnan(float(row[s]))
        )
        equity_curve.append(portfolio_val)

    if not equity_curve:
        return [], [], rebalance_log

    # Normalise to 1.0 at start
    base = equity_curve[0] if equity_curve[0] > 0 else initial_capital
    norm_equity = [e / base for e in equity_curve]

    # Drawdown curve
    peak = norm_equity[0]
    drawdown_curve: list[float] = []
    for e in norm_equity:
        if e > peak:
            peak = e
        dd = (peak - e) / peak if peak > 0 else 0.0
        drawdown_curve.append(dd)

    return norm_equity, drawdown_curve, rebalance_log


# ---------------------------------------------------------------------------
# Metrics helpers (pure Python, no vectorbt)
# ---------------------------------------------------------------------------


def _compute_result_metrics(
    equity_curve: list[float],
    initial_capital: float,
    rebalance_log: list[RebalanceEntry],
) -> PortfolioResult:
    """Derive all PortfolioResult fields from a normalised equity curve.

    Args:
        equity_curve: Normalised equity curve (1.0 at start).
        initial_capital: Starting capital in currency units.
        rebalance_log: List of rebalance events.

    Returns:
        Fully populated PortfolioResult.
    """
    if len(equity_curve) < 2:
        empty = PortfolioResult(
            total_return=0.0,
            annual_return=0.0,
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            max_drawdown=0.0,
            calmar_ratio=0.0,
            equity_curve=equity_curve,
            drawdown_curve=[0.0] * len(equity_curve),
            rebalance_log=rebalance_log,
            final_equity=initial_capital,
        )
        return empty

    total_return = (equity_curve[-1] - equity_curve[0]) / equity_curve[0] * 100
    years = len(equity_curve) / _TRADING_DAYS_PER_YEAR
    annual_return = ((equity_curve[-1] / equity_curve[0]) ** (1 / years) - 1) * 100 if years > 0 else 0.0

    # Daily returns
    daily_rets = [
        (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
        for i in range(1, len(equity_curve))
    ]

    mean_r = sum(daily_rets) / len(daily_rets)
    variance = sum((r - mean_r) ** 2 for r in daily_rets) / max(len(daily_rets) - 1, 1)
    std_r = math.sqrt(variance)
    daily_rf = _RISK_FREE_RATE / _TRADING_DAYS_PER_YEAR

    sharpe = (mean_r - daily_rf) / std_r * math.sqrt(_TRADING_DAYS_PER_YEAR) if std_r > 0 else 0.0

    downside = [min(0.0, r - daily_rf) for r in daily_rets]
    downside_var = sum(d ** 2 for d in downside) / max(len(downside), 1)
    downside_dev = math.sqrt(downside_var)
    sortino = (mean_r - daily_rf) / downside_dev * math.sqrt(_TRADING_DAYS_PER_YEAR) if downside_dev > 0 else 0.0

    volatility = std_r * math.sqrt(_TRADING_DAYS_PER_YEAR) * 100

    # Drawdown curve
    peak = equity_curve[0]
    max_dd = 0.0
    drawdown_curve: list[float] = []
    for e in equity_curve:
        if e > peak:
            peak = e
        dd = (peak - e) / peak if peak > 0 else 0.0
        drawdown_curve.append(dd)
        max_dd = max(max_dd, dd)

    calmar = annual_return / (max_dd * 100) if max_dd > 0 else 0.0

    # VaR 95%
    sorted_rets = sorted(daily_rets)
    var_idx = max(0, int(0.05 * len(sorted_rets)) - 1)
    var_95 = -sorted_rets[var_idx] * 100 if sorted_rets else 0.0

    return PortfolioResult(
        total_return=total_return,
        annual_return=annual_return,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        max_drawdown=max_dd * 100,
        calmar_ratio=calmar,
        equity_curve=equity_curve,
        drawdown_curve=drawdown_curve,
        rebalance_log=rebalance_log,
        final_equity=equity_curve[-1] * initial_capital,
        volatility=volatility,
        var_95=var_95,
    )


# ---------------------------------------------------------------------------
# VectorBT portfolio simulation
# ---------------------------------------------------------------------------


def _simulate_portfolio_vbt(
    price_matrix: "pd.DataFrame",
    rebalance_dates: "pd.DatetimeIndex",
    allocation_fn: Any,
    initial_capital: float,
    fees: float,
    slippage: float,
    allocation_kwargs: dict[str, Any],
) -> tuple[list[float], list[float], list[RebalanceEntry]]:
    """Simulate portfolio using vbt.Portfolio.from_orders().

    Uses ``size_type="targetpercent"`` and ``cash_sharing=True`` for proper
    multi-asset portfolio semantics.

    Args:
        price_matrix: DataFrame (dates × symbols) of close prices.
        rebalance_dates: DatetimeIndex of dates to trigger rebalancing.
        allocation_fn: Callable(symbols, price_data, **kwargs) → weights dict.
        initial_capital: Starting capital.
        fees: Per-trade fee fraction.
        slippage: Per-trade slippage fraction.
        allocation_kwargs: Extra kwargs forwarded to allocation_fn.

    Returns:
        Tuple of (equity_curve_normalised, drawdown_curve, rebalance_log).
    """
    import numpy as np  # noqa: PLC0415
    import pandas as pd  # noqa: PLC0415

    symbols = list(price_matrix.columns)
    n_dates = len(price_matrix)
    n_syms = len(symbols)

    # Build target-percent size array (n_dates × n_syms); NaN = no order
    size_arr = np.full((n_dates, n_syms), np.nan)
    rebalance_set = set(rebalance_dates.strftime("%Y-%m-%d"))
    rebalance_log: list[RebalanceEntry] = []

    prev_weights: dict[str, float] = {}
    for i, (date, _row) in enumerate(price_matrix.iterrows()):
        date_str = str(date)[:10]
        if date_str in rebalance_set:
            slice_df = price_matrix.iloc[: i + 1]
            new_weights = allocation_fn(symbols, price_data=slice_df, **allocation_kwargs)
            for j, sym in enumerate(symbols):
                size_arr[i, j] = new_weights.get(sym, 0.0)
            rebalance_log.append(
                RebalanceEntry(
                    date=date_str,
                    old_weights=dict(prev_weights),
                    new_weights=dict(new_weights),
                )
            )
            prev_weights = new_weights

    size_df = pd.DataFrame(size_arr, index=price_matrix.index, columns=price_matrix.columns)

    pf = vbt.Portfolio.from_orders(
        price_matrix,
        size=size_df,
        size_type="targetpercent",
        cash_sharing=True,
        init_cash=initial_capital,
        fees=fees,
        slippage=slippage,
        freq="1D",
    )

    equity_series = pf.value()
    # from_orders with cash_sharing returns a Series (single portfolio)
    if hasattr(equity_series, "sum"):
        try:
            equity_values = equity_series.values.tolist()
        except AttributeError:
            equity_values = list(equity_series)
    else:
        equity_values = list(equity_series)

    base = equity_values[0] if equity_values and equity_values[0] > 0 else initial_capital
    norm_equity = [v / base for v in equity_values]

    peak = norm_equity[0]
    drawdown_curve: list[float] = []
    for e in norm_equity:
        if e > peak:
            peak = e
        dd = (peak - e) / peak if peak > 0 else 0.0
        drawdown_curve.append(dd)

    return norm_equity, drawdown_curve, rebalance_log


# ---------------------------------------------------------------------------
# PortfolioBacktester
# ---------------------------------------------------------------------------


class PortfolioBacktester:
    """Portfolio-level backtesting using VectorBT.

    Absorbed from vectorbt-backtesting-skills dual_momentum pattern.
    Supports: multi-asset allocation, periodic rebalancing, benchmark comparison.

    Uses vectorbt when available; falls back to an equivalent pure-Python
    simulator when it is not installed.

    Args:
        symbols: List of symbol strings to include in the portfolio.
        benchmark: Benchmark index name for comparison (informational only;
            data must be provided via the ``benchmark_prices`` arg of
            :meth:`compare_benchmark`).
        rebalance_freq: One of ``"daily"``, ``"weekly"``, ``"monthly"``,
            ``"quarterly"`` (default), ``"yearly"``.
        initial_capital: Starting capital in currency units (default 1 000 000).
        fees: Per-trade fee fraction (default 0.001 = 0.1%).
        slippage: Per-trade slippage fraction used when vectorbt is available
            (default 0.0005 = 0.05%).

    Example::

        bt = PortfolioBacktester(["RELIANCE", "INFY", "TCS"])
        result = bt.run("2022-01-01", "2024-01-01", "equal_weight")
    """

    def __init__(
        self,
        symbols: list[str],
        benchmark: str = "NIFTY 50",
        rebalance_freq: str = "quarterly",
        initial_capital: float = 1_000_000.0,
        fees: float = 0.001,
        slippage: float = 0.0005,
    ) -> None:
        if not symbols:
            raise ValueError("symbols list must not be empty")
        if rebalance_freq not in _REBALANCE_FREQ_MAP:
            raise ValueError(
                f"rebalance_freq must be one of {list(_REBALANCE_FREQ_MAP.keys())}"
            )
        if initial_capital <= 0:
            raise ValueError("initial_capital must be positive")

        self.symbols = symbols
        self.benchmark = benchmark
        self.rebalance_freq = rebalance_freq
        self.initial_capital = initial_capital
        self.fees = fees
        self.slippage = slippage

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        start_date: str,
        end_date: str,
        allocation_strategy: str = "equal_weight",
        price_data: "pd.DataFrame | None" = None,
        momentum_lookback: int = 126,
        vol_lookback: int = 63,
        top_n: int | None = None,
    ) -> PortfolioResult:
        """Run portfolio backtest.

        Uses ``vbt.Portfolio.from_orders()`` with ``size_type="targetpercent"``
        and ``cash_sharing=True`` when vectorbt is installed, otherwise falls
        back to a pure-Python daily mark-to-market simulator.

        Args:
            start_date: Start date in ``YYYY-MM-DD`` format.
            end_date: End date in ``YYYY-MM-DD`` format.
            allocation_strategy: One of ``"equal_weight"``, ``"inverse_volatility"``,
                ``"momentum"``, or ``"market_cap"`` (market_cap falls back to
                equal_weight when market-cap data is unavailable).
            price_data: Optional pre-loaded DataFrame (dates × symbols) of
                close prices.  If not supplied the backtester uses synthetic
                random-walk prices for testing purposes.
            momentum_lookback: Lookback period (trading days) for momentum
                strategy (default 126 ≈ 6 months).
            vol_lookback: Lookback period (trading days) for inverse-volatility
                strategy (default 63 ≈ 3 months).
            top_n: For momentum strategy only — keep only top-N symbols.

        Returns:
            PortfolioResult with full metrics, equity/drawdown curves, and
            rebalance log.

        Raises:
            ValueError: If allocation_strategy is unknown or dates are invalid.
        """
        import pandas as pd  # noqa: PLC0415

        _known_strategies = {"equal_weight", "market_cap", "inverse_volatility", "momentum"}
        if allocation_strategy not in _known_strategies:
            raise ValueError(
                f"Unknown allocation_strategy '{allocation_strategy}'. "
                f"Choose from: {sorted(_known_strategies)}"
            )

        # Build price matrix
        price_matrix = self._build_price_matrix(price_data, start_date, end_date)

        # Resolve allocation function
        alloc_kwargs: dict[str, Any] = {}
        if allocation_strategy == "equal_weight" or allocation_strategy == "market_cap":
            # market_cap degrades to equal_weight when external data not supplied
            allocation_fn = _equal_weight
        elif allocation_strategy == "inverse_volatility":
            allocation_fn = _inverse_volatility
            alloc_kwargs = {"lookback": vol_lookback}
        else:  # momentum
            allocation_fn = _momentum_weight
            alloc_kwargs = {"lookback": momentum_lookback, "top_n": top_n}

        # Build rebalance dates
        pd_freq = _REBALANCE_FREQ_MAP[self.rebalance_freq]
        rebalance_dates = pd.date_range(
            start=price_matrix.index[0],
            end=price_matrix.index[-1],
            freq=pd_freq,
        )

        # Simulate
        if _VBT_AVAILABLE:
            equity_curve, drawdown_curve, rebalance_log = _simulate_portfolio_vbt(
                price_matrix=price_matrix,
                rebalance_dates=rebalance_dates,
                allocation_fn=allocation_fn,
                initial_capital=self.initial_capital,
                fees=self.fees,
                slippage=self.slippage,
                allocation_kwargs=alloc_kwargs,
            )
        else:
            logger.debug("vectorbt not available — using pure-Python portfolio simulator")
            equity_curve, drawdown_curve, rebalance_log = _simulate_portfolio_pure(
                price_matrix=price_matrix,
                rebalance_dates=rebalance_dates,
                allocation_fn=allocation_fn,
                initial_capital=self.initial_capital,
                fees=self.fees,
                allocation_kwargs=alloc_kwargs,
            )

        result = _compute_result_metrics(equity_curve, self.initial_capital, rebalance_log)
        result.drawdown_curve = drawdown_curve  # use the pre-computed curve
        logger.info(
            "Portfolio backtest complete — strategy=%s, symbols=%d, "
            "return=%.2f%%, sharpe=%.2f, max_dd=%.2f%%",
            allocation_strategy,
            len(self.symbols),
            result.total_return,
            result.sharpe_ratio,
            result.max_drawdown,
        )
        return result

    def compare_benchmark(
        self,
        result: PortfolioResult,
        price_data: "pd.DataFrame | None" = None,
        benchmark_prices: "pd.Series | None" = None,
        start_date: str = "",
        end_date: str = "",
    ) -> BenchmarkComparison:
        """Compare strategy result versus buy-and-hold and a benchmark index.

        Produces normalised cumulative returns, drawdown comparison, and
        risk-adjusted metrics (alpha, beta, information ratio).

        Args:
            result: The strategy PortfolioResult from :meth:`run`.
            price_data: Price matrix used in the backtest (dates × symbols).
                Used to compute the buy-and-hold baseline.  If ``None``,
                a synthetic price matrix is generated.
            benchmark_prices: Optional Series of benchmark (index) close
                prices aligned with the strategy dates.  If ``None``, an
                equal-weight average of all symbols is used as proxy.
            start_date: Start date for data generation if price_data is None.
            end_date: End date for data generation if price_data is None.

        Returns:
            BenchmarkComparison with alpha, beta, and information ratio.
        """
        # Build equal-weight buy-and-hold (no rebalancing, just hold)
        pm = self._build_price_matrix(price_data, start_date, end_date)
        bh_equity = self._buy_and_hold_curve(pm)
        buy_hold_result = _compute_result_metrics(bh_equity, self.initial_capital, [])

        # Index / benchmark curve
        if benchmark_prices is not None:
            idx_series = benchmark_prices.values.tolist()
            base_idx = idx_series[0] if idx_series[0] > 0 else 1.0
            index_equity = [v / base_idx for v in idx_series]
        else:
            # Fallback: use equal-weight portfolio of given symbols as proxy
            index_equity = bh_equity

        index_result = _compute_result_metrics(index_equity, self.initial_capital, [])

        # Alpha and beta
        alpha = result.annual_return - index_result.annual_return

        # Beta: covariance(strategy_rets, index_rets) / variance(index_rets)
        beta = self._compute_beta(result.equity_curve, index_equity)

        # Information ratio: (strategy_ret − index_ret) / tracking_error
        information_ratio = self._compute_information_ratio(
            result.equity_curve, index_equity
        )

        return BenchmarkComparison(
            strategy=result,
            buy_hold=buy_hold_result,
            index=index_result,
            alpha=alpha,
            beta=beta,
            information_ratio=information_ratio,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_price_matrix(
        self,
        price_data: "pd.DataFrame | None",
        start_date: str,
        end_date: str,
    ) -> "pd.DataFrame":
        """Return (or generate) a price matrix aligned to symbols.

        If price_data is supplied it is used directly (filtered to the
        date range when possible).  Otherwise a synthetic random-walk
        DataFrame is generated — useful for unit tests.

        Args:
            price_data: Optional externally supplied price matrix.
            start_date: Start date string (used for synthetic generation).
            end_date: End date string (used for synthetic generation).

        Returns:
            DataFrame with symbol columns and DatetimeIndex rows.
        """
        import pandas as pd  # noqa: PLC0415

        if price_data is not None:
            # Filter to requested date range if possible
            df = price_data.copy()
            for sym in self.symbols:
                if sym not in df.columns:
                    df[sym] = 100.0  # flat placeholder
            df = df[self.symbols]
            if start_date:
                df = df[df.index >= pd.Timestamp(start_date)]
            if end_date:
                df = df[df.index <= pd.Timestamp(end_date)]
            df = df.ffill().bfill()
            return df

        # Synthetic data — deterministic random walk for reproducibility
        import random  # noqa: PLC0415

        rng = random.Random(42)
        sd = start_date or "2022-01-01"
        ed = end_date or "2024-01-01"
        dates = pd.bdate_range(sd, ed)
        data: dict[str, list[float]] = {}
        for sym in self.symbols:
            price = 100.0
            prices = []
            for _ in dates:
                price = max(1.0, price * (1 + rng.gauss(0.0005, 0.015)))
                prices.append(round(price, 2))
            data[sym] = prices
        return pd.DataFrame(data, index=dates)

    def _buy_and_hold_curve(self, price_matrix: "pd.DataFrame") -> list[float]:
        """Equal-weight buy-and-hold: invest 1/N in each symbol on day 0.

        Args:
            price_matrix: DataFrame (dates × symbols).

        Returns:
            Normalised equity curve (1.0 at start).
        """
        symbols = list(price_matrix.columns)
        if not symbols:
            return []

        n = len(symbols)
        capital_per_sym = self.initial_capital / n

        # Initial shares
        first_prices = price_matrix.iloc[0]
        shares: dict[str, float] = {
            sym: capital_per_sym / float(first_prices[sym])
            for sym in symbols
            if float(first_prices[sym]) > 0
        }

        equity_curve: list[float] = []
        for _date, row in price_matrix.iterrows():
            val = sum(shares.get(sym, 0.0) * float(row[sym]) for sym in symbols)
            equity_curve.append(val)

        base = equity_curve[0] if equity_curve and equity_curve[0] > 0 else self.initial_capital
        return [v / base for v in equity_curve]

    @staticmethod
    def _compute_beta(
        strategy_curve: list[float], index_curve: list[float]
    ) -> float:
        """Compute portfolio beta relative to the index.

        Beta = cov(strategy_returns, index_returns) / var(index_returns).

        Args:
            strategy_curve: Normalised equity curve for the strategy.
            index_curve: Normalised equity curve for the benchmark index.

        Returns:
            Beta coefficient (float).  Returns 1.0 on insufficient data.
        """
        min_len = min(len(strategy_curve), len(index_curve))
        if min_len < 3:
            return 1.0

        s_rets = [
            (strategy_curve[i] - strategy_curve[i - 1]) / strategy_curve[i - 1]
            for i in range(1, min_len)
            if strategy_curve[i - 1] > 0
        ]
        i_rets = [
            (index_curve[i] - index_curve[i - 1]) / index_curve[i - 1]
            for i in range(1, min_len)
            if index_curve[i - 1] > 0
        ]

        if len(s_rets) < 2 or len(i_rets) < 2:
            return 1.0

        n = min(len(s_rets), len(i_rets))
        s_rets = s_rets[:n]
        i_rets = i_rets[:n]

        mean_s = sum(s_rets) / n
        mean_i = sum(i_rets) / n

        cov = sum((s_rets[k] - mean_s) * (i_rets[k] - mean_i) for k in range(n)) / (n - 1)
        var_i = sum((r - mean_i) ** 2 for r in i_rets) / (n - 1)

        return cov / var_i if var_i > 0 else 1.0

    @staticmethod
    def _compute_information_ratio(
        strategy_curve: list[float], index_curve: list[float]
    ) -> float:
        """Information ratio = annualised active return / tracking error.

        Active return is computed as the daily difference in returns between
        the strategy and the index.

        Args:
            strategy_curve: Normalised equity curve for the strategy.
            index_curve: Normalised equity curve for the benchmark.

        Returns:
            Information ratio (float).  Returns 0.0 on insufficient data.
        """
        min_len = min(len(strategy_curve), len(index_curve))
        if min_len < 3:
            return 0.0

        active: list[float] = []
        for i in range(1, min_len):
            if strategy_curve[i - 1] > 0 and index_curve[i - 1] > 0:
                sr = (strategy_curve[i] - strategy_curve[i - 1]) / strategy_curve[i - 1]
                ir = (index_curve[i] - index_curve[i - 1]) / index_curve[i - 1]
                active.append(sr - ir)

        if len(active) < 2:
            return 0.0

        mean_active = sum(active) / len(active)
        var_active = sum((a - mean_active) ** 2 for a in active) / (len(active) - 1)
        tracking_error = math.sqrt(var_active) * math.sqrt(_TRADING_DAYS_PER_YEAR)

        return (mean_active * _TRADING_DAYS_PER_YEAR) / tracking_error if tracking_error > 0 else 0.0


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------


def is_available() -> bool:
    """Return True if vectorbt is installed (portfolio simulation is accelerated)."""
    return _VBT_AVAILABLE
