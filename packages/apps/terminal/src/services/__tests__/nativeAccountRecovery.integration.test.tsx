import { Activity } from "react";
import { appendFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { reloginNativeAccount } from "../ftApi.native";
import { reconnectBrokerAccount } from "../brokerAccountsApi";
import { BrokerConnect } from "@/components/account/BrokerConnect";
import { ConnectedAccounts } from "@/routes/setup/ConnectedAccounts";
import { resetOperatorSignals, useOperatorSignalStore } from "@/stores/operatorSignalStore";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { pickNativeWriteTargetFromState } from "../brokerTargets";
import { canPromotePrimaryAccount } from "@/lib/brokerAccountRules";
import wire from "@/test-utils/nativeAccountRecoveryWire.json";

type Sample = typeof wire.samples[number];
let row: Sample;
let body: string;
let requests: Array<{ method: string; path: string; body?: string | null; key: string | null }>;
let unexpected: string[];
let client: QueryClient;
let nextBody: (() => Promise<Response>) | undefined;
let currentReadout: boolean;
let nextAccounts: (() => Promise<Response>) | undefined;
const response = (value: { body: string; status: number }) => new Response(value.body, { status: value.status, headers: { "Content-Type": "application/json" } });
beforeEach(() => {
  row = wire.samples[0]; body = row.body; requests = []; unexpected = []; nextBody = undefined; nextAccounts = undefined; currentReadout = false;
  resetOperatorSignals();
  useAuthStore.setState(s => ({ sessionGeneration: s.sessionGeneration + 1 }));
  useBrokerStore.setState({ accounts: [], activeAccountId: null });
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init) => {
    const path = new URL(String(url), "http://localhost").pathname.replace(/^\/ft-api/, "");
    const method = init?.method ?? "GET";
    const key = new Headers(init?.headers).get("Idempotency-Key");
    requests.push({ method, path, body: init?.body as string | undefined, key });
    if (method === "POST" && path === row.path) {
      try { expect(key).toBe(row.key); expect(init?.body).toBe("{}"); }
      catch (error) { unexpected.push(String(error)); throw error; }
      const reply = nextBody ? await nextBody() : response({ body, status: row.status });
      currentReadout = true;
      return reply;
    }
    if (method === "GET" && path === "/api/v1/native/accounts") {
      if (currentReadout && nextAccounts) return nextAccounts();
      return response((currentReadout ? wire.accountReadouts : wire.expiredAccountReadouts)[row.broker as keyof typeof wire.accountReadouts]);
    }
    if (method === "GET" && path === "/api/v1/native/brokers") return response(wire.catalogue);
    if (method === "GET" && path === "/api/v1/broker/mcp") return response({ body: JSON.stringify({ status: "success", data: { brokers: [] } }), status: 200 });
    unexpected.push(`${method} ${path}`); throw new Error("Unregistered transport");
  });
});
afterEach(context => {
  cleanup(); client.clear(); vi.restoreAllMocks(); resetOperatorSignals();
  if (process.env.FLINTTRADE_ACCOUNT_RESULT_LEDGER) appendFileSync(process.env.FLINTTRADE_ACCOUNT_RESULT_LEDGER,
    JSON.stringify({ case: context.task.name, sample: row.id, requests, unexpected }) + "\n");
  expect(unexpected).toEqual([]);
});
function select(sample: Sample) { row = sample; body = row.body; }
function login() { return reloginNativeAccount(row.broker, row.accountId, undefined, row.key); }
function soleWrite() {
  expect(requests.filter(r => r.method !== "GET")).toEqual([{ method: "POST", path: row.path, body: "{}", key: row.key }]);
}
it("retains the exact completed producer recovery through the exported client", async () => {
  expect(await login()).toEqual(JSON.parse(row.body)); soleWrite();
});
for (const caller of ["exported client", "reconnect facade"] as const) {
  describe(caller, () => {
    it.each(wire.samples)("retains literal $id", async sample => {
      select(sample);
      const result = caller === "exported client" ? await login() : await reconnectBrokerAccount({ source: "native", broker: row.broker, account_id: row.accountId }, row.key);
      expect(result).toEqual(JSON.parse(row.body)); soleWrite();
    });
  });
}
it("keeps original recovery receipt distinct from actual restart session unavailability", async () => {
  select(wire.samples.find(s => s.key === JSON.parse(wire.restartReplay.body).receipt.operationId)!);
  const installed = await login(); body = wire.restartReplay.body;
  const restarted = await login();
  expect(restarted).toEqual(JSON.parse(wire.restartReplay.body));
  expect("receipt" in restarted && "receipt" in installed && restarted.receipt).toEqual("receipt" in installed && installed.receipt);
  expect(restarted).not.toHaveProperty("recovery");
  expect(requests.filter(r => r.method === "POST")).toHaveLength(2);
});
it("keeps genuine committed cleanup continuation separate from recovery", async () => {
  row = { ...row, path: wire.cleanupContinuation.path, accountId: "Synthetic", key: JSON.parse(wire.cleanupContinuation.body).receipt.operationId };
  body = wire.cleanupContinuation.body;
  expect(await login()).toEqual(JSON.parse(body)); soleWrite();
});
it("accepts reordered JSON fields without treating key order as authority", async () => {
  const value = JSON.parse(row.body);
  body = JSON.stringify({ runtimeStatus: value.runtimeStatus, recovery: value.recovery, receipt: value.receipt });
  expect(await login()).toEqual(value); soleWrite();
});
const corruptions: Array<[string, string, unknown]> = [
  ["absent recovery", "recovery", undefined], ["null recovery", "recovery", null],
  ["foreign broker", "recovery.broker", "kotakneo"], ["foreign account", "recovery.accountId", "Foreign"],
  ["case-only account", "recovery.accountId", "mounted"], ["missing account", "recovery.accountId", undefined],
  ["readOnly false", "recovery.readOnly", false], ["readOnly string", "recovery.readOnly", "true"],
  ["missing readOnly", "recovery.readOnly", undefined], ["write authority", "recovery.writeAuthority", "entry"],
  ["missing write authority", "recovery.writeAuthority", undefined], ["grant authority", "recovery.grantAuthority", "entry"],
  ["missing grant authority", "recovery.grantAuthority", undefined], ["reconciliation false", "recovery.reconciliationRequired", false],
  ["missing reconciliation", "recovery.reconciliationRequired", undefined], ["absent census", "recovery.census", undefined],
  ["incomplete census", "recovery.census.complete", false], ["missing completeness", "recovery.census.complete", undefined],
  ["absent revision", "recovery.census.revision", undefined], ["invalid revision", "recovery.census.revision", "f"],
  ["uppercase revision", "recovery.census.revision", "F".repeat(64)], ["empty runs", "recovery.census.runIds", []],
  ["missing runs", "recovery.census.runIds", undefined], ["duplicate runs", "recovery.census.runIds", ["a", "a"]],
  ["mixed runs", "recovery.census.runIds", ["a", 1]], ["empty run", "recovery.census.runIds", [""]],
  ["extra metadata", "recovery.secret", "never-echo"], ["extra census", "recovery.census.flat", true],
  ["reordered response operation", "receipt.operationId", wire.samples[1].key], ["wrong operation kind", "receipt.kind", "connect"],
  ["uncommitted recovery", "receipt.state", "authentication_unknown"], ["unknown status", "runtimeStatus", "future_recovery"],
  ["recovery on ordinary status", "runtimeStatus", "session_present"], ["stale recovery on replay", "runtimeStatus", "session_unavailable"],
];
function corrupt(path: string, value: unknown) {
  const payload = JSON.parse(row.body); const parts = path.split(".");
  let owner = payload;
  for (const part of parts.slice(0, -1)) owner = owner[part];
  if (value === undefined) delete owner[parts.at(-1)!]; else owner[parts.at(-1)!] = value;
  body = JSON.stringify(payload);
}
it.each(corruptions)("refuses %s at the exported client", async (_name, path, value) => {
  corrupt(path, value); await expect(login()).rejects.toThrow(/outcome unavailable/i); soleWrite();
});
for (const surface of ["setup", "settings"] as const) {
  describe(`${surface} recovery mounted caller`, () => {
    function mount() {
      vi.spyOn(crypto, "randomUUID").mockReturnValue(row.key as `${string}-${string}-${string}-${string}-${string}`);
      const child = surface === "setup" ? <ConnectedAccounts /> : <BrokerConnect />;
      const view = render(<QueryClientProvider client={client}><Activity mode="visible">{child}</Activity></QueryClientProvider>);
      return { ...view, child };
    }
    async function submit() {
      fireEvent.click(await screen.findByRole("button", { name: surface === "setup" ? `Reconnect ${row.broker}` : `Re-authenticate ${row.broker} ${row.accountId}` }));
      await waitFor(() => expect(requests.filter(r => r.method === "POST")).toHaveLength(1));
    }
    it("keeps the independent recovered account visibly read-only after receipt disposal", async () => {
      currentReadout = true; mount();
      expect(await screen.findByText(/dhan.*· read-only/)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /set.*primary/i })).not.toBeInTheDocument();
      expect(requests.filter(r => r.method !== "GET")).toEqual([]);
    });
    it.each(wire.samples)("renders literal $id without inferring write readiness", async sample => {
      select(sample); mount(); await submit();
      const unknown = JSON.parse(row.body).receipt.state === "authentication_unknown";
      const notice = await screen.findByText(unknown ? /authentication outcome unknown; blocked/i : /read-only recovery for/i);
      if (!unknown) {
        expect(notice).toHaveTextContent(`${row.broker} / ${row.accountId}`);
        expect(notice).toHaveTextContent(/Reconciliation required.*No write or grant authority.*Publication-time owner census reference only; not current books, flatness, or entry readiness/i);
      }
      expect(screen.queryByText(/fresh credentials below|re-authenticated\./i)).not.toBeInTheDocument();
      await waitFor(() => expect(useBrokerStore.getState().accounts.find(a => a.broker === row.broker && a.account_id === row.accountId)).toMatchObject({ read_only: true, status: "connected" }));
      const accounts = useBrokerStore.getState().accounts;
      const account = accounts.find(a => a.broker === row.broker && a.account_id === row.accountId)!;
      // Independent real account-list HTTP, never derived from recovery census.
      expect(account).toMatchObject({ read_only: true, read_smoke_ok: false, status: "connected" });
      expect(pickNativeWriteTargetFromState("live", "", accounts, `native:${row.broker}:${row.accountId}`)).toBeUndefined();
      expect(canPromotePrimaryAccount(account)).toBe(false);
      expect(screen.queryByRole("button", { name: /^Start$|^Grant$/i })).not.toBeInTheDocument();
      soleWrite();
    });
    it.each(corruptions.filter(([name]) => ["absent recovery", "foreign account", "reordered response operation", "missing reconciliation", "unknown status"].includes(name)))("renders %s refusal without fresh credentials or auth retry", async (_name, path, value) => {
      corrupt(path, value); mount(); await submit();
      expect(await screen.findByText(/account outcome unavailable/i)).toBeInTheDocument();
      expect(screen.queryByText(/read-only recovery for|fresh credentials below/i)).not.toBeInTheDocument(); soleWrite();
    });
    it("does not clear an independent broker fault on restricted recovery", async () => {
      const fault = { message: "Book source unavailable", httpStatus: 503, broker: "dhan" };
      mount();
      await screen.findByRole("button", { name: surface === "setup" ? `Reconnect ${row.broker}` : `Re-authenticate ${row.broker} ${row.accountId}` });
      act(() => useOperatorSignalStore.setState({ brokerReject: fault }));
      let release!: (value: Response) => void;
      nextAccounts = () => new Promise(resolve => { release = resolve; });
      try {
        await submit();
        expect(await screen.findByText(/read-only recovery for/i)).toBeInTheDocument();
        await waitFor(() => expect(release).toBeTypeOf("function"));
        // The mutation result alone cannot clear a read fault. The existing
        // independent account-query recovery policy is tested separately.
        expect(useOperatorSignalStore.getState().brokerReject).toEqual(fault); soleWrite();
      } finally {
        await act(async () => { release?.(response(wire.accountReadouts.dhan)); });
      }
    });
    it("renders actual restarted replay separately from an independently recovered account list", async () => {
      select(wire.samples.find(s => s.key === JSON.parse(wire.restartReplay.body).receipt.operationId)!);
      body = wire.restartReplay.body; mount(); await submit();
      expect(await screen.findByText(/committed.*current session unavailable/i)).toBeInTheDocument();
      expect(screen.queryByText(/read-only recovery for|fresh credentials below/i)).not.toBeInTheDocument(); soleWrite();
    });
    it.each(["account-return", "hidden-return"])("fences late recovery across %s", async retirement => {
      let resolve!: (value: Response) => void;
      nextBody = () => new Promise(r => { resolve = r; });
      const view = mount(); await submit();
      expect(resolve).toBeTypeOf("function");
      if (retirement === "account-return") act(() => {
        useBrokerStore.setState({ activeAccountId: "native:dhan:Other" });
        useBrokerStore.setState({ activeAccountId: null });
      });
      else {
        view.rerender(<QueryClientProvider client={client}><Activity mode="hidden">{view.child}</Activity></QueryClientProvider>);
        view.rerender(<QueryClientProvider client={client}><Activity mode="visible">{view.child}</Activity></QueryClientProvider>);
      }
      const reads = requests.filter(r => r.method === "GET").length;
      await act(async () => { resolve(response(row)); });
      expect(screen.queryByText(/read-only recovery for|fresh credentials below|re-authenticated\./i)).not.toBeInTheDocument();
      expect(requests.filter(r => r.method === "GET")).toHaveLength(reads); soleWrite();
    });
  });
}
