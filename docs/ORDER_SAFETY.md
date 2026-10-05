# Order Safety Notes

FlintTrade is personal-use, self-hosted software. It is not a broker, an
investment adviser, a managed strategy product, a compliance product, or a
service that accepts funds or account access from other people. Nothing in this
repository is financial, investment, tax, legal, or regulatory advice.

This page describes the technical safety controls FlintTrade applies when an
operator enables an order-capable integration. Broker, exchange, tax, and
regulatory responsibilities remain with the operator and their broker.

## Order-Gating Model

Every reachable live write must mint a one-shot HMAC `SafetyContext` and
dispatch through `BrokerRouter`. A route, widget, automation, webhook, agent,
or script must not call a broker adapter or `OpenAlgoClient.place_order`
directly. Placement, regular modify/cancel, and extended verbs use different
gates — pick the matching one.

**Placement.** Every order FlintTrade submits goes through admission
when it's placed. The HTTP routes that submit an order are
`POST /api/v1/orders/place`, `POST /api/v1/orders/<broker>/place`,
`POST /api/v1/positions/exit-all`, and `POST /api/v1/orders/bracket`
when the body has exactly one stop-loss or one target. Each bracket leg
is admitted, then placed through SafetySystem, `gate_order`, and
`BrokerRouter`. Practice on that route is HTTP 403 `practice_unsupported`.
GTT, a broker-held variety, a stop-loss and a target together, and a
trailing stop are refused before that admission. Operator and automate
place (core `/orders/place`, strategy dispatch, and webhook place) share
the admission below. `place-smart`, `open-position`, and `close-position`
are not mounted. The Practice sandbox has no place or square-off route.
Settings → Practice does not place.

1. The mode guard runs first. Example data stays HTTP 403 `mode_blocked`
   (`Orders are not available for Example. Switch to Practice or Live to trade.`)
   and does not enter `Laya.admit`. The `/trade` Order Pad records a sample
   fill on the client for example data (`Example order placed`, id starting
   `SAMPLE-`). This guard is the server path.
2. `Laya.admit` then admits or refuses the proposal. A refusal
   (`laya_denied`) or a quantity clamp (`laya_clamp`) stops before
   SafetySystem on Live and before the native sandbox on Practice.
   Neither quantity is placed.
3. An allowed Live place runs `SafetySystem.check_order` in runtime order
   L5 → L4 → L1 → L2 → L3 (kill switch, daily P&L, field validation,
   position limits, portfolio risk).
4. `gate_order` then mints the `SafetyContext` bound to that order and the
   selector-bound principal. It does not re-run the layer checks.
   `gate_order` remains the only mint after an allowed Live place.
5. `BrokerRouter.place_order` re-HMACs, matches fields, applies the account
   ACL, and consumes the one-shot gate.

An allowed Practice place is admitted, then goes to the native sandbox. It
does not enter SafetySystem, `gate_order`, or `BrokerRouter`. When the
order names a security id, the quantity must be a positive multiple of
that contract's lot from the broker instrument master. If the master has
no lot, the sandbox refuses the order and does not fill it:
`Not placed. The lot size for NIFTY 24500 CE isn't in the instrument master, so this order can't be sized.`
An expired future is named as the desk shows it, for example
`NIFTY-OCT2026-FUT`. The routed place route is Live only and uses the same
Live admission. Modify and cancel are not this admission. `POST /api/v1/orders/cancel-all` only
cancels. A body with `"variety": "gtt"` is HTTP 422 `gtt_unsupported`
before Laya, SafetySystem, and any broker call, on place, routed place,
exit-all, and a bracket. The message is `Not placed. GTT orders aren't supported right now.`
No submit route reaches a broker forever or super-order endpoint. The
Kotak Neo adapter refuses a `gtt` place. `POST /api/v1/orders/forever` returns
HTTP 501 `Orders are placed through /api/v1/orders/place.` and does not
call a broker. Practice and Live both refuse that variety before the
sandbox or a broker. The Order Pad GTT option stays visible and disabled,
with the tooltip `GTT orders aren't supported right now.`

**Regular modify and cancel:**

1. Ordinary modify and cancel are blocked while Layer 5 is latched. A
   cancellation can remove a protective exit, so it is not exempt.
2. A risk-increasing modify also runs `SafetySystem.check_order` on the
   proposed order. A proven no-increase modify and a cancel skip that chain.
