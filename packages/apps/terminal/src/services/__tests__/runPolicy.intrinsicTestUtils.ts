import { expect, vi } from "vitest";
import type { ExactControlSelector } from "../runPolicy";
import fixtures from "./runPolicy.exact-fixture.json";

export { fixtures };
export type PolicyFixture = typeof fixtures[number];
export interface Contradiction {
  category: string;
  field: string;
  replacement: string;
  fixture: PolicyFixture;
}
const digest = "f".repeat(64);
const mutations: Record<string, Record<string, string>> = {
  "rights-source": { "value.subject": "output", "value.rights_digest": digest, "identity.rights_digest": digest },
  "rights-output": { "value.subject": "source", "value.rights_digest": digest, "identity.rights_digest": digest },
  candidate: {
    "value.candidate": "foreign-trial", "identity.trial": "foreign-trial",
    "value.identity": `provider-reported-revision:${digest}`,
    "identity.serving_identity": `provider-reported-revision:${digest}`,
  },
  evaluation: {
    "value.trial": "foreign-trial", "identity.trial": "foreign-trial", "value.suite": "foreign-suite",
    "value.manifest_digest": digest, "identity.manifest_digest": digest,
    "value.suite_digest": digest, "identity.suite_digest": digest,
  },
  "training-backend": {
    "value.connection_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "identity.connection_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    "value.policy.connection_revision": '"foreign-revision"', "identity.connection_revision": '"foreign-revision"',
  },
};
export const contradictions: Contradiction[] = fixtures.flatMap(fixture =>
  Object.entries(mutations[fixture.category] ?? {}).map(([field, replacement]) => ({ category: fixture.category, field, replacement, fixture })),
);

// Clone only the wire-negative variant; the real-owner fixture stays untouched.
export function contradict<T extends { exact_control: object }>(envelope: T, fault: Contradiction): T {
  const changed = structuredClone(envelope);
  const keys = fault.field.split(".");
  let target = changed.exact_control as Record<string, unknown>;
  for (const key of keys.slice(0, -1)) target = target[key] as Record<string, unknown>;
  expect(target[keys.at(-1)!]).not.toBe(fault.replacement);
  target[keys.at(-1)!] = fault.replacement;
  return changed;
}
export const response = (data: unknown) => new Response(JSON.stringify(data));
export const transportFailures: string[] = [];
export function registerPolicy(fixture: PolicyFixture, overrides: { base?: unknown; selected?: unknown; ack?: unknown; after?: unknown; preview?: unknown } = {}) {
  const base = `/v1/model-runs/${fixture.base.scope.run_id}/configuration`;
  const exact = `${base}/control?${new URLSearchParams(fixture.selector as ExactControlSelector)}`;
  const calls: string[] = [];
  let configured = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    const path = url.replace(/^\/ft-api/, ""); calls.push(`${init.method} ${path}`);
    try {
      const headers = new Headers(init.headers);
      expect(headers.get("Authorization")).toBe("Bearer synthetic-intrinsic");
      expect(headers.has("X-API-Key")).toBe(false);
      if (init.method === "GET" && path === base) return response(overrides.base ?? fixture.base);
      if (init.method === "GET" && path === exact) return response(configured ? overrides.after ?? fixture.after : overrides.selected ?? fixture.before);
      if (init.method === "POST" && path === `${base}/preview`) {
        expect(JSON.parse(String(init.body))).toEqual(fixture.proposal);
        return response(overrides.preview ?? fixture.preview);
      }
      if (init.method === "POST" && path === `${base}/confirm`) {
        expect(JSON.parse(String(init.body))).toEqual({ ...fixture.proposal, confirmation: fixture.preview.confirmation });
        configured = true;
        return response(overrides.ack ?? fixture.confirmed);
      }
      throw new Error(`Unregistered ${init.method} ${path}`);
    } catch (error) { transportFailures.push(String(error)); throw error; }
  }));
  return { calls, base, exact };
}
