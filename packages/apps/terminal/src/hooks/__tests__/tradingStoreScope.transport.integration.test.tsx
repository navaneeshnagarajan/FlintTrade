/** Public FDR-001 regressions: real query hooks, decoder, mirror and consumers. */
import { QueryClient, QueryClientProvider, onlineManager } from "@tanstack/react-query";
import { useLayoutEffect } from "react";
import { MemoryRouter } from "react-router";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { queryKeys } from "@/services/queryKeys";
import { useTradingStoreSync } from "@/hooks/useTradingStoreSync";
import { useAccountReadContext } from "@/hooks/useAccountReadsEnabled";
import { usePrimaryBannerKind } from "@/hooks/usePrimaryBannerKind";
import TerminalRoute from "@/routes/TerminalRoute";
import DailyWelcome from "@/components/welcome/DailyWelcome";
import { useSettingsStore } from "@/stores/settingsStore";
import { useOperatorSignalStore } from "@/stores/operatorSignalStore";
import { useAuthStore } from "@/stores/authStore";
import { useModeStore } from "@/stores/modeStore";
import { registerAuthenticatedQueryCachePurge } from "@/lib/authenticatedQueryCache";
import { WelcomeCard } from "@/routes/home/WelcomeCard";
import { PositionsCard } from "@/routes/home/PositionsCard";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { useTradingStore } from "@/stores/tradingStore";
import {
  PRIMARY_NATIVE_ACCOUNT as A,
  SECONDARY_NATIVE_ACCOUNT as B,
  resetAccountRuntime,
  setAccountRuntime,
  forceExactRefetch,
  setNativeAccountStatus,
} from "@/test-utils/accountQueryHarness";

const A_SCOPE = "live:native:dhan:A1";
const B_SCOPE = "live:native:upstox:B2";
const A_FUNDS = "/ft-api/api/v1/native/accounts/dhan/A1/funds";
const A_POSITIONS = "/ft-api/api/v1/native/accounts/dhan/A1/positions";
const B_FUNDS = "/ft-api/api/v1/native/accounts/upstox/B2/funds";
const B_POSITIONS = "/ft-api/api/v1/native/accounts/upstox/B2/positions";
const PAPER_FUNDS = "/ft-api/v1/sandbox/funds";
const PAPER_POSITIONS = "/ft-api/v1/sandbox/positions";
const POSITION = {
  symbol: "SYNTHETIC-A", exchange: "NSE", product: "MIS", quantity: 10,
  averagePrice: 100, ltp: 105, pnl: -3000, pnlPercent: -300,
};
const FUNDS = { availableCash: 12345, usedMargin: 200, totalBalance: 12545 };
const SAFETY_A = "/ft-api/api/v1/safety/config?broker=dhan&account_id=A1";
const SAFETY_B = "/ft-api/api/v1/safety/config?broker=upstox&account_id=B2";
const SAFETY = { l5_kill: { is_active: false, reason: "", flatten_complete: true }, l4_pnl: { is_paused: false, is_killed: false } };
// Only unrelated canvas/book panes are inert. The route, safety controls,
// stores, query hooks, API decoders and their transports are all real.
vi.mock("flexlayout-react", async (original) => ({ ...await original<typeof import("flexlayout-react")>(), Layout: () => null }));
vi.mock("@/routes/trade/TradeBottomPanel", () => ({ TradeBottomPanel: () => null }));
const json = (data: unknown) => new Response(JSON.stringify({ status: "success", data }), {
  headers: { "Content-Type": "application/json" },
});
function deferred() {
  let resolve!: (value: Response) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<Response>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject, entered: false };
}
class SyntheticTransportError extends Error {}

