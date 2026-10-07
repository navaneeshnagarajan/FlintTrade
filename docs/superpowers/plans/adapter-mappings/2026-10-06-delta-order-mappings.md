# Delta Exchange India Order Mappings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add isolated native-field/bracket mappings; preserve execution gates.

**Architecture:** Add a pure companion module which reuses pure primitives. Separate bracket resource types, preserving units/evidence; defer runtime integration.

**Tech Stack:** Python 3.12, pytest, existing dependencies.

**Spec:** `FT-GTT-001-revised.md`; `docs/superpowers/plans/2026-10-06-full-order-flow.md`, Stage C; repository `docs/acceptance/FT-GTT-001-capabilities.json`.

## Global Constraints

- “Where a broker does provide a native reduce-only primitive, use and preserve it for eligible exits instead of substituting a weaker client-only check.”
- “ACK, HTTP success and an order ID establish neither a fill nor a closed position.”
- No credentials, broker requests, dependency changes or enablement. Releases require specific owner approval.
- Preserve account/venue/product identity, requested/effective values, partial outcomes and runtime gates.

## Review Focus

1. Position bracket mistaken for an order bracket: Task 2.
2. Decimal prices rounded or contract counts treated as coins: Task 1.
3. Native reduce-only lost, or string false treated as true: Task 1.
4. Missing remaining size mistaken for fully filled: Task 3.
5. Successful bulk envelope hiding failures/skipped products: Task 3.

## Baseline and evidence

Baseline: `ad059991d7164c934676808f54550659051ed9d5`, 2026-10-06. Preserve `to_place_payload(order: Any, *, reduce_only: bool = False) -> dict[str, Any]`: market/limit/stop-loss, integer contracts, GTC/IOC, brackets and reduce-only already exist. Existing edit/cancel/read functions remain unchanged.

Gaps: conditional/options/bracket fields and lossless readback; absent quantities currently become zero. `brokers.lock` establishes no Delta SDK pin.

