"""Statistical Pairs Trading strategy with Ornstein-Uhlenbeck half-life.

Full stat-arb implementation using:
- Engle-Granger cointegration test (pure Python ADF-based)
- Augmented Dickey-Fuller stationarity test for spread validation
- Ornstein-Uhlenbeck half-life to size the lookback window dynamically
- Z-score entry/exit signals with configurable thresholds
- Stop-loss via a multiple of the spread standard deviation

Reference:
    marketcalls/Statistical-Arbitrage-Bayesian-Optimized-Kappa-Half-life-Pairs-Trading-Engine
    (adapted and reimplemented in pure Python + NumPy-free idioms for FlintTrade)

This strategy feeds off **two** synchronised bar lists: leg A is the primary
instrument (on_bar); leg B closes must be provided as ``bars_b``.  When the
analyser is run outside the simulator you may also call ``add_leg_b_close``
directly before each ``on_bar`` invocation.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any

from packages.core.src.models import OHLCV, Order, Quote
from packages.engine.src.strategy import BaseStrategy

from ._mixin import _BacktestStrategyMixin

logger = logging.getLogger("flinttrade.backtest.strategies.stat_pairs_trading")


# ---------------------------------------------------------------------------
# Statistical helpers (pure Python — no NumPy / scipy dependencies)
# ---------------------------------------------------------------------------


def _mean(values: list[float]) -> float:
    """Arithmetic mean."""
    return sum(values) / len(values) if values else 0.0


def _std(values: list[float], ddof: int = 1) -> float:
    """Sample (ddof=1) or population (ddof=0) standard deviation."""
    n = len(values)
    if n <= ddof:
        return 0.0
    m = _mean(values)
    variance = sum((v - m) ** 2 for v in values) / (n - ddof)
    return math.sqrt(max(0.0, variance))


def _ols(y: list[float], x: list[float]) -> tuple[float, float]:
    """OLS regression of y on x.

    Returns:
        Tuple of (slope, intercept).
    """
    n = len(y)
    if n < 2:
        return 1.0, 0.0
    sx = sum(x)
    sy = sum(y)
    sxy = sum(xi * yi for xi, yi in zip(x, y))
    sxx = sum(xi * xi for xi in x)
    denom = n * sxx - sx * sx
    if denom == 0:
        return 1.0, 0.0
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope, intercept


def _adf_test(series: list[float], max_lags: int = 1) -> float:
    """Approximate Augmented Dickey-Fuller test statistic.

    Computes the t-statistic for the lagged level term in the ADF regression:
        Δy_t = α + β*y_{t-1} + Σγ_i*Δy_{t-i} + ε

    A more negative ADF stat → stronger evidence against a unit root
    (i.e., series is stationary).  Approximate critical values:
        1%: -3.43   5%: -2.86   10%: -2.57

    Args:
        series:   Time series to test.
        max_lags: Number of lagged differences to include (1 is sufficient
                  for most financial spreads).

    Returns:
        ADF t-statistic (float).  Returns 0.0 if the series is too short.
    """
    n = len(series)
    min_obs = max_lags + 3
    if n < min_obs:
        return 0.0

    # First differences
    diff = [series[i] - series[i - 1] for i in range(1, n)]

    # Build OLS design matrix
    # Dependent: diff[max_lags:]
    # Regressors: constant, lagged level, lagged diffs
    dep_start = max_lags
    m = len(diff) - dep_start
    if m < 3:
        return 0.0

    dep = diff[dep_start:]
    # Lagged level: series[max_lags : n - 1]
    lag_level = series[max_lags : n - 1]

    # Build regressor matrix rows: [1, y_{t-1}, Δy_{t-1}, ..., Δy_{t-max_lags}]
    k = 1 + 1 + max_lags  # constant + lagged level + lagged diffs
    X: list[list[float]] = []
    for i in range(m):
        row = [1.0, lag_level[i]]
        for lag in range(1, max_lags + 1):
            row.append(diff[dep_start - lag + i])
        X.append(row)

    # OLS via normal equations: β = (X'X)^{-1} X'y
    # For speed we only need the coefficient and SE for the lagged level (col 1)
    # Use Gram-Schmidt / simple Gaussian elimination on the 2x2 sub-problem
    # after projecting out the constant.
    # Full k×k inversion for small k:
    xt_x = [[sum(X[i][r] * X[i][c] for i in range(m)) for c in range(k)] for r in range(k)]
    xt_y = [sum(X[i][r] * dep[i] for i in range(m)) for r in range(k)]

    # Solve xt_x * beta = xt_y via Gaussian elimination
    beta = _gauss_elim(xt_x, xt_y)
    if beta is None:
        return 0.0

    # Residuals
    residuals = [dep[i] - sum(beta[j] * X[i][j] for j in range(k)) for i in range(m)]
    sse = sum(r * r for r in residuals)
    sigma2 = sse / max(1, m - k)

    # SE of beta[1] = sqrt(sigma2 * (xt_x_inv)[1,1])
    xt_x_inv = _matrix_inv(xt_x)
    if xt_x_inv is None:
        return 0.0
    se_beta1 = math.sqrt(max(0.0, sigma2 * xt_x_inv[1][1]))
    if se_beta1 == 0:
        return 0.0

    return beta[1] / se_beta1


def _gauss_elim(A: list[list[float]], b: list[float]) -> list[float] | None:
    """Solve Ax = b by Gaussian elimination with partial pivoting.

    Returns coefficient vector or None if singular.
    """
    n = len(b)
    # Augmented matrix
    aug = [A[i][:] + [b[i]] for i in range(n)]

    for col in range(n):
        # Partial pivot
        max_row = col + max(range(n - col), key=lambda r: abs(aug[col + r][col]))
        aug[col], aug[max_row] = aug[max_row], aug[col]
        pivot = aug[col][col]
        if abs(pivot) < 1e-15:
            return None
        for row in range(col + 1, n):
            factor = aug[row][col] / pivot
            for j in range(col, n + 1):
                aug[row][j] -= factor * aug[col][j]

    # Back-substitution
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = aug[i][n]
        for j in range(i + 1, n):
            x[i] -= aug[i][j] * x[j]
        if abs(aug[i][i]) < 1e-15:
            return None
        x[i] /= aug[i][i]
    return x


def _matrix_inv(A: list[list[float]]) -> list[list[float]] | None:
    """Invert a square matrix via Gauss-Jordan.  Returns None if singular."""
    n = len(A)
    # Augment with identity
    aug = [A[i][:] + [1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]

    for col in range(n):
        max_row = col + max(range(n - col), key=lambda r: abs(aug[col + r][col]))
        aug[col], aug[max_row] = aug[max_row], aug[col]
        pivot = aug[col][col]
        if abs(pivot) < 1e-15:
            return None
        aug[col] = [v / pivot for v in aug[col]]
        for row in range(n):
            if row != col:
                factor = aug[row][col]
                aug[row] = [aug[row][j] - factor * aug[col][j] for j in range(2 * n)]

    return [row[n:] for row in aug]


def cointegration_test(y: list[float], x: list[float]) -> tuple[float, float]:
    """Engle-Granger two-step cointegration test.

    Step 1: Regress y on x to get the OLS residuals (the cointegrating spread).
    Step 2: Apply ADF test to the residuals.

    Args:
        y: Price series for leg A (dependent).
        x: Price series for leg B (independent).

    Returns:
        Tuple of (hedge_ratio, adf_stat).  A more negative ADF stat means
        the pair is more likely cointegrated.
    """
    n = min(len(y), len(x))
    if n < 20:
        return 1.0, 0.0

    y_n = y[-n:]
    x_n = x[-n:]
    hedge_ratio, intercept = _ols(y_n, x_n)
    residuals = [y_n[i] - hedge_ratio * x_n[i] - intercept for i in range(n)]
    adf = _adf_test(residuals)
    return hedge_ratio, adf


def adf_stationarity(series: list[float]) -> float:
    """Run ADF test directly on a series.

    Args:
        series: Time series to check for stationarity.

    Returns:
        ADF t-statistic.  Values below -2.86 indicate stationarity at 5%.
    """
    return _adf_test(series)


def ou_half_life(spread: list[float]) -> float:
    """Ornstein-Uhlenbeck half-life of mean reversion.

    Regresses Δspread_t on spread_{t-1}:
        Δspread = θ * spread_{t-1} + ε
    Half-life = -ln(2) / θ

    Args:
        spread: Residual spread series.

    Returns:
        Half-life in bars.  Returns 0.0 if the series is too short or
        the regression coefficient is non-negative (no mean reversion).
    """
    n = len(spread)
    if n < 3:
        return 0.0

    y = [spread[i] - spread[i - 1] for i in range(1, n)]
    x = spread[: n - 1]
    theta, _ = _ols(y, x)

    if theta >= 0:
        return 0.0
    half_life = -math.log(2) / theta
    return max(2.0, half_life)


def zscore(series: list[float], window: int) -> float:
    """Compute the current (last element) z-score over a rolling window.

    Args:
        series: Full series history.
        window: Lookback window.

    Returns:
        Z-score of the last element.  Returns 0.0 if window > len(series).
    """
    if len(series) < window:
        return 0.0
    w = series[-window:]
    m = _mean(w)
    s = _std(w, ddof=1)
    if s == 0:
        return 0.0
    return (series[-1] - m) / s


# ---------------------------------------------------------------------------
# Strategy dataclass
# ---------------------------------------------------------------------------


@dataclass
class PairsTradingConfig:
    """Configuration for StatPairsTrading.

    Attributes:
        lookback:          Rolling window for OLS hedge ratio and z-score
                           (bars).  When ``auto_halflife=True`` this becomes
                           a floor; the actual window is set to the OU
                           half-life.
        entry_threshold:   Z-score magnitude at which to enter a trade.
        exit_threshold:    Z-score magnitude at which to close the trade.
        stoploss_factor:   Stop-loss triggered when spread moves
                           ``stoploss_factor × std`` against the position.
        auto_halflife:     When True, dynamically set lookback = OU half-life.
        min_adf_stat:      Minimum (most negative) ADF stat required to trade.
                           Default -2.0 (relaxed); use -2.86 for 5% significance.
        recalc_every:      Recalculate hedge ratio and half-life every N bars.
    """

    lookback: int = 60
    entry_threshold: float = 2.0
    exit_threshold: float = 0.5
    stoploss_factor: float = 3.0
    auto_halflife: bool = True
    min_adf_stat: float = -2.0
    recalc_every: int = 20


# ---------------------------------------------------------------------------
# Main strategy
# ---------------------------------------------------------------------------


class StatPairsTrading(BaseStrategy, _BacktestStrategyMixin):
    """Statistical Pairs Trading with OU half-life and Engle-Granger cointegration.

    Enters a long/short spread position when the z-score of the spread
    exceeds ``entry_threshold``, and closes when it reverts to
    ``exit_threshold``.  Stop-loss exits if the spread widens to
    ``stoploss_factor × std``.

    The strategy supports two usage modes:

    1. **Simulator mode** — call ``on_bar(bar_a)`` once per bar.  Before each
       call, set the synchronised leg B close with ``add_leg_b_close(price)``.

    2. **Analysis mode** — call ``on_bar(bar_a, bars_b=<list>)`` passing the
       full leg B history each time (as in PairsCointegration).

    Args:
        name:            Strategy name.
        exchange:        Exchange (default ``"NSE"``).
        product:         Product type (default ``"MIS"``).
        config:          :class:`PairsTradingConfig` instance.
        symbol_a:        Symbol for leg A (primary instrument).
        symbol_b:        Symbol for leg B (hedge instrument).
        **kwargs:        Forwarded to BaseStrategy.

    Example::

        cfg = PairsTradingConfig(lookback=30, entry_threshold=2.0, exit_threshold=0.5)
        strategy = StatPairsTrading(config=cfg, symbol_a="HDFCBANK", symbol_b="ICICIBANK")
        for bar_a, close_b in zip(bars_a, closes_b):
            strategy.add_leg_b_close(close_b)
            strategy.on_bar(bar_a)
        orders = strategy.generate_orders()
    """

    def __init__(
        self,
        name: str = "StatPairsTrading",
        exchange: str = "NSE",
        product: str = "MIS",
        config: PairsTradingConfig | None = None,
        symbol_a: str = "",
        symbol_b: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(name=name, exchange=exchange, product=product)
        self._config = config or PairsTradingConfig()
        self._symbol = symbol_a
        self._symbol_b = symbol_b
        self._init_history()

        # Leg B closes
        self._b_closes: list[float] = []

        # Computed state
        self._hedge_ratio: float = 1.0
        self._intercept: float = 0.0
        self._spreads: list[float] = []
        self._effective_lookback: int = self._config.lookback
        self._current_adf: float = 0.0
        self._bars_since_recalc: int = 0

        # Position state
        self._spread_entry: float = 0.0   # spread value at trade entry
        self._spread_std: float = 1.0     # std of spread at trade entry

        # Tracking for daily_returns (walk-forward adapter compatibility)
        self.daily_returns: list[float] = []
        self._prev_equity: float = 1.0

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def add_leg_b_close(self, close_b: float) -> None:
        """Append a leg B close price before calling ``on_bar``.

        Args:
            close_b: Close price of the hedge instrument for this bar.
        """
        self._b_closes.append(close_b)

    # ------------------------------------------------------------------
    # BaseStrategy interface
    # ------------------------------------------------------------------

    def on_tick(self, quote: Quote) -> None:  # noqa: D401
        pass

    def on_bar(self, bar: OHLCV, bars_b: list[OHLCV] | None = None) -> None:
        """Process one bar for leg A.

        Args:
            bar:    Current OHLCV bar for leg A.
            bars_b: Optional list of leg B OHLCV bars (analysis mode).
        """
        self._record_bar(bar)

        # Sync leg B from bars_b if provided (analysis mode)
        if bars_b is not None:
            self._b_closes = [b.close for b in bars_b]

        n = min(len(self._closes), len(self._b_closes))
        if n < max(self._effective_lookback, 20):
            return

        # Periodically recalculate hedge ratio, half-life, and ADF
        self._bars_since_recalc += 1
        if self._bars_since_recalc >= self._config.recalc_every or not self._spreads:
            self._recalculate_model(n)
            self._bars_since_recalc = 0

        # Compute current spread
        close_a = self._closes[-1]
        close_b = self._b_closes[-1]
        spread = close_a - self._hedge_ratio * close_b - self._intercept
        self._spreads.append(spread)

        if len(self._spreads) < self._effective_lookback:
            return

        # ADF gate: only trade if spread is stationary enough
        if self._current_adf > self._config.min_adf_stat:
            return

        z = zscore(self._spreads, self._effective_lookback)
        cfg = self._config

        # Entry logic
        if self._position == 0:
            w = self._spreads[-self._effective_lookback:]
            self._spread_std = _std(w, ddof=1) or 1.0
            self._spread_entry = spread

            if z > cfg.entry_threshold:
                # Spread is too high → sell spread (short A, long B)
                self._sell()
                logger.debug(
                    "SELL spread: z=%.2f hedge=%.4f spread=%.4f",
                    z, self._hedge_ratio, spread,
                )
            elif z < -cfg.entry_threshold:
                # Spread is too low → buy spread (long A, short B)
                self._buy()
                logger.debug(
                    "BUY spread: z=%.2f hedge=%.4f spread=%.4f",
                    z, self._hedge_ratio, spread,
                )

        # Exit logic
        elif self._position != 0:
            spread_move = (spread - self._spread_entry) * self._position
            stop_breach = spread_move < -cfg.stoploss_factor * self._spread_std

            if abs(z) < cfg.exit_threshold or stop_breach:
                if stop_breach:
                    logger.debug(
                        "STOPLOSS exit: z=%.2f spread_move=%.4f", z, spread_move,
                    )
                if self._position > 0:
                    self._sell()
                else:
                    self._buy()
                self._flat()

        # Update daily returns for walk-forward adapter
        current_equity = 1.0 + sum(self._spreads) / max(1, len(self._spreads))
        if self._prev_equity > 0:
            self.daily_returns.append((current_equity - self._prev_equity) / self._prev_equity)
        self._prev_equity = current_equity

    def on_signal(self, signal: dict[str, Any]) -> None:  # noqa: D401
        pass

    def generate_orders(self) -> list[Order]:
        """Return and clear pending orders."""
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders

    # ------------------------------------------------------------------
    # Model calculation
    # ------------------------------------------------------------------

    def _recalculate_model(self, n: int) -> None:
        """Recalculate hedge ratio, intercept, ADF stat, and OU half-life."""
        lookback = self._config.lookback
        window = min(n, max(lookback * 2, 60))

        y = self._closes[-window:]
        x = self._b_closes[-window:]

        self._hedge_ratio, self._intercept = _ols(y, x)

        # Recompute spread history up to current window
        spread_w = [
            y[i] - self._hedge_ratio * x[i] - self._intercept
            for i in range(len(y))
        ]

        # ADF on the cointegration residuals
        self._current_adf = _adf_test(spread_w)

        # OU half-life to set effective lookback
        if self._config.auto_halflife and len(spread_w) >= 10:
            hl = ou_half_life(spread_w)
            if hl >= 2:
                self._effective_lookback = max(
                    self._config.lookback,
                    int(math.ceil(hl * 2)),
                )

        logger.debug(
            "Model recalc: hedge=%.4f adf=%.3f hl_lookback=%d",
            self._hedge_ratio, self._current_adf, self._effective_lookback,
        )


# ---------------------------------------------------------------------------
# Convenience function for pair selection
# ---------------------------------------------------------------------------


def select_best_pair(
    price_series: dict[str, list[float]],
    min_adf_stat: float = -2.86,
) -> list[tuple[str, str, float, float]]:
    """Score all pairs in a universe by cointegration strength.

    Args:
        price_series: Mapping of symbol → price list (equal-length).
        min_adf_stat: ADF threshold to include a pair (default -2.86 = 5%).

    Returns:
        List of (symbol_a, symbol_b, hedge_ratio, adf_stat) tuples,
        sorted by ADF stat (most negative first = strongest cointegration).
    """
    symbols = list(price_series.keys())
    results: list[tuple[str, str, float, float]] = []

    for i in range(len(symbols)):
        for j in range(i + 1, len(symbols)):
            sym_a = symbols[i]
            sym_b = symbols[j]
            y = price_series[sym_a]
            x = price_series[sym_b]
            hedge_ratio, adf_stat = cointegration_test(y, x)
            if adf_stat <= min_adf_stat:
                results.append((sym_a, sym_b, hedge_ratio, adf_stat))

    results.sort(key=lambda r: r[3])  # most negative first
    return results


__all__ = [
    "StatPairsTrading",
    "PairsTradingConfig",
    "cointegration_test",
    "adf_stationarity",
    "ou_half_life",
    "zscore",
    "select_best_pair",
]
