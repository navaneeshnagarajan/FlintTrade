import { useLayoutEffect, useRef, useSyncExternalStore } from "react";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { captureOperatorIncidentScope, isOperatorIncidentScopeCurrent } from "@/lib/operatorIncidentScope";
import { captureAuthSessionFence, isAuthSessionFenceCurrent, useAuthStore } from "@/stores/authStore";

/** Presentation custody only. Activity detach and observed A→B→A retire pending
 * results; neither a returned receipt nor a new mount revives their owner. */
function scopeGeneration() { return captureOperatorIncidentScope().generation; }
function subscribeScope(notify: () => void) {
  let observed = scopeGeneration();
  const changed = () => {
    const next = scopeGeneration();
    if (next !== observed) { observed = next; notify(); }
  };
  const stops = [useBrokerStore.subscribe(changed), useAuthStore.subscribe(changed), useModeStore.subscribe(changed), useConnectionStore.subscribe(changed)];
  return () => { stops.forEach(stop => stop()); };
}
export function useAccountResultFence() {
  useSyncExternalStore(subscribeScope, scopeGeneration, scopeGeneration);
  const owner = useRef({ generation: 0 });
  useLayoutEffect(() => {
    const current = owner.current;
    current.generation++;
    return () => { current.generation++; };
  }, []);
  return () => {
    const current = owner.current;
    const view = current.generation;
    const scope = captureOperatorIncidentScope();
    const auth = captureAuthSessionFence();
    return () => view === current.generation && isOperatorIncidentScopeCurrent(scope) && isAuthSessionFenceCurrent(auth);
  };
}
