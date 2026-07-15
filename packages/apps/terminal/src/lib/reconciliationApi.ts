/**
 * Reconciliation observability API — typed client + TanStack Query hooks.
 *
 * Talks to the FlintTrade backend's reconciliation routes (operations
 * blueprint, `/api/v1/reconciliation/*`) through the shared ftApi helpers so
 * paths, auth headers, and the `{status, data}` envelope behave exactly like
 * every other backend call (dev: `/ft-api/api/v1/...` via the Vite proxy;
 * prod: `/api/v1/...`).
 *
 * The backend reads the engine ReconciliationRunner's JSONL history
 * (`<workspace>/reconciliation/<broker>/<account>.jsonl`); POST `run`
 * triggers one `run_once()` cycle over the active native broker sessions.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FtApiError, get, post } from "@/services/ftApi.helpers";
import { useAuthStore } from "@/stores/authStore";

// ---------------------------------------------------------------------------
// Types — mirror flinttrade_gateway.reconciliation.ReconciliationReport.as_dict()
// ---------------------------------------------------------------------------

export type ReconciliationSeverity = "info" | "warning" | "critical";

export interface ReconciliationSeverityCounts {
  info: number;
  warning: number;
  critical: number;
}

export interface ReconciliationOrderDiff {
  order_id: string;
  symbol: string;
  discrepancy: string;
  severity: ReconciliationSeverity;
  flinttrade_status: string;
  broker_status: string;
  detail: string;
}

export interface ReconciliationPositionDiff {
  symbol: string;
  exchange: string;
  product: string;
  flinttrade_qty: number;
  broker_qty: number;
  discrepancy: string;
  severity: ReconciliationSeverity;
}

export interface ReconciliationHoldingDiff {
  symbol: string;
  exchange: string;
  flinttrade_qty: number;
  broker_qty: number;
  discrepancy: string;
  severity: ReconciliationSeverity;
}

export interface ReconciliationReport {
  adapter_id: string;
  account_id: string;
  generated_at: string;
  orders_diff: ReconciliationOrderDiff[];
  positions_diff: ReconciliationPositionDiff[];
  holdings_diff: ReconciliationHoldingDiff[];
  error: string;
  clean: boolean;
  severity: "" | ReconciliationSeverity;
  severity_counts: ReconciliationSeverityCounts;
}

/** One row of GET /reconciliation/status — the latest report per target. */
export interface ReconciliationTargetStatus {
  broker: string;
  account_id: string;
  last_report_at: string;
  clean: boolean;
  severity: "" | ReconciliationSeverity;
  severity_counts: ReconciliationSeverityCounts;
  error: string;
}

export interface ReconciliationStatus {
  targets: ReconciliationTargetStatus[];
  /** True while the engine's background runner is polling native sessions. */
  runner_active: boolean;
}

export interface ReconciliationRunResult {
  count: number;
  reports: ReconciliationReport[];
}

export interface ReconciliationOutcomeItem {
  item_index: number;
  symbol: string;
  exchange: string;
  product: string;
  action: string;
  quantity: number;
  price: number;
  trigger_price: number;
  price_type: string;
  variety: string;
  validity: string;
  strategy: string;
}

export type ReconciliationResolutionOutcome =
  "confirmed_applied" | "confirmed_not_applied" | "confirmed_partial";

export interface ReconciliationPendingResolution {
  resolution_id: string;
  outcome: ReconciliationResolutionOutcome;
  broker_order_ids: string[];
  broker_order_item_indexes: number[];
  not_applied_item_indexes: number[];
  note: string;
  evidence_digest: string;
  status: ReconciliationResolutionStatus;
  prepared_at: string;
}

/** One unresolved app-owned broker write returned by GET /reconciliation/outcomes. */
export interface ReconciliationOutcome {
  attempt_id: string;
  adapter_id: string;
  account_id: string;
  business_date: string;
  operation: string;
  dispatch_state: string;
  intent_source: string;
  symbol: string;
  exchange: string;
  product: string;
  action: string;
  quantity: number;
  price: number;
  trigger_price: number;
  price_type: string;
  variety: string;
  validity: string;
  strategy: string;
  prepared_at: string;
  invoked_at: string;
  unknown_at: string;
  error_kind: string;
  recovery_supported_outcomes: ReconciliationResolutionOutcome[];
  recovery_blocked_reason: string;
  items: ReconciliationOutcomeItem[];
  resolution: ReconciliationPendingResolution | null;
}

export interface ReconciliationOutcomesResult {
  count: number;
  outcomes: ReconciliationOutcome[];
}

export interface ResolveReconciliationOutcomeBody {
  broker: string;
  account_id: string;
  business_date: string;
  outcome: ReconciliationResolutionOutcome;
  broker_order_ids: string[];
  broker_order_item_indexes: number[];
  not_applied_item_indexes: number[];
  confirmation: string;
  note: string;
}

export interface ResolveReconciliationOutcomeResult {
  resolution_id: string;
  attempt_id: string;
  outcome: ReconciliationResolutionOutcome;
  status: "COMMITTED";
  evidence_digest: string;
  router_fault_cleared: boolean;
  writes_unblocked: boolean;
  remaining_outcomes: number | null;
}

export interface ResolveReconciliationOutcomeVariables {
  attemptId: string;
  body: ResolveReconciliationOutcomeBody;
}

export interface ReconciliationErrorResolution {
  attempt_id: string;
  resolution: ReconciliationPendingResolution;
}

