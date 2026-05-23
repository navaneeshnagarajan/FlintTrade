---
name: fii_dii_analysis
category: analysis
description: How to interpret FII/DII cash market and derivatives data for market direction
---
# FII / DII Analysis

## What FII/DII Data Tells You

**FII (Foreign Institutional Investors):** Largest movers of Indian markets. Their flows in equity + derivatives give a leading signal for index direction.

**DII (Domestic Institutional Investors):** Mutual funds, insurance companies. Often counter-trade FIIs — buy when FIIs sell (SIP inflows are steady).

## Cash Market Data

Published by NSE/BSE after market close daily.

| Reading | Interpretation |
|---|---|
| FII net buyers (large) | Bullish — foreign capital flowing in |
| FII net sellers (large) | Bearish — risk-off, consider hedging |
| DII net buyers with FII selling | Domestic support; may limit downside but not drive rally |
| Both FII + DII buying | Strong bullish signal |
| Both FII + DII selling | High probability of significant fall |

## Derivatives Data (More Important)

FII derivative positions reveal their hedging intent vs directional bets:

- **FII Long Index Futures:** Bullish directional bet → market likely to rise
- **FII Short Index Futures:** Bearish directional bet or hedging equity longs
- **FII Long/Short Ratio > 70%:** Bullish sentiment; > 75% often signals overextension
- **FII Long/Short Ratio < 40%:** Bearish sentiment

## Interpreting Combined Signals

### Bullish Setup
- FII cash: net buyers 3+ consecutive days
- FII derivatives: net long index futures, long/short > 65%
- DII: neutral to buyers
- Action: bias long on Nifty/BankNifty

### Bearish Setup
- FII cash: net sellers
- FII derivatives: increasing short index futures
- DII: heavy buyers (not enough to offset FII selling)
- Action: bias short or hedge portfolio with puts

### Divergence (watch carefully)
- FII selling cash but buying futures → hedged rebalancing, not directional
- FII buying cash but shorting futures → cautious accumulation with hedge

## Data Sources

- NSE daily F&O participant data: `www.nseindia.com/market-data/fii-dii-activity`
- FII derivative stats: published by NSE every evening

## Weekly Trend
3–5 day cumulative flow more reliable than single-day reading. Compute 5-day rolling sum of FII net flow for trend confirmation.
