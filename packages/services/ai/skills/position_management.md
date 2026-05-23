---
name: position_management
category: execution
description: Managing open positions — trailing stops, scaling, time exits, gap risk, overnight rules, hedging
---
# Position Management

## Trailing Stop Strategies

A trailing stop locks in profit as the position moves in your favour. Three common approaches:

- **Fixed ATR trail:** Move stop up by 1× ATR(14) for every 2× ATR the price advances. Balances noise tolerance with profit protection.
- **Swing-high/low trail:** Manually step the stop to each new higher swing low (long) or lower swing high (short). Requires active monitoring.
- **Percentage trail:** Trail at a fixed percentage (e.g. 1.5%) below the running high. Simple but blind to volatility.

For intraday F&O, a 0.5–1× ATR trail avoids premature exits on high-IV instruments.

## Scaling In and Out

- **Scaling in:** Enter at 50% of intended size, add remaining 50% only if the position confirms direction. Never average a losing trade.
- **Scaling out:** Exit 50% at the first target (1.5× risk), leave the remainder with a trailing stop. This locks in profit while staying exposed to larger moves.
- Adjust lot count in whole F&O lots — never fractional.

## Time-Based Exits

- **Intraday rule:** Close all MIS positions by 15:15 IST regardless of P&L.
- **0DTE decay exit:** Exit bought options by 14:00 IST to avoid accelerating theta decay in the final hour.
- **NRML positions:** Review at weekly expiry. Hold only if thesis is intact.

## Gap Risk Management

- Overnight F&O positions carry gap risk on news events, RBI decisions, and global cues.
- Hedge naked short options with a cheap OTM buy 1–2 strikes away before market close.
- Limit overnight NRML exposure to 10–25% of capital (see risk limits).

## Overnight Position Rules

1. No naked short options overnight without a hedge leg.
2. Verify margin requirement will not breach SPAN + Exposure margin by morning.
3. Set a GTT (Good Till Triggered) stop-loss order via the broker before end of day.
4. Check for corporate actions (dividends, splits, bonus) that affect open equity positions.

## Hedging Strategies

- **Delta hedge:** Buy/sell underlying futures to flatten delta on an options book.
- **Gamma hedge:** Add long options (long gamma) when short a straddle with an event approaching.
- **Calendar hedge:** Replace short near-term options with long next-expiry options to reduce overnight vega exposure.
