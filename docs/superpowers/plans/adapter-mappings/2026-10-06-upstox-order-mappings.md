# Upstox Order Mappings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve Upstox native order parameters, GTT rule evidence and batch outcomes in isolated pure mappings.

**Architecture:** Extend pure dictionary builders compatibly; separate resource/rule observations from exchange-order evidence. Runtime integration remains outside scope.

**Tech Stack:** Python 3.12, pytest; existing dependencies, upstox-python-sdk 2.30.0 from `brokers.lock`.

**Spec:** `docs/acceptance/FT-GTT-001.md`; `docs/superpowers/plans/2026-10-06-full-order-flow.md`, Stage C. Reviewed mapping baseline: `ad059991d7164c934676808f54550659051ed9d5`.

Main: `e658b50ab6753d63e64df250dfefabb91cc4630d`; filename-only comparison shows unchanged mapping/tests. Runtime drift unassessed.

## Global Constraints

- “Unknown capability is not proof of support.”
- “Batch/sliced orders have per-child outcomes; partial success is not an atomic all-or-nothing result.”
- “A terminal trigger does not prove that its spawned exchange order is terminal.”
- No added FlintTrade close slippage cap, account sessions, dependency changes or readiness promotion.
- Release publication, tags and release-PR merges require specific owner approval; none belong here.

## Review Focus

1. Explicit protection values disappearing during translation: Task 1.
2. Trigger completion or envelope success masquerading as fills: Task 2.
3. Missing rule messages hiding the broker rejection: Task 2.
4. Slices sharing correlation IDs mistaken for duplicate orders: Task 3.
5. Invalid quantities/counts silently truncated or omitted: Tasks 1–3.

## Files and grounded gaps

M = `packages/integrations/gateway/src/flinttrade_gateway/brokers/upstox_mapping.py`.
Create T = `packages/integrations/gateway/tests/brokers/test_upstox_order_contract_mapping.py`.
Modify only M; use literal/SimpleNamespace fixtures in T, without production Order imports.

Already supported: V3 slicing, DAY/IOC, requested AMO, positional multi-order correlations, ENTRY/TARGET/STOPLOSS construction, trigger overrides, STOPLOSS trailing gap, complete GTT modification, D-product segment disambiguation and strict cancel/exit envelope validation. Preserve those behaviours.

Inventory `docs/acceptance/FT-GTT-001-capabilities.json` records missing V3/rule protection. Further gaps: conflated `entry_status`, dropped messages, unconditional LIMIT, lossy quantities and batch filtering. Runtime remains unverified.

