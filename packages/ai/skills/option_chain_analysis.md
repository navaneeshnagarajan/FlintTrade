---
name: option_chain_analysis
category: analysis
description: Reading and trading option chains — OI, PCR, max pain, IV skew interpretation
---
# Option Chain Analysis

## Key Metrics to Read

### Open Interest (OI)
- **High Call OI at a strike** → resistance — writers don't expect price to cross it
- **High Put OI at a strike** → support — writers don't expect price to fall below it
- **OI build-up with price rise** → bullish confirmation (fresh longs)
- **OI build-up with price fall** → bearish confirmation (fresh shorts)
- **OI unwinding** → trend exhaustion — participants exiting

### Put-Call Ratio (PCR)
- PCR = Total Put OI / Total Call OI
- PCR > 1.2 → contrarian bullish (excess put writing = market expects support)
- PCR < 0.7 → contrarian bearish (excess call writing = market expects ceiling)
- PCR 0.8–1.2 → neutral/range-bound
- Use PCR on Nifty/BankNifty weeklies as the most liquid measure

### Max Pain
- The strike price where option writers (who hold most OI) lose the least
- Prices tend to gravitate toward max pain near expiry
- Most reliable in the final 3 days before expiry
- Max pain ≠ guaranteed target — treat as a magnetic zone, not a prediction

### Implied Volatility (IV)
- High IV → expensive options, prefer selling strategies
- Low IV → cheap options, prefer buying strategies
- IV Percentile > 80 → sell premium (strangles, iron condors)
- IV Percentile < 20 → buy premium (straddles near events)
- IV skew: higher Put IV than Call IV → fear premium, participants buying downside protection

## Trading Setups from Option Chain

### Range-Bound Market
1. Check PCR near 1.0, high OI walls on both sides
2. Sell ATM straddle or strangle inside the range
3. Place stop-loss if OI wall breaks with volume

### Directional Breakout
1. Watch for OI unwinding on one side + build-up on the other
2. Buy ITM option in the breakout direction (lower theta decay)
3. Set target at next OI resistance/support

### Expiry Day
1. Monitor max pain level — price often converges
2. Sell OTM options if price is far from max pain with 2h to expiry
3. Watch for pin risk near ATM strikes

## Data Source
Use `/api/v1/optionchain` — returns strikes, call OI, put OI, call IV, put IV, LTP for each strike.
