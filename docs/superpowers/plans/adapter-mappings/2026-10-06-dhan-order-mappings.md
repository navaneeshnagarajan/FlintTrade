# Dhan Order Mappings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair independently demonstrable Dhan mapping gaps without claiming operational order-flow parity.

**Architecture:** Extend the existing pure mapping module and dictionary contracts. Preserve native resource identity, observed quantities and broker statuses; do not add dispatch or infer execution from acknowledgements.

**Tech Stack:** Python 3.12, pytest; existing dependencies, dhanhq 2.2.0 pinned by `brokers.lock`.

**Spec:** `docs/acceptance/FT-GTT-001.md`; parent plan `docs/superpowers/plans/2026-10-06-full-order-flow.md`, Stage C. Baseline: `ad059991d7164c934676808f54550659051ed9d5`.

Main advanced to `e658b50ab6753d63e64df250dfefabb91cc4630d`; filename-only comparison found no pure mapping/test changes. Runtime drift was not assessed.

## Global Constraints

- “Missing native reduce-only does not inherently disable native GTT.”
- “Unknown capability is not proof of support.”
- “ACK, HTTP success and an order ID establish neither a fill nor a closed position.”
- No runtime integration, dependency changes, broker sessions, release, tag or release-PR merge. Release actions require specific owner approval.
- Keep `docs/acceptance/FT-GTT-001-capabilities.json` readiness unchanged. Mapping coverage cannot establish account/product/session eligibility.

## Review Focus

1. Forever family codes masquerading as execution types: Task 1.
2. Broad list visibility incorrectly becoming placement permission: Task 1.
3. Omitted trailing values silently cancelling protection: Task 2.
4. Fractional, Boolean or non-finite quantities becoming executable integers: Task 3.
5. Parent completion hiding live children or missing fill evidence: Tasks 1–2.

## Files, evidence and existing coverage

Modify `packages/integrations/gateway/src/flinttrade_gateway/brokers/dhan_mapping.py` (M); create `packages/integrations/gateway/tests/brokers/test_dhan_order_contract_mapping.py` (T). Existing `test_dhan_mapping.py` imports `adapter.BROKER_CATALOG`; do not execute or mock that catalogue. T uses isolated literal/SimpleNamespace fixtures.

Already implemented: normal enum translation, DAY/IOC, AMO REST payload with all four pump windows, slicing request reuse, SINGLE/OCO all-or-nothing second-leg construction, complete Forever replacement, Super directional checks, native legs, contract identity and absent-fill preservation. Existing tests cover Forever leg restrictions, Super leg shapes and conditional triggers. Retain them; this is not a rewrite.

The capability inventory correctly leaves full implementation/readiness unknown. Concrete remaining gaps are Forever `orderType=SINGLE/OCO` readback, Super remaining quantities, destructive omitted trailing edits and permissive integer coercion. Legacy CO/BO remain distinct from Super; normal `PRODUCT_MAP` does not implement them. Conditional triggers and account-wide exit are separate families, not additional Forever modes.

