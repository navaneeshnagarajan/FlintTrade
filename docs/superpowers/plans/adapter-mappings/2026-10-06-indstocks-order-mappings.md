# INDstocks Order Mappings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct INDstocks mappings and expose execution limitations.

**Architecture:** Separate REST payloads from requested/effective metadata; preserve independent resource identities. Mapping success never establishes readiness.

**Tech Stack:** Python 3.12, pytest, Decimal; existing dependencies.

**Spec:** `FT-GTT-001-revised.md`; `docs/superpowers/plans/2026-10-06-full-order-flow.md`, Stage C. Reviewed source: `ad059991d7164c934676808f54550659051ed9d5`. Later main `e658b50ab6753d63e64df250dfefabb91cc4630d` changes runtime code; pure mappings are unchanged, integration correspondence unassessed.

## Global Constraints

- “If a broker ignores a protection field, it cannot appear active.”
- “If it converts a market request to a limit, disclose that execution behaviour.”
- “A terminal trigger does not prove that its spawned exchange order is terminal.”
- No SDK installation, broker activity, enablement or release.
- Preserve ordinary, AMO, smart placement/modification/cancellation and all returned segments.

## Evidence, files and gaps

Sources, 2026-10-06: [normal orders](https://api-docs.indstocks.com/normal_orders/), [smart orders](https://api-docs.indstocks.com/smart_orders/), [glossary](https://api-docs.indstocks.com/glossary/), [feed](https://api-docs.indstocks.com/Websockets/). `brokers.lock` records REST-only INDmoney without an installable SDK pin.

Modify `packages/integrations/gateway/src/flinttrade_gateway/brokers/indmoney_mapping.py` (M). Create `packages/integrations/gateway/tests/brokers/test_indmoney_order_contract.py` (T), importing only pure mappings/core exceptions and `SimpleNamespace`; exclude adapter-catalogue imports.

Read-only foundations are `order_feature_contract.py`, `exit_evidence.py` and `docs/acceptance/FT-GTT-001-capabilities.json`. Retain blocked/unverified readiness. Keep normal IOC/BSE smart translations unverified because documentation conflicts. Lot/tick/freeze, CMP, funds/holdings, sessions and permissions need integration evidence.

## Review Focus

1. MARKET conversion and ignored trailing intent: Task 1 exposes/refuses degradation.
2. SELL legs and TRIGGER payloads: Task 2 preserves directional semantics.
3. Fractional/non-finite quantities and conflicting aliases: Tasks 1–2 refuse.
4. Parent/child identity confusion and cancelled partial fills: Task 3 preserves evidence.
5. Per-fill quantity and errors mistaken for successful execution: Task 3 separates them.

## Task 1: Normal payload validation and execution disclosure

**Files:** M, T. **Interfaces:** preserve `to_place_order_payload(order: Any, security_id: str, *, algo_id: str | None = None) -> dict[str, Any]` and `to_modify_order_payload(order_id: str, changes: dict[str, Any], *, segment: str | None = None) -> dict[str, Any]`; add `indmoney_execution_effects(order: Any) -> dict[str, Any]`.

- [ ] Add `test_normal_wire_and_strict_numbers`: NSE/BSE→EQUITY; NFO/BFO→DERIVATIVE, NSE/BSE exchange. MIS/CNC/NRML map to INTRADAY/CNC/MARGIN. Reject fractional/bool/non-finite/nonpositive quantities, blank security IDs, EQUITY/MARGIN and DERIVATIVE/CNC combinations. Normal SL/SL-M remain rejected; AMO retains `is_amo`.
- [ ] Pin normal modify output exactly `{order_id:'DRV-2049',segment:'DERIVATIVE',qty:75,limit_price:73}`. Both required; conflicting quantity/qty or price/limit_price aliases and conflicting inferred/explicit segments raise `IndMoneyMappingError`.
- [ ] Add `test_requested_effective_execution`: helper returns `requested_type`, `effective_type`, `effective_limit_price`, `trailing_active`, `limitations`. MARKET gives effective LIMIT, unknown price (`None`), and `MARKET_TO_LIMIT`; TRIGGER without explicit price gives effective TRIGGER_LIMIT at trigger price. Requests with `is_tsl=True` or nonzero `tsl_step_size`/canonical `trailing_jump` add `TSL_IGNORED` and always `trailing_active=False`; payload builders reject requested active trailing instead of silently downgrading. Metadata never enters the wire payload.
- [ ] Run isolated command; expect FAIL. Implement bounded finite Decimal validation without quantity truncation. Rerun to PASS. Commit explicit M/T as `fix(indmoney): preserve effective order semantics`.

## Task 2: Smart placement and modification fidelity

**Files:** M, T. **Interfaces:** preserve `to_smart_order_payload(order: Any, security_id: str, *, algo_id: str | None = None) -> dict[str, Any]`, `to_smart_modify_payload(order_id: str, changes: dict[str, Any], *, segment: str | None = None, algo_id: str | None = None) -> dict[str, Any]`, `to_cancel_payload(order_id: str, segment: str) -> dict[str, Any]`.

- [ ] Add `test_trigger_keeps_legs_without_limit_price`: TRIGGER emits `trigger_price`, optional `trigger_limit_price` from canonical price, plus supplied paired SL/target fields; never `limit_price`. Remove the current early-return loss of protective legs. Reject explicit non-DAY smart validity rather than silently changing it.
- [ ] Add `test_buy_sell_leg_inequalities`: entry 100 BUY accepts SL 90/89 and target 110/111; SELL accepts SL 110/111 and target 90/89. Reject equality, wrong-side triggers and missing leg limits. Use LIMIT price or effective TRIGGER price as entry reference; MARKET/CMP-dependent checks remain unverified without a quote.
- [ ] Add `test_smart_modify_exact_fields`: required order_id/segment/algo_id; optional order_type/qty and documented price fields only. For TRIGGER require positive trigger_price; canonical price maps to trigger_limit_price, conflicting aliases fail, explicit limit_price fails. Reject unknown mutation fields, remarks/is_tsl/tsl_step_size/trailing_jump modification. Existing-type comparison requires caller evidence. Cancel contains only order_id and segment; GTT IDs require explicit segment, never infer a segment or child role from the prefix alone.
- [ ] Run isolated command: FAIL; implement shared leg validation; rerun: PASS. Commit M/T as `fix(indmoney): preserve smart order leg contracts`.

## Task 3: Read resources, statuses, fills and errors

**Files:** M, T. **Interfaces:** preserve `from_indmoney_order(d: dict[str, Any]) -> dict[str, Any]` and existing ID extractors; add `indmoney_attempt_state(status: object) -> str`, `from_indmoney_order_fill(d: dict[str, Any], *, order_id: str) -> dict[str, Any]`, `from_indmoney_smart_results(resp: Any) -> list[dict[str, Any]]`.

- [ ] Add `test_official_read_fields`: id→orderid, requested_qty→quantity, traded_qty→filled_quantity; retain security_id, exchange_order_id, all four protective prices, extra_info, remarks and timestamps. Preserve raw status; add attempt_state for ordinary orders; GTT resource rows keep UNKNOWN attempt_state. Parent trigger_price must not be inferred from sl_trigger_price. Reject malformed identities/numbers; absent quantities stay absent.
- [ ] Add `test_exact_rest_states`: SUCCESS→FILLED; CANCELLED and PARTIALLY FILLED - CANCELLED→CANCELLED; EXPIRED and PARTIALLY FILLED - EXPIRED→EXPIRED; PARTIALLY FILLED→PARTIALLY_FILLED; INITIATED→ACKNOWLEDGED; QUEUED/PROCESSING→SUBMITTING; O-PENDING/SL-PENDING/PENDING/MODIFIED→WORKING. FAILED/ABORTED and unfamiliar/blank/substrings remain UNKNOWN without stronger evidence. Explicit cancellation-pending aliases remain CANCEL_PENDING. Preserve 40 fills after cancellation of a 100 order.
- [ ] Add `test_fill_and_smart_resource_identity`: per-order fill maps quantity/price/trade_date/fill_id/exch_order_id plus explicit requested order_id; never invent order identity from exchange ID. Keep existing trade functions available. Smart-results dictionaries expose `parent_order_id,parent_status,child_order_id,child_status,error`; absent child/error values are None. Preserve every order_data item; malformed items raise rather than disappear. Legacy single-result extractor rejects multiple results instead of silently taking first. GTT parent/child stay distinct from spawned execution.
- [ ] Add `test_error_taxonomy`: preserve 429→RateLimitError, TokenException→SessionExpired, GatewayTimeoutException→BrokerTimeout; add RequestValidationException→OrderError with broker code/message retained. ACK/CREATED/MODIFIED are never fills. Feed R/P/S/F/C/RJ/PF/PFC and numeric event IDs remain separate future feed/correlation work; no guessed REST-prefix joins.
- [ ] Run isolated command: FAIL; implement; rerun: PASS; commit M/T as `fix(indmoney): retain resource and fill evidence`.

## Isolated red/green verification

Inherit every startup, import, collection, sentinel and result requirement in [offline verification](offline-mapping-verification.md), applied to this broker's M/T files. Prepare executor-local `/tmp/ft_mapping_verify.py`, `/tmp/indmoney-imports.json` and `/tmp/ft-mapping-check/network-denied`; none is supplied by this plan. The wrapper must establish OS-enforced network denial before launching Python, refusing if unavailable.

The manifest pins real source hashes and audited installed pytest/dependency paths. Use `-I -S`; load audited dependencies without site or `.pth` processing. The runner itself disables pytest plugin autoload/configuration, regardless of environment flags, file-loads real allowlisted modules under inert namespaces and rejects unlisted imports. Unresolved transitive dependencies block execution; no substitute runtime authority. 

```text
/tmp/ft-mapping-check/network-denied .venv/bin/python -I -S /tmp/ft_mapping_verify.py --manifest /tmp/indmoney-imports.json --mapping packages/integrations/gateway/src/flinttrade_gateway/brokers/indmoney_mapping.py --test packages/integrations/gateway/tests/brokers/test_indmoney_order_contract.py --no-conftest --deny-network
```

Run before/after each task: assertion failure → PASS; import/isolation failures are blockers, not red-test evidence. Standard `python scripts/ft.py test-fast`/package pytest commands remain unrun pending integration verification. No tests ran during planning. Complete books, durable recovery, dispatch, UI disclosure and funded acceptance remain separate unvalidated prerequisites; mapping success cannot enable writes.
