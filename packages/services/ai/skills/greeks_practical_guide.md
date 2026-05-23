---
name: greeks_practical_guide
category: analysis
description: How delta changes with moneyness, gamma scalping, theta farming strategies, vega trading around events, and practical rho considerations for Indian options
---
# Greeks Practical Guide

## Delta — Sensitivity to Underlying Price

Delta measures how much the option price changes for a ₹1 move in the underlying.

| Option Moneyness | Call Delta | Put Delta |
|------------------|-----------|-----------|
| Deep ITM (>10%) | 0.80–1.00 | −0.80 to −1.00 |
| ITM (2–10%) | 0.60–0.80 | −0.60 to −0.80 |
| ATM (within 1%) | ~0.50 | ~−0.50 |
| OTM (2–10%) | 0.20–0.40 | −0.20 to −0.40 |
| Deep OTM (>10%) | 0.00–0.20 | 0.00 to −0.20 |

**Portfolio delta:** Sum of all position deltas. A delta-neutral portfolio moves very little with small underlying moves.
- Portfolio delta = +50: You own the equivalent of 50 shares worth of risk
- Flatten delta by selling calls or buying puts when delta is too large for your risk appetite

**Delta and probability:** The delta of an OTM option approximately equals its probability of expiring ITM. A 20-delta option has ~20% chance of expiring ITM. Use this for strike selection in spreads.

## Gamma — Rate of Delta Change

Gamma is highest for ATM options near expiry. It accelerates delta changes.

**Gamma scalping (for buyers):**
A long gamma position (long options) profits from large moves in either direction. The technique:
1. Buy an ATM straddle
2. When underlying moves up by 1σ (one standard deviation), the call gains more delta than the put loses → net positive delta. Sell the underlying to re-flatten to delta-neutral.
3. When underlying reverses, repeat in the other direction.
4. You collect small profits on each re-hedge — this is gamma scalping.

**Risk:** Theta (time decay) is the cost. Gamma scalping is only profitable if realised volatility > implied volatility.

**For sellers:** Short gamma means losses accelerate on large moves. Always be aware of your gamma exposure — especially on expiry day.

## Theta — Time Decay

Theta is negative for option buyers (positions lose value over time) and positive for sellers (positions gain value).

**Theta farming strategies (earning time decay):**
- Short straddle/strangle: Maximum theta, but naked. Suitable when IVP > 65.
- Iron condor / iron butterfly: Defined-risk theta collection. Target: 50% profit before expiry.
- Covered call (on equity holdings): Sell OTM calls against long stock positions. Low-risk theta income.
- Calendar spread: Long far-expiry, short near-expiry. Near-expiry decays faster — net positive theta.

**Theta acceleration rule:** Theta decay is not linear. The last 7 days of an option's life see disproportionate decay. Sellers should time entries 5–8 days before expiry to maximise theta per unit of time.

Daily theta for a ₹100 ATM option (approx):
- 30 DTE: ₹2–3/day
- 14 DTE: ₹4–6/day
- 7 DTE: ₹8–12/day
- 1 DTE: ₹25–40/day

## Vega — Sensitivity to Volatility Changes

Vega measures option price change for a 1% change in implied volatility (IV).

**Vega trading around events:**
- Before events (RBI, budget, earnings): IV rises → long vega positions (straddle buy) gain value
- After events: IV crushes → short vega positions (straddle sell) profit from the crush

**Vega exposure by option type:**
- Long options (call or put): Positive vega — benefit from IV increase
- Short options: Negative vega — hurt by IV increase, benefit from IV decrease
- ATM options have highest vega; deep ITM/OTM have lower vega

**Vega risk rule:** Before a major scheduled event (RBI, budget), your net portfolio vega should match your view. If you expect IV to spike, be net long vega. If you expect IV to remain stable or fall, be net short vega.

**India VIX and vega:** A 5-point rise in VIX (e.g., from 14 to 19) typically increases Nifty ATM option premium by 30–40%. If your portfolio has high short vega, model this scenario before event entry.

## Rho — Interest Rate Sensitivity

Rho measures option price change for a 1% change in interest rates. For most short-term Indian F&O options, rho is negligible.

**When rho matters:**
- LEAPS or long-dated options (3–6 months out): Rho can be meaningful
- When RBI announces a 50bps rate change (unusual, but possible): Deep ITM long-dated calls benefit; puts decline

**Practical rule:** Ignore rho for weekly and monthly options. For any position with > 90 DTE, note the vega and rho together before entering a rate-sensitive event like a budget.

## Greeks Dashboard (FlintTrade)

Use the Greeks widget to monitor:
- Net portfolio delta (target: within ±25 of delta-neutral for short-gamma strategies)
- Total theta earned per day (track against daily loss limit — theta should exceed daily costs)
- Net vega exposure (pre-event: ensure direction matches view)
- Per-position gamma (flag any position with gamma > 10 as high-risk on expiry day)
