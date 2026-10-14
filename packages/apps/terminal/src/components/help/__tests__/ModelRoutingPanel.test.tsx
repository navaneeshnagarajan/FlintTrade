import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ModelRoutingPanel from "../ModelRoutingPanel";
import { useAuthStore } from "@/stores/authStore";
import { useConnectionStore } from "@/stores/connectionStore";

const base = "/ft-api/v1/services/connections";
const id = "5a765bd0-48c1-4b8a-8db7-c94633b1abca";
const etag = (digit: string) => `"${digit.repeat(64)}"`;
const record = {
  schema_version: 1, connection_id: id, provider_id: "llm:openai", label: "Research",
  model: "explicit-model", endpoint: "https://api.openai.com/v1/chat/completions",
  auth_mode: "api_key", credential_configured: false,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};
const json = (body: unknown, revision = etag("a"), status = 200) => new Response(JSON.stringify(body), { status, headers: { ETag: revision, "Content-Type": "application/json" } });
let failures: string[];
let calls: string[];
let client: QueryClient;
let expectedToken: string;
type Handler = (init: RequestInit) => Response | Promise<Response>;
class SyntheticNetworkError extends Error {}
function transport(handlers: Record<string, Handler>) {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit = {}) => {
    const key = `${init.method ?? "GET"} ${url}`;
    calls.push(key);
    try {
      if (key === "GET /ft-api/v1/knowledge/skills") return json({ scope: null, skills: [] });
      const handler = handlers[key];
      if (!handler) throw new Error("Unregistered request");
      const headers = new Headers(init.headers);
      expect(headers.get("Authorization")).toBe(`Bearer ${expectedToken}`);
      expect(init.cache).toBe("no-store");
      return await handler(init);
    } catch (error) {
      if (error instanceof SyntheticNetworkError) throw error;
      failures.push(key);
      throw new Error("Synthetic transport assertion failed");
    }
  }));
}
function mount() {
  return render(<QueryClientProvider client={client}><ModelRoutingPanel /></QueryClientProvider>);
}
function fill(label: string, value: string) { fireEvent.change(screen.getByLabelText(label), { target: { value } }); }
async function newConfiguration() {
  await waitFor(() => expect(screen.getByRole("button", { name: "Add service connection" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Add service connection" }));
  fill("Connection provider", "llm:openai");
  fill("Connection label", "Research");
  fill("Connection model", "explicit-model");
  fill("Connection authentication", "api_key");
}
beforeEach(() => {
  failures = []; calls = [];
  expectedToken = "synthetic-session-a";
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  useAuthStore.setState({ status: "logged-in", token: "synthetic-session-a", username: "synthetic-a", sessionGeneration: 1 });
  useConnectionStore.setState({ apiKey: "" });
});
afterEach(() => {
  cleanup(); client.clear(); vi.unstubAllGlobals();
  expect(failures).toEqual([]);
});

it("creates from the mounted panel with the exact collection fence and verifies item plus collection", async () => {
  let created = false;
  transport({
    [`GET ${base}`]: () => json({ connections: created ? [record] : [] }, etag(created ? "b" : "a")),
    [`POST ${base}`]: init => {
      const headers = new Headers(init.headers);
      expect(headers.get("If-Match")).toBe(etag("a"));
      expect(headers.get("Idempotency-Key")).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
      expect(headers.get("Content-Type")).toBe("application/json");
      expect(JSON.parse(String(init.body))).toEqual({ provider_id: "llm:openai", label: "Research", model: "explicit-model", auth_mode: "api_key" });
      created = true;
      return json(record, etag("b"), 201);
    },
    [`GET ${base}/${id}`]: () => json(record, etag("b")),
  });
  mount();
  await newConfiguration();
  fireEvent.click(screen.getByRole("button", { name: "Create configuration" }));
  expect(await screen.findByText("Configuration saved and read back. No provider login or qualification was performed.")).toBeVisible();
  expect(screen.getByRole("option", { name: "Research · llm:openai" })).toBeInTheDocument();
  expect(calls.filter(call => call.includes("services/connections"))).toEqual([
    `GET ${base}`, `POST ${base}`, `GET ${base}/${id}`, `GET ${base}`,
  ]);
});

it("confirms credential replacement for the exact connection without persisting material", async () => {
  const material = "synthetic-not-live-replacement";
  let current = { ...record, credential_configured: true };
  let revision = etag("a");
  transport({
    [`GET ${base}`]: () => json({ connections: [current] }, revision),
    [`GET ${base}/${id}`]: () => json(current, revision),
    [`PATCH ${base}/${id}`]: init => {
      expect(new Headers(init.headers).get("If-Match")).toBe(etag("a"));
      const payload = JSON.parse(String(init.body));
      expect(payload.credential === material).toBe(true);
      const { credential: _credential, ...metadata } = payload;
      expect(metadata).toEqual({ label: "Renamed", model: "explicit-model", auth_mode: "api_key" });
      current = { ...current, label: "Renamed" }; revision = etag("b");
      return json(current, revision);
    },
  });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit Research" }));
  expect(screen.getByLabelText("Connection provider")).toBeDisabled();
  fill("Connection label", "Renamed");
  fill("Credential action", "replace");
  fill("Connection credential", material);
  fireEvent.click(screen.getByRole("button", { name: "Review connection update" }));
  const confirmation = screen.getByRole("region", { name: "Confirm connection change" });
  expect(confirmation).toHaveTextContent(id);
  expect(confirmation).toHaveTextContent("does not revoke the remote credential");
  expect(confirmation.textContent?.includes(material)).toBe(false);
  expect(calls.filter(call => call.startsWith("PATCH"))).toEqual([]);
  fireEvent.click(screen.getByRole("button", { name: "Confirm update" }));
  expect(await screen.findByText("Configuration saved and read back. No provider login or qualification was performed.")).toBeVisible();
  expect(JSON.stringify(client.getQueryCache().getAll().map(query => query.state.data)).includes(material)).toBe(false);
  expect(JSON.stringify(client.getMutationCache().getAll()).includes(material)).toBe(false);
  expect(JSON.stringify({ ...localStorage, ...sessionStorage }).includes(material)).toBe(false);
  expect(calls.filter(call => call.includes("services/connections"))).toEqual([`GET ${base}`, `PATCH ${base}/${id}`, `GET ${base}/${id}`, `GET ${base}`]);
});

it("clears only the local binding then explicitly confirms deletion with collection readback", async () => {
  let current = { ...record, credential_configured: true };
  let deleted = false;
  let revision = etag("a");
  const keys: string[] = [];
  transport({
    [`GET ${base}`]: () => json({ connections: deleted ? [] : [current] }, revision),
    [`GET ${base}/${id}`]: () => json(current, revision),
    [`PATCH ${base}/${id}`]: init => {
      const headers = new Headers(init.headers); keys.push(headers.get("Idempotency-Key") ?? "");
      expect(headers.get("If-Match")).toBe(etag("a"));
      expect(JSON.parse(String(init.body))).toEqual({ label: "Research", model: "explicit-model", auth_mode: "api_key", clear_credential: true });
      current = { ...current, credential_configured: false }; revision = etag("b");
      return json(current, revision);
    },
    [`DELETE ${base}/${id}`]: init => {
      const headers = new Headers(init.headers); keys.push(headers.get("Idempotency-Key") ?? "");
      expect(headers.get("If-Match")).toBe(etag("b"));
      expect(headers.get("Content-Type")).toBe("application/json");
      expect(init.body).toBe("{}");
      deleted = true; revision = etag("c"); return json({ deleted: true }, revision);
    },
  });
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Edit Research" }));
  fill("Credential action", "clear");
  fireEvent.click(screen.getByRole("button", { name: "Review connection update" }));
  expect(calls.some(call => call.startsWith("PATCH"))).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Confirm update" }));
  await screen.findByText("Configuration saved and read back. No provider login or qualification was performed.");
  fireEvent.click(screen.getByRole("button", { name: "Delete Research" }));
  expect(screen.getByRole("region", { name: "Confirm connection change" })).toHaveTextContent(id);
  expect(calls.some(call => call.startsWith("DELETE"))).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Confirm delete" }));
  expect(await screen.findByText("Local configuration deleted and absence verified. Remote credentials and accepted work were not revoked.")).toBeVisible();
  expect(screen.queryByRole("option", { name: "Research · llm:openai" })).not.toBeInTheDocument();
  expect(keys).toHaveLength(2); expect(new Set(keys).size).toBe(2);
  expect(calls.filter(call => call.includes("services/connections"))).toEqual([`GET ${base}`, `PATCH ${base}/${id}`, `GET ${base}/${id}`, `GET ${base}`, `DELETE ${base}/${id}`, `GET ${base}`]);
});

it.each([412, 403, 503, 200])("requires refresh and explicit resubmission after refused or uncertain create (%s)", async status => {
  let revision = etag("a");
  let attempts = 0;
  transport({
    [`GET ${base}`]: () => json({ connections: [] }, revision),
    [`POST ${base}`]: init => {
      attempts += 1;
      expect(new Headers(init.headers).get("If-Match")).toBe(attempts === 1 ? etag("a") : etag("b"));
      revision = etag("b");
      return status === 200 ? new Response("not-json", { status: 200 }) : json({ error: "untrusted response text" }, revision, status);
    },
  });
  mount(); await newConfiguration();
  fill("Credential action", "replace"); fill("Connection credential", "synthetic-only");
  fireEvent.click(screen.getByRole("button", { name: "Create configuration" }));
  await screen.findByRole("alert");
  expect(screen.queryByLabelText("Connection credential")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add service connection" })).toBeDisabled();
  expect(calls.filter(call => call.includes("services/connections"))).toEqual([`GET ${base}`, `POST ${base}`]);
  expect(document.body.textContent).not.toContain("untrusted response text");
  if (status === 412) expect(screen.getByRole("alert")).toHaveTextContent("revision conflict");
  fireEvent.click(screen.getByRole("button", { name: "Refresh connections" }));
  await newConfiguration();
  expect(attempts).toBe(1);
  fireEvent.click(screen.getByRole("button", { name: "Create configuration" }));
  await waitFor(() => expect(attempts).toBe(2));
  await screen.findByRole("alert");
});

it.each(["resolve", "reject"])("retires a deferred prior-session create on logout and new login (%s)", async outcome => {
  let resolve!: (response: Response) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<Response>((yes, no) => { resolve = yes; reject = no; });
  let entered = false;
  transport({
    [`GET ${base}`]: () => json({ connections: [] }),
    [`POST ${base}`]: () => { entered = true; return promise; },
  });
  mount(); await newConfiguration();
  fill("Credential action", "replace"); fill("Connection credential", "synthetic-only");
  fireEvent.click(screen.getByRole("button", { name: "Create configuration" }));
  await waitFor(() => expect(entered).toBe(true));
  expect(screen.getByLabelText("Connection credential")).toHaveValue("");
  act(() => useAuthStore.getState().setLoggedOut());
  expect(screen.queryByLabelText("Connection credential")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Add service connection" })).not.toBeInTheDocument();
  expectedToken = "synthetic-session-b";
  act(() => useAuthStore.setState({ status: "logged-in", token: expectedToken, username: "synthetic-b", sessionGeneration: 3 }));
  await newConfiguration(); fill("Connection label", "Session B draft");
  await act(async () => {
    if (outcome === "resolve") resolve(json({ ...record, credential_configured: true }, etag("b"), 201));
    else reject(new SyntheticNetworkError("synthetic network failure"));
    await Promise.resolve();
  });
  expect(screen.getByLabelText("Connection label")).toHaveValue("Session B draft");
  expect(screen.getByRole("button", { name: "Create configuration" })).toBeEnabled();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.queryByText(/Configuration saved and read back/)).not.toBeInTheDocument();
  expect(calls.filter(call => call.includes("services/connections"))).toEqual([`GET ${base}`, `POST ${base}`, `GET ${base}`]);
});

it("creates an explicit operator endpoint with transient credential binding and no invented admission", async () => {
  let created = false;
  const custom = { ...record, provider_id: "llm:custom", endpoint: "http://127.0.0.1:9000/studio", credential_configured: true };
  transport({
    [`GET ${base}`]: () => json({ connections: created ? [custom] : [] }, etag(created ? "b" : "a")),
    [`GET ${base}/${id}`]: () => json(custom, etag("b")),
    [`POST ${base}`]: init => {
      const body = JSON.parse(String(init.body));
      expect(body.credential === "synthetic-only").toBe(true);
      delete body.credential;
      expect(body).toEqual({ provider_id: "llm:custom", label: "Research", model: "explicit-model", auth_mode: "api_key", endpoint: custom.endpoint });
      created = true; return json(custom, etag("b"), 201);
    },
  });
  mount(); await newConfiguration();
  fill("Connection provider", "llm:custom");
  expect(screen.getByLabelText("Connection model")).toHaveValue("");
  fill("Connection model", "explicit-model"); fill("Connection authentication", "api_key");
  fill("Connection endpoint", custom.endpoint);
  fill("Credential action", "replace"); fill("Connection credential", "synthetic-only");
  expect(screen.getByText(/unsloth_chat/)).toHaveTextContent("assistant");
  fireEvent.click(screen.getByRole("button", { name: "Create configuration" }));
  await screen.findByText("Configuration saved and read back. No provider login or qualification was performed.");
  expect(calls.filter(call => !call.startsWith("GET"))).toEqual([`POST ${base}`]);
});

it("labels stored subscription credentials without pretending OAuth acquisition or qualification exists", async () => {
  const subscription = { ...record, auth_mode: "chatgpt_oauth", credential_configured: true };
  transport({ [`GET ${base}`]: () => json({ connections: [subscription] }) });
  mount(); fireEvent.click(await screen.findByRole("button", { name: "Edit Research" }));
  expect(screen.getByText(/OAuth acquisition\/PKCE/)).toHaveTextContent("not implemented");
  expect(screen.getByRole("button", { name: "Sign in with provider (unavailable)" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Refresh provider token (unavailable)" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Revoke remote credential (unavailable)" })).toBeDisabled();
  expect(screen.getByText(/Credential: stored, not verified/)).toBeVisible();
  expect(screen.getByText(/chatgpt_responses/)).toHaveTextContent("https://api.openai.com/v1/responses");
  expect(screen.getByText(/xAI OAuth/)).toHaveTextContent("unresolved");
  expect(calls.filter(call => !call.startsWith("GET"))).toEqual([]);
});

it("blocks advisory sends during setup uncertainty and retires the old task selection after readback", async () => {
  let resolve!: (response: Response) => void;
  const pending = new Promise<Response>(yes => { resolve = yes; });
  let entered = false;
  let current = record;
  let revision = etag("a");
  transport({
    [`GET ${base}`]: () => json({ connections: [current] }, revision),
    [`GET ${base}/${id}`]: () => json(current, revision),
    [`PATCH ${base}/${id}`]: () => { entered = true; return pending; },
  });
  mount(); await screen.findByRole("button", { name: "Edit Research" });
  fill("Task connection", id); fill("Task effort", "explicit-effort"); fill("Advisory task", "Synthetic explanation"); fill("Task deadline", "2000"); fill("Task output limit", "100");
  expect(screen.getByRole("button", { name: "Send advisory task" })).toBeEnabled();
  fireEvent.click(screen.getByRole("button", { name: "Edit Research" }));
  fill("Connection label", "Renamed");
  fireEvent.click(screen.getByRole("button", { name: "Review connection update" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm update" }));
  await waitFor(() => expect(entered).toBe(true));
  expect(screen.getByRole("button", { name: "Send advisory task" })).toBeDisabled();
  current = { ...record, label: "Renamed" }; revision = etag("b");
  await act(async () => resolve(json(current, revision)));
  await screen.findByText("Configuration saved and read back. No provider login or qualification was performed.");
  expect(screen.getByLabelText("Task connection")).toHaveValue("");
  expect(screen.getByRole("button", { name: "Send advisory task" })).toBeDisabled();
  expect(calls.filter(call => call.includes("/tasks"))).toEqual([]);
});

it("retains the refresh barrier across panel disposal without retaining credentials", async () => {
  transport({
    [`GET ${base}`]: () => json({ connections: [] }),
    [`POST ${base}`]: () => json({ error: "service_connection_store_unavailable" }, etag("b"), 503),
  });
  const first = mount(); await newConfiguration();
  fill("Credential action", "replace"); fill("Connection credential", "synthetic-only");
  fireEvent.click(screen.getByRole("button", { name: "Create configuration" }));
  await screen.findByRole("alert"); first.unmount();
  mount();
  expect(screen.getByRole("button", { name: "Add service connection" })).toBeDisabled();
  expect(screen.queryByLabelText("Connection credential")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Refresh connections" }));
  await newConfiguration();
  expect(calls.filter(call => call.includes("services/connections"))).toEqual([`GET ${base}`, `POST ${base}`, `GET ${base}`]);
});
