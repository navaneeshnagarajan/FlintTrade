# FlintTrade — screener

> Market scanner, OI spurt, PCR, max pain, futures quadrant, portfolio Greeks

## Absorbs
- openalgo-portfoliogreeks → Black-Scholes portfolio Greeks, lot-based, position-aware signs

## Depends on: core, data

## Rules
- Read root CLAUDE.md for project-wide rules
- Use packages/core/src/openalgo_client.py for ALL OpenAlgo API calls
- Never reference specific brokers
- Write tests in tests/test_screener.py
- Log work in root DEVLOG.md
- Branch: feature/screener-{description}

## Additional pip libraries
- py_vollib_vectorized — vectorized Black-Scholes Greeks (use this over hand-rolled math)
- mibian — simple options pricing for quick calculations
- NSE-Option-Chain-Analyzer (VarunS2002) — reference for OI trend analysis patterns

## Feature scope clarification
- screener CALCULATES: Greeks, PCR, max pain, OI analysis, support/resistance from OI
- terminal DISPLAYS the results from screener
- dashboard shows portfolio-level Greeks summary from screener

## Multi-exchange Greeks
- MCX options have different expiry times (11:30 PM) — affects theta calculation
- CDS options expire at 12:30 PM — affects time decay near expiry
- Must pass correct expiry_time to OpenAlgo's /api/v1/optiongreeks endpoint
- MCX Greeks require commodity-specific risk-free rates

## Crypto screening
- BTC/ETH options Greeks via Delta Exchange
- Funding rate arbitrage detection (perpetuals vs futures)
- Cross-exchange price comparison (requires ccxt)

## Free data sources (no broker API needed)
- nsepython — NSE option chain, FII/DII data, PCR, advance/decline
- openchart — Free NSE/NFO historical data
- yfinance — Free global data including MCX commodities
