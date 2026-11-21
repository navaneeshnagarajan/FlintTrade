import { Activity } from "react";
import { appendFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { connectNativeAccount, reloginNativeAccount } from "../ftApi.native";
import { reconnectBrokerAccount } from "../brokerAccountsApi";
import { BrokerConnect } from "@/components/account/BrokerConnect";
import { ConnectedAccounts } from "@/routes/setup/ConnectedAccounts";
import { useBrokerStore } from "@/stores/brokerStore";
import wire from "@/test-utils/nativeAccountResultWire.v2.json";
import cleanupWire from "@/test-utils/nativeAccountCleanupWire.json";

const connected = wire.ordinary.rows.find(r => r.label === "connect")!;
const reconnected = wire.ordinary.rows.find(r => r.label === "reconnect")!;
const expired = wire.ordinary.rows.find(r => r.label === "reconnect-expired")!;
const unavailableAccounts = wire.ordinary.rows.find(r => r.label === "expired-accounts")!;
const presentAccounts = wire.ordinary.rows.find(r => r.label === "reconnect-accounts")!;
const unknown = wire.unknown.rows.find(r => r.label === "connect")!;
const catalogue = wire.ordinary.rows.find(r => r.label === "catalogue")!;
let replies: Array<{ body: string; status: number }>;
let requests: Array<{ method: string; path: string; body?: string | null }>;
let unexpected: string[];
let client: QueryClient;
let nextBody: (() => Promise<Response>) | undefined;
let accountBody: string;
let reconnectKey: string;
const response = (row: { body: string; status: number }) => new Response(row.body, { status: row.status, headers: { "Content-Type": "application/json" } });
beforeEach(() => {
  replies = []; requests = []; unexpected = []; nextBody = undefined;
  accountBody = unavailableAccounts.body;
  reconnectKey = reconnected.key!;
  useBrokerStore.setState({ accounts: [], activeAccountId: null });
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    const path = new URL(String(url), "http://localhost").pathname.replace(/^\/ft-api/, "");
    const method = init?.method ?? "GET";
    requests.push({ method, path, body: init?.body as string | undefined });
    if (method === "POST" && [connected.path, reconnected.path].includes(path)) {
      const key = new Headers(init?.headers).get("Idempotency-Key");
      try { expect(key).toBe(path === connected.path ? connected.key : reconnectKey); }
      catch (error) { unexpected.push(String(error)); throw error; }
      if (nextBody) return nextBody();
      const row = replies.shift(); if (row) return response(row);
    }
    if (method === "GET" && path === "/api/v1/native/accounts") return response({ body: accountBody, status: 200 });
    if (method === "GET" && path === "/api/v1/native/brokers") return response(catalogue);
    if (method === "GET" && path === "/api/v1/broker/mcp") return response({ body: JSON.stringify({ status: "success", data: { brokers: [] } }), status: 200 });
    unexpected.push(`${method} ${path}`); throw new Error("Unregistered transport");
  });
});
afterEach((context) => {
  cleanup(); client.clear(); vi.restoreAllMocks();
  if (process.env.FLINTTRADE_ACCOUNT_RESULT_LEDGER) appendFileSync(process.env.FLINTTRADE_ACCOUNT_RESULT_LEDGER,
    JSON.stringify({ case: context.task.name, requests: requests.map(({ method, path, body }) => ({ method, path, body: body?.includes("credentials") ? "[credential-bearing request omitted]" : body })), unexpected }) + "\n");
  expect(unexpected).toEqual([]);
});

