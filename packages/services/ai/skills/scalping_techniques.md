---
name: scalping_techniques
category: strategy
description: Tick scalping, order flow reading, 1-min chart patterns, and scalper risk management for Indian intraday trading
---
# Scalping Techniques

## What Is Scalping

Scalping targets 2–10 ticks per trade on liquid F&O instruments, holding positions for seconds to a few minutes. Profitability depends on high win rate, tight execution, and ruthless discipline on loss exits.

## Best Instruments for Scalping (India)

- **Nifty 50 futures (NIFTY):** Tightest spread (~0.05 pts), highest liquidity
- **Bank Nifty futures (BANKNIFTY):** Wider spread but large moves; 1–2 point targets viable
- **ATM options on expiry day:** High gamma = large tick-per-rupee moves; premium > ₹100 only

## Best Times to Scalp (IST)

| Window | Why |
|--------|-----|
| 09:15–10:30 | Opening range breakouts, high volume, strong directional moves |
| 14:00–15:15 | Afternoon momentum, trend continuation, pre-close positioning |
| 11:00–13:30 | Avoid — lunch lull, choppy, low volume, whipsaws costly |

Never scalp in the last 5 minutes (15:25–15:30): extreme illiquidity, wide spreads.

## Order Flow Reading

Order flow tells you who is in control before price confirms it:

- **DOM (Depth of Market):** Watch bid/ask stack. Large bids absorbing sell pressure = bullish absorption. Thin bids below price = risk of rapid drop.
- **Tape reading:** Consecutive trades printing at the ask = buyers in control. Consecutive trades at the bid = sellers in control.
- **Imbalance:** When ask-side orders vanish suddenly (pulled) price often jumps — this is a trigger to enter fast.

Use FlintTrade's depth widget (50-level DOM from OpenAlgo) to monitor stacking.

## 1-Minute Chart Patterns for Scalpers

- **Opening Range Breakout (ORB):** Mark the high/low of the first 5-minute candle. Enter on breakout with volume confirmation. Target = range size. SL = back inside the range.
- **Inside bar breakout:** A narrow inside bar after a trend candle — enter the breakout direction. Tight SL (just below/above inside bar).
- **VWAP bounce:** Price dips to VWAP and prints a bullish candle with above-average volume. Study a stop below the wick and a 0.25% VWAP-reversion objective.
- **Micro double bottom/top:** Two equal lows (within 2–3 ticks) on the 1-min chart at a support level. Study the second candle's high as a breakout reference.

## Scalper Risk Management Study Rules

- **Maximum SL:** 2–3 ticks (Nifty: ≤ 10 points per lot) is a common study constraint for scalp-style systems.
- **Risk per trade:** 0.25% of capital maximum in simulations. This is lower than swing examples because frequency is higher.
- **Daily loss limit:** 1.5% of capital as a modelled circuit breaker.
- **Win-rate hurdle:** Compare whether the tested setup can exceed 55% with reward:risk of 1.5:1 before considering it positive expectancy.
- **3 consecutive losses:** Include a pause-and-review rule in the backtest to check whether market conditions changed.
- **No averaging:** Model scalp losses as capped rather than averaged down.

## Spread Cost Analysis

Spread cost must be factored into every scalp. For Nifty futures (lot = 75):

```
Spread cost per round trip ≈ 1 point × 75 = ₹75
Brokerage (flat ₹20 × 2) = ₹40
STT + other charges ≈ ₹30
Total cost per round trip ≈ ₹145
```

A 5-point target nets ≈ ₹375 − ₹145 = ₹230 per lot. Scalping requires disciplined sizing to keep costs below 30% of gross profit.

## Execution Requirements

- Use **LIMIT orders** for entries whenever possible — avoid paying the spread.
- Use **MARKET orders** for exits if the move is going against you fast.
- Co-location or low-latency connection is preferable for sub-second execution.
- OpenAlgo MIS product type for all scalps — never NRML for intraday scalps.
