---
name: backtest_guide
category: strategy
description: How to use FlintTrade's backtest engine — data, metrics, walk-forward, pitfalls
---
# FlintTrade Backtest Guide

## Data Pipeline

Historical OHLCV data flows through the `historical` package:
- Source: OpenChart (free, NSE), yfinance (fallback)
- Storage: DuckDB at `~/.flinttrade/data/historical.duckdb`
- Resolutions: 1m, 3m, 5m, 15m, 30m, 1h, 1D
- Equity history: up to 20 years | F&O: up to 3 years (exchange limit)

Fetch via `historical` package before running any backtest.

## Strategy Structure

A backtest strategy must implement:
```python
def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    # df has columns: open, high, low, close, volume
    # Must return df with added column: signal (1=buy, -1=sell, 0=hold)
    ...
```

Entry/exit rules must be vectorised (pandas/numpy). Avoid Python loops for performance.

## Key Metrics

| Metric | Good | Acceptable |
|---|---|---|
| Annual Return | > 25% | > 15% |
| Sharpe Ratio | > 1.5 | > 1.0 |
| Sortino Ratio | > 2.0 | > 1.2 |
| Max Drawdown | < 15% | < 25% |
| Win Rate | > 55% | > 45% |
| Profit Factor | > 1.8 | > 1.3 |
| Calmar Ratio | > 1.5 | > 0.8 |

## Walk-Forward Testing

Purpose: Detect overfitting. A strategy that only works on training data is useless.

Steps:
1. Split data: 70% in-sample (IS), 30% out-of-sample (OOS)
2. Optimise parameters on IS only
3. Apply optimised parameters to OOS without touching
4. OOS Sharpe should be at least 70% of IS Sharpe

Rolling walk-forward: repeat in 6-month windows, check consistency.

## Monte Carlo Simulation

Randomises trade order 1,000 times to estimate the true distribution of outcomes.
- 5th percentile drawdown → worst realistic scenario
- Use this for position sizing, not the average-case drawdown

## Common Backtesting Pitfalls

1. **Look-ahead bias** — using future data in signal calculation. Always use `.shift(1)`.
2. **Survivorship bias** — testing only currently-listed stocks. Index constituent history matters.
3. **Overfitting** — too many parameters, too short a test period. Rule: minimum 100 trades.
4. **Ignoring slippage** — use 0.05% per trade for liquid stocks, 0.1%+ for small-caps.
5. **Ignoring impact costs** — large orders move the market. Limit position size to <1% of daily volume.

## Accessing the Backtest Engine

```python
from packages.backtest_engine.src.simulator import BacktestSimulator

sim = BacktestSimulator(symbol="NIFTY", exchange="NSE_INDEX",
                        start="2023-01-01", end="2024-12-31",
                        interval="1D")
results = sim.run(strategy_fn=generate_signals, initial_capital=100000)
print(results.sharpe, results.max_drawdown)
```
