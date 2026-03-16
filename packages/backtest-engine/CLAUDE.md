# FlintTrade — backtest-engine

> Event-driven simulation engine, vectorbt strategies, metrics, walk-forward

## Absorbs
- openengine → Backtester class, YahooFinance/OpenAlgo connectors, live trader
- vectorbt-backtesting-skills → 12 strategy templates, TA-Lib indicators, QuantStats tearsheets
- openalgo-backtrader (p2c2e) → Backtrader integration

## Depends on: core, historical, engine

## Rules
- Read root CLAUDE.md for project-wide rules
- Use packages/core/src/openalgo_client.py for ALL OpenAlgo API calls
- Never reference specific brokers
- Write tests in tests/test_backtest_engine.py
- Log work in root DEVLOG.md
- Branch: feature/backtest-engine-{description}

## Additional pip libraries
- quantstats — tearsheet generation, monthly returns heatmap, Sharpe/Sortino
- ta-lib — 150+ technical indicators (C library, much faster than pure Python)
- py_vollib_vectorized — options pricing during backtest simulation
