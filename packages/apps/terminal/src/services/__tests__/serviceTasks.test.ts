import { createHash } from "node:crypto";
import { QueryClient } from "@tanstack/react-query";
import { expect, it, vi, afterEach } from "vitest";
import { dispatchServiceTask, readServiceTask, readServiceConnections, readServiceControl, saveServiceControl } from "../serviceTasks";
import { useBrokerStore } from "@/stores/brokerStore";
import { SCOPE, deferred, seedKnowledgeSession } from "./knowledgeTestUtils";
import { knowledgeScopeKey, observeKnowledgeScope } from "../knowledgeScope";
import { useAuthStore } from "@/stores/authStore";
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const taskId = "ce259288-d560-4fb0-9763-53be0bfaf256";
const taskInput = { request_id: taskId, mode: "automatic" as const, selection: null, prompt: "Explain", classification: "public" as const, context_refs: [], purpose: "assistant" as const, deadline_ms: 3000, max_output_tokens: 100, required_hard_controls: ["output_tokens"] };
const transient = { request_id: taskId, outcome: "completed", code: "ok", output: "Bounded synthetic text", output_digest: createHash("sha256").update(JSON.stringify("Bounded synthetic text")).digest("hex") };
const { output: _output, ...durableReceipt } = transient;
it.each(["auth", "account", "account-return"])("retires a public client's held durable response on %s", async change => {
  seedKnowledgeSession();
  const held = deferred<Response>(); const entered = deferred<void>();
  const io = vi.fn().mockImplementation((_url, init) => {
    if (init.method === "POST") return Promise.resolve(new Response(JSON.stringify(transient)));
    entered.resolve(); return held.promise;
  });
  vi.stubGlobal("fetch", io);
  const pending = dispatchServiceTask(taskInput);
  const rejection = expect(pending).rejects.toThrow(/retired|scope|session/i);
  await entered.promise;
  if (change === "auth") useAuthStore.setState({ sessionGeneration: 11 });
  else {
    useBrokerStore.getState().setActiveAccount("native:dhan:account-b");
    if (change === "account-return") useBrokerStore.getState().setActiveAccount("native:dhan:account-a");
  }
  held.resolve(new Response(JSON.stringify(durableReceipt)));
  await rejection;
  expect(io).toHaveBeenCalledTimes(2);
});
it.each(["missing-post", "missing-get", "raw-text", "wrong", "digest-only-mismatch", "outcome", "code", "identity", "unknown", "lost", "oversize", "durable-plaintext"])("fences %s without retry or returning plaintext", async fault => {
  seedKnowledgeSession();
  const sent: Record<string, unknown> = { ...transient };
  const durable: Record<string, unknown> = { ...durableReceipt };
  if (fault === "missing-post") delete sent.output_digest;
  if (fault === "missing-get") delete durable.output_digest;
  if (fault === "raw-text") sent.output_digest = durable.output_digest = createHash("sha256").update(transient.output).digest("hex");
  if (fault === "wrong") durable.output_digest = "0".repeat(64);
  if (fault === "digest-only-mismatch") { delete sent.output; durable.output_digest = "0".repeat(64); }
  if (fault === "outcome") durable.outcome = "pending";
  if (fault === "code") durable.code = "outcome_unknown";
  if (fault === "identity") durable.request_id = "5a765bd0-48c1-4b8a-8db7-c94633b1abca";
  if (fault === "unknown") durable.accounting = "unknown";
  if (fault === "oversize") sent.output = "x".repeat(1_048_577);
  if (fault === "durable-plaintext") durable.output = "Unverified GET answer";
  const io = vi.fn().mockImplementation((_url, init) => init.method === "GET" && fault === "lost"
    ? Promise.reject(new Error("Lost readback")) : Promise.resolve(new Response(JSON.stringify(init.method === "POST" ? sent : durable))));
  vi.stubGlobal("fetch", io);
  await expect(dispatchServiceTask(taskInput)).rejects.toThrow();
  expect(io.mock.calls.map(([_url, init]) => init.method)).toEqual(["POST", "GET"]);
});
it.each(["auth", "account-return", "server-return"])("cannot reuse a previously verified transient answer in a new %s scope", async change => {
  seedKnowledgeSession();
  const client = new QueryClient(); observeKnowledgeScope(client, SCOPE);
  const scope = knowledgeScopeKey(client);
  const io = vi.fn().mockImplementation((_url, init) => Promise.resolve(new Response(JSON.stringify(init.method === "POST" ? transient : durableReceipt))));
  vi.stubGlobal("fetch", io);
  const verified = await dispatchServiceTask(taskInput, () => scope === knowledgeScopeKey(client));
  if (change === "auth") useAuthStore.setState({ sessionGeneration: 11 });
  else if (change === "server-return") {
    observeKnowledgeScope(client, { ...SCOPE, run_id: "server-b" }); observeKnowledgeScope(client, SCOPE);
  } else {
    useBrokerStore.getState().setActiveAccount("native:dhan:account-b");
    useBrokerStore.getState().setActiveAccount("native:dhan:account-a");
  }
  await expect(readServiceTask(taskId, verified)).rejects.toThrow(/retired|scope|session/i);
  expect(io).toHaveBeenCalledTimes(2);
  client.clear();
});
it.each(["dispatch", "manual"])("fences the actual asynchronous digest continuation during %s", async phase => {
  seedKnowledgeSession();
  const client = new QueryClient(); observeKnowledgeScope(client, SCOPE);
  const scope = knowledgeScopeKey(client);
  const current = () => scope === knowledgeScopeKey(client);
  const io = vi.fn().mockImplementation((_url, init) => Promise.resolve(new Response(JSON.stringify(init.method === "POST" ? transient : durableReceipt))));
  vi.stubGlobal("fetch", io);
  const previous = phase === "manual" ? await dispatchServiceTask(taskInput, current) : undefined;
  const entered = deferred<void>(); const release = deferred<void>();
  const original = crypto.subtle.digest.bind(crypto.subtle);
  vi.spyOn(crypto.subtle, "digest").mockImplementation(async (algorithm, data) => {
    const hash = await original(algorithm, data); entered.resolve(); await release.promise; return hash;
  });
  const pending = phase === "manual" ? readServiceTask(taskId, previous, current) : dispatchServiceTask(taskInput, current);
  const refused = expect(pending).rejects.toThrow(/scope|retired/);
  await entered.promise;
  observeKnowledgeScope(client, { ...SCOPE, run_id: "server-b" }); observeKnowledgeScope(client, SCOPE);
  release.resolve(); await refused;
  expect(io.mock.calls.map(([_url, init]) => init.method)).toEqual(phase === "manual" ? ["POST", "GET", "GET"] : ["POST", "GET"]);
  client.clear();
});
it("keeps a cold digest-only read honest and never recovers text from a previous dispatch", async () => {
  seedKnowledgeSession();
  const io = vi.fn().mockImplementation((_url, init) => Promise.resolve(new Response(JSON.stringify(init.method === "POST" ? transient : durableReceipt))));
  vi.stubGlobal("fetch", io);
  expect(await dispatchServiceTask(taskInput)).toEqual(transient);
  expect(await readServiceTask(taskId)).toEqual(durableReceipt);
  expect(io.mock.calls.map(([_url, init]) => init.method)).toEqual(["POST", "GET", "GET"]);
});
it("reconciles transient POST text with the exact durable canonical-JSON digest", async () => {
  useAuthStore.setState({ status: "logged-in", token: "synthetic-ui-session" });
  const id = "ce259288-d560-4fb0-9763-53be0bfaf256";
  const output = 'Quoted "risk"\\boundary\nनमस्ते 🚦\u007f';
  // Python canonical(...): ensure_ascii=True includes DEL and surrogate pairs.
  const canonical = JSON.stringify(output).replace(/[\u007f-\uffff]/g, char => `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`);
  const durable = { request_id: id, outcome: "completed", code: "ok", output_digest: createHash("sha256").update(canonical).digest("hex") };
  const io = vi.fn().mockImplementation((_url, init) => Promise.resolve(new Response(JSON.stringify(init.method === "POST" ? { ...durable, output } : durable))));
  vi.stubGlobal("fetch", io);
  const task = { request_id: id, mode: "automatic" as const, selection: null, prompt: "Explain", classification: "public" as const, context_refs: [], purpose: "assistant" as const, deadline_ms: 3000, max_output_tokens: 100, required_hard_controls: ["output_tokens"] };
  expect(await dispatchServiceTask(task)).toEqual({ ...durable, output });
  expect(io.mock.calls.map(([url, init]) => `${init.method} ${url}`)).toEqual([
    "POST /ft-api/v1/services/connections/tasks", `GET /ft-api/v1/services/connections/tasks/${id}`,
  ]);
});
it("preserves the real opaque collection tag through the existing reader", async () => {
  useAuthStore.setState({ status: "logged-in", token: "synthetic-ui-session" });
  const tag = `"${"abcdef01".repeat(8)}"`;
  const connection = {
    schema_version: 1, connection_id: "ce259288-d560-4fb0-9763-53be0bfaf256", provider_id: "llm:openai",
    label: "Synthetic connection", model: "explicit-model", endpoint: "https://api.openai.com/v1/chat/completions",
    auth_mode: "api_key", credential_configured: false, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
  };
  const io = vi.fn().mockResolvedValue(new Response(JSON.stringify({ connections: [connection] }), { headers: { ETag: tag } }));
  vi.stubGlobal("fetch", io);
  expect(await readServiceConnections()).toEqual({ connections: [connection], etag: tag });
  expect(io).toHaveBeenCalledTimes(1);
  expect(io.mock.calls[0][0]).toBe("/ft-api/v1/services/connections");
  expect(io.mock.calls[0][1].method).toBe("GET");
});
it("rejects an incomplete collection even when its tag happens to be numeric", async () => {
  useAuthStore.setState({ status: "logged-in", token: "synthetic-ui-session" });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ connections: [
    { connection_id: "ce259288-d560-4fb0-9763-53be0bfaf256", label: "Incomplete", provider_id: "llm:openai" },
  ] }), { headers: { ETag: '\"3\"' } })));
  await expect(readServiceConnections()).rejects.toThrow(/invalid/i);
});
it("still requires numeric revisions for control policy records", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ revision: 1, policy: {} }), { headers: { ETag: `"${"a".repeat(64)}"` } })));
  await expect(readServiceControl("task-routing")).rejects.toThrow(/control revision unavailable/i);
});
it("posts exact fixed task scope and reads the same durable typed refusal without resending", async () => {
  useAuthStore.setState({ status: "logged-in", token: "synthetic-ui-session" });
  const id = "ce259288-d560-4fb0-9763-53be0bfaf256";
  const receipt = { request_id: id, outcome: "refused", code: "admission_missing", attempts: [] };
  const io = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(receipt), { status: 200 })));
  vi.stubGlobal("fetch", io);
  const task = { request_id: id, mode: "fixed" as const, selection: { connection_id: "synthetic-connection", connection_revision: '"3"', model: "explicit-model", effort: "explicit-effort" }, prompt: "Explain risk", classification: "public" as const, context_refs: ["skill:risk_management"], purpose: "assistant" as const, deadline_ms: 3000, max_output_tokens: 100, required_hard_controls: ["output_tokens"] };
  expect(await dispatchServiceTask(task)).toEqual(receipt);
  expect(io).toHaveBeenCalledTimes(2);
  expect(JSON.parse(io.mock.calls[0][1].body)).toEqual(task);
  expect(io.mock.calls[1][0]).toBe(`/ft-api/v1/services/connections/tasks/${id}`);
  expect(io.mock.calls[1][1].method).toBe("GET");
});
it("uses the returned quoted revision and verifies policy write by readback", async () => {
  const io = vi.fn().mockImplementation((_url, init) => Promise.resolve(new Response(JSON.stringify({ revision: init.method === "GET" && io.mock.calls.length === 1 ? 0 : 1, policy: {} }), { status: 200, headers: { ETag: io.mock.calls.length === 1 ? '"0"' : '"1"' } })));
  vi.stubGlobal("fetch", io);
  const before = await readServiceControl("task-routing");
  const after = await saveServiceControl("task-routing", before.etag, { bootstrap: null, candidates: [] });
  expect(io.mock.calls[1][1].headers["If-Match"]).toBe('"0"');
  expect(after.etag).toBe('"1"');
  expect(io).toHaveBeenCalledTimes(3);
});
