# FT-GTT-001 — full order flow and native broker capabilities

## Status and purpose

Proposed design for owner review, replacing the narrower GTT-only proposal
in draft PR #308. This is a specification, not approved implementation or
evidence of operational readiness.

FlintTrade should support the order features each broker actually offers,
including native GTT. Entry, protection, modification, cancellation, close
and recovery need consistent safety checks and truthful status. Prioritise
execution when closing, without an additional FlintTrade hard slippage cap;
never promise a fill, price or completion time.

## 1. Capability-driven order flow

Maintain a capability contract for each broker/account/product/segment:
order types, validity, native triggers, OCO/bracket/cover features, supported
fields, quantity rules, modification, cancellation and observable books.
Distinguish documented broker support, implemented adapter support and
verified readiness. Unknown capability is not proof of support.

Cover the six current native adapters: Dhan, Upstox, Kotak Neo, INDmoney,
Groww and Delta Exchange. Version capability records and distinguish API
support from app-only features, account eligibility, temporary broker
restrictions and implementation gaps. Never invent an API to achieve parity.

Before entry or modification, validate instrument identity, side, product,
session/AMO rules, lot/tick/freeze limits, permitted quantity, available
funds or holdings authorisation, and broker permissions. Retain native
order-family parameters and requested versus effective values. Rejections
must identify the broker reason and affected item. Batch/sliced orders have
per-child outcomes; partial success is not an atomic all-or-nothing result.

Preserve meaningful native features and semantics across OrderPad,
ForeverOrders and other reachable surfaces. Do not silently discard fields
or describe materially different broker behaviour with the same promise.
If a broker ignores a protection field, it cannot appear active. If it
converts a market request to a limit, disclose that execution behaviour.

Missing native reduce-only does not inherently disable native GTT. Runtime
readiness and safety requirements still gate actual writes; a proposed
capability is not permission to bypass an existing runtime refusal.

