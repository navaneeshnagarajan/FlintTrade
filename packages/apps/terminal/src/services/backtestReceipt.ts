import { useSyncExternalStore } from "react";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { captureOperatorIncidentScope } from "@/lib/operatorIncidentScope";

/** Local presentation identity only. Core derives its own authority. */
export function evaluationScopeKey(): string {
  return JSON.stringify(captureOperatorIncidentScope());
}
function subscribeScope(notify: () => void) {
  const unsubscribes = [useAuthStore, useBrokerStore, useModeStore, useConnectionStore].map(store => store.subscribe(notify));
  return () => unsubscribes.forEach(unsubscribe => unsubscribe());
}
export function useEvaluationScope() {
  return useSyncExternalStore(subscribeScope, evaluationScopeKey, evaluationScopeKey);
}
export interface BacktestReceipt {
  readonly experimentId: string | null;
  readonly trialId: string | null;
  readonly strategy: string;
  readonly manifestId: string | null;
  /** Submitted selector only; never server-verified control_scope. */
  readonly submittedRunId: string | null;
  readonly httpStatus: number;
  readonly reason: string;
}
const empty: readonly BacktestReceipt[] = Object.freeze([]);
const receipts = new Map<string, readonly BacktestReceipt[]>();
const listeners = new Set<() => void>();
function subscribe(notify: () => void) { listeners.add(notify); return () => { listeners.delete(notify); }; }
export function captureBacktestReceipt(scope: string, response: Response, strategy: string, manifestId?: string, submittedRunId?: string) {
  if (scope !== evaluationScopeKey()) return;
  const experimentId = response.headers.get("X-Experiment-Id");
  const trialId = response.headers.get("X-Trial-Id");
  const valid = /^[a-f0-9]{32}$/.test(experimentId ?? "") && /^[a-f0-9]{32}$/.test(trialId ?? "");
  const receipt = Object.freeze({ experimentId: valid ? experimentId : null, trialId: valid ? trialId : null,
    strategy, manifestId: manifestId ?? null, submittedRunId: submittedRunId ?? null, httpStatus: response.status,
    reason: valid ? "Immutable references returned by core; normal backtests are not qualification." : "Immutable references unavailable: missing or malformed response headers." });
  receipts.set(scope, Object.freeze([receipt, ...(receipts.get(scope) ?? empty)]));
  listeners.forEach(notify => notify());
  return receipt;
}
const resultReceipts = new WeakMap<object, { scope: string; receipt: BacktestReceipt }>();
export function retainBacktestResultReceipt(scope: string, result: object, receipt: BacktestReceipt | undefined) {
  if (receipt && scope === evaluationScopeKey()) resultReceipts.set(result, { scope, receipt });
}
export function backtestReceiptFor(result: object) {
  const value = resultReceipts.get(result);
  return value?.scope === evaluationScopeKey() ? value.receipt : undefined;
}
export function useBacktestReceipts(scope: string) {
  return useSyncExternalStore(subscribe, () => receipts.get(scope) ?? empty, () => empty);
}
// Private receipt references never survive authentication retirement in memory.
useAuthStore.subscribe((next, previous) => {
  if (next.sessionGeneration !== previous.sessionGeneration || next.status !== previous.status || next.token !== previous.token) {
    receipts.clear(); listeners.forEach(notify => notify());
  }
});
