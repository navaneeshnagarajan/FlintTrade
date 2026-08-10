/**
 * Tests for useModeData — mode-aware data routing hook.
 *
 * Verifies that:
 *   1. Explore mode returns mock data from MockDataEngine
 *   2. Live/practice mode delegates to TanStack Query hooks
 *   3. Switching mode changes the data source
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// Broker account discovery is tested separately. Keep this suite network-free
// while exercising the real mode, connection, broker, and account-read stores.
vi.mock("@/hooks/useBrokerAccounts", () => ({
  useBrokerAccounts: () => ({ data: [] }),
}));

// ---------------------------------------------------------------------------
// Mock API service — prevent real network calls
// ---------------------------------------------------------------------------

const mockPositions = [{ symbol: "NIFTY", exchange: "NFO", quantity: 50, pnl: 1200 }];
const mockOrders = [{ orderId: "ORD001", symbol: "NIFTY", status: "COMPLETE" }];
const mockHoldings = [{ symbol: "RELIANCE", exchange: "NSE", quantity: 10 }];
const mockFunds = { available_balance: 50000, utilized_margin: 10000, total_balance: 60000 };
const mockTrades = [{ trade_id: "T001", symbol: "RELIANCE", side: "BUY" }];

vi.mock("@/services/api", () => ({
  getFunds: () => Promise.resolve(mockFunds),
  getHoldings: () => Promise.resolve(mockHoldings),
  getOrderbook: () => Promise.resolve(mockOrders),
  getPositionbook: () => Promise.resolve(mockPositions),
  getTradebook: () => Promise.resolve(mockTrades),
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
import {
  resetAccountRuntime,
  setAccountRuntime,
} from "@/test-utils/accountQueryHarness";

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
  vi.clearAllMocks();
  setAccountRuntime({ mode: "explore" });
});

afterEach(() => {
  resetAccountRuntime();
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
    setAccountRuntime({ mode: "live" });
  });

  it("returns API positions data", async () => {
    const { result } = renderHook(() => useModeData("positions"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    const positions = result.current.data as Array<{ symbol: string }>;
    expect(positions).toEqual(mockPositions);
  });

  it("returns API orders data", async () => {
    const { result } = renderHook(() => useModeData("orders"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data).toEqual(mockOrders);
  });

  it("returns API funds data", async () => {
    const { result } = renderHook(() => useModeData("funds"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data).toEqual(mockFunds);
  });

  it("does not fetch account data when live mode has no broker connection", () => {
    setAccountRuntime({ accounts: [], mode: "live" });

    const { result } = renderHook(() => useModeData("orders"), {
      wrapper: createWrapper(),
    });

    expect(result.current.isLoading).toBe(false);
    expect(result.current.data).toBeUndefined();
  });
});

describe("useModeData — practice mode", () => {
  it("reads the backend sandbox without requiring a live broker connection", async () => {
    setAccountRuntime({ accounts: [], mode: "practice" });

    const { result } = renderHook(() => useModeData("positions"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.data).toEqual(mockPositions));
  });
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

    // Switch to live through the same real account stores used by production.
    setAccountRuntime({ mode: "live" });

    // Wait for API data to arrive — waitFor retries until the assertion passes
    await waitFor(() => {
      const liveData = result.current.data as Array<{ pnl: number }> | undefined;
      expect(liveData).toBeDefined();
      expect(liveData!.length).toBeGreaterThan(0);
      expect(liveData![0].pnl).toBe(1200); // API value
    });
  });

  it("switches from live to explore data source", async () => {
    setAccountRuntime({ mode: "live" });

    const { result } = renderHook(() => useModeData("funds"), {
      wrapper: createWrapper(),
    });

    // Wait for API data
    await waitFor(() => {
      const funds = result.current.data as { available_balance: number } | undefined;
      return funds?.available_balance === 50000;
    });

    // Switch to explore through the real mode/account store snapshot.
    setAccountRuntime({ mode: "explore" });

    await waitFor(() => {
      const funds = result.current.data as { availableCash: number };
      return funds.availableCash === 250_000;
    });

    const funds = result.current.data as { availableCash: number };
    expect(funds.availableCash).toBe(250_000); // canonical explore mock value
  });
});
