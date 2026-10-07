# Kotak Neo Order Mappings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strengthen independently testable Kotak v3 order translations and evidence without enabling broker execution.

**Architecture:** Preserve existing mapping signatures and raw broker fields; add conservative evidence metadata rather than replacing consumer-facing statuses. Mapping outputs remain transport arguments or observations, never authority to place/retry orders.

**Tech Stack:** Python 3.12, pytest, Decimal; existing dependencies.

**Spec:** `FT-GTT-001-revised.md`; `docs/superpowers/plans/2026-10-06-full-order-flow.md`, Stage C. Source baseline: `ad059991d7164c934676808f54550659051ed9d5`.

## Global Constraints

- “ACK, HTTP success and an order ID establish neither a fill nor a closed position.”
- “Missing native reduce-only does not inherently disable native GTT.”
- “Unknown capability is not proof of support.”
- No dependency upgrades, broker sessions, release actions or runtime enablement.
- Existing supported mapping functions and historical read coverage remain available.

## Evidence and scope

Checked 2026-10-06: [migration](https://github.com/Kotak-Neo/kotak-neo-python/blob/main/docs/guides/MIGRATION.md), [placement](https://github.com/Kotak-Neo/kotak-neo-python/blob/main/docs/functions/orders/place_order.md), [modify](https://raw.githubusercontent.com/Kotak-Neo/kotak-neo-python/main/docs/functions/orders/modify_order.md), [order report](https://raw.githubusercontent.com/Kotak-Neo/kotak-neo-python/main/docs/functions/orders/order_report.md).

`brokers.lock` identifies runtime `kotakneoapi==3.0.8`, commit `9a37488d77dc96442ee2a90ef78462e688cf4856`; release `3.0.7` is separate evidence. The pinned migration URL was unavailable during initial planning; it was retrieved on 2026-10-07 alongside pinned placement documentation. Those documents match current public documentation, but this establishes only the inspected parameter contract, not installed-SDK or full-surface parity. Current documentation and existing mapping fixtures establish the proposed contract, not complete pinned-SDK parity. Later main `e658b50ab6753d63e64df250dfefabb91cc4630d` has runtime drift; the mapping basis is unchanged, but integration correspondence is unassessed. Do not change the pin or certify parity here.

Current v3 removes CO/BO, their leg parameters, GTC/GTD/EOS and spread/2L/3L. The legacy canonical mapper still accepts only MIS/CNC/NRML. The standalone public-v3 parameter companion also preserves MTF, documented by [placement](https://github.com/Kotak-Neo/kotak-neo-python/blob/9a37488d77dc96442ee2a90ef78462e688cf4856/docs/functions/orders/place_order.md) and [migration](https://github.com/Kotak-Neo/kotak-neo-python/blob/9a37488d77dc96442ee2a90ef78462e688cf4856/docs/guides/MIGRATION.md) at the pinned commit. Keep the legacy gap separate; neither mapping establishes MTF account/instrument eligibility or runtime readiness. Native GTT and bulk execution are unestablished. Historical CO/BO/MTF reads must remain visible with `broker_product`; no new GTT endpoint or synthetic substitute.

## File map

- Modify `packages/integrations/gateway/src/flinttrade_gateway/brokers/kotakneo_mapping.py` (M below).
- Create `packages/integrations/gateway/tests/brokers/test_kotakneo_order_contract.py` (T below): independent mapping fixtures, no adapter imports.
- Existing `test_kotakneo_mapping.py` supplies regression examples; `test_kotakneo_adapter.py` and `test_kotakneo_sdk_contract.py` are later integration evidence, outside these commands.
- Read-only dependencies: `order_feature_contract.py`, `exit_evidence.py`, `docs/acceptance/FT-GTT-001-capabilities.json`; no production registration or inventory-readiness promotion.

## Review Focus

1. Unsupported product/validity or conflicting modification aliases: Task 1 refuses rather than silently translating.
2. Missing/conflicting quantities and malformed IDs: Task 2 preserves uncertainty.
3. Cancellation substrings and partial fills: Task 2 never manufactures terminal evidence.
4. Malformed history versus genuinely empty history: Task 2 distinguishes failure.
5. Error envelopes containing IDs and successful acknowledgements: Task 3 cannot imply execution.

## Task 1: Preserve the exact v3 wire contract

**Files:** M, T. **Interfaces:** preserve `to_place_order_params(order: Any, trading_symbol: str, *, tag: str | None = None) -> dict[str, Any]` and `to_modify_order_params(order_id: str, changes: dict[str, Any]) -> dict[str, Any]`.

- [ ] Add `test_v3_wire_contract_and_conflicting_aliases`. Assert MARKET/LIMIT/SL/SL-M → MKT/L/SL/SL-M; BUY/SELL → B/S; NSE/BSE/NFO/BFO/MCX → nse_cm/bse_cm/nse_fo/bse_fo/mcx_fo. Assert finite string-valued numerics, positive integral quantity, positive LIMIT/SL price and stop trigger, DAY/IOC, MCX DAY-only, `amo=YES/NO`, optional canonical `tag`.
- [ ] Assert the complete modify key set is `order_id,order_type,price,quantity,validity,trigger_price,disclosed_quantity`, plus `amo` only when supplied. Signed context fields are validated but never forwarded. Conflicting `pricetype`/`order_type` must raise `KotakNeoMappingError`; equivalent LIMIT/L aliases agree. Reject disclosed quantity exceeding total. Keep removed quick/leg fields rejected and retain current conservative MCX-modify restriction.
- [ ] Run command below: new conflict/disclosure assertions must FAIL; existing cases may already pass.
- [ ] Add minimal conflict/disclosure validation in M; preserve supported signatures, number bounds and existing defaults. Do not infer instrument tick/lot/freeze limits or account eligibility.
- [ ] Repeat command; require PASS. Stage M and T explicitly; commit `fix(kotak): validate v3 order mapping conflicts`.

## Task 2: Preserve trustworthy read identities and states

**Files:** M, T. **Interfaces:** preserve `from_kotak_order(d: dict[str, Any]) -> dict[str, Any]`, `from_kotak_trade(d: dict[str, Any]) -> dict[str, Any]`, `order_history_rows(resp: Any) -> list[dict[str, Any]]`; add `kotak_attempt_state(status: object) -> str`.

- [ ] Add `test_read_identity_quantity_and_status_evidence`: map `nOrdNo` to canonical `orderid`, `qty/fldQty` to total/filled, `prc/trgPrc/avgPrc` to price/trigger/average; preserve `exOrdId`/`exchOrdId`, `rejRsn`, `GuiOrdId`, timestamp and validity aliases. Missing optional numbers stay absent. Reject negative/fractional quantity, filled greater than total, conflicting populated aliases and whitespace IDs with `BrokerReadResponseInvalid`.
- [ ] Add `test_exact_states_keep_partial_fills`: helper normalises case/whitespace; exact complete/traded → FILLED, cancelled → CANCELLED, rejected → REJECTED, open → WORKING; explicit CANCEL_PENDING/CANCEL_REQUESTED → CANCEL_PENDING. Everything else, including blank, NOT_CANCELLED and COMPLETE_PENDING, → UNKNOWN. Add `attempt_state` without altering raw `status`; a cancelled row with total 100/filled 40 retains 40.
- [ ] Add `test_history_errors_are_not_empty`: valid nested/direct empty data lists yield `[]`; malformed/error envelopes or non-object rows raise `BrokerReadResponseInvalid`. Preserve all valid historical segments/products. Whole-book trades retain `nOrdNo`; no per-order endpoint or fill deduplication by order ID is invented.
- [ ] Run command: expect FAIL; implement only these pure checks; rerun to PASS. Commit M/T as `fix(kotak): retain conservative order read evidence`.

## Task 3: Pin acknowledgement and error boundaries

**Files:** T; M only if a fixture exposes a gap. **Interfaces:** preserve `ensure_ok(resp: Any) -> Any` and `require_write_success(resp: Any, *, expected_order_id: str | None = None) -> dict[str, Any]`.

- [ ] Add `test_ack_is_not_fill_and_error_id_is_not_success`: accepted `stat=Ok,stCode=200,nOrdNo` remains an ACK; reject wrong IDs, boolean status codes, `Error`, `Error Message`, `error`, Not_Ok, and completed-order `stCode=1021,status_code=400`. Preserve broker reason. Never classify timeout/502/503/504 as definite non-execution or prescribe replay.
- [ ] Run command; record genuine failures before any implementation. If fixtures pass already, make no artificial code change. Preserve read-envelope versus write-ACK distinctions. Rerun; require PASS. Commit explicit changed files as `test(kotak): pin order acknowledgement boundaries`.

## Isolated red/green verification

Inherit every startup, import, collection, sentinel and result requirement in [offline verification](offline-mapping-verification.md), applied to this broker's M/T files. Prepare executor-local `/tmp/ft_mapping_verify.py`, `/tmp/kotakneo-imports.json` and `/tmp/ft-mapping-check/network-denied`; none is supplied by this plan. The wrapper must establish OS-enforced network denial before launching Python, refusing if unavailable.

The manifest pins real source hashes and audited installed pytest/dependency paths. Use `-I -S`; load audited dependencies without site or `.pth` processing. The runner itself disables pytest plugin autoload/configuration, regardless of environment flags, file-loads real allowlisted modules under inert namespaces and rejects unlisted imports. Unresolved transitive dependencies block execution; no substitute runtime authority. Kotak's `kotakneo_sdk` closure remains a prerequisite.

```text
/tmp/ft-mapping-check/network-denied .venv/bin/python -I -S /tmp/ft_mapping_verify.py --manifest /tmp/kotakneo-imports.json --mapping packages/integrations/gateway/src/flinttrade_gateway/brokers/kotakneo_mapping.py --test packages/integrations/gateway/tests/brokers/test_kotakneo_order_contract.py --no-conftest --deny-network
```

Run before/after each task: assertion failure → PASS; import/isolation failures are blockers, not red-test evidence. Standard `python scripts/ft.py test-fast`/package pytest commands remain unrun pending integration verification. No tests ran during planning. Complete books, durable recovery, dispatch, UI disclosure and funded acceptance remain separate unvalidated prerequisites; mapping success cannot enable writes.
