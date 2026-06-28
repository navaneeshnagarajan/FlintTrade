---
name: risk_management
category: analysis
description: Position sizing, stop-loss placement, and portfolio risk-limit modelling for Indian F&O workflows
---
# Risk Management for F&O Workflows

## Position Sizing

### Percent Risk Model
Model a fixed percentage of capital per simulated position. A conservative study band is 1–2% per position.

```
Quantity = (Account Capital × Risk%) / (Entry Price − Stop Loss Price)
```

Example: ₹10L account, 1% risk, entry at ₹500, SL at ₹480.
Quantity = (1,000,000 × 0.01) / (500 − 480) = 10,000/20 = 500 shares.

### For Options
Options can go to zero. Treat full premium paid as the maximum loss.
Example cap model: keep option premium exposure at or below 1% of simulated capital.
```
Max options premium = Account Capital × 0.01
```

### Lot-Based Sizing (F&O)
Nifty lot size = 75 | BankNifty lot size = 30 | Sensex lot size = 10
Lot-based simulations should use whole lots and round down when a model produces a fractional lot.

## Stop-Loss Placement

### Technical SL
- Below the last swing low (long) / above last swing high (short)
- Below/above a significant moving average (20 EMA, 50 EMA)
- Below/above a VWAP band

### ATR-Based SL
```
SL distance = 1.5 × ATR(14)
```
Adapts to current volatility — wider SL in volatile markets.

### Options SL
- Bought options: SL at 30–40% of premium paid (e.g., bought at ₹100, exit at ₹60)
- Sold options: SL at 2× premium received (e.g., sold at ₹50, exit when option reaches ₹100)

## Portfolio Risk Limits

| Limit | Conservative | Aggressive |
|---|---|---|
| Max single trade risk | 1% capital | 2% capital |
| Max daily loss | 3% capital | 5% capital |
| Max open trades | 5 | 10 |
| Max sector concentration | 25% | 40% |
| Max overnight F&O exposure | 10% capital | 25% capital |

## Kill Switch Rules
1. Daily loss > 3% → stop all new trades for the day
2. 3 consecutive losses → pause and review
3. Weekly loss > 7% → stop all trades, do post-mortem
4. Any single trade > 5% loss → emergency exit, review system

## Margin Management
Always maintain minimum 30% free margin buffer. Never deploy >70% of available margin.
Monitor using `/api/v1/funds` before each new position.
