---
name: drawdown_management
category: analysis
description: Daily and weekly loss limits, max drawdown policy, recovery strategies with position size reduction tables, and when to switch to paper trading
---
# Drawdown Management

## Understanding Drawdown

Drawdown is the peak-to-trough decline from the highest account value. It is inevitable in trading — even the best strategies have drawdown periods. The goal is not to avoid drawdown but to keep it within survivable limits.

```
Drawdown % = (Peak account value − Current account value) / Peak account value × 100
```

Example: Account peak = ₹10L. Current value = ₹8.5L. Drawdown = 15%.

## Loss Limit Framework

The following is an illustrative strategy-level exit policy, not FlintTrade Layer 4 or Layer 5.

### Daily Loss Limits

| Tier | Loss Level | Action |
|------|-----------|--------|
| Yellow | −1.5% of capital | Warning — review open positions, no new entries for 30 minutes |
| Orange | −2.5% of capital | Reduce all open positions by 50%, no new entries for rest of day |
| Red (strategy exit policy) | −3% of capital | Close all positions under the strategy's reviewed exit procedure; stop trading for the day. |

### Weekly Loss Limits

| Loss Level | Action |
|-----------|--------|
| −5% of capital | Review the week's trades. Identify what went wrong. Reduce size by 50% next week. |
| −7% of capital | Stop all trading. Mandatory 2-day review period before resuming. |
| −10% of capital | Full strategy review. Consider paper trading for 2 weeks before resuming live. |

### Maximum Drawdown Policy

Set a maximum drawdown level that, if reached, triggers a mandatory review:

- **Conservative traders:** 10% max drawdown
- **Moderate risk:** 15% max drawdown
- **Aggressive:** 20% max drawdown (only with proven edge over 200+ trades)

If maximum drawdown is hit, the strategy must be reviewed and approved before resuming. This is not optional.

## Recovery Strategies — Position Size Reduction Table

After a drawdown, the correct response is to reduce size, not increase it (to "recover faster"). Larger size after a drawdown increases the risk of a deeper drawdown.

| Drawdown Level | Position Size (% of Normal) | Review Required |
|----------------|----------------------------|-----------------|
| 0–5% | 100% | No |
| 5–8% | 75% | Weekly review |
| 8–12% | 50% | Formal review + trading journal analysis |
| 12–18% | 25% | Paper trading validation recommended |
| > 18% | Paper trading only | Full strategy overhaul required |

**Example:** Normal position size = 2 lots of Nifty (1.5% risk per trade). At 10% drawdown, reduce to 1 lot (0.75% risk per trade). Resume full size only after recovering to the 5% drawdown level.

**Recovery math:** After a 15% drawdown, you need a 17.6% gain to get back to peak (not 15%). Larger drawdowns require disproportionately larger recoveries. Preventing deep drawdowns is far more important than recovery.

| Drawdown | Recovery Needed |
|----------|----------------|
| 10% | 11.1% |
| 20% | 25% |
| 30% | 42.9% |
| 50% | 100% |

## When to Switch to Paper Trading

Switching to paper trading is not defeat — it is a diagnostic tool.

**Switch to paper trading when:**
- Two consecutive weeks of losses (weekly loss limit hit twice)
- Live performance deviates from backtested/paper performance by more than 30%
- Emotional state is significantly impacting decision-making
- New strategy has not been paper-validated for at least 20 sessions
- Major market regime change (e.g., VIX doubles in a week) — old parameters may not apply

**Paper trading period:** Minimum 10 sessions. Resume live only if:
- Paper trading shows positive expectancy
- Max drawdown in paper sessions < designed max drawdown
- No systematic errors (missed orders, wrong quantities, wrong direction)

## Building in Automatic Recovery Rules

Use FlintTrade's existing controls. Layer 4 percentage thresholds block
subsequent new orders; explicit Layer 5 performs operator-triggered global
cancel/flatten; automatic account-scoped cancel/flatten belongs to the separate
MTM circuit breaker. Automation must not call broker cancellation or position
closure methods directly. Exercise the intended control in Practice mode and
verify broker exposure before relying on it (see `algo_deployment_checklist`).

## Psychological Aspect of Drawdown

Drawdowns feel worse than they mathematically are. A 10% drawdown feels like a disaster because:
- It erases recent gains visibly
- Recency bias makes it feel permanent
- Each losing day compounds the emotional burden

Countermeasure: Focus on the process, not the P&L. If your trades are following the rules and the system has positive expectancy, a drawdown is a statistical event, not a failure.
