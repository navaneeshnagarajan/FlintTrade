import { describe, it, expect, vi, beforeEach, afterEach, type MockInstance } from "vitest";

const mockConnectionState = vi.hoisted(() => ({
  host: "http://localhost:5000",
  apiKey: "test-key-123",
  openAlgoHydrated: true,
  status: "connected",
}));

const mockModeState = vi.hoisted(() => ({
  mode: "live",
}));

const mockBrokerState = vi.hoisted(() => ({
  accounts: [] as Array<{ account_id: string; broker: string; source?: string; status?: string; is_primary?: boolean }>,
  activeAccountId: null as string | null,
}));

// ---------------------------------------------------------------------------
// Mock Zustand stores and rate limiters BEFORE importing the module under test.
// vi.mock is hoisted by Vitest, so the factories run before any import.
// ---------------------------------------------------------------------------

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: {
    getState: () => mockConnectionState,
  },
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: {
    getState: () => mockModeState,
  },
}));

vi.mock("@/stores/brokerStore", () => {
  const brokerAccountKey = (account: { account_id: string; broker: string; source?: string }) => [
    account.source ?? "gateway",
    account.broker,
    account.account_id,
  ].map(encodeURIComponent).join(":");
  const findBrokerAccountMatch = <T extends { account_id: string; broker: string; source?: string }>(
    accounts: T[],
    selector: string | null,
  ): T | undefined => {
    if (!selector) return undefined;
    const exact = accounts.find((account) => brokerAccountKey(account) === selector);
    if (exact) return exact;
    const legacy = accounts.filter((account) => account.account_id === selector);
    return legacy.length === 1 ? legacy[0] : undefined;
  };
  return {
    brokerAccountKey,
    findBrokerAccountMatch,
    isBrokerAccountMatch: (
      account: { account_id: string; broker: string; source?: string },
      selector: string | null,
    ) => findBrokerAccountMatch([account], selector) === account,
    useBrokerStore: {
      getState: () => mockBrokerState,
    },
  };
});

vi.mock("@/services/rateLimiter", () => ({
  orderLimiter: { tryConsume: vi.fn(() => true) },
  smartOrderLimiter: { tryConsume: vi.fn(() => true) },
  generalLimiter: { tryConsume: vi.fn(() => true) },
}));

// Now import the functions under test and the mocked limiters
import {
  placeOrder,
  placeGtt,
  modifyGtt,
  cancelGtt,
  basketOrder,
  splitOrder,
  OrderApiError,
  cancelAllOrders,
  exitAllPositions,
  cancelOrder,
  modifyOrder,
  type OrderAuthorityPin,
  orderStatus,
  getGttOrderbook,
  getQuotes,
  getDepth,
  getIntervals,
  getFunds,
  getMargin,
  getHolidays,
  getTimings,
  getMultiOptionGreeks,
  getHistory,
  getExpiry,
  getOptionChain,
  getOptionSymbol,
  getGex,
  getIVSmile,
  getMaxPain,
  getOIProfile,
  getSyntheticFuture,
  getTicker,
  getInstruments,
  getSymbol,
  getBrokerCapabilities,
  getLeverageSettings,
  getChartPreferences,
  updateChartPreferences,
  getAnalyzerStatus,
  sendTelegram,
  ping,
  searchSymbol,
  getHoldings,
  getOrderbook,
  getPositionbook,
  getTradebook,
  getQuoteDetails,
  getBrokerLimits,
  getScripMaster,
  searchScrip,
  getOrderHistory,
  getOrderTrades,
} from "../api";
import {
  orderLimiter,
  generalLimiter,
} from "@/services/rateLimiter";
import {
  CONNECTED_NATIVE_READ_CONTEXT,
  EXPLORE_READ_CONTEXT,
  PRACTICE_READ_CONTEXT,
  UNCONFIGURED_LIVE_READ_CONTEXT,
} from "@/test-utils/accountReadFixtures";
import type { AccountReadContext } from "@/hooks/useAccountReadsEnabled";

const OPENALGO_READ_CONTEXT = Object.freeze({
  identity: Object.freeze({
    mode: "live",
    scopeKey: "live:openalgo:test-scope",
    brokerType: "openalgo",
    accountId: "default",
  }),
  enabled: true,
  host: "",
  apiKey: "test-key-123",
}) satisfies AccountReadContext;

