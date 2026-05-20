# FlintTrade — data

> Real-time tick capture, WebSocket storage, trade logs, SEBI audit trails, order flow, P&L tracking, tax reports

## Key Modules
- `tick_recorder.py` — Real-time tick capture and storage
- `trade_logger.py` — Trade event logging
- `audit_logger.py` — SEBI 5-year audit trail compliance
- `orderflow.py` / `orderflow_routes.py` — Order flow analysis and API routes
- `pnl_tracker.py` / `pnl_routes.py` — P&L tracking and API routes
- `tax_report.py` / `tax_routes.py` — Tax report generation and API routes
- `storage.py` — DuckDB storage layer

## Absorbs
- openquest → QuestDB tick aggregation, multi-exchange streaming, TradingView charts

## Depends on: core

## Rules
- Read root CLAUDE.md for project-wide rules
- Use packages/core/src/openalgo_client.py for ALL OpenAlgo API calls
- Never reference specific brokers
- Tests are in the `tests/` directory. Add new test files as needed.
- Update root CHANGELOG.md
- Branch: main (pre-release, all commits to main)

## Crypto data (Delta Exchange)
- 24/7 tick data — storage grows continuously (no market close)
- Funding rate snapshots every 8 hours
- Liquidation events as separate data stream
- Use CCXT for supplementary crypto data if needed
