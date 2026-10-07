# Groww Smart Order Mappings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add independently tested, resource-specific GTT/OCO request and response mappings without enabling broker execution.

**Architecture:** Introduce one pure smart-order mapping module beside the ordinary mapper. Accept explicit native dictionaries and retain resource identity, nested fields and raw evidence; transport and lifecycle integration require a subsequent plan.

**Tech Stack:** Python 3.12, pytest, existing dependencies.

**Spec:** `FT-GTT-001-revised.md`; `docs/superpowers/plans/2026-10-06-full-order-flow.md`, Stage C; repository `docs/acceptance/FT-GTT-001-capabilities.json`.

## Global Constraints

- “Missing native reduce-only does not inherently disable native GTT.”
- “ACK, HTTP success and an order ID establish neither a fill nor a closed position.”
- Preserve requested versus effective values, per-item failures, account/product scope and existing readiness gates.
- Pure mapping fixtures only; no accounts, network execution, dependency upgrades or release actions. Any future release needs specific owner approval.

## Review Focus

1. GTT edit nesting and immutable transaction side: Task 2.
2. OCO sizing against signed exposure, without a reduce-only claim: Task 1.
3. Returned FNO/BSE resources and unknown status: Task 3.
4. Incomplete child identities and pagination: Task 3.
5. Non-finite prices, fractional quantities and unknown product combinations: Task 1.

## Baseline and evidence

Read-only baseline: `ad059991d7164c934676808f54550659051ed9d5`, checked 2026-10-06. Existing `to_place_order_payload(order: Any)`, `to_modify_payload(order_id: str, changes: dict[str, Any], *, segment: str)`, `to_cancel_payload(order_id: str, *, segment: str)` and `from_order(row: dict[str, Any])` already map ordinary orders. Preserve these and their tests. Their stop spelling differs from current annexure `SL`/`SL_M`; ordinary-wire compatibility remains a separately verified prerequisite, not a speculative rewrite here. `extract_order_id` recognising `smart_order_id` is not smart CRUD support.

Latest main `e658b50ab6753d63e64df250dfefabb91cc4630d` has runtime drift outside this mapping review; integration against it remains unassessed.

