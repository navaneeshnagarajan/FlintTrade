/**
 * useOptionChain.test.ts
 *
 * Dedicated tests for the useOptionChain hook.
 * Verifies enabled/disabled state, data return, and error handling.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockGetOptionChain = vi.fn();

vi.mock("@/services/api", () => ({
  getOptionChain: (symbol: string, exchange: string, expiry?: string) =>
    mockGetOptionChain(symbol, exchange, expiry),
}));

vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children);
}

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { useOptionChain } from "../useOptionChain";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useOptionChain", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("returns data when expiry is selected", async () => {
    const chainData = {
      symbol: "NIFTY",
      expiry: "2026-04-10",
      spotPrice: 23500,
      strikes: [{ strike: 23500, ce_ltp: 150, pe_ltp: 120 }],
    };
    mockGetOptionChain.mockResolvedValue(chainData);

    const { result } = renderHook(
      () => useOptionChain("NIFTY", "NFO", "2026-04-10"),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(chainData);
    expect(mockGetOptionChain).toHaveBeenCalledWith("NIFTY", "NFO", "2026-04-10");
  });

  it("returns empty/idle when no symbol is provided", () => {
    const { result } = renderHook(
      () => useOptionChain(""),
      { wrapper: createWrapper() },
    );

    // enabled: false → query stays idle, never fetches
    expect(result.current.fetchStatus).toBe("idle");
    expect(mockGetOptionChain).not.toHaveBeenCalled();
  });

  it("handles error state", async () => {
    mockGetOptionChain.mockRejectedValue(new Error("Network failure"));

    const { result } = renderHook(
      () => useOptionChain("NIFTY", "NFO", "2026-04-10"),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(Error);
  });
});
