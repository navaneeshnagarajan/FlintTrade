import { describe, it, expect, vi, beforeEach, afterEach, type MockInstance } from "vitest";

const mockConnectionState = vi.hoisted(() => ({
  host: "http://localhost:5000",
  apiKey: "test-key-123",
  openAlgoHydrated: true,
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
  cancelAllOrders,
  cancelOrder,
  modifyOrder,
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
  getPnlSymbols,
  sendTelegram,
  ping,
  searchSymbol,
  getPositionbook,
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

    await getFunds();

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

  it("uses the primary live native account for funds when no OpenAlgo key is configured", async () => {
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
          data: { available_balance: "100.50", used_margin: "20.25", total_balance: "120.75" },
        }),
      );

    const result = await getFunds();

    expect(result).toEqual({ availableCash: 100.5, usedMargin: 20.25, totalBalance: 120.75 });
    expect((fetchSpy.mock.calls[0] as [string, RequestInit | undefined])[0]).toContain("/api/v1/native/accounts");
    expect((fetchSpy.mock.calls[1] as [string, RequestInit | undefined])[0]).toContain(
      "/api/v1/native/accounts/dhan/D1/funds",
    );
    expect(fetchSpy).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/funds"),
      expect.anything(),
    );
  });

  it("uses the active live native account before the primary native fallback", async () => {
    mockConnectionState.apiKey = "";
    mockBrokerState.accounts = [
      { account_id: "D1", broker: "dhan", source: "native" },
      { account_id: "U1", broker: "upstox", source: "native" },
    ];
    mockBrokerState.activeAccountId = "U1";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "dhan", account_id: "D1", is_primary: true, has_session: true },
              { adapter_id: "upstox", account_id: "U1", is_primary: false, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: [{ symbol: "INFY", quantity: 2 }],
        }),
      );

    const result = await getPositionbook();

    expect(result).toEqual([{ symbol: "INFY", quantity: 2 }]);
    expect((fetchSpy.mock.calls[1] as [string, RequestInit | undefined])[0]).toContain(
      "/api/v1/native/accounts/upstox/U1/positions",
    );
  });

  it("uses a broker-aware active native key when multiple brokers share the same account id", async () => {
    mockConnectionState.apiKey = "";
    mockBrokerState.accounts = [
      { account_id: "SHARED", broker: "dhan", source: "native" },
      { account_id: "SHARED", broker: "upstox", source: "native" },
    ];
    mockBrokerState.activeAccountId = "native:upstox:SHARED";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: {
            accounts: [
              { adapter_id: "dhan", account_id: "SHARED", is_primary: true, has_session: true },
              { adapter_id: "upstox", account_id: "SHARED", is_primary: false, has_session: true },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
          data: [{ symbol: "SBIN", quantity: 5 }],
        }),
      );

    const result = await getPositionbook();

    expect(result).toEqual([{ symbol: "SBIN", quantity: 5 }]);
    expect((fetchSpy.mock.calls[1] as [string, RequestInit | undefined])[0]).toContain(
      "/api/v1/native/accounts/upstox/SHARED/positions",
    );
  });

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

    await expect(getPositionbook()).rejects.toThrow();
    const urls = fetchSpy.mock.calls.map(([url]) => String(url));
    expect(urls.some((url) => url.includes("/api/v1/native/accounts/dhan/D1/positions"))).toBe(false);
  });

  it("still uses the primary native account when no account is actively selected", async () => {
    mockConnectionState.apiKey = "";
    mockBrokerState.accounts = [];
    mockBrokerState.activeAccountId = null;
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
          data: [{ symbol: "RELIANCE", quantity: 1 }],
        }),
      );

    const result = await getPositionbook();

    expect(result).toEqual([{ symbol: "RELIANCE", quantity: 1 }]);
    expect((fetchSpy.mock.calls[1] as [string, RequestInit | undefined])[0]).toContain(
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

  it("uses native margin calculator when a live native account is connected without an OpenAlgo key", async () => {
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
            required_margin: "2500.5",
            span_margin: "2000.25",
            exposure_margin: "500.25",
          },
        }),
      );

    const result = await getMargin("INFY", "NSE", 10, "MIS", "BUY");

    expect(result).toMatchObject({
      required_margin: 2500.5,
      total_margin_required: 2500.5,
      span_margin: 2000.25,
      exposure_margin: 500.25,
    });
    expect((fetchSpy.mock.calls[1] as [string, RequestInit | undefined])[0]).toContain(
      "/api/v1/native/accounts/upstox/U1/margin?symbol=INFY&exchange=NSE&qty=10&product=MIS&action=BUY",
    );
    expect(fetchSpy).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/margin"),
      expect.anything(),
    );
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
            holiday_type: "TRADING_HOLIDAY",
            closed_exchanges: ["NSE", "BSE"],
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
      holiday_type: "TRADING_HOLIDAY",
      closed_exchanges: ["NSE", "BSE"],
      open_exchanges: [],
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
            { delta: "0.55", gamma: "0.002", theta: "-8.1", vega: "6.4", iv: "13.2" },
            { Delta: "-0.45", Gamma: "0.003", Theta: "-7.1", Vega: "5.4", IV: "14.2" },
          ],
        }),
      );

    const result = await getMultiOptionGreeks([
      { symbol: "NIFTY24600CE", exchange: "NFO" },
      { symbol: "NIFTY24700PE", exchange: "NFO" },
    ]);

    expect(result).toEqual([
      { delta: 0.55, gamma: 0.002, theta: -8.1, vega: 6.4, iv: 13.2 },
      { delta: -0.45, gamma: 0.003, theta: -7.1, vega: 5.4, iv: 14.2 },
    ]);
    expect((fetchSpy.mock.calls[1] as [string, RequestInit | undefined])[0]).toContain(
      "/api/v1/native/accounts/upstox/U1/optiongreeks?symbols=NFO%3ANIFTY24600CE%2CNFO%3ANIFTY24700PE",
    );
    expect(fetchSpy).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/multioptiongreeks"),
      expect.anything(),
    );
  });

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
            strikes: [
              {
                strike_price: 25000,
                ce_ltp: "100.5",
                ce_oi: "10",
                ce_volume: "1000",
                pe_ltp: "80.25",
                pe_oi: "20",
                pe_volume: "2000",
              },
            ],
          },
        }),
      );

    const expiries = await getExpiry("NIFTY", "NSE_INDEX");
    const chain = await getOptionChain("NIFTY", "NSE_INDEX", "2026-07-30") as unknown as {
      chain: Array<{ strike: number; ce: { ltp: number; oi: number }; pe: { ltp: number; oi: number } }>;
      pcr: number;
    };

    expect(expiries).toEqual({ expiry: ["2026-07-30"] });
    expect(chain.chain[0]).toMatchObject({
      strike: 25000,
      ce: { ltp: 100.5, oi: 10 },
      pe: { ltp: 80.25, oi: 20 },
    });
    expect(chain.pcr).toBe(2);
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
            underlying_ltp: "25020",
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

    expect(result).toMatchObject({
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

  it("routes legacy market-intelligence reads through FlintTrade backend shapes", async () => {
    mockConnectionState.apiKey = "";
    fetchSpy
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
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
          data: {
            curves: [
              {
                points: [
                  { strike: 25000, call_iv: "12.5", put_iv: "13.25", moneyness: "0" },
                ],
              },
            ],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          status: "success",
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

    expect(gex).toEqual([
      { strike: 25000, call_gamma: 1.5, put_gamma: -0.25, net_gamma: 1.25, call_oi: 100, put_oi: 80 },
    ]);
    expect(ivSmile).toEqual([
      { strike: 25000, call_iv: 12.5, put_iv: 13.25, moneyness: 0 },
    ]);
    expect(oiProfile).toEqual([
      { strike: 25000, type: "CE", oi: 100, oi_delta_d: 5, ltp: 0 },
      { strike: 25000, type: "PE", oi: 130, oi_delta_d: -3, ltp: 0 },
    ]);
    const urls = fetchSpy.mock.calls.map((call) => (call as [string, RequestInit])[0]);
    expect(urls).toEqual([
      expect.stringContaining("/api/v1/gex"),
      expect.stringContaining("/api/v1/ivsmile"),
      expect.stringContaining("/api/v1/oiprofile"),
    ]);
    expect(urls.some((url) => url.includes("/api/v1/iv_smile"))).toBe(false);
    expect(urls.some((url) => url.includes("/api/v1/oi_profile"))).toBe(false);
  });

  it("keeps explore mode on sample account data instead of touching native accounts", async () => {
    mockConnectionState.apiKey = "";
    mockModeState.mode = "explore";

    const result = await getFunds();

    expect(result).toEqual({ availableCash: 250_000, usedMargin: 48_500, totalBalance: 298_500 });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("never reads a real native account balance in practice mode", async () => {
    // Finding #4: an account-scoped native read (funds) must be Live-only. In
    // Practice the real balance must never surface as sandbox state, so the read
    // fails closed before any native fetch rather than showing live funds.
    mockConnectionState.apiKey = "";
    mockModeState.mode = "practice";
    mockBrokerState.accounts = [{ account_id: "D1", broker: "dhan", source: "native" }];
    mockBrokerState.activeAccountId = "native:dhan:D1";

    await expect(getFunds()).rejects.toThrow();
    expect(fetchSpy).not.toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/native/accounts"),
      expect.anything(),
    );
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

  it("keeps P&L symbols on the FlintTrade backend instead of requiring an OpenAlgo key", async () => {
    mockConnectionState.apiKey = "";
    const response = {
      status: "success",
      date_from: null,
      date_to: null,
      series_count: 1,
      period: {
        realized_pnl: 500,
        unrealized_pnl: 25,
        total_pnl: 525,
        trade_count: 2,
      },
      overall_summary: {
        realized: 500,
        unrealized: 25,
        total: 525,
        max_total: 525,
        min_total: 0,
        trade_count: 2,
        data_points: 1,
      },
    };
    fetchSpy.mockResolvedValueOnce(jsonResponse(response));

    const result = await getPnlSymbols();

    expect(result).toEqual(response);
    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/ft-api/api/v1/pnl/symbols");
    expect(init.method).toBeUndefined();
    expect(init.body).toBeUndefined();
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

    await modifyOrder({
      orderId: "UP-7",
      symbol: "RELIANCE",
      exchange: "NSE",
      action: "BUY",
      quantity: 1,
      price: 101,
      product: "MIS",
      orderType: "LIMIT",
      strategy: "TestStrategy",
    });

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

    await cancelOrder("UP-7", "OrderLadder");

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

    await cancelAllOrders("Scalper");

    const [url, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/api/v1/orders/cancel-all");
    expect(url).not.toContain("/api/v1/orders/upstox/cancel-all");
    const body = JSON.parse(init.body as string);
    expect(body).toMatchObject({
      broker: "upstox",
      account_id: "U1",
      strategy: "Scalper",
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

  it("keeps practice native placeOrder on the default safety proxy path", async () => {
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
    const body = JSON.parse(init.body as string);
    expect(body).not.toHaveProperty("account_id");
  });

  it("postOrder does NOT include apikey in the body (backend injects it)", async () => {
    fetchSpy.mockResolvedValueOnce(
      jsonResponse({ status: "success", data: { orderId: "ORD-2" } }),
    );

    await cancelAllOrders("TestStrategy");

    const body = JSON.parse(
      (fetchSpy.mock.calls[0] as [string, RequestInit])[1].body as string,
    );
    expect(body).not.toHaveProperty("apikey");
    expect(body).toHaveProperty("strategy", "TestStrategy");
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

    const result = await getPositionbook();
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

    await expect(getFunds()).rejects.toThrow("DB connection lost");
  });

  it("throws generic message for unexpected status codes", async () => {
    fetchSpy.mockResolvedValueOnce(jsonResponse({}, 429));

    await expect(getFunds()).rejects.toThrow("Server error (429)");
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

    await expect(getFunds()).rejects.toThrow(
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

    await expect(getFunds()).rejects.toThrow("Rate limit exceeded");
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