Official references include [Dhan Forever Orders](https://dhanhq.co/docs/v2/forever/)
and [Kotak Neo order documentation](https://github.com/Kotak-Neo/kotak-neo-python/blob/main/docs/functions/orders/place_order.md).
Record version/date and validate each adapter's actual semantics before
enablement. These published schemas do not establish atomic reduce-only
support; a client flag or placement-time position check cannot supply it.
Where a broker does provide a native reduce-only primitive, use and preserve
it for eligible exits instead of substituting a weaker client-only check.

## 2. Shared lifecycle contract

Track user intent separately from broker attempts. States must distinguish
`REQUESTED`, `SUBMITTING`, `ACKNOWLEDGED`, `WORKING`, `PARTIALLY_FILLED`,
`MODIFY_PENDING`, `CANCEL_PENDING`, `UNKNOWN` and terminal attempt outcomes
such as `FILLED`, `CANCELLED`, `REJECTED` and `EXPIRED`. Protection resources
also distinguish armed, triggered and spawned execution orders. Exit-intent
outcomes such as `FAILED` and `CLOSED` are separate from attempt states.
ACK, HTTP success and an order ID establish
neither a fill nor a closed position.

`CLOSED` requires coherent, fresh position/fill evidence that the intended
exposure is flat and no linked executable or unresolved exit remains.
Flat exposure with a live sibling remains a visible execution hazard.
External position changes and reversals must be shown explicitly.

Use explicit broker status mappings. `CANCEL_PENDING`, `CANCEL_REQUESTED`
and documented variants remain potentially executable. Blank/unrecognised
statuses, including strings containing CANCEL, REJECT or COMPLETE, must not
be classified terminal by substring. Preserve fills preceding cancellation,
rejection or expiry. A terminal trigger does not prove that its spawned
exchange order is terminal.

## 3. Quantity reconciliation

Scope evidence by mode, broker, account, instrument/expiry, segment and
product. Reconcile positions, fills, ordinary orders, visible triggers and
their children before submitting a replacement. Timestamps alone do not
prove cross-book consistency.

Let `P` be the reconciled remaining position eligible for the authorised
intent, retaining its original direction. Let `W` be unique outstanding
executable exit quantities and unmatched reservations. Additional quantity
cannot exceed `max(0, P - W)` or the remaining authorised intent.

Count remaining quantities and confirmed fills once. Deduplicate local and
broker records by stable account-scoped identity; transfer reservations
without counting their broker orders again. Include external orders and
pending cancellations. Do not assume OCO siblings are mutually exclusive
without proven broker semantics. Ambiguous identity, unavailable/incomplete
books or conflicting quantities block automatic replacement.

Example: a 40 fill already reflected in a position falling from 100 to 60
leaves 60, not 20. A separate executable exit with 20 remaining leaves an
additional cap of 40. Reconcile any cancellation-race fills before releasing
that order's remaining quantity.

These checks mitigate risk; they cannot guarantee that concurrent external
trading will never cause a reversal without broker-enforced protection.

## 4. Execution-first close and recovery

An explicit close intent may progress towards its requested remaining
quantity. Automatic recovery of a failed stop additionally requires an
authorised protection policy covering that position; importing a broker
trigger does not authorise recovery trading.

After definite failure, reconcile exposure and every potentially executable
attempt. Where supported and permitted, submit the eligible remainder as a
market order through the existing safety-context/router path. Record each
attempt against the same intent. Do not reuse the original quantity blindly.
Unsupported market execution requires an explicit supported alternative,
not a silent capped-limit substitution.

Do not replace a working order while it can still execute. Within the
authorised flow, cancel, wait for authoritative terminal evidence, reconcile
final fills, then reconsider the remainder. Cancel ACK and disappearance
from one list are insufficient alone.

Lost responses/timeouts produce `UNKNOWN`; never blindly replay submission
or cancellation, release reservations on a timer, or assume transport is
exactly once. Reconcile verified identities/history. Retry only after
definite non-execution or a validated broker idempotency contract.
Correlation tags alone are not idempotency guarantees. This replay rule
concerns the original request; a new attempt for a confirmed unfilled
remainder follows the quantity and terminal-evidence rules above.

Unchanged permission, validation, market or broker failures must not spin.
Further attempts require changed preconditions, fresh reconciliation and
continued authorisation. Session, account and safety gates remain binding;
entry-pause/kill-switch exit policy must remain explicit.

## 5. Native GTT, OCO and honest presentation

Native triggers may fire while FlintTrade is offline. Preserve supported
listing, creation, modification and cancellation, with broker-specific
constraints and clear entry-versus-protection intent. Position linking and
best-effort cancellation/resizing do not make execution atomically
reduce-only. Never label an unproven order “It can only reduce this position”.

List all supported returned segments/products, including externally placed
orders. Native entry triggers remain valid where the broker supports them;
having no current position does not by itself make an entry trigger invalid.
Mark orphaned, oversized or direction-inconsistent position-linked
protection `Unexpected`; use `Unlinked` when intent/provenance is unknown
and claim external provenance only when established. Manual
closes, partial closes, square-off and expiry must expose stale protection.
When an OCO leg fills, reconcile/cancel its sibling where supported and
authorised; retain its executable risk until confirmed resolved.

Use persistent rows/banners plus sticky failure/uncertainty notifications:

- “Your broker may execute this GTT while FlintTrade is offline. It could
  open or reverse a position if your position changes.”
- “Cancel pending. This order may still fill.”
- “Exit status unknown. An order may still execute.”
- “This prioritises execution. The fill price may differ significantly,
  and execution isn't guaranteed.”

Confirmed stop rejection with exposure remaining shows `Stop failed` and
offers the gated Close action. If exposure is unknown, say so. Retain DDPI
warnings for relevant CNC stops and broker-specific visibility limitations.
Unavailable/unsupported books must never appear as verified empty books.
Toast dismissal, navigation and repeated clicks cannot clear unresolved
state or create duplicate attempts.

## 6. Acceptance and evidence gates

Define deterministic stub unit, UI and route tests covering:

- ACK versus fill versus confirmed close; partial fills and terminal states.
- Pending/unknown cancellation, substring traps, late and duplicate events.
- Lost submit/cancel responses, no blind replay, coherent quantity accounting,
  external orders, sign changes, OCO/child races and unreadable books.
- Definite-failure market recovery, unchanged-failure no-spin behaviour,
  unsupported alternatives and unauthorised imported-trigger recovery.
- OrderPad/ForeverOrders parity and all reachable API, batch, nested and
  bracket/cover routes; no ungated or unsupported-field bypass.
- Persistent failure/uncertainty, repeated clicks, refresh, account switching,
  visibility limitations and accurate broker-semantic copy.

Stub success does not establish live safety. Before dependent enablement,
establish adapter mappings, read consistency, durable intent/attempt
recovery, cross-process coordination and crash-after-write reconciliation.
Process-local reservations alone cannot prove restart safety. Restart and
end-to-end live acceptance remain unverified until those prerequisites and
separately authorised integration evidence exist.

## Boundaries and known gaps

At main `091510bf20501354102407afd139efcb570a461d`, independent inspection
found terminal-substring classification in `reduce_only.py::_order_is_open`
and `Positions/positionReconcile.ts::orderStatusIsOpen`, an unreadable-book
local-state fallback, and process-local reservations. ForeverOrders has its
own create/modify surface. These are later implementation requirements,
not repairs delivered here.

This spec introduces no hosted triggers, credentials work, broker activity,
live validation, release or implementation plan. Shared lifecycle status is
in scope; durable integration remains a separate evidence gate. Preserve
unrelated work.

## Public capability evidence to carry into implementation

Evidence checked 2026-10-06; verify versions and eligibility before wiring
individual operations. This is a starting inventory, not exhaustive parity
or current adapter-readiness certification.

- Dhan: [Forever SINGLE/OCO](https://dhanhq.co/docs/v2/forever/) and
  [Super orders](https://dhanhq.co/docs/v2/super-order/) have distinct native
  contracts; preserve them rather than map everything to a plain order.
- Upstox: [native GTT](https://upstox.com/developer/api-documentation/place-gtt-order/)
  and [V3 placement](https://upstox.com/developer/api-documentation/v3/place-order/)
  require feature, segment and market-protection eligibility checks.
- Kotak: [current migration guidance](https://github.com/Kotak-Neo/kotak-neo-python/blob/main/docs/guides/MIGRATION.md)
  removes legacy CO/BO and several validity types. Do not infer current
  support from old examples; native GTT API support remains unestablished.
- INDstocks: [smart-order documentation](https://api-docs.indstocks.com/smart_orders/)
  says trailing-stop fields are currently ignored;
  [normal orders](https://api-docs.indstocks.com/normal_orders/) document
  market-to-limit conversion. Neither may be represented as stronger
  protection or execution than the broker provides.
- Groww: [smart orders](https://groww.in/trade-api/docs/curl/smart-orders)
  document native GTT/OCO and resource-specific editable fields.
- Delta: [official API](https://docs.delta.exchange/) documents native
  reduce-only, conditional/bracket families and batch/close operations;
  retain their product constraints and per-item failure semantics.
