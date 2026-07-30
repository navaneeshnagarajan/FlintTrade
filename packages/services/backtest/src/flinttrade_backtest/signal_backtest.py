"""Signal-array backtest with an optional Rust (tick_engine) accelerated path.

This module is the first production consumer of the ``flinttrade-ticks``
Rust/PyO3 crate (imported as ``tick_engine``). It provides a dependency-free
quick backtest for pre-computed signal arrays — the niche between the
event-driven ``BacktestSimulator`` (which needs a Python strategy object with
per-bar callbacks) and the optional vectorbt runner (a heavy extra that is not
installed by default).

Execution model (identical on both engines)
-------------------------------------------
A signal at bar ``i`` fills at the *next* bar's open (``open[i + 1]``) with
one-way fractional slippage and a flat per-order commission. The simulator
holds at most one position; an opposite signal closes it (re-entry happens on
a later non-zero signal). Any position still open at the end is closed at the
last bar's close with no slippage. The Sharpe ratio is annualised over 252
trading days from per-trade equity returns, and max drawdown is the largest
peak-to-trough fraction of the equity curve.

Engine selection (fail-closed)
------------------------------
The pure-Python reference implementation is the **default** and replicates the
Rust ``TickSimulator`` semantics operation-for-operation, so results are
byte-equivalent. The accelerated path is opt-in and import-guarded: the
desktop bootstrap deliberately excludes the wheel
(``uv sync --no-install-package flinttrade-ticks``), so its absence must never
break a caller.

- ``engine="python"`` (default): always the pure-Python path.
- ``engine="auto"``: uses ``tick_engine`` when importable, else falls back to
  the pure-Python path. Results are identical either way.
- ``engine="accelerated"``: requires the wheel; raises
  :class:`TickEngineNotAvailableError` when it is absent.

The Rust engine supplies the simulation state (equity curve, trades, P&L)
bit-for-bit; the two derived summary ratios (Sharpe, max drawdown) are always
computed in Python from that state, because the Rust Sharpe reduction is
sensitive to compiler FMA contraction and would otherwise drift by an ULP
between build hosts.

Usage::

    from flinttrade_backtest.signal_backtest import (
        SignalBacktestConfig, run_signal_backtest,
    )

    bars = [[ts, o, h, l, c, v], ...]
    signals = [0, 1, 0, 0, -1, 0]      # 1 = long, -1 = short, 0 = hold
    result = run_signal_backtest(bars, signals, engine="auto")
    print(result.total_pnl, result.sharpe_ratio, result.engine)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Sequence

try:
    import tick_engine as _tick_engine
except ImportError:
    _tick_engine = None  # type: ignore[assignment]

EngineName = Literal["python", "auto", "accelerated"]

_ANNUALISATION_FACTOR: float = 252.0


class TickEngineNotAvailableError(RuntimeError):
    """Raised when the flinttrade-ticks wheel is required but not installed."""


def is_tick_engine_available() -> bool:
    """Return ``True`` when the tick_engine Rust extension is importable."""
    return _tick_engine is not None


# ---------------------------------------------------------------------------
# Config / result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SignalBacktestConfig:
    """Configuration for a signal-array backtest.

    Field defaults mirror ``tick_engine.TickSimulator`` exactly.

    Attributes:
        initial_capital: Starting capital in INR.
        slippage_pct: One-way slippage as a fraction (0.001 = 0.1%).
        commission: Flat per-order commission in INR.
        lot_size: Units per trade.
    """

    initial_capital: float = 100_000.0
    slippage_pct: float = 0.001
    commission: float = 20.0
    lot_size: float = 1.0


@dataclass
class SignalTrade:
    """A completed round-trip trade from a signal-array backtest.

    Attributes:
        entry_time: Bar timestamp at entry (truncated to int).
        exit_time: Bar timestamp at exit (truncated to int).
        entry_price: Fill price at entry, including slippage.
        exit_price: Fill price at exit, including slippage.
        qty: Quantity (lot-size units).
        pnl: Realised P&L for this trade in INR.
        direction: 1 for long, -1 for short.
    """

    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    qty: float
    pnl: float
    direction: int


@dataclass
class SignalBacktestResult:
    """Full output of a signal-array backtest.

    Attributes:
        total_pnl: Net P&L (final capital minus initial capital).
        sharpe_ratio: Annualised Sharpe ratio over per-trade equity returns.
        max_drawdown: Maximum peak-to-trough drawdown fraction (0-1).
        win_rate: Fraction of trades that were profitable (0-1).
        total_trades: Number of completed trades.
        trades: Individual trade records.
        equity_curve: Capital after each bar (length = n_bars + 1).
        engine: Which engine produced the result: ``"python"`` or
            ``"tick-engine"``.
    """

    total_pnl: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    trades: list[SignalTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    engine: str = "python"


# ---------------------------------------------------------------------------
# Metric helpers (operation-for-operation ports of tick_engine metrics.rs)
# ---------------------------------------------------------------------------


def _sharpe_ratio(returns: Sequence[float]) -> float:
    """Annualised Sharpe ratio (252 trading-day basis, risk-free rate = 0).

    Exact port of ``tick_engine::metrics::sharpe_ratio``: same summation
    order, same ``n - 1`` variance denominator, same 1e-10 guard.

    Args:
        returns: Per-trade fractional returns.

    Returns:
        Annualised Sharpe ratio, or 0.0 with fewer than 2 observations.
    """
    if len(returns) < 2:
        return 0.0
    n = float(len(returns))
    mean = sum(returns) / n
    variance = sum((r - mean) * (r - mean) for r in returns) / (n - 1.0)
    std_dev = math.sqrt(variance)
    if std_dev < 1e-10:
        return 0.0
    return mean / std_dev * math.sqrt(_ANNUALISATION_FACTOR)


def _max_drawdown_frac(equity: Sequence[float]) -> float:
    """Maximum peak-to-trough drawdown as a fraction (0.0-1.0).

    Exact port of ``tick_engine::metrics::max_drawdown_frac``.

    Args:
        equity: Equity-curve values.

    Returns:
        Largest drawdown fraction observed, 0.0 for an empty curve.
    """
    if not equity:
        return 0.0
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        if peak > 0.0:
            dd = (peak - e) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


# ---------------------------------------------------------------------------
# EMA crossover signal generation (port of tick_engine lib.rs helpers)
# ---------------------------------------------------------------------------


def _compute_ema(values: Sequence[float], period: int) -> list[float | None]:
    """EMA series seeded with the simple mean of the first *period* values.

    Exact port of ``compute_ema`` in tick_engine's ``lib.rs`` (same seed, same
    smoothing-constant arithmetic, same operation order).

    Args:
        values: Input price series.
        period: EMA period; must be positive for a non-empty result.

    Returns:
        List of the same length as *values* with ``None`` before the seed.
    """
    result: list[float | None] = [None] * len(values)
    if not values or period <= 0 or len(values) < period:
        return result
    k = 2.0 / (float(period) + 1.0)
    seed = sum(values[:period]) / float(period)
    result[period - 1] = seed
    prev = seed
    for i in range(period, len(values)):
        ema = values[i] * k + prev * (1.0 - k)
        result[i] = ema
        prev = ema
    return result


def ema_crossover_signals(
    closes: Sequence[float],
    fast_period: int = 9,
    slow_period: int = 21,
) -> list[int]:
    """Generate EMA-crossover signals matching tick_engine's built-in strategy.

    A bullish cross (fast EMA crossing above slow) emits 1; a bearish cross
    emits -1; all other bars emit 0.

    Args:
        closes: Close-price series.
        fast_period: Fast EMA period; must be > 0 and < *slow_period*.
        slow_period: Slow EMA period; must be > 0.

    Returns:
        Signal list aligned with *closes*.

    Raises:
        ValueError: If either period is not positive or *fast_period* >= *slow_period*.
    """
    if fast_period <= 0 or slow_period <= 0:
        raise ValueError("fast_period and slow_period must be > 0")
    if fast_period >= slow_period:
        raise ValueError("fast_period must be less than slow_period")

    fast_ema = _compute_ema(closes, fast_period)
    slow_ema = _compute_ema(closes, slow_period)
    n = len(closes)
    signals = [0] * n
    for i in range(1, n):
        f = fast_ema[i]
        s = slow_ema[i]
        pf = fast_ema[i - 1]
        ps = slow_ema[i - 1]
        if f is None or s is None or pf is None or ps is None:
            continue
        if f > s and pf <= ps:
            signals[i] = 1
        elif f < s and pf >= ps:
            signals[i] = -1
    return signals


# ---------------------------------------------------------------------------
# Input validation / conversion
# ---------------------------------------------------------------------------


def _validate_and_convert(
    bars: Sequence[Sequence[float]],
    signals: Sequence[int],
) -> tuple[list[list[float]], list[int]]:
    """Validate inputs and coerce them to plain floats/ints.

    Mirrors the validation performed by ``TickSimulator.run`` so both engines
    reject the same inputs with the same error class.

    Args:
        bars: Rows of ``[timestamp, open, high, low, close, volume]``.
        signals: Signal per bar (1 = long, -1 = short, 0 = hold).

    Returns:
        Tuple of (converted bars, converted signals).

    Raises:
        ValueError: On length mismatch, empty bars, malformed rows, or
            signals outside the -1/0/1 domain.
    """
    if len(bars) != len(signals):
        raise ValueError(
            f"bars ({len(bars)}) and signals ({len(signals)}) must have the same length"
        )
    if len(bars) == 0:
        raise ValueError("bars cannot be empty")

    rows: list[list[float]] = []
    for i, bar in enumerate(bars):
        if len(bar) != 6:
            raise ValueError(
                f"bar at index {i} must have exactly 6 values "
                "(timestamp, open, high, low, close, volume)"
            )
        rows.append([float(v) for v in bar])

    converted: list[int] = []
    for index, signal in enumerate(signals):
        value = int(signal)
        if value not in (-1, 0, 1):
            raise ValueError(f"signal at index {index} must be -1, 0, or 1 (got {value})")
        converted.append(value)
    return rows, converted


def _coerce_timestamp(value: Any, index: int) -> float:
    """Convert a bar-dict timestamp to a float epoch value.

    Accepts numeric epochs, numeric strings, ISO-8601 strings, and
    ``datetime`` objects. Naive datetimes (and naive ISO strings) are
    interpreted as UTC so the conversion is deterministic across machines.

    Args:
        value: Raw ``timestamp`` value from a bar dict.
        index: Bar index, used in error messages.

    Returns:
        Epoch seconds as a float.

    Raises:
        ValueError: If the timestamp is missing or unparseable.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.timestamp()
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            pass
        try:
            dt = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(
                f"bar at index {index} has an unparseable timestamp: {value!r}"
            ) from exc
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.timestamp()
    raise ValueError(f"bar at index {index} is missing a usable 'timestamp' value")


