"""FlintTrade tick-engine — high-performance Rust/PyO3 backtesting simulator.

This package exposes a compiled Rust extension for tick-level backtesting.
The Rust core handles bar-by-bar simulation with configurable slippage,
commission, and lot size — orders of magnitude faster than pure Python.

Classes
-------
TickSimulator
    Main simulator. Accepts OHLCV bars and signals, returns SimulationResult.
Bar
    OHLCV bar dataclass (timestamp, open, high, low, close, volume).
Trade
    Completed trade record (entry/exit times, prices, P&L, direction).
SimulationResult
    Full simulation output (total_pnl, sharpe_ratio, max_drawdown, win_rate,
    total_trades, trades list, equity_curve).

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

from tick_engine.tick_engine import Bar, SimulationResult, TickSimulator, Trade

__all__ = ["Bar", "SimulationResult", "TickSimulator", "Trade"]
__version__ = "0.1.0"
