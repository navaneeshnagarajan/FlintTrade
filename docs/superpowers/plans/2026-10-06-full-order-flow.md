# Full Order Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement FT-GTT-001 in independently reviewable slices, starting with conservative status/quantity handling and truthful UI, then broker-specific native-feature parity.

**Architecture:** Keep intent, execution attempts and native protection resources distinct. First repair independent classifiers and presentation without changing any runtime gate; then establish pure evidence/capability contracts before six separate adapter plans. Durable reconciliation, dispatch and enablement are a blocked integration stage, not a side effect of capability work.

**Tech Stack:** Python 3.12, pytest, React/TypeScript, TanStack Query, Vitest and Playwright; existing dependencies only.

**Spec:** [Approved FT-GTT-001](https://github.com/navaneeshnagarajan/FlintTrade/blob/b74a9434eaf5e0a318ebf730398527f16347af7e/docs/acceptance/FT-GTT-001.md). Read it alongside this plan.

## Global Constraints

- “Missing native reduce-only does not inherently disable native GTT.”
- “Runtime readiness and safety requirements still gate actual writes; a proposed capability is not permission to bypass an existing runtime refusal.”
- “Prioritise execution when closing, without an additional FlintTrade hard slippage cap; never promise a fill, price or completion time.”
- “Lost responses/timeouts produce `UNKNOWN`; never blindly replay submission or cancellation, release reservations on a timer, or assume transport is exactly once.”
- “Process-local reservations alone cannot prove restart safety.”
- Preserve all supported broker order families and fields; unsupported/unknown is different from temporarily unavailable. Never substitute app-only features for an API.
- All eventual writes retain `SafetyContext` through the existing gate and `BrokerRouter`; frontend native-write readiness checks remain unchanged.
- No dependency upgrades, funded broker actions, credentials work, hosted triggers or release actions are part of this plan.
- British English, explicit file staging, Conventional Commits, one command per line. No changelog entry for unshipped design.

## Review Focus

1. Cancel/reject/complete substrings must not release executable risk; Task 1 pins pending, blank and unfamiliar values.
2. Malformed or conflicting quantities must not create spare capacity; Task 2 pins invalid numbers, duplicate identities and incomplete books.
3. An ACK or a flat position with a live sibling must not look closed; Tasks 3–4 pin presentation and closure evidence separately.
4. Account switches, missing books and late events must not reuse another scope's evidence; Tasks 3–4 pin scope isolation and reconciliation.
5. Broker-native features may materially differ: ignored trailing stops, market-to-limit conversion and non-atomic batches must remain visible; Task 5 and the six adapter plans pin these differences.

---

## Baseline, boundaries and sequence

Source main: `091510bf20501354102407afd139efcb570a461d`, verified through GitHub on 2026-10-06. The inspected local source was its parent `bdd8d54e5103bfb1a7f9534f0ea8473e7475a65a`; the GitHub comparison confirms that the independent source/test files named below are unchanged in main. Dependency manifests changed in main: use main's environment when eventually executing. No project `.agents/skills` directory was present in the inspected checkout.

This document was prepared with read-only source inspection. No implementation, installation, test execution or operational validation has occurred.

**Stage A: Tasks 1–3.** One independently executable first slice; three small commits, one reviewable change set. Its result is narrower and more truthful behaviour, not full lifecycle safety.

**Stage B: Tasks 4–5.** Pure, stub-tested contracts; no provider/router registration or capability enablement.

**Stage C: six separate adapter plans.** Ground each full implementation in the settled contracts and broker-version evidence. Do not combine six adapters into a speculative rewrite.

**Stage D: integration remains blocked.** Durable dispatch and authoritative read-coherence integration are outside this plan's executable scope. Existing operational gates remain. Their separately verified completion is a prerequisite for automatic recovery, reliable restart behaviour and native write enablement.

Path aliases below are exact repository prefixes, not new directories:
- `E` = `packages/services/engine`
- `G` = `packages/integrations/gateway`
- `T` = `packages/apps/terminal/src`
- `B` = `G/src/flinttrade_gateway/brokers`

## Task 1: Preserve pending and unknown execution risk

**Files:** modify `E/src/flinttrade_engine/reduce_only.py` and `T/widgets/trading/Positions/positionReconcile.ts`; extend `E/tests/test_reduce_only.py` and `T/widgets/trading/Positions/positionReconcile.test.ts`.

**Interfaces:** preserve `_order_is_open(row: Mapping[str, object]) -> bool`, `orderStatusIsOpen(status: string): boolean` and `contractHasOpenExit(position: ContractFields, orders: readonly ExitOrderFields[]): boolean`. These are conservative executable-risk predicates, not complete lifecycle classifiers.

- [ ] Add parametrised tests `test_pending_and_unknown_status_remain_executable` and `keeps pending and unknown statuses executable`. Assert open for `CANCEL_PENDING`, `CANCEL_REQUESTED`, `CANCEL PENDING`, `PENDING_CANCEL`, `REJECT_PENDING`, `COMPLETE_PENDING`, `NOT_CANCELLED`, `""`, whitespace and an unfamiliar value; assert closed only for the existing exact terminal set `COMPLETE`, `COMPLETED`, `FILLED`, `CANCELLED`, `CANCELED`, `REJECTED`, `TRADED`, `EXPIRED`. Trim/case normalisation is allowed; substring inference is not.
- [ ] Run the focused commands below; the substring cases must fail before the fix.
- [ ] Replace substring fallbacks with conservative `True`/`true`. Keep exact terminal mappings and all existing signatures. Do not treat trigger-resource terminality as execution-child terminality.
- [ ] Repeat both commands; all tests must pass. A SELL cancel-pending row must keep a long position's exit-pending tag; the BUY/short case must also pass.
- [ ] Commit only these four files: `fix(orders): retain pending and unknown execution risk`.

```text
python scripts/ft.py test-fast packages/services/engine/tests/test_reduce_only.py --workers 0
pnpm --filter @flinttrade/terminal exec vitest run src/widgets/trading/Positions/positionReconcile.test.ts
```

## Task 2: Fail closed on insufficient quantity evidence

**Files:** modify `E/src/flinttrade_engine/reduce_only.py`; extend `E/tests/test_reduce_only.py`. Do not change the process-local reservation implementation.

**Interfaces:** retain `classify_reduce_only(*, symbol: str, exchange: str, product: str, action: str, quantity: int, positions: Sequence[Mapping[str, object]], our_orders: Sequence[Mapping[str, object]], broker_orders: Sequence[Mapping[str, object]] | None, live: bool, extra_pending: int = 0) -> ReduceOnlyDecision`. Preserve the four existing result fields. An unreadable or ambiguous input returns `qualifies=False, cap=0`; known exposure/pending totals may be retained only when valid.

- [ ] Replace the current unreadable-book assertions in `test_live_broker_open_exit_reduces_the_cap_and_an_unreadable_book_stays_capped`: `broker_orders=None` in Live must refuse both with and without local pending exits. Add `test_partial_fill_is_not_subtracted_from_position_twice`: position 60 after a 40 fill, terminal original order and no other exits gives cap 60; a separate exit with 20 remaining gives cap 40; cancel-pending 20 still gives cap 40.
- [ ] Add `test_ambiguous_quantity_evidence_refuses`: matching potentially executable rows with missing/negative/non-finite/fractional quantities, filled greater than total, conflicting total/filled aliases, conflicting copies of one ID, or ambiguous matching position rows yield `qualifies=False, cap=0`. Identical local/broker copies of a stable ID count once. Give existing valid pending-order fixtures stable IDs; retain separate missing-ID refusal cases rather than weakening the check. Missing identity on a potentially executable matching row is ambiguity, not proof of uniqueness. Valid terminal-order historical fills remain preserved; they are not subtracted again from current position.
- [ ] Run the Task 2 command below and record the expected failing assertions.
- [ ] Add private validation `_quantity_evidence_is_valid(positions: Sequence[Mapping[str, object]], orders: Sequence[Mapping[str, object]], *, symbol: str, exchange: str, product: str, exit_action: str) -> bool` in `reduce_only.py`; validate matching evidence before cap calculation. Use existing whole-number aliases without silently converting malformed values to zero. Require `extra_pending` to be a non-negative integer (not a boolean); refuse invalid values. Refuse unreadable Live books before local-only qualification. Preserve Practice support and the public signatures. Update docstrings that currently promise an unreadable-book fallback.
- [ ] Repeat the command; all cases must pass. Existing whole-contract quantity semantics are unchanged; broker-specific units belong in Stage C.
- [ ] Commit the two explicit files: `fix(orders): refuse ambiguous exit quantity evidence`.

```text
python scripts/ft.py test-fast packages/services/engine/tests/test_reduce_only.py --workers 0
```

**Limit:** These legacy function arguments do not establish account-wide cross-book coherence, trigger visibility, authorised-intent quantity or reservation transfer. Task 2 must not claim to solve them or certify a safe replacement. Task 4 defines those requirements independently; Stage D is required to supply them.

## Task 3: Make the existing UI truthful without enabling writes

**Files:** modify `T/widgets/trading/Positions/PositionsWidget.tsx`, `T/widgets/trading/Positions/positionReconcile.ts`, `T/widgets/orders/ForeverOrdersWidget.tsx`; extend their existing `positionReconcile.test.ts`, `Positions/__tests__/PositionsWidget.test.tsx`, `Positions/__tests__/PositionsWidget.queryStates.integration.test.tsx`, and `orders/ForeverOrdersWidget.test.tsx`.

**Interfaces:** preserve existing `SquareOffDialog`, `ExitAllDialog` and ForeverOrders mutation calls. `exitOrdersUnreadableMessage(contract: string): string` and Python `exit_orders_unreadable_message(contract: str) -> str` receive matching truthful copy: `Not placed. Broker orders for {label} are unavailable. Reconcile them before another exit.` The backend copy change belongs to this commit, with `E/tests/test_reduce_only.py` coverage.

- [ ] Add tests `does not describe acknowledgement as a filled exit`, `keeps unavailable orders distinct from empty orders`, `keeps cancel-pending rows visible`, and `does not carry another account's warning or response into the active account`. Assert that successful submission alone never says `CLOSED`, `filled` or `Every open position was squared off`; loading/error/unsupported books never become an empty verified book. Keep a persistent visible book-unavailable warning while evidence is unavailable. Existing native-write guards remain effective.
- [ ] Add ForeverOrders tests that returned non-equity rows remain visible, cancellation ACK alone does not remove a row, and an unfamiliar trigger status cannot imply its spawned order is terminal. Display the spec's offline-GTT warning on the existing native GTT surface; do not infer external provenance merely from absence of local linkage.
- [ ] Run the focused commands below; capture failures before changing presentation.
- [ ] Update the components to use submission wording and the actual query loading/error state. Change the exit-all ACK body to `Exit-all requested. Check positions and orders for the outcome.` Display the exact warning `This prioritises execution. The fill price may differ significantly, and execution isn't guaranteed.` in close confirmation. Use `Cancel pending. This order may still fill.` when that state is known; do not relabel all transport failures as definite rejections. Retain broker refusal details and relevant DDPI warnings.
- [ ] Run the focused commands again and require PASS. Preserve the existing Dhan/Upstox selection restriction until capability integration is ready; describe it as implemented availability, not a claim that other brokers lack native APIs.
- [ ] Commit the explicit Task 3 files: `fix(terminal): distinguish order requests from execution outcomes`.

```text
pnpm --filter @flinttrade/terminal exec vitest run src/widgets/trading/Positions/positionReconcile.test.ts src/widgets/trading/Positions/__tests__/PositionsWidget.test.tsx src/widgets/trading/Positions/__tests__/PositionsWidget.queryStates.integration.test.tsx src/widgets/orders/ForeverOrdersWidget.test.tsx
python scripts/ft.py test-fast packages/services/engine/tests/test_reduce_only.py --workers 0
```

**Limit:** Query warnings and existing notifications are not a durable attempt ledger. Persistent intent-specific hazards across refresh, duplicate-attempt prevention, and confirmed `Stop failed`/`CLOSED` projections require Stage D. Do not add a browser-local trading authority or claim these requirements complete in Stage A.

## Task 4: Define pure reconciliation and recovery decisions

**Create:** `E/src/flinttrade_engine/exit_evidence.py`, `E/tests/test_exit_evidence.py`. No existing provider/router imports or registration.

**Interfaces:** immutable Python dataclasses; quantities are `Decimal` in explicit broker units, never floats.
- `ExitScope(mode: str, broker: str, account_id: str, instrument_id: str, expiry: str, segment: str, product: str)`.
- `ExitAttempt(attempt_id: str, broker_order_id: str | None, state: str, remaining: Decimal, reservation_id: str | None, parent_resource_id: str | None)`.
- `ProtectionLeg(leg_id: str, state: str, remaining: Decimal, child_ids: tuple[str, ...], children_complete: bool)`; each independently executable armed OCO/conditional leg has a stable identity and its own quantity.
- `ProtectionResource(resource_id: str, legs: tuple[ProtectionLeg, ...])`; leg states are `ARMED`, `TRIGGERED`, `CANCEL_PENDING`, `CANCELLED`, `REJECTED`, `EXPIRED`, `UNKNOWN`, separate from attempt states. Never represent multiple armed legs with one unproven aggregate quantity.
- `ExitEvidence(scope: ExitScope, original_sign: int, current_signed_quantity: Decimal, authorised_remaining: Decimal, attempts: tuple[ExitAttempt, ...], protection_resources: tuple[ProtectionResource, ...], unmatched_reservations: tuple[tuple[str, Decimal], ...], books_complete: bool, coherence_verified: bool, freshness_verified: bool, scope_verified: bool)`.
- `ExitDecision(cap: Decimal, outcome: str, next_action: str, reason: str)`; outcomes `OPEN`, `UNKNOWN`, `FAILED`, `CLOSED`; actions `WAIT`, `RECONCILE`, `CANCEL_THEN_RECONCILE`, `SUBMIT_MARKET`, `REQUEST_ALTERNATIVE`, `NONE`.
- `decide_exit(evidence: ExitEvidence, *, explicit_close: bool, protection_authorised: bool, market_supported: bool, preconditions_changed: bool) -> ExitDecision`. This returns advice only and performs no I/O.

- [ ] Add `test_closed_requires_flat_and_no_executable_or_unknown_attempt`, `test_unknown_never_replays`, `test_cancel_ack_never_releases_quantity`, `test_reservation_transfer_counts_once`, `test_oco_children_remain_independently_executable`, `test_external_reversal_does_not_authorise_new_direction`, and `test_failed_stop_needs_authorised_policy`. Pin cap 60 then 40 from the spec; duplicate conflicting IDs, mismatched scope, missing books, stale evidence and unverified coherence return cap zero and `RECONCILE`.
- [ ] Add `test_recovery_waits_for_definite_failure_and_changed_preconditions`: only a definitively failed/terminal attempt, fresh coherent eligible remainder and continued explicit-close/protection authorisation may yield `SUBMIT_MARKET`. Unsupported market yields `REQUEST_ALTERNATIVE`; unchanged rejection yields no new attempt. `UNKNOWN`, `SUBMITTING`, modify/cancel pending and working states never become a resubmission opportunity. Timestamps alone cannot set coherence. A coherent flat snapshot with any armed resource, unresolved child or unmatched reservation remains hazardous and is not `CLOSED`. Conflicting snapshot evidence requires reconciliation. This snapshot-only function cannot validate event ordering or cumulative-fill monotonicity; event reduction and late/duplicate-event replay tests belong to Stage D, not this task.
- [ ] Run `python scripts/ft.py test-fast packages/services/engine/tests/test_exit_evidence.py --workers 0`; expect missing-module failure initially.
- [ ] Implement the dataclasses and pure decision function. Use full spec attempt states; unknown strings are `UNKNOWN`. Validate `original_sign` as -1 or 1; retain it across flat/reversed snapshots. Scope owns all identities. Calculate cap as `min(authorised_remaining, max(0, P - W))`, where P is eligible current exposure in the original direction and W is unique executable remainder plus unmatched reservations. Deduplicate identical broker identities, transfer matched reservations once, count unresolved OCO legs separately, and require all attempts terminal before `CLOSED`. Count each armed or cancellation-pending leg as independently executable risk, including both OCO legs unless a validated atomic broker contract supplies stronger semantics. Pin a position of 100 with two armed legs of 40 to cap 20. Transfer each triggered leg quantity to its known children only when that leg's child set is complete; otherwise reconcile with zero cap. Duplicate/conflicting leg identities require reconciliation. A terminal trigger is not a terminal child. Reject negative/non-finite quantities and conflicting duplicate evidence. Do not implement idempotency from correlation tags or decide coherence inside this function.
- [ ] Repeat the command; all deterministic cases pass. Commit the two files: `feat(orders): define pure exit evidence decisions`.

The input booleans are an explicit trust boundary, not a new way to assert readiness. No production caller may supply them until the separately validated Stage D evidence source exists. Durable event ingestion and authoritative freshness remain unresolved integration requirements.

## Task 5: Establish a versioned native-feature inventory

**Create:** `G/src/flinttrade_gateway/order_feature_contract.py`, `G/tests/test_order_feature_contract.py`, `docs/acceptance/FT-GTT-001-capabilities.json`.

**Interfaces:** `OrderFeatureRecord` is a frozen dataclass with fields `schema_version: int`, `broker: str`, `api_version: str`, `checked_on: str`, `family: str`, `operation: str`, `product: str`, `segment: str`, `documented: str`, `implemented: str`, `readiness: str`, `supported_fields: tuple[str, ...]`, `quantity_unit: str`, `limitations: tuple[str, ...]`, `sources: tuple[str, ...]`. `validate_feature_records(records: Sequence[OrderFeatureRecord]) -> None` raises `ValueError` on invalid records. Schema version is 1. Support values are `yes/no/unknown`; readiness is `unverified/blocked/verified` and begins `unverified` or `blocked`, never inferred from `documented=yes`.

- [ ] Add tests `test_support_does_not_imply_readiness`, `test_native_gtt_does_not_require_native_reduce_only`, `test_records_are_unique_by_broker_version_family_operation_product_segment`, and `test_all_six_brokers_have_explicit_unknowns`. Pin INDmoney ignored trailing-stop and market-to-limit limitations, Kotak legacy CO/BO removal, and Delta native reduce-only as distinct facts. Unknown eligibility/units remain explicit; no wildcard grants eligibility.
- [ ] Run `python scripts/ft.py test-fast packages/integrations/gateway/tests/test_order_feature_contract.py --workers 0`; expect missing-module failure.
- [ ] Implement the validator and evidence-backed inventory from the spec's official links, checking versions against `brokers.lock` without changing dependencies. Each record separates API support, implemented mapping and runtime readiness. Preserve requested/effective field semantics in limitations; this inventory does not replace existing readiness gates or add routes.
- [ ] Repeat the command; require PASS. Commit the three explicit files: `feat(gateway): record versioned native order features`.

## Stage C: Six independently approved adapter implementation plans

After Tasks 4–5 settle, produce one short executable plan per row below; each must contain exact supported field/status mappings, resource identity and child relations, read/list coverage, product/session/quantity validation, per-item outcomes, and failing stub tests before code. Adapter files are integration targets, not permission to alter held lifecycle methods. Recheck current official docs and pinned SDK behaviour before finalising each plan.

1. **Dhan:** `B/dhan_mapping.py`, later `B/dhan.py`; existing tests `G/tests/brokers/test_dhan_mapping.py` and `test_dhan_adapter.py`. Preserve `to_forever_kwargs`, `to_modify_forever_kwargs`, `from_dhan_forever_order`, `to_super_order_kwargs`, `to_modify_super_order_kwargs`, `from_dhan_super_order`, `to_slice_order_kwargs` and normal-order mappings. Forever SINGLE/OCO, Super legs, trailing jump, AMO, slicing and product differences must survive round trips. No native reduce-only claim without evidence.
2. **Upstox:** `B/upstox_mapping.py`, later `B/upstox.py`; tests `G/tests/brokers/test_upstox_mapping.py` and `test_upstox_adapter.py`. Preserve `to_place_order_v3_params`, `to_multi_order_params`, `to_gtt_place_params`, `to_gtt_modify_params`, `from_upstox_gtt_order`, `from_upstox_multi_order` and `from_upstox_cancel_exit`. Pin entry/stop/target rule state, market-protection eligibility and per-child batch outcomes.
3. **Kotak Neo:** `B/kotakneo_mapping.py`, later `B/kotakneo.py`; tests `G/tests/brokers/test_kotakneo_mapping.py`, `test_kotakneo_adapter.py`, `test_kotakneo_sdk_contract.py`. Preserve `to_place_order_params`, `to_modify_order_params`, `from_kotak_order` and current supported product/validity semantics. Do not restore migrated-away CO/BO or invent a GTT endpoint; unresolved native GTT remains unknown.
4. **INDmoney:** `B/indmoney_mapping.py`, later `B/indmoney.py`; tests `G/tests/brokers/test_indmoney_mapping.py` and `test_indmoney_adapter.py`. Preserve `to_place_order_payload`, `to_smart_order_payload`, `to_smart_modify_payload`, `from_indmoney_order`; smart-order family/segment/cancel semantics need explicit fixtures. Requested trailing-stop fields must never imply active trailing protection when ignored. Expose market-to-limit conversion before confirmation and retain effective values.
5. **Groww:** `B/groww_mapping.py`, later `B/groww.py`; tests `G/tests/brokers/test_groww_mapping.py` and `G/tests/test_groww_adapter.py`. Preserve `to_place_order_payload`, `to_modify_payload`, `to_cancel_payload`, `from_order`. Add a separately specified smart GTT/OCO mapping unit after endpoint/schema verification; do not guess function signatures now. Pin resource-specific editable fields and all documented returned segments.
6. **Delta:** `B/delta_mapping.py`, later `B/delta.py`; existing test `G/tests/test_delta_adapter.py`; create `G/tests/brokers/test_delta_order_mapping.py` for independent mapping fixtures. Preserve `to_place_payload(order: Any, *, reduce_only: bool = False)`, `to_edit_payload`, `to_cancel_payload`, `from_order`, `from_position`. Preserve real native reduce-only, conditional/bracket families, product sizing and per-item batch/close errors. Do not apply Indian-equity lot assumptions to Delta contracts.

Each adapter plan runs its exact mapping test file with `python scripts/ft.py test-fast <path> --workers 0`. Adapter integration suites run only when their scope is authorised and does not exercise blocked paths. Mapping success never enables native HTTP or proves funded readiness.

## Stage D: Blocked integration and acceptance work

These spec requirements are deliberately unfinished; no placeholder implementation may be presented as their completion:
- Durable intent/attempt recovery, atomic reservation transfer, cross-process coordination, crash-after-write reconciliation and coherent complete book snapshots across positions, fills, normal orders and triggers/children. Define event identity, cumulative confirmed fills and monotonic reductions; test that late/duplicate terminal events never regress fills or resurrect completed attempts.
- Gated entry/modify/cancel/close/recovery routing; authorisation, funds/holdings, lot/tick/freeze, session/AMO and permission checks on every reachable normal, batch, nested, bracket/cover and native family route.
- Execution-first market recovery after definite failure; cancel → authoritative terminal evidence → final-fill reconciliation → eligible remainder. Unknown outcomes require identity/history reconciliation, not transport retries. Broker idempotency must be separately proved.
- Consume the capability inventory in `T/widgets/trading/OrderPad/OrderPadWidget.tsx`, `T/widgets/orders/ForeverOrdersWidget.tsx`, `T/lib/brokerOrdersApi.ts` and other proven reachable surfaces, preserving native fields and per-child results. Existing tests are OrderPad `__tests__/OrderPadWidget.test.tsx`, ForeverOrders tests and `T/lib/brokerOrdersApi.test.ts`.
- Persistent account-scoped hazards across navigation/refresh; sticky uncertainty/failure notifications; duplicate-click exclusion; `Stop failed`, `Unexpected` and `Unlinked` based on evidence; no recovery authorisation inferred from imported triggers; OCO sibling cancellation only when authorised.
- Restart, end-to-end and separately authorised live evidence. Until then, show availability/refusal honestly and retain current freezes.

After the blocked prerequisites are cleared, author a new integration plan against the then-current source. It must inventory every reachable route, name exact files/tests and include the existing `G/tests/test_no_legacy_order_path.py` guard. Do not guess or probe those integration paths in this phase.

## Verification and handoff

For each executable task: failing focused test → minimal implementation → passing focused test → explicit-file commit. Future execution should use the repository's `.venv`; no installation is authorised by this planning document. Before any PR, revalidate remote main and repeat affected checks. Never push merely because tests pass.

For Stage A UI verification, use a stub-only app session and the repository's Reticle flow/assertion guidance. Do not connect broker sessions. A blocked or unavailable UI verdict is recorded as unverified, not PASS. Documentation-only preparation skips Reticle because it changes no running surface.

Broader repository commands, when the relevant scope and environment permit them:
```text
python scripts/ft.py check --dry-run
python scripts/ft.py lint
pnpm --filter @flinttrade/terminal typecheck
pnpm --filter @flinttrade/terminal test
pnpm --filter @flinttrade/terminal build
python scripts/ft.py check --full
```

A broad command that would exercise excluded integration paths is not run under this scope. Record that verification gap and obtain the necessary clearance; never suppress checks to make a full-gate claim. Cross-platform and terminal acceptance require CI/contributor evidence, not one-machine inference.

**Review decision:** approve Stage A's exact scope first. Stages B/C can progress independently without clearing readiness gates; Stage D cannot. No implementation or publication is implied by this document's creation.
