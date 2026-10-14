import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import { createRunPolicyClient, type ExactControlSelector, type RunProposal } from "../runPolicy";
import type { RunScope } from "../runPolicyTransport";
import fixtures from "./runPolicy.exact-fixture.json";

const response = (data: unknown) => new Response(JSON.stringify(data));
beforeEach(() => useAuthStore.setState({ status: "logged-in", token: "synthetic-r41", username: "operator", sessionGeneration: 410 }));
afterEach(() => vi.unstubAllGlobals());

it.each(fixtures)("independently verifies real $category HTTP configuration and its immutable identity", async fixture => {
  const scope = fixture.base.scope as RunScope;
  const selector = fixture.selector as ExactControlSelector;
  const proposal = fixture.proposal as RunProposal;
  const base = `/v1/model-runs/${scope.run_id}/configuration`;
  const exact = `${base}/control?${new URLSearchParams(selector)}`;
  const calls: string[] = [];
  const failures: string[] = [];
  let configured = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    const path = url.replace(/^\/ft-api/, ""); calls.push(`${init.method} ${path}`);
    try {
      expect(new Headers(init.headers).has("X-API-Key")).toBe(false);
      if (path === exact && init.method === "GET") return response(configured ? fixture.after : fixture.before);
      if (path === `${base}/preview` && init.method === "POST") {
        expect(JSON.parse(String(init.body))).toEqual(proposal); return response(fixture.preview);
      }
      if (path === `${base}/confirm` && init.method === "POST") {
        expect(JSON.parse(String(init.body))).toEqual({ ...proposal, confirmation: fixture.preview.confirmation });
        configured = true; return response(fixture.confirmed);
      }
      throw new Error("unregistered request");
    } catch (reason) { failures.push(String(reason)); throw reason; }
  }));
  const client = createRunPolicyClient(scope);
  const observed = await client.readControl(selector);
  expect(observed.exact_control.revision).toBe(proposal.expected_revision);
  const preview = await client.preview(proposal);
  const durable = await client.confirm(preview);
  expect(durable.exact_control).toEqual(fixture.after.exact_control);
  expect(calls).toEqual([`GET ${exact}`, `POST ${base}/preview`, `POST ${base}/confirm`, `GET ${exact}`]);
  expect(failures).toEqual([]);
  expect(JSON.stringify(durable)).not.toContain('Synthetic reviewed bytes only');
  client.dispose();
});

it.each(fixtures.flatMap(fixture => ["scope", "missing", "malformed", "revision", "value", "identity", "lost-ack", "malformed-ack"].map(fault => ({ fixture, fault, category: fixture.category }))))("keeps $category $fault outcome unknown with one GET and no resend", async ({ fixture, fault }) => {
  const scope = fixture.base.scope as RunScope;
  const proposal = fixture.proposal as RunProposal;
  const base = `/v1/model-runs/${scope.run_id}/configuration`;
  const exact = `${base}/control?${new URLSearchParams(fixture.selector as ExactControlSelector)}`;
  const changed: Record<string, unknown> = structuredClone(fixture.after);
  const snapshot = changed.exact_control as Record<string, unknown>;
  if (fault === "scope") changed.scope = { ...scope, account: "foreign-book" };
  if (fault === "missing") delete changed.exact_control;
  if (fault === "malformed") snapshot.revision = "1";
  if (fault === "revision") snapshot.revision = 2;
  if (fault === "value") snapshot.value = null;
  if (fault === "identity") snapshot.identity = { ...snapshot.identity as object, manifest_digest: "a".repeat(64), event_id: "foreign-event" };
  const calls: string[] = []; const failures: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    const path = url.replace(/^\/ft-api/, ""); calls.push(`${init.method} ${path}`);
    if (path === `${base}/preview` && init.method === "POST") return response(fixture.preview);
    if (path === `${base}/confirm` && init.method === "POST") {
      if (fault === "lost-ack") throw new Error("synthetic lost acknowledgement");
      return response(fault === "malformed-ack" ? { ...fixture.confirmed, exact_control: {} } : fixture.confirmed);
    }
    if (path === exact && init.method === "GET") return response(changed);
    failures.push(path); throw new Error("unregistered request");
  }));
  const client = createRunPolicyClient(scope); const view = await client.preview(proposal);
  await expect(client.confirm(view)).rejects.toMatchObject({ outcome: "unknown" });
  await expect(client.preview(proposal)).rejects.toThrow(/read/i);
  await expect(client.confirm(view)).rejects.toThrow(/consumed|cancelled/i);
  expect(calls).toEqual([`POST ${base}/preview`, `POST ${base}/confirm`, `GET ${exact}`]);
  expect(failures).toEqual([]); client.dispose();
});

it.each(fixtures.filter(fixture => !fixture.category.startsWith("rights-")))("refuses $category preview when immutable identity changed after the displayed read", async fixture => {
  const client = createRunPolicyClient(fixture.base.scope as RunScope);
  const identity = { ...fixture.preview.target_identity, ...(fixture.category === "training-backend" ? { connection_revision: '"changed"' } : { manifest_digest: "f".repeat(64) }) };
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.includes("/control?") ? response(fixture.before) : response({ ...fixture.preview, target_identity: identity })));
  await client.readControl(fixture.selector as ExactControlSelector);
  await expect(client.preview(fixture.proposal)).rejects.toThrow(/changed|identity/i);
  expect(fetch).toHaveBeenCalledTimes(2);
});

it("never retains private material from a malformed acknowledgement when readback is unavailable", async () => {
  const fixture = fixtures[0];
  const client = createRunPolicyClient(fixture.base.scope as RunScope);
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/preview") ? response(fixture.preview)
    : url.endsWith("/confirm") ? response({ ...fixture.confirmed, exact_control: undefined, result: { event_id: "event-safe", documents: { private: "PRIVATE-ACK-DOCUMENT" }, endpoint: "https://example.invalid/?token=PRIVATE-TOKEN" } })
      : response({})));
  const view = await client.preview(fixture.proposal);
  const failure = await client.confirm(view).catch(reason => reason);
  expect(failure.outcome).toBe("unknown");
  expect(failure.result).toEqual({ event_id: "event-safe" });
});

it("cancels a held exact read instead of publishing its late observation", async () => {
  const fixture = fixtures[0]; const client = createRunPolicyClient(fixture.base.scope as RunScope);
  let release!: (value: Response) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(resolve => { release = resolve; })));
  const read = client.readControl(fixture.selector as ExactControlSelector);
  const rejected = expect(read).rejects.toThrow(/cancelled|retired/i);
  client.cancel(); release(response(fixture.after)); await rejected;
  expect(fetch).toHaveBeenCalledTimes(1);
});
