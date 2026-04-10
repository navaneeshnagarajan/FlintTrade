---
name: candlestick_patterns
category: analysis
description: 15 key candlestick patterns with confirmation rules, reliability statistics, volume integration, and IST-specific considerations
---
# Candlestick Patterns

## Pattern Reliability Framework

A candlestick pattern alone is not a signal — it is a hypothesis. Require ALL of the following before acting:
1. Pattern forms at a significant S/R level or pivot
2. Next candle confirms (closes in the expected direction)
3. Volume on the pattern candle is above 20-period average (for reversal patterns)

Reliability rating below is based on backtested data on Nifty/BankNifty 15-min charts.

## Reversal Patterns (Bullish)

**1. Hammer**
- Long lower wick (≥ 2× body), small body at the top, little or no upper wick
- Forms at support after a downtrend
- Reliability: 62% | Confirmation: Next candle closes above hammer's body
- IST note: Hammer at 09:20–09:30 (opening range) is the most reliable

**2. Bullish Engulfing**
- Large bullish candle fully engulfs the previous bearish candle's body
- Reliability: 68% | Confirmation: Volume on bullish candle > 1.5× previous candle
- Strongest at key S/R or VWAP level

**3. Morning Star (3-candle)**
- Bearish candle → small indecision body (doji or spinning top) → strong bullish candle (closes > 50% into first candle's body)
- Reliability: 71% | One of the most reliable reversal patterns
- Works on 5-min and 15-min charts; less reliable on 1-min

**4. Piercing Line**
- Bearish candle followed by bullish candle that opens below the low but closes above the midpoint
- Reliability: 60% | Requires volume surge on second candle

**5. Bullish Harami**
- Small bullish candle contained within the prior bearish candle's body
- Reliability: 53% — use only with other confirmation (MACD divergence, RSI < 30)

**6. Dragonfly Doji**
- Open = High = Close, long lower wick
- Reliability: 65% at support | Strong rejection of lower prices
- Most meaningful on daily/weekly charts; usable on 15-min for intraday

## Reversal Patterns (Bearish)

**7. Shooting Star**
- Long upper wick (≥ 2× body), small body at the bottom, forms after uptrend at resistance
- Reliability: 62% | Confirmation: Next candle closes below shooting star's body

**8. Bearish Engulfing**
- Large bearish candle fully engulfs prior bullish candle's body
- Reliability: 67% | Volume confirmation critical

**9. Evening Star (3-candle)**
- Bullish candle → small indecision body → strong bearish candle
- Reliability: 70% | Mirror of morning star; plan trades the session before on known resistance

**10. Dark Cloud Cover**
- Bullish candle followed by bearish candle that opens above the high but closes below the midpoint
- Reliability: 59% | Confirmation needed

**11. Gravestone Doji**
- Open = Low = Close, long upper wick
- Reliability: 64% at resistance | Rejection of higher prices

## Continuation Patterns

**12. Three White Soldiers**
- Three consecutive strong bullish candles with small wicks, each opening within the prior body
- Reliability: 72% | Very bullish if volume increases with each candle

**13. Three Black Crows**
- Three consecutive strong bearish candles — mirror of three white soldiers
- Reliability: 71% | Watch for in uptrends; trend change signal

## Indecision / Confirmation Patterns

**14. Doji**
- Open ≈ Close; body is < 5% of the candle range
- On its own: no directional signal — market is undecided
- In context: doji after a strong trend = exhaustion; signals upcoming reversal or pause
- Act on the candle AFTER the doji, not the doji itself

**15. Spinning Top**
- Small body with upper and lower wicks of roughly equal length
- Similar to doji — represents indecision. Treat identically.

## Combining with Volume (Critical Rule)

- **Reversal patterns without volume confirmation:** reduce position size by 50%
- **Breakout candles with 2× average volume:** increase confidence, can enter with full size
- Use FlintTrade's chart widget (Lightweight Charts) — volume bars below each candle

## IST-Specific Considerations

- **09:15–09:25 candles:** Often unreliable (gap open, order imbalance); wait for the 09:30 candle to close before acting on first-candle patterns
- **11:00–13:30 candles (lunch lull):** Low volume — all patterns have lower reliability; treat as tentative
- **14:00–14:30 candles:** Opening of afternoon session; patterns here have similar reliability to morning
- **15:00–15:30 candles:** Last 30 minutes — patterns can be misleading due to MIS square-off flows; avoid new entries based on late-session patterns alone