def bars_from_dicts(bars: Sequence[dict[str, Any]]) -> list[list[float]]:
    """Convert OHLCV bar dicts to the 6-column row shape both engines accept.

    This bridges the dict-shaped bar data used across the backtest package
    (``timestamp``/``open``/``high``/``low``/``close``/``volume`` keys) to the
    ``[ts, o, h, l, c, v]`` rows expected by :func:`run_signal_backtest`.

    Args:
        bars: Bar dicts. ``timestamp`` may be a numeric epoch, a numeric or
            ISO-8601 string, or a ``datetime``; naive values are read as UTC.

    Returns:
        List of 6-float rows.

    Raises:
        ValueError: If any timestamp is missing or unparseable.
    """
    rows: list[list[float]] = []
    for i, bar in enumerate(bars):
        rows.append([
            _coerce_timestamp(bar.get("timestamp"), i),
            float(bar.get("open", 0.0)),
            float(bar.get("high", 0.0)),
            float(bar.get("low", 0.0)),
            float(bar.get("close", 0.0)),
            float(bar.get("volume", 0.0)),
        ])
    return rows


# ---------------------------------------------------------------------------
# Pure-Python reference engine (exact port of TickSimulator::run)
# ---------------------------------------------------------------------------


def _run_python(
    bars: list[list[float]],
    signals: list[int],
    config: SignalBacktestConfig,
) -> SignalBacktestResult:
    """Run the pure-Python reference simulation.

    Operation-for-operation port of ``TickSimulator::run`` in tick_engine's
    ``lib.rs``. Every arithmetic step is performed in the same order on IEEE
    binary64 values, so the results are byte-equivalent to the Rust engine.

    Args:
        bars: Validated 6-float rows.
        signals: Validated signal ints, aligned with *bars*.
        config: Simulation parameters.

    Returns:
        The completed :class:`SignalBacktestResult` (``engine="python"``).
    """
    n = len(bars)
    capital = config.initial_capital
    equity_curve: list[float] = [capital]

    in_trade = False
    entry_price = 0.0
    entry_time = 0
    direction = 0

    trades: list[SignalTrade] = []
    trade_returns: list[float] = []

    for i in range(n - 1):
        signal = signals[i]
        next_bar = bars[i + 1]
        next_open = next_bar[1]
        next_time = int(next_bar[0])

        if not in_trade and signal != 0:
            if signal > 0:
                fill_price = next_open * (1.0 + config.slippage_pct)
            else:
                fill_price = next_open * (1.0 - config.slippage_pct)
            capital -= config.commission
            entry_price = fill_price
            entry_time = next_time
            direction = signal
            in_trade = True
        elif in_trade and signal != 0 and signal != direction:
            if direction > 0:
                exit_price = next_open * (1.0 - config.slippage_pct)
            else:
                exit_price = next_open * (1.0 + config.slippage_pct)
            capital -= config.commission
            pnl = (exit_price - entry_price) * float(direction) * config.lot_size
            capital += pnl

            prev_equity = equity_curve[-1]
            ret = (capital - prev_equity) / prev_equity if prev_equity > 0.0 else 0.0
            trade_returns.append(ret)

            trades.append(SignalTrade(
                entry_time=entry_time,
                exit_time=next_time,
                entry_price=entry_price,
                exit_price=exit_price,
                qty=config.lot_size,
                pnl=pnl,
                direction=direction,
            ))
            in_trade = False
            direction = 0
        equity_curve.append(capital)

    if in_trade:
        last_bar = bars[n - 1]
        exit_price = last_bar[4]
        exit_time = int(last_bar[0])
        capital -= config.commission
        pnl = (exit_price - entry_price) * float(direction) * config.lot_size
        capital += pnl

        prev_equity = equity_curve[-1]
        ret = (capital - prev_equity) / prev_equity if prev_equity > 0.0 else 0.0
        trade_returns.append(ret)

        trades.append(SignalTrade(
            entry_time=entry_time,
            exit_time=exit_time,
            entry_price=entry_price,
            exit_price=exit_price,
            qty=config.lot_size,
            pnl=pnl,
            direction=direction,
        ))
    equity_curve.append(capital)

    total_pnl = capital - config.initial_capital
    total_trades = len(trades)
    win_count = sum(1 for t in trades if t.pnl > 0.0)
    win_rate = win_count / total_trades if total_trades > 0 else 0.0

    return SignalBacktestResult(
        total_pnl=total_pnl,
        sharpe_ratio=_sharpe_ratio(trade_returns),
        max_drawdown=_max_drawdown_frac(equity_curve),
        win_rate=win_rate,
        total_trades=total_trades,
        trades=trades,
        equity_curve=equity_curve,
        engine="python",
    )