`brokers.lock` pins reference SDK growwapi 1.5.0; the implementation remains REST-based. SDK smart-method behaviour has not been independently established. Sources: [Smart Orders](https://groww.in/trade-api/docs/curl/smart-orders), [annexures](https://groww.in/trade-api/docs/curl/annexures), [limits](https://groww.in/trade-api/docs/curl), and the supplied capability research.

Use these exact repository paths throughout:
- M: `packages/integrations/gateway/src/flinttrade_gateway/brokers/groww_smart_mapping.py` (create)
- T: `packages/integrations/gateway/tests/brokers/test_groww_smart_mapping.py` (create)
- R: `packages/integrations/gateway/tests/brokers/test_groww_mapping.py` (unchanged regression)

### Offline runner prerequisite

Inherit every requirement of [offline mapping verification](offline-mapping-verification.md), including source/test hashes, audited installed pytest/dependency paths, sentinel checks and exit codes. Extend its executor-local runner broker selector to `groww`; allow M only; keep it standard-library-only. The runner/manifest are prerequisites, not supplied or validated here. Load real source by file-spec with inert namespaces; never execute package initialisers or mock authority. Establish network denial before Python. Launch `-I -S`; load only manifest-audited pytest/dependency paths without site or `.pth` processing. The runner itself disables plugin autoload, ignores ambient pytest options, and enforces no-conftest isolated collection. Missing isolation/import prerequisites block verification.

From repository root, every “Run T” means:
`unshare -Urn .venv/bin/python -I -S /tmp/ft-mapping-check/run.py --root "$PWD" --broker groww --tests packages/integrations/gateway/tests/brokers/test_groww_smart_mapping.py --manifest /tmp/ft-mapping-check/imports.json`

Repository `python scripts/ft.py test-fast <test-path> --workers 0` and ordinary pytest remain unrun pending integration validation.

### Task 1: Resource-specific creation

**Files:** M, T. **Interfaces:** produce `to_gtt_create_payload(request: Mapping[str, Any]) -> dict[str, Any]` and `to_oco_create_payload(request: Mapping[str, Any]) -> dict[str, Any]`.

- [ ] Write failing `test_create_gtt_nested_order`, `test_create_oco_position_bound`, and parameterised `test_create_rejects_invalid_inputs`. Assert GTT retains `order={"order_type":"LIMIT","price":"3990.00","transaction_type":"BUY"}` and trigger price separately. Assert OCO quantity 50/net-position 50 succeeds, 51 fails, and positive exposure with BUY fails.
- [ ] Run the isolated command; expect missing-function failures.
- [ ] Implement strict native-field allowlists. Copy reference ID, family, segment, symbol, quantity, product, exchange and duration; GTT additionally carries trigger price/direction and nested order; OCO carries signed net-position, exit side, target and stop-loss objects. Preserve decimal strings with `Decimal` validation; never truncate quantities. Reject non-finite/non-positive prices, booleans, unsupported fields and `child_legs` writes until their schema is established.
- [ ] Validate `CASH`/`FNO`, NSE/BSE, DAY execution validity, reference-ID grammar (8–20 alphanumeric/hyphen characters, at most two hyphens), GTT `UP`/`DOWN`, nested `LIMIT`/`MARKET`/`SL`/`SL_M`; require limit prices where applicable. Limit request fixtures to GTT CASH/CNC or FNO/NRML, OCO CASH/MIS and OCO FNO/NRML; reject other combinations as unverified. The official [Python SDK GTT documentation](https://groww.in/trade-api/docs/python-sdk/smart-orders) supplies the resource-specific GTT pairs omitted from the REST table. Apply that GTT policy to supplied current product context during modification, without filtering historical reads or permitting product changes. Preserve FNO quantity units without automatic lot conversion; instrument lot/tick/freeze checks remain integration prerequisites.
- [ ] Re-run T; expect PASS. Commit only M/T: `feat: add Groww smart order creation mappings`.

### Task 2: Safe modification and resource addressing

**Files:** M, T. **Interfaces:** `to_smart_modify_payload(current: Mapping[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]`; `smart_resource_path(operation: str, *, smart_order_id: str, segment: str, smart_order_type: str) -> str`.

- [ ] Write failing `test_modify_resource_allowlists` and `test_resource_paths`. Assert GTT MARKET edit emits nested `order.price=None`, preserves current `order.transaction_type`, rejects side/product/duration changes; OCO rejects order-type/limit-price edits while accepting quantity, duration, product and leg trigger prices.
- [ ] Run T; expect failures for missing interfaces.
- [ ] Implement nested allowlists, rejecting unknown edits rather than dropping them. Validate effective merged resource with Task 1 rules where applicable. Produce `/v1/order-advance/modify/{id}`, `/v1/order-advance/cancel/{segment}/{type}/{id}`, and `/v1/order-advance/status/{segment}/{type}/internal/{id}` for operations `modify`, `cancel`, `get`; reject unsafe identifier characters. These are PUT, POST and GET respectively; cancellation has no invented ordinary-order body. Never implement implicit cancel/recreate.
- [ ] Re-run T; expect PASS. Commit M/T: `feat: map Groww smart edits and resource identities`.

### Task 3: Evidence-preserving reads

**Files:** M, T. **Interfaces:** `from_smart_order(row: Mapping[str, Any]) -> dict[str, Any]`; `from_smart_page(payload: Mapping[str, Any]) -> list[dict[str, Any]]`.

- [ ] Write failing `test_smart_read_preserves_evidence` and `test_page_is_not_complete_book`. Assert deep-copied `native` retains timestamps, expiry, permission flags, nested legs and any returned IDs; output keeps `smart_order_id`, family, segment and `raw_status`. Assert ACTIVE→ARMED, CANCELLED→CANCELLED; all other values, including COMPLETED, remain UNKNOWN pending trigger-specific evidence. No execution-fill inference. Missing identity raises `ValueError`.
- [ ] Run T; expect failures. Implement mapping of every returned row, without segment/product filtering. Preserve undocumented child objects opaquely; do not manufacture spawned IDs. Parse only explicit successful `payload.orders`; malformed/unavailable envelopes fail, while an explicit empty page returns `[]` without a completeness claim.
- [ ] Re-run T offline; expect PASS. R remains deferred until its transitive imports are independently cleared. Commit M/T: `feat: preserve Groww smart resource evidence`.

For each commit above, stage only the two exact files using `git add packages/integrations/gateway/src/flinttrade_gateway/brokers/groww_smart_mapping.py packages/integrations/gateway/tests/brokers/test_groww_smart_mapping.py`, then `git commit -m "<message specified in task>"`. Do not push. Semantic request validation raises `ValueError`; malformed reads use the same exception in this standalone module.

## Remaining prerequisites

List retrieval must explicitly cover both families, CASH/FNO, status/time windows and pagination rather than relying on OCO/ACTIVE defaults. Preserve write limits 10/sec, 250/min separately from reads 20/sec, 500/min. Trading subscription, product eligibility, sessions, coherent position checks, bracket-child semantics and durable dispatch remain unvalidated. Bulk cancel/close is not established; never represent repeated calls as atomic success. No tests or implementation were executed while preparing this plan.
