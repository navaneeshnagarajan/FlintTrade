---
name: support_resistance
category: analysis
description: Identifying and classifying support and resistance levels using swing highs/lows, round numbers, moving averages, and VWAP — with breakout and false breakout rules
---
# Support and Resistance Analysis

## What Makes a Level Significant

A support or resistance level gains strength from:
1. **Number of touches:** A level tested 3+ times is more significant than one tested once
2. **Time period:** A level that held for weeks/months is stronger than an intraday level
3. **Volume at the level:** High-volume rejections confirm the level is real
4. **Role reversal:** Old resistance becomes new support after a breakout (and vice versa)

## Identifying S/R Levels

### Swing Highs and Lows
- A swing high is a candle (or price bar) whose high is higher than both the preceding and following N candles (use N=3 for 15-min, N=5 for daily)
- A swing low is the opposite
- Mark these on the chart using the last 20–50 candles for intraday, 6–12 months of daily data for positional

### Round Numbers and Psychological Levels
- Nifty: Every 500-point level (22,000, 22,500, 23,000) acts as natural S/R
- BankNifty: Every 1,000-point level
- Individual stocks: Round hundreds (₹500, ₹1,000, ₹1,500)
- These levels cluster stop-losses and take-profits, causing price to react

### Moving Averages as Dynamic S/R
- **20 EMA:** Most important for intraday (9–15 min charts) — acts as dynamic support in uptrend
- **50 EMA:** Swing trading level; respected on 1-hour and daily charts
- **200 EMA:** Long-term trend separator; price above = bull market; price below = bear market
- When price returns to a rising 20 EMA in a strong uptrend, treat it as a high-probability long entry

### VWAP and VWAP Bands
- **VWAP:** Institutional benchmark; price above VWAP = buyers in control for the session
- **+1σ / -1σ bands:** Act as the first S/R away from VWAP; price often oscillates between these
- **+2σ / -2σ bands:** Extreme levels; price reaching here often reverts — high-probability mean-reversion trades
- VWAP resets daily at 09:15 IST

### Prior Day High/Low/Close
- Prior day high (PDH): Key resistance; breakout above PDH on volume = strong bullish signal
- Prior day low (PDL): Key support; break below PDL = momentum short signal
- Prior day close (PDC): Often tested at open — a gap above PDC that holds is bullish

## Strength Classification

| Tier | Definition | Trading Weight |
|------|-----------|----------------|
| T1 (Major) | Weekly/monthly swing highs-lows, 52-week highs/lows, round numbers | Full position size |
| T2 (Intermediate) | Daily swing highs/lows, prior week high/low, 50/200 EMA | 75% position size |
| T3 (Minor) | Intraday swing highs/lows, 20 EMA on 15-min, VWAP ±1σ | 50% position size |

Only trade at T1 and T2 levels for directional trades. T3 is for intraday scalps with tight SL.

## Breakout Rules

A valid breakout requires:
1. Close above/below the level on the timeframe being traded (not just a wick)
2. Volume ≥ 1.5× the 20-period average on the breakout candle
3. A retest of the broken level that holds (role reversal) is the ideal entry — lower risk, cleaner SL

**Entry on breakout:** Enter immediately on the close of the breakout candle. SL below the broken level.
**Entry on retest:** Wait for price to return to the broken level and show a reversal candle. Tighter SL, higher probability.

## False Breakout Identification

A false breakout (bear trap or bull trap) has these signatures:
- Breakout candle lacks volume (below 1× average)
- Breakout candle closes near the level, not clearly above/below
- Price immediately reverses within 1–3 candles after the breakout
- Occurs late in a trend (5th+ move of the same magnitude without a retracement)

**False breakout trade:**
- If price breaks above resistance on low volume and reverses below the level: short with SL above the wick high
- Risk: 0.5–1× ATR(14). Target: prior support (2–3× the SL distance)

## Confluence Zones

The highest-probability trades occur where multiple S/R types overlap:
- Round number + swing high + 200 EMA = strong triple-confluence resistance → sell with confidence
- VWAP + prior day close + 20 EMA = triple-confluence support on a pullback → buy with confidence

Always note the count of confluences before entering. Single S/R = tentative; triple confluence = high conviction.
