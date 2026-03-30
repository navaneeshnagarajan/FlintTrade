/**
 * useOrderFlow tests
 *
 * Tests the TanStack Query hook for fetching order flow footprint data.
 * The fetch helper is internal to the module, so we mock the global fetch.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import type { OrderFlowData } from "../useOrderFlow";

// ---------------------------------------------------------------------------
// Mock fetch
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

import { useOrderFlow } from "../useOrderFlow";

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
// Tests
// ---------------------------------------------------------------------------

describe("useOrderFlow", () => {
  it("is disabled when symbol is empty", () => {
    const { result } = renderHook(() => useOrderFlow(""), { wrapper: createWrapper() });
    expect(result.current.fetchStatus).toBe("idle");
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("fetches order flow data when symbol is provided", async () => {
    const mockData: OrderFlowData = {
      buckets: [
        {
          time_label: "10:00",
          cells: { "23500": { buy_volume: 100, sell_volume: 80 } },
          poc_price: 23500,
          total_volume: 180,
          delta: 20,
        },
      ],
      symbol: "NIFTY",
      interval: 60,
    };

    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ status: "success", data: mockData }),
    });

    const { result } = renderHook(() => useOrderFlow("NIFTY", "NSE", 60), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockData);
  });

  it("uses default exchange NSE and interval 60", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ status: "success", data: { buckets: [], symbol: "NIFTY", interval: 60 } }),
    });

    renderHook(() => useOrderFlow("NIFTY"), { wrapper: createWrapper() });

    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("symbol=NIFTY");
    expect(url).toContain("exchange=NSE");
    expect(url).toContain("interval=60");
  });

  it("throws on HTTP error", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 500,
      json: () => Promise.resolve({ message: "Internal error" }),
    });

    const { result } = renderHook(() => useOrderFlow("NIFTY"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toContain("Internal error");
  });

  it("throws on API error status", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ status: "error", message: "No data" }),
    });

    const { result } = renderHook(() => useOrderFlow("NIFTY"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toContain("No data");
  });
});