export interface ResolveReconciliationOutcomeCallbacks {
  onSuccess?: (
    result: ResolveReconciliationOutcomeResult,
    variables: ResolveReconciliationOutcomeVariables,
  ) => void;
  onError?: (
    error: Error,
    variables: ResolveReconciliationOutcomeVariables,
    errorResolution: ReconciliationErrorResolution | null,
  ) => void;
}

type UnknownRecord = Record<string, unknown>;
export type ReconciliationPendingStatus =
  "PENDING_AUDIT" | "PENDING_ROUTER_CLEAR";
export type ReconciliationResolutionStatus =
  ReconciliationPendingStatus | "COMMITTED";

const UNAUTHENTICATED_PRINCIPAL = "__unauthenticated__";
const RESOLUTION_OUTCOMES = new Set<ReconciliationResolutionOutcome>([
  "confirmed_applied",
  "confirmed_not_applied",
  "confirmed_partial",
]);
const RECONCILIATION_SEVERITIES = new Set<ReconciliationSeverity>([
  "info",
  "warning",
  "critical",
]);
const UNRESOLVED_DISPATCH_STATES = new Set([
  "OUTCOME_UNKNOWN",
  "CONFIRMED_APPLIED",
  "CONFIRMED_NOT_APPLIED",
  "CONFIRMED_PARTIAL",
]);
const OUTCOME_STRING_FIELDS = [
  "attempt_id",
  "adapter_id",
  "account_id",
  "business_date",
  "operation",
  "dispatch_state",
  "intent_source",
  "symbol",
  "exchange",
  "product",
  "action",
  "price_type",
  "variety",
  "validity",
  "strategy",
  "prepared_at",
  "invoked_at",
  "unknown_at",
  "error_kind",
  "recovery_blocked_reason",
] as const;
const INTENT_STRING_FIELDS = [
  "symbol",
  "exchange",
  "product",
  "action",
  "price_type",
  "variety",
  "validity",
  "strategy",
] as const;
const INTENT_NUMBER_FIELDS = ["quantity", "price", "trigger_price"] as const;

function recordValue(value: unknown): UnknownRecord | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as UnknownRecord)
    : null;
}

function textValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function strictStringArray(value: unknown): string[] | null {
  if (
    !Array.isArray(value) ||
    value.some(
      (item) =>
        typeof item !== "string" ||
        item.length === 0 ||
        item !== item.trim() ||
        /\s/u.test(item),
    ) ||
    new Set(value).size !== value.length
  )
    return null;
  return value;
}

function strictIndexArray(value: unknown): number[] | null {
  if (
    !Array.isArray(value) ||
    value.some((item) => !Number.isInteger(item) || item < 0) ||
    new Set(value).size !== value.length
  )
    return null;
  return value as number[];
}

