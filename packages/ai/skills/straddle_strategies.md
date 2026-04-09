---
name: straddle_strategies
category: strategy
description: MTM straddle and strangle execution patterns for Indian F&O expiry trading
---
# Straddle and Strangle Strategies

## ATM Straddle (Short)

**Setup:** Sell ATM Call + Sell ATM Put of the same expiry.

**When to use:**
- IV Percentile > 70 (expensive premium)
- No major event (earnings, RBI policy, budget) within the expiry period
- Market in consolidation — low ADX, narrow Bollinger Bands

**Entry:** Sell both legs at market open (9:20–9:25 IST) after gap settles.

**Profit zone:** Price stays within the straddle's breakeven range.
- Upper BE = Strike + Total Premium Received
- Lower BE = Strike − Total Premium Received

**Exit rules:**
1. MTM profit target: 30–40% of premium collected
2. Stop-loss: 2× premium collected (combined)
3. Time stop: Close before 3:15 IST on expiry day regardless of P&L

**Adjustment (delta hedge):**
- If underlying moves >0.5× ATM strike distance, buy a far OTM option in the direction of move to cap loss

## ATM Strangle (Short)

**Setup:** Sell OTM Call + Sell OTM Put, typically 1–2 strikes away from ATM.

**Advantage over straddle:** Wider profit zone, less capital at risk per trade.
**Disadvantage:** Lower premium collected.

**Typical strikes for Nifty:** Sell strikes ±100–200 points from spot.

## Straddle MTM Monitor

Track: Combined MTM P&L, individual leg delta, net delta (should stay near 0 for delta-neutral).

Alert thresholds:
- Net delta > ±0.3 → re-hedge or exit
- MTM loss > 1.5× premium → exit immediately

## Weekly vs Monthly

| | Weekly (Thursday expiry) | Monthly (last Thursday) |
|---|---|---|
| Theta decay | Fast — accelerates Wednesday/Thursday | Slower |
| Liquidity | High for Nifty/BankNifty | High |
| Event risk | Lower | Higher (RBI, results season) |

## Execution via OpenAlgo

```python
# Sell ATM straddle
placeorder(symbol="NIFTY26APR25000CE", exchange="NFO", action="SELL",
           product="MIS", quantity=50, price_type="MARKET")
placeorder(symbol="NIFTY26APR25000PE", exchange="NFO", action="SELL",
           product="MIS", quantity=50, price_type="MARKET")
```

Always use `MIS` product for intraday straddles — auto-squared off by broker.
