import { z } from "zod";
import { onlineManager } from "@tanstack/react-query";
import { useConnectionStore } from "@/stores/connectionStore";
import { captureAuthSessionFence, isAuthSessionFenceCurrent, useAuthStore } from "@/stores/authStore";
import { buildHeaders, getBase, isDemoAuthSession } from "./ftApi.helpers";

export const runScopeSchema = z.strictObject({ run_id: z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/), actor: z.string().min(1), account: z.string().min(1), environment: z.enum(["paper", "live"]) });
export type RunScope = z.infer<typeof runScopeSchema>;
let authorityGeneration = 0;
let observing = false;
const listeners = new Set<() => void>();
function observeAuthority() {
  if (observing) return;
  observing = true;
  const advance = () => { authorityGeneration++; listeners.forEach(notify => notify()); };
  useAuthStore.subscribe((next, previous) => { if (next.token !== previous.token || next.status !== previous.status || next.username !== previous.username || next.sessionGeneration !== previous.sessionGeneration) advance(); });
  useConnectionStore.subscribe((next, previous) => { if (next.status !== previous.status || next.apiKey !== previous.apiKey) advance(); });
  onlineManager.subscribe(advance);
}
// Observed connection/session retirement only. Terminal account/mode selection
// is deliberately excluded; exact run authority is always rechecked by core.
export function runPolicyAuthorityKey() { observeAuthority(); return authorityGeneration; }
export function subscribeRunPolicyAuthority(notify: () => void) { observeAuthority(); listeners.add(notify); return () => { listeners.delete(notify); }; }
export class RunPolicyError extends Error {
  constructor(readonly outcome: "retired" | "refused" | "unknown" | "unavailable", message: string) { super(message); }
}
export function sameRunScope(a: RunScope, b: RunScope) {
  return a.run_id === b.run_id && a.actor === b.actor && a.account === b.account && a.environment === b.environment;
}
export function canonicalPolicy(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonicalPolicy).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${canonicalPolicy(item)}`).join(",")}}`;
  return JSON.stringify(value);
}
/** A visible operator/run lifetime; disposal never controls backend execution. */
export function createRunPolicyTransport(scope: RunScope) {
  scope = runScopeSchema.parse(scope);
  const fence = captureAuthSessionFence();
  const token = useAuthStore.getState().token;
  const generation = runPolicyAuthorityKey();
  const abort = new AbortController();
  let disposed = false;
  const assertCurrent = () => {
    if (disposed || generation !== runPolicyAuthorityKey() || !isAuthSessionFenceCurrent(fence) || useAuthStore.getState().token !== token) throw new RunPolicyError("retired", "Run policy belongs to a retired operator or view. Read again.");
    if (!onlineManager.isOnline()) throw new RunPolicyError("unavailable", "Connection unavailable. Read exact policy after reconnection.");
    if (useAuthStore.getState().status !== "logged-in" || !useAuthStore.getState().token || isDemoAuthSession()) throw new RunPolicyError("refused", "An installed operator session is required.");
  };
  async function request(path: string, body?: unknown): Promise<unknown> {
    assertCurrent();
    const headers = buildHeaders(body !== undefined); delete headers["X-API-Key"];
    let response: Response;
    let raw: unknown;
    try {
      response = await fetch(`${getBase()}${path}`, { method: body === undefined ? "GET" : "POST", headers, cache: "no-store", redirect: "error", signal: abort.signal, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
      raw = await response.json();
    } catch {
      assertCurrent();
      throw new RunPolicyError(body === undefined ? "unavailable" : "unknown", "Outcome unavailable. Read exact policy; do not resend.");
    }
    assertCurrent();
    // Do not echo supplied documents, confirmation tokens or remote error text.
    if (!response.ok) throw new RunPolicyError(response.status >= 500 && body !== undefined ? "unknown" : "refused", response.status === 409 ? "Revision or confirmation conflict. Read again and explicitly review a new proposal." : `Policy unavailable or refused (${response.status}). Read exact policy before continuing.`);
    return raw;
  }
  return { request, assertCurrent, dispose: () => { disposed = true; abort.abort(); }, scope };
}
