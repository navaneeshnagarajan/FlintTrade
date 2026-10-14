import { useCallback, useSyncExternalStore } from "react";
import { z } from "zod";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { captureOperatorIncidentScope } from "@/lib/operatorIncidentScope";

// Observe the existing run-status owner; do not acquire another agent session.
// This is a client retirement fence, never server account/run authority.
const runs = new WeakMap<QueryClient, { identity: string; generation: number }>();
function runIdentity(client: QueryClient) {
  return JSON.stringify(client.getQueryCache().findAll({ queryKey: ["aiAgent"] })
    .filter(query => query.queryKey[2] === "status")
    .map(query => {
      const data = query.state.data;
      const value = data && typeof data === "object" ? data as Record<string, unknown> : {};
      return [query.queryHash, value.run_id ?? null, value.started_at ?? null, value.mode ?? null,
        value.actor_id ?? null, query.state.status, query.state.isInvalidated];
    }).sort((a, b) => String(a[0]).localeCompare(String(b[0]))));
}
export function knowledgeLocalScopeKey(client: QueryClient): string {
  const local = captureOperatorIncidentScope();
  let run = runs.get(client);
  if (!run) {
    run = { identity: runIdentity(client), generation: 0 };
    runs.set(client, run);
    const owned = run;
    client.getQueryCache().subscribe(() => {
      const next = runIdentity(client);
      if (next !== owned.identity) { owned.identity = next; owned.generation++; }
    });
  }
  return JSON.stringify([local.generation, local.account, local.authGeneration, local.mode, run.generation, run.identity]);
}
export const authoritativeKnowledgeScopeSchema = z.strictObject({
  account_id: z.string().min(1).max(256), environment: z.enum(["paper", "live", "research"]),
  run_id: z.string().min(1).max(256),
}).nullable();
export type AuthoritativeKnowledgeScope = z.infer<typeof authoritativeKnowledgeScopeSchema>;
export function sameKnowledgeScope(a: AuthoritativeKnowledgeScope, b: AuthoritativeKnowledgeScope) {
  return a === null || b === null ? a === b
    : a.account_id === b.account_id && a.environment === b.environment && a.run_id === b.run_id;
}
type Observation = { local: string; scope: AuthoritativeKnowledgeScope | undefined; generation: number; listeners: Set<() => void> };
const observations = new WeakMap<QueryClient, Observation>();
function observation(client: QueryClient) {
  const local = knowledgeLocalScopeKey(client);
  let value = observations.get(client);
  if (!value) {
    value = { local, scope: undefined, generation: 0, listeners: new Set() };
    observations.set(client, value);
  } else if (value.local !== local) {
    value.local = local; value.scope = undefined; value.generation++;
  }
  return value;
}
export function knowledgeScopeKey(client: QueryClient): string {
  const value = observation(client);
  return JSON.stringify([value.local, value.generation, value.scope === undefined ? "unobserved" : value.scope]);
}
export function observeKnowledgeScope(client: QueryClient, scope: AuthoritativeKnowledgeScope) {
  const value = observation(client);
  if (value.scope === undefined || !sameKnowledgeScope(value.scope, scope)) {
    if (value.scope !== undefined) value.generation++;
    value.scope = scope;
    value.listeners.forEach(notify => notify());
  }
}
/** Initial discovery need not discard a draft; later changes retire its owner. */
export function knowledgeRetirementKey(client: QueryClient) {
  const value = observation(client);
  return JSON.stringify([value.local, value.generation]);
}
export interface KnowledgeBinding {
  scope: AuthoritativeKnowledgeScope;
  isCurrent?: () => boolean;
  observe?: (scope: AuthoritativeKnowledgeScope) => void;
}
export function captureKnowledgeBinding(client: QueryClient): KnowledgeBinding {
  const key = knowledgeScopeKey(client);
  const scope = observation(client).scope;
  if (scope === undefined) throw new Error("Authoritative knowledge scope unavailable; refresh the catalogue");
  return { scope, isCurrent: () => key === knowledgeScopeKey(client),
    observe: next => { if (key === knowledgeScopeKey(client)) observeKnowledgeScope(client, next); } };
}
export function useKnowledgeScope() {
  const client = useQueryClient();
  const subscribe = useCallback((notify: () => void) => {
    const listeners = observation(client).listeners;
    listeners.add(notify);
    const unsubs = [useAuthStore.subscribe(notify), useBrokerStore.subscribe(notify),
      useModeStore.subscribe(notify), useConnectionStore.subscribe(notify), client.getQueryCache().subscribe(event => {
        // Query construction/observer events happen during sibling renders.
        // Only the run owner can change this snapshot; never forward unrelated
        // knowledge/selection cache events into React's synchronous subscriber.
        // Run data updates retain synchronous commit/send fences. Structural
        // add/observer events can originate in render, so notify React later;
        // the run observer above still advances every incarnation immediately.
        if (event.query.queryKey[0] === "aiAgent" && event.query.queryKey[2] === "status") {
          if (event.type === "updated") notify();
          else queueMicrotask(() => { if (listeners.has(notify)) notify(); });
        }
      })];
    return () => { listeners.delete(notify); unsubs.forEach(unsubscribe => unsubscribe()); };
  }, [client]);
  const snapshot = useCallback(() => knowledgeScopeKey(client), [client]);
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}
