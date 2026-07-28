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

## Unknown Broker Outcomes

If adapter entry occurred but FlintTrade could not persist or receive the
broker acknowledgement, the lifecycle ledger records `OUTCOME_UNKNOWN` and
blocks later normal writes. A clean broker snapshot never clears that state:
the order may have filled and disappeared or may use an identifier FlintTrade
did not receive.

Recovery is an operator decision in the Reconciliation widget. The operator
must inspect the broker, use an authenticated PIN-unlocked Live session, own
the exact broker/account selector, and type the decision, selector and attempt
ID exactly. Before accepting a new decision, FlintTrade forces reconciliation
for only that selector and requires the resulting snapshot generation to be
durably adopted. Finalisation revalidates the same evidence under the outcome
lease so a newer conflicting snapshot cannot be ignored. Snapshot timestamps
are monotonic: older snapshots and same-time snapshots with different content
fail closed. Every broker-observed material order identity is retained as an
immutable, generation-scoped observation, so a later changed or empty snapshot
cannot erase earlier matching evidence. The public diff is cryptographically
bound to recursively frozen private broker/local snapshots and rebuilt before
persistence and again before adoption. Malformed, mutated, or mismatched
reconciliation reports are rejected rather than interpreted as clean.

For applied placements, every supplied broker ID must have been first observed
after the attempt was invoked and must match all material persisted identity
fields. Basket IDs are bound to explicit child indexes rather than inferred
from list order; a partial decision must partition every child into applied and
not-applied sets. Modify and cancel decisions use operation-specific state
evidence. A cancel-pending state, a mixed modify state, missing broker fields,
an `UNKNOWN` material marker, or an operation for which the ledger did not
persist enough evidence remains blocked. Broker normalisers do not substitute
zero for an omitted numeric order field; an explicit zero remains valid and an
omitted or malformed value remains unavailable.

FlintTrade first persists the immutable decision as `PENDING_AUDIT`, fsyncs a
hash-chained audit event and independently verifies its receipt. The ledger
then commits `CONFIRMED_APPLIED`, `CONFIRMED_NOT_APPLIED`, or
`CONFIRMED_PARTIAL` together with the local order-state update, but retains a
durable `PENDING_ROUTER_CLEAR` record until the current router removes only
that attempt's fault. Completion requires a verifiable receipt bound to the
resolution, attempt, selector, and exact current-router generation; a boolean,
missing, stale, or mismatched proof fails closed. A `PENDING_AUDIT` retry must
obtain a newer exact-selector
generation; the ledger archives the prior pending revision and creates a new
resolution ID. A `PENDING_ROUTER_CLEAR` retry resumes the already committed
decision without another broker read. Other
unknown attempts and unrelated critical ledger health, including conservatively
migrated legacy faults, continue to block normal writes. Recovery performs no
broker mutation and emergency reducing writes remain on the gated path.

The terminal rejects malformed or contradictory status, report, success and
structured-error envelopes before changing cached state or showing a healthy
result. Attempt identity, canonical outcome, status, booleans and authorised
remaining-outcome counts are runtime-validated. Authentication transitions
retire the entire QueryClient generation, so callbacks from an older principal
can finish only against the retired client and cannot repopulate the next
principal's cache.

If task cancellation or another `BaseException` crosses a broker-write boundary
after adapter invocation, the attempt is durably marked `OUTCOME_UNKNOWN` before
the exception is re-raised. Audit appends repair and fsync a torn tail in the
newest plain chain segment, including across a date rollover, before extending
the chain; archive compression uses a same-directory,
fsynced atomic replacement so a crash preserves either the source or a complete
archive.

## Safety Layers

| Layer | Purpose | Examples |
|---|---|---|
| Order validation | Reject malformed or disallowed orders before routing. | Symbol, exchange, side, quantity, order type, price, and market-session checks. |
| Rate limits | Keep local order operations bounded. | Per-second order caps and lower smart-order caps. |
| Position limits | Prevent local workflows from exceeding configured exposure. | Max open positions, per-symbol limits, and margin-use guards. |
| Daily risk limits | Pause or hard-stop subsequent new orders when daily loss thresholds are hit. | Configured pause and hard-stop thresholds; no broker-side cancel or flatten. |
| Kill switch | Stop order-capable workflows, cancel open orders, and request position flattening where supported. | Explicit UI button, API endpoint, or Telegram command. |

## Kill Switch

Kill switch triggers:

- Telegram bot: `/kill` command when the operator enables the integration.
- Terminal UI: Kill switch button in the Risk Panel.
- API: `POST /ft-api/safety/kill-switch/activate`.

The percentage-based Layer 4 daily-loss thresholds do not activate this kill
switch. They latch new-order admission until manually reset. Automatic
account-level flattening, when enabled, is owned separately by the authoritative
rupee MTM circuit breaker.

The kill switch is a local software control. It should be paired with broker-side
limits, broker-side position checks, and manual review of live-mode settings.

## Audit Logging

FlintTrade writes local audit events for order and safety activity. The archive
path is configurable and defaults to `archive/audit/` inside your workspace
directory, which is platform-specific:

| Platform | Default audit archive |
|---|---|
| Linux | `~/.flinttrade/archive/audit/` |
| macOS | `~/Library/Application Support/flinttrade/archive/audit/` |
| Windows | `%APPDATA%\flinttrade\archive\audit\` |
| Override | `FLINTTRADE_WORKSPACE_DIR`, then `FLINTTRADE_HOME` (in that precedence order) |

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
- Secrets should be file-backed under your platform workspace directory
  (`~/.flinttrade/` on Linux, `~/Library/Application Support/flinttrade/` on
  macOS, `%APPDATA%\flinttrade\` on Windows; overridden by
  `FLINTTRADE_WORKSPACE_DIR`, then `FLINTTRADE_HOME`) or stored in the OS
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
