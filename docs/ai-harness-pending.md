# AI harness unfinished-work checkpoint — 11 September 2026

The maintainer stopped the integrated build and requested a closeout: merge
finished work, preserve unfinished work, and end this goal. This is **not** a
claim that the complete autonomous trading harness has been built.

## Recovery references

- Finished integration base: `1ae225d05` on `codex/native-ai-context`, including
  upstream `main` through `820ab6906` via merge `fd5f09043`.
- Unfinished source and tests: `codex/ai-harness-pending-20260911`, based on that
  finished commit. Do not merge this branch wholesale: it includes known
  failing and incomplete implementations.
- The older recovery stash `c173ff700574293ca0a67e72f5caa4666bb2f0e4` is retained;
  this branch is newer and is the source checkpoint to resume.
- The existing worktree and ignored design/evidence files are retained. The
  private plan is `.local/agent-context/PLAN.md` in the main checkout; detailed
  task reports are under `.superpowers/sdd/2026-09-10-integrated-build-plan/`
  in the development worktree. Those local files are not part of a clone.

## Finished components

The finished branch contains configured-broker AI input receipts, backend
ownership and live-lease proof propagation, durable usage-admission contracts,
forecast contracts and message validation, immutable memory and RAG influence
receipts, official Codex model/quota metadata, stable account-action retry IDs,
and a legacy-account TOTP upgrade repair. These components had bounded reviews
and focused tests. They do not complete account activation, paid transport
wiring, overnight research, or strategy qualification/promotion.

## Preserved unfinished units

| Unit | Source and state | Last recorded evidence / next blocker |
| --- | --- | --- |
| Account authority (3b / 9A.2) | `account_mutation_contracts`, `account_mutation_locks`, `account_mutation_principals`, `account_mutation_journal`, `account_mutation_flows`, gateway protocol and backup exclusions | 146 focused tests passed. Storage primitives only; exhaustive recovery, reconciliation, concrete coordinator, registry rebind, provider flows and atomic activation remain. Not independently approved. |
| Operator evidence companion | `operator_session.py`, compatibility import in `auth_routes.py`, tests and inert service fixture | Extraction retains the existing verifier semantics. Combined operator/service/migration-input run passed 115 tests; keep with account integration for review. |
| Router mutation lease (3c / 9B.1) | `router_mutation_lease.py`, app/native-account/rate-limit rebuild paths and tests | Expanded run: 524 passed, 22 failed. Nineteen shutdown failures are a real regression: already-owned cleanup incorrectly requires live proof. Retirement-only lease and RED test are partial, unwired and unverified. Three emergency-dispatcher `AttributeError` failures need diagnosis. |
| OpenAlgo migration (3d / 9B.2) | `broker_setup.py`, `openalgo_migration.py`, gateway normaliser compatibility and input tests | 27 input tests passed; helpers are inert. Six new recovery tests remain RED because `openalgo_migration_recovery` does not exist. No source-consumption ledger, retirement or runtime activation has been implemented. |
| Forecast transport draft | `forecast_http.py` and its tests | Earlier 12 synthetic HTTP tests passed. No independent review, runtime/usage integration, worker activation or TimesFM-specific distribution. |

The authority/migration handoff must resolve public authenticated manifest and
completed-step reads, inert candidate staging, encrypted prior-snapshot
recovery, and source-family-to-operation allocation. Ordinary manifests remain
workspace → vault → projection; only the sealed exact-default OpenAlgo
migration permits vault → workspace → projection. Do not loosen either gate.

## Ordered remaining build scope

1. Complete and review account authority and router retirement/mutation leases.
   Then finish migration/recovery, atomic OpenAlgo activation, the concrete
   coordinator, all account/auth/rotation writers, and backup authority.
2. Finish exact-account role selection, data/recording/balances/Practice flows
   and the operator UI. Fresh-install native setup remains guarded until its
   coherent cutover is ready.
3. Wire every LLM/embedding/probe/retry/fallback/stream attempt through managed
   service policy and durable usage admission; finish subscription and budget
   UI, data/news services and catalogue status accuracy.
4. Integrate forecast workers, result/usage ledgers, runtime, rights and licence
   lineage. A consumer subscription is not API credit; model weights and live
   evidence permissions must remain explicit.
5. Finish the decision gateway and persistent RAG workflow, then the isolated,
   credential-free overnight experiment controller.
6. Implement immutable strategy releases, backtest/walk-forward qualification,
   unchanged prospective Practice sessions, mandates and capital canaries.
7. Finish integrated UI/E2E verification, whole-tree tests and independent
   audits before any integrated release or completion claim.

Real broker connections, complete live-data Practice market sessions and funded
order smoke remain separate maintainer-controlled checks. No such calls were
made for this checkpoint. Also retain the minor TOTP test-flake follow-up:
replace the fixed wrong code with a deterministically invalid code.

## Resume without restarting

Inspect current `main` and this checkpoint's diff against `1ae225d05`; read the
private plan and task 3b/3c/3d reports before editing. Apply coherent units to a
new integration branch, preserving red tests with their pending implementation.
Do not cherry-pick the entire WIP commit into `main` or bypass account/live-order
guards. Keep `gate_order` / `gate_broker_write` → `BrokerRouter` mandatory, and
rerun `gateway/tests/test_no_legacy_order_path.py` after order-adjacent changes.
No future implementation, remote push, provider invocation or release is
authorised merely by this handoff; the maintainer has closed this work wave.
