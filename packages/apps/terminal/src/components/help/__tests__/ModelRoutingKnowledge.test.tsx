import { createHash } from "node:crypto";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ModelRoutingPanel from "../ModelRoutingPanel";
import { useBrokerStore } from "@/stores/brokerStore";
import { useAuthStore } from "@/stores/authStore";
import { observeKnowledgeScope } from "@/services/knowledgeScope";
import { BODY, SCOPE, NAME, VERSION, deferred, knowledgeTransport, procedure, response, row, seedKnowledgeSession } from "@/services/__tests__/knowledgeTestUtils";

const base = "/ft-api/v1/services/connections";
const id = "5a765bd0-48c1-4b8a-8db7-c94633b1abca";
const etag = `"${"a".repeat(64)}"`;
const connection = { schema_version: 1, connection_id: id, provider_id: "llm:openai", label: "Synthetic",
  model: "explicit-model", endpoint: "https://api.openai.com/v1/chat/completions", auth_mode: "api_key",
  credential_configured: false, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" };
let client: QueryClient;
let io: ReturnType<typeof knowledgeTransport>;
let scope = SCOPE;
let version = VERSION;
let submitted: Record<string, unknown>[];
function fill(label: string, value: string) { fireEvent.change(screen.getByLabelText(label), { target: { value } }); }
function mount() { return render(<QueryClientProvider client={client}><ModelRoutingPanel /></QueryClientProvider>); }
async function prepare(selected = true) {
  mount();
  await waitFor(() => expect(screen.getByRole("button", { name: `Read procedure ${NAME}`, hidden: true })).toBeEnabled());
  // Open the real panel's disclosure, not an invented selection cache.
  fireEvent.click(screen.getByText("Choose canonical knowledge"));
  if (selected) {
    fireEvent.click(screen.getByRole("button", { name: `Read procedure ${NAME}` }));
    expect((await screen.findByLabelText("Complete procedure body")).textContent).toBe(BODY);
    fireEvent.click(screen.getByRole("button", { name: "Select this procedure" }));
    await screen.findByRole("button", { name: "Unselect this procedure" });
  }
  await screen.findByRole("option", { name: "Synthetic · llm:openai" });
  fill("Task connection", id); fill("Task effort", "explicit-effort"); fill("Task deadline", "2000");
  fill("Task output limit", "100"); fill("Advisory task", "Original advisory input");
  expect(screen.getByRole("button", { name: "Send advisory task" })).toBeEnabled();
}
function clickSend() { fireEvent.click(screen.getByRole("button", { name: "Send advisory task" })); }
function noSubmission() {
  expect(submitted).toEqual([]);
  expect(io.requests.filter(r => r.path.includes("/tasks"))).toEqual([]);
  expect(screen.queryByRole("button", { name: "Read durable receipt" })).not.toBeInTheDocument();
  expect(client.getQueryCache().findAll({ queryKey: ["service-task-active"] }).some(q => q.state.data)).toBe(false);
}
beforeEach(() => {
  seedKnowledgeSession(); scope = SCOPE; version = VERSION; submitted = [];
  onlineManager.setOnline(true);
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  io = knowledgeTransport();
  io.routes.set(`GET ${base}`, () => new Response(JSON.stringify({ connections: [connection] }), { headers: { ETag: etag, "Content-Type": "application/json" } }));
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ scope, skills: [row({ origin: "stock", version_id: version })] }));
  io.routes.set(`GET /ft-api/v1/knowledge/skills/${NAME}`, () => response(procedure({ scope, version, classification: "public" })));
  io.routes.set(`POST ${base}/tasks`, init => {
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    submitted.push(body);
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer synthetic-knowledge");
    expect(new Headers(init.headers).has("X-Run-Id")).toBe(false);
    const output = "Synthetic completed advisory";
    const receipt = { request_id: body.request_id, outcome: "completed", code: "ok", output_digest: createHash("sha256").update(JSON.stringify(output)).digest("hex") };
    io.routes.set(`GET ${base}/tasks/${body.request_id}`, () => response(receipt));
    return response({ ...receipt, output });
  });
});
afterEach(() => { cleanup(); client.clear(); onlineManager.setOnline(true); io.assertClean(); vi.unstubAllGlobals(); });