Sources, checked 2026-10-06: [CreateOrderRequest](https://docs.delta.exchange/#tocS_CreateOrderRequest), CreateBracketOrderRequest, EditBracketOrderRequest, Order, and supplied capability research. Runtime drift at main `e658b50ab6753d63e64df250dfefabb91cc4630d` remains unassessed.

Exact files:
- M: `packages/integrations/gateway/src/flinttrade_gateway/brokers/delta_order_mapping.py` (create)
- T: `packages/integrations/gateway/tests/brokers/test_delta_order_mapping.py` (create)
- Existing composition dependency: `packages/integrations/gateway/src/flinttrade_gateway/brokers/delta_mapping.py`

### Offline runner prerequisite

Inherit all requirements of [offline mapping verification](offline-mapping-verification.md), including source/test hashes, audited installed pytest/dependency paths, sentinel checks and exit codes. Extend its executor-local runner broker selector to `delta`; allow M, existing `delta_mapping.py`, and `packages/core/core/src/flinttrade_core/exceptions.py`; audit the complete pure import closure. The runner/manifest remain unvalidated prerequisites. Load real source by file-spec with inert namespaces; never execute package initialisers or mock authority. Establish network denial before Python. Launch `-I -S`; load only manifest-audited pytest/dependency paths without site or `.pth` processing. The runner itself disables plugin autoload, ignores ambient pytest options, and enforces no-conftest isolated collection. Missing isolation/import prerequisites block verification.

From repository root, every “Run T” means:
`unshare -Urn .venv/bin/python -I -S /tmp/ft-mapping-check/run.py --root "$PWD" --broker delta --tests packages/integrations/gateway/tests/brokers/test_delta_order_mapping.py --manifest /tmp/ft-mapping-check/imports.json`

Repository `python scripts/ft.py test-fast <test-path> --workers 0` and ordinary pytest remain unrun pending integration validation.

### Task 1: Explicit native options and precision

**Files:** M, T. **Interfaces:** `to_native_place_payload(order: Any, *, native: Mapping[str, Any], reduce_only: bool = False) -> dict[str, Any]`; `validate_contract_payload(payload: Mapping[str, Any], *, tick_size: str) -> None`.

- [ ] Write failing `test_native_options_preserved`, `test_reduce_only_boolean`, `test_contract_precision`. Assert `quantity=10` remains size 10 regardless of contract value 0.001; quantity 0.01 fails; exact price `59000.50` survives. Reject booleans/non-finite prices and tick violations without rounding. Assert reduce-only True produces boolean true; `"false"` raises. Add `test_native_only_stop_price` (SL-M, no canonical trigger, native stop_price="56000") and `test_trailing_only_stop` (SL-M, trail_amount="50", no stop_price); both succeed with stop_loss_order. Conflicting aliases fail.
- [ ] Run T; expect missing-interface failures.
- [ ] For ordinary non-conditional requests, compose existing placement. For conditional requests, build directly in M using existing `product_symbol`, `contract_size` and `time_in_force` primitives; resolve canonical/native stop aliases before validation, without calling base SL/SL-M placement. Map SL→limit_order and SL-M/SLM→market_order; omit absent stop_price for trailing-only requests. Accept only `post_only`, `client_order_id`, `stop_order_type`, `stop_price`, `trail_amount`, `stop_trigger_method`, `bracket_stop_loss_limit_price`, `bracket_take_profit_limit_price`, `bracket_stop_trigger_method`. Reject unknown keys; canonicalise reduce-only from the explicit boolean argument only. Enforce client-ID length ≤32, boolean post-only, conditional kind `stop_loss_order`/`take_profit_order`, and trigger method `mark_price`/`last_traded_price`/`spot_price`. Preserve default mark-price behaviour; reject contradictory aliases rather than silently overwrite them.
- [ ] Validate native decimal strings with Decimal, positive integer contract count and supplied positive tick size. Conditional orders require stop price or a positive trailing amount; limit orders require limit price. Product eligibility/units remain external facts. Preserve DAY→GTC for later presentation.
- [ ] Re-run T; expect PASS. Commit M/T: `feat: preserve Delta native order options`.

### Task 2: Distinct bracket mappings

**Files:** M, T. **Interfaces:** `to_order_bracket_edit_payload(order_id: str, changes: Mapping[str, Any]) -> dict[str, Any]`; `to_position_bracket_create_payload(request: Mapping[str, Any]) -> dict[str, Any]`.

- [ ] Write failing `test_order_bracket_edit_is_flat`, `test_position_bracket_create_is_nested`, `test_bracket_identity_rejected`. Assert order ID `"34521712"` becomes integer `id=34521712`; nested position-leg fields in an order edit raise `ValueError`.
- [ ] Run T; expect failures.
- [ ] Implement order edits with one product identity and flat `bracket_stop_loss_price`, `bracket_stop_loss_limit_price`, `bracket_take_profit_price`, `bracket_take_profit_limit_price`, `bracket_trail_amount`, `bracket_stop_trigger_method`; retain order identity. Implement position creation with exactly one product identity, nested `stop_loss_order`/`take_profit_order`, and bracket trigger method. Nested legs carry order type, stop price, limit price; only stop-loss accepts trail amount. Validate using Task 1 rules. Reject both product identities, empty legs, arbitrary order IDs on position creation and unknown fields.
- [ ] Re-run T; expect PASS. Commit M/T: `feat: distinguish Delta bracket resource mappings`.

Order edits target PUT `/v2/orders/bracket`; position creation targets POST there. Position-bracket modification is unknown: define no function or guessed fields for it. Existing ordinary order bracket placement remains intact. One position bracket per contract differs from multiple order brackets; never invent child IDs.

### Task 3: Conservative read and bulk evidence

**Files:** M, T. **Interfaces:** `from_native_order(row: Mapping[str, Any]) -> dict[str, Any]`; `from_operation_response(payload: Mapping[str, Any], *, operation: str) -> dict[str, Any]`.

- [ ] Write failing `test_order_evidence_requires_quantities` and `test_operation_preserves_partial_evidence`. Assert size 10/unfilled 2 yields filled 8, cancelled retains 8, missing unfilled stays absent, and negative/oversized/fractional quantities raise. Assert raw reduce-only, conditional/bracket fields, client ID and timestamps survive deep-copying.
- [ ] Run T; expect failures. Implement output keys `orderid`, `product_id`, `symbol`, `quantity_unit="contracts"`, `raw_status`, `native`, and present-only quantities. Map exact open→WORKING, pending→UNKNOWN, cancelled/canceled→CANCELLED; closed→FILLED only with valid zero remainder, otherwise UNKNOWN. Unknown strings remain UNKNOWN.
- [ ] Implement operation output `operation`, `raw_response`, `items`, `skipped_products`, `complete=False`. Copy list-valued result entries separately, preserving errors and identities; preserve close-all `result.skipped_products` and reasons. Unknown shapes remain raw with empty items and no success inference. Preserve pagination metadata in raw responses for active orders/history/fills; missing rows never establish complete books.
- [ ] Re-run T; expect PASS. Commit M/T: `feat: retain Delta order and bulk evidence`.

Commit only M/T with `git add` and `git commit -m "<task message>"`; no push. New validators raise `ValueError`; existing exceptions remain unchanged.

## Remaining prerequisites

Batch create is same-contract, maximum 50, limit/GTC only; edit/delete retain separate schemas and item outcomes. Close-all skips halted/auction products and never proves flatness. Account quota 20,000 weighted units/5min differs from matching-engine 500 operations/sec/product; cancellations have a documented matching-engine exemption. Completeness, permissions, product eligibility, durable reconciliation, cancellation races, dispatch and live readiness remain unvalidated. No tests ran.
