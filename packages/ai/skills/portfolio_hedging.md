---
name: portfolio_hedging
category: strategy
description: Protective puts, collar strategy, VIX-based hedging, tail risk hedging, hedging cost analysis, and when hedging is not worth the premium cost
---
# Portfolio Hedging

## Why Hedge

Hedging is portfolio insurance. You pay a premium (the hedging cost) to eliminate catastrophic downside. It is not meant to make money — it is meant to prevent ruin during tail-risk events (Black Swans, circuit breakers, geopolitical shocks).

Hedging becomes valuable when:
- You hold a concentrated equity portfolio (>50% in one sector)
- You are approaching a high-uncertainty event (election results, budget, RBI emergency meeting)
- India VIX is low (<13) — options are cheap, insurance is affordable

## Strategy 1 — Protective Put

**Setup:** Buy an OTM put option on Nifty (or the underlying you hold) to cap downside.

**Sizing:**
```
Puts needed = Portfolio value / (Nifty spot × lot size)
For a ₹10L portfolio with Nifty at 22,000 and lot size 75:
Puts needed = 10,00,000 / (22,000 × 75) = 0.61 → buy 1 lot
```

This provides partial protection (1 lot covers ₹16.5L notional — over-hedges this portfolio, which is fine).

**Strike selection:**
- 5% OTM put: Cheap but provides protection only on large moves (5%+ fall)
- 2% OTM put: More expensive but activates on moderate corrections
- ATM put: Most expensive; activates immediately

**Typical cost:** A 3-month ATM Nifty put costs approximately 2–3% of the portfolio value (notional). A 5% OTM put costs 0.5–1%.

## Strategy 2 — Collar Strategy

**Setup:** Own the underlying (or ETF). Sell an OTM call + buy an OTM put at the same or different expiry.

**Effect:** The call premium received offsets the put premium paid, reducing or eliminating hedging cost. But you cap your upside at the call strike.

**Example (Nifty):**
- Nifty at 22,000. Hold 1 lot.
- Sell 22,500 CE for ₹120 premium
- Buy 21,500 PE for ₹80 premium
- Net cost of hedge: ₹80 − ₹120 = −₹40 (net CREDIT — hedged at zero cost)
- Protected below 21,500; capped above 22,500

Zero-cost collar: Strike the call and put such that premiums are equal. You sacrifice upside in exchange for free downside protection.

## Strategy 3 — VIX-Based Hedging

India VIX is mean-reverting and spikes during market stress. Buy hedges when VIX is low; avoid paying for expensive hedges when VIX is already elevated.

| VIX Level | Hedging Recommendation |
|-----------|----------------------|
| VIX < 13 | Excellent time to buy puts (cheap insurance) |
| VIX 13–18 | Fair cost; buy for high-uncertainty events only |
| VIX 18–25 | Expensive; consider collars instead (sell call to fund put) |
| VIX > 25 | Do not buy puts — insurance is at peak cost; the storm may already be here |

VIX spikes are usually short-lived. If you missed buying protection before a VIX spike, wait for the spike to subside before adding new hedges.

## Strategy 4 — Tail Risk Hedging

Tail risk = low-probability, high-severity events. Traditional hedges (5% OTM puts) underperform in true tail events because 5% OTM is not far enough.

**Deep OTM tail hedge:**
- Buy 10–15% OTM puts, 2–3 months out
- Cost: 0.1–0.3% of portfolio (very cheap due to low probability priced in)
- Payoff: 10–30× in a genuine crisis (2008-type 40% crash)

**Allocation rule:** Allocate 0.5–1% of portfolio annually to tail hedges. Think of it as a pure insurance premium that will likely expire worthless 80% of the time.

## Hedging Cost Analysis — The Insurance Premium Approach

Treat hedging cost as a fixed annual expense, like business insurance.

```
Annual hedging budget = Portfolio size × 1–2%
For a ₹10L portfolio: ₹10,000–20,000 per year
Equivalent to 4 lots of 3-month 5% OTM puts per year at typical prices
```

Track the cost separately. If the portfolio's annual return exceeds 15% and hedging costs 1.5%, you are still up 13.5% with downside protected. This is the correct mental accounting.

## When Hedging Is NOT Worth It

Hedging destroys value when:

1. **You are already diversified:** A portfolio of 20+ stocks across 8+ sectors in a market-tracking allocation is self-hedging. Index-level hedges are redundant.
2. **Position sizes are small:** Paying ₹3,000 to hedge a ₹20,000 position (15% cost) makes no economic sense.
3. **VIX is already elevated:** Buying puts after a 20% market fall when VIX is at 30 locks in high premiums at exactly the wrong time.
4. **Short-duration intraday positions:** Intraday F&O positions are already limited to one session; systemic overnight risk is zero.
5. **The hedge and the position are uncorrelated:** Buying Nifty puts to hedge a portfolio of small-cap stocks provides limited protection (beta mismatch).

**Decision rule:** Hedge when the cost is < 2% of the protected value and the event being hedged against would cause a loss > 10% of portfolio. Otherwise, the expected value of the hedge is negative.
