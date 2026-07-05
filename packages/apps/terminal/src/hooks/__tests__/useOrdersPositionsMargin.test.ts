/**
 * Tests for the three remaining REST-query hooks not covered elsewhere:
 *
 *   - useOrders    → getOrderbook
 *   - usePositions → getPositionbook
 *   - useMargin    → getMargin (with the conditional ``enabled`` gate)
 *
 * Same pattern as useFunds.test.ts — mock the @/services/api module,
 * wrap renderHook in QueryClientProvider with retry: false + gcTime: 0,
 * and mock isMarketHours so refetchInterval is deterministic.
 *
 * useMargin's conditional gate (``enabled && !!symbol && !!exchange &&
 * qty > 0``) is the load-bearing logic — most calls in the OrderPad
 * flow miss the gate by design and must NOT fire a fetch. The four
 * branches below lock that contract.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import type { Order, Position, MarginData } from "@/types/api";

// ---------------------------------------------------------------------------
// Mocks — declared BEFORE the hook imports so vi.mock hoisting applies.
// ---------------------------------------------------------------------------

const mockGetOrderbook = vi.fn<() => Promise<Order[]>>();
const mockGetPositionbook = vi.fn<() => Promise<Position[]>>();
const mockGetMargin = vi.fn<
  (sym: string, exch: string, qty: number, prod: string, act: string) => Promise<MarginData>
>();

vi.mock("@/services/api", () => ({
  getOrderbook: () => mockGetOrderbook(),
  getPositionbook: () => mockGetPositionbook(),
  getMargin: (...args: [string, string, number, string, string]) => mockGetMargin(...args),
}));

// isMarketHours drives refetchInterval. Pinning it makes test timing
// deterministic regardless of when the suite runs.
vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

import { useOrders } from "../useOrders";
import { usePositions } from "../usePositions";
import { useMargin } from "../useMargin";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
        refetchOnWindowFocus: false,
      },
    },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// useOrders
// ---------------------------------------------------------------------------

describe("useOrders", () => {
  it("calls getOrderbook exactly once on mount", async () => {
    mockGetOrderbook.mockResolvedValue([]);

    renderHook(() => useOrders(), { wrapper: createWrapper() });

    await waitFor(() => expect(mockGetOrderbook).toHaveBeenCalledTimes(1));
  });

  it("does not call getOrderbook when disabled", () => {
    mockGetOrderbook.mockResolvedValue([]);

    const { result } = renderHook(() => useOrders({ enabled: false }), { wrapper: createWrapper() });

    expect(mockGetOrderbook).not.toHaveBeenCalled();
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("exposes the array unwrapped", async () => {
    const orders = [
      { order_id: "OID1", symbol: "NIFTY", status: "OPEN" } as unknown as Order,
    ];
    mockGetOrderbook.mockResolvedValue(orders);

    const { result } = renderHook(() => useOrders(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toStrictEqual(orders);
  });

  it("transitions to error state when the query fails", async () => {
    mockGetOrderbook.mockRejectedValue(new Error("Order book unreachable"));

    const { result } = renderHook(() => useOrders(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect((result.current.error as Error).message).toContain("unreachable");
  });
});

// ---------------------------------------------------------------------------
// usePositions
// ---------------------------------------------------------------------------

describe("usePositions", () => {
  it("calls getPositionbook exactly once on mount", async () => {
    mockGetPositionbook.mockResolvedValue([]);

    renderHook(() => usePositions(), { wrapper: createWrapper() });

    await waitFor(() => expect(mockGetPositionbook).toHaveBeenCalledTimes(1));
  });

  it("does not call getPositionbook when disabled", () => {
    mockGetPositionbook.mockResolvedValue([]);

    const { result } = renderHook(() => usePositions({ enabled: false }), { wrapper: createWrapper() });

    expect(mockGetPositionbook).not.toHaveBeenCalled();
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("exposes the array unwrapped", async () => {
    const positions = [
      { symbol: "NIFTY", net_qty: 50, ltp: 24850 } as unknown as Position,
    ];
    mockGetPositionbook.mockResolvedValue(positions);

    const { result } = renderHook(() => usePositions(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toStrictEqual(positions);
  });

  it("starts in loading state before the query resolves", () => {
    mockGetPositionbook.mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => usePositions(), { wrapper: createWrapper() });

    expect(result.current.isLoading).toBe(true);
    expect(result.current.data).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// useMargin — conditional ``enabled`` gate
// ---------------------------------------------------------------------------

describe("useMargin — enabled gate", () => {
  function makeMargin(overrides: Partial<MarginData> = {}): MarginData {
    return {
      total_margin_required: 18000,
      span_margin: 14000,
      exposure_margin: 4000,
      ...overrides,
    };
  }

  it("fires the fetch when all inputs are valid", async () => {
    mockGetMargin.mockResolvedValue(makeMargin());

    renderHook(
      () => useMargin("NIFTY", "NFO", 50, "MIS", "BUY"),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(mockGetMargin).toHaveBeenCalledTimes(1));
    expect(mockGetMargin).toHaveBeenCalledWith("NIFTY", "NFO", 50, "MIS", "BUY");
  });

  it("does NOT fire when symbol is empty", () => {
    renderHook(
      () => useMargin("", "NFO", 50, "MIS", "BUY"),
      { wrapper: createWrapper() },
    );
    expect(mockGetMargin).not.toHaveBeenCalled();
  });

  it("does NOT fire when exchange is empty", () => {
    renderHook(
      () => useMargin("NIFTY", "", 50, "MIS", "BUY"),
      { wrapper: createWrapper() },
    );
    expect(mockGetMargin).not.toHaveBeenCalled();
  });

  it("does NOT fire when qty <= 0", () => {
    renderHook(
      () => useMargin("NIFTY", "NFO", 0, "MIS", "BUY"),
      { wrapper: createWrapper() },
    );
    expect(mockGetMargin).not.toHaveBeenCalled();
  });

  it("does NOT fire when caller passes enabled=false", () => {
    renderHook(
      () => useMargin("NIFTY", "NFO", 50, "MIS", "BUY", /* enabled */ false),
      { wrapper: createWrapper() },
    );
    expect(mockGetMargin).not.toHaveBeenCalled();
  });

  it("exposes margin data unwrapped on success", async () => {
    const margin = makeMargin({ total_margin_required: 22500, span_margin: 17000, exposure_margin: 5500 });
    mockGetMargin.mockResolvedValue(margin);

    const { result } = renderHook(
      () => useMargin("NIFTY", "NFO", 75, "NRML", "SELL"),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toStrictEqual(margin);
  });
});
