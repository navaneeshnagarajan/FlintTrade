"""Performance metrics calculator.

Computes risk/return metrics from backtest results: Sharpe, Sortino, Calmar,
drawdowns, trade statistics, monthly returns, VaR, and more.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

try:
    from .simulator import BacktestResult, EquityPoint, SimTrade
except ImportError:
    from simulator import BacktestResult, EquityPoint, SimTrade

# Annualization factors
_TRADING_DAYS_PER_YEAR = 252
_RISK_FREE_RATE = 0.07  # India — 7% risk-free rate


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DrawdownInfo:
    """Drawdown statistics."""

    max_drawdown_pct: float = 0.0
    max_drawdown_duration_bars: int = 0
    avg_drawdown_pct: float = 0.0
    current_drawdown_pct: float = 0.0


@dataclass
class TradeStats:
    """Trade-level statistics."""

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    avg_bars_held: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0


@dataclass
class MonthlyReturn:
    """Single month return entry."""

    year: int
    month: int
    return_pct: float


@dataclass
class TimeAnalysis:
    """Best/worst by time period."""

    best_hour: int = -1
    worst_hour: int = -1
    best_day_of_week: int = -1   # 0=Mon..4=Fri
    worst_day_of_week: int = -1


@dataclass
class RiskMetrics:
    """Risk metrics."""

    var_95: float = 0.0     # Value at Risk 95%
    cvar_95: float = 0.0    # Conditional VaR (Expected Shortfall)
    volatility: float = 0.0  # Annualized


@dataclass
class PerformanceReport:
    """Complete performance metrics report."""

    total_return_pct: float = 0.0
    cagr: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    drawdown: DrawdownInfo = field(default_factory=DrawdownInfo)
    trade_stats: TradeStats = field(default_factory=TradeStats)
    monthly_returns: list[MonthlyReturn] = field(default_factory=list)
    time_analysis: TimeAnalysis = field(default_factory=TimeAnalysis)
    risk: RiskMetrics = field(default_factory=RiskMetrics)
    pnl_histogram: list[float] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core calculation functions
# ---------------------------------------------------------------------------


def compute_returns(equity_curve: list[EquityPoint]) -> list[float]:
    """Compute per-bar percentage returns from equity curve."""
    if len(equity_curve) < 2:
        return []
    returns = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1].equity
        curr = equity_curve[i].equity
        if prev > 0:
            returns.append((curr - prev) / prev)
        else:
            returns.append(0.0)
    return returns


def compute_sharpe(returns: list[float], risk_free: float = _RISK_FREE_RATE) -> float:
    """Annualized Sharpe ratio."""
    if len(returns) < 2:
        return 0.0
    mean_r = sum(returns) / len(returns)
    std_r = _std(returns)
    if std_r == 0:
        return 0.0
    daily_rf = risk_free / _TRADING_DAYS_PER_YEAR
    return (mean_r - daily_rf) / std_r * math.sqrt(_TRADING_DAYS_PER_YEAR)


def compute_sortino(returns: list[float], risk_free: float = _RISK_FREE_RATE) -> float:
    """Annualized Sortino ratio (uses downside deviation)."""
    if len(returns) < 2:
        return 0.0
    mean_r = sum(returns) / len(returns)
    daily_rf = risk_free / _TRADING_DAYS_PER_YEAR
    downside = [min(0, r - daily_rf) for r in returns]
    dd_sq = sum(d ** 2 for d in downside) / len(downside)
    downside_dev = math.sqrt(dd_sq)
    if downside_dev == 0:
        return 0.0
    return (mean_r - daily_rf) / downside_dev * math.sqrt(_TRADING_DAYS_PER_YEAR)


def compute_cagr(
    initial: float, final: float, bars: int, bars_per_year: float = _TRADING_DAYS_PER_YEAR,
) -> float:
    """Compound Annual Growth Rate."""
    if initial <= 0 or final <= 0 or bars <= 0:
        return 0.0
    years = bars / bars_per_year
    if years <= 0:
        return 0.0
    return ((final / initial) ** (1 / years) - 1) * 100


def compute_max_drawdown(equity_curve: list[EquityPoint]) -> DrawdownInfo:
    """Compute max drawdown, duration, and average drawdown."""
    if not equity_curve:
        return DrawdownInfo()

    peak = equity_curve[0].equity
    max_dd = 0.0
    max_dd_duration = 0
    current_dd_duration = 0
    drawdowns: list[float] = []

    for pt in equity_curve:
        if pt.equity > peak:
            peak = pt.equity
            current_dd_duration = 0
        dd = (peak - pt.equity) / peak * 100 if peak > 0 else 0.0
        if dd > 0:
            drawdowns.append(dd)
            current_dd_duration += 1
        if dd > max_dd:
            max_dd = dd
        max_dd_duration = max(max_dd_duration, current_dd_duration)

    return DrawdownInfo(
        max_drawdown_pct=max_dd,
        max_drawdown_duration_bars=max_dd_duration,
        avg_drawdown_pct=sum(drawdowns) / len(drawdowns) if drawdowns else 0.0,
        current_drawdown_pct=equity_curve[-1].drawdown if equity_curve else 0.0,
    )


def compute_trade_stats(trades: list[SimTrade]) -> TradeStats:
    """Compute trade-level statistics."""
    if not trades:
        return TradeStats()

    wins = [t for t in trades if t.net_pnl > 0]
    losses = [t for t in trades if t.net_pnl <= 0]

    total_win = sum(t.net_pnl for t in wins)
    total_loss = abs(sum(t.net_pnl for t in losses))

    avg_win = total_win / len(wins) if wins else 0.0
    avg_loss = total_loss / len(losses) if losses else 0.0

    profit_factor = total_win / total_loss if total_loss > 0 else float("inf") if total_win > 0 else 0.0

    win_rate = len(wins) / len(trades) * 100 if trades else 0.0
    expectancy = avg_win * (win_rate / 100) - avg_loss * (1 - win_rate / 100)

    # Consecutive wins/losses
    max_consec_w, max_consec_l = 0, 0
    curr_w, curr_l = 0, 0
    for t in trades:
        if t.net_pnl > 0:
            curr_w += 1
            curr_l = 0
        else:
            curr_l += 1
            curr_w = 0
        max_consec_w = max(max_consec_w, curr_w)
        max_consec_l = max(max_consec_l, curr_l)

    pnls = [t.net_pnl for t in trades]

    return TradeStats(
        total_trades=len(trades),
        winning_trades=len(wins),
        losing_trades=len(losses),
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        profit_factor=profit_factor,
        expectancy=expectancy,
        max_consecutive_wins=max_consec_w,
        max_consecutive_losses=max_consec_l,
        avg_bars_held=sum(t.bars_held for t in trades) / len(trades) if trades else 0,
        largest_win=max(pnls) if pnls else 0.0,
        largest_loss=min(pnls) if pnls else 0.0,
    )


def compute_monthly_returns(equity_curve: list[EquityPoint]) -> list[MonthlyReturn]:
    """Group equity curve into monthly returns."""
    if len(equity_curve) < 2:
        return []

    # Group by (year, month)
    months: dict[tuple[int, int], list[EquityPoint]] = {}
    for pt in equity_curve:
        ts = pt.timestamp[:7]  # "YYYY-MM"
        try:
            parts = ts.split("-")
            key = (int(parts[0]), int(parts[1]))
        except (ValueError, IndexError):
            continue
        months.setdefault(key, []).append(pt)

    results: list[MonthlyReturn] = []
    sorted_keys = sorted(months.keys())
    prev_equity = equity_curve[0].equity

    for key in sorted_keys:
        pts = months[key]
        end_eq = pts[-1].equity
        ret = ((end_eq - prev_equity) / prev_equity * 100) if prev_equity > 0 else 0.0
        results.append(MonthlyReturn(year=key[0], month=key[1], return_pct=ret))
        prev_equity = end_eq

    return results


def compute_var(returns: list[float], confidence: float = 0.95) -> tuple[float, float]:
    """Value at Risk and Conditional VaR (Expected Shortfall).

    Returns (VaR, CVaR) as positive loss percentages.
    """
    if not returns:
        return 0.0, 0.0

    sorted_r = sorted(returns)
    idx = int((1 - confidence) * len(sorted_r))
    idx = max(0, min(idx, len(sorted_r) - 1))
    var = -sorted_r[idx] * 100  # Convert to positive %
    tail = sorted_r[: idx + 1]
    cvar = -sum(tail) / len(tail) * 100 if tail else 0.0
    return var, cvar


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class PerformanceMetrics:
    """Compute all performance metrics from a BacktestResult.

    Usage::

        metrics = PerformanceMetrics()
        report = metrics.compute(backtest_result)
        print(f"Sharpe: {report.sharpe_ratio}")
    """

    @staticmethod
    def compute(result: BacktestResult) -> PerformanceReport:
        """Compute full performance report."""
        returns = compute_returns(result.equity_curve)
        dd = compute_max_drawdown(result.equity_curve)
        ts = compute_trade_stats(result.trades)
        monthly = compute_monthly_returns(result.equity_curve)

        sharpe = compute_sharpe(returns)
        sortino = compute_sortino(returns)
        cagr = compute_cagr(
            result.config.initial_capital, result.final_equity, result.total_bars,
        )
        calmar = cagr / dd.max_drawdown_pct if dd.max_drawdown_pct > 0 else 0.0

        var_95, cvar_95 = compute_var(returns, 0.95)
        vol = _std(returns) * math.sqrt(_TRADING_DAYS_PER_YEAR) * 100 if returns else 0.0

        return PerformanceReport(
            total_return_pct=result.total_return_pct,
            cagr=cagr,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            drawdown=dd,
            trade_stats=ts,
            monthly_returns=monthly,
            risk=RiskMetrics(var_95=var_95, cvar_95=cvar_95, volatility=vol),
            pnl_histogram=[t.net_pnl for t in result.trades],
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _std(values: list[float]) -> float:
    """Sample standard deviation."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)
