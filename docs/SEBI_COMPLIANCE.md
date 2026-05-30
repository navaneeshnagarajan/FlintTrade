# SEBI Algo-Trading Rules — Informational Notes (personal use)

> Reference: SEBI Circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013 (February 4, 2025)
> Subject: Safer participation of retail investors in Algorithmic trading
> Full circular: `.local/reference/SEBI_Circular_Feb042025_AlgoTrading.pdf` (local only)

> **This is NOT a compliance attestation.** FlintTrade is personal-use software and
> makes **no** claim of SEBI compliance. These are informational notes on what the SEBI
> retail-algo rules *are*. For a personal trader using a broker's API, the one operational
> requirement that touches FlintTrade is a **static IP** for API access (registered with
> your broker); the regulatory obligations (registration of algo products, audit
> record-keeping, surveillance) rest with **your broker and the exchanges**, not with this
> tool. FlintTrade `v0.6.0-alpha` is not production-ready; you remain solely responsible
> for your own broker, exchange, tax, and regulatory obligations before any live use. The
> "status" column below describes whether a rule is *relevant to FlintTrade's operation* —
> it is **not** an assertion that you, or FlintTrade, are compliant.

## Implementation Timeline

| Date | Milestone | Status |
|---|---|---|
| Feb 4, 2025 | Circular issued | Done |
| Apr 1, 2025 | ISF formulates implementation standards | Done |
| Aug 1, 2025 | Circular provisions effective | Active |
| Oct 31, 2025 | Brokers submit at least one retail algo product via API | Done (broker side) |
| Nov 30, 2025 | Exchange registration of retail algo products complete | Done (broker side) |
| Jan 5, 2026 | Non-compliant brokers barred from new retail API clients | Active |
| **Apr 1, 2026** | **Full framework mandatory for all brokers** | **Upcoming** |

## FlintTrade's Position

FlintTrade is a **personal tool built by a tech-savvy retail investor** under Section I.c of the circular:

> *"Algos developed by tech-savvy retail investors themselves, using programming knowledge, shall also be registered with the Exchange, through their broker, only if they cross the specified order per second threshold. Further, the same registered Algo shall be permitted to be used by such retail investors for their family (but not for other investors). 'Family' for this purpose would mean self, spouse, dependent children and dependent parents."*

FlintTrade is:
- Open-source (AGPL-3.0) — **White Box** algo (logic disclosed and replicable)
- Personal/family use only — not a commercial algo provider
- Below OPS threshold — rate limiter enforces <10 orders/second
- NOT an algo provider — no empanelment or Research Analyst registration required

## Compliance Matrix

| SEBI Requirement | Circular Section | FlintTrade Status | Implementation |
|---|---|---|---|
| **OPS threshold** | I.c | **Compliant** | Engine rate limiter: 10 OPS hard limit (`packages/services/engine/src/safety.py` Layer 1). Below threshold = no Exchange registration required |
| **Family use allowed** | I.c | **Compliant** | Ditto package supports multi-account for family members |
| **Static IP whitelisting** | I.d | **Compliant** | Configured at broker dashboard level. ER605 router provides static IP. Not FlintTrade's responsibility — broker enforces |
| **No open APIs** | I.d | **Compliant** | Uses OpenAlgo's API key authentication, not open APIs |
| **OAuth authentication** | I.d | **Compliant** | Broker handles OAuth flow. OpenAlgo passes through broker's OAuth |
| **Two-factor authentication** | I.d | **Compliant** | Broker login requires 2FA. OpenAlgo uses broker's 2FA mechanism |
| **Kill switch** | IV.a.iii | **Compliant** | 5-layer safety system (`packages/services/engine/src/safety.py`). Layer 5 = kill switch. Triggers: Telegram `/kill`, UI button, auto P&L breach. Actions: cancel all orders → close all positions → stop all strategies → audit log |
| **Audit trail** | II.b | **Compliant** | `packages/core/data/src/audit_logger.py` — append-only JSONL, daily rotation, gzip compression, 5-year retention. Events: ORDER_PLACED, ORDER_MODIFIED, ORDER_CANCELLED, SAFETY_CHECK, LOGIN, LOGOUT, KILL_SWITCH_ACTIVATED |
| **White Box classification** | V.a.i | **Compliant** | Open-source AGPL-3.0. All logic disclosed, replicable, auditable on GitHub |
| **Algo registration** | II.a | **Not required** | Only required if crossing OPS threshold. FlintTrade enforces <10 OPS |
| **Empanelment as Algo Provider** | III.a | **Not applicable** | FlintTrade is personal use, not a commercial algo provider |
| **Research Analyst registration** | V.a.ii | **Not applicable** | Only for Black Box algo providers. FlintTrade is White Box |
| **Algo ID tagging** | I.b | **Future** | When/if OPS threshold is crossed, orders need Exchange-issued algo IDs. Currently strategy name is passed as `strategy` param. Exchange algo ID support planned |

