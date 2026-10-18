import { expect, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import { useConnectionStore } from "@/stores/connectionStore";

export const NAME = "session-lessons-2026-07-19";
export const VERSION = "candidate:" + "a".repeat(64);
export const HASH = "b".repeat(64);
export const SCOPE = { account_id: "native:dhan:account-a", environment: "paper" as const, run_id: "server-run-a" };
export const BODY = "  Complete procedure\n\nFinal required protection step.\n";
export function row(overrides: Record<string, unknown> = {}) {
  return { name: NAME, version_id: VERSION, package_hash: HASH, origin: "learned", state: "default", enabled: true, default: true, validated: true, run_pinned: false, unavailable_reason: null, ...overrides };
}
export function procedure(overrides: Record<string, unknown> = {}) {
  return { scope: SCOPE, reference: `skill:${NAME}`, version: VERSION, body: BODY, classification: "private", receipt: "context-receipt", ...overrides };
}
export function seedKnowledgeSession() {
  useAuthStore.setState({ status: "logged-in", token: "synthetic-knowledge", username: "knowledge-test", sessionGeneration: 10 });
  useBrokerStore.setState({ activeAccountId: "native:dhan:account-a" });
  useModeStore.setState({ mode: "practice" });
  useConnectionStore.setState({ apiKey: "" });
}
export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(r => { resolve = r; });
  return { promise, resolve };
}
export function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}
export function knowledgeTransport() {
  const routes = new Map<string, (init: RequestInit) => Response | Promise<Response>>();
  const failures: unknown[] = [];
  const requests: { path: string; init: RequestInit }[] = [];
  const fetch = vi.fn(async (path: string, init: RequestInit = {}) => {
    requests.push({ path, init });
    try {
      expect(new Headers(init.headers).get("Authorization")).toBe(`Bearer ${useAuthStore.getState().token}`);
      expect(init.cache).toBe("no-store");
      const handler = routes.get(`${init.method ?? "GET"} ${path}`);
      if (!handler) throw new Error(`Unregistered knowledge request: ${init.method} ${path}`);
      return await handler(init);
    } catch (error) { failures.push(error); throw error; }
  });
  vi.stubGlobal("fetch", fetch);
  return { routes, requests, fetch, assertClean: () => expect(failures).toEqual([]) };
}
