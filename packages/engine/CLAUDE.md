# FlintTrade — engine

> Strategy execution, order routing, 5-layer safety, kill switches, scheduler, action center, sandbox, social trading

## Key Modules
- `strategy.py` — Base strategy interface
- `strategy_runner.py` — Strategy execution engine
- `strategy_lifecycle.py` — Strategy start/stop/pause lifecycle management
- `strategy_routes.py` — Strategy API routes
- `strategies/` — Live strategy implementations (currently 2: `ema_crossover.py`, `wheel_live.py`). The 94 backtest-only templates live in `packages/backtest-engine/src/strategies/`.
- `router.py` — Order routing with smart execution
- `safety.py` — 5-layer safety system and kill switches
- `scheduler.py` — Cron-based strategy scheduling
- `action_center.py` / `action_center_routes.py` — Action center for manual interventions
- `sandbox.py` / `sandbox_routes.py` — Paper trading sandbox mode
- `social_trading.py` — Social trading / copy trading

## Absorbs
- openengine → event-driven architecture, BaseStrategy interface, live trader
- algomirror → strategy_executor.py parallel execution patterns

## Depends on: core

## Rules
- Read root CLAUDE.md for project-wide rules
- Use packages/core/src/openalgo_client.py for ALL OpenAlgo API calls
- Never reference specific brokers
- Tests are in the `tests/` directory. Add new test files as needed.
- Update root CHANGELOG.md
- Branch: main (pre-release, all commits to main)

## Multi-exchange safety
- Auto square-off times differ: equity 3:15 PM, currency 4:45 PM, MCX 11:30 PM
- Position limits may differ per exchange segment
- Rate limits apply across ALL exchanges combined (10 OPS total, not per exchange)

## Crypto safety (Delta Exchange)
- 24/7 market — no auto square-off time
- Leverage up to 100x — position size limits critical
- Liquidation price monitoring required
- Funding rate impact on perpetual positions
- No circuit breakers in crypto — wider stop losses needed
