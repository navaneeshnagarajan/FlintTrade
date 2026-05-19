# FlintTrade — backtest-engine

> Event-driven simulation engine, vectorbt strategies, metrics, walk-forward

## Absorbs
- openengine → Backtester class, YahooFinance/OpenAlgo connectors, live trader
- vectorbt-backtesting-skills → 94 strategy templates across 16 categories (live count in `src/strategies/`), TA-Lib indicators, QuantStats tearsheets
- openalgo-backtrader (p2c2e) → Backtrader integration pattern (reference-absorbed; `pip install backtrader` used where needed)

## Depends on: core, historical, engine

## Rules
- Read root CLAUDE.md for project-wide rules
- Use packages/core/src/openalgo_client.py for ALL OpenAlgo API calls
- Never reference specific brokers
- Tests are in the `tests/` directory. Add new test files as needed.
- Update root CHANGELOG.md
- Branch: main (pre-release, all commits to main)

## Additional pip libraries
- quantstats — tearsheet generation, monthly returns heatmap, Sharpe/Sortino
- ta-lib — 150+ technical indicators (C library, much faster than pure Python)
- py_vollib_vectorized — options pricing during backtest simulation