## 5-Layer Safety System

```
Layer 1: Order validation (price, quantity, exchange, symbol, market hours, rate limit)
Layer 2: Position limits (max simultaneous positions, margin usage caps)
Layer 3: Portfolio risk (net delta/vega limits for options portfolios)
Layer 4: Daily P&L limits (pause trigger at configurable threshold, auto kill switch)
Layer 5: Kill switch (cancel all orders → close all positions → stop all strategies → audit log)
```

Kill switch triggers:
- Telegram bot: `/kill` command
- UI: Kill switch button in Risk Panel widget
- Automatic: P&L breach threshold (configurable in workspace.json)
- API: `POST /ft-api/safety/kill-switch/activate`

## Audit Trail

| Event | What's logged | Retention |
|---|---|---|
| ORDER_PLACED | Strategy, symbol, exchange, side, qty, price, order type, timestamp | 5 years |
| ORDER_MODIFIED | Original + modified fields, reason, timestamp | 5 years |
| ORDER_CANCELLED | Strategy, symbol, reason, timestamp | 5 years |
| SAFETY_CHECK | Layer, verdict (PASS/FAIL), reason, order details | 5 years |
| LOGIN / LOGOUT | Session start/end, broker, timestamp | 5 years |
| KILL_SWITCH_ACTIVATED | Trigger (manual/auto/telegram), P&L at time, positions closed | 5 years |

Storage: Append-only JSONL files at configurable path (default `~/.flinttrade/archive/audit/`).
Format: `audit_YYYY-MM-DD.jsonl` with daily rotation and gzip compression of old files.

## Rate Limits

| Category | Limit | Enforced by |
|---|---|---|
| Orders | 10/second | Engine Layer 1 + OpenAlgo |
| Smart orders | 2/second | Engine Layer 1 + OpenAlgo |
| General API | 50/second | OpenAlgo |

Rate limits apply across ALL exchanges combined (not per exchange).

## Exchange-Specific Rules

### Market Hours (IST)

| Exchange | Open | Close | Auto Square-off |
|---|---|---|---|
| NSE/NFO/BFO | 9:15 AM | 3:30 PM | 3:15 PM |
| CDS/BCD | 9:00 AM | 5:00 PM | 4:45 PM |
| MCX | 9:00 AM | 11:30 PM | 11:25 PM |
| DELTA (crypto) | 24/7 | 24/7 | None (perpetual) |

### Option Expiry Times

| Exchange | Expiry time | Notes |
|---|---|---|
| NFO | 3:30 PM | Standard equity options |
| BFO | 3:30 PM | BSE options |
| CDS | 12:30 PM | Currency options expire EARLIER |
| MCX | 11:30 PM (varies) | Per-commodity: check `/api/v1/expiry` |

### Session Management
- Broker sessions expire ~3:30 AM IST daily
- Manual broker login via OpenAlgo web UI required each day
- No TOTP auto-login implemented (by design — OpenAlgo handles broker auth)

## STT Rates (effective April 1, 2026)

| Segment | Rate | Applied on |
|---|---|---|
| Futures | 0.05% | Sell-side turnover |
| Options | 0.15% | Buy-side premium turnover |

Factor both into strategy P&L calculations and backtest cost models.

## Crypto (Delta Exchange)

- Delta Exchange is FIU-India registered (AML/KYC compliant)
- INR settlement — derivatives classified as speculative business income
- NOT subject to 30% crypto capital gains tax or 1% TDS (derivatives exemption)
- SEBI does not regulate crypto — FIU-India does. Different compliance framework.
- API key + IP whitelisting required (same as equity brokers)
- 24/7 market — no auto square-off, wider stop losses needed

## What FlintTrade Users Must Do

1. **Configure static IP** at broker dashboard (use your router's public IP)
2. **Use broker's 2FA** when logging into OpenAlgo each day
3. **Keep audit logs** — FlintTrade auto-creates them, don't delete the archive directory
4. **Stay below OPS threshold** — default rate limiter handles this
5. **Family only** — don't share strategies with non-family investors
6. **Don't distribute as commercial algo** — FlintTrade is open-source for personal use. Distributing strategies as a service requires Research Analyst registration
