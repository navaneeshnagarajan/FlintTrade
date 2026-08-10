/**
 * Tests for useModeData — mode-aware data routing hook.
 *
 * Verifies that:
 *   1. Explore mode returns mock data from MockDataEngine
 *   2. Live/practice mode delegates to TanStack Query hooks
 *   3. Switching mode changes the data source
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import type { AccountReadContext } from "@/hooks/useAccountReadsEnabled";
import {
  CONNECTED_NATIVE_READ_CONTEXT,
  PRACTICE_READ_CONTEXT,
  UNCONFIGURED_LIVE_READ_CONTEXT,
} from "@/test-utils/accountReadFixtures";

// ---------------------------------------------------------------------------
// Mock modeStore — start in explore mode, allow switching
// ---------------------------------------------------------------------------

let currentMode: "explore" | "practice" | "live" = "explore";
let brokerConnected = true;
const modeListeners = new Set<() => void>();
const accountReadState = vi.hoisted(() => ({
  current: undefined as AccountReadContext | undefined,
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) => {
    // Mimic Zustand selector subscription — re-render on mode change
    const [, setState] = React.useState(0);
    React.useEffect(() => {
      const cb = () => setState((n) => n + 1);
      modeListeners.add(cb);
      return () => { modeListeners.delete(cb); };
    }, []);
    return selector({ mode: currentMode });
  },
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => brokerConnected,
}));

vi.mock("@/hooks/useAccountReadsEnabled", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useAccountReadsEnabled")>()),
  useAccountReadContext: () => accountReadState.current,
}));

function setTestMode(mode: "explore" | "practice" | "live") {
  currentMode = mode;
  modeListeners.forEach((cb) => cb());
}

// ---------------------------------------------------------------------------
// Mock API service — prevent real network calls
// ---------------------------------------------------------------------------

const mockPositions = [{ symbol: "NIFTY", exchange: "NFO", quantity: 50, pnl: 1200 }];
const mockOrders = [{ orderId: "ORD001", symbol: "NIFTY", status: "COMPLETE" }];
const mockHoldings = [{ symbol: "RELIANCE", exchange: "NSE", quantity: 10 }];
const mockFunds = { available_balance: 50000, utilized_margin: 10000, total_balance: 60000 };
const mockTrades = [{ trade_id: "T001", symbol: "RELIANCE", side: "BUY" }];
const mockGetFunds = vi.fn((_context: AccountReadContext, _signal?: AbortSignal) =>
  Promise.resolve(mockFunds));
const mockGetHoldings = vi.fn((_context: AccountReadContext, _signal?: AbortSignal) =>
  Promise.resolve(mockHoldings));
const mockGetOrderbook = vi.fn((_context: AccountReadContext, _signal?: AbortSignal) =>
  Promise.resolve(mockOrders));
const mockGetPositionbook = vi.fn((_context: AccountReadContext, _signal?: AbortSignal) =>
  Promise.resolve(mockPositions));
const mockGetTradebook = vi.fn((_context: AccountReadContext, _signal?: AbortSignal) =>
  Promise.resolve(mockTrades));
const accountDataCases = [
  ["positions", mockPositions, mockGetPositionbook],
  ["orders", mockOrders, mockGetOrderbook],
  ["holdings", mockHoldings, mockGetHoldings],
  ["funds", mockFunds, mockGetFunds],
  ["tradebook", mockTrades, mockGetTradebook],
] as const;

function accountTransportMocks() {
  return [
    mockGetPositionbook,
    mockGetOrderbook,
    mockGetHoldings,
    mockGetFunds,
    mockGetTradebook,
  ];
}

vi.mock("@/services/api", () => ({
  getFunds: (context: AccountReadContext, signal?: AbortSignal) => mockGetFunds(context, signal),
  getHoldings: (context: AccountReadContext, signal?: AbortSignal) => mockGetHoldings(context, signal),
  getOrderbook: (context: AccountReadContext, signal?: AbortSignal) => mockGetOrderbook(context, signal),
  getPositionbook: (context: AccountReadContext, signal?: AbortSignal) => mockGetPositionbook(context, signal),
  getTradebook: (context: AccountReadContext, signal?: AbortSignal) => mockGetTradebook(context, signal),
}));

// Mock market hours
vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

// Mock tradingStore
vi.mock("@/stores/tradingStore", () => ({
  useTradingStore: {
    getState: () => ({
      updateFromFunds: vi.fn(),
      updateFromPositions: vi.fn(),
    }),
  },
}));

// Mock mockDataEngine
vi.mock("@/services/mockDataEngine", () => {
  const mockEngine = {
    getMockPositions: () => [{ symbol: "NIFTY", exchange: "NSE_INDEX", pnl: 999, side: "BUY", quantity: 25, avgPrice: 24100, ltp: 24150, product: "MIS" }],
    getMockOrders: () => [{ orderId: "MOCK001", symbol: "NIFTY", status: "COMPLETE", exchange: "NSE_INDEX", side: "BUY", product: "MIS", orderType: "MARKET", quantity: 10, price: 24150, timestamp: "2026-04-08T10:00:00Z" }],
    getMockHoldings: () => [{ symbol: "RELIANCE", exchange: "NSE", quantity: 15, avgPrice: 2800, ltp: 2850, currentValue: 42750, pnl: 750, pnlPct: 1.79 }],
    getSnapshot: () => [
      { symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 24150, change: 50, changePct: 0.21, volume: 300000, open: 24100, high: 24200, low: 24050, close: 24100 },
    ],
  };
  return {
    mockDataEngine: mockEngine,
    MockDataEngine: vi.fn(() => mockEngine),
  };
});

// ---------------------------------------------------------------------------
// Import hook after mocks
// ---------------------------------------------------------------------------

import { useModeData } from "../useModeData";

// ---------------------------------------------------------------------------
// Wrapper
// ---------------------------------------------------------------------------

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

// ---------------------------------------------------------------------------
// Reset
// ---------------------------------------------------------------------------

beforeEach(() => {
  currentMode = "explore";
  brokerConnected = true;
  accountReadState.current = CONNECTED_NATIVE_READ_CONTEXT;
  modeListeners.clear();
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests: Explore mode
// ---------------------------------------------------------------------------

describe("useModeData — explore mode", () => {
  it("returns mock positions without loading state", () => {
    const { result } = renderHook(() => useModeData("positions"), {
      wrapper: createWrapper(),
    });

    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.data).toBeDefined();
    expect(Array.isArray(result.current.data)).toBe(true);
    // Verify it's mock data (has the mock engine's shape)
    const positions = result.current.data as Array<{ symbol: string }>;
    expect(positions[0].symbol).toBe("NIFTY");
  });

  it("returns mock orders", () => {
    const { result } = renderHook(() => useModeData("orders"), {
      wrapper: createWrapper(),
    });

    expect(result.current.isLoading).toBe(false);
    const orders = result.current.data as Array<{ orderId: string }>;
    expect(orders[0].orderId).toBe("MOCK001");
  });

  it("returns mock holdings", () => {
    const { result } = renderHook(() => useModeData("holdings"), {
      wrapper: createWrapper(),
    });

    const holdings = result.current.data as Array<{ symbol: string }>;
    expect(holdings[0].symbol).toBe("RELIANCE");
  });

  it("returns mock funds", () => {
    const { result } = renderHook(() => useModeData("funds"), {
      wrapper: createWrapper(),
    });

    // Explore funds are mapped to the canonical Funds shape (availableCash),
    // not the engine's internal naming — so widgets read the same field as live.
    const funds = result.current.data as { availableCash: number };
    expect(funds.availableCash).toBe(250_000);
  });

  it("returns mock watchlist", () => {
    const { result } = renderHook(() => useModeData("watchlist"), {
      wrapper: createWrapper(),
    });

    const watchlist = result.current.data as Array<{ symbol: string }>;
    expect(watchlist[0].symbol).toBe("NIFTY");
  });

  it("provides a refetch function that refreshes mock data", () => {
    const { result } = renderHook(() => useModeData("positions"), {
      wrapper: createWrapper(),
    });

    // refetch should not throw
    expect(typeof result.current.refetch).toBe("function");
    act(() => {
      result.current.refetch();
    });
    // Data should still be present after refetch
    expect(result.current.data).toBeDefined();
  });
});

// ---------------------------------------------------------------------------
// Tests: Live mode (delegates to API)
// ---------------------------------------------------------------------------

describe("useModeData — live mode", () => {
  beforeEach(() => {
    currentMode = "live";
  });

  it.each(accountDataCases)(
    "keeps %s idle when a broker boolean lacks selected account authority",
    (key) => {
      brokerConnected = true;
      accountReadState.current = UNCONFIGURED_LIVE_READ_CONTEXT;

      const { result } = renderHook(() => useModeData(key), {
        wrapper: createWrapper(),
      });

      expect(result.current.isLoading).toBe(false);
      expect(result.current.data).toBeUndefined();
      for (const transport of accountTransportMocks()) {
        expect(transport).not.toHaveBeenCalled();
      }
    },
  );

  it.each(accountDataCases)(
    "routes %s through the exact connected native authority",
    async (key, expectedData, expectedTransport) => {
      const { result } = renderHook(() => useModeData(key), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.data).toEqual(expectedData));
      expect(expectedTransport).toHaveBeenCalledOnce();
      expect(expectedTransport).toHaveBeenCalledWith(
        CONNECTED_NATIVE_READ_CONTEXT,
        expect.any(AbortSignal),
      );
      for (const transport of accountTransportMocks()) {
        if (transport !== expectedTransport) expect(transport).not.toHaveBeenCalled();
      }
    },
  );
});

describe("useModeData — practice mode", () => {
  it.each(accountDataCases)(
    "routes %s through sandbox authority without requiring a Live broker",
    async (key, expectedData, expectedTransport) => {
      currentMode = "practice";
      brokerConnected = false;
      accountReadState.current = PRACTICE_READ_CONTEXT;

      const { result } = renderHook(() => useModeData(key), {
        wrapper: createWrapper(),
      });

      await waitFor(() => expect(result.current.data).toEqual(expectedData));
      expect(expectedTransport).toHaveBeenCalledOnce();
      expect(expectedTransport).toHaveBeenCalledWith(
        PRACTICE_READ_CONTEXT,
        expect.any(AbortSignal),
      );
      for (const transport of accountTransportMocks()) {
        if (transport !== expectedTransport) expect(transport).not.toHaveBeenCalled();
      }
    },
  );
});

// ---------------------------------------------------------------------------
// Tests: Mode switching
// ---------------------------------------------------------------------------

describe("useModeData — mode switching", () => {
  it("switches from explore to live data source", async () => {
    const { result } = renderHook(() => useModeData("positions"), {
      wrapper: createWrapper(),
    });

    // Initially in explore mode — mock data
    const explorePosns = result.current.data as Array<{ pnl: number }>;
    expect(explorePosns[0].pnl).toBe(999); // mock engine value

    // Switch to live
    act(() => {
      setTestMode("live");
    });

    // Wait for API data to arrive — waitFor retries until the assertion passes
    await waitFor(() => {
      const liveData = result.current.data as Array<{ pnl: number }> | undefined;
      expect(liveData).toBeDefined();
      expect(liveData!.length).toBeGreaterThan(0);
      expect(liveData![0].pnl).toBe(1200); // API value
    });
  });

  it("switches from live to explore data source", async () => {
    currentMode = "live";

    const { result } = renderHook(() => useModeData("funds"), {
      wrapper: createWrapper(),
    });

    // Wait for API data
    await waitFor(() => {
      const funds = result.current.data as { available_balance: number } | undefined;
      return funds?.available_balance === 50000;
    });

    // Switch to explore
    act(() => {
      setTestMode("explore");
    });

    await waitFor(() => {
      const funds = result.current.data as { availableCash: number };
      return funds.availableCash === 250_000;
    });

    const funds = result.current.data as { availableCash: number };
    expect(funds.availableCash).toBe(250_000); // canonical explore mock value
  });
});