function isResolutionOutcome(
  value: unknown,
): value is ReconciliationResolutionOutcome {
  return (
    typeof value === "string" &&
    RESOLUTION_OUTCOMES.has(value as ReconciliationResolutionOutcome)
  );
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function hasStringFields<T extends readonly string[]>(
  record: UnknownRecord,
  fields: T,
): boolean {
  return fields.every((field) => typeof record[field] === "string");
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isBusinessDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return (
    !Number.isNaN(parsed.getTime()) &&
    parsed.toISOString().slice(0, 10) === value
  );
}

function timestampValue(value: string): number | null {
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function operationRecoveryOutcomes(
  operation: string,
): ReconciliationResolutionOutcome[] {
  if (operation === "place_multi_order") {
    return ["confirmed_applied", "confirmed_not_applied", "confirmed_partial"];
  }
  if (
    operation === "place_order" ||
    operation === "place_reducing_order" ||
    operation === "modify_order" ||
    operation === "cancel_order" ||
    operation === "cancel_smart_order"
  ) {
    return ["confirmed_applied", "confirmed_not_applied"];
  }
  return [];
}

function strictRecoveryOutcomes(
  value: unknown,
  operation: string,
): ReconciliationResolutionOutcome[] | null {
  if (
    !Array.isArray(value) ||
    value.some((outcome) => !isResolutionOutcome(outcome)) ||
    new Set(value).size !== value.length
  )
    return null;
  const expected = operationRecoveryOutcomes(operation);
  const isCompleteSet =
    value.length === expected.length &&
    expected.every((outcome) => value.includes(outcome));
  const isMigratedPositiveOnly =
    expected.includes("confirmed_applied") &&
    value.length === 1 &&
    value[0] === "confirmed_applied";
  if (!isCompleteSet && !isMigratedPositiveOnly) return null;
  return value as ReconciliationResolutionOutcome[];
}

function recoveryReasonMatchesCapabilities(
  supportedOutcomes: ReconciliationResolutionOutcome[],
  operation: string,
  blockedReason: string,
): boolean {
  const expected = operationRecoveryOutcomes(operation);
  if (expected.length === 0) {
    return supportedOutcomes.length === 0 && isNonEmptyString(blockedReason);
  }
  const isRestricted = supportedOutcomes.length < expected.length;
  return isRestricted
    ? isNonEmptyString(blockedReason)
    : blockedReason.length === 0;
}

interface IntentEvidence {
  symbol: string;
  exchange: string;
  product: string;
  action: string;
  quantity: number;
  price: number;
  trigger_price: number;
  price_type: string;
  variety: string;
  validity: string;
  strategy: string;
}

function hasPlacementIntentEvidence(intent: IntentEvidence): boolean {
  return (
    isNonEmptyString(intent.symbol) &&
    isNonEmptyString(intent.exchange) &&
    isNonEmptyString(intent.product) &&
    isNonEmptyString(intent.action) &&
    intent.quantity > 0 &&
    intent.price >= 0 &&
    intent.trigger_price >= 0
  );
}

function hasModifyIntentEvidence(intent: IntentEvidence): boolean {
  return (
    INTENT_STRING_FIELDS.some((field) => intent[field].trim().length > 0) ||
    INTENT_NUMBER_FIELDS.some((field) => intent[field] !== 0)
  );
}

function strictSeverityCounts(
  value: unknown,
): ReconciliationSeverityCounts | null {
  const record = recordValue(value);
  if (!record) return null;
  const values = [record.info, record.warning, record.critical];
  if (values.some((count) => !Number.isInteger(count) || (count as number) < 0))
    return null;
  return {
    info: record.info as number,
    warning: record.warning as number,
    critical: record.critical as number,
  };
}

function isReconciliationSeverity(
  value: unknown,
): value is ReconciliationSeverity {
  return (
    typeof value === "string" &&
    RECONCILIATION_SEVERITIES.has(value as ReconciliationSeverity)
  );
}

function worstSeverity(
  counts: ReconciliationSeverityCounts,
  error: string,
): "" | ReconciliationSeverity {
  if (error || counts.critical > 0) return "critical";
  if (counts.warning > 0) return "warning";
  if (counts.info > 0) return "info";
  return "";
}

function statusFieldsAreConsistent(
  clean: boolean,
  severity: string,
  counts: ReconciliationSeverityCounts,
  error: string,
): severity is "" | ReconciliationSeverity {
  const discrepancyCount = counts.info + counts.warning + counts.critical;
  const expectedClean = discrepancyCount === 0 && error.length === 0;
  return clean === expectedClean && severity === worstSeverity(counts, error);
}

function normaliseOrderDiff(value: unknown): ReconciliationOrderDiff | null {
  const record = recordValue(value);
  const stringFields = [
    "order_id",
    "symbol",
    "discrepancy",
    "flinttrade_status",
    "broker_status",
    "detail",
  ] as const;
  if (
    !record ||
    stringFields.some((field) => typeof record[field] !== "string") ||
    !isReconciliationSeverity(record.severity)
  )
    return null;
  return {
    order_id: record.order_id as string,
    symbol: record.symbol as string,
    discrepancy: record.discrepancy as string,
    severity: record.severity,
    flinttrade_status: record.flinttrade_status as string,
    broker_status: record.broker_status as string,
    detail: record.detail as string,
  };
}

function normalisePositionDiff(
  value: unknown,
): ReconciliationPositionDiff | null {
  const record = recordValue(value);
  const stringFields = [
    "symbol",
    "exchange",
    "product",
    "discrepancy",
  ] as const;
  if (
    !record ||
    stringFields.some((field) => typeof record[field] !== "string") ||
    typeof record.flinttrade_qty !== "number" ||
    !Number.isFinite(record.flinttrade_qty) ||
    typeof record.broker_qty !== "number" ||
    !Number.isFinite(record.broker_qty) ||
    !isReconciliationSeverity(record.severity)
  )
    return null;
  return {
    symbol: record.symbol as string,
    exchange: record.exchange as string,
    product: record.product as string,
    flinttrade_qty: record.flinttrade_qty,
    broker_qty: record.broker_qty,
    discrepancy: record.discrepancy as string,
    severity: record.severity,
  };
}

function normaliseHoldingDiff(
  value: unknown,
): ReconciliationHoldingDiff | null {
  const record = recordValue(value);
  const stringFields = ["symbol", "exchange", "discrepancy"] as const;
  if (
    !record ||
    stringFields.some((field) => typeof record[field] !== "string") ||
    typeof record.flinttrade_qty !== "number" ||
    !Number.isFinite(record.flinttrade_qty) ||
    typeof record.broker_qty !== "number" ||
    !Number.isFinite(record.broker_qty) ||
    !isReconciliationSeverity(record.severity)
  )
    return null;
  return {
    symbol: record.symbol as string,
    exchange: record.exchange as string,
    flinttrade_qty: record.flinttrade_qty,
    broker_qty: record.broker_qty,
    discrepancy: record.discrepancy as string,
    severity: record.severity,
  };
}

function normaliseReport(
  value: unknown,
  fallbackBroker: string,
  fallbackAccountId: string,
): ReconciliationReport | null {
  const record = recordValue(value);
  if (!record) return null;
  const adapterId = textValue(record.adapter_id);
  const accountId = textValue(record.account_id);
  const generatedAt = textValue(record.generated_at);
  const ordersDiff = Array.isArray(record.orders_diff)
    ? record.orders_diff.map(normaliseOrderDiff)
    : null;
  const positionsDiff = Array.isArray(record.positions_diff)
    ? record.positions_diff.map(normalisePositionDiff)
    : null;
  const holdingsDiff = Array.isArray(record.holdings_diff)
    ? record.holdings_diff.map(normaliseHoldingDiff)
    : null;
  const severityCounts = strictSeverityCounts(record.severity_counts);
  if (
    !adapterId ||
    !accountId ||
    !generatedAt ||
    timestampValue(generatedAt) === null ||
    (fallbackBroker && adapterId !== fallbackBroker) ||
    (fallbackAccountId && accountId !== fallbackAccountId) ||
    !ordersDiff ||
    ordersDiff.some((row) => row === null) ||
    !positionsDiff ||
    positionsDiff.some((row) => row === null) ||
    !holdingsDiff ||
    holdingsDiff.some((row) => row === null) ||
    !severityCounts ||
    typeof record.error !== "string" ||
    typeof record.clean !== "boolean" ||
    typeof record.severity !== "string"
  ) {
    return null;
  }
  const observedCounts: ReconciliationSeverityCounts = {
    info: 0,
    warning: 0,
    critical: 0,
  };
  for (const diff of [...ordersDiff, ...positionsDiff, ...holdingsDiff]) {
    if (diff) observedCounts[diff.severity] += 1;
  }
  if (
    observedCounts.info !== severityCounts.info ||
    observedCounts.warning !== severityCounts.warning ||
    observedCounts.critical !== severityCounts.critical ||
    !statusFieldsAreConsistent(
      record.clean,
      record.severity,
      severityCounts,
      record.error,
    )
  ) {
    return null;
  }
  return {
    adapter_id: adapterId,
    account_id: accountId,
    generated_at: generatedAt,
    orders_diff: ordersDiff as ReconciliationOrderDiff[],
    positions_diff: positionsDiff as ReconciliationPositionDiff[],
    holdings_diff: holdingsDiff as ReconciliationHoldingDiff[],
    error: record.error,
    clean: record.clean,
    severity: record.severity,
    severity_counts: severityCounts,
  };
}

function normaliseTargetStatus(
  value: unknown,
): ReconciliationTargetStatus | null {
  const record = recordValue(value);
  if (!record) return null;
  const broker = textValue(record.broker);
  const accountId = textValue(record.account_id);
  const lastReportAt = textValue(record.last_report_at);
  const counts = strictSeverityCounts(record.severity_counts);
  if (
    !broker ||
    !accountId ||
    !lastReportAt ||
    timestampValue(lastReportAt) === null ||
    typeof record.clean !== "boolean" ||
    typeof record.severity !== "string" ||
    typeof record.error !== "string" ||
    !counts ||
    !statusFieldsAreConsistent(
      record.clean,
      record.severity,
      counts,
      record.error,
    )
  )
    return null;
  return {
    broker,
    account_id: accountId,
    last_report_at: lastReportAt,
    clean: record.clean,
    severity: record.severity,
    severity_counts: counts,
    error: record.error,
  };
}

function normaliseStatus(value: unknown): ReconciliationStatus {
  const record = recordValue(value);
  if (
    !record ||
    !Array.isArray(record.targets) ||
    typeof record.runner_active !== "boolean"
  ) {
    throw new Error("Reconciliation status response is malformed.");
  }
  const targets = record.targets.map(normaliseTargetStatus);
  if (targets.some((target) => target === null)) {
    throw new Error("Reconciliation status evidence is malformed.");
  }
  return {
    targets: targets as ReconciliationTargetStatus[],
    runner_active: record.runner_active,
  };
}

function normaliseOutcomeItem(
  value: unknown,
): ReconciliationOutcomeItem | null {
  const record = recordValue(value);
  if (
    !record ||
    !Number.isInteger(record.item_index) ||
    (record.item_index as number) < 0 ||
    !hasStringFields(record, INTENT_STRING_FIELDS) ||
    INTENT_NUMBER_FIELDS.some((field) => !isFiniteNumber(record[field])) ||
    (record.quantity as number) < 0
  ) {
    return null;
  }
  const item: ReconciliationOutcomeItem = {
    item_index: record.item_index as number,
    symbol: record.symbol as string,
    exchange: record.exchange as string,
    product: record.product as string,
    action: record.action as string,
    quantity: record.quantity as number,
    price: record.price as number,
    trigger_price: record.trigger_price as number,
    price_type: record.price_type as string,
    variety: record.variety as string,
    validity: record.validity as string,
    strategy: record.strategy as string,
  };
  return hasPlacementIntentEvidence(item) ? item : null;
}

function normalisePendingResolution(
  value: unknown,
): ReconciliationPendingResolution | null {
  const record = recordValue(value);
  const brokerOrderIds = strictStringArray(record?.broker_order_ids);
  const brokerOrderItemIndexes = strictIndexArray(
    record?.broker_order_item_indexes,
  );
  const notAppliedItemIndexes = strictIndexArray(
    record?.not_applied_item_indexes,
  );
  const status = textValue(record?.status);
  if (
    !record ||
    !textValue(record.resolution_id) ||
    !isResolutionOutcome(record.outcome) ||
    (status !== "PENDING_AUDIT" &&
      status !== "PENDING_ROUTER_CLEAR" &&
      status !== "COMMITTED") ||
    !brokerOrderIds ||
    !brokerOrderItemIndexes ||
    !notAppliedItemIndexes ||
    typeof record.note !== "string" ||
    typeof record.evidence_digest !== "string" ||
    record.evidence_digest.length === 0 ||
    typeof record.prepared_at !== "string" ||
    record.prepared_at.length === 0
  ) {
    return null;
  }
  return {
    resolution_id: textValue(record.resolution_id),
    outcome: record.outcome,
    broker_order_ids: brokerOrderIds,
    broker_order_item_indexes: brokerOrderItemIndexes,
    not_applied_item_indexes: notAppliedItemIndexes,
    note: record.note,
    evidence_digest: record.evidence_digest,
    status,
    prepared_at: record.prepared_at,
  };
}

function resolutionEvidenceIsValid(
  operation: string,
  items: ReconciliationOutcomeItem[],
  resolution: ReconciliationPendingResolution,
): boolean {
  if (
    (resolution.outcome === "confirmed_not_applied" ||
      resolution.outcome === "confirmed_partial") &&
    resolution.note.trim().length === 0
  )
    return false;

  if (operation === "place_multi_order") {
    if (
      resolution.broker_order_ids.length !==
      resolution.broker_order_item_indexes.length
    ) {
      return false;
    }
    const itemIndexes = new Set(items.map((item) => item.item_index));
    const appliedIndexes = new Set(resolution.broker_order_item_indexes);
    const notAppliedIndexes = new Set(resolution.not_applied_item_indexes);
    if (
      [...appliedIndexes, ...notAppliedIndexes].some(
        (index) => !itemIndexes.has(index),
      ) ||
      [...appliedIndexes].some((index) => notAppliedIndexes.has(index)) ||
      appliedIndexes.size + notAppliedIndexes.size !== itemIndexes.size
    )
      return false;
    if (resolution.outcome === "confirmed_applied") {
      return (
        appliedIndexes.size === itemIndexes.size && notAppliedIndexes.size === 0
      );
    }
    if (resolution.outcome === "confirmed_not_applied") {
      return (
        appliedIndexes.size === 0 &&
        resolution.broker_order_ids.length === 0 &&
        notAppliedIndexes.size === itemIndexes.size
      );
    }
    return appliedIndexes.size > 0 && notAppliedIndexes.size > 0;
  }

  if (
    resolution.broker_order_item_indexes.length > 0 ||
    resolution.not_applied_item_indexes.length > 0 ||
    resolution.outcome === "confirmed_partial"
  )
    return false;
  if (operation === "place_order" || operation === "place_reducing_order") {
    return (
      resolution.broker_order_ids.length ===
      (resolution.outcome === "confirmed_applied" ? 1 : 0)
    );
  }
  return resolution.broker_order_ids.length === 0;
}

function normaliseOutcome(value: unknown): ReconciliationOutcome | null {
  const record = recordValue(value);
  if (
    !record ||
    !hasStringFields(record, OUTCOME_STRING_FIELDS) ||
    INTENT_NUMBER_FIELDS.some((field) => !isFiniteNumber(record[field])) ||
    (record.quantity as number) < 0 ||
    !isNonEmptyString(record.attempt_id) ||
    !isNonEmptyString(record.adapter_id) ||
    !isNonEmptyString(record.account_id) ||
    !isNonEmptyString(record.operation) ||
    !isNonEmptyString(record.error_kind) ||
    !isBusinessDate(record.business_date as string) ||
    !UNRESOLVED_DISPATCH_STATES.has(record.dispatch_state as string) ||
    !Array.isArray(record.items) ||
    !("resolution" in record)
  )
    return null;

  const preparedAt = timestampValue(record.prepared_at as string);
  const invokedAt = timestampValue(record.invoked_at as string);
  const unknownAt = timestampValue(record.unknown_at as string);
  if (
    preparedAt === null ||
    invokedAt === null ||
    unknownAt === null ||
    preparedAt > invokedAt ||
    invokedAt > unknownAt
  )
    return null;

  const operation = record.operation as string;
  const items = record.items.map(normaliseOutcomeItem);
  if (
    items.some((item) => item === null) ||
    new Set(items.map((item) => item?.item_index)).size !== items.length
  ) {
    return null;
  }
  const strictItems = items as ReconciliationOutcomeItem[];
  if (
    operation === "place_multi_order"
      ? strictItems.length === 0 ||
        strictItems.some((item, position) => item.item_index !== position)
      : strictItems.length > 0
  )
    return null;

  const intent: IntentEvidence = {
    symbol: record.symbol as string,
    exchange: record.exchange as string,
    product: record.product as string,
    action: record.action as string,
    quantity: record.quantity as number,
    price: record.price as number,
    trigger_price: record.trigger_price as number,
    price_type: record.price_type as string,
    variety: record.variety as string,
    validity: record.validity as string,
    strategy: record.strategy as string,
  };
  if (
    intent.price < 0 ||
    intent.trigger_price < 0 ||
    ((operation === "place_order" || operation === "place_reducing_order") &&
      !hasPlacementIntentEvidence(intent)) ||
    (operation === "modify_order" && !hasModifyIntentEvidence(intent))
  )
    return null;

  const supportedOutcomes = strictRecoveryOutcomes(
    record.recovery_supported_outcomes,
    operation,
  );
  if (
    !supportedOutcomes ||
    !recoveryReasonMatchesCapabilities(
      supportedOutcomes,
      operation,
      record.recovery_blocked_reason as string,
    )
  )
    return null;

  const resolution = normalisePendingResolution(record.resolution);
  if (record.resolution !== null && resolution === null) {
    return null;
  }
  if (resolution) {
    const expectedDispatchState = {
      confirmed_applied: "CONFIRMED_APPLIED",
      confirmed_not_applied: "CONFIRMED_NOT_APPLIED",
      confirmed_partial: "CONFIRMED_PARTIAL",
    }[resolution.outcome];
    if (
      resolution.status === "COMMITTED" ||
      !supportedOutcomes.includes(resolution.outcome) ||
      !resolutionEvidenceIsValid(operation, strictItems, resolution) ||
      (resolution.status === "PENDING_AUDIT" &&
        record.dispatch_state !== "OUTCOME_UNKNOWN") ||
      (resolution.status === "PENDING_ROUTER_CLEAR" &&
        record.dispatch_state !== expectedDispatchState)
    )
      return null;
  } else if (record.dispatch_state !== "OUTCOME_UNKNOWN") {
    return null;
  }

  return {
    attempt_id: record.attempt_id as string,
    adapter_id: record.adapter_id as string,
    account_id: record.account_id as string,
    business_date: record.business_date as string,
    operation,
    dispatch_state: record.dispatch_state as string,
    intent_source: record.intent_source as string,
    symbol: intent.symbol,
    exchange: intent.exchange,
    product: intent.product,
    action: intent.action,
    quantity: intent.quantity,
    price: intent.price,
    trigger_price: intent.trigger_price,
    price_type: intent.price_type,
    variety: intent.variety,
    validity: intent.validity,
    strategy: intent.strategy,
    prepared_at: record.prepared_at as string,
    invoked_at: record.invoked_at as string,
    unknown_at: record.unknown_at as string,
    error_kind: record.error_kind as string,
    recovery_supported_outcomes: supportedOutcomes,
    recovery_blocked_reason: record.recovery_blocked_reason as string,
    items: strictItems,
    resolution,
  };
}

function normaliseOutcomes(value: unknown): ReconciliationOutcomesResult {
  const record = recordValue(value);
  if (
    !record ||
    !Number.isInteger(record.count) ||
    (record.count as number) < 0 ||
    !Array.isArray(record.outcomes) ||
    record.count !== record.outcomes.length
  ) {
    throw new Error("Reconciliation outcomes response is malformed");
  }
  const outcomes = record.outcomes.map(normaliseOutcome);
  if (
    outcomes.some((outcome) => outcome === null) ||
    new Set(outcomes.map((outcome) => outcome?.attempt_id)).size !==
      outcomes.length
  ) {
    throw new Error("Reconciliation outcomes response is malformed");
  }
  return {
    count: record.count as number,
    outcomes: outcomes as ReconciliationOutcome[],
  };
}

function useAuthenticatedPrincipal(): string | null {
  return useAuthStore((state) => {
    const username = state.username?.trim();
    return state.status === "logged-in" && username ? username : null;
  });
}

export function pendingResolutionStatusFromError(
  error: unknown,
  expectedAttemptId: string,
): ReconciliationPendingStatus | null {
  const status = resolutionStatusFromError(error, expectedAttemptId);
  return status === "PENDING_AUDIT" || status === "PENDING_ROUTER_CLEAR"
    ? status
    : null;
}

export function resolutionStatusFromError(
  error: unknown,
  expectedAttemptId: string,
): ReconciliationResolutionStatus | null {
  return (
    resolutionFromError(error, expectedAttemptId)?.resolution.status ?? null
  );
}

export function resolutionFromError(
  error: unknown,
  expectedAttemptId: string,
): ReconciliationErrorResolution | null {
  if (!(error instanceof FtApiError)) return null;
  const data = recordValue(error.data);
  const attemptId = textValue(data?.attempt_id);
  const resolution = normalisePendingResolution(data?.resolution);
  if (
    !data ||
    !attemptId ||
    attemptId !== expectedAttemptId ||
    !resolution ||
    data.status !== resolution.status ||
    data.resolution_id !== resolution.resolution_id
  )
    return null;
  return { attempt_id: attemptId, resolution };
}

function arraysMatch<T>(left: readonly T[], right: readonly T[]): boolean {
  return (
    left.length === right.length &&
    left.every((value, index) => value === right[index])
  );
}

function resolutionMatchesMutation(
  resolution: ReconciliationPendingResolution,
  variables: ResolveReconciliationOutcomeVariables,
  attempt: ReconciliationOutcome | undefined,
): boolean {
  const body = variables.body;
  const confirmationDecision = {
    confirmed_applied: "APPLIED",
    confirmed_not_applied: "NOT_APPLIED",
    confirmed_partial: "PARTIAL",
  }[body.outcome];
  const expectedConfirmation = `CONFIRM ${confirmationDecision} ${body.broker}:${body.account_id}:${variables.attemptId}`;
  return Boolean(
    attempt &&
    attempt.attempt_id === variables.attemptId &&
    attempt.adapter_id === body.broker &&
    attempt.account_id === body.account_id &&
    attempt.business_date === body.business_date &&
    body.confirmation === expectedConfirmation &&
    resolution.outcome === body.outcome &&
    attempt.recovery_supported_outcomes.includes(resolution.outcome) &&
    arraysMatch(resolution.broker_order_ids, body.broker_order_ids) &&
    arraysMatch(
      resolution.broker_order_item_indexes,
      body.broker_order_item_indexes,
    ) &&
    arraysMatch(
      resolution.not_applied_item_indexes,
      body.not_applied_item_indexes,
    ) &&
    resolution.note === body.note &&
    resolutionEvidenceIsValid(attempt.operation, attempt.items, resolution),
  );
}

function mutationResolutionFromError(
  error: unknown,
  variables: ResolveReconciliationOutcomeVariables,
  attempt: ReconciliationOutcome | undefined,
): ReconciliationErrorResolution | null {
  const errorResolution = resolutionFromError(error, variables.attemptId);
  return errorResolution &&
    resolutionMatchesMutation(errorResolution.resolution, variables, attempt)
    ? errorResolution
    : null;
}

function isCurrentAuthSession(principal: string, generation: number): boolean {
  const state = useAuthStore.getState();
  return (
    state.status === "logged-in" &&
    state.username?.trim() === principal &&
    state.sessionGeneration === generation
  );
}

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

export const reconciliationKeys = {
  all: ["reconciliation"] as const,
  principal: (principal: string) =>
    [...reconciliationKeys.all, "principal", principal] as const,
  status: (principal: string) =>
    [...reconciliationKeys.principal(principal), "status"] as const,
  outcomes: (principal: string) =>
    [...reconciliationKeys.principal(principal), "outcomes"] as const,
  reportsRoot: (principal: string) =>
    [...reconciliationKeys.principal(principal), "reports"] as const,
  reports: (
    principal: string,
    broker: string,
    accountId: string,
    limit: number,
  ) =>
    [
      ...reconciliationKeys.reportsRoot(principal),
      broker,
      accountId,
      limit,
    ] as const,
};

// ---------------------------------------------------------------------------
// Typed client
// ---------------------------------------------------------------------------

export const getReconciliationStatus =
  async (): Promise<ReconciliationStatus> =>
    normaliseStatus(await get<unknown>("reconciliation/status"));

export const getReconciliationReports = async (
  broker: string,
  accountId: string,
  limit = 5,
): Promise<ReconciliationReport[]> => {
  const params = new URLSearchParams({
    broker,
    account_id: accountId,
    limit: String(limit),
  });
  const data = await get<unknown>(
    `reconciliation/reports?${params.toString()}`,
  );
  const reports = recordValue(data)?.reports;
  if (!Array.isArray(reports)) {
    throw new Error("Reconciliation reports response is malformed.");
  }
  const normalised = reports.map((report) =>
    normaliseReport(report, broker, accountId),
  );
  if (normalised.some((report) => report === null)) {
    throw new Error("Reconciliation report evidence is malformed.");
  }
  return normalised as ReconciliationReport[];
};

export const runReconciliation = async (): Promise<ReconciliationRunResult> => {
  const value = await post<unknown>("reconciliation/run");
  const record = recordValue(value);
  if (
    !record ||
    !Number.isInteger(record.count) ||
    (record.count as number) < 0
  ) {
    throw new Error("Reconciliation run response is malformed.");
  }
  if (!Array.isArray(record.reports)) {
    throw new Error("Reconciliation run reports are malformed.");
  }
  const reports = record.reports.map((report) =>
    normaliseReport(report, "", ""),
  );
  if (
    reports.some((report) => report === null) ||
    reports.length !== record.count
  ) {
    throw new Error("Reconciliation run report evidence is malformed.");
  }
  return {
    count: record.count as number,
    reports: reports as ReconciliationReport[],
  };
};

export const getReconciliationOutcomes =
  async (): Promise<ReconciliationOutcomesResult> =>
    normaliseOutcomes(await get<unknown>("reconciliation/outcomes"));

function normaliseResolveReconciliationOutcomeResult(
  value: unknown,
  expectedAttemptId: string,
  expectedOutcome: ReconciliationResolutionOutcome,
): ResolveReconciliationOutcomeResult {
  const record = recordValue(value);
  const remainingOutcomes = record?.remaining_outcomes;
  if (
    !record ||
    !textValue(record.resolution_id) ||
    record.attempt_id !== expectedAttemptId ||
    record.outcome !== expectedOutcome ||
    record.status !== "COMMITTED" ||
    typeof record.evidence_digest !== "string" ||
    record.evidence_digest.length === 0 ||
    typeof record.router_fault_cleared !== "boolean" ||
    typeof record.writes_unblocked !== "boolean" ||
    !(
      remainingOutcomes === null ||
      (Number.isInteger(remainingOutcomes) &&
        (remainingOutcomes as number) >= 0)
    ) ||
    (record.writes_unblocked &&
      typeof remainingOutcomes === "number" &&
      remainingOutcomes > 0)
  ) {
    throw new Error("Outcome resolution response is malformed.");
  }
  return {
    resolution_id: record.resolution_id as string,
    attempt_id: expectedAttemptId,
    outcome: expectedOutcome,
    status: "COMMITTED",
    evidence_digest: record.evidence_digest,
    router_fault_cleared: record.router_fault_cleared,
    writes_unblocked: record.writes_unblocked,
    remaining_outcomes: remainingOutcomes as number | null,
  };
}

export const resolveReconciliationOutcome = async (
  attemptId: string,
  body: ResolveReconciliationOutcomeBody,
): Promise<ResolveReconciliationOutcomeResult> => {
  const value = await post<unknown>(
    `reconciliation/outcomes/${encodeURIComponent(attemptId)}/resolve`,
    body,
  );
  return normaliseResolveReconciliationOutcomeResult(
    value,
    attemptId,
    body.outcome,
  );
};

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

/** Per-target reconciliation status, refreshed on a slow observability poll. */
export function useReconciliationStatus() {
  const principal = useAuthenticatedPrincipal();
  const queryPrincipal = principal ?? UNAUTHENTICATED_PRINCIPAL;
  return useQuery<ReconciliationStatus>({
    queryKey: reconciliationKeys.status(queryPrincipal),
    queryFn: getReconciliationStatus,
    enabled: principal !== null,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}

/** Unresolved broker outcomes, polled alongside the reconciliation status. */
export function useReconciliationOutcomes() {
  const principal = useAuthenticatedPrincipal();
  const queryPrincipal = principal ?? UNAUTHENTICATED_PRINCIPAL;
  return useQuery<ReconciliationOutcomesResult>({
    queryKey: reconciliationKeys.outcomes(queryPrincipal),
    queryFn: getReconciliationOutcomes,
    enabled: principal !== null,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}

/**
 * Last `limit` persisted reports for one broker account (newest first).
 *
 * `enabled` lets callers fetch lazily — e.g. only once a status row is
 * expanded — so collapsed rows cost nothing.
 */
export function useReconciliationReports(
  broker: string,
  accountId: string,
  limit = 5,
  enabled = true,
) {
  const principal = useAuthenticatedPrincipal();
  const queryPrincipal = principal ?? UNAUTHENTICATED_PRINCIPAL;
  return useQuery<ReconciliationReport[]>({
    queryKey: reconciliationKeys.reports(
      queryPrincipal,
      broker,
      accountId,
      limit,
    ),
    queryFn: () => getReconciliationReports(broker, accountId, limit),
    enabled:
      principal !== null &&
      enabled &&
      broker.length > 0 &&
      accountId.length > 0,
    staleTime: 15_000,
  });
}

/**
 * Operator-triggered `run_once()` cycle. On success every reconciliation
 * query (status + reports) is invalidated so the table reflects the fresh
 * JSONL lines immediately.
 */
export function useRunReconciliation() {
  const queryClient = useQueryClient();
  const principal = useAuthenticatedPrincipal();
  const queryPrincipal = principal ?? UNAUTHENTICATED_PRINCIPAL;
  const sessionGeneration = useAuthStore((state) => state.sessionGeneration);
  return useMutation<
    ReconciliationRunResult,
    Error,
    void,
    { principal: string; generation: number }
  >({
    mutationFn: runReconciliation,
    onMutate: () => ({
      principal: queryPrincipal,
      generation: sessionGeneration,
    }),
    onSuccess: (_result, _variables, context) => {
      if (
        !context ||
        !isCurrentAuthSession(context.principal, context.generation)
      )
        return;
      void queryClient.invalidateQueries({
        queryKey: reconciliationKeys.principal(context.principal),
      });
    },
  });
}

/** Record one broker-verified outcome; this never dispatches a broker write. */
export function useResolveReconciliationOutcome(
  callbacks: ResolveReconciliationOutcomeCallbacks = {},
) {
  const queryClient = useQueryClient();
  const principal = useAuthenticatedPrincipal();
  const queryPrincipal = principal ?? UNAUTHENTICATED_PRINCIPAL;
  const sessionGeneration = useAuthStore((state) => state.sessionGeneration);
  return useMutation<
    ResolveReconciliationOutcomeResult,
    Error,
    ResolveReconciliationOutcomeVariables,
    { principal: string; generation: number }
  >({
    mutationFn: ({ attemptId, body }) =>
      resolveReconciliationOutcome(attemptId, body),
    onMutate: () => ({
      principal: queryPrincipal,
      generation: sessionGeneration,
    }),
    onSuccess: (result, variables, context) => {
      if (
        !context ||
        !isCurrentAuthSession(context.principal, context.generation)
      )
        return;
      callbacks.onSuccess?.(result, variables);
    },
    onError: (error, variables, context) => {
      if (
        !context ||
        !isCurrentAuthSession(context.principal, context.generation)
      )
        return;
      const outcomesKey = reconciliationKeys.outcomes(context.principal);
      const cachedOutcomes =
        queryClient.getQueryData<ReconciliationOutcomesResult>(outcomesKey);
      const cachedAttempt = cachedOutcomes?.outcomes.find(
        (outcome) => outcome.attempt_id === variables.attemptId,
      );
      const errorResolution = mutationResolutionFromError(
        error,
        variables,
        cachedAttempt,
      );
      // Hook-level effects survive observer unmount; run them before changing query identity.
      callbacks.onError?.(error, variables, errorResolution);
      if (errorResolution?.resolution.status === "COMMITTED") {
        queryClient.setQueryData<ReconciliationOutcomesResult>(
          outcomesKey,
          (current) => {
            if (!current) return current;
            const currentAttempt = current.outcomes.find(
              (outcome) => outcome.attempt_id === variables.attemptId,
            );
            if (
              !resolutionMatchesMutation(
                errorResolution.resolution,
                variables,
                currentAttempt,
              )
            ) {
              return current;
            }
            const outcomes = current.outcomes.filter(
              (outcome) => outcome.attempt_id !== variables.attemptId,
            );
            return { ...current, count: outcomes.length, outcomes };
          },
        );
        return;
      }
      const pendingResolution = errorResolution?.resolution ?? null;
      if (!pendingResolution) return;
      queryClient.setQueryData<ReconciliationOutcomesResult>(
        outcomesKey,
        (current) => {
          if (!current) return current;
          const currentAttempt = current.outcomes.find(
            (outcome) => outcome.attempt_id === variables.attemptId,
          );
          if (
            !resolutionMatchesMutation(
              pendingResolution,
              variables,
              currentAttempt,
            )
          ) {
            return current;
          }
          let changed = false;
          const outcomes = current.outcomes.map((outcome) => {
            if (outcome.attempt_id !== variables.attemptId) return outcome;
            changed = true;
            return { ...outcome, resolution: pendingResolution };
          });
          return changed ? { ...current, outcomes } : current;
        },
      );
    },
    onSettled: (_data, _error, _variables, context) => {
      if (
        !context ||
        !isCurrentAuthSession(context.principal, context.generation)
      )
        return;
      return queryClient.invalidateQueries({
        queryKey: reconciliationKeys.principal(context.principal),
      });
    },
  });
}
