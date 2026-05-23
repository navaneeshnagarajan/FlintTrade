---
name: volatility_trading
category: strategy
description: Trading volatility — VIX interpretation, IV percentile strategies, straddle timing, vol crush, calendar spreads
---
# Volatility Trading

## VIX Interpretation

India VIX measures 30-day implied volatility of Nifty options. Key readings:

| VIX Level | Market Condition | Strategy Bias |
|-----------|-----------------|---------------|
| < 12 | Complacent, low fear | Buy options (cheap premium), avoid selling |
| 12–18 | Normal regime | Balanced; favour neutral spreads |
| 18–25 | Elevated uncertainty | Begin selling premium carefully |
| > 25 | High fear / event risk | Sell premium aggressively post-spike |

VIX mean-reverts. A spike above 25 often precedes a crush back below 20 within 1–3 sessions.

## IV Percentile (IVP) Strategies

IV Percentile = percentage of days in the past year where IV was lower than today.

- **IVP > 70:** IV is expensive. Favour short vega strategies — sell straddles, strangles, iron condors.
- **IVP 40–70:** IV is fair. Favour neutral or defined-risk spreads (bull put, bear call).
- **IVP < 30:** IV is cheap. Buy options — debit spreads, long straddles ahead of catalysts.

Check IVP per symbol, not just Nifty VIX — individual stocks can have idiosyncratic IV spikes.

## Straddle and Strangle Timing

- **Sell straddle:** Best entered when IVP > 70 and no known event in the next 5 sessions. Maximum premium at ATM strike.
- **Buy straddle:** Enter when IVP < 30 and a known catalyst (earnings, RBI policy) is within 3–5 sessions.
- **Strangle:** Wider breakevens than straddle. Sell when IVP > 75 for extra cushion.

## Volatility Crush Around Events

IV expands into events (earnings, budget, RBI policy) and crushes immediately after regardless of direction.

- **Never buy options on the event day itself** — pay maximum IV, receive crush immediately.
- **Sell a straddle 1 session before the event** to capture the crush.
- **Or buy 5–7 days before** when IV is still building, exit the day before announcement.

## Calendar Spreads for Vega

A calendar spread (sell near-expiry, buy far-expiry at same strike) is long vega: profits when IV rises.

- Ideal entry: IVP 30–50, no imminent event.
- The short near-expiry decays faster — time decay works in your favour.
- Max loss is the net debit paid; profit if the underlying stays near the strike.
- Use weekly/monthly Nifty or BankNifty options for liquid calendars.