# ---------------------------------------------------------------------------
# Accelerated engine (tick_engine dispatch)
# ---------------------------------------------------------------------------


def _require_tick_engine() -> None:
    """Raise :class:`TickEngineNotAvailableError` when the wheel is absent."""
    if _tick_engine is None:
        raise TickEngineNotAvailableError(
            "The flinttrade-ticks wheel (tick_engine) is not installed in this "
            "environment — it is optional and deliberately excluded by the "
            "desktop bootstrap. Install it with `uv sync` from the workspace "
            'root, or use engine="python".'
        )


def _trade_returns_from_curve(
    signals: Sequence[int],
    equity_curve: Sequence[float],
) -> list[float]:
    """Recover per-trade equity returns from a completed equity curve.

    The close-event bar indices are a pure function of the signal sequence
    (they involve no price arithmetic), and both engines record capital after
    bar ``i`` at ``equity_curve[i + 1]``. Each close's return is therefore
    exactly ``(curve[i + 1] - curve[i]) / curve[i]`` — the same expression, on
    the same bits, that the engines evaluate internally.

    Args:
        signals: The validated signal sequence the simulation ran on.
        equity_curve: The resulting equity curve (length ``len(signals) + 1``).

    Returns:
        Per-trade fractional returns in close order.
    """
    n = len(signals)
    in_trade = False
    direction = 0
    returns: list[float] = []

    for i in range(n - 1):
        signal = signals[i]
        if not in_trade and signal != 0:
            in_trade = True
            direction = signal
        elif in_trade and signal != 0 and signal != direction:
            prev = equity_curve[i]
            curr = equity_curve[i + 1]
            returns.append((curr - prev) / prev if prev > 0.0 else 0.0)
            in_trade = False
            direction = 0

    if in_trade:
        prev = equity_curve[n - 1]
        curr = equity_curve[n]
        returns.append((curr - prev) / prev if prev > 0.0 else 0.0)

    return returns


