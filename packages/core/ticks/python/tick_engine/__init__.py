"""FlintTrade tick-engine — high-performance Rust/PyO3 backtesting simulator.

This package exposes a compiled Rust extension for tick-level backtesting.
The Rust core handles bar-by-bar simulation with configurable slippage,
commission, and lot size — orders of magnitude faster than pure Python — plus
Monte Carlo confidence intervals, an intraday session tracker, and options
(single-leg + multi-leg spread) and pairs backtesters.

Status
------
The crate builds, imports, and is exercised by its Rust and Python test suites,
but it currently has **no production consumer** — no FlintTrade route, service,
or widget dispatches to it yet. It is kept as a ready, tested capability for a
future high-throughput backtest path. Re-exported in full here so the whole
compiled surface is importable from Python rather than only the four core
simulator types; wiring it into a backtest route is tracked separately.

Core simulation
---------------
``TickSimulator``
    Main simulator. Accepts OHLCV bars and signals, returns ``SimulationResult``.
``Bar``
    OHLCV bar (timestamp, open, high, low, close, volume).
``Trade``
    Completed trade record (entry/exit times, prices, P&L, direction).
``SimulationResult``
    Full simulation output (total_pnl, sharpe_ratio, max_drawdown, win_rate,
    total_trades, trades list, equity_curve).
``Tick`` / ``Signal`` / ``BacktestResult``
    Tick-level input, strategy signal, and generic backtest output types.

Monte Carlo
-----------
``simulate`` / ``simulate_correlated`` / ``confidence_intervals``
    Monte Carlo path simulation (independent or correlated) and CI extraction.

Session tracking
----------------
``SessionConfig`` / ``SessionState`` / ``SessionTracker``
    Intraday trading-session state machine (square-off windows, day boundaries).

Options
-------
``OptionType`` / ``OptionStrategyType`` / ``OptionsConfig`` / ``OptionsStrategy``
``Greeks`` / ``black_scholes_greeks``
    Options backtester and Black-Scholes greeks.
``LegConfig`` / ``SpreadConfig`` / ``SpreadBacktest`` / ``run_spreads_batch``
``straddle_config`` / ``strangle_config`` / ``iron_condor_config``
    Multi-leg spread configuration builders and batch spread backtester.

Pairs
-----
``PairsStrategy`` / ``run_batch``
    Pairs-trading strategy and batch runner.

Example
-------
>>> from tick_engine import TickSimulator
>>> sim = TickSimulator(initial_capital=100_000, commission=20.0)
>>> bars = [
...     [1700000000, 19000.0, 19100.0, 18950.0, 19050.0, 500000],
...     [1700000060, 19050.0, 19200.0, 19000.0, 19150.0, 600000],
... ]
>>> result = sim.run_ema_crossover(bars, fast_period=9, slow_period=21)
>>> print(result)
"""

from tick_engine.tick_engine import (
    BacktestResult,
    Bar,
    Greeks,
    LegConfig,
    OptionStrategyType,
    OptionsConfig,
    OptionsStrategy,
    OptionType,
    PairsStrategy,
    SessionConfig,
    SessionState,
    SessionTracker,
    Signal,
    SimulationResult,
    SpreadBacktest,
    SpreadConfig,
    Tick,
    TickSimulator,
    Trade,
    black_scholes_greeks,
    confidence_intervals,
    iron_condor_config,
    run_batch,
    run_spreads_batch,
    simulate,
    simulate_correlated,
    straddle_config,
    strangle_config,
)

__all__ = [
    # Core simulation
    "TickSimulator",
    "Bar",
    "Trade",
    "SimulationResult",
    "Tick",
    "Signal",
    "BacktestResult",
    # Monte Carlo
    "simulate",
    "simulate_correlated",
    "confidence_intervals",
    # Session tracking
    "SessionConfig",
    "SessionState",
    "SessionTracker",
    # Options
    "OptionType",
    "OptionStrategyType",
    "OptionsConfig",
    "OptionsStrategy",
    "Greeks",
    "black_scholes_greeks",
    "LegConfig",
    "SpreadConfig",
    "SpreadBacktest",
    "run_spreads_batch",
    "straddle_config",
    "strangle_config",
    "iron_condor_config",
    # Pairs
    "PairsStrategy",
    "run_batch",
]
__version__ = "0.6.0-beta.1"
