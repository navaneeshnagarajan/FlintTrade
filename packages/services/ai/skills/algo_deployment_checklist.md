---
name: algo_deployment_checklist
category: execution
description: Pre-deployment validation, paper trading thresholds, kill switch testing, go-live checklist, and incident response for live algo trading
---
# Algo Deployment Checklist

## Phase 1 — Paper Trading Validation

Never go live without passing ALL criteria in paper mode first.

**Minimum paper trading period:** 20 trading sessions (≈ 1 calendar month)

**Required thresholds to pass:**
| Metric | Minimum Threshold |
|--------|-----------------|
| Total trades | ≥ 60 (enough statistical sample) |
| Win rate | ≥ strategy's theoretical win rate ± 5% |
| Max drawdown (paper) | ≤ designed max drawdown |
| Sharpe ratio | ≥ 1.0 |
| Consecutive losses | No run > 2× designed max |
| Execution fill rate | ≥ 95% (orders getting filled as expected) |

If any metric fails, return to backtesting. Do not rationalise.

## Phase 2 — Pre-Deployment Technical Checks

**Code and configuration:**
- [ ] All hardcoded values replaced with config parameters
- [ ] API key stored through FlintTrade Setup/Settings or the encrypted vault, never in code
- [ ] OpenAlgo host set to the intended target through Setup/Settings
- [ ] Product type correct: `MIS` for intraday, `NRML` for overnight/options sell
- [ ] Lot size resolved from current instrument metadata; no hardcoded lot assumptions
- [ ] Symbol format validated against OpenAlgo `/api/v1/symbol` endpoint

**Safety systems:**
- [ ] Layer 4 daily-loss pause and hard-stop thresholds configured and verified to block only new orders
- [ ] Explicit Layer 5 tested manually — does it cancel open orders and request position flattening?
- [ ] Max position limit enforced (strategy cannot open more than N lots)
- [ ] Duplicate order guard in place (prevents double-firing on reconnect)
- [ ] WebSocket reconnect with position re-sync on disconnect

**Connectivity:**
- [ ] OpenAlgo `/api/v1/ping` returns success
- [ ] Broker authenticated (verify `/api/v1/funds` succeeds; a zero balance is not an authentication failure)
- [ ] WebSocket connection stable for 30 minutes under load test

## Phase 3 — Go-Live Checklist (Day 1)

Run these checks at 09:00 IST, 15 minutes before market open:

1. OpenAlgo health check: `make health`
2. Funds available: minimum 2× required margin per instrument
3. No open positions from yesterday (flat start)
4. Explicit Layer 5 control reachable; account-MTM breaker monitoring checked separately
5. Telegram alerts active (if configured): send a test message
6. Position mirror disabled (ditto) on day 1 — single account only

## Phase 4 — First Hour Monitoring (09:15–10:30 IST)

During the first live hour, monitor manually even if the algo is automated:

- Watch every order placement and fill
- Verify fills match expected prices (within 0.1% slippage for futures)
- Confirm SL orders placed correctly after each entry
- Watch account MTM — should not breach 50% of daily loss limit in the first hour
- Log every anomaly: missed fills, unexpected orders, latency spikes

**Scale-up rule:** Run at 25% of target position size for the first 5 days. Scale to 50% at day 6 if performance matches paper trading within 20%.

## Phase 5 — Scaling Up

| Day | Position Size | Condition to Advance |
|-----|---------------|----------------------|
| 1–5 | 25% | No system errors, fills normal |
| 6–10 | 50% | Live Sharpe ≥ 0.8 × paper Sharpe |
| 11–20 | 75% | Max drawdown ≤ 1.2 × paper drawdown |
| 21+ | 100% | All metrics stable |

Never skip a scale step because early results look good. Slippage and market impact change at full size.

## Incident Response

**Level 1 — Single order anomaly:** Log it. Keep trading. Review post-session.

**Level 2 — Unexpected position:** Use FlintTrade's explicit Layer 5 control or the broker UI. Do not add a direct broker-cancellation call to the automation, and do not resume until the cause is identified.

**Level 3 — Layer 4 daily-loss threshold or explicit Layer 5 activation:** Layer 4 blocks new orders only. Explicit Layer 5 or the separate account-MTM breaker may cancel or flatten; confirm broker exposure before declaring positions closed. Complete a post-mortem before the next session and file it in `~/.flinttrade/incidents/YYYYMMDD.md`.

**Level 4 — Broker/API unresponsive:** Close positions manually via broker's own app. Notify broker support. Keep a phone or mobile app login for this scenario — do not rely solely on OpenAlgo when a broker is having issues.

## Post-Session Review (Every Day)

- Compare live fills vs expected fills
- Check for drift between live P&L and paper P&L (should be within 15%)
- Review any SL hits — were they valid signals or noise?
- Update `DEVLOG.md` with session metrics
