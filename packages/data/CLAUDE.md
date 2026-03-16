# FlintTrade — data

> Real-time tick capture, WebSocket storage, trade logs, SEBI audit trails

## Absorbs
- openquest → QuestDB tick aggregation, multi-exchange streaming, TradingView charts

## Depends on: core

## Rules
- Read root CLAUDE.md for project-wide rules
- Use packages/core/src/openalgo_client.py for ALL OpenAlgo API calls
- Never reference specific brokers
- Write tests in tests/test_data.py
- Log work in root DEVLOG.md
- Branch: feature/data-{description}

## Crypto data (Delta Exchange)
- 24/7 tick data — storage grows continuously (no market close)
- Funding rate snapshots every 8 hours
- Liquidation events as separate data stream
- Use CCXT for supplementary crypto data if needed