def _convert_rust_result(result: Any, signals: Sequence[int]) -> SignalBacktestResult:
    """Convert a ``tick_engine.SimulationResult`` to the shared result type.

    The primary simulation state (equity curve, trades, P&L, win rate) is
    taken from the Rust engine bit-for-bit — its per-bar arithmetic contains
    no fusable multiply-add chains, so it is byte-stable across builds. The
    two derived summary statistics (Sharpe ratio and max drawdown) are
    recomputed here in Python from that state: the Rust Sharpe reduction is
    sensitive to floating-point contraction (FMA), so deriving it in Python
    from the byte-equal equity curve keeps the full result bit-identical to
    the pure-Python engine on every build host.

    Args:
        result: A ``SimulationResult`` returned by ``TickSimulator``.
        signals: The validated signal sequence the simulation ran on.

    Returns:
        Equivalent :class:`SignalBacktestResult` (``engine="tick-engine"``).
    """
    trades = [
        SignalTrade(
            entry_time=t.entry_time,
            exit_time=t.exit_time,
            entry_price=t.entry_price,
            exit_price=t.exit_price,
            qty=t.qty,
            pnl=t.pnl,
            direction=int(t.direction),
        )
        for t in result.trades
    ]
    equity_curve = list(result.equity_curve)
    trade_returns = _trade_returns_from_curve(signals, equity_curve)
    return SignalBacktestResult(
        total_pnl=result.total_pnl,
        sharpe_ratio=_sharpe_ratio(trade_returns),
        max_drawdown=_max_drawdown_frac(equity_curve),
        win_rate=result.win_rate,
        total_trades=result.total_trades,
        trades=trades,
        equity_curve=equity_curve,
        engine="tick-engine",
    )


