---
name: volatility_analysis
category: strategy
description: Volatility analysis — VIX interpretation, IV percentile diagnostics, straddle timing concepts, vol crush, calendar spreads
---
# Volatility Analysis

## VIX Interpretation

India VIX measures 30-day implied volatility of Nifty options. Key readings:

| VIX Level | Market Condition | Analysis Focus |
|-----------|-----------------|---------------|
| < 12 | Complacent, low fear | Compare option premium with realised-volatility history |
| 12–18 | Normal regime | Review neutral-spread examples and risk ranges |
| 18–25 | Elevated uncertainty | Study short-vega sensitivity and hedge assumptions |
| > 25 | High fear / event risk | Study post-event volatility compression scenarios |

VIX mean-reverts. A spike above 25 often precedes a crush back below 20 within 1–3 sessions.

## IV Percentile (IVP) Strategies

IV Percentile = percentage of days in the past year where IV was lower than today.

- **IVP > 70:** IV is high versus its own history. Study short-vega payoff examples and margin sensitivity.
- **IVP 40–70:** IV is near the middle of its historical range. Compare neutral or defined-risk payoff examples.
- **IVP < 30:** IV is low versus its own history. Study debit-spread and long-volatility examples around known catalysts.

Check IVP per symbol, not just Nifty VIX — individual stocks can have idiosyncratic IV spikes.

## Straddle and Strangle Timing

- **Short straddle example:** Inspect how high IVP and no near-term event change ATM premium and margin assumptions.
- **Long straddle example:** Inspect how low IVP and a known catalyst change breakevens and theta cost.
- **Strangle example:** Compare wider breakevens with lower premium and different tail-risk exposure.

## Volatility Crush Around Events

IV expands into events (earnings, budget, RBI policy) and crushes immediately after regardless of direction.

- **Event-day long-vol example:** Study how paying maximum IV can be affected by immediate crush.
- **Pre-event short-vol example:** Study how short-premium payoff changes when IV crush occurs.
- **Pre-event long-vol example:** Study how early entry changes theta cost and IV-expansion exposure.

## Calendar Spreads for Vega

A calendar spread (sell near-expiry, buy far-expiry at same strike) is long vega: profits when IV rises.

- Ideal entry: IVP 30–50, no imminent event.
- The short near-expiry decays faster — time decay works in your favour.
- Max loss is the net debit paid; profit if the underlying stays near the strike.
- Use weekly/monthly Nifty or BankNifty options for liquid calendars.