3. `gate_order` mints the `SafetyContext` over the canonical fingerprint
   (`_op` is `modify` or `cancel`).
4. `BrokerRouter.modify_order` / `cancel_order` re-verify and consume the
   gate.

**Extended verbs** (forever modify/cancel, super-order, conditional
trigger modify/cancel, convert, exit-all, reducing, multi, cancel-all,
smart-cancel). Exit-all is a submit route: the server records a
reduce-only proof for each open contract before `exit_all_positions`.
Forever, basket, split, and trigger *place* are not submit routes.

1. Risk-increasing legs still run `SafetySystem.check_order` where the
   route admits exposure.
2. `gate_broker_write` mints the `SafetyContext` (it delegates to
   `gate_order`, which remains the sole mint). The verb must be listed in
   `GATED_WRITE_VERBS` and `payload["_op"]` must equal the verb.
3. `BrokerRouter.execute_gated` re-verifies and dispatches.

New integrations must preserve this split. Do not invent a third path, and
do not send an extended verb through `gate_order` alone.

## Laya admission

An operator or automate proposal is admitted or refused as a typed verdict
with `allow`, `reason`, and `limits`. Laya does not place an order and does
not mint the one-shot write ticket. `gate_order` remains the only mint.
Chat may suggest and explain only: bring your own API key, use managed
Ollama, or point **Custom (OpenAI-compatible)** at another local runtime.
Chat is not an admission source, and Chat downtime does not close Live.

Operator and automate place run the mode guard, then `Laya.admit`.
**Live** place then runs SafetySystem L1–L5, `gate_order`, and
`BrokerRouter`. Laya does not replace those layers, and `gate_order`
remains the only mint after an allowed Live place. **Practice** place is
admitted before the sandbox and does not enter SafetySystem, `gate_order`,
or `BrokerRouter`. Example data stays `mode_blocked` before admit. A refusal
(`laya_denied`) or a quantity clamp (`laya_clamp`) stops before
SafetySystem on Live and before the sandbox on Practice. A clamp names
the reduced quantity. Neither size is placed. Order Pad and Quick Trade
require the operator to place that reduced quantity. An automate clamp is
a dispatcher error and does not place the reduced quantity on its own.
Chat is not an admission source. Modify, cancel, and cancel-all are not
admitted as place. Forever place, basket, split, and conditional-trigger
place do not submit. A Live bracket with exactly one stop-loss or one
target does submit. A GTT body is refused on every submit route
before Laya admission and SafetySystem. No submit route reaches a broker
forever or super-order endpoint. The Kotak Neo adapter refuses a `gtt` place.

Admission order is fixed. Down is checked first. The existing hard rules
then run unchanged (source, mode, symbol, side, quantity, price, trigger).
Only after those rules pass does Laya ask typed A/B questions about free
text: whether a note states a reason, whether it shows tilt or revenge, and
whether the stated plan contradicts the order side. Expiry, quantity, price,
and symbol are not sent to the model. Thresholds sit on option probabilities
in the versioned `laya_policy.toml`. There is no confidence field in the
gate. The model can deny or clamp. It cannot raise a quantity or overturn a
rule refusal. An unreachable host, a timeout, a malformed response, or a
revision or digest mismatch is Down. Down refuses Practice as well as Live.
Down copy is the same in every mode: "Laya is Down. New orders are paused until it's Ready. You can still close positions." A non-exit order is HTTP 403. That refusal carries no quantity ceiling. A Practice
refusal never says Live. When Laya is Ready
or Degraded and a Live place is refused only because Live is not qualified,
the reason is "Laya isn't qualified for Live yet. Practice orders are
available." An uncertain answer, including an empty note, clamps in
Practice and denies in Live. It is not a hard reject. The Practice server
reason is "Laya is uncertain. Quantity stays inside the tighter limit."
The Live server reason is "Laya is uncertain. Live stays closed." On a
denial, Order Pad and Quick Trade show that server reason inside one
alert (`role="alert"`), the only live region. The reason line is named
"Laya decision" and is not its own status. The desk
does not auto-place. A clamp is only when the requested quantity is
greater than the allowed one. Order Pad and Quick Trade show "Not placed.
Laya allows up to N." with Place N and Cancel. Place N sends that
quantity. On Order Pad, "Review Practice order" then shows the placed
quantity. Place 1 on "Not placed. Laya allows up to 1." places, because
that request is already at the allowed quantity.