Official references rechecked 2026-10-06: [V3 placement](https://upstox.com/developer/api-documentation/v3/place-order/), [GTT placement](https://upstox.com/developer/api-documentation/place-gtt-order/), [GTT detail](https://upstox.com/developer/api-documentation/get-gtt-order-details/), [multi-order](https://upstox.com/developer/api-documentation/place-multi-order/). SDK compatibility remains unverified. Below are newly specified mapping interfaces, not existing Order fields or SDK constructors.

## Task 1: Forward explicit market protection without inventing eligibility

**Files:** M, T. **Interfaces:** extend `to_place_order_v3_params(order: Any, instrument_token: str, *, tag: str | None = None, market_protection: int | None = None) -> dict[str, Any]`; extend `to_multi_order_params(orders_with_tokens: list[tuple[Any, str]], *, tag: str | None = None, market_protection_by_index: dict[int, int] | None = None) -> list[dict[str, Any]]`. Indexes are zero-based.

Extend `to_gtt_place_params(order: Any, instrument_token: str, *, market_protection_by_strategy: dict[str, int] | None = None) -> dict[str, Any]`, `to_gtt_modify_params(gtt_order_id: str, changes: dict[str, Any], *, market_protection_by_strategy: dict[str, int] | None = None) -> dict[str, Any]`, and `_gtt_rules(order: Any, side: str = "BUY", *, market_protection_by_strategy: dict[str, int] | None = None) -> tuple[str, list[dict[str, Any]]]`.

- [ ] Add `test_market_protection_mapping_is_explicit`: None omits the field; exact integers -1, 0, 1 and 25 survive on V3, individual batch items and selected GTT rules. Boolean, fractional, -2 and 26 raise `UpstoxMappingError`. Reject invalid indexes, unknown strategies and values for absent rules.
- [ ] Assert LIMIT/SL requests retain the requested value without manufacturing an active-protection flag. Broker applicability is MARKET/SL-M; default automatic protection and zero rejection remain broker behaviour. Do not change order types or choose a protection percentage.
- [ ] Add `test_upstox_request_quantities_are_exact`: regular, sliced, multi and GTT creation reject Boolean, fractional, non-finite, negative and zero quantities; numeric integer strings remain accepted. Retain complete-replacement GTT checks and trailing-gap validation.
- [ ] Run T using the command below; expect failure. Implement minimal order-only numeric validation and field forwarding, preserving existing public call compatibility. Do not add these kwargs to SDK calls here.
- [ ] Rerun T, expect PASS; explicitly stage M/T and commit `feat: preserve Upstox market protection mappings`.

## Task 2: Preserve independent GTT rule state

**Files:** M, T. **Interface:** retain `from_upstox_gtt_order(d: dict[str, Any]) -> dict[str, Any]`.

- [ ] Add `test_gtt_entry_status_is_independent`: fixture top-level status differs from ENTRY; output `entry_status` always comes from ENTRY, while existing `status` preserves supplied resource status or falls back to ENTRY. Add `resource_status` only when observed. Envelope success must never enter this resource mapper as evidence of execution.
- [ ] Add `test_gtt_rules_preserve_broker_rejection`: retain each rule's `message`, strategy, raw status, trigger type/price, side, child `order_id`, optional trailing gap and observed market protection. Null child IDs remain empty; absent fills remain absent. Test duplicate ENTRY strategies raise `BrokerReadResponseInvalid` rather than last-write-wins flattening.
- [ ] Pin SCHEDULED, TRIGGERED, EXPIRED, OPEN, COMPLETED, CANCELLED, PENDING, FAILED, INACTIVE and unknown statuses unchanged in each rule. A COMPLETED ENTRY with PENDING STOPLOSS preserves both; neither creates FILLED/CLOSED. Test NSE_EQ, BSE_EQ and NSE_FO rows without filtering to a creation allow-list.
- [ ] Replace unconditional LIMIT readback: IMMEDIATE ENTRY retains LIMIT; otherwise `pricetype=""` until execution type is observed. Recreate the BELOW fixture in T; trigger price is not fill evidence.
- [ ] Run T, observe failures, implement only these readback changes, rerun to PASS; stage M/T and commit `fix: retain Upstox GTT rule evidence`.

## Task 3: Preserve every multi-order outcome

**Files:** M, T. **Interfaces:** retain `from_upstox_multi_order(resp: dict[str, Any]) -> dict[str, Any]`, `from_upstox_cancel_exit(resp: dict[str, Any]) -> dict[str, Any]` and Task 1's multi builder.

[Batch cancellation](https://upstox.com/developer/api-documentation/cancel-multi-order/) accepts tag/segment filters; unfiltered means all open orders, maximum ten. `data.order_ids` is response evidence, never a selected-ID cancellation request. No cancellation builder is introduced.

- [ ] Add `test_multi_input_limit`: accept ten input rows, reject eleven; retain slice/AMO/tag/correlation fields. Post-slicing count still needs instrument freeze evidence elsewhere.
- [ ] Add `test_multi_response_lossless`: preserve ordered successes, complete errors, `status`, and complete `summary`, including `payload_error`; maintain existing `order_ids`, `order_results`, `total`, `success` keys. Two distinct child IDs sharing correlation `"1"` both survive. Correlation IDs are request-local, never idempotency keys.
- [ ] Add `test_multi_malformed_evidence_rejected`: malformed rows, missing IDs, duplicate child IDs, non-list data/errors, invalid counts and success envelopes containing errors raise `UpstoxMappingError`; do not silently filter. Do not equate input-line totals with sliced-child counts.
- [ ] Run T, observe failures; implement narrow checks. Recreate cancel/exit strict-validation fixtures in T: IDs are acknowledgements, not flatness. Rerun to PASS; stage M/T and commit `fix: retain Upstox per-child batch outcomes`.

## Verification and integration prerequisites

First satisfy [offline runner prerequisites](offline-mapping-verification.md): reviewed real dependency allow-list, file loading, no production initialisers/conftests, network-disabled sandbox and sentinel checks. Every red/green step uses:

`.venv/bin/python -I -S /tmp/ft-mapping-check/run.py --root "$PWD" --broker upstox --tests packages/integrations/gateway/tests/brokers/test_upstox_order_contract_mapping.py --manifest /tmp/ft-mapping-check/imports.json`

Normal `ft.py test-fast` and existing suites remain unrun pending integration verification.

Planning executed no tests. GTT get excludes completed resources; absence cannot prove cancellation. Requested AMO does not establish effective session handling. Per-account permissions, temporary MCX restrictions, instrument quantity units, lot/tick/freeze, holdings/funds, rule eligibility and LTP-dependent trailing minima require later runtime evidence. Wiring new mapping inputs through models/UI/SDK, retaining all placement IDs, durable reconciliation and enablement are blocked technical prerequisites, not executable tasks here.