def _run_tick_engine(
    bars: list[list[float]],
    signals: list[int],
    config: SignalBacktestConfig,
) -> SignalBacktestResult:
    """Run the simulation on the Rust tick_engine.

    Args:
        bars: Validated 6-float rows.
        signals: Validated signal ints, aligned with *bars*.
        config: Simulation parameters.

    Returns:
        The completed :class:`SignalBacktestResult` (``engine="tick-engine"``).
    """
    sim = _tick_engine.TickSimulator(
        initial_capital=config.initial_capital,
        slippage_pct=config.slippage_pct,
        commission=config.commission,
        lot_size=config.lot_size,
    )
    return _convert_rust_result(sim.run(bars, signals), signals)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_signal_backtest(
    bars: Sequence[Sequence[float]],
    signals: Sequence[int],
    config: SignalBacktestConfig | None = None,
    engine: EngineName = "python",
) -> SignalBacktestResult:
    """Backtest a pre-computed signal array over OHLCV bars.

    Args:
        bars: Rows of ``[timestamp, open, high, low, close, volume]`` (use
            :func:`bars_from_dicts` to convert dict-shaped bars).
        signals: One signal per bar: 1 = enter long, -1 = enter short,
            0 = hold. A signal at index ``i`` fills at the open of bar
            ``i + 1``; an opposite signal closes the open position.
        config: Simulation parameters; defaults mirror
            ``tick_engine.TickSimulator``.
        engine: ``"python"`` (default, pure-Python reference), ``"auto"``
            (tick_engine when available, else Python), or ``"accelerated"``
            (tick_engine required).

    Returns:
        :class:`SignalBacktestResult`. The two engines produce byte-equivalent
        results.

    Raises:
        ValueError: On malformed inputs or an unknown *engine* value.
        TickEngineNotAvailableError: When ``engine="accelerated"`` and the
            flinttrade-ticks wheel is not installed.
    """
    if engine not in ("python", "auto", "accelerated"):
        raise ValueError(
            f'Unknown engine {engine!r}: expected "python", "auto" or "accelerated"'
        )

    cfg = config or SignalBacktestConfig()
    rows, sigs = _validate_and_convert(bars, signals)

    if engine == "accelerated":
        _require_tick_engine()
        return _run_tick_engine(rows, sigs, cfg)
    if engine == "auto" and _tick_engine is not None:
        return _run_tick_engine(rows, sigs, cfg)
    return _run_python(rows, sigs, cfg)