describe("current managed account HTTP correspondence", () => {
  it("retains a real committed CONNECT receipt separately from current session presence", async () => {
    replies.push(connected);
    const result = await connectNativeAccount({ adapter_id: "dhan", account_id: "Synthetic", credentials: { client_id: "Synthetic", access_token: "synthetic-access" } }, connected.key!);
    expect(result).toEqual(JSON.parse(connected.body));
    expect(requests).toEqual([{ method: "POST", path: connected.path, body: JSON.stringify({ adapter_id: "dhan", account_id: "Synthetic", credentials: { client_id: "Synthetic", access_token: "synthetic-access" } }) }]);
  });
  it.each([reconnected, expired])("propagates the literal $label through the exported reconnect facade", async row => {
    replies.push(row);
    const result = await reconnectBrokerAccount({ source: "native", broker: "dhan", account_id: "Synthetic" }, reconnected.key!);
    expect(result).toEqual(JSON.parse(row.body));
    expect(requests).toEqual([{ method: "POST", path: reconnected.path, body: "{}" }]);
  });
  it("preserves genuine authentication uncertainty without resend", async () => {
    replies.push(unknown);
    const result = await connectNativeAccount({ adapter_id: "dhan", account_id: "Synthetic", credentials: {} }, connected.key!);
    expect(result).toEqual(JSON.parse(unknown.body)); expect(requests).toHaveLength(1);
  });
  it.each(["operationId", "kind", "credentialGeneration", "state", "runtimeStatus", "reason", "extra"])("refuses a single-field contradiction: %s", async field => {
    const body = JSON.parse(reconnected.body);
    if (field === "runtimeStatus") body.runtimeStatus = "future_recovery_status";
    else if (field === "extra") body.receipt.secret = "must-not-echo";
    else body.receipt[field] = { operationId: connected.key, kind: "connect", credentialGeneration: 0, state: "authentication_unknown", reason: "must-not-echo\n" }[field as "kind"];
    replies.push({ body: JSON.stringify(body), status: 200 });
    await expect(reloginNativeAccount("dhan", "Synthetic", undefined, reconnected.key!)).rejects.toThrow(/outcome unavailable/i);
    expect(requests).toHaveLength(1);
  });
});

for (const surface of ["setup", "settings"] as const) {
  describe(`${surface} mounted account result`, () => {
    function mount() {
      vi.spyOn(crypto, "randomUUID").mockReturnValue(reconnectKey as `${string}-${string}-${string}-${string}-${string}`);
      const child = surface === "setup" ? <ConnectedAccounts /> : <BrokerConnect />;
      const view = render(<QueryClientProvider client={client}><Activity mode="visible">{child}</Activity></QueryClientProvider>);
      return { ...view, child };
    }
    async function submit() {
      fireEvent.click(await screen.findByRole("button", { name: surface === "setup" ? "Reconnect dhan" : "Re-authenticate dhan Synthetic" }));
      await waitFor(() => expect(requests.filter(r => r.method === "POST")).toHaveLength(1));
    }
    it("renders current normal-factory reconnect success without demanding credentials or granting writes", async () => {
      replies.push(reconnected); mount(); await submit();
      expect(await screen.findByText(/session present.*not.*trading authority/i)).toBeInTheDocument();
      expect(screen.queryByText(/fresh credentials below/i)).not.toBeInTheDocument();
      expect(requests.filter(r => r.method !== "GET")).toEqual([{ method: "POST", path: reconnected.path, body: "{}" }]);
      expect(useBrokerStore.getState().accounts[0].read_smoke_ok).toBe(false);
    });
    it("does not let an independent live account census erase an unavailable durable replay", async () => {
      replies.push(expired); mount(); await submit(); accountBody = presentAccounts.body;
      expect(await screen.findByText(/committed.*session unavailable/i)).toBeInTheDocument();
      expect(screen.queryByText(/fresh credentials below/i)).not.toBeInTheDocument();
      expect(requests.filter(r => r.method === "POST")).toHaveLength(1);
    });
    it("renders a genuine committed cleanup-pending receipt without success or fresh-credential inference", async () => {
      reconnectKey = cleanupWire.key;
      replies.push(cleanupWire); mount(); await submit();
      expect(await screen.findByText(/committed.*cleanup pending/i)).toBeInTheDocument();
      expect(screen.queryByText(/session present|fresh credentials below/i)).not.toBeInTheDocument();
      expect(requests.filter(r => r.method === "POST")).toHaveLength(1);
    });
    it("refuses an unknown future status without credential prefill or resend", async () => {
      const body = JSON.parse(reconnected.body); body.runtimeStatus = "future_unrecognised";
      replies.push({ body: JSON.stringify(body), status: 200 }); mount(); await submit();
      expect(await screen.findByText(/account outcome unavailable/i)).toBeInTheDocument();
      expect(screen.queryByText(/fresh credentials below/i)).not.toBeInTheDocument();
      expect(requests.filter(r => r.method === "POST")).toHaveLength(1);
    });
    it.each(["account-return", "hidden-return"])("retires a held result across %s", async retirement => {
      let resolve!: (r: Response) => void;
      nextBody = () => new Promise(r => { resolve = r; });
      const view = mount(); await submit();
      if (retirement === "account-return") act(() => {
        useBrokerStore.setState({ activeAccountId: "native:dhan:Other" });
        useBrokerStore.setState({ activeAccountId: null });
      });
      else {
        view.rerender(<QueryClientProvider client={client}><Activity mode="hidden">{view.child}</Activity></QueryClientProvider>);
        view.rerender(<QueryClientProvider client={client}><Activity mode="visible">{view.child}</Activity></QueryClientProvider>);
      }
      const reads = requests.filter(r => r.method === "GET").length;
      await act(async () => { resolve(response(reconnected)); });
      expect(screen.queryByText(/session present|re-authenticated|fresh credentials below/i)).not.toBeInTheDocument();
      expect(requests.filter(r => r.method === "GET")).toHaveLength(reads);
    });
  });
}


