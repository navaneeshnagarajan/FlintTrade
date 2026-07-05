/**
 * useHoldings tests — mirrors `useFunds.test.ts` plus an explicit check that
 * the `retry: false` override in `useHoldings` short-circuits to error state
 * on the FIRST failed call (the other simple hooks default to 3 retries).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import type { Holding } from "@/types/api";

const mockGetHoldings = vi.fn<() => Promise<Holding[]>>();

vi.mock("@/services/api", () => ({
  getHoldings: () => mockGetHoldings(),
}));

import { useHoldings } from "../useHoldings";

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false },
    },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

function makeHolding(overrides: Partial<Holding> = {}): Holding {
  return {
    symbol: "RELIANCE",
    exchange: "NSE",
    quantity: 10,
    averagePrice: 2900,
    ltp: 2980,
    pnl: 800,
    pnlPercent: 2.76,
    ...overrides,
  };
}

beforeEach(() => vi.clearAllMocks());

describe("useHoldings — URL is called", () => {
  it("calls getHoldings exactly once on mount", async () => {
    mockGetHoldings.mockResolvedValue([makeHolding()]);
    renderHook(() => useHoldings(), { wrapper: createWrapper() });
    await waitFor(() => expect(mockGetHoldings).toHaveBeenCalledTimes(1));
  });

  it("does not call getHoldings when disabled", () => {
    mockGetHoldings.mockResolvedValue([makeHolding()]);
    const { result } = renderHook(() => useHoldings({ enabled: false }), { wrapper: createWrapper() });

    expect(mockGetHoldings).not.toHaveBeenCalled();
    expect(result.current.fetchStatus).toBe("idle");
  });
});

describe("useHoldings — response shape", () => {
  it("exposes a Holding[] array on success", async () => {
    const data: Holding[] = [
      makeHolding({ symbol: "TCS", quantity: 5 }),
      makeHolding({ symbol: "INFY", quantity: 20 }),
    ];
    mockGetHoldings.mockResolvedValue(data);

    const { result } = renderHook(() => useHoldings(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data).toStrictEqual(data);
    expect(result.current.data).toHaveLength(2);
  });
});

describe("useHoldings — retry: false override", () => {
  it("transitions to error state after a SINGLE failure (no retry)", async () => {
    mockGetHoldings.mockRejectedValue(new Error("HTTP 500"));
    const { result } = renderHook(() => useHoldings(), { wrapper: createWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    // Hook override means exactly one call — no automatic retries.
    expect(mockGetHoldings).toHaveBeenCalledTimes(1);
    expect((result.current.error as Error).message).toContain("HTTP 500");
  });
});