def run_ema_crossover_backtest(
    bars: Sequence[Sequence[float]],
    fast_period: int = 9,
    slow_period: int = 21,
    config: SignalBacktestConfig | None = None,
    engine: EngineName = "python",
) -> SignalBacktestResult:
    """Backtest the built-in EMA crossover strategy.

    Mirrors ``TickSimulator.run_ema_crossover``: signals are generated with
    :func:`ema_crossover_signals` and executed by :func:`run_signal_backtest`.

    Args:
        bars: Rows of ``[timestamp, open, high, low, close, volume]``.
        fast_period: Fast EMA period; must be > 0 and < *slow_period*.
        slow_period: Slow EMA period; must be > 0.
        config: Simulation parameters.
        engine: Same selection semantics as :func:`run_signal_backtest`.

    Returns:
        :class:`SignalBacktestResult`.

    Raises:
        ValueError: On invalid periods or malformed bars.
        TickEngineNotAvailableError: When ``engine="accelerated"`` and the
            flinttrade-ticks wheel is not installed.
    """
    if engine not in ("python", "auto", "accelerated"):
        raise ValueError(
            f'Unknown engine {engine!r}: expected "python", "auto" or "accelerated"'
        )
    if fast_period <= 0 or slow_period <= 0:
        raise ValueError("fast_period and slow_period must be > 0")
    if fast_period >= slow_period:
        raise ValueError("fast_period must be less than slow_period")

    if engine == "accelerated":
        _require_tick_engine()

    cfg = config or SignalBacktestConfig()
    rows, _ = _validate_and_convert(bars, [0] * len(bars))

    # Signal generation is a cheap O(n) pass and replicates the Rust built-in
    # exactly (asserted in the test suite), so both engines execute the same
    # signal array — only the simulation loop is dispatched.
    closes = [row[4] for row in rows]
    signals = ema_crossover_signals(closes, fast_period, slow_period)

    if engine == "accelerated" or (engine == "auto" and _tick_engine is not None):
        return _run_tick_engine(rows, signals, cfg)
    return _run_python(rows, signals, cfg)
