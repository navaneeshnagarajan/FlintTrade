---
name: risk_of_ruin
category: analysis
description: Calculating risk of ruin — Kelly criterion, optimal f, position sizing, drawdown recovery, variance drag
---
# Risk of Ruin

## What Is Risk of Ruin?

Risk of ruin (RoR) is the probability that a trading account is reduced to zero (or an unacceptable level) given a sequence of losses. Even a strategy with positive expectancy can go to zero with oversized positions.

## Simplified Risk of Ruin Formula

```
RoR = ((1 − Edge) / (1 + Edge)) ^ (Capital / Risk_per_trade)
```

Where `Edge = Win_rate − Loss_rate` (e.g. 55% wins → Edge = 0.10).

A 55% win-rate system risking 5% per trade has a measurable ruin probability. Risking 1% per trade makes ruin essentially impossible over a 1,000-trade sample.

## Kelly Criterion

Kelly tells you the mathematically optimal fraction of capital to bet:

```
Kelly % = W − (L / R)
```

- W = win probability (e.g. 0.55)
- L = loss probability (1 − W)
- R = average win / average loss ratio

Example: W=0.55, R=1.5 → Kelly = 0.55 − (0.45/1.5) = 0.55 − 0.30 = **25%**

Full Kelly is too aggressive for live trading. Use **Half-Kelly** (12.5% in this example) or **Quarter-Kelly** for a more conservative sizing that still captures most of the mathematical edge without the savage drawdowns full Kelly produces.

## Optimal f

Optimal f (Ralph Vince) is the fraction of capital to risk per trade that maximises the geometric growth rate of the account. Like Kelly, it is derived from the historical trade series:

```
Optimal_f = argmax [ product((1 + f × (trade_pnl / abs(max_loss)))) ]
```

In practice, optimal f produces very aggressive sizing. Trade at 20–30% of optimal f for safety.

## Drawdown Recovery Mathematics

Drawdown compounds against you:

| Drawdown | Required Recovery |
|----------|-----------------|
| 10% | 11.1% |
| 20% | 25.0% |
| 30% | 42.9% |
| 50% | 100.0% |
| 70% | 233.3% |

This is why stopping at a 20–25% drawdown is a hard rule — beyond that, recovery requires extraordinary performance.

## Variance Drag

Variance drag (geometric penalty) means that a strategy with positive arithmetic mean can still destroy capital when volatility is high:

```
Geometric mean ≈ Arithmetic mean − (Variance / 2)
```

A strategy returning 3% average per trade with 8% standard deviation has a geometric return of only 3% − 3.2% = **−0.2%** per trade — it will slowly ruin the account despite a positive arithmetic mean.

**Reduce position size until the geometric mean is clearly positive.** This is the single most important insight from ruin mathematics.

## Practical Sizing to Avoid Ruin

1. Risk ≤ 1% per trade (never exceed 2%)
2. Maximum concurrent correlated positions: 3 (caps portfolio risk at 3–6%)
3. Hard daily stop: 3% account loss — no new trades that day
4. Weekly hard stop: 7% account loss — full review before resuming
5. Monthly drawdown > 15%: reduce position size by 50% until account recovers
