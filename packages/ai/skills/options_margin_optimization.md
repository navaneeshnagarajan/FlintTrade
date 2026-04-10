---
name: options_margin_optimization
category: execution
description: SPAN margin rules, hedge benefits for spreads vs naked positions, calendar spread margin, converting naked to spread for margin reduction, and MIS vs NRML margin
---
# Options Margin Optimisation

## How SPAN Margin Works

SEBI mandates SPAN (Standard Portfolio Analysis of Risk) margin for F&O positions. SPAN calculates the worst-case loss for the portfolio across 16 scenarios (price and volatility combinations). You pay margin for the scenario with the worst expected loss.

Key components:
- **SPAN margin:** Core requirement based on worst-case scenario
- **Exposure margin:** Additional 3–4% of notional (varies by broker)
- **Total margin = SPAN + Exposure margin**

Check real-time margin using `/api/v1/margin` before placing each order.

## Naked vs Hedged Position Margin Comparison

Hedge dramatically reduces margin because SPAN recognises that the long option caps your maximum loss.

**Example: Nifty (lot = 75), Nifty at 22,000**

| Position | Approx Margin |
|----------|--------------|
| Sell naked ATM Call | ₹95,000–1,10,000 |
| Sell ATM Call + Buy OTM Call 100pts away (bear call spread) | ₹15,000–25,000 |
| Sell ATM Put + Buy OTM Put 100pts away (bull put spread) | ₹15,000–25,000 |
| Iron condor (both spreads) | ₹25,000–40,000 |
| Short straddle (sell call + sell put) | ₹1,30,000–1,60,000 (combined) |
| Short iron fly (straddle + wings) | ₹30,000–50,000 |

Margins change daily — always verify. The reduction from naked to spread is typically 75–85%.

## Calendar Spread Margin

A calendar spread (sell near-expiry, buy far-expiry at the same strike) receives SPAN margin credit on the near leg because the far leg is a partial hedge.

- **Same underlying, same strike, different expiries:** SEBI grants margin credit; effective margin ≈ 40–60% of the near-leg naked margin
- **Different strikes (diagonal spread):** Partial credit; effective margin depends on strike difference

Calendar spread margin benefit disappears 1–2 days before the near expiry expires. Book your position before the near leg expires or close it before this occurs.

## Converting Naked to Spread for Margin Reduction

If you have an existing naked short option that is consuming heavy margin, add a wing (long OTM option) to convert it to a spread:

**Before:**
- Sell Nifty 22,200 CE for ₹80 premium. Margin = ₹1,05,000

**After adding wing:**
- Buy Nifty 22,300 CE for ₹40 premium. Net credit = ₹80 − ₹40 = ₹40. New margin = ₹22,000

The wing costs ₹40 per unit (₹3,000 per lot) but frees up ₹83,000 in margin. The freed margin can be redeployed or kept as a buffer.

**Rule:** If a naked option's premium has decayed by 50%, consider adding the wing. The remaining risk of the naked position (delta, vega) may not justify the ongoing heavy margin.

## MIS vs NRML Margin

| Product | Margin | Position | Usage |
|---------|--------|----------|-------|
| MIS (Margin Intraday Square-off) | 40–50% of NRML margin | Must close by 3:20 IST | Intraday trades only |
| NRML (Normal) | Full SPAN + Exposure | Can hold overnight | Positional, overnight, selling options |

**For option selling:** Always use NRML unless you are certain the position will be squared off by 3:20 IST. Intraday MIS auto-square-off happens at market price at 3:20, which can be disadvantageous. For multi-day premium collection strategies, use NRML.

**MIS margin benefit calculation:**
```
Effective NRML margin for Nifty short straddle: ₹1,50,000
MIS factor: 0.45 (broker-dependent, typically 40–50%)
MIS margin: ₹1,50,000 × 0.45 = ₹67,500
```

## Margin Utilisation Best Practices

- Keep total margin utilisation below 70% of available margin
- Maintain 30% free margin as buffer for intraday margin calls (MTM losses) and new opportunities
- When adding hedge legs to reduce margin, verify the new margin requirement via `/api/v1/margin` before assuming the savings
- Monitor exposure margin separately — it is sometimes added by brokers as additional margin above SEBI minimum

## Peak Margin Rule (SEBI 2021)

SEBI requires peak margin to be monitored across the day, not just at end of day. You must maintain margin at the highest intraday point. Your broker will block peak margin automatically — ensure your account has enough before entering multiple positions in rapid succession.
