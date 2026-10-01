# Autonomous agent harness

FlintTrade's existing Autonomous Agent now has an isolated **Practice** runtime.
It reuses `AutonomousTrader`, configured and authorised market-data reads, Laya
admission and the real `SandboxEngine`. It does not place real-money orders.

## Before starting

- Use a full, authenticated Practice session. Explore, setup tokens, expired
  sessions and a contradictory mode header cannot start this runtime.
- Enable `ai.autonomous_agent.enabled` in the workspace. Configure an LLM using
  the existing AI settings and establish the configured market-data accounts.
- Laya must satisfy the normal Practice admission requirements. A configured
  chat model is not Laya readiness, and Practice readiness is not Live approval.
- The canonical calendar, rate limiter, sandbox and backend ownership must be
  available. The harness does not remove native-account setup/read-port guards.
- The current complete market-input route is a working OpenAlgo connection.
  Native saved-session reconnection/account setup remains behind the existing
  lifecycle cutover, and native depth is not yet implemented. The harness
  refuses unavailable required inputs rather than pretending a native session
  is ready.
- Start with an empty Practice position book and no pending Practice orders.
  Existing manual exposure is not silently adopted by an agent.

Select **Advanced** skill level and **Practice** mode, then open **AI → Agent**.
Enter exact instrument symbols, exchange, position quantity
in **units**, stop-loss percentage and take-profit percentage. For derivatives,
use the exact contract and its valid quantity; the harness does not guess a lot
size from an underlying name. Start is an explicit operator action. An optional entry rationale (up to 2,000
characters) records your standing purpose for the entries. This is
operator-authored text, not model reasoning. Laya still decides each proposal;
providing a rationale does not approve a refusal or clamp. Never put credentials
in this field.

## Behaviour

The worker waits outside the effective market session. During an open session
it reads authorised market data, asks the configured LLM for a signal, applies
agent limits and submits through canonical Practice admission. New entries
also require the shared L5 kill switch to be available and clear. A kill latch
brakes new model work and entries; only server-proven reducing exits remain
available. Final write admission is held only around the synchronous sandbox
write, after Laya has decided. Laya refusals
and quantity clamps do not place an order and are never automatically accepted
or retried. Orders require a confirmed sandbox fill before they become tracked
agent positions. Percentage-based stop and target monitoring thresholds are
rebased on that confirmed fill, preserving the assessed percentages rather
than retaining stale quote-based levels. Derivative orders require an exact, freshly receipted contract
lot size from the authorised quote account. Missing metadata or a quantity
that is not a valid lot multiple is refused; there is no lot-size fallback.

A daily-loss brake stops new entries while retaining protective monitoring.
Stop and session-boundary cleanup use the existing protective-exit logic;
refused or uncertain exits remain visible. A stop received during a slow model
or admission call is checked again before an entry can be written. Feature
disablement and market-session changes also brake new entries.

The agent settles positions before a daily reset and runs the existing learning
reflection after a flat session. Stored lessons may inform later prompts;
they cannot alter safety limits or grant execution authority.

### Bounded model usage

Every Practice run has explicit model bounds:

- `model_call_limit`: 500 by default, an integer from 1 to 10,000 across the
  entire run, including every signal request and post-session reflection
- `model_output_limit`: 512 by default, an integer from 16 to 4,096 output
  tokens per request

These are request and output limits, **not a currency cap or an input-token
limit**. Provider pricing and billed usage can vary. Failed requests and
unknown outcomes still consume a reserved attempt. The limit does not reset
with the trading session, and no run is silently resumed after interruption.

The runtime freezes a dedicated copy of the selected model configuration when
the run starts. Later Settings changes apply to future runs. Provider fallback
and empty-reasoning retries are disabled for this client, and per-call output
overrides cannot exceed the run's limit. A request cannot select a different
model from the frozen configuration. Other AI clients are unchanged.

A `model_attempt_reserved` event must commit before each provider request. If
that evidence cannot be written, no request is sent. The final reserved request
may complete its decision and pass normal entry admission. A later request is
refused before dispatch, stops new entries and initiates normal protected
settlement. Reflection is skipped once no attempts remain. Budget exhaustion
is a normal stop reason, distinct from an unavailable or failing model.

Analysis admission freshly checks the shared kill switch, operator session,
runtime ownership, stop state and session boundaries before reservation and
again immediately before provider dispatch. A safety refusal does not consume
an attempt unless its reservation had already committed; it records a safe
`safety_brake` reason without labelling the provider unavailable. Active kill
switches also skip post-session reflection.

Status snapshots expose `model_usage` with both limits, `model_calls_used`,
`model_calls_remaining` and `status` (`available`, `exhausted` or
`evidence_unavailable`). Reservation evidence contains only safe counts and
operation/status labels, never prompts, responses, API keys or provider error
text. After interruption, the latest reservation events remain the durable
record of attempted usage, even if the last cycle snapshot was not committed.

The run remains bound to its original signed operator session. It cannot
renew authentication or reconstruct credentials from saved evidence. Session
expiry, revoked backend ownership, unavailable required inputs or failed
persistence stop new execution and can require reconciliation.

## Run history and recovery

Practice run identity, configuration, lifecycle, snapshots and ordered events
are stored in `practice_agent_runs.sqlite` in the platform workspace. Auth
credentials are not stored in this ledger. Each lifecycle transition commits
its run row, snapshot and transition event atomically; a failed write cannot
leave a phantom successful transition. The UI exposes run history and
paginated evidence, including refusals and interrupted runs.

After a process interruption, an active run becomes **Reconciliation required**.
It is never silently resumed and uncertain orders are never replayed. Inspect
Practice positions and pending orders, then use the explicit resolution action.
The backend must prove the sandbox is flat before releasing the run for a new
start. Resolution is an acknowledgement of the reconciled state, not an order
or an automatic liquidation.

One app-owned worker and one durable active run are allowed. The runtime retains
ownership until execution, learning and resource cleanup actually complete.
An incomplete stop must not be presented as a successful flat shutdown.

## API

Existing control endpoints select the runtime from the signed session mode:

- `POST /api/v1/ai/agent/start`
- `POST /api/v1/ai/agent/stop`
- `GET /api/v1/ai/agent/status`

Practice evidence endpoints require a full Practice session and the owning
operator identity:

- `GET /api/v1/ai/agent/practice/runs`
- `GET /api/v1/ai/agent/practice/runs/{run_id}/events?after=0&limit=100`
- `POST /api/v1/ai/agent/practice/runs/{run_id}/resolve`

A current running worker is not equivalent to a ready decision provider or a
qualified trading strategy. Read the lifecycle and last failure together.

## Live boundaries and evidence limits

The existing Live agent retains operator-approved entry intentions and the
Laya → SafetySystem → `gate_order` → `BrokerRouter` chain. A broker order-id
acknowledgement is not a confirmed fill: an approved Live intention cannot
rotate into another intention for that symbol without reconciliation.

Automated tests use synthetic model/data boundaries, real signed test sessions
and a real sandbox. Such tests prove the local wiring and failure handling;
they are not a real trading-day run, native-broker live acceptance, profitable
strategy qualification, distribution signing, or funded-order authorisation.
The separate native account-lifecycle, forecast, research-isolation and qualification
backlog remains subject to its own implementation and evidence gates.
