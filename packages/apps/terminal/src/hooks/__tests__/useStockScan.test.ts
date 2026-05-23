/**
 * useStockScan tests
 *
 * Tests the TanStack Query hook for the stock screener endpoint.
 * The fetch helper is internal to the module, so we mock the global fetch.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ---------------------------------------------------------------------------
// Mock fetch and import.meta.env
// ---------------------------------------------------------------------------

const mockFetch = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { useStockScan } from "../useStockScan";
import type { StockFundamentals } from "../useStockScan";

// ---------------------------------------------------------------------------
// Wrapper
// ---------------------------------------------------------------------------

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, retryDelay: 0 } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useStockScan", () => {
  it("fetches stock scan with default params", async () => {
    const mockStocks: StockFundamentals[] = [
      {
        symbol: "RELIANCE",
        name: "Reliance Industries",
        exchange: "NSE",
        market_cap: 1800000,
        pe_ratio: 28.5,
        pb_ratio: 2.1,
        roe: 12.3,
        roce: 14.5,
        dividend_yield: 0.5,
        sector: "Energy",
      },
    ];

    mockFetch.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          status: "success",
          data: { stocks: mockStocks, sectors: ["Energy", "IT"], count: 1 },
        }),
    });

    const { result } = renderHook(() => useStockScan(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.stocks).toHaveLength(1);
    expect(result.current.data?.stocks[0].symbol).toBe("RELIANCE");
    expect(result.current.data?.sectors).toContain("Energy");
  });

  it("passes filter params as query string", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          status: "success",
          data: { stocks: [], sectors: [], count: 0 },
        }),
    });

    renderHook(
      () =>
        useStockScan({
          sector: "IT",
          min_market_cap: 100000,
          max_pe: 30,
          sort_by: "market_cap",
          limit: 50,
        }),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("sector=IT");
    expect(url).toContain("min_market_cap=100000");
    expect(url).toContain("max_pe=30");
    expect(url).toContain("sort_by=market_cap");
    expect(url).toContain("limit=50");
  });

  it("throws on HTTP error", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 502,
      json: () => Promise.resolve({}),
    });

    // useStockScan has retry: 1 internally, so use a longer wait
    const { result } = renderHook(() => useStockScan(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true), { timeout: 5000 });
    expect(result.current.error?.message).toContain("502");
  });

  it("throws on API error status", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ status: "error", data: { stocks: [], sectors: [], count: 0 } }),
    });

    const { result } = renderHook(() => useStockScan(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true), { timeout: 5000 });
  });
});