function nativeReadContext(brokerType: string, accountId: string): AccountReadContext {
  return Object.freeze({
    identity: Object.freeze({
      mode: "live" as const,
      scopeKey: `live:native:${brokerType}:${accountId}`,
      brokerType,
      accountId,
    }),
    enabled: true,
    host: "",
    apiKey: "",
  });
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("OpenAlgo API client (api.ts)", () => {
  let fetchSpy: MockInstance<typeof globalThis.fetch>;

  beforeEach(() => {
    fetchSpy = vi.spyOn(globalThis, "fetch");
    // Reset rate limiter mocks to allow requests by default
    vi.mocked(orderLimiter.tryConsume).mockReturnValue(true);
    vi.mocked(generalLimiter.tryConsume).mockReturnValue(true);
    mockConnectionState.apiKey = "test-key-123";
    mockConnectionState.openAlgoHydrated = true;
    mockConnectionState.status = "connected";
    mockModeState.mode = "live";
    mockBrokerState.accounts = [];
    mockBrokerState.activeAccountId = null;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // ---- POST requests ----

  it("POST request sends JSON body with apikey", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { available: 50000 } }),
    );

    await getFunds(OPENALGO_READ_CONTEXT);

    expect(fetchSpy).toHaveBeenCalledOnce();
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/funds");
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual(
      expect.objectContaining({ "Content-Type": "application/json" }),
    );
    const body = JSON.parse(init.body as string);
    expect(body).toHaveProperty("apikey", "test-key-123");
  });

  it("uses the exact captured live native account for funds without account discovery", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: { available_balance: "100.50", used_margin: "20.25", total_balance: "120.75" },
      }),
    );

    const result = await getFunds(nativeReadContext("dhan", "D1"));

    expect(result).toEqual({ availableCash: 100.5, usedMargin: 20.25, totalBalance: 120.75 });
    expect((fetchSpy.mock.calls[0] as [string, RequestInit | undefined])[0]).toContain(
      "/api/v1/native/accounts/dhan/D1/funds",
    );
    expect(fetchSpy).toHaveBeenCalledOnce();
    expect(fetchSpy).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/funds"),
      expect.anything(),
    );
  });

  it("normalises current OpenAlgo funds aliases into the canonical Funds shape", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: { availablecash: "80000.50", utiliseddebits: "19500", totalbalance: "100000" },
      }),
    );

    await expect(getFunds(OPENALGO_READ_CONTEXT)).resolves.toEqual({
      availableCash: 80000.5,
      usedMargin: 19500,
      totalBalance: 100000,
    });
  });

  it("keeps a captured active native position read pinned when mutable stores change", async () => {
    mockConnectionState.apiKey = "";
    mockBrokerState.accounts = [
      { account_id: "D1", broker: "dhan", source: "native" },
      { account_id: "U1", broker: "upstox", source: "native" },
    ];
    mockBrokerState.activeAccountId = "U1";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: [{ symbol: "INFY", quantity: 2 }],
      }),
    );

    const result = await getPositionbook(nativeReadContext("upstox", "U1"));

    expect(result).toEqual([{ symbol: "INFY", quantity: 2 }]);
    expect((fetchSpy.mock.calls[0] as [string, RequestInit | undefined])[0]).toContain(
      "/api/v1/native/accounts/upstox/U1/positions",
    );
  });

  it("uses the broker encoded in context when multiple brokers share an account id", async () => {
    mockConnectionState.apiKey = "";
    mockBrokerState.accounts = [
      { account_id: "SHARED", broker: "dhan", source: "native" },
      { account_id: "SHARED", broker: "upstox", source: "native" },
    ];
    mockBrokerState.activeAccountId = "native:upstox:SHARED";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: [{ symbol: "SBIN", quantity: 5 }],
      }),
    );

    const result = await getPositionbook(nativeReadContext("upstox", "SHARED"));

    expect(result).toEqual([{ symbol: "SBIN", quantity: 5 }]);
    expect((fetchSpy.mock.calls[0] as [string, RequestInit | undefined])[0]).toContain(
      "/api/v1/native/accounts/upstox/SHARED/positions",
    );
  });

  it.each([
    {
      name: "orderbook",
      read: getOrderbook,
      response: [{ orderId: "O-1", symbol: "SBIN", exchange: "NSE" }],
      path: "/api/v1/native/accounts/dhan/A1/orders",
    },
    {
      name: "positionbook",
      read: getPositionbook,
      response: [{ symbol: "SBIN", exchange: "NSE", quantity: 2 }],
      path: "/api/v1/native/accounts/dhan/A1/positions",
    },
    {
      name: "holdings",
      read: getHoldings,
      response: [{ symbol: "RELIANCE", exchange: "NSE", quantity: 2 }],
      path: "/api/v1/native/accounts/dhan/A1/holdings",
    },
    {
      name: "tradebook",
      read: getTradebook,
      response: [{ tradeId: "T-1", orderId: "O-1", symbol: "SBIN", exchange: "NSE" }],
      path: "/api/v1/native/accounts/dhan/A1/trades",
    },
  ])(
    "routes $name through the exact immutable native account context",
    async ({ read, response, path }) => {
      mockConnectionState.apiKey = "mutable-openalgo-key";
      mockBrokerState.accounts = [
        { account_id: "B2", broker: "upstox", source: "native", status: "connected" },
      ];
      mockBrokerState.activeAccountId = "native:upstox:B2";
      fetchSpy.mockResolvedValueOnce(jsonResponse({ status: "success", data: response }));
      const controller = new AbortController();

      await expect(read(CONNECTED_NATIVE_READ_CONTEXT, controller.signal)).resolves.toEqual(response);

      expect(fetchSpy).toHaveBeenCalledOnce();
      const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
      expect(url).toContain(path);
      expect(url).not.toContain("upstox/B2");
      expect(init.signal).toBe(controller.signal);
    },
  );

  it.each([
    ["funds", getFunds],
    ["orderbook", getOrderbook],
    ["positionbook", getPositionbook],
  ])("rejects %s before transport when immutable account context is missing", async (_name, read) => {
    fetchSpy.mockResolvedValue(jsonResponse({ status: "success", data: [] }));

    await expect(
      (read as unknown as (context?: AccountReadContext) => Promise<unknown>)(undefined),
    ).rejects.toThrow("Account read context is required");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("rejects margin before transport when immutable account context is missing", async () => {
    fetchSpy.mockResolvedValue(jsonResponse({ status: "success", data: {} }));

    await expect(
      (getMargin as unknown as (
        context: AccountReadContext | undefined,
        symbol: string,
        exchange: string,
        qty: number,
        product: string,
        action: string,
      ) => Promise<unknown>)(undefined, "INFY", "NSE", 10, "MIS", "BUY"),
    ).rejects.toThrow("Account read context is required");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("rejects margin before transport when immutable Live authority is unavailable", async () => {
    fetchSpy.mockResolvedValue(jsonResponse({ status: "success", data: {} }));

    await expect(
      getMargin(UNCONFIGURED_LIVE_READ_CONTEXT, "INFY", "NSE", 10, "MIS", "BUY"),
    ).rejects.toThrow("Account reads are unavailable");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it.each([
    ["holdings", getHoldings],
    ["tradebook", getTradebook],
  ])(
    "rejects %s before transport when immutable Live authority is unavailable",
    async (_name, read) => {
      fetchSpy.mockResolvedValue(jsonResponse({ status: "success", data: [] }));

      await expect(read(UNCONFIGURED_LIVE_READ_CONTEXT)).rejects.toThrow(
        "Account reads are unavailable",
      );
      expect(fetchSpy).not.toHaveBeenCalled();
    },
  );

  it("fails closed instead of serving another account's data when the active native session lapses", async () => {
    // Wave-2 audit finding: silently falling back to the primary account would
    // render a DIFFERENT real account's positions under the operator's
    // selection with no affordance. The read must fail so the UI surfaces the
    // needs-relogin state.
    mockConnectionState.apiKey = "";
    mockBrokerState.accounts = [
      { account_id: "D1", broker: "dhan", source: "native" },
      { account_id: "U1", broker: "upstox", source: "native" },
    ];
    mockBrokerState.activeAccountId = "U1";
    fetchSpy.mockResolvedValue(
      jsonResponse({
        status: "success",
        data: {
          accounts: [
            { adapter_id: "dhan", account_id: "D1", is_primary: true, has_session: true },
            { adapter_id: "upstox", account_id: "U1", is_primary: false, has_session: false },
          ],
        },
      }),
    );

    await expect(getPositionbook(UNCONFIGURED_LIVE_READ_CONTEXT)).rejects.toThrow(
      "Account reads are unavailable",
    );
    const urls = fetchSpy.mock.calls.map(([url]) => String(url));
    expect(urls.some((url) => url.includes("/api/v1/native/accounts/dhan/D1/positions"))).toBe(false);
  });

  it("reads a caller-captured primary native account without a mutable fallback", async () => {
    mockConnectionState.apiKey = "";
    mockBrokerState.accounts = [];
    mockBrokerState.activeAccountId = null;
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: [{ symbol: "RELIANCE", quantity: 1 }],
      }),
    );

    const result = await getPositionbook(nativeReadContext("dhan", "D1"));

    expect(result).toEqual([{ symbol: "RELIANCE", quantity: 1 }]);
    expect((fetchSpy.mock.calls[0] as [string, RequestInit | undefined])[0]).toContain(
      "/api/v1/native/accounts/dhan/D1/positions",
    );
  });

  it("uses native order status when a live native account is connected without an OpenAlgo key", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: { order_id: "OID-1", order_status: "COMPLETE" },
        }),
      );

    const result = await orderStatus({ orderId: "OID-1" });

    expect(result).toEqual({ status: "COMPLETE" });
    expect((fetchSpy.mock.calls[1] as [string, RequestInit | undefined])[0]).toContain(
      "/api/v1/native/accounts/upstox/U1/orderstatus?order_id=OID-1",
    );
    expect(fetchSpy).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/orderstatus"),
      expect.anything(),
    );
  });

  it("uses native quotes when a live native account is connected without an OpenAlgo key", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: [{ symbol: "INFY", exchange: "NSE", ltp: "1450.25", open: 1440, high: 1460, low: 1430, close: 1448 }],
        }),
      );

    const result = await getQuotes("INFY", "NSE");

    expect(result).toMatchObject({ symbol: "INFY", exchange: "NSE", ltp: 1450.25 });
    expect((fetchSpy.mock.calls[1] as [string, RequestInit | undefined])[0]).toContain(
      "/api/v1/native/accounts/upstox/U1/quotes?symbol=INFY&exchange=NSE",
    );
    expect(fetchSpy).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/quotes"),
      expect.anything(),
    );
  });

  it("rejects a native quote whose LTP is missing instead of materialising zero", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: [{ symbol: "INFY", exchange: "NSE", open: 1440 }],
        }),
      );

    await expect(getQuotes("INFY", "NSE")).rejects.toThrow(/valid positive LTP/i);
  });

  it("uses the native quote route for ticker fallback when no OpenAlgo key is configured", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "dhan", account_id: "D1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: [{ symbol: "RELIANCE", exchange: "NSE", last_price: "3010.75" }],
        }),
      );

    const result = await getTicker("RELIANCE", "NSE");

    expect(result).toMatchObject({ symbol: "RELIANCE", exchange: "NSE", ltp: 3010.75 });
    expect((fetchSpy.mock.calls[1] as [string, RequestInit | undefined])[0]).toContain(
      "/api/v1/native/accounts/dhan/D1/quotes?symbol=RELIANCE&exchange=NSE",
    );
    expect(fetchSpy).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/ticker"),
      expect.anything(),
    );
  });

  it("uses native market depth when a live native account is connected without an OpenAlgo key", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: [{
            symbol: "INFY",
            exchange: "NSE",
            bids: [{ price: "1450.0", quantity: "10", orders: "2" }],
            asks: [{ price: 1450.5, quantity: 8, orders: 1 }],
          }],
        }),
      );

    const result = await getDepth("INFY", "NSE");

    expect(result).toEqual({
      buy: [{ price: 1450, quantity: 10, orders: 2 }],
      sell: [{ price: 1450.5, quantity: 8, orders: 1 }],
    });
    expect((fetchSpy.mock.calls[1] as [string, RequestInit | undefined])[0]).toContain(
      "/api/v1/native/accounts/upstox/U1/depth?symbol=INFY&exchange=NSE",
    );
    expect(fetchSpy).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/depth"),
      expect.anything(),
    );
  });

  it("uses the exact captured native account and AbortSignal for margin", async () => {
    mockConnectionState.apiKey = "mutable-openalgo-key";
    mockBrokerState.accounts = [
      { account_id: "B2", broker: "upstox", source: "native", status: "connected" },
    ];
    mockBrokerState.activeAccountId = "native:upstox:B2";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: {
          required_margin: "2500.5",
          span_margin: "2000.25",
          exposure_margin: "500.25",
        },
      }),
    );
    const controller = new AbortController();

    const result = await getMargin(
      CONNECTED_NATIVE_READ_CONTEXT,
      "INFY",
      "NSE",
      10,
      "MIS",
      "BUY",
      controller.signal,
    );

    expect(result).toMatchObject({
      required_margin: 2500.5,
      total_margin_required: 2500.5,
      span_margin: 2000.25,
      exposure_margin: 500.25,
    });
    expect(fetchSpy).toHaveBeenCalledOnce();
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain(
      "/api/v1/native/accounts/dhan/A1/margin?symbol=INFY&exchange=NSE&qty=10&product=MIS&action=BUY",
    );
    expect(url).not.toContain("upstox/B2");
    expect(init.signal).toBe(controller.signal);
  });

  it("keeps Practice margin on sandbox authority without touching a Live target", async () => {
    mockConnectionState.apiKey = "configured-live-key";
    mockBrokerState.accounts = [
      { account_id: "D1", broker: "dhan", source: "native", status: "connected" },
    ];
    mockBrokerState.activeAccountId = "native:dhan:D1";
    fetchSpy.mockResolvedValue(jsonResponse({ status: "success", data: {} }));
    const controller = new AbortController();

    await expect(
      getMargin(PRACTICE_READ_CONTEXT, "INFY", "NSE", 10, "MIS", "BUY", controller.signal),
    ).rejects.toThrow("margin is not available from the Practice sandbox");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("reads native broker verbs as thin envelope readers with no per-broker branching", async () => {
    // One-core rule: the core facade absorbs broker payload differences and
    // serves canonical shapes, so these clients pass rows through unchanged
    // and EVERY broker uses the same verb — a groww account calls
    // quote_details exactly like kotakneo (the facade falls back server-side).
    mockConnectionState.apiKey = "";
    const accounts = {
      status: "success",
      data: {
        accounts: [
          { adapter_id: "groww", account_id: "G1", is_primary: true, has_session: true },
        ],
      },
    };
    fetchSpy
      .mockResolvedValueOnce(jsonResponse(accounts))
      .mockResolvedValueOnce(jsonResponse({
        status: "success",
        data: [{ symbol: "INFY", exchange: "NSE", ltp: 1450.25 }],
      }))
      .mockResolvedValueOnce(jsonResponse(accounts))
      .mockResolvedValueOnce(jsonResponse({ status: "success", data: { segment: "CASH" } }))
      .mockResolvedValueOnce(jsonResponse(accounts))
      .mockResolvedValueOnce(jsonResponse({ status: "success", data: { segments: [{ exchange: "NSE" }] } }))
      .mockResolvedValueOnce(jsonResponse(accounts))
      .mockResolvedValueOnce(jsonResponse({ status: "success", data: [{ symbol: "NIFTY", token: "12345" }] }))
      .mockResolvedValueOnce(jsonResponse(accounts))
      .mockResolvedValueOnce(jsonResponse({ status: "success", data: [{ order_id: "OID-1", status: "OPEN" }] }))
      .mockResolvedValueOnce(jsonResponse(accounts))
      .mockResolvedValueOnce(jsonResponse({ status: "success", data: [{ order_id: "OID-1", trade_id: "T1" }] }));

    await expect(getQuoteDetails("INFY", "NSE", "ltp")).resolves.toEqual(
      [{ symbol: "INFY", exchange: "NSE", ltp: 1450.25 }],
    );
    await expect(getBrokerLimits("CASH", "NSE", "MIS")).resolves.toMatchObject({ segment: "CASH" });
    await expect(getScripMaster("NSE")).resolves.toMatchObject({ segments: [{ exchange: "NSE" }] });
    await expect(searchScrip("NIFTY", { exchange: "NFO" })).resolves.toEqual(
      [{ symbol: "NIFTY", token: "12345" }],
    );
    await expect(getOrderHistory("OID-1")).resolves.toEqual([{ order_id: "OID-1", status: "OPEN" }]);
    await expect(getOrderTrades("OID-1")).resolves.toEqual([{ order_id: "OID-1", trade_id: "T1" }]);

    const urls = fetchSpy.mock.calls.map(([url]) => String(url));
    // The SAME quote_details verb for a non-Kotak broker — no client-side
    // adapter_id branch, no client-side ltp reshaping.
    expect(urls.some((url) => url.includes(
      "/api/v1/native/accounts/groww/G1/quote_details?symbol=INFY&exchange=NSE&quote_type=ltp",
    ))).toBe(true);
    expect(urls.some((url) => url.includes("/api/v1/native/accounts/groww/G1/limits"))).toBe(true);
    expect(urls.some((url) => url.includes("/api/v1/native/accounts/groww/G1/orderhistory?order_id=OID-1"))).toBe(true);
  });

  it("uses native market calendar reads when a live native account is connected without an OpenAlgo key", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: [{
            date: "2026-08-15",
            description: "Independence Day",
            holiday_type: "SPECIAL_SESSION",
            closed_exchanges: ["NSE", "BSE"],
            open_exchanges: [{
              exchange: "NSE",
              start_time: "1786811400000",
              end_time: "1786815000000",
            }],
          }],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: [{ exchange: "NSE", start_time: "1718595000000", end_time: "1718618400000" }],
        }),
      );

    const holidays = await getHolidays();
    const timings = await getTimings();

    expect(holidays).toEqual([{
      date: "2026-08-15",
      description: "Independence Day",
      holiday_type: "SPECIAL_SESSION",
      closed_exchanges: ["NSE", "BSE"],
      open_exchanges: [{
        exchange: "NSE",
        start_time: 1786811400000,
        end_time: 1786815000000,
      }],
    }]);
    expect(timings).toEqual([
      { exchange: "NSE", start_time: 1718595000000, end_time: 1718618400000 },
    ]);
    expect((fetchSpy.mock.calls[1] as [string, RequestInit | undefined])[0]).toContain(
      "/api/v1/native/accounts/upstox/U1/holidays",
    );
    expect((fetchSpy.mock.calls[3] as [string, RequestInit | undefined])[0]).toContain(
      "/api/v1/native/accounts/upstox/U1/timings",
    );
    expect(fetchSpy).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/holidays"),
      expect.anything(),
    );
    expect(fetchSpy).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/timings"),
      expect.anything(),
    );
  });

  it.each([
    "2026-08-15 00:00:00+05:30",
    "2026-08-15T00:00:00.000Z",
  ])("normalises a valid Upstox _date datetime %s to its calendar date", async (_date) => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: [{
            _date,
            description: "Independence Day",
            holiday_type: "TRADING_HOLIDAY",
            closed_exchanges: ["NSE", "BSE"],
            open_exchanges: [],
          }],
        }),
      );

    await expect(getHolidays()).resolves.toEqual([
      {
        date: "2026-08-15",
        description: "Independence Day",
        holiday_type: "TRADING_HOLIDAY",
        closed_exchanges: ["NSE", "BSE"],
        open_exchanges: [],
      },
    ]);
  });

  it.each([
    ["non-array payload", { holidays: [] }],
    ["non-object row", [null]],
    [
      "invalid calendar date",
      [{
        _date: "2026-02-30 00:00:00+05:30",
        description: "Invalid holiday",
        holiday_type: "TRADING_HOLIDAY",
        closed_exchanges: ["NSE"],
        open_exchanges: [],
      }],
    ],
    [
      "invalid datetime",
      [{
        _date: "2026-08-15T25:00:00+05:30",
        description: "Invalid holiday",
        holiday_type: "TRADING_HOLIDAY",
        closed_exchanges: ["NSE"],
        open_exchanges: [],
      }],
    ],
    [
      "invalid special-session timestamp",
      [{
        date: "2026-08-15",
        description: "Independence Day",
        holiday_type: "SPECIAL_SESSION",
        closed_exchanges: ["NSE", "BSE"],
        open_exchanges: [{
          exchange: "NSE",
          start_time: "not-an-epoch",
          end_time: "1786815000000",
        }],
      }],
    ],
  ])("rejects a malformed native holiday %s", async (_caseName, payload) => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(jsonResponse({ status: "success", data: payload }));

    await expect(getHolidays()).rejects.toThrow(/invalid native holiday response/i);
  });

  it("uses native option Greeks when a live native account is connected without an OpenAlgo key", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: [
            {
              symbol: "NIFTY24600CE", exchange: "NFO", instrument_id: "NSE_FO|CE",
              delta: "0.55", gamma: "0.002", theta: "-8.1", vega: "6.4", iv: "13.2",
            },
            {
              symbol: "NIFTY24700PE", exchange: "NFO", instrument_id: "NSE_FO|PE",
              Delta: "-0.45", Gamma: "0.003", Theta: "-7.1", Vega: "5.4", IV: "14.2",
            },
          ],
        }),
      );

    const result = await getMultiOptionGreeks([
      { symbol: "NIFTY24600CE", exchange: "NFO" },
      { symbol: "NIFTY24700PE", exchange: "NFO" },
    ]);

    expect(result).toEqual([
      {
        symbol: "NIFTY24600CE", exchange: "NFO", instrument_id: "NSE_FO|CE",
        delta: 0.55, gamma: 0.002, theta: -8.1, vega: 6.4, iv: 13.2,
      },
      {
        symbol: "NIFTY24700PE", exchange: "NFO", instrument_id: "NSE_FO|PE",
        delta: -0.45, gamma: 0.003, theta: -7.1, vega: 5.4, iv: 14.2,
      },
    ]);
    expect((fetchSpy.mock.calls[1] as [string, RequestInit | undefined])[0]).toContain(
      "/api/v1/native/accounts/upstox/U1/optiongreeks?symbols=NFO%3ANIFTY24600CE%2CNFO%3ANIFTY24700PE",
    );
    expect(fetchSpy).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/multioptiongreeks"),
      expect.anything(),
    );
  });

  it.each(["", "   ", [], [""], ["  "]])(
    "rejects malformed native Greek values instead of coercing %j to zero",
    async (delta) => {
      mockConnectionState.apiKey = "";
      fetchSpy
        .mockResolvedValueOnce(
          jsonResponse({
            status: "success",
            data: {
              accounts: [
                { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
              ],
            },
          }),
        )
        .mockResolvedValueOnce(
          jsonResponse({
            status: "success",
            data: [{
              symbol: "NIFTY24600CE",
              exchange: "NFO",
              instrument_id: "NSE_FO|CE",
              delta,
              gamma: "0.002",
              theta: "-8.1",
              vega: "6.4",
              iv: "13.2",
            }],
          }),
        );

      await expect(getMultiOptionGreeks([
        { symbol: "NIFTY24600CE", exchange: "NFO" },
      ])).rejects.toThrow(/lacks delta|invalid delta/i);
    },
  );

  it("uses native instrument search when no OpenAlgo key is configured", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: [{
            symbol: "RELIANCE",
            name: "Reliance Industries",
            instrument_key: "NSE_EQ|INE002A01018",
            lot_size: 1,
          }],
        }),
      );

    const result = await searchSymbol("RELIANCE");

    expect(result).toEqual([
      expect.objectContaining({
        symbol: "RELIANCE",
        exchange: "NSE_EQ",
        instrument_key: "NSE_EQ|INE002A01018",
      }),
    ]);
    expect((fetchSpy.mock.calls[1] as [string, RequestInit | undefined])[0]).toContain(
      "/api/v1/native/accounts/upstox/U1/search?query=RELIANCE",
    );
    expect(fetchSpy).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/search"),
      expect.anything(),
    );
  });

  it("uses native instrument search to resolve symbol metadata when no OpenAlgo key is configured", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: [{
            symbol: "NIFTY",
            name: "NIFTY 50",
            exchange: "NSE_INDEX",
            instrument_type: "INDEX",
            lot_size: 75,
            tick_size: 0.05,
          }],
        }),
      );

    const result = await getSymbol("NIFTY", "NSE_INDEX");

    expect(result).toEqual({
      symbol: "NIFTY",
      name: "NIFTY 50",
      exchange: "NSE_INDEX",
      instrumenttype: "INDEX",
      lotsize: 75,
      tick_size: 0.05,
    });
    expect((fetchSpy.mock.calls[1] as [string, RequestInit | undefined])[0]).toContain(
      "/api/v1/native/accounts/upstox/U1/search?query=NIFTY&exchange=NSE_INDEX",
    );
  });

  it("uses FlintTrade broker capabilities for the active native broker without an OpenAlgo key", async () => {
    mockConnectionState.apiKey = "";
    mockBrokerState.accounts = [
      { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
    ];
    mockBrokerState.activeAccountId = "native:upstox:U1";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        broker: "upstox",
        capabilities: {
          broker_name: "upstox",
          supports_equity: true,
          supports_options: true,
          supports_futures: true,
          supports_bracket_orders: false,
          supports_cover_orders: false,
        },
      }),
    );

    const result = await getBrokerCapabilities();

    expect(result).toEqual({
      broker_name: "upstox",
      broker_type: "equity",
      supported_exchanges: ["BFO", "BSE", "NFO", "NSE"],
      features: {
        market_protection: false,
        leverage: false,
        bracket_orders: false,
        cover_orders: false,
      },
    });
    expect((fetchSpy.mock.calls[0] as [string, RequestInit | undefined])[0]).toContain(
      "/api/v1/broker/capabilities?broker=upstox",
    );
    expect(fetchSpy).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/broker/capabilities"),
      expect.anything(),
    );
  });

  it("uses FlintTrade native interval metadata for the active broker without an OpenAlgo key", async () => {
    mockConnectionState.apiKey = "";
    mockBrokerState.accounts = [
      { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
    ];
    mockBrokerState.activeAccountId = "native:upstox:U1";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        broker: "upstox",
        capabilities: {
          broker_name: "upstox",
          historical_intervals: ["1m", "3m", "5m", "15m", "30m", "1D", "1W"],
          historical_intraday_intervals_minutes: [1, 3, 5, 15, 30],
        },
      }),
    );

    const result = await getIntervals();

    expect(result).toEqual(["1m", "3m", "5m", "15m", "30m", "1D", "1W"]);
    expect((fetchSpy.mock.calls[0] as [string, RequestInit | undefined])[0]).toContain(
      "/api/v1/broker/capabilities?broker=upstox",
    );
    expect(fetchSpy.mock.calls.map((call) => String(call[0]))).not.toEqual(
      expect.arrayContaining([expect.stringContaining("/api/v1/intervals")]),
    );
  });

  it("combines native intraday and calendar interval metadata when the backend omits the prebuilt list", async () => {
    mockConnectionState.apiKey = "";
    mockBrokerState.accounts = [
      { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
    ];
    mockBrokerState.activeAccountId = "native:upstox:U1";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        broker: "upstox",
        capabilities: {
          broker_name: "upstox",
          historical_intraday_intervals_minutes: [1, 3, 5, 15, 30],
          historical_calendar_intervals: ["1D", "1W", "1M"],
        },
      }),
    );

    const result = await getIntervals();

    expect(result).toEqual(["1m", "3m", "5m", "15m", "30m", "1D", "1W", "1M"]);
  });

  it("uses FlintTrade leverage margin snapshot instead of the stale broker leverage path", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        available: 50000,
        used: 10000,
        total: 60000,
        leverage_ratio: 0.1667,
      }),
    );

    const result = await getLeverageSettings();

    expect(result).toEqual({ available: 50000, used: 10000, total: 60000, leverage_ratio: 0.1667 });
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/ft-api/api/v1/leverage/margin/current");
    expect(url).not.toContain("/api/v1/../broker/leverage");
    expect(init.method).toBeUndefined();
    expect(init.body).toBeUndefined();
  });

  it("unwraps backend instruments envelopes for the option-chain cache", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        exchange: "NFO",
        count: 1,
        instruments: [
          {
            symbol: "NIFTY",
            name: "Nifty 50",
            exchange: "NFO",
            instrumenttype: "OPTIDX",
            lotsize: 75,
            tick_size: 0.05,
            token: "token-1",
          },
        ],
      }),
    );

    const result = await getInstruments();

    expect(result).toEqual([
      expect.objectContaining({ symbol: "NIFTY", exchange: "NFO", lotsize: 75 }),
    ]);
    expect((fetchSpy.mock.calls[0] as [string, RequestInit | undefined])[0]).toContain("/api/v1/instruments");
  });

  it("keeps the optional instruments cache empty in native-only mode without an OpenAlgo key", async () => {
    mockConnectionState.apiKey = "";
    mockBrokerState.accounts = [
      { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
    ];

    const result = await getInstruments();

    expect(result).toEqual([]);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("uses native history and normalises candle envelopes when no OpenAlgo key is configured", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            symbol: "INFY",
            exchange: "NSE",
            interval: "1d",
            bars: [
              {
                timestamp: "2026-01-02T09:15:00+05:30",
                open: "1",
                high: "2",
                low: "0.5",
                close: "1.5",
                volume: "10",
              },
            ],
          },
        }),
      );

    const result = await getHistory("INFY", "NSE", "1d", "2026-01-01", "2026-01-31");

    expect(result).toEqual([
      { timestamp: 1767325500, open: 1, high: 2, low: 0.5, close: 1.5, volume: 10 },
    ]);
    expect((fetchSpy.mock.calls[1] as [string, RequestInit | undefined])[0]).toContain(
      "/api/v1/native/accounts/upstox/U1/history?symbol=INFY&exchange=NSE&interval=1d&start_date=2026-01-01&end_date=2026-01-31",
    );
  });

  it("uses native expiry and option chain reads when no OpenAlgo key is configured", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: ["2026-07-30"],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            underlying: "NIFTY",
            exchange: "NSE_INDEX",
            spot_price: "25020",
            strikes: [
              {
                strike_price: 25000,
                ce_ltp: "100.5",
                ce_oi: "10",
                ce_volume: "1000",
                ce_iv: "18.4",
                ce_delta: "0.55",
                ce_gamma: "0.002",
                ce_theta: "-8.1",
                ce_vega: "6.4",
                ce_greeks_complete: true,
                pe_ltp: "80.25",
                pe_oi: "20",
                pe_volume: "2000",
                pe_iv: "17.2",
                pe_delta: "-0.45",
                pe_gamma: "0.003",
                pe_theta: "-7.1",
                pe_vega: "5.4",
                pe_greeks_complete: false,
              },
            ],
          },
        }),
      );

    const expiries = await getExpiry("NIFTY", "NSE_INDEX");
    const chain = await getOptionChain("NIFTY", "NSE_INDEX", "2026-07-30") as unknown as {
      chain: Array<{ strike: number; ce: { ltp: number; oi: number }; pe: { ltp: number; oi: number } }>;
      pcr: number;
      underlying_ltp: number;
    };

    expect(expiries).toEqual({ expiry: ["2026-07-30"] });
    expect(chain.chain[0]).toMatchObject({
      strike: 25000,
      ce: { ltp: 100.5, oi: 10, iv: 0.184, delta: 0.55 },
      pe: { ltp: 80.25, oi: 20, iv: null, delta: null },
    });
    expect(chain.pcr).toBe(2);
    expect(chain.underlying_ltp).toBe(25020);
    expect((fetchSpy.mock.calls[1] as [string, RequestInit | undefined])[0]).toContain(
      "/api/v1/native/accounts/upstox/U1/expiry?symbol=NIFTY&exchange=NSE_INDEX",
    );
    const optionChainUrl = (fetchSpy.mock.calls[3] as [string, RequestInit | undefined])[0];
    expect(optionChainUrl).toContain("/api/v1/native/accounts/upstox/U1/optionchain?");
    expect(optionChainUrl).toContain("underlying=NIFTY");
    expect(optionChainUrl).toContain("exchange=NSE_INDEX");
    expect(optionChainUrl).toContain("expiry=2026-07-30");
    expect(fetchSpy).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/optionchain"),
      expect.anything(),
    );
  });

  it("keeps only non-blank string expiries from native responses", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: [null, 0, true, "", "   ", " 2026-07-30 "],
        }),
      );

    await expect(getExpiry("NIFTY", "NSE_INDEX")).resolves.toEqual({
      expiry: ["2026-07-30"],
    });
  });

  it("preserves omitted native option OI as unavailable and refuses a partial PCR", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            underlying: "NIFTY",
            exchange: "NSE_INDEX",
            spot_price: "25020",
            strikes: [
              { strike_price: 25000, ce_ltp: "100", pe_ltp: "90", pe_oi: "0" },
              { strike_price: 25100, ce_ltp: "50", ce_oi: "50", pe_ltp: "140", pe_oi: "50" },
            ],
          },
        }),
      );

    const chain = await getOptionChain("NIFTY", "NSE_INDEX", "2026-07-30") as unknown as {
      chain: Array<{
        strike: number;
        ce: Record<string, unknown>;
        pe: Record<string, unknown>;
      }>;
      pcr: number | null;
    };

    expect(chain.chain[0]?.ce).not.toHaveProperty("oi");
    expect(chain.chain[0]?.ce).not.toHaveProperty("open_interest");
    expect(chain.chain[0]?.pe).toMatchObject({ oi: 0, open_interest: 0 });
    expect(chain.pcr).toBeNull();
  });

  it("normalises pre-shaped native chains through strict spot, strike, and OI validation", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            underlying_ltp: "25020",
            chain: [
              { strike: true, ce: { oi: 100 }, pe: { oi: 100 } },
              { strike: 0, ce: { oi: 100 }, pe: { oi: 100 } },
              { strike: "25000", ce: { oi: 0 }, pe: {} },
              { strike: 25100, ce: {}, pe: { open_interest: "10" } },
            ],
          },
        }),
      );

    const chain = await getOptionChain("NIFTY", "NSE_INDEX", "2026-07-30") as unknown as {
      underlying_ltp: number;
      pcr: number | null;
      chain: Array<{ strike: number; ce: Record<string, unknown>; pe: Record<string, unknown> }>;
    };

    expect(chain.underlying_ltp).toBe(25020);
    expect(chain.chain.map((row) => row.strike)).toEqual([25000, 25100]);
    expect(chain.chain[0]?.ce).toMatchObject({ oi: 0, open_interest: 0 });
    expect(chain.chain[0]?.pe).not.toHaveProperty("oi");
    expect(chain.chain[1]?.ce).not.toHaveProperty("oi");
    expect(chain.chain[1]?.pe).toMatchObject({ oi: 10, open_interest: 10 });
    expect(chain.pcr).toBeNull();
  });

  it("rejects malformed native option-leg numeric fields instead of dropping them", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            underlying_ltp: 25020,
            chain: [{
              strike: 25000,
              ce: { change: "bad", change_percent: "0", oi_change: "bad" },
              pe: { change_pct: "-1.5", oi_change: "0" },
            }],
          },
        }),
      );

    await expect(getOptionChain("NIFTY", "NSE_INDEX", "2026-07-30"))
      .rejects.toThrow(/option-chain.*change/i);
  });

  it.each([
    ["ltp", true],
    ["bid", []],
    ["ask", {}],
    ["change", "bad"],
    ["change_percent", []],
    ["change_pct", true],
    ["oi_change", {}],
    ["oi", 1.5],
    ["volume", true],
    ["delta", []],
    ["gamma", {}],
    ["theta", true],
    ["vega", "Infinity"],
    ["iv", -1],
  ])("rejects invalid flattened native option-leg %s values", async (field, invalidValue) => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            underlying_ltp: 25020,
            strikes: [{ strike_price: 25000, [`ce_${field}`]: invalidValue }],
          },
        }),
      );

    await expect(getOptionChain("NIFTY", "NSE_INDEX", "2026-07-30"))
      .rejects.toThrow(new RegExp(`option-chain.*${field}`, "i"));
  });

  it("preserves explicit native LTP zero while leaving omitted LTP unavailable", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            underlying_ltp: 25020,
            strikes: [{ strike_price: 25000, ce_ltp: "0" }],
          },
        }),
      );

    const chain = await getOptionChain("NIFTY", "NSE_INDEX", "2026-07-30") as unknown as {
      chain: Array<{ ce: Record<string, unknown>; pe: Record<string, unknown> }>;
    };

    expect(chain.chain[0]?.ce).toMatchObject({ ltp: 0, last_price: 0 });
    expect(chain.chain[0]?.pe).not.toHaveProperty("ltp");
    expect(chain.chain[0]?.pe).not.toHaveProperty("last_price");
  });

  it("rejects a native option chain whose spot price is unavailable", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: { chain: [{ strike: 25000, ce: { oi: 10 }, pe: { oi: 20 } }] },
        }),
      );

    await expect(getOptionChain("NIFTY", "NSE_INDEX", "2026-07-30"))
      .rejects.toThrow(/valid positive spot price/i);
  });

  it("selects the native ATM fallback nearest the authoritative spot instead of the middle row", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            underlying_ltp: 92,
            chain: [
              { strike: 50, ce: { oi: 1 }, pe: { oi: 1 } },
              { strike: 90, ce: { oi: 1 }, pe: { oi: 1 } },
              { strike: 110, ce: { oi: 1 }, pe: { oi: 1 } },
              { strike: 200, ce: { oi: 1 }, pe: { oi: 1 } },
            ],
          },
        }),
      );

    const chain = await getOptionChain("NIFTY", "NSE_INDEX", "2026-07-30") as unknown as {
      atm_strike: number;
    };

    expect(chain.atm_strike).toBe(90);
  });

  it("rejects malformed OpenAlgo option-chain arrays before consumers iterate them", async () => {
    mockConnectionState.apiKey = "test-key-123";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: { chain: { length: 1 } },
      }),
    );

    await expect(getOptionChain("NIFTY", "NFO", "2026-07-30"))
      .rejects.toThrow(/option-chain chain array/i);
  });

  it("validates modern and legacy OpenAlgo chain arrays together", async () => {
    mockConnectionState.apiKey = "test-key-123";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: { chain: [], calls: { length: 1 }, puts: [] },
      }),
    );

    await expect(getOptionChain("NIFTY", "NFO", "2026-07-30"))
      .rejects.toThrow(/option-chain calls array/i);
  });

  it("rejects malformed OpenAlgo option-leg scalars", async () => {
    mockConnectionState.apiKey = "test-key-123";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: {
          chain: [{
            strike: 25000,
            ce: { change: "bad", change_pct: "0", oi_change: "0" },
            pe: null,
          }],
          calls: [],
          puts: [],
        },
      }),
    );

    await expect(getOptionChain("NIFTY", "NFO", "2026-07-30"))
      .rejects.toThrow(/option-chain.*change/i);
  });

  it.each([
    ["ltp", true],
    ["last_price", []],
    ["bid", {}],
    ["ask", "Infinity"],
    ["change", "bad"],
    ["change_percent", {}],
    ["change_pct", []],
    ["oi_change", true],
    ["oi", {}],
    ["open_interest", []],
    ["volume", true],
    ["delta", []],
    ["gamma", {}],
    ["theta", true],
    ["vega", "bad"],
    ["iv", "Infinity"],
    ["implied_volatility", -1],
  ])("rejects invalid OpenAlgo option-leg %s values", async (field, invalidValue) => {
    mockConnectionState.apiKey = "test-key-123";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: {
          chain: [{ strike: 25000, ce: { [field]: invalidValue }, pe: null }],
          calls: [],
          puts: [],
        },
      }),
    );

    await expect(getOptionChain("NIFTY", "NFO", "2026-07-30"))
      .rejects.toThrow(new RegExp(`option-chain.*${field}`, "i"));
  });

  it("normalises every finite OpenAlgo option-leg scalar and preserves explicit zero", async () => {
    mockConnectionState.apiKey = "test-key-123";
    const zeroFields = {
      ltp: "0",
      last_price: "0",
      bid: "0",
      ask: "0",
      change: "0",
      change_percent: "0",
      change_pct: "0",
      oi_change: "0",
      oi: "0",
      open_interest: "0",
      volume: "0",
      delta: "0",
      gamma: "0",
      theta: "0",
      vega: "0",
      iv: "0",
      implied_volatility: "0",
    };
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: {
          chain: [{ strike: 25000, ce: zeroFields, pe: null }],
          calls: [],
          puts: [],
        },
      }),
    );

    const chain = await getOptionChain("NIFTY", "NFO", "2026-07-30") as unknown as {
      chain: Array<{ ce: Record<string, unknown> }>;
    };
    expect(chain.chain[0]?.ce).toMatchObject(Object.fromEntries(
      Object.keys(zeroFields).map((field) => [field, 0]),
    ));
  });

  it("trims and filters OpenAlgo expiry payloads before returning them", async () => {
    mockConnectionState.apiKey = "test-key-123";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: { expiry: [null, true, "", "   ", " 2026-07-30 "] },
      }),
    );

    await expect(getExpiry("NIFTY", "NFO")).resolves.toEqual({ expiry: ["2026-07-30"] });
  });

  it("derives synthetic futures from native option-chain rows without an OpenAlgo key", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "upstox", account_id: "U1", is_primary: true, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            spot_price: "25020",
            atm_strike: 25000,
            strikes: [
              { strike_price: 24950, ce_ltp: "125.5", pe_ltp: "76.25" },
              { strike_price: 25000, ce_ltp: "101.25", pe_ltp: "86.75" },
              { strike_price: 25050, ce_ltp: "79.5", pe_ltp: "111.25" },
            ],
          },
        }),
      );

    const result = await getSyntheticFuture("NIFTY", "NSE_INDEX", "2026-07-30");

    expect(result).toEqual({
      underlying: "NIFTY",
      underlying_ltp: 25020,
      expiry: "2026-07-30",
      atm_strike: 25000,
      synthetic_future_price: 25014.5,
    });
    const urls = fetchSpy.mock.calls.map((call) => (call as [string, RequestInit | undefined])[0]);
    expect(urls[1]).toContain("/api/v1/native/accounts/upstox/U1/optionchain?");
    expect(urls.some((url) => url.includes("/api/v1/syntheticfuture"))).toBe(false);
  });

  it("builds compact option symbols locally when no OpenAlgo key is configured", async () => {
    mockConnectionState.apiKey = "";

    const result = await getOptionSymbol("NIFTY", "NFO", "2026-07-30", "CE", "25000");

    expect(result).toEqual({ symbol: "NIFTY30JUL2625000CE", exchange: "NFO" });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("keeps OpenAlgo option-symbol resolution primary when an API key is configured", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { symbol: "BROKER-NIFTY-CE", exchange: "NFO" } }),
    );

    const result = await getOptionSymbol("NIFTY", "NFO", "2026-07-30", "CE", "25000");

    expect(result).toEqual({ symbol: "BROKER-NIFTY-CE", exchange: "NFO" });
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/optionsymbol");
    expect(JSON.parse(init.body as string)).toEqual({
      apikey: "test-key-123",
      underlying: "NIFTY",
      exchange: "NFO",
      expiry_date: "2026-07-30",
      option_type: "CE",
      offset: "25000",
    });
  });

  it("routes max pain through the FlintTrade backend and normalises strike losses", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: {
          max_pain_strike: "25000",
          total_loss_at_max_pain: "123456",
          strike_losses: [
            { strike: "24950", total_loss: "456789" },
            { strike: "25000", total_loss: "123456" },
          ],
        },
      }),
    );

    const result = await getMaxPain("NIFTY", "NFO", "2026-07-30");

    expect(result).toEqual({
      is_sample_data: true,
      max_pain_strike: 25000,
      total_loss_at_max_pain: 123456,
      strike_losses: [
        { strike: 24950, total_loss: 456789 },
        { strike: 25000, total_loss: 123456 },
      ],
      strikes: [
        { strike: 24950, total_pain: 456789 },
        { strike: 25000, total_pain: 123456 },
      ],
    });
    expect(fetchSpy).toHaveBeenCalledOnce();
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/maxpain");
    expect(url).not.toContain("/api/v1/max_pain");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      symbol: "NIFTY",
      exchange: "NFO",
      expiry_date: "2026-07-30",
    });
  });

  it("rejects unavailable Max Pain strikes and rows instead of fabricating zero pain", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: {
          is_sample_data: false,
          max_pain_strike: true,
          strike_losses: [
            { strike: true, total_loss: 400 },
            { total_loss: 300 },
            { strike: 25000 },
            { strike: 25100, total_loss: false },
            { strike: 25200, total_loss: 500 },
            { strike: 25300, total_loss: 0 },
          ],
          strikes: [
            { strike: true, total_pain: 400 },
            { total_pain: 300 },
            { strike: 25000 },
            { strike: 25100, total_pain: false },
            { strike: 25200, call_pain: 0, total_pain: 500 },
            { strike: 25300, total_pain: 0 },
          ],
        },
      }),
    );

    await expect(getMaxPain("NIFTY", "NFO", "2026-07-30")).resolves.toEqual({
      is_sample_data: false,
      max_pain_strike: null,
      strike_losses: [{ strike: 25200, total_loss: 500 }],
      strikes: [{ strike: 25200, call_pain: 0, total_pain: 500 }],
    });
  });

  it("preserves zero Max Pain losses when a positive authoritative strike is present", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: {
          is_sample_data: false,
          max_pain_strike: 25000,
          total_loss_at_max_pain: 0,
          strike_losses: [
            { strike: 24950, total_loss: 10 },
            { strike: 25000, total_loss: 0 },
          ],
          strikes: [
            { strike: 24950, total_pain: 10 },
            { strike: 25000, call_pain: 0, put_pain: 0, total_pain: 0 },
          ],
        },
      }),
    );

    await expect(getMaxPain("NIFTY", "NFO", "2026-07-30")).resolves.toEqual({
      is_sample_data: false,
      max_pain_strike: 25000,
      total_loss_at_max_pain: 0,
      strike_losses: [
        { strike: 24950, total_loss: 10 },
        { strike: 25000, total_loss: 0 },
      ],
      strikes: [
        { strike: 24950, total_pain: 10 },
        { strike: 25000, call_pain: 0, put_pain: 0, total_pain: 0 },
      ],
    });
  });

  it("keeps an all-zero unavailable Max Pain response empty", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: {
          is_sample_data: false,
          max_pain_strike: null,
          total_loss_at_max_pain: 0,
          strike_losses: [{ strike: 25000, total_loss: 0 }],
          strikes: [{ strike: 25000, call_pain: 0, put_pain: 0, total_pain: 0 }],
        },
      }),
    );

    await expect(getMaxPain("NIFTY", "NFO", "2026-07-30")).resolves.toEqual({
      is_sample_data: false,
      max_pain_strike: null,
      strike_losses: [],
      strikes: [],
    });
  });

  it("routes legacy market-intelligence reads through FlintTrade backend shapes", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          is_sample_data: false,
          data: {
            strikes: [
              {
                strike: "25000",
                call_gex: "1.5",
                put_gex: "-0.25",
                net_gex: "1.25",
                call_oi: "100",
                put_oi: "80",
              },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          is_sample_data: false,
          data: {
            is_sample_data: false,
            curves: [
              {
                points: [
                  { strike: 25000, call_iv: "0.125", put_iv: "0.1325", moneyness: "1" },
                ],
              },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          is_sample_data: false,
          data: {
            strikes: [
              {
                strike: "25000",
                ce_oi: "100",
                pe_oi: "130",
                ce_oi_change: "5",
                pe_oi_change: "-3",
              },
            ],
          },
        }),
      );

    const [gex, ivSmile, oiProfile] = await Promise.all([
      getGex("NIFTY", "NFO", "2026-07-30"),
      getIVSmile("NIFTY", "NFO", "2026-07-30"),
      getOIProfile("NIFTY", "NFO", "2026-07-30"),
    ]);

    expect(gex).toEqual({
      is_sample_data: false,
      rows: [
        { strike: 25000, call_gex: 1.5, put_gex: -0.25, net_gex: 1.25, call_oi: 100, put_oi: 80 },
      ],
    });
    expect(ivSmile).toEqual({
      is_sample_data: false,
      points: [{ strike: 25000, call_iv: 0.125, put_iv: 0.1325, moneyness: 1 }],
    });
    expect(oiProfile).toEqual({
      is_sample_data: false,
      rows: [
        { strike: 25000, type: "CE", oi: 100, oi_delta_d: 5 },
        { strike: 25000, type: "PE", oi: 130, oi_delta_d: -3 },
      ],
    });
    const urls = fetchSpy.mock.calls.map((call) => (call as [string, RequestInit])[0]);
    expect(urls).toEqual([
      expect.stringContaining("/api/v1/gex"),
      expect.stringContaining("/api/v1/ivsmile"),
      expect.stringContaining("/api/v1/oiprofile"),
    ]);
    expect(urls.some((url) => url.includes("/api/v1/iv_smile"))).toBe(false);
    expect(urls.some((url) => url.includes("/api/v1/oi_profile"))).toBe(false);
  });

  it("treats an IV Smile payload without explicit provenance as sample data", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: {
          curves: [{
            points: [
              { strike: 25000, call_iv: 0.125, put_iv: 0.1325, moneyness: 1 },
              { strike: 25100, call_iv: 0.126, put_iv: 0, moneyness: 1.004 },
            ],
          }],
        },
      }),
    );

    await expect(getIVSmile("NIFTY", "NFO")).resolves.toEqual({
      is_sample_data: true,
      points: [{ strike: 25000, call_iv: 0.125, put_iv: 0.1325, moneyness: 1 }],
    });
  });

  it("rejects boolean, array, and object values in IV Smile numeric provenance", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        is_sample_data: false,
        data: {
          is_sample_data: false,
          points: [
            { strike: true, call_iv: [0.125], put_iv: true, moneyness: ["1"] },
            { strike: 25000, call_iv: 0.125, put_iv: 0.1325, moneyness: 1 },
          ],
        },
      }),
    );

    await expect(getIVSmile("NIFTY", "NFO")).resolves.toEqual({
      is_sample_data: false,
      points: [{ strike: 25000, call_iv: 0.125, put_iv: 0.1325, moneyness: 1 }],
    });
  });

  it("rejects malformed strikes and negative OI without fabricating zeros", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: {
          is_sample_data: false,
          strikes: [
            { strike: true, ce_oi: 100, pe_oi: 80 },
            { strike: 25000, ce_oi: -1, pe_oi: "80" },
            { strike: 25100, ce_oi: false, pe_oi: [] },
            { strike: 25200, ce_oi: 1.5, pe_oi: "Infinity" },
            { strike: 25300, ce_oi: 0, pe_oi: "0" },
          ],
        },
      }),
    );

    await expect(getOIProfile("NIFTY", "NFO")).resolves.toEqual({
      is_sample_data: false,
      rows: [
        { strike: 25000, type: "PE", oi: 80 },
        { strike: 25300, type: "CE", oi: 0 },
        { strike: 25300, type: "PE", oi: 0 },
      ],
    });
  });

  it("validates legacy OI Profile rows instead of trusting fractional OI", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: [
          { strike: 25000, type: "CE", oi: 1.5 },
          { strike: 25100, type: "PE", oi: 0 },
        ],
      }),
    );

    await expect(getOIProfile("NIFTY", "NFO")).resolves.toEqual({
      is_sample_data: true,
      rows: [{ strike: 25100, type: "PE", oi: 0 }],
    });
  });

  it("keeps explicit zero legacy LTP but withholds negative LTP as unavailable", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: [
          { strike: 25000, type: "CE", oi: 10, ltp: 0 },
          { strike: 25000, type: "PE", oi: 20, ltp: -1 },
        ],
      }),
    );

    await expect(getOIProfile("NIFTY", "NFO")).resolves.toEqual({
      is_sample_data: true,
      rows: [
        { strike: 25000, type: "CE", oi: 10, ltp: 0 },
        { strike: 25000, type: "PE", oi: 20 },
      ],
    });
  });

  it("preserves explicit zero canonical OI changes while leaving omitted changes unavailable", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: {
          is_sample_data: false,
          strikes: [{ strike: 25000, ce_oi: 0, pe_oi: 0, ce_oi_change: 0 }],
        },
      }),
    );

    await expect(getOIProfile("NIFTY", "NFO")).resolves.toEqual({
      is_sample_data: false,
      rows: [
        { strike: 25000, type: "CE", oi: 0, oi_delta_d: 0 },
        { strike: 25000, type: "PE", oi: 0 },
      ],
    });
  });

  it("requires exposure fields and integer OI for GEX while preserving explicit zero", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: {
          is_sample_data: false,
          strikes: [
            {
              strike: 25000,
              call_gamma: 1.5,
              put_gamma: -0.25,
              net_gamma: 1.25,
              call_oi: 100,
              put_oi: 80,
            },
            { strike: 25100, call_gex: 1, put_gex: -1, net_gex: 0, call_oi: 1.5, put_oi: 2 },
            { strike: 25200, call_gex: 1, put_gex: -1, net_gex: 0, call_oi: "Infinity", put_oi: 2 },
            { strike: 25300, call_gex: 0, put_gex: 0, net_gex: 0, call_oi: 0, put_oi: "0" },
          ],
        },
      }),
    );

    await expect(getGex("NIFTY", "NFO")).resolves.toEqual({
      is_sample_data: false,
      rows: [
        { strike: 25300, call_gex: 0, put_gex: 0, net_gex: 0, call_oi: 0, put_oi: 0 },
      ],
    });
  });

  it("drops GEX rows whose net exposure disagrees with call plus put exposure beyond scale-aware tolerance", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: {
          is_sample_data: false,
          strikes: [
            { strike: 25000, call_gex: 1, put_gex: -1, net_gex: 10, call_oi: 100, put_oi: 100 },
            { strike: 25100, call_gex: 1.2, put_gex: -0.2, net_gex: 1.0000005, call_oi: 100, put_oi: 100 },
          ],
        },
      }),
    );

    await expect(getGex("NIFTY", "NFO")).resolves.toEqual({
      is_sample_data: false,
      rows: [
        { strike: 25100, call_gex: 1.2, put_gex: -0.2, net_gex: 1.0000005, call_oi: 100, put_oi: 100 },
      ],
    });
  });

  it("refuses account funds in Explore instead of inventing an account fallback", async () => {
    mockConnectionState.apiKey = "";
    mockModeState.mode = "explore";

    await expect(getFunds(EXPLORE_READ_CONTEXT)).rejects.toThrow("Account reads are unavailable");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("keeps Explore history synthetic even when an OpenAlgo key is configured", async () => {
    mockConnectionState.apiKey = "configured-live-key";
    mockModeState.mode = "explore";

    const result = await getHistory("NIFTY", "NSE_INDEX", "5m", "2026-07-01", "2026-07-14");

    expect(result).toHaveLength(96);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("serves sample expiries and a sample option chain in Explore instead of erroring", async () => {
    // Regression: expiry/optionchain had no Explore fallback, so the Option
    // Chain and OI Chart widgets errored with "OpenAlgo API key is not
    // configured" in demo mode instead of rendering sample data.
    mockConnectionState.apiKey = "";
    mockModeState.mode = "explore";

    const expiries = await getExpiry("NIFTY", "NFO");
    expect(expiries.expiry.length).toBeGreaterThan(0);
    expect(expiries.expiry[0]).toMatch(/^\d{2}-[A-Z]{3}-\d{2}$/);

    const chain = await getOptionChain("NIFTY", "NFO", expiries.expiry[0]) as unknown as {
      chain: Array<{ strike: number; ce: { ltp: number; oi: number }; pe: { ltp: number; oi: number } }>;
      atm_strike: number;
      underlying_ltp: number;
      is_sample_data: boolean;
    };
    expect(chain.is_sample_data).toBe(true);
    expect(chain.chain.length).toBeGreaterThan(10);
    expect(chain.atm_strike).toBeGreaterThan(0);
    for (const row of chain.chain) {
      expect(row.ce.ltp).toBeGreaterThanOrEqual(0);
      expect(row.pe.oi).toBeGreaterThan(0);
    }
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("reads Practice funds from the order-execution sandbox, never a real account", async () => {
    mockConnectionState.apiKey = "configured-live-key";
    mockModeState.mode = "practice";
    mockBrokerState.accounts = [{ account_id: "D1", broker: "dhan", source: "native" }];
    mockBrokerState.activeAccountId = "native:dhan:D1";
    fetchSpy.mockResolvedValueOnce(jsonResponse({
      status: "success",
      data: {
        capital: { initial: 1_000_000, current: 1_012_500, available: 900_000, used_margin: 112_500 },
      },
    }));

    await expect(getFunds(PRACTICE_READ_CONTEXT)).resolves.toEqual({
      availableCash: 900_000,
      usedMargin: 112_500,
      totalBalance: 1_012_500,
    });
    const urls = fetchSpy.mock.calls.map(([url]) => String(url));
    expect(urls).toEqual([expect.stringContaining("/v1/sandbox/capital")]);
    expect(urls.some((url) => url.includes("/api/v1/funds"))).toBe(false);
    expect(urls.some((url) => url.includes("/api/v1/native/accounts"))).toBe(false);
  });

  it("reads Practice positions from the same sandbox used for Practice orders", async () => {
    mockConnectionState.apiKey = "configured-live-key";
    mockModeState.mode = "practice";
    fetchSpy.mockResolvedValueOnce(jsonResponse({
      status: "success",
      data: {
        positions: [{
          symbol: "INFY",
          exchange: "NSE",
          product: "MIS",
          net_qty: 10,
          avg_price: 1500,
          realised_pnl: 100,
          unrealised_pnl: 50,
        }],
      },
    }));

    await expect(getPositionbook(PRACTICE_READ_CONTEXT)).resolves.toEqual([{
      symbol: "INFY",
      exchange: "NSE",
      product: "MIS",
      quantity: 10,
      averagePrice: 1500,
      ltp: 1505,
      pnl: 150,
      pnlPercent: 1,
    }]);
    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("/v1/sandbox/positions");
  });

  it("reads Practice holdings from sandbox authority without touching a Live broker", async () => {
    mockConnectionState.apiKey = "";
    mockConnectionState.status = "disconnected";
    mockModeState.mode = "live";

    await expect(getHoldings(PRACTICE_READ_CONTEXT)).resolves.toEqual([]);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("reads Practice trades from the canonical fill ledger authority", async () => {
    mockConnectionState.apiKey = "";
    mockConnectionState.status = "disconnected";
    mockModeState.mode = "live";
    fetchSpy.mockResolvedValueOnce(jsonResponse({
      status: "success",
      data: {
        trades: [{
          trade_id: "TR-1",
          order_id: "SB-1",
          symbol: "INFY",
          exchange: "NSE",
          action: "BUY",
          quantity: 10,
          price: 1_500,
          traded_at: "2026-07-14T10:00:00+00:00",
        }],
      },
    }));

    await expect(getTradebook(PRACTICE_READ_CONTEXT)).resolves.toEqual([{
      tradeId: "TR-1",
      orderId: "SB-1",
      symbol: "INFY",
      exchange: "NSE",
      action: "BUY",
      quantity: 10,
      price: 1_500,
      timestamp: "2026-07-14T10:00:00+00:00",
    }]);
    expect(String(fetchSpy.mock.calls[0]?.[0])).toContain("/v1/sandbox/trades");
    expect(String(fetchSpy.mock.calls[0]?.[0])).not.toContain("/v1/sandbox/orders");
  });

  it("POST sends extra params merged with apikey", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { ltp: 22500 } }),
    );

    await getQuotes("NIFTY", "NSE_INDEX");

    const body = JSON.parse(
      (fetchSpy.mock.calls[0] as [string, RequestInit])[1].body as string,
    );
    expect(body).toMatchObject({
      apikey: "test-key-123",
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
    });
  });

  it("checks OpenAlgo analyzer status through the documented status route", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { enabled: true } }),
    );

    const result = await getAnalyzerStatus();

    expect(result).toEqual({ enabled: true });
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/analyzer/status");
    expect(url).not.toContain("/api/v1/analyzer?");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ apikey: "test-key-123" });
  });

  it("keeps chart preferences on the FlintTrade backend instead of requiring an OpenAlgo key", async () => {
    mockConnectionState.apiKey = "";
    const response = {
      user_id: "default",
      theme: { background: "#0a0a0f" },
      indicator_sets: {},
      layouts: { default: { panels: [] } },
      layout: { panels: [] },
    };
    fetchSpy.mockResolvedValueOnce(jsonResponse({ status: "success", data: response }));

    const result = await getChartPreferences();

    expect(result).toEqual(response);
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/ft-api/api/v1/chart");
    expect(init.method).toBeUndefined();
    expect(init.body).toBeUndefined();
  });

  it("updates chart preferences through the FlintTrade backend route", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        data: { user_id: "default", theme: { background: "#111" }, indicator_sets: {}, layouts: {}, layout: {} },
      }),
    );

    const result = await updateChartPreferences({ theme: { background: "#111" } });

    expect(result).toMatchObject({ user_id: "default", theme: { background: "#111" } });
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/ft-api/api/v1/chart");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ theme: { background: "#111" } });
    expect(init.headers).toMatchObject({ "Content-Type": "application/json" });
  });

  it("sends Telegram test messages through FlintTrade backend credentials", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy.mockResolvedValueOnce(jsonResponse({ status: "success", data: { message: "sent" } }));

    const result = await sendTelegram("hello", { botToken: "tok-test", chatId: "123" });

    expect(result).toEqual({ message: "sent" });
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/ft-api/api/v1/telegram");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      message: "hello",
      bot_token: "tok-test",
      chat_id: "123",
    });
    expect(JSON.parse(init.body as string)).not.toHaveProperty("apikey");
  });

  it("supports Telegram test messages from workspace configuration without an OpenAlgo key", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy.mockResolvedValueOnce(jsonResponse({ status: "success", data: { message: "sent" } }));

    await sendTelegram("hello");

    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/ft-api/api/v1/telegram");
    expect(JSON.parse(init.body as string)).toEqual({ message: "hello" });
  });

  // ---- GET requests ----

  it("GET request does not send a body or Content-Type", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: ["1m", "5m", "1h"] }),
    );

    const result = await getIntervals();

    expect(result).toEqual(["1m", "5m", "1h"]);
    const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit | undefined];
    // GET calls use the single-arg form of fetch (no init or no method)
    expect(init).toBeUndefined();
  });

  // ---- postOrder — mode header ----

  it("postOrder attaches X-FlintTrade-Mode header from modeStore", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { orderId: "ORD-1" } }),
    );

    await placeOrder({
      symbol: "RELIANCE",
      exchange: "NSE",
      action: "BUY",
      quantity: 1,
      price_type: "MARKET",
      product: "MIS",
      orderType: "MARKET",
    } as unknown as Parameters<typeof placeOrder>[0]);

    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/orders/place");
    const headers = init.headers as Record<string, string>;
    expect(headers["X-FlintTrade-Mode"]).toBe("live");
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("placeOrder with a Practice authority pin keeps sandbox mode even if the store flips after the gate", async () => {
    mockModeState.mode = "practice";
    fetchSpy.mockImplementation(async (_url, init) => {
      // Flip after the transport has already chosen the pinned mode.
      mockModeState.mode = "live";
      const headers = init?.headers as Record<string, string>;
      expect(headers["X-FlintTrade-Mode"]).toBe("practice");
      return jsonResponse({ status: "success", data: { orderId: "PRAC-PIN" } });
    });

    await placeOrder(
      {
        symbol: "RELIANCE",
        exchange: "NSE",
        action: "BUY",
        quantity: 1,
        product: "MIS",
        orderType: "MARKET",
      },
      { mode: "practice" },
    );

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const headers = (fetchSpy.mock.calls[0]![1] as RequestInit).headers as Record<string, string>;
    expect(headers["X-FlintTrade-Mode"]).toBe("practice");
  });

  it("placeOrder with a Practice authority pin rejects when the store already left Practice", async () => {
    mockModeState.mode = "live";
    await expect(
      placeOrder(
        {
          symbol: "RELIANCE",
          exchange: "NSE",
          action: "BUY",
          quantity: 1,
          product: "MIS",
          orderType: "MARKET",
        },
        { mode: "practice" },
      ),
    ).rejects.toThrow(/mode changed from practice to live/i);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("rejects an exact account-A authority pin after the active account changes to B", async () => {
    mockConnectionState.apiKey = "";
    mockBrokerState.accounts = [
      { account_id: "ACCOUNT-A", broker: "dhan", source: "native", status: "connected" },
      { account_id: "ACCOUNT-B", broker: "upstox", source: "native", status: "connected" },
    ];
    mockBrokerState.activeAccountId = "native:upstox:ACCOUNT-B";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { orderId: "WRONG-ACCOUNT" } }),
    );

    await expect(placeOrder(
      {
        symbol: "RELIANCE",
        exchange: "NSE",
        action: "SELL",
        quantity: 1,
        product: "MIS",
        orderType: "MARKET",
      },
      {
        mode: "live",
        scopeKey: "live:native:dhan:ACCOUNT-A",
        brokerType: "dhan",
        accountId: "ACCOUNT-A",
      },
    )).rejects.toThrow(/authority|account|scope/i);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("routes an exact OpenAlgo square-off pin to literal openalgo/default", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { orderId: "OA-SQUARE-OFF" } }),
    );

    await placeOrder(
      {
        symbol: "RELIANCE",
        exchange: "NSE",
        action: "SELL",
        quantity: 1,
        product: "MIS",
        orderType: "MARKET",
        strategy: "FlintPositions",
      },
      {
        mode: "live",
        scopeKey: "live:openalgo:7d290c41e91d8f71",
        brokerType: "openalgo",
        accountId: "default",
      },
    );

    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/orders/openalgo/place");
    expect(JSON.parse(String(init.body))).toMatchObject({
      broker: "openalgo",
      account_id: "default",
      symbol: "RELIANCE",
    });
  });

  it("routes an exact native square-off pin to the literal displayed account", async () => {
    mockConnectionState.apiKey = "";
    mockBrokerState.accounts = [
      { account_id: "ACCOUNT-A", broker: "upstox", source: "native", status: "connected" },
    ];
    mockBrokerState.activeAccountId = "native:upstox:ACCOUNT-A";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { orderId: "UP-SQUARE-OFF" } }),
    );

    await placeOrder(
      {
        symbol: "RELIANCE",
        exchange: "NSE",
        action: "SELL",
        quantity: 1,
        product: "MIS",
        orderType: "MARKET",
        strategy: "FlintPositions",
      },
      {
        mode: "live",
        scopeKey: "live:native:upstox:ACCOUNT-A",
        brokerType: "upstox",
        accountId: "ACCOUNT-A",
      },
    );

    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/orders/upstox/place");
    expect(JSON.parse(String(init.body))).toMatchObject({
      broker: "upstox",
      account_id: "ACCOUNT-A",
      symbol: "RELIANCE",
    });
  });

  it("postOrder normalises terminal order body fields before sending", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { orderId: "ORD-1" } }),
    );

    await placeOrder({
      symbol: "RELIANCE",
      exchange: "NSE",
      action: "BUY",
      quantity: 1,
      price: 100,
      triggerPrice: 99,
      product: "MIS",
      orderType: "SL",
      strategy: "TestStrategy",
      marketProtection: true,
    });

    const body = JSON.parse(
      (fetchSpy.mock.calls[0] as [string, RequestInit])[1].body as string,
    );
    expect(body).toMatchObject({
      order_type: "SL",
      trigger_price: 99,
      market_protection: true,
    });
    expect(body).not.toHaveProperty("apikey");
  });

  it("routes live placeOrder through the active connected native account when no OpenAlgo key is configured", async () => {
    mockConnectionState.apiKey = "";
    mockModeState.mode = "live";
    mockBrokerState.accounts = [
      { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
    ];
    mockBrokerState.activeAccountId = "native:upstox:U1";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { orderId: "UP-1" } }),
    );

    await placeOrder({
      symbol: "RELIANCE",
      exchange: "NSE",
      action: "BUY",
      quantity: 1,
      price_type: "MARKET",
      product: "MIS",
      orderType: "MARKET",
    } as unknown as Parameters<typeof placeOrder>[0]);

    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/orders/upstox/place");
    const body = JSON.parse(init.body as string);
    expect(body).toMatchObject({ broker: "upstox", account_id: "U1", symbol: "RELIANCE" });
    expect(body).not.toHaveProperty("apikey");
  });

  it("fails closed instead of retargeting when the active native account is not yet connected", async () => {
    // Re-audit finding #1: after a reload the persisted active native account
    // rehydrates as not-yet-connected (status !== "connected") until the first
    // poll. Sending on the bare path would let the backend resolve
    // brokers.execution.default and silently route this LIVE order to a
    // different target — so postOrder must reject, not fetch.
    mockConnectionState.apiKey = "";
    mockModeState.mode = "live";
    mockBrokerState.accounts = [
      { account_id: "U1", broker: "upstox", source: "native", status: "disconnected" },
    ];
    mockBrokerState.activeAccountId = "native:upstox:U1";

    await expect(
      placeOrder({
        symbol: "RELIANCE",
        exchange: "NSE",
        action: "BUY",
        quantity: 1,
        price_type: "MARKET",
        product: "MIS",
        orderType: "MARKET",
      } as unknown as Parameters<typeof placeOrder>[0]),
    ).rejects.toThrow(/not available for live writes/i);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("fails closed and never diverts to native before the OpenAlgo config has hydrated", async () => {
    // The apiKey-drop regression: after a reload the in-memory bridge apiKey is
    // transiently "" while the loopback config GET is still in flight. With a
    // connected native account selected, the old code would silently DIVERT a
    // bridge order to that native account. postOrder must instead fail closed
    // with the "still loading" message and never fetch (neither native nor bridge).
    mockConnectionState.apiKey = "";
    mockConnectionState.openAlgoHydrated = false;
    mockModeState.mode = "live";
    mockBrokerState.accounts = [
      { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
    ];
    mockBrokerState.activeAccountId = "native:upstox:U1";

    await expect(
      placeOrder({
        symbol: "RELIANCE",
        exchange: "NSE",
        action: "BUY",
        quantity: 1,
        price_type: "MARKET",
        product: "MIS",
        orderType: "MARKET",
      } as unknown as Parameters<typeof placeOrder>[0]),
    ).rejects.toThrow(/still loading/i);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("does not block practice-mode orders during the OpenAlgo hydration window", async () => {
    // Non-live orders never depend on the bridge-vs-native routing decision (they
    // execute in the SandboxEngine), so the hydration gate must not block them.
    mockConnectionState.apiKey = "";
    mockConnectionState.openAlgoHydrated = false;
    mockModeState.mode = "practice";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { orderId: "SBX-1" } }),
    );

    await placeOrder({
      symbol: "RELIANCE",
      exchange: "NSE",
      action: "BUY",
      quantity: 1,
      price_type: "MARKET",
      product: "MIS",
      orderType: "MARKET",
    } as unknown as Parameters<typeof placeOrder>[0]);

    expect(fetchSpy).toHaveBeenCalledOnce();
    const [url] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/orders/place");
  });

  it("never resolves a rejected Practice order as success", async () => {
    mockModeState.mode = "practice";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        order_id: "",
        status: "REJECTED",
        message: "A market order needs a live price (LTP) to fill",
      }),
    );

    await expect(placeOrder({
      symbol: "RELIANCE",
      exchange: "NSE",
      action: "BUY",
      quantity: 1,
      price_type: "MARKET",
      product: "MIS",
      orderType: "MARKET",
    } as unknown as Parameters<typeof placeOrder>[0])).rejects.toThrow(
      /needs a live price/i,
    );
  });

  it("routes live modifyOrder through the active connected native account", async () => {
    mockConnectionState.apiKey = "";
    mockModeState.mode = "live";
    mockBrokerState.accounts = [
      { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
    ];
    mockBrokerState.activeAccountId = "native:upstox:U1";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { orderId: "UP-7" } }),
    );

    await modifyOrder(
      {
        orderId: "UP-7",
        symbol: "RELIANCE",
        exchange: "NSE",
        action: "BUY",
        quantity: 1,
        price: 101,
        product: "MIS",
        orderType: "LIMIT",
        strategy: "TestStrategy",
      },
      {
        mode: "live",
        scopeKey: "live:native:upstox:U1",
        brokerType: "upstox",
        accountId: "U1",
      },
    );

    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/orders/upstox/modify");
    const body = JSON.parse(init.body as string);
    expect(body).toMatchObject({
      broker: "upstox",
      account_id: "U1",
      orderid: "UP-7",
      order_type: "LIMIT",
    });
  });

  it("routes live cancelOrder through the active connected native account", async () => {
    mockConnectionState.apiKey = "";
    mockModeState.mode = "live";
    mockBrokerState.accounts = [
      { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
    ];
    mockBrokerState.activeAccountId = "native:upstox:U1";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { orderId: "UP-7" } }),
    );

    await cancelOrder("UP-7", "OrderLadder", {
      mode: "live",
      scopeKey: "live:native:upstox:U1",
      brokerType: "upstox",
      accountId: "U1",
    });

    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/orders/upstox/cancel");
    const body = JSON.parse(init.body as string);
    expect(body).toMatchObject({
      broker: "upstox",
      account_id: "U1",
      orderid: "UP-7",
      strategy: "OrderLadder",
    });
  });

  const runtimeInvalidMutationPins = [
    {
      pinName: "undefined",
      authority: undefined as unknown as OrderAuthorityPin,
    },
    {
      pinName: "mode-only",
      authority: { mode: "live" } as unknown as OrderAuthorityPin,
    },
    {
      pinName: "malformed",
      authority: {
        mode: "live",
        scopeKey: "live:openalgo:7d290c41e91d8f71",
        brokerType: "openalgo",
      } as unknown as OrderAuthorityPin,
    },
    {
      pinName: "unsupported-source",
      authority: {
        mode: "explore",
        scopeKey: "explore:mock",
        brokerType: "mock",
        accountId: "default",
      } as unknown as OrderAuthorityPin,
      configure: () => {
        mockModeState.mode = "explore";
      },
    },
  ];

  const runtimeGuardedMutations = [
    {
      mutationName: "cancelOrder",
      mutate: (authority: OrderAuthorityPin) => cancelOrder("A-ORDER", "Orders", authority),
    },
    {
      mutationName: "modifyOrder",
      mutate: (authority: OrderAuthorityPin) => modifyOrder(
        {
          orderId: "A-ORDER",
          symbol: "RELIANCE",
          exchange: "NSE",
          action: "BUY",
          quantity: 1,
          price: 101,
          product: "MIS",
          orderType: "LIMIT",
          strategy: "Orders",
        },
        authority,
      ),
    },
  ];

  it.each(runtimeGuardedMutations.flatMap((mutation) => (
    runtimeInvalidMutationPins.map((invalidPin) => ({ ...mutation, ...invalidPin }))
  )))(
    "$mutationName rejects a runtime $pinName authority before transport",
    async ({ authority, configure, mutate }) => {
      configure?.();
      fetchSpy.mockResolvedValue(
        jsonResponse({ status: "success", data: { orderId: "DEFAULT-FALLBACK" } }),
      );

      await expect(mutate(authority)).rejects.toThrow(/exact.*authority|authority.*exact/i);
      expect(fetchSpy).not.toHaveBeenCalled();
    },
  );

  it.each([
    [
      "cancel",
      () => cancelOrder("A-ORDER", "Orders", {
        mode: "live",
        scopeKey: "live:native:dhan:ACCOUNT-A",
        brokerType: "dhan",
        accountId: "ACCOUNT-A",
      }),
    ],
    [
      "modify",
      () => modifyOrder(
        {
          orderId: "A-ORDER",
          symbol: "RELIANCE",
          exchange: "NSE",
          action: "BUY",
          quantity: 1,
          price: 101,
          product: "MIS",
          orderType: "LIMIT",
          strategy: "Orders",
        },
        {
          mode: "live",
          scopeKey: "live:native:dhan:ACCOUNT-A",
          brokerType: "dhan",
          accountId: "ACCOUNT-A",
        },
      ),
    ],
  ])("refuses a stale account-A %s pin after the imperative stores switch to B", async (_kind, mutate) => {
    mockConnectionState.apiKey = "";
    mockModeState.mode = "live";
    mockBrokerState.accounts = [
      { account_id: "ACCOUNT-A", broker: "dhan", source: "native", status: "connected" },
      { account_id: "ACCOUNT-B", broker: "upstox", source: "native", status: "connected" },
    ];
    mockBrokerState.activeAccountId = "native:upstox:ACCOUNT-B";
    fetchSpy.mockResolvedValue(
      jsonResponse({ status: "success", data: { orderId: "WRONG-ACCOUNT" } }),
    );

    await expect(mutate()).rejects.toThrow(/authority|account|scope/i);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("sends native broker/account selectors for live cancelAllOrders", async () => {
    mockConnectionState.apiKey = "";
    mockModeState.mode = "live";
    mockBrokerState.accounts = [
      { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
    ];
    mockBrokerState.activeAccountId = "native:upstox:U1";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: {} }),
    );

    await cancelAllOrders();

    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/orders/cancel-all");
    expect(url).not.toContain("/api/v1/orders/upstox/cancel-all");
    const body = JSON.parse(init.body as string);
    expect(body).toMatchObject({
      broker: "upstox",
      account_id: "U1",
    });
    expect(body).not.toHaveProperty("strategy");
  });

  it("maps basketOrder params onto the backend legs contract", async () => {
    // The backend basket route reads a `legs` array with snake_case per-leg
    // fields; the terminal-facing params keep camelCase `orders`. Pin the wire
    // mapping field by field.
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({
        status: "success",
        strategy: "FlintLegBuilder",
        placed_count: 2,
        failed_count: 0,
        rolled_back: false,
        order_ids: ["B1", "B2"],
        legs: [],
      }, 201),
    );

    await basketOrder({
      strategy: "FlintLegBuilder",
      orders: [
        {
          symbol: "NIFTY10APR2622000CE",
          exchange: "NFO",
          action: "SELL",
          quantity: 50,
          orderType: "MARKET",
          product: "MIS",
        },
        {
          symbol: "NIFTY10APR2622100CE",
          exchange: "NFO",
          action: "BUY",
          quantity: 50,
          orderType: "LIMIT",
          product: "MIS",
          price: 42.5,
          triggerPrice: 41,
        },
      ],
    });

    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/orders/basket");
    const body = JSON.parse(init.body as string);
    expect(body.strategy).toBe("FlintLegBuilder");
    expect(body).not.toHaveProperty("orders");
    expect(body.legs).toEqual([
      {
        symbol: "NIFTY10APR2622000CE",
        exchange: "NFO",
        action: "SELL",
        quantity: 50,
        order_type: "MARKET",
        product: "MIS",
      },
      {
        symbol: "NIFTY10APR2622100CE",
        exchange: "NFO",
        action: "BUY",
        quantity: 50,
        order_type: "LIMIT",
        product: "MIS",
        price: 42.5,
        trigger_price: 41,
      },
    ]);
    // MARKET leg must NOT carry price/trigger_price keys — the backend parses
    // an absent key as None, and a present key as a float.
    expect(body.legs[0]).not.toHaveProperty("price");
    expect(body.legs[0]).not.toHaveProperty("trigger_price");
  });

  it("sends native broker/account selectors for live basketOrder", async () => {
    // The basket route has no /<broker>/ path variant — the principal comes
    // from `broker` / `account_id` in the body. Without them the backend would
    // resolve brokers.execution.default, silently retargeting the basket.
    mockConnectionState.apiKey = "";
    mockModeState.mode = "live";
    mockBrokerState.accounts = [
      { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
    ];
    mockBrokerState.activeAccountId = "native:upstox:U1";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", placed_count: 1, failed_count: 0, order_ids: ["B1"], legs: [] }, 201),
    );

    await basketOrder({
      orders: [
        { symbol: "NIFTY10APR2622000CE", exchange: "NFO", action: "SELL", quantity: 50, orderType: "MARKET", product: "MIS" },
      ],
    });

    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/orders/basket");
    expect(url).not.toContain("/api/v1/orders/upstox/basket");
    const body = JSON.parse(init.body as string);
    expect(body).toMatchObject({ broker: "upstox", account_id: "U1", strategy: "basket" });
    expect(body.legs).toHaveLength(1);
  });

  it("fails closed for basketOrder when the active native account is not connected", async () => {
    mockConnectionState.apiKey = "";
    mockModeState.mode = "live";
    mockBrokerState.accounts = [
      { account_id: "U1", broker: "upstox", source: "native", status: "disconnected" },
    ];
    mockBrokerState.activeAccountId = "native:upstox:U1";

    await expect(
      basketOrder({
        orders: [
          { symbol: "NIFTY10APR2622000CE", exchange: "NFO", action: "SELL", quantity: 50, orderType: "MARKET", product: "MIS" },
        ],
      }),
    ).rejects.toThrow(/not available for live writes/i);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("sends native broker/account selectors for live splitOrder", async () => {
    // The split route has no /<broker>/ path variant either — order_routes
    // `place_split` resolves its principal from `broker` / `account_id` in the
    // body (`_request_principal` → `_resolve_target`). Without them the whole
    // split would silently retarget to brokers.execution.default.
    mockConnectionState.apiKey = "";
    mockModeState.mode = "live";
    mockBrokerState.accounts = [
      { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
    ];
    mockBrokerState.activeAccountId = "native:upstox:U1";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", placed_count: 4, failed_count: 0, order_ids: [] }, 201),
    );

    await splitOrder({
      symbol: "RELIANCE",
      exchange: "NSE",
      action: "BUY",
      totalQuantity: 100,
      chunkSize: 25,
      orderType: "MARKET",
      product: "MIS",
    });

    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/orders/split");
    expect(url).not.toContain("/api/v1/orders/upstox/split");
    const body = JSON.parse(init.body as string);
    expect(body).toMatchObject({ broker: "upstox", account_id: "U1" });
    // The wire body must carry the snake_case contract place_split requires —
    // pinning the injection against a body the route would 400 on is useless.
    expect(body).toMatchObject({
      symbol: "RELIANCE",
      exchange: "NSE",
      action: "BUY",
      total_qty: 100,
      chunk_size: 25,
      order_type: "MARKET",
      product: "MIS",
    });
    expect(body).not.toHaveProperty("totalQuantity");
    expect(body).not.toHaveProperty("chunkSize");
  });

  it("throws an OrderApiError carrying the HTTP status and the 422 BasketOrderResult body", async () => {
    // place_basket answers 422 with the full per-leg truth on partial failure
    // (order_routes.py). The client must attach that body + status to the
    // thrown error so callers (LegBuilder) can surface placed/failed counts
    // and unconfirmed rollbacks instead of only the first error string.
    const failureBody = {
      status: "error",
      strategy: "FlintLegBuilder",
      timestamp: "2026-07-20T10:15:00+05:30",
      placed_count: 2,
      failed_count: 1,
      rolled_back: true,
      order_ids: ["B1", "B2"],
      legs: [
        { leg_index: 0, symbol: "NIFTY10APR2621900PE", action: "SELL", quantity: 50, success: true, order_id: "B1", error: "", rolled_back: true, rollback_order_id: "" },
        { leg_index: 1, symbol: "NIFTY10APR2622100CE", action: "SELL", quantity: 50, success: true, order_id: "B2", error: "", rolled_back: true, rollback_order_id: "RB2" },
        { leg_index: 2, symbol: "NIFTY10APR2622200CE", action: "BUY", quantity: 50, success: false, order_id: "", error: "Broker 'dhan' is not connected", rolled_back: false, rollback_order_id: "" },
      ],
      message: "Leg 3 failed: Broker 'dhan' is not connected",
      failed_leg_index: 2,
    };
    fetchSpy.mockResolvedValueOnce(jsonResponse(failureBody, 422));

    const err: unknown = await basketOrder({
      orders: [
        { symbol: "NIFTY10APR2621900PE", exchange: "NFO", action: "SELL", quantity: 50, orderType: "MARKET", product: "MIS" },
      ],
    }).then(
      () => { throw new Error("expected basketOrder to reject"); },
      (e: unknown) => e,
    );

    // Backward compatible: still an Error with the server message as .message.
    expect(err).toBeInstanceOf(Error);
    expect(err).toBeInstanceOf(OrderApiError);
    const apiErr = err as OrderApiError;
    expect(apiErr.message).toBe("Leg 3 failed: Broker 'dhan' is not connected");
    expect(apiErr.status).toBe(422);
    expect(apiErr.body).toEqual(failureBody);
  });

  it("routes live exit-all through the confirmed account-scoped safety endpoint", async () => {
    mockConnectionState.apiKey = "";
    mockModeState.mode = "live";
    mockBrokerState.accounts = [
      { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
    ];
    mockBrokerState.activeAccountId = "native:upstox:U1";
    fetchSpy.mockResolvedValueOnce(jsonResponse({ status: "success", data: {} }));

    await exitAllPositions();

    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/positions/exit-all");
    expect(JSON.parse(init.body as string)).toEqual({
      confirm: true,
      broker: "upstox",
      account_id: "U1",
    });
    expect(new Headers(init.headers).get("X-FlintTrade-Mode")).toBe("live");
  });

  it("uses the explicit OpenAlgo selector for a bridge exit-all", async () => {
    fetchSpy.mockResolvedValueOnce(jsonResponse({ status: "success", data: {} }));

    await exitAllPositions();

    const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({
      confirm: true,
      broker: "openalgo",
      account_id: "default",
    });
  });

  it("routes legacy GTT helpers through the gated forever-order endpoints", async () => {
    mockConnectionState.apiKey = "";
    mockModeState.mode = "live";
    mockBrokerState.accounts = [
      { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
    ];
    mockBrokerState.activeAccountId = "native:upstox:U1";
    fetchSpy
      .mockResolvedValueOnce(jsonResponse({ status: "success", data: { order_id: "GTT-1" } }))
      .mockResolvedValueOnce(jsonResponse({ status: "success", data: { order_id: "GTT-1" } }))
      .mockResolvedValueOnce(jsonResponse({ status: "success", data: { order_id: "GTT-1" } }))
      .mockResolvedValueOnce(
        jsonResponse({ status: "success", data: [{ trigger_id: "GTT-1", symbol: "RELIANCE" }] }),
      );

    await placeGtt({
      trigger_type: "OCO",
      entry_trigger_type: "BELOW",
      symbol: "RELIANCE",
      exchange: "NSE",
      action: "BUY",
      product: "CNC",
      quantity: 1,
      pricetype: "LIMIT",
      price: 100,
      triggerprice_sl: 95,
      triggerprice_tg: 110,
      stoploss: 94,
      target: 111,
    });

    const [placeUrl, placeInit] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(placeUrl).toContain("/api/v1/orders/forever");
    expect(placeInit.method).toBe("POST");
    const placeBody = JSON.parse(placeInit.body as string);
    expect(placeBody).toMatchObject({
      broker: "upstox",
      account_id: "U1",
      variety: "gtt",
      entry_trigger_type: "BELOW",
      trigger_price: 95,
      price: 94,
      trigger_price1: 110,
      price1: 111,
      quantity1: 1,
    });

    await modifyGtt({
      trigger_id: "GTT-1",
      trigger_type: "SINGLE",
      entry_trigger_type: "IMMEDIATE",
      symbol: "RELIANCE",
      exchange: "NSE",
      action: "BUY",
      product: "CNC",
      quantity: 2,
      price: 101,
      triggerprice_sl: 96,
    });

    const [modifyUrl, modifyInit] = fetchSpy.mock.calls[1] as [string, RequestInit];
    expect(modifyUrl).toContain("/api/v1/orders/forever/GTT-1");
    expect(modifyInit.method).toBe("PUT");
    expect(JSON.parse(modifyInit.body as string)).toMatchObject({
      broker: "upstox",
      account_id: "U1",
      changes: { quantity: 2, trigger_price: 96, price: 101, entry_trigger_type: "IMMEDIATE" },
    });

    await cancelGtt({ trigger_id: "GTT-1" });
    const [cancelUrl, cancelInit] = fetchSpy.mock.calls[2] as [string, RequestInit];
    expect(cancelUrl).toContain("/api/v1/orders/forever/GTT-1");
    expect(cancelUrl).toContain("broker=upstox");
    expect(cancelUrl).toContain("account_id=U1");
    expect(cancelInit.method).toBe("DELETE");

    const rows = await getGttOrderbook();
    const [listUrl, listInit] = fetchSpy.mock.calls[3] as [string, RequestInit];
    expect(listUrl).toContain("/api/v1/orders/forever");
    expect(listUrl).toContain("broker=upstox");
    expect(listUrl).toContain("account_id=U1");
    expect(listInit.method).toBe("GET");
    expect(rows).toStrictEqual([{ trigger_id: "GTT-1", symbol: "RELIANCE" }]);
  });

  it("keeps Practice placeOrder on the safety proxy and never targets a native broker API", async () => {
    mockConnectionState.apiKey = "";
    mockModeState.mode = "practice";
    mockBrokerState.accounts = [
      { account_id: "U1", broker: "upstox", source: "native", status: "connected" },
    ];
    mockBrokerState.activeAccountId = "native:upstox:U1";
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { orderId: "SIM-1" } }),
    );

    await placeOrder({
      symbol: "RELIANCE",
      exchange: "NSE",
      action: "BUY",
      quantity: 1,
      price_type: "MARKET",
      product: "MIS",
      orderType: "MARKET",
    } as unknown as Parameters<typeof placeOrder>[0]);

    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/orders/place");
    expect(url).not.toContain("/api/v1/orders/upstox/place");
    expect(new Headers(init.headers).get("X-FlintTrade-Mode")).toBe("practice");
    const body = JSON.parse(init.body as string);
    expect(body).not.toHaveProperty("broker");
    expect(body).not.toHaveProperty("account_id");
  });

  it("postOrder does NOT include apikey in the body (backend injects it)", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { orderId: "ORD-2" } }),
    );

    await cancelAllOrders();

    const body = JSON.parse(
      (fetchSpy.mock.calls[0] as [string, RequestInit])[1].body as string,
    );
    expect(body).not.toHaveProperty("apikey");
    expect(body).not.toHaveProperty("strategy");
  });

  // ---- Response unwrapping ----

  it("unwraps { data: X } from successful response", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { status: "pong" } }),
    );

    const result = await ping();
    expect(result).toEqual({ status: "pong" });
  });

  it("falls back to raw json when data key is absent", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", ltp: 100 }),
    );

    const result = await getQuotes("INFY", "NSE");
    // When no `data` key, returns entire json
    expect(result).toHaveProperty("ltp", 100);
  });

  it("unwraps nested arrays (positionbook with positions key)", async () => {
    const positions = [{ symbol: "NIFTY", quantity: 50 }];
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { positions } }),
    );

    const result = await getPositionbook(OPENALGO_READ_CONTEXT);
    expect(result).toEqual(positions);
  });

  // ---- Error responses ----

  it("throws on 401 with descriptive message", async () => {
    fetchSpy.mockResolvedValueOnce(jsonResponse({ message: "Unauthorized" }, 401));

    await expect(getQuotes("NIFTY", "NSE")).rejects.toThrow(
      "API key invalid. Check Settings → Connection.",
    );
  });

  it("throws on 500 with server message when available", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ error: "DB connection lost" }, 500),
    );

    await expect(getFunds(OPENALGO_READ_CONTEXT)).rejects.toThrow("DB connection lost");
  });

  it("throws generic message for unexpected status codes", async () => {
    fetchSpy.mockResolvedValueOnce(jsonResponse({}, 429));

    await expect(getFunds(OPENALGO_READ_CONTEXT)).rejects.toThrow("Server error (429)");
  });

  it("throws on status: error in JSON body", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "error", message: "Symbol not found" }),
    );

    await expect(getQuotes("INVALID", "NSE")).rejects.toThrow("Symbol not found");
  });

  // ---- Network errors ----

  it("throws descriptive error on network failure (POST)", async () => {
    fetchSpy.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(getFunds(OPENALGO_READ_CONTEXT)).rejects.toThrow(
      "Connection failed. Check OpenAlgo is running.",
    );
  });

  it("throws descriptive error on network failure (postOrder)", async () => {
    fetchSpy.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(placeOrder({} as Parameters<typeof placeOrder>[0])).rejects.toThrow(
      "Connection failed. Check FlintTrade backend is running.",
    );
  });

  // ---- Rate limiting ----

  it("throws when general rate limiter is exhausted (POST)", async () => {
    vi.mocked(generalLimiter.tryConsume).mockReturnValue(false);

    await expect(getFunds(OPENALGO_READ_CONTEXT)).rejects.toThrow("Rate limit exceeded");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("throws when order rate limiter is exhausted (postOrder)", async () => {
    vi.mocked(orderLimiter.tryConsume).mockReturnValue(false);

    await expect(
      placeOrder({} as Parameters<typeof placeOrder>[0]),
    ).rejects.toThrow("Rate limit exceeded");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  // ---- Input sanitisation ----

  it("searchSymbol sanitises query and sends POST", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: [{ symbol: "RELIANCE", exchange: "NSE" }] }),
    );

    const result = await searchSymbol("RELIANCE<script>");
    expect(result).toEqual([{ symbol: "RELIANCE", exchange: "NSE" }]);

    const body = JSON.parse(
      (fetchSpy.mock.calls[0] as [string, RequestInit])[1].body as string,
    );
    // angle brackets stripped by the sanitiser
    expect(body.query).not.toContain("<");
    expect(body.query).not.toContain(">");
  });
});