it("keeps verified output on manual read but never in caches or reopened panels", async () => {
  await prepare(); clickSend();
  await screen.findByText("Synthetic completed advisory");
  fireEvent.click(screen.getByRole("button", { name: "Read durable receipt" }));
  await waitFor(() => expect(io.requests.filter(r => r.path.includes("/tasks/")).length).toBe(2));
  await waitFor(() => expect(screen.getByRole("button", { name: "Read durable receipt" })).toBeEnabled());
  expect(screen.getByText("Synthetic completed advisory")).toBeVisible();
  expect(JSON.stringify(client.getQueryCache().getAll().map(q => q.state.data))).not.toContain("Synthetic completed advisory");
  expect(JSON.stringify(client.getMutationCache().getAll())).not.toContain("Synthetic completed advisory");
  expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain("Synthetic completed advisory");
  cleanup(); mount();
  expect(screen.queryByText("Synthetic completed advisory")).not.toBeInTheDocument();
  expect(await screen.findByText(/output unavailable/i)).toBeVisible();
  expect(submitted).toHaveLength(1);
});

it.each(["auth", "account", "account-return", "server", "server-return"])("does not retain held completed text after %s retirement", async change => {
  await prepare(false);
  const held = deferred<Response>(); let entered = false;
  const output = "Original scope transient answer";
  let receipt: Record<string, unknown> = {};
  io.routes.set(`POST ${base}/tasks`, init => {
    const task = JSON.parse(String(init.body)); submitted.push(task);
    receipt = { request_id: task.request_id, outcome: "completed", code: "ok", output_digest: createHash("sha256").update(JSON.stringify(output)).digest("hex") };
    io.routes.set(`GET ${base}/tasks/${task.request_id}`, () => { entered = true; return held.promise; });
    return response({ ...receipt, output });
  });
  clickSend(); await waitFor(() => expect(entered).toBe(true));
  act(() => {
    if (change === "auth") useAuthStore.setState({ sessionGeneration: 11 });
    else if (change.startsWith("server")) {
      observeKnowledgeScope(client, { ...SCOPE, run_id: "server-run-b" });
      if (change === "server-return") observeKnowledgeScope(client, SCOPE);
    } else {
      useBrokerStore.getState().setActiveAccount("native:dhan:account-b");
      if (change === "account-return") useBrokerStore.getState().setActiveAccount("native:dhan:account-a");
    }
  });
  fill("Advisory task", "New scope draft");
  await act(async () => held.resolve(response(receipt)));
  expect(screen.getByLabelText("Advisory task")).toHaveValue("New scope draft");
  expect(screen.queryByRole("region", { name: "Task receipt" })).not.toBeInTheDocument();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(JSON.stringify(client.getQueryCache().getAll().map(q => q.state.data))).not.toContain(output);
  expect(submitted).toHaveLength(1);
  expect(io.requests.filter(r => r.path.includes("/tasks/"))).toHaveLength(1);
});

it.each(["lost", "mismatch", "unknown"])("retires visible output on %s manual read and keeps the no-resend barrier", async fault => {
  await prepare(false); clickSend(); await screen.findByText("Synthetic completed advisory");
  const requestId = submitted[0].request_id;
  io.routes.set(`GET ${base}/tasks/${requestId}`, () => fault === "lost" ? response({ error: "Receipt unavailable" }, 503)
    : response({ request_id: requestId, outcome: fault === "unknown" ? "pending" : "completed", code: "ok", output_digest: "0".repeat(64) }));
  fireEvent.click(screen.getByRole("button", { name: "Read durable receipt" }));
  await screen.findByRole("alert");
  expect(screen.queryByText("Synthetic completed advisory")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Send advisory task" })).toBeDisabled();
  cleanup(); mount();
  expect(screen.getByRole("button", { name: "Send advisory task" })).toBeDisabled();
  expect(submitted).toHaveLength(1);
  expect(io.requests.filter(r => r.path.includes("/tasks/"))).toHaveLength(2);
  expect(JSON.stringify(client.getQueryCache().getAll().map(q => q.state.data))).not.toContain("Synthetic completed advisory");
});

it("preserves a no-selection task with explicit server-null scope", async () => {
  io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ scope: null, skills: [row({ origin: "stock" })] }));
  await prepare(false);
  clickSend();
  await screen.findByText("Synthetic completed advisory");
  expect(submitted).toHaveLength(1);
  expect(submitted[0].context_refs).toEqual([]);
  expect(io.requests.filter(r => r.path.endsWith(`skills/${NAME}`))).toEqual([]);
});

