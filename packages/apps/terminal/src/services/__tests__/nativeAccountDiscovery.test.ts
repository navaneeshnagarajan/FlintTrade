/** Real public market clients and native discovery; only HTTP is inert. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getHistory, getIntervals, getMultiQuotes, getQuotes } from "../api";
import { listNativeAccounts } from "../ftApi.native";
import { useAuthStore } from "@/stores/authStore";
import { useBrokerStore } from "@/stores/brokerStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";
import { PRIMARY_NATIVE_ACCOUNT, SECONDARY_NATIVE_ACCOUNT, resetAccountRuntime, setAccountRuntime } from "@/test-utils/accountQueryHarness";

const DISCOVERY = "/ft-api/api/v1/native/accounts";
const REFUSAL = "Credential store unavailable.";
let requests: Array<{ signal?: AbortSignal | null; reply: (value: Response) => void; fail: (error: unknown) => void }>;
let failures: string[];
let dataResponses: Map<string, unknown>;
let dataReads: string[];

function refusal() {
  return new Response(JSON.stringify({ status: "error", message: REFUSAL }), {
    status: 503, headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  requests = []; failures = [];
  dataResponses = new Map(); dataReads = [];
  setAccountRuntime({ accounts: [], mode: "practice" });
  useAuthStore.setState({ status: "logged-in", username: "Synthetic", token: null });
  vi.stubGlobal("fetch", (input: RequestInfo | URL, init: RequestInit = {}) => {
    try {
      expect(init.method ?? "GET").toBe("GET");
      expect(init.body).toBeUndefined();
      if (dataResponses.has(String(input))) {
        dataReads.push(String(input));
        return Promise.resolve(new Response(JSON.stringify({ status: "success", data: dataResponses.get(String(input)) })));
      }
      expect(String(input)).toBe(DISCOVERY);
      return new Promise<Response>((reply, fail) => { requests.push({ signal: init.signal, reply, fail }); });
    } catch (error) { failures.push(String(error)); throw error; }
  });
});

afterEach(() => {
  requests.forEach(({ reply }) => reply(refusal()));
  resetAccountRuntime();
  useAuthStore.setState({ status: "logged-out", username: null, token: null });
  vi.unstubAllGlobals();
  expect(failures).toEqual([]);
  expect([...dataReads].sort()).toEqual([...dataResponses.keys()].sort());
});

function success(accounts: unknown[] = []) {
  return new Response(JSON.stringify({ status: "success", data: { accounts } }), { headers: { "Content-Type": "application/json" } });
}

const changes = [
  { name: "account A-B-A", change: () => { useBrokerStore.getState().setActiveAccount("native:upstox:B2"); useBrokerStore.getState().setActiveAccount("native:dhan:A1"); } },
  { name: "provider replacement", change: () => useBrokerStore.getState().updateAccount("native:dhan:A1", { broker: "upstox" }) },
  { name: "session incarnation", change: () => useAuthStore.setState((s) => ({ sessionGeneration: s.sessionGeneration + 1 })) },
  { name: "logout-login", change: () => { useAuthStore.setState({ status: "logged-out" }); useAuthStore.setState({ status: "logged-in" }); } },
  { name: "token replacement", change: () => useAuthStore.setState({ token: "synthetic-replacement" }) },
  { name: "operator replacement", change: () => useAuthStore.setState({ username: "Other synthetic operator" }) },
  { name: "credential replacement", change: () => useConnectionStore.setState({ apiKey: "synthetic-key" }) },
  { name: "connection disconnect-return", change: () => { useConnectionStore.getState().setStatus("disconnected"); useConnectionStore.getState().setStatus("connected"); } },
  { name: "mode round trip", change: () => { useModeStore.setState({ mode: "live" }); useModeStore.setState({ mode: "practice" }); } },
  { name: "broker disconnect-return", change: () => { useBrokerStore.getState().updateAccount("native:dhan:A1", { status: "disconnected" }); useBrokerStore.getState().updateAccount("native:dhan:A1", { status: "connected" }); } },
  { name: "broker session expiry", change: () => useBrokerStore.getState().updateAccount("native:dhan:A1", { expires_at: 1 }) },
  { name: "broker readiness retirement", change: () => useBrokerStore.getState().updateAccount("native:dhan:A1", { needs_relogin: true }) },
];

describe("native account discovery shared acquisition", () => {
  it("retains each original client's exact data read after shared successful discovery", async () => {
    setAccountRuntime({ mode: "practice", accounts: [PRIMARY_NATIVE_ACCOUNT], activeAccountId: "native:dhan:A1" });
    const base = `${DISCOVERY}/dhan/A1`;
    const quote = { symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 100, open: 98, high: 101, low: 97, close: 99, prev_close: 99, volume: 2 };
    const bars = [{ timestamp: 1767225600, open: 98, high: 101, low: 97, close: 100, volume: 2 }];
    dataResponses.set("/ft-api/api/v1/broker/capabilities?broker=dhan", { capabilities: { historical_intervals: ["1d"] } });
    dataResponses.set(`${base}/quotes?symbols=NSE_INDEX%3ANIFTY`, [quote]);
    dataResponses.set(`${base}/quotes?symbol=NIFTY&exchange=NSE_INDEX`, quote);
    dataResponses.set(`${base}/history?symbol=NIFTY&exchange=NSE_INDEX&interval=1d&start_date=2026-01-01&end_date=2026-01-02`, bars);
    const scope = "practice:native:dhan:A1";
    const outcomes = Promise.all([
      getMultiQuotes([{ symbol: "NIFTY", exchange: "NSE_INDEX" }], undefined, scope),
      getIntervals(undefined, scope),
      getQuotes("NIFTY", "NSE_INDEX", undefined, scope),
      getHistory("NIFTY", "NSE_INDEX", "1d", "2026-01-01", "2026-01-02", undefined, scope),
    ]);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(requests).toHaveLength(1);
    requests[0].reply(success([{ adapter_id: "dhan", account_id: "A1", has_session: true, is_primary: true }]));
    expect(await outcomes).toEqual([{ results: [{ symbol: "NIFTY", exchange: "NSE_INDEX", data: quote }] }, ["1d"], quote, bars]);
  });

  it.each([
    ["null payload", null], ["missing collection", {}], ["null collection", { accounts: null }],
    ["array payload", []], ["object collection", { accounts: {} }],
    ["invalid row", { accounts: [null] }], ["partial row", { accounts: [{ adapter_id: "dhan" }] }],
    ["blank identity", { accounts: [{ adapter_id: "dhan", account_id: " " }] }],
    ["coerced session flag", { accounts: [{ adapter_id: "dhan", account_id: "A1", has_session: "true" }] }],
    ["malformed suffix", { accounts: [{ adapter_id: "dhan", account_id: "A1" }, {}] }],
    ["coerced readiness", { accounts: [{ adapter_id: "dhan", account_id: "A1", read_smoke_ok: 1 }] }],
    ["invalid expiry", { accounts: [{ adapter_id: "dhan", account_id: "A1", expires_at: "later" }] }],
  ])("refuses %s as unavailable rather than certifying empty discovery", async (_name, data) => {
    const result = Promise.allSettled([listNativeAccounts()]);
    requests[0].reply(new Response(JSON.stringify({ status: "success", data })));
    expect(await result).toMatchObject([{ status: "rejected", reason: { message: "Native account discovery is unavailable or malformed." } }]);
  });

  it.each(["success", "refusal"])("does not reuse a settled %s even in the same task", async (outcome) => {
    const first = Promise.allSettled([listNativeAccounts()]);
    requests[0].reply(outcome === "success" ? success() : refusal());
    await first;
    const second = Promise.allSettled([listNativeAccounts()]);
    const count = requests.length;
    requests[1]?.reply(success([{ adapter_id: "dhan", account_id: "A1", label: null, expires_at: null, extra: { untouched: true } }]));
    expect(await second).toEqual([{ status: "fulfilled", value: [{ adapter_id: "dhan", account_id: "A1", label: null, expires_at: null, extra: { untouched: true } }] }]);
    expect(count).toBe(2);
  });

  it("settles a cancelled public borrower before the ignored transport finishes", async () => {
    const controller = new AbortController();
    let cancelled: unknown;
    void listNativeAccounts(controller.signal).catch((error: unknown) => { cancelled = error; });
    const survivor = listNativeAccounts();
    controller.abort(new DOMException("view retired", "AbortError"));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(cancelled).toMatchObject({ name: "AbortError", message: "view retired" });
    expect(requests[0].signal?.aborted).toBe(false);
    requests[0].reply(success([{ adapter_id: "dhan", account_id: "A1", has_session: true }]));
    expect(await survivor).toEqual([{ adapter_id: "dhan", account_id: "A1", has_session: true }]);
  });

  it("does not retire a legitimate borrower for display-only account changes", async () => {
    setAccountRuntime({ accounts: [PRIMARY_NATIVE_ACCOUNT], mode: "practice" });
    const result = listNativeAccounts();
    useBrokerStore.getState().updateAccount("native:dhan:A1", { label: "New display name" });
    expect(requests[0].signal?.aborted).toBe(false);
    requests[0].reply(success());
    expect(await result).toEqual([]);
  });

  it.each(["fetch", "body decoding"])("preserves %s failure identity for every borrower and releases the slot", async (kind) => {
    const failure = new TypeError("synthetic native fetch failure");
    const response = success();
    vi.spyOn(response, "json").mockRejectedValue(failure);
    const results = Promise.allSettled([listNativeAccounts(), listNativeAccounts()]);
    if (kind === "fetch") requests[0].fail(failure);
    else requests[0].reply(response);
    for (const outcome of await results) {
      expect(outcome.status).toBe("rejected");
      if (outcome.status === "rejected") expect(outcome.reason).toBe(failure);
    }
    const next = listNativeAccounts();
    expect(requests).toHaveLength(2);
    requests[1].reply(success());
    expect(await next).toEqual([]);
  });

  it("preserves truly empty accounts", async () => {
    const result = listNativeAccounts(); requests[0].reply(success());
    expect(await result).toEqual([]);
  });

  it.each(changes)("fences a held decoded body after $name without reviving A", async ({ change }) => {
    setAccountRuntime({ mode: "practice", accounts: [PRIMARY_NATIVE_ACCOUNT, SECONDARY_NATIVE_ACCOUNT], activeAccountId: "native:dhan:A1" });
    useConnectionStore.getState().setStatus("connected");
    const old = Promise.allSettled([
      listNativeAccounts(), getQuotes("NIFTY", "NSE_INDEX", undefined, "practice:native:dhan:A1"),
    ]);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(requests).toHaveLength(1);
    let decode!: (value: unknown) => void;
    let entered!: () => void;
    const decoding = new Promise<void>((resolve) => { entered = resolve; });
    const response = success();
    vi.spyOn(response, "json").mockImplementation(() => {
      entered(); return new Promise((resolve) => { decode = resolve; });
    });
    requests[0].reply(response);
    await decoding;
    change();
    const retired = requests[0].signal?.aborted;
    const fresh = Promise.allSettled([listNativeAccounts()]);
    const started = requests.length;
    decode({ status: "success", data: { accounts: [] } });
    await new Promise((resolve) => setTimeout(resolve, 0));
    const joined = Promise.allSettled([listNativeAccounts()]);
    requests.slice(1).forEach(({ reply }) => reply(success()));
    expect(await old).toMatchObject([
      { status: "rejected", reason: { name: "MarketDataAuthorityChangedError" } },
      { status: "rejected", reason: { name: "MarketDataAuthorityChangedError" } },
    ]);
    expect(await fresh).toEqual([{ status: "fulfilled", value: [] }]);
    expect(await joined).toEqual([{ status: "fulfilled", value: [] }]);
    expect(retired).toBe(true);
    expect(started).toBe(2);
    expect(requests).toHaveLength(2);
  });
  it.each([0, 1])("cancelling borrower %s leaves the other original client alive", async (cancelled) => {
    const controllers = [new AbortController(), new AbortController()];
    const results = Promise.allSettled([
      getIntervals(controllers[0].signal, "practice:unconfigured"),
      getQuotes("NIFTY", "NSE_INDEX", controllers[1].signal, "practice:unconfigured"),
    ]);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(requests).toHaveLength(1);
    controllers[cancelled].abort();
    const transportAborted = requests[0].signal?.aborted;
    requests[0].reply(refusal());
    const settled = await results;
    expect(settled[cancelled]).toMatchObject({ status: "rejected", reason: { name: "AbortError" } });
    expect(settled[1 - cancelled]).toMatchObject({ status: "rejected", reason: { name: "FtApiError", message: REFUSAL, status: 503 } });
    expect(transportAborted).toBe(false);
  });

  it("retires the last borrower immediately and never revives its delayed transport", async () => {
    const controller = new AbortController();
    const old = Promise.allSettled([listNativeAccounts(controller.signal)]);
    controller.abort();
    const retired = requests[0].signal?.aborted;
    const fresh = Promise.allSettled([listNativeAccounts()]);
    const started = requests.length;
    requests[0].reply(new Response(JSON.stringify({ data: { accounts: [{ adapter_id: "dhan", account_id: "OLD" }] } })));
    await new Promise((resolve) => setTimeout(resolve, 0));
    // A late old completion must not clear the current flight's slot.
    const joined = Promise.allSettled([listNativeAccounts()]);
    requests.slice(1).forEach(({ reply }) => reply(refusal()));
    expect(await old).toMatchObject([{ status: "rejected", reason: { name: "AbortError" } }]);
    expect(await fresh).toMatchObject([{ status: "rejected", reason: { message: REFUSAL } }]);
    expect(await joined).toMatchObject([{ status: "rejected", reason: { message: REFUSAL } }]);
    expect(retired).toBe(true);
    expect(started).toBe(2);
    expect(requests).toHaveLength(2);
  });

  it("does not acquire for an already cancelled caller", async () => {
    const controller = new AbortController(); controller.abort();
    const result = Promise.allSettled([listNativeAccounts(controller.signal)]);
    const count = requests.length;
    requests.forEach(({ reply }) => reply(refusal()));
    expect(await result).toMatchObject([{ status: "rejected", reason: { name: "AbortError" } }]);
    expect(count).toBe(0);
  });

  it("shares one held native refusal across all four original Terminal public clients", async () => {
    const scope = "practice:unconfigured";
    const results = Promise.allSettled([
      getMultiQuotes([{ symbol: "NIFTY", exchange: "NSE_INDEX" }], undefined, scope),
      getIntervals(undefined, scope),
      getQuotes("NIFTY", "NSE_INDEX", undefined, scope),
      getHistory("NIFTY", "NSE_INDEX", "1d", "2026-01-01", "2026-01-02", undefined, scope),
    ]);
    // post() first awaits the ordinary Practice/account-routing gates. Drain
    // this task's promise continuations while discovery itself remains held.
    await new Promise((resolve) => setTimeout(resolve, 0));
    const started = requests.length;
    requests.forEach(({ reply }) => reply(refusal()));
    const settled = await results;
    expect(settled).toHaveLength(4);
    for (const result of settled) {
      expect(result.status).toBe("rejected");
      if (result.status === "rejected") expect(result.reason).toMatchObject({ name: "FtApiError", message: REFUSAL, status: 503 });
    }
    expect(started).toBe(1);
  });
});
