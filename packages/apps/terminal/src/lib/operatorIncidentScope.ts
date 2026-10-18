import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import { useConnectionStore } from "@/stores/connectionStore";
const errors = new WeakMap<Error, OperatorIncidentScope>();
export function scopedIncidentError(error: unknown, scope: OperatorIncidentScope): Error {
  const value = error instanceof Error ? error : new Error(String(error));
  errors.set(value, scope); return value;
}
export function incidentScopeForError(error: Error): OperatorIncidentScope | undefined { return errors.get(error); }
let generation = 0;
let observing = false;
export interface OperatorIncidentScope { readonly generation: number; readonly account: string | null; readonly authGeneration: number; readonly mode: string }
/** One diagnostic-generation observer, not a trading authority or acquisition owner. */
export function captureOperatorIncidentScope(account?: string): OperatorIncidentScope {
  if (!observing) {
    observing = true;
    useBrokerStore.subscribe?.((next, previous) => { if (next.activeAccountId !== previous.activeAccountId) generation++; });
    useAuthStore.subscribe?.((next, previous) => { if (next.sessionGeneration !== previous.sessionGeneration || next.status !== previous.status || next.token !== previous.token || next.username !== previous.username) generation++; });
    useModeStore.subscribe?.((next, previous) => { if (next.mode !== previous.mode) generation++; });
    useConnectionStore.subscribe?.((next, previous) => { if (next.apiKey !== previous.apiKey) generation++; });
  }
  return { generation, account: account ?? useBrokerStore.getState().activeAccountId, authGeneration: useAuthStore.getState().sessionGeneration, mode: useModeStore.getState().mode };
}
export function isOperatorIncidentScopeCurrent(scope: OperatorIncidentScope): boolean {
  const current = captureOperatorIncidentScope();
  return scope.generation === current.generation && scope.account === current.account && scope.authGeneration === current.authGeneration && scope.mode === current.mode;
}
