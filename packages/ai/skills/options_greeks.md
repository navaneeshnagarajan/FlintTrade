---
name: options_greeks
category: analysis
description: Delta, gamma, theta, vega explained with practical trading implications for Indian F&O
---
# Options Greeks — Practical Guide

## Delta (Δ)

**What it is:** Rate of change of option price per ₹1 move in the underlying.

| Option | Delta Range | Interpretation |
|---|---|---|
| Deep ITM Call | 0.8–1.0 | Moves almost like the underlying |
| ATM Call | ~0.5 | 50% probability of expiring ITM |
| OTM Call | 0.1–0.3 | Low sensitivity to price |
| ATM Put | ~−0.5 | |

**Practical use:**
- Delta-neutral portfolio: sum of all deltas = 0 (fully hedged)
- Position delta tells you equivalent futures exposure: delta 0.5 × 75 (Nifty lot) = 37.5 equivalent futures

## Gamma (Γ)

**What it is:** Rate of change of delta per ₹1 move. Measures how fast delta changes.

- Highest gamma at ATM near expiry — option's delta changes rapidly
- Long options: positive gamma (good — delta works in your favour)
- Short options: negative gamma (bad — delta works against you)

**Practical:** On expiry Thursday, short ATM straddles carry extreme negative gamma. Even a 1% move can result in massive losses. Reduce or close shorts before expiry.

## Theta (Θ)

**What it is:** Time decay — how much option value is lost per day.

- Always negative for option buyers (you lose value each day)
- Always positive for option sellers (you gain value each day)
- Theta accelerates sharply in the last 7 days before expiry

**Practical:**
- Option buyer: enter with at least 15 days to expiry; avoid buying in the last week
- Option seller: sell in the last 7 days to maximise theta collection
- Theta is highest for ATM options

## Vega (ν)

**What it is:** Rate of change of option price per 1% change in Implied Volatility.

- Higher vega = option price changes more with IV
- Long options: positive vega (want IV to rise after entry)
- Short options: negative vega (want IV to fall after entry)

**Practical:**
- Before a big event (RBI, budget): IV rises → buy options before, sell after announcement
- After event: IV crashes (IV crush) → options sold before event profit from collapse
- ATM options have the highest vega; OTM options have lower vega

## Combined Greek Analysis

**Positive theta, negative vega strategy (short premium):**
- Sell straddle/strangle in high-IV environment
- Profit from: time passing (theta) + IV falling (vega)
- Risk: large directional move (gamma)

**Positive gamma, positive vega strategy (long premium):**
- Buy straddle/strangle before a catalyst
- Profit from: big move (gamma) + IV spike (vega)
- Risk: time decay (theta) if no move occurs

## Fetching Greeks via OpenAlgo

```
POST /api/v1/optiongreeks
Body: { "symbol": "NIFTY", "expiry": "26APR2025", "strike": 22000, "option_type": "CE" }
Returns: delta, gamma, theta, vega, IV
```
