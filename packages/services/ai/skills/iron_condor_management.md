---
name: iron_condor_management
category: strategy
description: Iron condor entry criteria, strike selection, adjustment rules, max loss management, and partial profit taking for Nifty/BankNifty
---
# Iron Condor Management

## What Is an Iron Condor

An iron condor combines a bull put spread (below the market) and a bear call spread (above the market). You collect net credit and profit if the underlying stays within the profit range until expiry.

Structure:
- Short OTM put (lower short strike)
- Long further OTM put (lower long strike)
- Short OTM call (upper short strike)
- Long further OTM call (upper long strike)

Maximum profit = net credit collected. Maximum loss = width of spread − credit collected.

## Entry Criteria

**Mandatory entry conditions:**
1. **IV Percentile (IVP) > 50:** At minimum 50; ideally > 65. Low IVP means cheap premium — not enough credit to justify risk.
2. **No major event within 7 days:** RBI policy, budget, earnings of heavy-weight stocks within the expiry period eliminate the condor's edge.
3. **ADX < 20 or market in established trading range:** Trending markets are the primary risk to iron condors.
4. **India VIX < 20:** High VIX increases probability of large moves that breach strikes.

**Optimal entry timing:** Tuesday or Wednesday of the expiry week for weekly condors. This captures 3–4 days of accelerated theta decay.

## Strike Selection (16-Delta Rule)

Target the 16-delta strike for both short strikes. At 16 delta, the option has approximately a 16% probability of expiring ITM (84% OTM) — statistically sound for premium collection.

For Nifty at 22,000, typical weekly (Thursday) condor setup:
- Short put: 22,000 − 200 = 21,800 (≈ 16-delta on low vol week)
- Long put: 21,800 − 100 = 21,700 (wing, buys protection)
- Short call: 22,000 + 200 = 22,200 (≈ 16-delta)
- Long call: 22,200 + 100 = 22,300 (wing)

Adjust strike distances for current IV — use the option chain's delta column via `/api/v1/optionchain`.

**Minimum credit rule:** Only place the condor if total credit collected ≥ 30% of the spread width. For a 100-point spread, minimum credit = 30 points. Below this, the risk:reward is insufficient.

## Adjustment Rules — Roll the Tested Side

When the underlying moves toward one of the short strikes:

**Trigger:** Short strike delta reaches 30 (from initial 16). This means the market has moved significantly.

**Adjustment options:**
1. **Roll the tested side outward:** Buy back the tested short strike, sell a new one further away in the same expiry. Cost debit; reduces max profit but extends the range. Do this only if you can roll for a net credit or small debit (< 20% of original credit).
2. **Add a long option on the tested side:** Convert the condor to an asymmetric condor — add an extra long position on the breached side to cap losses.
3. **Exit the tested spread:** Close only the bull put spread or bear call spread that is under threat. Keep the profitable side open. Reduces total risk immediately.

**Do not adjust more than twice.** If two adjustments have been made and the position is still under pressure, close the entire position.

## Partial Profit Taking

Do not wait for full expiry to collect premium. Exit rules:

| Profit Level | Study Response |
|-------------|--------|
| 25% of max profit | Continue monitoring in the model |
| 50% of max profit | Compare partial-close outcomes against holding |
| 75% of max profit | Compare full-close outcomes against residual theta |
| Expiry day morning | Include a time-risk close assumption in the scenario |

Many backtests review the 50% profit band because it balances realised premium against remaining time-risk assumptions.

## Max Loss Management

**Hard-stop model:** If total position loss reaches 200% of the original credit collected, model an immediate close with no averaging.

Example: Collected ₹30 credit per lot on a 100-point spread. If the position shows a loss of ₹60 per lot, exit. Max defined loss on the spread is ₹70 (100 − 30), so the hard stop at 2× credit is well before maximum loss.

## Margin Considerations

Iron condor margin is calculated as the wider spread's SPAN margin. The four-leg structure reduces margin vs. a naked straddle by approximately 40–60%. Use `/api/v1/margin` to verify before entry. Ensure at least 30% free margin buffer after entry.
