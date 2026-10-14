/**
 * FlintTrade Python backend REST API client — barrel re-export.
 * All logic lives in domain-specific modules. Import from here to avoid
 * breaking any existing imports.
 */

import { runBacktest as legacyBacktest, type BacktestConfig as LegacyBacktestConfig, type BacktestResult } from "./ftApi.backtest";
import { buildHeaders, getBase, isDemoAuthSession, parseResponse, FtApiError } from "./ftApi.helpers";
import { captureBacktestReceipt, evaluationScopeKey, retainBacktestResultReceipt } from "./backtestReceipt";
import { BacktestRunSelector, HistoryBacktestRequest, assertBacktestResult, throwBacktestHttpError, EvaluationActionError } from "./evaluationActions";
import { useAuthStore } from "@/stores/authStore";

import { captureOperatorIncidentScope } from "@/lib/operatorIncidentScope";

export type BacktestConfig = LegacyBacktestConfig & { data_manifest_id?: string; run_id?: string };
/** Preserve the existing result while retaining immutable headers at its real caller. */
export async function runBacktest(config: BacktestConfig): Promise<BacktestResult> {
  if ("run_id" in config) {
    BacktestRunSelector.parse(config.run_id);
    if (isDemoAuthSession()) throw new Error("Registered-run backtests are unavailable in the preview; the selector cannot label a simulated result.");
    if (useAuthStore.getState().status !== "logged-in" || !useAuthStore.getState().token) throw new Error("An installed full operator session is required for a registered-run backtest.");
  }
  if ("data_manifest_id" in config) {
    HistoryBacktestRequest.parse(config);
    if (isDemoAuthSession()) throw new Error("Immutable history is unavailable in the preview; no data substitution is permitted.");
  }
  if (isDemoAuthSession()) return legacyBacktest(config);
  const scope = evaluationScopeKey();
  const incidentScope = captureOperatorIncidentScope();
  const frozen = { ...config };
  const headers = buildHeaders(true);
  // Only the optional run-control path requires the exclusive operator bearer.
  // Preserve the pre-existing unscoped headers and all current-scope fences.
  if ("run_id" in frozen) delete headers["X-API-Key"];
  try {
    const response = await fetch(`${getBase()}/api/v1/backtest/run`, {
      method: "POST", headers, body: JSON.stringify(frozen),
    });
    if (scope !== evaluationScopeKey()) throw new Error("Execution scope retired; backtest outcome belongs to its original session.");
    const receipt = captureBacktestReceipt(scope, response, frozen.strategy, frozen.data_manifest_id, frozen.run_id);
    if (!response.ok) await throwBacktestHttpError(response, incidentScope);
    const result = await parseResponse<unknown>(response, "backtest/run");
    if (scope !== evaluationScopeKey()) throw new Error("Execution scope retired; backtest outcome belongs to its original session.");
    assertBacktestResult(result);
    retainBacktestResultReceipt(scope, result, receipt);
    return result;
  } catch (error) {
    if (scope !== evaluationScopeKey()) throw new Error("Execution scope retired; backtest outcome belongs to its original session.");
    if (error instanceof FtApiError || error instanceof EvaluationActionError) throw error;
    throw new EvaluationActionError("unknown", "Backtest transport or JSON unavailable. Read returned immutable references where available; no automatic resend.");
  }
}

export * from "./ftApi.helpers";
export * from "./ftApi.screener";
export * from "./ftApi.backtest";
export * from "./ftApi.ai";
export * from "./ftApi.automation";
export * from "./ftApi.trading";
export * from "./ftApi.analysis";
export * from "./ftApi.data";
export * from "./ftApi.journal";
export * from "./ftApi.admin";
export * from "./ftApi.invest";
export * from "./ftApi.workspace";
export * from "./ftApi.localAi";
