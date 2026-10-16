# Structural accessibility regression lane

`structural-accessibility.spec.ts` registers eight maintained native cases: keyboard,
selection, drag and channel propagation plus three structural Axe rules, each at
1440×900 and 2560×1440. `accessibility-overflow.spec.ts` adds eight native regressions:
the keyboard context menu, inline editor slot/overflow, dock clipping/focus,
single-tab editing semantics, and Enter/Space completion of Duplicate/Delete.
Each completed tab action must focus the committed duplicate or surviving selected
tab, retaining selection, persisted symbols and native paint/hit geometry.

`observed-registry.ts` layers request/response bodies, close ledgers, console,
DOM/accessibility snapshots and native text-range geometry on the existing
fail-closed registry. It awaits that registry's idempotent disposal and all body
reads; it does not introduce a verifier dependency. Both specs and their helpers
are explicitly checked by `e2e:infra:typecheck`, `e2e:infra:lint`, and the maintained
registration contract.

These are ordinary default-lane Chromium/Vite tests. They need the repository's
pinned browser/dependencies and the existing fail-closed synthetic API registry;
they require no Reticle daemon, witness, external module or operator path. Run them
inside the authorised disposable runtime, with one worker, zero retries, blocked
service workers and the existing strict port/no-egress constraints. The aggregate
acceptance carrier still owns reconciliation of the complete default inventory.

`structural-accessibility.ts` shares registration without registering tests merely
by being imported. Its optional lifecycle hooks allow a separately configured
instrumented diagnostic lane to reuse the same eight cases. No such diagnostic
spec or external witness is shipped by this patch or discovered by default. Any
private instrumented run must declare its own eight-identity mapping, qualified
client/witness/presenter/runtime hashes, case-owned HELLO session, original and
fresh native verdicts, and accepted complete captures. It is not a replacement
for native Axe, paint, geometry or hit-testing.

Existing tests, screenshot/focus baselines, masks, tolerances and budgets remain
unchanged. Raw full-page Axe output is retained even when a case targets one
structural rule. The native acceptance report must also verify that all six
complete default-page analyses have no violations.
