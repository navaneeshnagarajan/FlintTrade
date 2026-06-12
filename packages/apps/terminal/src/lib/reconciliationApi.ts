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
import { get, post } from "@/services/ftApi.helpers";

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
  severity: string;
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
  severity: string;
}

export interface ReconciliationHoldingDiff {
  symbol: string;
  exchange: string;
  flinttrade_qty: number;
  broker_qty: number;
  discrepancy: string;
  severity: string;
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
  severity: string;
  severity_counts: ReconciliationSeverityCounts;
}

/** One row of GET /reconciliation/status — the latest report per target. */
export interface ReconciliationTargetStatus {
  broker: string;
  account_id: string;
  last_report_at: string;
  clean: boolean;
  severity: string;
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

// ---------------------------------------------------------------------------
// Query keys
// ---------------------------------------------------------------------------

export const reconciliationKeys = {
  all: ["reconciliation"] as const,
  status: () => [...reconciliationKeys.all, "status"] as const,
  reports: (broker: string, accountId: string, limit: number) =>
    [...reconciliationKeys.all, "reports", broker, accountId, limit] as const,
};

// ---------------------------------------------------------------------------
// Typed client
// ---------------------------------------------------------------------------

export const getReconciliationStatus = (): Promise<ReconciliationStatus> =>
  get<ReconciliationStatus>("reconciliation/status");

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
  const data = await get<{ reports: ReconciliationReport[] }>(
    `reconciliation/reports?${params.toString()}`,
  );
  return Array.isArray(data.reports) ? data.reports : [];
};

export const runReconciliation = (): Promise<ReconciliationRunResult> =>
  post<ReconciliationRunResult>("reconciliation/run");

// ---------------------------------------------------------------------------
// Hooks
// ---------------------------------------------------------------------------

/** Per-target reconciliation status, refreshed on a slow observability poll. */
export function useReconciliationStatus() {
  return useQuery<ReconciliationStatus>({
    queryKey: reconciliationKeys.status(),
    queryFn: getReconciliationStatus,
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
  return useQuery<ReconciliationReport[]>({
    queryKey: reconciliationKeys.reports(broker, accountId, limit),
    queryFn: () => getReconciliationReports(broker, accountId, limit),
    enabled: enabled && broker.length > 0 && accountId.length > 0,
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
  return useMutation<ReconciliationRunResult, Error>({
    mutationFn: runReconciliation,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: reconciliationKeys.all });
    },
  });
}