Official pages rechecked 2026-10-06: [Forever](https://dhanhq.co/docs/v2/forever/), [Super](https://dhanhq.co/docs/v2/super-order/), [Orders](https://dhanhq.co/docs/v2/orders/). SDK pin is verified from `brokers.lock`; installed SDK source was unavailable. Retain the existing Super MARKET refusal and AMO REST workaround; exact SDK compatibility remains a later prerequisite.

## Task 1: Preserve Forever identity and constrain creation

**Files:** M, T. **Interfaces:** keep `to_forever_kwargs(order: Any, security_id: str, *, tag: str | None = None) -> dict[str, Any]`, `to_modify_forever_kwargs(order_id: str, changes: dict[str, Any]) -> dict[str, Any]`, and `from_dhan_forever_order(d: dict[str, Any]) -> dict[str, Any]`.

- [ ] Add `test_forever_native_family_readback`: `orderType="OCO"` produces `order_flag="OCO"`, `broker_order_type="OCO"`, `pricetype=""`; explicit `orderFlag="OCO", orderType="LIMIT"` retains LIMIT. Conflicting SINGLE/OCO indicators raise `BrokerReadResponseInvalid`.
- [ ] Add `test_forever_creation_product_scope`: CNC/MTF remain buildable; MIS/NRML raise `DhanMappingError`. Read fixtures for INTRADAY/MARGIN/CO/BO and NSE_FNO/MCX_COMM remain visible. Preserve original `broker_product` beside canonical MIS/NRML values; do not use creation restrictions to filter reads.
- [ ] Add `test_forever_creation_order_types`: a creation-only LIMIT/MARKET allow-list accepts both; SL/SL-M and their STOP_LOSS/STOP_LOSS_MARKET aliases raise `DhanMappingError`. Separate modification fixtures retain both stop types; historical readback remains unchanged.
- [ ] Add `test_forever_status_and_missing_evidence`: preserve exact CONFIRM, TRANSIT, PENDING, TRADED, CANCELLED, REJECTED, EXPIRED, blank and unfamiliar statuses. Never manufacture fills, execution-child IDs or reduce-only evidence. Retain `orderId`, observed `exchangeOrderId`, `legName`, both OCO quantities/prices/triggers and timestamps; absent validity stays absent rather than fabricated DAY.
- [ ] Run the focused command below; expect new assertions to fail.
- [ ] Implement these field-preservation, product and creation-type checks. Keep SDK `trigger_Price`/`trigger_Price1` spelling and existing complete-replacement requirements; read-side family aliases do not permit `ENTRY_LEG` modification.
- [ ] Rerun T, expect PASS; explicitly stage M/T and commit `fix: preserve Dhan Forever resource semantics`.

## Task 2: Make Super edits and observations lossless

**Files:** M, T. **Interfaces:** retain `to_modify_super_order_kwargs(order_id: str, changes: dict[str, Any]) -> dict[str, Any]` and `from_dhan_super_order(d: dict[str, Any]) -> dict[str, Any]`.

- [ ] Add `test_super_modify_requires_explicit_trailing_intent`: STOP_LOSS_LEG requires stop price and explicit trailing jump; omitted jump raises, zero intentionally disables, positive survives. ENTRY_LEG requires complete replacement; TARGET_LEG requires only target price. Recreate the stop-edit fixture in T with explicit zero.
- [ ] Add `test_super_read_preserves_remaining_and_children`: top-level `remainingQuantity=3` becomes `remaining_quantity="3"`; missing remains absent. Validate present nested `totalQuatity` (documented spelling), `remainingQuantity`, `triggeredQuantity`, `price`, `trailingJump` as finite primitives without rewriting raw leg keys. Invalid numeric evidence raises `BrokerReadResponseInvalid`.
- [ ] Include same-ID TARGET_LEG/STOP_LOSS_LEG fixtures, parent TRADED with child PENDING, and child CANCEL_PENDING. Preserve both legs and raw statuses; identity is resource plus leg, not bare order ID. No inferred terminality or flatness.
- [ ] Run T and observe failures. Implement minimal checks, retaining SDK kwargs shape and existing `leg_details_valid` semantics; do not reinterpret that structural flag as readiness.
- [ ] Rerun T, expect PASS; stage M/T and commit `fix: preserve Dhan Super leg intent and evidence`.

## Task 3: Reject lossy quantities without changing native requests

**Files:** M, T. **Interfaces:** retain normal/AMO/Super/slice/Forever builders and modify functions; add private `_order_quantity(value: Any, *, field: str, allow_zero: bool = False) -> int`.

- [ ] Add `test_dhan_order_quantities_are_exact`: parameterise applicable request quantities over `True`, `1.5`, `"NaN"`, infinity, negative and zero; reject with `DhanMappingError`. Accept `"10"`; disclosed quantities may be zero. Explicit partial/invalid OCO leg values must not silently downgrade to SINGLE.
- [ ] Add regression assertions preserving IOC, AMO windows, Super target/stop/trailing values and slice request equivalence. `to_modify_order_kwargs` must reject unsupported validity instead of replacing it with DAY.
- [ ] Run T, observe failure; replace order-only coercions, leaving market-data helpers untouched. Rerun T and expect PASS; stage M/T and commit `fix: validate Dhan mapping quantities exactly`.

## Verification and remaining prerequisites

Before any test, satisfy [offline runner prerequisites](offline-mapping-verification.md): reviewed real dependency allow-list, source-file loading, no production initialisers/conftests, network-disabled sandbox and sentinel verification. All red/green steps use:

`.venv/bin/python -I -S /tmp/ft-mapping-check/run.py --root "$PWD" --broker dhan --tests packages/integrations/gateway/tests/brokers/test_dhan_order_contract_mapping.py --manifest /tmp/ft-mapping-check/imports.json`

Normal `ft.py test-fast` and existing suites remain unrun pending integration verification.

No tests were executed during planning. Books remain separate: Forever `/forever/all`, daily Super `/super/orders`, ordinary orders and trades. The slice response/error contract still needs authoritative fixtures before adding a response interface; never reduce multiple child outcomes to the first ID. Cross-book completeness, sibling reconciliation, lot/tick/freeze conversion, funds/holdings, sessions, permissions, SDK invocation and runtime adapter enablement remain unvalidated technical prerequisites outside this plan.