it.each([false, true])("preflights at the actual panel send and keeps the same-scope positive (selected=%s)", async selected => {
  await prepare(selected);
  fill("Task knowledge references", "skill:manually-entered");
  const mark = io.requests.length;
  clickSend();
  expect(await screen.findByText("Synthetic completed advisory")).toBeVisible();
  expect(submitted).toHaveLength(1);
  expect(submitted[0]).toMatchObject({ prompt: "Original advisory input", context_refs: selected ? [`skill:${NAME}`, "skill:manually-entered"] : ["skill:manually-entered"],
    selection: { connection_id: id, connection_revision: etag, model: "explicit-model", effort: "explicit-effort" } });
  expect(io.requests.slice(mark).map(r => r.path)).toEqual([
    "/ft-api/v1/knowledge/skills", ...(selected ? [`/ft-api/v1/knowledge/skills/${NAME}`, "/ft-api/v1/knowledge/skills"] : []),
    `${base}/tasks`, `${base}/tasks/${submitted[0].request_id}`,
  ]);
});
it.each(["server-run", "version", "malformed", "denied", "offline"])("does not dispatch or mint an apparent receipt after %s preflight refusal", async fault => {
  await prepare();
  if (fault === "server-run") scope = { ...SCOPE, run_id: "server-run-b" };
  if (fault === "version") version = "replacement-version";
  if (fault === "malformed") io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ skills: [] }));
  if (fault === "denied") io.routes.set("GET /ft-api/v1/knowledge/skills", () => response({ error: "knowledge_unavailable" }, 503));
  if (fault === "offline") act(() => onlineManager.setOnline(false));
  clickSend();
  if (fault === "server-run") await waitFor(() => expect(screen.getByLabelText("Task connection")).toHaveValue(""));
  else await screen.findByRole("alert");
  noSubmission();
  expect(client.getQueryCache().findAll({ queryKey: ["aiAgent"] })).toHaveLength(0);
});
it("initiates transport inside the original scope before publishing submitted state", async () => {
  await prepare();
  const events: string[] = [];
  const unsubscribe = client.getQueryCache().subscribe(event => {
    if (event.query.queryKey[0] === "service-task-active" && event.query.state.data && events.length < 2) {
      events.push("publish");
      useBrokerStore.getState().setActiveAccount("native:dhan:account-b");
    }
  });
  io.routes.set(`POST ${base}/tasks`, init => {
    events.push(`post:${useBrokerStore.getState().activeAccountId}`);
    const body = JSON.parse(String(init.body)) as Record<string, unknown>; submitted.push(body);
    const receipt = { request_id: body.request_id, outcome: "completed" };
    io.routes.set(`GET ${base}/tasks/${body.request_id}`, () => response(receipt));
    return response(receipt);
  });
  clickSend();
  await waitFor(() => expect(submitted).toHaveLength(1));
  await act(async () => { await Promise.resolve(); });
  unsubscribe();
  expect(events).toEqual(["post:native:dhan:account-a", "publish"]);
  expect(screen.queryByRole("button", { name: "Read durable receipt" })).not.toBeInTheDocument();
});