type Handler = (init: RequestInit) => Response | Promise<Response>;
const handlers = new Map<string, Handler>();
const entered: string[] = [];
const fixtureFailures: string[] = [];
const pending = new Set<ReturnType<typeof deferred>>();
const clients: QueryClient[] = [];
const clockStart = Date.now();
let scenarioNumber = 0;
const committedCards: Array<{ scope: string; positions: string; welcome: string; risk: string; safety: string; recovery: string }> = [];
const dismiss = () => {};
function get(path: string, handler: Handler) { handlers.set(`GET ${path}`, handler); }
function hold(path: string) {
  const response = deferred();
  pending.add(response);
  get(path, () => { response.entered = true; return response.promise; });
  return response;
}
function count(path: string) { return entered.filter((key) => key === `GET ${path}`).length; }
function selectB() { act(() => { useBrokerStore.getState().setActiveAccount(brokerAccountKey(B)); }); }
function RiskBannerProbe() { return <output aria-label="Primary banner">{usePrimaryBannerKind() ?? "none"}</output>; }
function Surface({ enabled = true, safety = false, daily = false }: { enabled?: boolean; safety?: boolean; daily?: boolean }) {
  const authenticated = useAuthStore((s) => s.status === "logged-in");
  useTradingStoreSync(enabled && authenticated);
  const { identity } = useAccountReadContext();
  // Observe the actual committed DOM before the root's passive mirror effect.
  useLayoutEffect(() => {
    committedCards.push({
      scope: identity.scopeKey,
      positions: screen.getByTestId("positions-card").textContent ?? "",
      welcome: screen.getByTestId("welcome-card").textContent ?? "",
      risk: screen.queryByLabelText("Primary banner")?.textContent ?? "",
      safety: screen.queryByLabelText(/Daily loss alert:|Kill switch status:/)?.textContent ?? "",
      recovery: screen.queryByText("Session recovered")?.closest("[role=alert]")?.textContent ?? "",
    });
  });
  return <><WelcomeCard /><PositionsCard />{safety && <><RiskBannerProbe /><TerminalRoute /></>}{daily && <DailyWelcome onDismiss={dismiss} />}</>;
}
function mount(enabled = true, safety = false, daily = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  clients.push(client);
  registerAuthenticatedQueryCachePurge(() => client.clear());
  if (daily) client.setQueryData(["holidays"], []);
  const view = render(<MemoryRouter><QueryClientProvider client={client}><Surface enabled={enabled} safety={safety} daily={daily} /></QueryClientProvider></MemoryRouter>);
  return {
    client, ...view,
    setEnabled: (next: boolean) => view.rerender(<MemoryRouter><QueryClientProvider client={client}><Surface enabled={next} safety={safety} daily={daily} /></QueryClientProvider></MemoryRouter>),
  };
}
const welcome = () => within(screen.getByTestId("welcome-card"));

beforeEach(() => {
  // Each isolated scenario gets a fresh second of real token-bucket budget.
  // Keep the production limiter intact; only wall time advances between cases.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(clockStart + ++scenarioNumber * 1000);
  handlers.clear(); entered.length = 0; fixtureFailures.length = 0;
  committedCards.length = 0;
  useTradingStore.getState().resetSessionState();
  useAuthStore.setState({ status: "logged-in", token: null, username: "Synthetic" });
  setAccountRuntime({ accounts: [A, B], activeAccountId: brokerAccountKey(A) });
  onlineManager.setOnline(true);
  useSettingsStore.setState({ riskLimits: { ...useSettingsStore.getState().riskLimits, mtmStoploss: 5000 } });
  useOperatorSignalStore.setState({ decisionStatus: "ready" });
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  get(A_FUNDS, () => json(FUNDS));
  get(A_POSITIONS, () => json([POSITION]));
  get(SAFETY_A, () => json(SAFETY));
  get(SAFETY_B, () => json(SAFETY));
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const key = `${init.method ?? "GET"} ${String(input)}`;
    try {
      const handler = handlers.get(key);
      expect(handler, `Unregistered synthetic request: ${key}`).toBeDefined();
      if ((init.method ?? "GET") === "GET") expect(init.body).toBeUndefined();
      // The exact URL includes the immutable broker/account selector. Reads
      // do not send a mode header; no wildcard account or method is admitted.
      expect(new Headers(init.headers).get("X-FlintTrade-Mode")).toBeNull();
      entered.push(key);
      return await handler!(init);
    } catch (error) {
      if (!(error instanceof SyntheticTransportError)) fixtureFailures.push(`${key}: ${String(error)}`);
      throw error;
    }
  });
});

afterEach(async () => {
  cleanup();
  registerAuthenticatedQueryCachePurge(() => {});
  for (const client of clients.splice(0)) client.clear();
  for (const response of pending) response.resolve(json([]));
  pending.clear();
  await Promise.resolve();
  onlineManager.setOnline(true);
  resetAccountRuntime();
  useTradingStore.getState().resetSessionState();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  localStorage.removeItem("flinttrade:sessionActive");
  useAuthStore.setState({ status: "logged-out", token: null, username: null });
  expect(fixtureFailures).toEqual([]);
});

