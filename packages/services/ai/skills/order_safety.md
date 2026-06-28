---
name: order_safety
category: safety
description: Local order-safety controls, audit trails, and operator checks
---
# Order Safety

FlintTrade is personal-use, self-hosted software. It is not a broker, adviser,
managed strategy, or compliance service. Use this skill for local safety
diagnostics only.

## Broker-Mediated Orders

FlintTrade routes order-capable actions through configured broker adapters or the
OpenAlgo-compatible bridge. FlintTrade itself does not connect directly to an
exchange. Every live-mode order path must traverse `gate_order` before reaching a
broker adapter or `OpenAlgoClient.place_order`.

## Audit Trail

For personal records and debugging, keep a complete local audit trail:

- Timestamp of order generation (millisecond precision)
- Order parameters (symbol, exchange, quantity, price, side)
- Strategy, source, or automation identifier
- Modification and cancellation history
- Execution details and fills
- Safety-gate verdicts and rejection reasons

FlintTrade's `data` package (append-only audit logger) keeps this as daily JSONL files under `~/.flinttrade/archive/audit/`. Retention is operator-controlled — FlintTrade does not delete entries, and how long they are kept is up to the operator.

## Order-to-Trade Ratio

High order churn can create account, broker, and operational risk.

- Track submitted, modified, cancelled, and filled orders.
- Investigate strategies with high cancellation rates.
- Never place orders with intent to cancel immediately.

## Kill Switch

A kill switch should cancel open orders where supported and prevent new
order-capable actions. FlintTrade exposes kill-switch controls through the
Telegram bot (`/kill` command when enabled), Risk Panel, and safety API.

## Local Risk Controls

Broker-side checks remain authoritative for account and venue limits. FlintTrade
adds local checks before routing:

- Daily loss limit (configurable in workspace.json)
- Max position size per symbol
- Max concurrent open orders
- Per-minute and per-second order limits
- Optional manual review gates

## Operator Checklist

- Run sandbox mode first.
- Confirm broker-side account safeguards are configured.
- Keep all credentials out of Git and out of prompt logs.
- Verify that every enabled integration still routes through `gate_order`.
- Treat tax, broker, exchange, and regulatory obligations as external to this
  repository.

## Privacy

Never log or store PAN, Aadhaar, bank account details, demat account numbers, or
broker credentials in FlintTrade's database. Native-adapter broker credentials
belong in the encrypted gateway vault; OpenAlgo broker credentials remain inside
OpenAlgo.
