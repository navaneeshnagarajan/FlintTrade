# FlintTrade — historical

> Historical data download, merge, DuckDB/Parquet, free NSE data

## Absorbs
- historify → DuckDB pipeline, data management UI, scheduler
- openchart → Free NSE/NFO historical data library (pip install openchart, no broker API needed)

## Depends on: core

## Rules
- Read root CLAUDE.md for project-wide rules
- Use packages/core/src/openalgo_client.py for ALL OpenAlgo API calls
- Never reference specific brokers
- Tests are in the `tests/` directory. Add new test files as needed.
- Update root CHANGELOG.md
- Branch: main (pre-release, all commits to main)

## Multi-exchange data
- Support historical data for ALL exchanges: NSE, BSE, NFO, BFO, CDS, BCD, MCX, NCDEX
- MCX data includes evening session (post 3:30 PM)
- Expired commodity options available via broker API (some brokers provide 5yr data)
- openchart library provides free NSE/NFO data only — MCX/CDS needs broker API via OpenAlgo

## Crypto historical data
- Delta Exchange historical via OpenAlgo API
- Supplementary: yfinance for BTC/ETH/commodity prices (free)
- Supplementary: `pip install ccxt` for exchange-specific historical (optional, not currently integrated)
- MCX commodity data: yfinance provides GOLD, SILVER, CRUDE in INR