describe("mounted direct CONNECT with genuine factory bodies", () => {
  async function form(row: typeof connected) {
    vi.spyOn(crypto, "randomUUID").mockReturnValue(connected.key as `${string}-${string}-${string}-${string}-${string}`);
    replies.push(row);
    const view = render(<QueryClientProvider client={client}><Activity mode="visible"><BrokerConnect /></Activity></QueryClientProvider>);
    fireEvent.click(await screen.findByRole("combobox", { name: /^Broker$/i }));
    fireEvent.click(await screen.findByRole("option", { name: "Dhan" }));
    fireEvent.click(screen.getByRole("combobox", { name: /login method/i }));
    fireEvent.click(await screen.findByRole("option", { name: /^Access token$/i }));
    fireEvent.change(screen.getByLabelText(/account id/i), { target: { value: "Synthetic" } });
    fireEvent.change(screen.getByLabelText("Dhan client ID"), { target: { value: "Synthetic" } });
    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "synthetic-access" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    return view;
  }
  it.each([connected, unknown])("renders current direct CONNECT: $body", async row => {
    await form(row);
    expect(await screen.findByText(row === connected ? /session present.*not.*trading authority/i : /authentication outcome unknown; blocked/i)).toBeInTheDocument();
    expect(screen.queryByText(/fresh credentials below/i)).not.toBeInTheDocument();
    expect(requests.filter(r => r.method === "POST")).toEqual([{ method: "POST", path: connected.path, body: JSON.stringify({ adapter_id: "dhan", account_id: "Synthetic", credentials: { client_id: "Synthetic", access_token: "synthetic-access" } }) }]);
    expect(screen.getByLabelText("Access token")).toHaveValue("");
    expect(JSON.stringify(client.getMutationCache().getAll().map(m => m.state))).not.toContain("synthetic-access");
  });
  it("retires a held CONNECT and clears mounted credentials across Activity hide", async () => {
    let resolve!: (value: Response) => void;
    nextBody = () => new Promise(r => { resolve = r; });
    const view = await form(connected);
    await waitFor(() => expect(requests.filter(r => r.method === "POST")).toHaveLength(1));
    view.rerender(<QueryClientProvider client={client}><Activity mode="hidden"><BrokerConnect /></Activity></QueryClientProvider>);
    await act(async () => { resolve(response(connected)); });
    view.rerender(<QueryClientProvider client={client}><Activity mode="visible"><BrokerConnect /></Activity></QueryClientProvider>);
    expect(screen.queryByText(/session present.*trading authority/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Access token")).toHaveValue("");
  });
});
