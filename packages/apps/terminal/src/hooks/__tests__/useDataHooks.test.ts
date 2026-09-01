/**
 * Tests for TanStack Query data-fetching hooks:
 *   - useFunds
 *   - useHoldings
 *   - useOrders
 *   - usePositions
 *   - useTradebook
 *   - useOptionChain
 *   - useMargin
 *   - useSyntheticFuture
 *
 * Strategy: Mock the api service functions, wrap hooks in QueryClientProvider,
 * and verify loading/success/error states plus query key configuration.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import type { AccountReadContext } from "@/hooks/useAccountReadsEnabled";

const mockAccountReadContext = vi.hoisted(() => Object.freeze({
  identity: Object.freeze({
    mode: "live" as const,
    scopeKey: "live:native:dhan:A1",
    brokerType: "dhan",
    accountId: "A1",
  }),
  enabled: true,
  host: "",
  apiKey: "",
}));

// ---------------------------------------------------------------------------
// Mock api service
// ---------------------------------------------------------------------------

const mockGetFunds = vi.fn();
const mockGetHoldings = vi.fn();
const mockGetOrderbook = vi.fn();
const mockGetPositionbook = vi.fn();
const mockGetTradebook = vi.fn();
const mockGetOptionChain = vi.fn();
const mockGetMargin = vi.fn();
const mockGetSyntheticFuture = vi.fn();
const mockDataScope = vi.hoisted(() => ({ value: "live:native:dhan:A1" }));

vi.mock("@/services/api", () => ({
  getFunds: (context: AccountReadContext, signal?: AbortSignal) =>
    mockGetFunds(context, signal),
  getHoldings: (context: AccountReadContext, signal?: AbortSignal) =>
    mockGetHoldings(context, signal),
  getOrderbook: (context: AccountReadContext, signal?: AbortSignal) =>
    mockGetOrderbook(context, signal),
  getPositionbook: (context: AccountReadContext, signal?: AbortSignal) =>
    mockGetPositionbook(context, signal),
  getTradebook: (context: AccountReadContext, signal?: AbortSignal) =>
    mockGetTradebook(context, signal),
  getOptionChain: (symbol: string, exchange: string, expiry?: string) =>
    mockGetOptionChain(symbol, exchange, expiry),
  getMargin: (
    context: AccountReadContext,
    symbol: string,
    exchange: string,
    qty: number,
    product: string,
    action: string,
    signal?: AbortSignal,
  ) => mockGetMargin(context, symbol, exchange, qty, product, action, signal),
  getSyntheticFuture: (
    symbol: string,
    exchange: string,
    expiry?: string,
    signal?: AbortSignal,
    expectedDataScope?: string,
  ) => mockGetSyntheticFuture(symbol, exchange, expiry, signal, expectedDataScope),
}));

vi.mock("@/hooks/useAccountReadsEnabled", () => ({
  useAccountReadsEnabled: () => true,
  useAccountReadContext: () => mockAccountReadContext,
}));

vi.mock("@/hooks/useDataScope", () => ({
  useDataScope: () => mockDataScope.value,
  useMarketDataScope: () => mockDataScope.value,
}));

// Mock market hours (default: market closed so refetchInterval doesn't interfere)
vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

// Mock tradingStore (useFunds and usePositions sync to it)
const mockUpdateFromFunds = vi.fn();
const mockUpdateFromPositions = vi.fn();

vi.mock("@/stores/tradingStore", () => ({
  useTradingStore: {
    getState: () => ({
      updateFromFunds: mockUpdateFromFunds,
      updateFromPositions: mockUpdateFromPositions,
    }),
  },
}));

// ---------------------------------------------------------------------------
// Import hooks after mocks
// ---------------------------------------------------------------------------

import { useFunds } from "../useFunds";
import { useHoldings } from "../useHoldings";
import { useOrders } from "../useOrders";
import { usePositions } from "../usePositions";
import { useTradebook } from "../useTradebook";
import { useOptionChain } from "../useOptionChain";
import { useMargin } from "../useMargin";
import { useSyntheticFuture } from "../useSyntheticFuture";

// ---------------------------------------------------------------------------
// Test wrapper
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
  mockDataScope.value = "live:native:dhan:A1";
});

// ---------------------------------------------------------------------------
// useFunds
// ---------------------------------------------------------------------------

describe("useFunds", () => {
  it("returns loading state initially", () => {
    mockGetFunds.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useFunds(), { wrapper: createWrapper() });
    expect(result.current.isLoading).toBe(true);
  });

  it("returns funds data on success", async () => {
    const fundsData = {
      available_balance: 50000,
      utilized_margin: 10000,
      total_balance: 60000,
    };
    mockGetFunds.mockResolvedValue(fundsData);

    const { result } = renderHook(() => useFunds(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(fundsData);
    expect(mockGetFunds).toHaveBeenCalledWith(
      mockAccountReadContext,
      expect.any(AbortSignal),
    );
  });

  it("returns error state on failure", async () => {
    mockGetFunds.mockRejectedValue(new Error("Funds fetch failed"));
    const { result } = renderHook(() => useFunds(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

// ---------------------------------------------------------------------------
// useHoldings
// ---------------------------------------------------------------------------

describe("useHoldings", () => {
  it("returns loading state initially", () => {
    mockGetHoldings.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useHoldings(), { wrapper: createWrapper() });
    expect(result.current.isLoading).toBe(true);
  });

  it("returns holdings array on success", async () => {
    const holdings = [
      { symbol: "RELIANCE", exchange: "NSE", quantity: 10, avg_price: 2500, ltp: 2600 },
    ];
    mockGetHoldings.mockResolvedValue(holdings);

    const { result } = renderHook(() => useHoldings(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data![0].symbol).toBe("RELIANCE");
    expect(mockGetHoldings).toHaveBeenCalledWith(
      mockAccountReadContext,
      expect.any(AbortSignal),
    );
  });

  it("returns error state on failure (retry disabled)", async () => {
    mockGetHoldings.mockRejectedValue(new Error("Holdings fetch failed"));
    const { result } = renderHook(() => useHoldings(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

// ---------------------------------------------------------------------------
// useOrders
// ---------------------------------------------------------------------------

describe("useOrders", () => {
  it("returns loading state initially", () => {
    mockGetOrderbook.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useOrders(), { wrapper: createWrapper() });
    expect(result.current.isLoading).toBe(true);
  });

  it("returns orders array on success", async () => {
    const orders = [
      { order_id: "ORD001", symbol: "NIFTY", status: "open", side: "BUY" },
    ];
    mockGetOrderbook.mockResolvedValue(orders);

    const { result } = renderHook(() => useOrders(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(mockGetOrderbook).toHaveBeenCalledWith(
      mockAccountReadContext,
      expect.any(AbortSignal),
    );
  });

  it("returns error state on failure", async () => {
    mockGetOrderbook.mockRejectedValue(new Error("Orderbook error"));
    const { result } = renderHook(() => useOrders(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

// ---------------------------------------------------------------------------
// usePositions
// ---------------------------------------------------------------------------

describe("usePositions", () => {
  it("returns loading state initially", () => {
    mockGetPositionbook.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => usePositions(), { wrapper: createWrapper() });
    expect(result.current.isLoading).toBe(true);
  });

  it("returns positions array on success", async () => {
    const positions = [
      { symbol: "NIFTY", exchange: "NFO", quantity: 50, pnl: 1200 },
    ];
    mockGetPositionbook.mockResolvedValue(positions);

    const { result } = renderHook(() => usePositions(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(mockGetPositionbook).toHaveBeenCalledWith(
      mockAccountReadContext,
      expect.any(AbortSignal),
    );
  });
});

// ---------------------------------------------------------------------------
// useTradebook
// ---------------------------------------------------------------------------

describe("useTradebook", () => {
  it("returns loading state initially", () => {
    mockGetTradebook.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useTradebook(), { wrapper: createWrapper() });
    expect(result.current.isLoading).toBe(true);
  });

  it("returns trades array on success", async () => {
    const trades = [
      { trade_id: "T001", symbol: "RELIANCE", side: "BUY", quantity: 10, price: 2500 },
    ];
    mockGetTradebook.mockResolvedValue(trades);

    const { result } = renderHook(() => useTradebook(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(mockGetTradebook).toHaveBeenCalledWith(
      mockAccountReadContext,
      expect.any(AbortSignal),
    );
  });

  it("returns error state on failure", async () => {
    mockGetTradebook.mockRejectedValue(new Error("Tradebook error"));
    const { result } = renderHook(() => useTradebook(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

// ---------------------------------------------------------------------------
// useOptionChain
// ---------------------------------------------------------------------------

describe("useOptionChain", () => {
  it("is disabled when symbol is empty", () => {
    const { result } = renderHook(() => useOptionChain(""), { wrapper: createWrapper() });
    // When enabled is false, query stays in pending status and never fetches
    expect(result.current.fetchStatus).toBe("idle");
    expect(mockGetOptionChain).not.toHaveBeenCalled();
  });

  it("fetches option chain when symbol is provided", async () => {
    const chainData = {
      symbol: "NIFTY",
      expiry: "2026-04-03",
      strikes: [{ strike: 23500, ce_ltp: 150, pe_ltp: 120 }],
    };
    mockGetOptionChain.mockResolvedValue(chainData);

    const { result } = renderHook(() => useOptionChain("NIFTY", "NFO", "2026-04-03"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(chainData);
    expect(mockGetOptionChain).toHaveBeenCalledWith("NIFTY", "NFO", "2026-04-03");
  });

  it("defaults exchange to NFO when not provided", async () => {
    mockGetOptionChain.mockResolvedValue({ symbol: "NIFTY", strikes: [] });

    renderHook(() => useOptionChain("NIFTY", undefined, "26-MAR-26"), { wrapper: createWrapper() });

    await waitFor(() => expect(mockGetOptionChain).toHaveBeenCalled());
    expect(mockGetOptionChain).toHaveBeenCalledWith("NIFTY", "NFO", "26-MAR-26");
  });

  it("stays idle when expiry is omitted", () => {
    const { result } = renderHook(() => useOptionChain("NIFTY"), { wrapper: createWrapper() });

    expect(result.current.fetchStatus).toBe("idle");
    expect(mockGetOptionChain).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// useMargin
// ---------------------------------------------------------------------------

describe("useMargin", () => {
  it("is disabled when symbol is empty", () => {
    const { result } = renderHook(
      () => useMargin("", "NSE", 10, "MIS", "BUY"),
      { wrapper: createWrapper() },
    );
    expect(result.current.fetchStatus).toBe("idle");
    expect(mockGetMargin).not.toHaveBeenCalled();
  });

  it("is disabled when qty is 0", () => {
    const { result } = renderHook(
      () => useMargin("NIFTY", "NFO", 0, "MIS", "BUY"),
      { wrapper: createWrapper() },
    );
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("is disabled when enabled param is false", () => {
    const { result } = renderHook(
      () => useMargin("NIFTY", "NFO", 50, "MIS", "BUY", false),
      { wrapper: createWrapper() },
    );
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("fetches margin when all params are valid", async () => {
    const marginData = { required_margin: 25000, available_margin: 50000 };
    mockGetMargin.mockResolvedValue(marginData);

    const { result } = renderHook(
      () => useMargin("NIFTY", "NFO", 50, "MIS", "BUY"),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(marginData);
    expect(mockGetMargin).toHaveBeenCalledWith(
      mockAccountReadContext,
      "NIFTY",
      "NFO",
      50,
      "MIS",
      "BUY",
      expect.any(AbortSignal),
    );
  });
});

// ---------------------------------------------------------------------------
// useSyntheticFuture
// ---------------------------------------------------------------------------

describe("useSyntheticFuture", () => {
  it("is disabled when symbol is empty", () => {
    const { result } = renderHook(
      () => useSyntheticFuture("", "NFO"),
      { wrapper: createWrapper() },
    );
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("is disabled when exchange is empty", () => {
    const { result } = renderHook(
      () => useSyntheticFuture("NIFTY", ""),
      { wrapper: createWrapper() },
    );
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("fetches synthetic future when symbol and exchange are provided", async () => {
    const futureData = { synthetic_price: 23520.5, basis: 20.5, annualized_basis: 3.2 };
    mockGetSyntheticFuture.mockResolvedValue(futureData);

    const { result } = renderHook(
      () => useSyntheticFuture("NIFTY", "NFO", "2026-04-03"),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(futureData);
    expect(mockGetSyntheticFuture).toHaveBeenCalledWith(
      "NIFTY",
      "NFO",
      "2026-04-03",
      expect.any(AbortSignal),
      mockDataScope.value,
    );
  });

  it("does not retain a Live synthetic future after switching to Explore", async () => {
    const futureData = { synthetic_price: 23520.5, basis: 20.5, annualized_basis: 3.2 };
    mockGetSyntheticFuture.mockResolvedValue(futureData);
    const { result, rerender } = renderHook(
      () => useSyntheticFuture("NIFTY", "NFO", "2026-04-03"),
      { wrapper: createWrapper() },
    );
    await waitFor(() => expect(result.current.data).toEqual(futureData));

    mockDataScope.value = "explore:mock";
    rerender();

    await waitFor(() => expect(result.current.fetchStatus).toBe("idle"));
    expect(result.current.data).toBeUndefined();
    expect(mockGetSyntheticFuture).toHaveBeenCalledTimes(1);
  });

  it("aborts an in-flight Live synthetic future when Explore retires its authority", async () => {
    let resolveLive!: (value: { synthetic_price: number }) => void;
    let liveSignal: AbortSignal | undefined;
    mockGetSyntheticFuture.mockImplementation(
      (
        _symbol: string,
        _exchange: string,
        _expiry: string,
        signal?: AbortSignal,
        expectedDataScope?: string,
      ) => {
        expect(expectedDataScope).toBe("live:native:dhan:A1");
        liveSignal = signal;
        return new Promise((resolve) => {
          resolveLive = resolve;
        });
      },
    );
    const { result, rerender } = renderHook(
      () => useSyntheticFuture("NIFTY", "NFO", "2026-04-03"),
      { wrapper: createWrapper() },
    );
    await waitFor(() => expect(result.current.fetchStatus).toBe("fetching"));

    mockDataScope.value = "explore:mock";
    rerender();

    expect(liveSignal).toBeInstanceOf(AbortSignal);
    expect(liveSignal?.aborted).toBe(true);
    resolveLive({ synthetic_price: 23520.5 });
    await waitFor(() => expect(result.current.fetchStatus).toBe("idle"));
    expect(result.current.data).toBeUndefined();
  });
});