describe("current-account aggregate truth", () => {
  it.each([
    { name: "unavailable", pnl: null, token: "text-text-muted", text: "—" },
    { name: "profit", pnl: 25, token: "text-bullish-text", text: "+₹25" },
    { name: "loss", pnl: -3000, token: "text-bearish-text", text: "-₹3,000" },
  ])("WelcomeCard uses the existing $name colour token without inline styling", async ({ pnl, token, text }) => {
    get(A_POSITIONS, () => pnl === null ? new Response("Positions unavailable", { status: 503 }) : json([{ ...POSITION, pnl }]));
    mount();
    if (pnl === null) await welcome().findByText("Positions unavailable");
    else await welcome().findByText(text);
    const value = welcome().getByText("Today's P&L").nextElementSibling;
    expect(value).toHaveTextContent(text);
    expect(value).toHaveClass(token);
    expect(value).not.toHaveAttribute("style");
  });

  it.each([false, true])("A4 marks offline-idle aggregates stale without losing last-known values (zero=%s)", async (zero) => {
    if (zero) {
      get(A_POSITIONS, () => json([]));
      get(A_FUNDS, () => json({ availableCash: 0, usedMargin: 0, totalBalance: 0 }));
    }
    const { client } = mount();
    const value = zero ? "+₹0" : "-₹3,000";
    await welcome().findByText(value);
    await waitFor(() => expect(useTradingStore.getState()).toMatchObject({ fundsStatus: "ready", positionsStatus: "ready" }));
    const reads = [...entered];

    act(() => { onlineManager.setOnline(false); });

    expect(client.getQueryState(queryKeys.funds.detail(A_SCOPE))?.fetchStatus).toBe("idle");
    expect(client.getQueryState(queryKeys.positions.list(A_SCOPE))?.fetchStatus).toBe("idle");
    expect(entered).toEqual(reads);
    expect(useTradingStore.getState()).toMatchObject({
      fundsStatus: "stale", positionsStatus: "stale",
      totalPnl: zero ? 0 : -3000, positionCount: zero ? 0 : 1,
      availableMargin: zero ? 0 : 12345,
    });
    expect(welcome().getByText(value)).toBeInTheDocument();
    expect(welcome().getByText("Positions stale — last known P&L")).toBeInTheDocument();
    expect(within(screen.getByTestId("positions-card")).getByText("P&L stale — last known value")).toBeInTheDocument();

    act(() => { onlineManager.setOnline(true); });
    await waitFor(() => expect(useTradingStore.getState()).toMatchObject({ fundsStatus: "ready", positionsStatus: "ready" }));
    expect(welcome().queryByText("Positions stale — last known P&L")).not.toBeInTheDocument();
    expect(entered).toEqual(reads);
  });

  it("A4 a fresh-cache in-flight refetch stays ready until canonical freshness changes", async () => {
    const { client } = mount();
    await welcome().findByText("-₹3,000");
    await waitFor(() => expect(useTradingStore.getState().fundsStatus).toBe("ready"));
    const funds = hold(A_FUNDS);
    const positions = hold(A_POSITIONS);
    const refetches: Promise<void>[] = [];
    try {
      act(() => {
        refetches.push(client.refetchQueries({ queryKey: queryKeys.funds.detail(A_SCOPE), exact: true }));
        refetches.push(client.refetchQueries({ queryKey: queryKeys.positions.list(A_SCOPE), exact: true }));
      });
      await waitFor(() => { expect(funds.entered).toBe(true); expect(positions.entered).toBe(true); });
      expect(client.getQueryState(queryKeys.positions.list(A_SCOPE))?.fetchStatus).toBe("fetching");
      expect(useTradingStore.getState()).toMatchObject({ fundsStatus: "ready", positionsStatus: "ready" });
      expect(welcome().queryByText("Positions stale — last known P&L")).not.toBeInTheDocument();
      await act(async () => { await client.invalidateQueries({ queryKey: queryKeys.positions.list(A_SCOPE), exact: true, refetchType: "none" }); });
      await welcome().findByText("Positions stale — last known P&L");
      expect(useTradingStore.getState()).toMatchObject({ fundsStatus: "ready", positionsStatus: "stale" });
      expect(welcome().getByText("-₹3,000")).toBeInTheDocument();
      expect(count(A_FUNDS)).toBe(2);
      expect(count(A_POSITIONS)).toBe(2);
    } finally {
      await act(async () => { funds.resolve(json(FUNDS)); positions.resolve(json([POSITION])); await Promise.all(refetches); });
    }
    await waitFor(() => expect(useTradingStore.getState()).toMatchObject({ fundsStatus: "ready", positionsStatus: "ready" }));
  });

  it("A4 keeps a failed same-scope funds refetch stale independently of current positions", async () => {
    const { client } = mount();
    await welcome().findByText("-₹3,000");
    get(A_FUNDS, () => new Response("Funds refresh failed", { status: 503 }));
    await forceExactRefetch(client, queryKeys.funds.detail(A_SCOPE));
    await waitFor(() => expect(useTradingStore.getState()).toMatchObject({ availableMargin: 12345, fundsStatus: "stale", positionsStatus: "ready" }));
    expect(welcome().getByText("-₹3,000")).toBeInTheDocument();
  });

  it("A5 crash recovery labels same-account cached positions as last known after disconnection", async () => {
    localStorage.setItem("flinttrade:sessionActive", "true");
    mount(true, false, true);
    await welcome().findByText("-₹3,000");
    setNativeAccountStatus(A, "disconnected");
    expect(screen.getByText("Session recovered").closest("[role=alert]")).toHaveTextContent("Last known open positions: 1");
    expect(screen.getByText("Session recovered").closest("[role=alert]")).toHaveTextContent("Positions are stale");
  });

  it("A5 a verified zero open-position count clears recovery rather than hiding every positive control", async () => {
    localStorage.setItem("flinttrade:sessionActive", "true");
    get(A_POSITIONS, () => json([{ ...POSITION, quantity: 0, pnl: 75 }]));
    mount(true, false, true);
    await welcome().findByText("+₹75");
    expect(useTradingStore.getState()).toMatchObject({ positionCount: 0, positionsStatus: "ready" });
    expect(screen.queryByText("Session recovered")).not.toBeInTheDocument();
  });

  it("A4 shared decoder blocker: malformed funds must not become a verified zero balance", async () => {
    get(A_FUNDS, () => json(null));
    const { client } = mount();
    await welcome().findByText("-₹3,000");
    await waitFor(() => expect(client.getQueryState(queryKeys.funds.detail(A_SCOPE))?.fetchStatus).toBe("idle"));
    expect(useTradingStore.getState().fundsStatus).toBe("unavailable");
    expect(useTradingStore.getState().positionsStatus).toBe("ready");
  });

  it("A4 shared decoder blocker: a null Practice book must not become verified empty positions", async () => {
    setAccountRuntime({ mode: "practice", accounts: [] });
    get(PAPER_FUNDS, () => json({ funds: { available_balance: 0, used_margin: 0, current_balance: 0 } }));
    get(PAPER_POSITIONS, () => json({ positions: null }));
    const { client } = mount();
    await waitFor(() => expect(client.getQueryState(queryKeys.positions.list("practice:sandbox:default"))?.fetchStatus).toBe("idle"));
    await waitFor(() => expect(useTradingStore.getState().fundsStatus).toBe("ready"));
    expect(useTradingStore.getState().positionsStatus).toBe("unavailable");
    expect(welcome().queryByText("+₹0")).not.toBeInTheDocument();
  });

  it.each(["resolve", "reject"] as const)("A2 isolates each late A resource %s from current B values, availability and risk", async (outcome) => {
    const fundsA = hold(A_FUNDS);
    const positionsA = hold(A_POSITIONS);
    get(B_FUNDS, () => json({ availableCash: 678, usedMargin: 12, totalBalance: 690 }));
    get(B_POSITIONS, () => json([{ ...POSITION, symbol: "SYNTHETIC-B", pnl: 75 }]));
    mount(true, true);
    await waitFor(() => { expect(fundsA.entered).toBe(true); expect(positionsA.entered).toBe(true); });
    selectB();
    await welcome().findByText("+₹75");
    for (const [response, payload] of [[fundsA, FUNDS], [positionsA, [POSITION]]] as const) {
      await act(async () => {
        if (outcome === "resolve") response.resolve(json(payload));
        else response.reject(new SyntheticTransportError("Retired A transport failed"));
        await response.promise.catch(() => {});
      });
      expect(useTradingStore.getState()).toMatchObject({ scopeKey: B_SCOPE, availableMargin: 678, totalPnl: 75, fundsStatus: "ready", positionsStatus: "ready" });
      expect(welcome().getByText("+₹75")).toBeInTheDocument();
      expect(screen.getByLabelText("Primary banner")).not.toHaveTextContent("live_risk");
      expect(screen.getByLabelText("Kill switch status: inactive")).toBeInTheDocument();
      expect(count(B_FUNDS)).toBe(1); expect(count(B_POSITIONS)).toBe(1);
    }
  });

  it("A3 separates Live and Practice, then restores only Live's own cache", async () => {
    const paperFunds = hold(PAPER_FUNDS);
    const paperPositions = hold(PAPER_POSITIONS);
    mount();
    await welcome().findByText("-₹3,000");
    act(() => { useModeStore.setState({ mode: "practice" }); });
    expect(welcome().queryByText("-₹3,000")).not.toBeInTheDocument();
    await waitFor(() => { expect(paperFunds.entered).toBe(true); expect(paperPositions.entered).toBe(true); });
    await act(async () => { paperFunds.resolve(json({ funds: { available_balance: 800, used_margin: 10, current_balance: 810 } })); });
    await waitFor(() => expect(useTradingStore.getState()).toMatchObject({ availableMargin: 800, positionsStatus: "loading" }));
    await act(async () => { paperPositions.resolve(json({ positions: [{ ...POSITION, symbol: "PAPER", pnl: 44 }] })); });
    await welcome().findByText("+₹44");
    act(() => { useModeStore.setState({ mode: "live" }); });
    await welcome().findByText("-₹3,000");
    expect(welcome().queryByText("+₹44")).not.toBeInTheDocument();
    expect(useTradingStore.getState()).toMatchObject({ scopeKey: A_SCOPE, availableMargin: 12345 });
    expect(count(A_FUNDS)).toBe(1); expect(count(A_POSITIONS)).toBe(1);
  });

  it("A3 Explore retires installed aggregates and keeps the explicit local preview without new reads", async () => {
    mount();
    await welcome().findByText("-₹3,000");
    const reads = [...entered];
    act(() => { useModeStore.setState({ mode: "explore" }); });
    expect(welcome().queryByText("-₹3,000")).not.toBeInTheDocument();
    expect(welcome().getByText("5")).toBeInTheDocument();
    expect(within(screen.getByTestId("positions-card")).getByText("RELIANCE")).toBeInTheDocument();
    expect(useTradingStore.getState()).toMatchObject({ fundsStatus: "unavailable", positionsStatus: "unavailable", totalPnl: 0, availableMargin: 0 });
    expect(entered).toEqual(reads);
  });

  it("A3 real logout retires both cached aggregates and pending old-session responses", async () => {
    const { client } = mount();
    await welcome().findByText("-₹3,000");
    const fundsA = hold(A_FUNDS); const positionsA = hold(A_POSITIONS);
    act(() => { void client.refetchQueries({ queryKey: queryKeys.funds.detail(A_SCOPE), exact: true }); void client.refetchQueries({ queryKey: queryKeys.positions.list(A_SCOPE), exact: true }); });
    await waitFor(() => { expect(fundsA.entered).toBe(true); expect(positionsA.entered).toBe(true); });
    act(() => { useAuthStore.getState().setLoggedOut(); });
    await act(async () => { fundsA.resolve(json(FUNDS)); positionsA.resolve(json([POSITION])); });
    expect(useTradingStore.getState()).toMatchObject({ scopeKey: null, totalPnl: 0, availableMargin: 0, fundsStatus: "unavailable", positionsStatus: "unavailable" });
    expect(welcome().getByText("Positions unavailable")).toBeInTheDocument();
    expect(welcome().queryByText("-₹3,000")).not.toBeInTheDocument();
  });

  it.each([
    { name: "null", payload: null },
    { name: "missing book", payload: {} },
    { name: "null book", payload: { positions: null } },
    { name: "non-array book", payload: { positions: "unreadable" } },
    { name: "null row", payload: [null] },
    { name: "partial book", payload: [POSITION, null] },
  ])("A4 rejects a malformed Live $name rather than advertising a real zero", async ({ payload }) => {
    get(A_POSITIONS, () => json(payload));
    mount();
    await welcome().findByText("Positions unavailable");
    expect(welcome().queryByText("+₹0")).not.toBeInTheDocument();
    expect(within(screen.getByTestId("positions-card")).queryByText("No open positions")).not.toBeInTheDocument();
    expect(useTradingStore.getState().fundsStatus).toBe("ready");
  });

  it("A4 successful empty positions and valid zero funds are genuine zero, not unavailable", async () => {
    get(A_POSITIONS, () => json([]));
    get(A_FUNDS, () => json({ availableCash: 0, usedMargin: 0, totalBalance: 0 }));
    mount();
    await welcome().findByText("+₹0");
    expect(welcome().getByText("0")).toBeInTheDocument();
    expect(useTradingStore.getState()).toMatchObject({ totalPnl: 0, positionCount: 0, availableMargin: 0, fundsStatus: "ready", positionsStatus: "ready" });
    expect(within(screen.getByTestId("positions-card")).getByText("No open positions")).toBeInTheDocument();
    expect(within(screen.getByTestId("positions-card")).getByText("+₹0")).toBeInTheDocument();
  });

  it("A4 a funds-only failure leaves valid positions current", async () => {
    get(A_FUNDS, () => new Response("Funds unavailable", { status: 503 }));
    mount();
    await welcome().findByText("-₹3,000");
    await waitFor(() => expect(useTradingStore.getState()).toMatchObject({ fundsStatus: "unavailable", positionsStatus: "ready", availableMargin: 0 }));
  });

  it.each(["active", "pause", "hard-stop"] as const)("A5 independent backend %s stays visible while aggregates are unavailable", async (state) => {
    hold(A_FUNDS); hold(A_POSITIONS);
    get(SAFETY_A, () => json({ l5_kill: { is_active: state === "active", reason: "Synthetic safety hold", flatten_complete: false }, l4_pnl: { is_paused: state === "pause", is_killed: state === "hard-stop" } }));
    mount(true, true);
    await waitFor(() => expect(screen.getByLabelText("Primary banner")).toHaveTextContent("live_risk"));
    expect(welcome().queryByText("+₹0")).not.toBeInTheDocument();
    if (state === "active") {
      expect(screen.getByLabelText("Kill switch status: active")).toHaveTextContent("broker flattening is incomplete");
      expect(screen.getByRole("button", { name: "Retry emergency broker actions" })).toBeEnabled();
    } else {
      expect(screen.getByRole("button", { name: /Activate emergency kill switch process-wide/ })).toBeEnabled();
    }
  });

  it("A5 kill-switch loading and failed initial status stay visible without aggregates", async () => {
    hold(A_FUNDS); hold(A_POSITIONS);
    const safety = hold(SAFETY_A);
    mount(true, true);
    expect(screen.getByLabelText("Kill switch status: loading")).toBeInTheDocument();
    await waitFor(() => expect(safety.entered).toBe(true));
    await act(async () => { safety.resolve(new Response("Safety unavailable", { status: 503 })); });
    await screen.findByLabelText("Kill switch status: unavailable");
    expect(screen.getByRole("button", { name: /Activate emergency kill switch process-wide/ })).toBeDisabled();
  });

  it("A5 manual emergency activation remains reachable without account aggregates", async () => {
    hold(A_FUNDS); hold(A_POSITIONS);
    const path = "/ft-api/api/v1/safety/kill-switch";
    handlers.set(`POST ${path}`, (init) => {
      expect(JSON.parse(String(init.body))).toEqual({ reason: "Manual kill switch — trader initiated from terminal" });
      expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
      return json({ is_active: true, reason: "Synthetic manual activation", emergency_actions: { complete: false, targets: [], outcomes: [] } });
    });
    mount(true, true);
    await screen.findByLabelText("Kill switch status: inactive");
    fireEvent.click(screen.getByRole("button", { name: /Activate emergency kill switch process-wide/ }));
    await waitFor(() => expect(entered.filter((key) => key === `POST ${path}`)).toHaveLength(1));
  });

  it("A4 exposes aged same-scope aggregates as stale on both cards and keeps a labelled risk warning", async () => {
    const { client } = mount(true, true);
    await screen.findByLabelText("Daily loss alert: ₹3000; kill switch status: inactive");
    await act(async () => { await client.invalidateQueries({ queryKey: queryKeys.positions.list(A_SCOPE), exact: true, refetchType: "none" }); });
    await welcome().findByText("Positions stale — last known P&L");
    expect(within(screen.getByTestId("positions-card")).getByText("P&L stale — last known value")).toBeInTheDocument();
    expect(screen.getByLabelText("Daily loss alert: ₹3000; kill switch status: inactive")).toHaveTextContent("last known P&L");
    expect(screen.getByLabelText("Primary banner")).toHaveTextContent("live_risk");
    expect(useTradingStore.getState().fundsStatus).toBe("ready");
    expect(count(A_POSITIONS)).toBe(1);
  });
  it("A3 retires cached aggregates when the app-root session is disabled", async () => {
    const view = mount();
    await welcome().findByText("-₹3,000");
    view.setEnabled(false);
    expect(welcome().getByText("Positions unavailable")).toBeInTheDocument();
    expect(welcome().queryByText("-₹3,000")).not.toBeInTheDocument();
    expect(useTradingStore.getState()).toMatchObject({ scopeKey: null, fundsStatus: "unavailable", positionsStatus: "unavailable", totalPnl: 0, availableMargin: 0 });
    expect(count(A_FUNDS)).toBe(1);
    expect(count(A_POSITIONS)).toBe(1);
  });
  it("A5 crash recovery never claims A's open positions belong to pending B or infers B is flat", async () => {
    localStorage.setItem("flinttrade:sessionActive", "true");
    hold(B_FUNDS); hold(B_POSITIONS);
    mount(true, false, true);
    await waitFor(() => expect(screen.getByText("Session recovered").closest("[role=alert]")).toHaveTextContent("You have 1 open position"));
    committedCards.length = 0;
    selectB();
    for (const frame of committedCards.filter((frame) => frame.scope === B_SCOPE)) {
      expect(frame.recovery).not.toContain("You have 1 open position");
    }
    expect(screen.getByText("Session recovered").closest("[role=alert]")).toHaveTextContent("Current-account positions are loading");
    expect(screen.getByRole("button", { name: "Review positions now" })).toBeEnabled();
  });
  it("A5 never commits A's daily-loss warning as B's risk or terminal safety presentation", async () => {
    hold(B_FUNDS); hold(B_POSITIONS);
    mount(true, true);
    await screen.findByLabelText("Daily loss alert: ₹3000; kill switch status: inactive");
    expect(screen.getByLabelText("Primary banner")).toHaveTextContent("live_risk");
    committedCards.length = 0;
    selectB();
    await waitFor(() => expect(count(B_POSITIONS)).toBe(1));
    const framesB = committedCards.filter((frame) => frame.scope === B_SCOPE);
    expect(framesB.length).toBeGreaterThan(0);
    for (const frame of framesB) {
      expect(frame.risk).not.toBe("live_risk");
      expect(frame.safety).not.toMatch(/3000|daily limit|MTM limit reached/);
    }
    expect(screen.getByLabelText("Kill switch status: inactive")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Activate emergency kill switch process-wide/ })).toBeEnabled();
  });
  it("A1 never commits a foreign header with the returning account's cached position rows", async () => {
    get(B_FUNDS, () => json({ ...FUNDS, availableCash: 678 }));
    get(B_POSITIONS, () => json([{ ...POSITION, symbol: "SYNTHETIC-B", pnl: 75 }]));
    mount();
    await welcome().findByText("-₹3,000");
    selectB();
    await welcome().findByText("+₹75");
    act(() => { useBrokerStore.getState().setActiveAccount(brokerAccountKey(A)); });
    await welcome().findByText("-₹3,000");
    committedCards.length = 0;
    selectB();
    await welcome().findByText("+₹75");
    const framesB = committedCards.filter((frame) => frame.scope === B_SCOPE);
    expect(framesB.length).toBeGreaterThan(0);
    for (const frame of framesB) {
      expect(frame.positions).not.toContain("-₹3,000");
      expect(frame.welcome).not.toContain("-₹3,000");
    }
  });
  it("A3 retires A for disconnected B and labels only A's returning cache stale", async () => {
    mount();
    await welcome().findByText("-₹3,000");
    setNativeAccountStatus(B, "disconnected");
    selectB();
    expect(welcome().getByText("Positions unavailable")).toBeInTheDocument();
    expect(welcome().queryByText("-₹3,000")).not.toBeInTheDocument();
    expect(useTradingStore.getState()).toMatchObject({ scopeKey: B_SCOPE, fundsStatus: "unavailable", positionsStatus: "unavailable", availableMargin: 0 });
    expect(count(B_FUNDS)).toBe(0);
    expect(count(B_POSITIONS)).toBe(0);
    setNativeAccountStatus(A, "disconnected");
    act(() => { useBrokerStore.getState().setActiveAccount(brokerAccountKey(A)); });
    await welcome().findByText("Positions stale — last known P&L");
    expect(welcome().getByText("-₹3,000")).toBeInTheDocument();
    expect(useTradingStore.getState()).toMatchObject({ scopeKey: A_SCOPE, fundsStatus: "stale", positionsStatus: "stale", availableMargin: 12345 });
    expect(count(A_FUNDS)).toBe(1);
    expect(count(A_POSITIONS)).toBe(1);
  });
  it.each([false, true])("A4 never presents a paused positions read as current (cached=%s)", async (cached) => {
    if (!cached) onlineManager.setOnline(false);
    const { client } = mount();
    if (cached) {
      await welcome().findByText("-₹3,000");
      act(() => { onlineManager.setOnline(false); });
      act(() => { void client.refetchQueries({ queryKey: queryKeys.positions.list(A_SCOPE), exact: true }); });
    }
    await waitFor(() => expect(client.getQueryState(queryKeys.positions.list(A_SCOPE))?.fetchStatus).toBe("paused"));
    await welcome().findByText(cached ? "Positions stale — last known P&L" : "Positions unavailable");
    expect(useTradingStore.getState().positionsStatus).toBe(cached ? "stale" : "unavailable");
    expect(count(A_POSITIONS)).toBe(cached ? 1 : 0);
    expect(welcome().queryByText("+₹0")).not.toBeInTheDocument();
    act(() => { onlineManager.setOnline(true); });
    await waitFor(() => expect(useTradingStore.getState().positionsStatus).toBe("ready"));
    expect(welcome().getByText("-₹3,000")).toBeInTheDocument();
  });
  it("A4 labels cached P&L stale after a failed same-scope refetch without invalidating funds", async () => {
    const { client } = mount();
    await welcome().findByText("-₹3,000");
    get(A_POSITIONS, () => new Response("unavailable", { status: 503 }));
    await forceExactRefetch(client, queryKeys.positions.list(A_SCOPE));
    await welcome().findByText("Positions stale — last known P&L");
    expect(welcome().getByText("-₹3,000")).toBeInTheDocument();
    expect(useTradingStore.getState()).toMatchObject({ positionsStatus: "stale", fundsStatus: "ready", availableMargin: 12345 });
  });
  it.each([409, 501, 503])("A4 reports an initial position refusal %s as unavailable, independently of valid funds", async (status) => {
    get(A_POSITIONS, () => new Response(JSON.stringify({ status: "error", message: "Synthetic book unavailable" }), { status }));
    mount();
    await waitFor(() => expect(useTradingStore.getState().availableMargin).toBe(12345));
    await welcome().findByText("Positions unavailable");
    expect(welcome().queryByText("+₹0")).not.toBeInTheDocument();
    expect(useTradingStore.getState()).toMatchObject({ scopeKey: A_SCOPE, positionsStatus: "unavailable", fundsStatus: "ready" });
  });
  it("A1 retires A immediately while B funds and positions arrive independently", async () => {
    const fundsB = hold(B_FUNDS);
    const positionsB = hold(B_POSITIONS);
    const { client } = mount();
    await welcome().findByText("-₹3,000");
    await waitFor(() => expect(useTradingStore.getState().availableMargin, String(client.getQueryState(queryKeys.funds.detail(A_SCOPE))?.error)).toBe(12345));
    selectB();
    expect(welcome().queryByText("-₹3,000")).not.toBeInTheDocument();
    expect(welcome().queryByText("+₹0")).not.toBeInTheDocument();
    expect(welcome().getByText("Loading positions")).toBeInTheDocument();
    expect(useTradingStore.getState()).toMatchObject({
      scopeKey: B_SCOPE, availableMargin: 0, totalPnl: 0,
      fundsStatus: "loading", positionsStatus: "loading",
    });
    await waitFor(() => { expect(fundsB.entered).toBe(true); expect(positionsB.entered).toBe(true); });
    await act(async () => { fundsB.resolve(json({ availableCash: 678, usedMargin: 12, totalBalance: 690 })); });
    await waitFor(() => expect(useTradingStore.getState()).toMatchObject({
      availableMargin: 678, fundsStatus: "ready", positionsStatus: "loading",
    }));
    expect(welcome().queryByText("-₹3,000")).not.toBeInTheDocument();
    await act(async () => { positionsB.resolve(json([{ ...POSITION, symbol: "SYNTHETIC-B", pnl: 75 }])); });
    await welcome().findByText("+₹75");
    expect(useTradingStore.getState()).toMatchObject({ scopeKey: B_SCOPE, totalPnl: 75, availableMargin: 678, positionsStatus: "ready" });
    expect(count(A_FUNDS)).toBe(1);
    expect(count(A_POSITIONS)).toBe(1);
  });
});
