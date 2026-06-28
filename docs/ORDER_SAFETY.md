# Order Safety Notes

FlintTrade is personal-use, self-hosted software. It is not a broker, an
investment adviser, a managed strategy product, a compliance product, or a
service that accepts funds or account access from other people. Nothing in this
repository is financial, investment, tax, legal, or regulatory advice.

This page describes the technical safety controls FlintTrade applies when an
operator enables an order-capable integration. Broker, exchange, tax, and
regulatory responsibilities remain with the operator and their broker.

## Order-Gating Model

Every order-capable path must pass through the same safety gate before it can
reach a broker adapter or the OpenAlgo-compatible bridge:

1. The caller builds a `SafetyContext` for the intended order.
2. `gate_order` validates the context against local limits and mode settings.
3. `BrokerRouter` receives only gated requests.
4. Broker adapters and `OpenAlgoClient.place_order` remain downstream of the
   gate.

New integrations must preserve this flow. A route, widget, automation, webhook,
agent, or script must not call a broker adapter directly.

## Safety Layers

| Layer | Purpose | Examples |
|---|---|---|
| Order validation | Reject malformed or disallowed orders before routing. | Symbol, exchange, side, quantity, order type, price, and market-session checks. |
| Rate limits | Keep local order operations bounded. | Per-second order caps and lower smart-order caps. |
| Position limits | Prevent local workflows from exceeding configured exposure. | Max open positions, per-symbol limits, and margin-use guards. |
| Daily risk limits | Pause or stop workflows when daily loss thresholds are hit. | Configured pause and kill thresholds. |
| Kill switch | Stop order-capable workflows and cancel open orders where supported. | UI button, API endpoint, Telegram command, or automatic threshold breach. |

## Kill Switch

Kill switch triggers:

- Telegram bot: `/kill` command when the operator enables the integration.
- Terminal UI: Kill switch button in the Risk Panel.
- API: `POST /ft-api/safety/kill-switch/activate`.
- Automatic: configurable daily P&L breach threshold.

The kill switch is a local software control. It should be paired with broker-side
limits, broker-side position checks, and manual review of live-mode settings.

## Audit Logging

FlintTrade writes local audit events for order and safety activity. The archive
path is configurable and defaults under `~/.flinttrade/archive/audit/`.

| Event | Typical fields |
|---|---|
| `ORDER_PLACED` | Strategy or source, symbol, exchange, side, quantity, order type, timestamp. |
| `ORDER_MODIFIED` | Original fields, modified fields, reason, timestamp. |
| `ORDER_CANCELLED` | Source, symbol, reason, timestamp. |
| `SAFETY_CHECK` | Layer, verdict, reason, and order summary. |
| `LOGIN` / `LOGOUT` | Session start or end, broker label, timestamp. |
| `KILL_SWITCH_ACTIVATED` | Trigger, local P&L snapshot, affected positions or orders where available. |

Audit retention is a local configuration choice. These logs are useful for
debugging and personal records; they are not a legal or regulatory attestation.

## Rate Limits

| Category | Default local limit | Enforced by |
|---|---|---|
| Orders | 10 per second | Engine safety gate plus adapter-level checks. |
| Smart orders | 2 per second | Engine safety gate plus adapter-level checks. |
| General API | 50 per second | OpenAlgo-compatible bridge when enabled. |

Limits apply across configured exchanges for the running FlintTrade instance.
Operators should also configure any limits available in their broker dashboard.

## Sessions And Credentials

- Broker login, OAuth, TOTP, and exchange access remain broker-side concerns.
- Native-adapter broker credentials live in the encrypted gateway vault.
- The OpenAlgo-compatible bridge stores only the OpenAlgo API key in FlintTrade;
  broker authentication remains inside OpenAlgo.
- Secrets should be file-backed under `~/.flinttrade/` or stored in the OS
  keyring. Do not commit credentials or personal network details.

## Market Metadata

FlintTrade includes market-hours, expiry, fee, and cost-model metadata so local
screens, calculators, and backtests can behave consistently. Treat this metadata
as software configuration, not advice or a guarantee that an order is suitable,
permitted, or profitable.

## Operator Checklist

Before enabling live-mode order routing:

1. Review the source code for the order path you plan to use.
2. Run in sandbox mode first and inspect the audit log output.
3. Configure broker-side safeguards such as order limits, account limits, and
   manual approval controls where available.
4. Keep broker credentials, API keys, and personal network details out of Git.
5. Confirm that every enabled automation still routes through `gate_order`.
6. Treat FlintTrade as local software for your own account, not as an investment
   service for others.
