---
name: bracket_order_strategies
category: execution
description: Using bracket and cover orders for automatic SL and target, margin benefits, trailing SL, and when to use BO vs manual SL
---
# Bracket Order Strategies

## What Is a Bracket Order (BO)

A bracket order fires three simultaneous orders: the entry order, a stop-loss leg, and a target (take-profit) leg. When either the SL or the target is hit, the other leg is automatically cancelled. It removes manual intervention from the exit entirely.

## BO vs Cover Order (CO) vs Manual SL

| Feature | Bracket Order (BO) | Cover Order (CO) | Manual SL |
|---|---|---|---|
| Legs | Entry + SL + Target | Entry + SL only | Entry only |
| Trailing SL | Supported by some brokers | Not standard | Manual |
| Margin benefit | Highest (≈ 40–60% reduction) | High (≈ 30–50% reduction) | None |
| Flexibility | Fixed after placement | Fixed after placement | Full |
| Slippage risk | Low (auto-execution) | Low | High (emotion/latency) |

Use CO when you want margin benefit but do not have a clear target level. Use BO when both SL and target are pre-defined before entry.

## Margin Benefit of BO

SEBI SPAN margin for Nifty futures = approximately ₹1.1L per lot. With a BO that has a 50-point SL (₹3,750 max loss):

```
BO margin ≈ SL value × lot size × margin multiplier
         ≈ 50 × 75 × 1.1 = ~₹4,125 per lot (approx)
```

Actual values vary by broker; always verify via `/api/v1/margin` before deploying. The margin benefit is only active while both BO legs are live.

## Trailing SL in Bracket Orders

A trailing SL moves the stop-loss by a fixed number of ticks whenever the price moves in your favour by the trail step. Rules:

- Set trail step = 0.5 × initial SL distance for conservative trails
- Set trail step = 1.0 × initial SL distance to lock in profit faster
- Trail activates only after price has moved at least 1 × initial SL in your favour (to avoid premature tightening)

Example: Buy Nifty at 22,000. Initial SL = 21,980 (20 points). Trail step = 10 points.
- Price moves to 22,020 → SL trails up to 22,000 (break-even locked)
- Price moves to 22,030 → SL = 22,010 (10 points profit locked)

## When to Use BO vs Manual SL

**Use Bracket Order when:**
- Strategy has well-defined, system-generated SL and target (algo signals)
- Scalping — emotions cause manual SL delays at critical moments
- You cannot monitor the screen continuously
- Capital is limited and margin benefit is needed

**Use Manual SL when:**
- Adjusting a multi-leg options position (BO is per-leg, not portfolio-level)
- Trailing SL logic is complex (time-based, ATR-based, level-based)
- Position might be partially closed before SL
- News-driven trades where the target is dynamic

## BO Placement via OpenAlgo

```python
# Bracket order: Buy Nifty with 20-pt SL, 40-pt target, 10-pt trail
placeorder(
    symbol="NIFTY",
    exchange="NFO",
    action="BUY",
    product="MIS",
    quantity=75,
    price_type="LIMIT",
    price=22000,
    stoploss=20,
    squareoff=40,
    trailing_stoploss=10
)
```

Note: `stoploss`, `squareoff`, and `trailing_stoploss` are in points/ticks, not prices. Confirm parameter names with your broker's OpenAlgo adapter — not all brokers support trailing SL.

## Common Mistakes

- Setting SL too tight — BO fires immediately on normal noise. Use ATR × 1.5 as minimum SL.
- Setting target too far — reduces BO margin benefit calculation accuracy.
- Forgetting BO auto-squares at 3:20 IST — if position is still open, MIS square-off happens at market price.
- Using BO for overnight positions — BO is strictly intraday (MIS).
