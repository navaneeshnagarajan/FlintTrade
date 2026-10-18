/** Real Trade Review tabs, stores, queries and decoders; synthetic HTTP only. */
import { onlineManager, QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { act, cleanup, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/authStore";
import {
  PRIMARY_NATIVE_ACCOUNT,
  PRIMARY_SCOPE,
  SECONDARY_NATIVE_ACCOUNT,
  setNativeAccountStatus,
  forceExactRefetch,
  renderAccountSurface,
  resetAccountRuntime,
  setAccountRuntime,
} from "@/test-utils/accountQueryHarness";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import ModeHonestyBar from "@/chrome/ModeHonestyBar";
import { queryKeys } from "@/services/queryKeys";
import TradeJournalTool from "../TradeJournalTool";
import { sevenDaysAgoISO, todayISO } from "../utils";

const TRADES_A = "/ft-api/api/v1/native/accounts/dhan/A1/trades";
const ORDERS_A = "/ft-api/api/v1/native/accounts/dhan/A1/orders";
const TRADES_B = "/ft-api/api/v1/native/accounts/upstox/B2/trades";
const ORDERS_B = "/ft-api/api/v1/native/accounts/upstox/B2/orders";
const PRACTICE_TRADES = "/ft-api/v1/sandbox/trades";
const PRACTICE_ORDERS = "/ft-api/v1/sandbox/orders";
const OPEN_FILL = {
  tradeId: "synthetic-buy", orderId: "synthetic-entry", symbol: "SYNTHETIC-A", exchange: "NSE",
  action: "BUY", quantity: 75, price: 100, timestamp: "2026-09-09T09:20:00",
};
const CLOSED_FILLS = [OPEN_FILL, {
  ...OPEN_FILL, tradeId: "synthetic-sell", orderId: "synthetic-exit", action: "SELL",
  price: 110, timestamp: "2026-09-09T09:50:00",
}];
let JOURNAL: string;
const SCREENSHOTS = "/ft-api/api/v1/journal/screenshots";
const EMPTY_ORDERS = "Orders: 0 placed, 0 filled, 0 rejected, 0 pending";
const routes = new Map<string, (init: RequestInit) => Response | Promise<Response>>();
const unexpected: string[] = [];
const clients: QueryClient[] = [];
const clockStart = Date.now();
let scenarioNumber = 0;

function response(data: unknown, status = 200): Response {
  const body = status >= 400 ? { status: "error", message: "Synthetic account read unavailable" } : { status: "success", data };
  return new Response(JSON.stringify(body), {
    status, headers: { "Content-Type": "application/json" },
  });
}

function get(url: string, handler: () => Response | Promise<Response>) {
  routes.set(`GET ${url}`, (init) => {
    expect(init.body).toBeUndefined();
    expect(new Headers(init.headers).has("Authorization")).toBe(false);
    expect(new Headers(init.headers).has("X-API-Key")).toBe(false);
    return handler();
  });
}

const fetchMock = vi.fn((input: RequestInfo | URL, init: RequestInit = {}) => {
  const key = `${init.method ?? "GET"} ${String(input)}`;
  try {
    const handler = routes.get(key);
    if (!handler) throw new Error(`Unregistered synthetic request: ${key}`);
    return Promise.resolve(handler(init)).catch((error: unknown) => {
      // Async fixture assertions must not be swallowed as a product refusal.
      if (error instanceof Error && error.name === "AssertionError") unexpected.push(`${key}: ${error}`);
      throw error;
    });
  } catch (error) {
    unexpected.push(`${key}: ${String(error)}`);
    return Promise.reject(error);
  }
});

function countReads(url: string) {
  return fetchMock.mock.calls.filter(([input, init]) => String(input) === url && (init?.method ?? "GET") === "GET").length;
}

function holdRead(url: string) {
  let resolve!: (value: Response) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<Response>((res, rej) => { resolve = res; reject = rej; });
  const held = { entered: false, resolve, reject };
  get(url, () => { held.entered = true; return promise; });
  return held;
}

function ReviewSurface() {
  const mode = useModeStore((state) => state.mode);
  return <><ModeHonestyBar mode={mode} /><TradeJournalTool /></>;
}

async function openSession() {
  const view = renderAccountSurface(() => <ReviewSurface />);
  clients.push(view.client);
  await userEvent.setup().click(screen.getByRole("tab", { name: "Session" }));
  return {
    ...view,
    session: within(screen.getByLabelText("Session statistics")),
    redraw: () => view.rerender(<QueryClientProvider client={view.client}><ReviewSurface /></QueryClientProvider>),
  };
}

function expectNoSamples() {
  const session = within(screen.getByLabelText("Session statistics"));
  expect(session.queryByText("NIFTY 22200 CE")).not.toBeInTheDocument();
  expect(session.queryByText("+₹12,850")).not.toBeInTheDocument();
  expect(session.queryByLabelText("Orders: 14 placed, 12 filled, 1 rejected, 1 pending")).not.toBeInTheDocument();
}

beforeEach(() => {
  // Keep the production limiter and query timers. Advance only wall time,
  // monotonically even after a case ages its cache, to isolate HTTP budgets.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(clockStart + ++scenarioNumber * 60_000);
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  routes.clear();
  unexpected.length = 0;
  fetchMock.mockClear();
  useAuthStore.setState({ token: null });
  setAccountRuntime({ activeAccountId: brokerAccountKey(PRIMARY_NATIVE_ACCOUNT) });
  JOURNAL = `/ft-api/api/v1/trades/journal?start_date=${sevenDaysAgoISO()}&end_date=${todayISO()}&limit=`;
  onlineManager.setOnline(true);
  // The real tool and its initial Log share this key but request different
  // explicit page sizes; neither read may fall through to blanket GET success.
  get(`${JOURNAL}1000`, () => response({ trades: [], total: 0 }));
  get(`${JOURNAL}200`, () => response({ trades: [], total: 0 }));
  get(SCREENSHOTS, () => response([]));
  get(TRADES_A, () => response([]));
  get(ORDERS_A, () => response([]));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  resetAccountRuntime();
  onlineManager.setOnline(true);
  vi.unstubAllGlobals();
  vi.useRealTimers();
  expect(unexpected).toEqual([]);
});

describe("Session truth through Trade Review", () => {
  it.each([
    { condition: "invalidated", empty: false }, { condition: "aged", empty: false },
    { condition: "invalidated", empty: true }, { condition: "aged", empty: true },
  ] as const)("S2/S3: $condition idle books retain independently labelled evidence (empty=$empty)", async ({ condition, empty }) => {
    get(TRADES_A, () => response(empty ? [] : CLOSED_FILLS));
    const { client, session, redraw } = await openSession();
    await session.findByText(empty ? "No round trips closed yet today." : "1W / 0L");
    await session.findByLabelText(EMPTY_ORDERS);
    const reads = fetchMock.mock.calls.length;
    if (condition === "invalidated") {
      await act(async () => { await client.invalidateQueries({ queryKey: queryKeys.orders.list(PRIMARY_SCOPE), exact: true, refetchType: "none" }); });
    } else {
      vi.setSystemTime(Date.now() + 6_000);
    }
    redraw();
    expect(await session.findByText("Orders stale — showing the last available order book.")).toBeInTheDocument();
    expect(session.getByLabelText("Last available orders: 0 placed, 0 filled, 0 rejected, 0 pending")).toBeInTheDocument();
    expect(session.queryByLabelText(EMPTY_ORDERS)).not.toBeInTheDocument();
    expect(session.queryByText("Trades stale — showing the last available fills.")).not.toBeInTheDocument();
    if (!empty) expect(session.getByText("Live")).toBeInTheDocument();

    if (condition === "invalidated") {
      await act(async () => { await client.invalidateQueries({ queryKey: queryKeys.tradebook.list(PRIMARY_SCOPE), exact: true, refetchType: "none" }); });
    } else {
      vi.setSystemTime(Date.now() + 10_000);
    }
    redraw();
    expect(client.getQueryCache().find({ queryKey: queryKeys.tradebook.list(PRIMARY_SCOPE), exact: true })?.isStaleByTime(15_000)).toBe(true);
    expect(client.getQueryState(queryKeys.tradebook.list(PRIMARY_SCOPE))?.fetchStatus).toBe("idle");
    expect(client.getQueryState(queryKeys.orders.list(PRIMARY_SCOPE))?.fetchStatus).toBe("idle");
    expect(await session.findByText("Trades stale — showing the last available fills.")).toBeInTheDocument();
    expect(session.getAllByText(empty ? "+₹0" : "+₹750").length).toBeGreaterThan(0);
    expect(session.getByLabelText("Last available orders: 0 placed, 0 filled, 0 rejected, 0 pending")).toBeInTheDocument();
    expect(session.queryByText("Live")).not.toBeInTheDocument();
    if (empty) expect(session.getByText("No closed round trips in the last available fills.")).toBeInTheDocument();
    else expect(session.getByText("Live · stale")).toBeInTheDocument();
    expect(fetchMock.mock.calls).toHaveLength(reads);
    expect(countReads(TRADES_A)).toBe(1);
    expect(countReads(ORDERS_A)).toBe(1);
    expectNoSamples();
  });

  it("S3: a fresh-cache in-flight refetch stays current until canonical freshness changes", async () => {
    get(TRADES_A, () => response(CLOSED_FILLS));
    const { client, session } = await openSession();
    await session.findByText("1W / 0L");
    await session.findByLabelText(EMPTY_ORDERS);
    const trades = holdRead(TRADES_A);
    const orders = holdRead(ORDERS_A);
    const refetches: Promise<void>[] = [];
    try {
      act(() => {
        refetches.push(client.refetchQueries({ queryKey: queryKeys.tradebook.list(PRIMARY_SCOPE), exact: true }));
        refetches.push(client.refetchQueries({ queryKey: queryKeys.orders.list(PRIMARY_SCOPE), exact: true }));
      });
      await waitFor(() => { expect(trades.entered).toBe(true); expect(orders.entered).toBe(true); });
      expect(client.getQueryState(queryKeys.tradebook.list(PRIMARY_SCOPE))?.fetchStatus).toBe("fetching");
      expect(session.getByText("Live")).toBeInTheDocument();
      expect(session.getByLabelText(EMPTY_ORDERS)).toBeInTheDocument();
      expect(session.queryByText(/stale|unavailable/i)).not.toBeInTheDocument();
      await act(async () => { await client.invalidateQueries({ queryKey: queryKeys.tradebook.list(PRIMARY_SCOPE), exact: true, refetchType: "none" }); });
      await session.findByText("Trades stale — showing the last available fills.");
      expect(session.getByLabelText(EMPTY_ORDERS)).toBeInTheDocument();
      expect(session.getAllByText("+₹750").length).toBeGreaterThan(0);
      expect(countReads(TRADES_A)).toBe(2);
      expect(countReads(ORDERS_A)).toBe(2);
    } finally {
      await act(async () => { trades.resolve(response(CLOSED_FILLS)); orders.resolve(response([])); await Promise.all(refetches); });
    }
    await session.findByText("Live");
    expect(session.queryByText(/stale|unavailable/i)).not.toBeInTheDocument();
  });

  it.each(["trades", "orders"] as const)("S2: a null Practice %s book is unavailable, not zero success", async (book) => {
    setAccountRuntime({ mode: "practice" });
    const tradePhases: string[] = [];
    const orderPhases: string[] = [];
    let phase = "Log";
    get(PRACTICE_TRADES, () => {
      tradePhases.push(phase);
      return response({ trades: book === "trades" ? null : CLOSED_FILLS });
    });
    get(PRACTICE_ORDERS, () => {
      orderPhases.push(phase);
      return response({ orders: book === "orders" ? null : [] });
    });
    const { client } = renderAccountSurface(() => <ReviewSurface />);
    clients.push(client);
    expect(screen.getByRole("tab", { name: "Log" })).toHaveAttribute("data-state", "active");
    // The real current-day Practice Log owns the first trade observer. Settle
    // its result before mounting Session, rather than racing two observers.
    if (book === "trades") await screen.findByText("Fills unavailable — retry above");
    await waitFor(() => expect(client.getQueryState(queryKeys.tradebook.list("practice:sandbox:default"))).toMatchObject({
      status: book === "trades" ? "error" : "success", fetchStatus: "idle",
    }));
    expect(tradePhases).toEqual(["Log"]);
    expect(orderPhases).toEqual([]);
    expect(countReads(PRACTICE_TRADES)).toBe(1);
    expect(countReads(PRACTICE_ORDERS)).toBe(0);

    phase = "Session";
    await userEvent.setup().click(screen.getByRole("tab", { name: "Session" }));
    const session = within(screen.getByLabelText("Session statistics"));
    expect(await session.findByText(book === "trades" ? "Trades unavailable." : "Orders unavailable.")).toBeInTheDocument();
    // retry:false disables automatic retries, not the new observer's normal
    // error-on-mount fetch. A successful fresh Log book is reused instead.
    expect(tradePhases).toEqual(book === "trades" ? ["Log", "Session"] : ["Log"]);
    expect(orderPhases).toEqual(["Session"]);
    expect(countReads(PRACTICE_TRADES)).toBe(book === "trades" ? 2 : 1);
    expect(countReads(PRACTICE_ORDERS)).toBe(1);
    if (book === "trades") {
      expect(session.queryByText("No round trips closed yet today.")).not.toBeInTheDocument();
      expect(session.queryByText("+₹0")).not.toBeInTheDocument();
      expect(session.getByLabelText(EMPTY_ORDERS)).toBeInTheDocument();
    } else {
      expect(session.queryByLabelText(EMPTY_ORDERS)).not.toBeInTheDocument();
      expect(session.getAllByText("+₹750").length).toBeGreaterThan(0);
    }
    expectNoSamples();
  });

  it.each(["resolve", "reject"] as const)("S3: a late A %s cannot contaminate connected B", async (outcome) => {
    setAccountRuntime({ accounts: [PRIMARY_NATIVE_ACCOUNT, SECONDARY_NATIVE_ACCOUNT], activeAccountId: brokerAccountKey(PRIMARY_NATIVE_ACCOUNT) });
    get(TRADES_A, () => response(CLOSED_FILLS));
    const { client, session } = await openSession();
    expect(await session.findByText("1W / 0L")).toBeInTheDocument();
    const aTrades = holdRead(TRADES_A);
    const aOrders = holdRead(ORDERS_A);
    const bTrades = holdRead(TRADES_B);
    const bOrders = holdRead(ORDERS_B);
    const pending: Promise<void>[] = [];
    try {
      act(() => {
        pending.push(client.refetchQueries({ queryKey: queryKeys.tradebook.list(PRIMARY_SCOPE), exact: true }));
        pending.push(client.refetchQueries({ queryKey: queryKeys.orders.list(PRIMARY_SCOPE), exact: true }));
      });
      await waitFor(() => expect(aTrades.entered && aOrders.entered).toBe(true));
      act(() => useBrokerStore.setState({ activeAccountId: brokerAccountKey(SECONDARY_NATIVE_ACCOUNT) }));
      expect(session.getByText("Loading trades…")).toBeInTheDocument();
      expect(session.getByText("Loading orders…")).toBeInTheDocument();
      expect(session.queryByText("+₹750")).not.toBeInTheDocument();
      expectNoSamples();
      await waitFor(() => expect(bTrades.entered && bOrders.entered).toBe(true));
      await act(async () => {
        bTrades.resolve(response(CLOSED_FILLS.map((fill) => ({ ...fill, symbol: "SYNTHETIC-B", price: fill.action === "SELL" ? 102 : 100 }))));
        bOrders.resolve(response([]));
      });
      expect(await session.findByLabelText(EMPTY_ORDERS)).toBeInTheDocument();
      expect(session.getAllByText("+₹150").length).toBeGreaterThan(0);
      await act(async () => {
        if (outcome === "resolve") {
          aTrades.resolve(response(CLOSED_FILLS));
          aOrders.resolve(response([{ status: "rejected" }]));
        } else {
          aTrades.reject(new Error("Retired A trade request failed"));
          aOrders.reject(new Error("Retired A order request failed"));
        }
        await Promise.all(pending);
      });
      expect(session.getAllByText("+₹150").length).toBeGreaterThan(0);
      expect(session.queryByText("+₹750")).not.toBeInTheDocument();
      expect(session.queryByText("SYNTHETIC-A")).not.toBeInTheDocument();
      expect(session.getByLabelText(EMPTY_ORDERS)).toBeInTheDocument();
      expect(session.queryByText(/stale|unavailable/i)).not.toBeInTheDocument();
      expect(countReads(TRADES_A)).toBe(2);
      expect(countReads(ORDERS_A)).toBe(2);
      expect(countReads(TRADES_B)).toBe(1);
      expect(countReads(ORDERS_B)).toBe(1);
    } finally {
      await act(async () => {
        for (const request of [aTrades, aOrders, bTrades, bOrders]) request.resolve(response([]));
        await Promise.all(pending);
      });
    }
  });

  it.each(["disconnected", "paused", "offline-idle"] as const)("S2/S3: a cached zero book is visibly stale when %s", async (condition) => {
    const { client, session } = await openSession();
    expect(await session.findByText("No round trips closed yet today.")).toBeInTheDocument();
    expect(session.getByLabelText(EMPTY_ORDERS)).toBeInTheDocument();
    if (condition === "disconnected") setNativeAccountStatus(PRIMARY_NATIVE_ACCOUNT, "disconnected");
    else {
      act(() => { onlineManager.setOnline(false); });
      if (condition === "paused") {
        await forceExactRefetch(client, queryKeys.tradebook.list(PRIMARY_SCOPE));
        await forceExactRefetch(client, queryKeys.orders.list(PRIMARY_SCOPE));
        expect(client.getQueryState(queryKeys.tradebook.list(PRIMARY_SCOPE))?.fetchStatus).toBe("paused");
        expect(client.getQueryState(queryKeys.orders.list(PRIMARY_SCOPE))?.fetchStatus).toBe("paused");
      }
    }
    expect(await session.findByText("Trades stale — showing the last available fills.")).toBeInTheDocument();
    expect(session.getByText("Orders stale — showing the last available order book.")).toBeInTheDocument();
    expect(session.queryByText("No round trips closed yet today.")).not.toBeInTheDocument();
    expect(session.getByText("No closed round trips in the last available fills.")).toBeInTheDocument();
    expect(session.queryByLabelText(EMPTY_ORDERS)).not.toBeInTheDocument();
    expect(session.getByLabelText("Last available orders: 0 placed, 0 filled, 0 rejected, 0 pending")).toBeInTheDocument();
    expect(countReads(TRADES_A)).toBe(1);
    expect(countReads(ORDERS_A)).toBe(1);
    expectNoSamples();
  });

  it.each(["explore", "live", "practice"] as const)("S4: explicit Explore owns fixed samples after starting in %s", async (initialMode) => {
    setAccountRuntime({ mode: initialMode });
    get(TRADES_A, () => response(CLOSED_FILLS));
    get(PRACTICE_TRADES, () => response({ trades: CLOSED_FILLS }));
    get(PRACTICE_ORDERS, () => response({ orders: [] }));
    const { session } = await openSession();
    if (initialMode !== "explore") expect(await session.findByText("1W / 0L")).toBeInTheDocument();
    const requestsBeforeExplore = fetchMock.mock.calls.length;
    act(() => useModeStore.setState({ mode: "explore" }));
    expect(session.getByText("+₹12,850")).toBeInTheDocument();
    expect(session.getByLabelText("Orders: 14 placed, 12 filled, 1 rejected, 1 pending")).toBeInTheDocument();
    const log = within(session.getByRole("table", { name: "Today's trade log" }));
    expect(log.getAllByRole("row")).toHaveLength(8);
    expect(log.getByText("NIFTY 22200 CE")).toBeInTheDocument();
    expect(log.getByText("09:18")).toBeInTheDocument();
    expect(session.queryByText("SYNTHETIC-A")).not.toBeInTheDocument();
    expect(session.queryByText("Live")).not.toBeInTheDocument();
    expect(session.queryByText("Practice")).not.toBeInTheDocument();
    expect(screen.getByTestId("mode-honesty-bar")).toHaveTextContent("Example data. No broker is connected and no orders are sent.");
    expect(session.queryByText(/Sample data/i)).not.toBeInTheDocument();
    expect(fetchMock.mock.calls).toHaveLength(requestsBeforeExplore);
    if (initialMode === "explore") expect(fetchMock).not.toHaveBeenCalled();
  });

  it("S3: retains same-scope cached evidence visibly stale after independent refetch failures", async () => {
    get(TRADES_A, () => response(CLOSED_FILLS));
    get(ORDERS_A, () => response([{ orderId: "synthetic-entry", symbol: "SYNTHETIC-A", status: "complete" }]));
    const { client, session } = await openSession();
    expect(await session.findByLabelText("Orders: 1 placed, 1 filled, 0 rejected, 0 pending")).toBeInTheDocument();
    expect(session.getByText("1W / 0L")).toBeInTheDocument();
    get(TRADES_A, () => response(null, 503));
    await forceExactRefetch(client, queryKeys.tradebook.list(PRIMARY_SCOPE));
    expect(await session.findByText("Trades stale — showing the last available fills.")).toBeInTheDocument();
    expect(session.getAllByText("+₹750").length).toBeGreaterThan(0);
    expect(session.getByLabelText("Orders: 1 placed, 1 filled, 0 rejected, 0 pending")).toBeInTheDocument();
    get(ORDERS_A, () => response(null, 409));
    await forceExactRefetch(client, queryKeys.orders.list(PRIMARY_SCOPE));
    expect(await session.findByText("Orders stale — showing the last available order book.")).toBeInTheDocument();
    expect(session.getByLabelText("Last available orders: 1 placed, 1 filled, 0 rejected, 0 pending")).toBeInTheDocument();
    expect(session.getAllByText("+₹750").length).toBeGreaterThan(0);
    expectNoSamples();
    expect(countReads(TRADES_A)).toBe(2);
    expect(countReads(ORDERS_A)).toBe(2);
  });

  it.each(["live", "practice"] as const)("S3: pairs restored %s fills with the correct mode provenance", async (mode) => {
    setAccountRuntime({ mode });
    const fills = CLOSED_FILLS.map((fill) => ({ ...fill, strategy: "Restored from backup" }));
    const tradesUrl = mode === "practice" ? PRACTICE_TRADES : TRADES_A;
    const ordersUrl = mode === "practice" ? PRACTICE_ORDERS : ORDERS_A;
    get(tradesUrl, () => response(mode === "practice" ? { trades: fills } : fills));
    get(ordersUrl, () => response(mode === "practice" ? { orders: [] } : []));
    const { session } = await openSession();
    expect(await session.findByText(mode === "practice" ? "Practice" : "Live")).toBeInTheDocument();
    expect(session.queryByText(mode === "practice" ? "Live" : "Practice")).not.toBeInTheDocument();
    const log = within(session.getByRole("table", { name: "Today's trade log" }));
    expect(log.getByText("SYNTHETIC-A")).toBeInTheDocument();
    expect(log.getByText("+₹750")).toBeInTheDocument();
    expect(log.getByText("30m")).toBeInTheDocument();
    expect(log.getByText("Restored")).toHaveAttribute("title", "Restored from backup. Not sent to a broker or checked by Laya.");
    expect(session.getByLabelText(EMPTY_ORDERS)).toBeInTheDocument();
    expectNoSamples();
    expect(countReads(tradesUrl)).toBe(1);
    expect(countReads(ordersUrl)).toBe(1);
    if (mode === "practice") expect(countReads(TRADES_A)).toBe(0);
  });

  it("S3: a genuine breakeven closed trade remains numeric zero, not unavailable", async () => {
    get(TRADES_A, () => response(CLOSED_FILLS.map((fill) => ({ ...fill, price: 100 }))));
    const { session } = await openSession();
    expect(await session.findByText("Live")).toBeInTheDocument();
    const log = within(session.getByRole("table", { name: "Today's trade log" }));
    expect(log.getAllByRole("row")).toHaveLength(2);
    expect(log.getByText("+₹0")).toBeInTheDocument();
    expect(session.queryByText(/unavailable|stale/i)).not.toBeInTheDocument();
    expect(session.queryByText("No round trips closed yet today.")).not.toBeInTheDocument();
    expectNoSamples();
  });

  describe.each(["trades", "orders"] as const)("S2: independent %s failures", (book) => {
    it.each([
      { name: "transport rejection", reply: () => Promise.reject(new Error("Synthetic connection lost")) },
      { name: "read freeze", reply: () => response(null, 409) },
      { name: "unsupported", reply: () => response(null, 501) },
      { name: "invalid JSON", reply: () => new Response("{invalid-json", { status: 200 }) },
      { name: "null book", reply: () => response(null) },
      { name: "missing book", reply: () => response({}) },
      { name: "wrong book type", reply: () => response({ [book]: "unreadable" }) },
      { name: "partial malformed book", reply: () => response([null]) },
    ])("does not turn $name into zero success", async ({ reply }) => {
      get(TRADES_A, () => response(CLOSED_FILLS));
      get(book === "trades" ? TRADES_A : ORDERS_A, reply);
      const { session } = await openSession();
      expect(await session.findByText(book === "trades" ? "Trades unavailable." : "Orders unavailable.")).toBeInTheDocument();
      if (book === "trades") {
        expect(session.queryByText("+₹0")).not.toBeInTheDocument();
        expect(session.queryByText("No round trips closed yet today.")).not.toBeInTheDocument();
        expect(session.queryByRole("table", { name: "Today's trade log" })).not.toBeInTheDocument();
        expect(session.getByLabelText(EMPTY_ORDERS)).toBeInTheDocument();
      } else {
        expect(session.queryByLabelText(EMPTY_ORDERS)).not.toBeInTheDocument();
        expect(session.getAllByText("+₹750").length).toBeGreaterThan(0);
        expect(session.getByText("1W / 0L")).toBeInTheDocument();
      }
      expectNoSamples();
      expect(countReads(TRADES_A)).toBe(1);
      expect(countReads(ORDERS_A)).toBe(1);
    });
  });

  it.each(["disconnected", "unconfigured", "offline"] as const)("S2: %s reads are unavailable, not an empty session", async (condition) => {
    if (condition === "offline") onlineManager.setOnline(false);
    else setAccountRuntime({ accounts: condition === "unconfigured" ? [] : [{ ...PRIMARY_NATIVE_ACCOUNT, status: "disconnected" }] });
    const { session } = await openSession();
    expect(await session.findByText("Trades unavailable.")).toBeInTheDocument();
    expect(session.getByText("Orders unavailable.")).toBeInTheDocument();
    expect(session.queryByText("+₹0")).not.toBeInTheDocument();
    expect(session.queryByText("No round trips closed yet today.")).not.toBeInTheDocument();
    expect(session.queryByLabelText(EMPTY_ORDERS)).not.toBeInTheDocument();
    expectNoSamples();
    expect(countReads(TRADES_A)).toBe(0);
    expect(countReads(ORDERS_A)).toBe(0);
  });

  it("S2: distinguishes deferred trade and order reads from successful emptiness", async () => {
    const trades = holdRead(TRADES_A);
    const orders = holdRead(ORDERS_A);
    try {
      const { session } = await openSession();
      await waitFor(() => expect(trades.entered && orders.entered).toBe(true));
      expect(session.getByText("Loading trades…")).toBeInTheDocument();
      expect(session.getByText("Loading orders…")).toBeInTheDocument();
      expect(session.queryByText("No round trips closed yet today.")).not.toBeInTheDocument();
      expect(session.queryByText("+₹0")).not.toBeInTheDocument();
      expect(session.queryByLabelText(EMPTY_ORDERS)).not.toBeInTheDocument();
      expectNoSamples();
      await act(async () => trades.resolve(response([])));
      expect(await session.findByText("No round trips closed yet today.")).toBeInTheDocument();
      expect(session.getByText("Loading orders…")).toBeInTheDocument();
      expect(session.queryByLabelText(EMPTY_ORDERS)).not.toBeInTheDocument();
      await act(async () => orders.resolve(response([])));
      expect(await session.findByLabelText(EMPTY_ORDERS)).toBeInTheDocument();
    } finally {
      await act(async () => { trades.resolve(response([])); orders.resolve(response([])); });
    }
  });

  it.each([
    { mode: "live", fills: "empty" }, { mode: "practice", fills: "empty" },
    { mode: "live", fills: "open-only" }, { mode: "practice", fills: "open-only" },
  ] as const)("S1: shows no closed trips for $mode $fills fills, never examples", async ({ mode, fills }) => {
    setAccountRuntime({ mode, activeAccountId: brokerAccountKey(PRIMARY_NATIVE_ACCOUNT) });
    const tradesUrl = mode === "practice" ? PRACTICE_TRADES : TRADES_A;
    const ordersUrl = mode === "practice" ? PRACTICE_ORDERS : ORDERS_A;
    const rows = fills === "empty" ? [] : [OPEN_FILL];
    get(tradesUrl, () => response(mode === "practice" ? { trades: rows } : rows));
    get(ordersUrl, () => response(mode === "practice" ? { orders: [] } : []));
    const { session } = await openSession();
    await waitFor(() => expect(countReads(tradesUrl)).toBe(1));
    await waitFor(() => expect(countReads(ordersUrl)).toBe(1));
    expect(await session.findByText("No round trips closed yet today.")).toBeInTheDocument();
    expect(session.getByLabelText(EMPTY_ORDERS)).toBeInTheDocument();
    expect(within(session.getByRole("table", { name: "Today's trade log" })).getAllByRole("row")).toHaveLength(1);
    expect(session.getByText("+₹0")).toBeInTheDocument();
    expectNoSamples();
    expect(countReads(tradesUrl)).toBe(1);
    expect(countReads(ordersUrl)).toBe(1);
    if (mode === "practice") {
      expect(countReads(TRADES_A)).toBe(0);
      expect(countReads(ORDERS_A)).toBe(0);
    }
    expect(countReads(`${JOURNAL}200`) + countReads(`${JOURNAL}1000`)).toBe(1);
  });
});