Chip reason codes are `not_started` (Not started), `stopped` (Stopped),
`port_in_use` (`Port <n> in use`), `still_loading` (Still loading),
`downloading` (`Downloading the model · X of Y GB`), `download_failed`
(Can't download the model), `unreachable` (Unreachable), `unverified`
(Can't verify the model), `wrong_revision` (Wrong model version),
`key_rejected` (Can't reach Laya), and `key_missing` (The Laya API key file is missing.). A health check does not replace `key_missing` with Not started. `<n>` is the sidecar port. For
`not_started`, `stopped`, `port_in_use`, `still_loading`, and
`unreachable`, the tooltip is the label followed by
`. Next: python -m flinttrade_core.laya_runtime start`. `downloading`
has no tooltip and no Next line, and it is not Still loading. The
`download_failed` tooltip is "Check your connection, then Start Laya again."
`downloading` and `download_failed` use the status word Down. Orders are
refused with "Laya is Down. New orders are paused until it's Ready. You can still close positions."
The `unverified` tooltip is "The installed model couldn't be checked
against the pinned version. Restart Laya. If it keeps happening, reinstall
it." That code applies when this start did not download. A failed download,
including one over an older unverified snapshot, is `download_failed`
("Can't download the model"). The `wrong_revision` tooltip is "Laya is running a different model
than FlintTrade expects." That code is only a real mismatch: a complete
download whose files do not match the pin, a snapshot already on disk
that this start is not replacing, or a running sidecar that reports
another revision or digest. A dropped connection, a partial download, or
a failed download or swap, including one that puts the previous
checkpoint back, is not this code. The
`key_rejected` tooltip is "Laya restarted with a new key. Reconnecting…"
The chip stays Down and orders are refused. When a place is refused
because Laya cannot be reached, or because it rejects the key, the chip
updates on that same order: Unreachable, or Can't reach Laya. The
refusal text stays "Laya is Down. New orders are paused until it's Ready. You can still close positions."
Every chip-Down refusal reads that sentence.

`identity_absent` is not a chip code. When the chip is Ready and a single
decision carries no proof, the refusal code is `laya_unverified` and the
refusal reads "Not placed. Laya's decision couldn't be verified. Try again."

On each sidecar start FlintTrade hashes `model.safetensors` and every
file in `[checkpoint.manifest]` before launch. The runtime record holds
the sha256, pid, and start token, and the inode, size, and modification
time of the weights file and of each pinned file
(`<workspace>/runtime/laya/verification.json`, with the token and pid
also in `run.json`). Every `stop` deletes that record, as does a start
that fails after it was written. A record from an earlier run is
rejected. A decision without `revision` or `sha256` is checked against
that record for both admitted and clamped orders. The decision log is
`<workspace>/runtime/laya/decisions.jsonl`. It records `proof=decision`
or `proof=runtime`. An admitted Practice place with an empty note skips
the model and writes one line, `effect=clamp` with `failure=note_absent`
and no proof, including when the quantity already fits. When this run's
record stood in, each model allow keeps its own `effect=allow`
`proof=runtime` line. There is no dedupe. A model decision with no proof is refused with "Not placed.
Laya's decision couldn't be verified. Try again." A health document that
omits the digest is Ready when that record matches the pin. If the
record cannot be checked, the chip reason is `unverified`. Stopping the
sidecar records Down before an in-flight probe can publish Ready. Desk
place surfaces go through this admission. Laya is not Ready by default.

The pins live in
`packages/services/engine/src/flinttrade_engine/laya_policy.toml`.
`[checkpoint]` names `revision` beside `sha256`, and the weights file `model.safetensors`.
`[checkpoint.manifest]` pins these files by sha256: `rl_agent_config.json`,
`encoder/config.json`, `tokenizer/tokenizer_config.json`, and
`tokenizer/tokenizer.json`. FlintTrade hashes each of them before launch.
When the files are already on disk and this start is not replacing them,
a missing pinned file, a shard index (`model.safetensors.index.json`),
or any extra weights file or other file the launcher could read shows
Can't verify the model (`unverified`) and the sidecar does not start. A
changed byte in a snapshot that this start is not replacing shows Wrong
model version (`wrong_revision`) and the sidecar does not start. A changed
byte in the runtime checkpoint starts the download below; the sidecar does
not start on that tree. Laya does not reach Ready in these cases. `start`
downloads the commit in `[checkpoint] revision`, not the model repository's
default branch, into `<workspace>/runtime/laya/staging` when the weights
file or a manifest file is not on disk, and when the runtime checkpoint
is on disk but its hashes are not the pin. The download does not start
the sidecar. That download sets `HF_HOME` to
`<workspace>/runtime/laya/hf-home` and `HF_HUB_DISABLE_XET=1`, so transfer
logs stay out of the shared cache. The model is about 2.37 GB, and that
size is reported once. While it runs, including a pin change, the chip is
`Downloading the model · X of Y GB` (for example `Downloading the model · 1.2 of 3.4 GB`) and the status word is Down. There
is no Updating label. When no checkpoint is already there, a full match
renames staging onto `<workspace>/runtime/laya/checkpoint`. When a
checkpoint is already there, the current copy stays in place until the
new files match. On a full match that checkpoint is renamed aside to
`checkpoint.old-<random>` in the same runtime directory, staging is
renamed onto `checkpoint`, then the old copy is deleted. Hub access stays
off for that launch. If that second rename fails, the old checkpoint is
renamed back and the chip is `download_failed` ("Can't download the
model"), not `wrong_revision`. A complete download whose files do not
match the pin is `wrong_revision`, staging is deleted, and the checkpoint
already on disk stays. An extra loadable file in a complete download is
`unverified`. A dropped connection, a partial or missing file, or a read
error is also `download_failed`. The sidecar does not start on files that
do not match the pin. If the download does not finish, the chip is `download_failed`, not
`wrong_revision` and not `unverified`, whatever older snapshot is on
disk. `unverified` stays when this start did not download. A snapshot
already on disk is `wrong_revision` only when this start did not
download. Those failures delete the staging directory and leave the shared
model cache alone. Leftover staging directories and `checkpoint.old-*`
copies are removed at the start of `start` once a checkpoint is in place,
with no chip change and no message. If `checkpoint` is missing and one or
more `checkpoint.old-*` copies remain, the last `checkpoint.old-*` name
is restored onto `checkpoint` and any other aside copies are removed. If that restore
fails, the aside copy stays where it is and that cleanup is skipped. A
copy that was restored is then checked against the pin. If it does not
match, the sidecar does not start on it; the pinned download runs
instead, and a failed download leaves `download_failed` with that copy
still on disk.
A verified boot
sets `LAYA_WEIGHTS_PATH` to that hashed weights file. A model already in
the standard Hugging Face cache is accepted. When that file is the cache
symlink (`snapshots/<revision>/model.safetensors` into `blobs/`), the
launch path is the snapshot file, not the blob. A blob path is still
refused. The boot runs offline
(`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`). It does not pass a repo
id or a revision. When the sidecar health document leaves the revision
empty, FlintTrade fills the pinned revision from the verified manifest, so
the chip leaves Still loading. The launch log line is
`laya weights path=<path> sha256=<digest>`. The recorded inode, size,
and modification time are rechecked, without hashing again, when Laya
reports Ready and on each watch tick, about every 1.5 seconds. If one
changes, the chip shows Can't verify the model and the log line is
`laya weights path=<path> changed=<field>`, where `<field>` is `inode`,
`size`, `mtime`, or a comma-separated list of those. The same watch
reads the pid file (`runtime/laya/sidecar.pid`), the key file
(`runtime/laya/api.key`), and the runtime record, so a command-line
stop or start, or a key rotation, is reconciled by that watch. The desk
polls `GET /api/v1/ping` every 1.5 seconds. That ping reconciles the
pid, the key, and the runtime record the same way an order does, so the
chip and the order gate read the same state. A stop or a start shows on
the chip by the next 1.5-second check. After Start Laya, until the ping confirms
the new state, the chip says Checking in the neutral colour and the
popover says Checking Laya…. It does not show a stale Ready during that
wait. An admitted place while the chip is not Ready or Degraded also
shows Checking until the next ping. A confirmed first load still says Still loading. A place refused
with exactly "Laya is Down. New orders are paused until it's Ready. You can still close positions." sets
the chip to Down on that response. The refusal line stays that sentence.
New orders stay paused. A reduce-only close is unchanged.

When decision status is Down, the desk opens incident class `laya` ("Laya is
Down. New orders are paused until it's Ready. You can still close positions.").
That class closes a new Live place and Position Mirror start on the shared
client place path. The server decides reduce-only. A client flag is ignored.
A close qualifies inside either place route when it is the same contract,
the opposite side, and the quantity is no more than the open quantity minus
pending exits. Pending exits are this desk's unfilled opposite orders. On
Live they also include the broker's open orders on that contract when that
book can be read. An unreadable broker order book still admits a reduce-only
close, capped at the open quantity minus this desk's own pending exits. An
unreadable position book is not classified as a close. Laya records a
qualifying close with proof kind `reduce_only` and does not deny or clamp
it. Down and Degraded do not block it. Live still runs
SafetySystem after that record. A second exit on the same broker account,
while one of this desk's exits on that contract is still unfilled, is
HTTP 409 `exit_pending`:
`"Not placed. An exit for <symbol> is already pending. Wait for it to fill, or cancel it and try again."`
Practice uses this code on the Practice book. On Live it is the code when
the broker order book can be read. The Live hold is for that broker
account. When the broker order book cannot be read, that refusal is HTTP 409
`exit_orders_unreadable`: `"Not placed. One exit at a time for <symbol> until your broker's orders load."`
`message` and `reason` are that same text. The label is the symbol, or `this contract` when the symbol is empty.
The Positions row shows **Exit pending** for the unfilled-exit case. A position whose sign flips after the broker book has
loaded keeps that row, tagged **Unexpected**, and the book shows
`Position changed after your broker's orders loaded. You're now <long or short> <quantity> <symbol>. Close it if that wasn't intended.`
until dismissed.
Anything that would flip or add to a position takes the full admit.
`POST /api/v1/positions/exit-all` uses the same classification as a
server-side proof before it flattens. `POST /api/v1/orders/cancel-all`
only cancels. Layer 5 and Ditto Kill All cancel resting orders and then
flatten; they stay reachable while Laya is Down, and they are not
cancel-only. A filled reducing close can show "Closed. Exits are allowed
while Laya is Down."
Broker may stay **Connected** or **Connected (read)**. Laya starts Down.
`GET /health` records Ready, Degraded, or Down from the opt-in sidecar when
one is registered. The desk polls `GET /api/v1/ping` every 1.5 seconds. That ping reconciles the watched pid, key, and runtime record the same way an order does, then
publishes Live-facing `laya`, sidecar `laya_practice`,
`laya_live_qualified`, `laya_reason`, and `laya_port`. It does not invent Ready. The Laya chip label follows
the current mode, so Practice shows the sidecar and does not read Down while
Practice orders are being admitted. During the first load the chip says
Still loading. "Not qualified for Live" is the chip tooltip and the popover
line when the sidecar is up and Live is not qualified. A base checkpoint is not
qualified for Live, so Live stays Down until a qualification record exists
for the exact model revision, weight digest, and policy version
(`EvidenceUseScope.LIVE_DECISION`). Practice can be Ready or Degraded from
the same probe. Degraded does not open that class and does not mute Live.
Degraded enforces the tighter quantity ceiling and the desk says so. Down
does not add a second deny under a Live control that is already muted.
Other Live write verbs still reach SafetySystem without this admission.
Other Practice verbs go straight to the sandbox. The sidecar install is in
[DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md#laya-decision-sidecar).
Operator steps are in [Start Laya](USER_GUIDE.md#start-laya).

| Concern | Automate risk note | SafetySystem | Ticket guards | Laya |
| --- | --- | --- | --- | --- |
| Allow or deny | `allowed` and `reason` | L1–L5 pass or fail | refusal string | verdict `allow` and `reason` |
| Size | `position_qty` | L1 quantity, L2 limits | lot multiple | `limits.max_quantity` |
| Price | stop and target | L1 price band | limit and trigger present | price and trigger present |
| Mode | not modelled | mode guard | Example data refused | Example data stays `mode_blocked` before admit; Down refuses the proposal |
| Book, margin, Greeks, daily loss, kill | daily loss is agent config | L2–L5 | not present | not owned |

The automate risk note is not this admission. Lot size, the price band,
margin, Greeks, daily loss, and the kill switch stay where they are.

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

`SafetySystem` has five layers (L1–L5). Rate limits are a separate
HTTP/`OpenAlgoClient` control, not a sixth safety layer.
`_check_order_locked` fail-fasts in runtime order **L5 → L4 → L1 → L2 →
L3**: the first failing layer is the refusal the operator sees.

| Layer | Purpose | Examples |
|---|---|---|
| L5 Kill switch | Stop order-capable workflows, cancel open orders, and request position flattening where supported. | Explicit UI button, API endpoint, or Telegram command. Checked first. |
| L4 Daily P&L | Pause or hard-stop subsequent new orders when daily loss thresholds are hit. | Default pause at 3 % and hard stop at 15 %; no broker-side cancel or flatten. |
| L1 Order validation | Reject malformed or disallowed orders before routing. | Symbol, exchange, side, quantity, order type, price, and market-session checks. |
| L2 Position limits | Prevent local workflows from exceeding configured exposure. | Default max five open positions and 60 % margin-use guard. |
| L3 Portfolio risk | Cap book-level Greek exposure. | Net delta and net vega guards. |

## Kill Switch

Kill switch triggers:

- Telegram bot: `/kill` command when the operator enables the integration.
- Terminal UI: the Kill Switch control on the `/trade` workspace (Live mode
  only), and Activate / Reset on `/automate` → Settings.
- API: `POST /api/v1/safety/kill-switch` to latch Layer 5 (JSON body
  `{ "reason": "…" }`). `DELETE /api/v1/safety/kill-switch` resets it after
  emergency actions complete. From the Vite dev proxy the same routes are
  `/ft-api/api/v1/safety/kill-switch`. There is no `/activate` suffix.

The percentage-based Layer 4 daily-loss thresholds do not activate this kill
switch. They latch new-order admission until manually reset. Automatic
account-level flattening, when enabled, is owned separately by the authoritative
rupee MTM circuit breaker.

The kill switch is a local software control. It should be paired with broker-side
limits, broker-side position checks, and manual review of live-mode settings.

## Audit Logging

FlintTrade writes local audit events for order and safety activity. The audit
directory is resolved by `audit_log_dir()`: `AUDIT_LOG_DIR` (direct directory),
then `<storage.archive>/audit` when `workspace.json` sets `storage.archive`,
then `archive/audit/` inside the workspace directory
(`FLINTTRADE_WORKSPACE_DIR`, then `FLINTTRADE_HOME`, then the OS default):

| Platform | Default audit archive |
|---|---|
| Linux | `~/.flinttrade/archive/audit/` |
| macOS | `~/Library/Application Support/flinttrade/archive/audit/` |
| Windows | `%APPDATA%\flinttrade\archive\audit\` |
| Override | `AUDIT_LOG_DIR`, then `<storage.archive>/audit`, then the workspace `archive/audit/` path above |

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
| Orders | 10 per second | FlintTrade order proxy: HTTP 429 `"Rate limit exceeded"` from `@rate_limit`. The OpenAlgo client additionally blocks in-process (`_RateLimiter.acquire`) before a bridge request leaves. |
| Smart orders | 2 per second | Same split: proxy 429 plus client-side throttle. |
| General API | 50 per second | OpenAlgo-compatible client throttle when the bridge is enabled. |

Limits apply across configured exchanges for the running FlintTrade instance.
Operators should also configure any limits available in their broker dashboard.

## Sessions And Credentials

- Broker login, OAuth, TOTP, and exchange access remain broker-side concerns.
- Native-adapter broker credentials live in the encrypted gateway vault.
- The account transaction foundation retains unknown authentication outcomes
  rather than retrying them. Its vault and workspace evidence must remain
  coherent before a read generation can be exposed. Redacted terminal audit
  events have durable pending delivery and stable IDs; audit export never
  repeats authentication or order work. Production native account HTTP
  mutations remain `503`, and native HTTP reads remain `409` until their
  separate cutovers land.
- The OpenAlgo-compatible bridge stores only the OpenAlgo API key in FlintTrade;
  broker authentication remains inside OpenAlgo.
- Secrets should be file-backed under your platform workspace directory
  (`~/.flinttrade/` on Linux, `~/Library/Application Support/flinttrade/` on
  macOS, `%APPDATA%\flinttrade\` on Windows; overridden by
  `FLINTTRADE_WORKSPACE_DIR`, then `FLINTTRADE_HOME`). Telegram and LLM
  credentials live as hardened files under `<workspace>/secrets/` with a
  `secret://` reference in `workspace.json`. Do not commit credentials or
  personal network details.

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
5. Confirm that every enabled automation still routes through `gate_order`
   or `gate_broker_write`.
6. Treat FlintTrade as local software for your own account, not as an investment
   service for others.