it("freezes every task input across its real held preflight", async () => {
  await prepare();
  fill("Task knowledge references", "skill:original-manual");
  const held = deferred<Response>(); let entered = false;
  io.routes.set(`GET /ft-api/v1/knowledge/skills/${NAME}`, () => { entered = true; return held.promise; });
  clickSend(); await waitFor(() => expect(entered).toBe(true));
  noSubmission();
  fill("Advisory task", "Later draft"); fill("Task model", "later-model"); fill("Task effort", "later-effort");
  fill("Task deadline", "9000"); fill("Task output limit", "900"); fill("Task classification", "private");
  fill("Task routing mode", "automatic"); fill("Task knowledge references", "skill:later-manual");
  await act(async () => held.resolve(response(procedure({ classification: "public" }))));
  await screen.findByText("Synthetic completed advisory");
  expect(submitted[0]).toMatchObject({ prompt: "Original advisory input", mode: "fixed", classification: "public",
    deadline_ms: 2000, max_output_tokens: 100, context_refs: [`skill:${NAME}`, "skill:original-manual"],
    selection: { connection_id: id, connection_revision: etag, model: "explicit-model", effort: "explicit-effort" } });
});
it.each(["revision", "revision-return", "selection-return", "blocked"])("refuses observed %s changes during preflight", async change => {
  await prepare();
  const held = deferred<Response>(); let entered = false;
  io.routes.set(`GET /ft-api/v1/knowledge/skills/${NAME}`, () => { entered = true; return held.promise; });
  clickSend(); await waitFor(() => expect(entered).toBe(true));
  act(() => {
    if (change === "blocked") client.setQueryData(["service-connections-blocked", 10], true);
    else if (change === "selection-return") {
      fireEvent.click(screen.getByRole("button", { name: "Unselect this procedure" }));
    } else {
      client.setQueryData(["service-connections", 10], { connections: [connection], etag: `"${"b".repeat(64)}"` });
      if (change === "revision-return") client.setQueryData(["service-connections", 10], { connections: [connection], etag });
    }
  });
  if (change === "selection-return") fireEvent.click(await screen.findByRole("button", { name: "Select this procedure" }));
  await act(async () => held.resolve(response(procedure({ classification: "public" }))));
  await screen.findByRole("alert");
  noSubmission();
});
it.each(["resolve", "reject"])("does not publish a late task %s into a newly selected account", async outcome => {
  await prepare();
  const held = deferred<Response>(); let entered = false; let requestId = "";
  io.routes.set(`POST ${base}/tasks`, init => {
    const body = JSON.parse(String(init.body)) as Record<string, unknown>; submitted.push(body);
    requestId = String(body.request_id); entered = true;
    io.routes.set(`GET ${base}/tasks/${requestId}`, () => response({ request_id: requestId, outcome: "completed", output: "Old account receipt" }));
    return held.promise;
  });
  clickSend(); await waitFor(() => expect(entered).toBe(true));
  act(() => useBrokerStore.getState().setActiveAccount("native:dhan:account-b"));
  fill("Advisory task", "New account draft");
  await act(async () => held.resolve(outcome === "resolve"
    ? response({ request_id: requestId, outcome: "completed" }) : response({ error: "old_scope_error" }, 503)));
  expect(screen.getByLabelText("Advisory task")).toHaveValue("New account draft");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "Task receipt" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Read durable receipt" })).not.toBeInTheDocument();
  expect(submitted).toHaveLength(1);
});
it("never resubmits after uncertainty, even on panel disposal and reopening", async () => {
  await prepare();
  io.routes.set(`POST ${base}/tasks`, init => { submitted.push(JSON.parse(String(init.body))); return response({ error: "uncertain" }, 503); });
  clickSend(); await screen.findByRole("alert");
  expect(screen.getByRole("button", { name: "Send advisory task" })).toBeDisabled();
  cleanup(); mount();
  fill("Task connection", id); fill("Task effort", "explicit-effort"); fill("Task deadline", "2000");
  fill("Task output limit", "100"); fill("Advisory task", "Another draft");
  expect(screen.getByRole("button", { name: "Send advisory task" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Read durable receipt" })).toBeEnabled();
  expect(submitted).toHaveLength(1);
});

it.each(["account", "account-return", "auth"])("retires pending preflight across %s before any task POST", async change => {
  await prepare();
  const held = deferred<Response>();
  let entered = false;
  io.routes.set(`GET /ft-api/v1/knowledge/skills/${NAME}`, () => { entered = true; return held.promise; });
  clickSend(); await waitFor(() => expect(entered).toBe(true));
  noSubmission();
  act(() => {
    if (change === "auth") useAuthStore.setState({ sessionGeneration: 11 });
    else {
      useBrokerStore.getState().setActiveAccount("native:dhan:account-b");
      if (change === "account-return") useBrokerStore.getState().setActiveAccount("native:dhan:account-a");
    }
  });
  await act(async () => held.resolve(response(procedure({ scope: SCOPE, classification: "public" }))));
  noSubmission();
  expect(screen.queryByText(/retired scope/)).not.toBeInTheDocument();
});
