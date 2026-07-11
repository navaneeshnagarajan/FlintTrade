/**
 * useOrderFlow tests
 *
 * Tests the TanStack Query hook for fetching order flow footprint data.
 * The hook now delegates to getOrderFlow() from ftApi.data which uses
 * ftApi.helpers.get(). We mock the global fetch and verify that the
 * correct URL is called and that data / errors flow correctly.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import type { OrderFlowData } from "../useOrderFlow";

// ---------------------------------------------------------------------------
// Mock fetch
// ---------------------------------------------------------------------------

const mockFetch = vi.fn();
type MarketHoursTarget = string | { exchange: string; symbol: string };
const mockIsMarketHours = vi.hoisted(
  () => vi.fn<(target?: MarketHoursTarget) => boolean>(() => false),
);

vi.mock("@/lib/market", () => ({
  isMarketHours: (target?: MarketHoursTarget) => mockIsMarketHours(target),
}));

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch);
  mockIsMarketHours.mockReset().mockReturnValue(false);
});

afterEach(() => {
  vi.useRealTimers();
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
      exchange: "NFO",
      interval: 300,
      is_live: false,
    };

    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ status: "success", data: mockData }),
    });

    const { result } = renderHook(() => useOrderFlow("NIFTY"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockData);
  });

  it("uses default exchange NFO, interval 300, and bins 50", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          status: "success",
          data: {
            buckets: [],
            symbol: "NIFTY",
            exchange: "NFO",
            interval: 300,
            is_live: false,
          },
        }),
    });

    renderHook(() => useOrderFlow("NIFTY"), { wrapper: createWrapper() });

    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("symbol=NIFTY");
    expect(url).toContain("exchange=NFO");
    expect(url).toContain("interval=300");
    expect(url).toContain("bins=50");
  });

  it("uses provided exchange and interval when overridden", async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          status: "success",
          data: {
            buckets: [],
            symbol: "BANKNIFTY",
            exchange: "NSE",
            interval: 60,
            is_live: false,
          },
        }),
    });

    renderHook(() => useOrderFlow("BANKNIFTY", "NSE", 60, 20), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    const url = mockFetch.mock.calls[0][0] as string;
    expect(url).toContain("symbol=BANKNIFTY");
    expect(url).toContain("exchange=NSE");
    expect(url).toContain("interval=60");
    expect(url).toContain("bins=20");
  });

  it.each([
    ["MCX", "GOLD"],
    ["CDS", "USDINR"],
    ["CDS", "EURUSD29JUL26FUT"],
  ])(
    "re-evaluates %s:%s polling from 60s when closed to 5s while open",
    async (exchange, symbol) => {
      vi.useFakeTimers();
      let isOpen = false;
      mockIsMarketHours.mockImplementation(
        (candidate) => (
          typeof candidate === "object"
          && candidate.exchange === exchange
          && candidate.symbol === symbol
          && isOpen
        ),
      );
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({
          status: "success",
          data: {
            buckets: [],
            symbol,
            exchange,
            interval: 300,
            is_live: true,
          },
        }),
      });

      renderHook(
        () => useOrderFlow(symbol, exchange),
        { wrapper: createWrapper() },
      );
      await vi.waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
      expect(mockIsMarketHours).toHaveBeenCalledWith({ exchange, symbol });

      mockFetch.mockClear();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });
      expect(mockFetch).not.toHaveBeenCalled();

      isOpen = true;
      await act(async () => {
        await vi.advanceTimersByTimeAsync(55_000);
      });
      expect(mockFetch).toHaveBeenCalledTimes(1);

      mockFetch.mockClear();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });
      expect(mockFetch).toHaveBeenCalledTimes(1);
    },
  );

  it("throws the backend's message on HTTP error", async () => {
    // ftApi.helpers now extracts the backend's {message} body on !ok (the
    // generic "HTTP <status>" remains only the no-JSON-body fallback).
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

  it("falls back to the status code when the error body is not JSON", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 500,
      json: () => Promise.reject(new Error("not json")),
    });

    const { result } = renderHook(() => useOrderFlow("NIFTY"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toContain("HTTP 500");
  });

  it("throws on API error status in JSON body", async () => {
    // parseResponse in ftApi.helpers.ts throws when status === "error"
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ status: "error", message: "No data available" }),
    });

    const { result } = renderHook(() => useOrderFlow("NIFTY"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toContain("No data available");
  });
});
