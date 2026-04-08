/**
 * Tests for useDepthData — TanStack Query hook for market depth polling.
 *
 * Verifies that:
 *   1. The query is enabled when symbol is provided and enabled=true
 *   2. The query is disabled when enabled=false (explore mode)
 *   3. The query is disabled when symbol is empty
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ---------------------------------------------------------------------------
// Mock API service
// ---------------------------------------------------------------------------

const mockDepthData = {
  symbol: "NIFTY",
  exchange: "NSE_INDEX",
  bids: [
    { price: 24100, quantity: 500 },
    { price: 24095, quantity: 300 },
  ],
  asks: [
    { price: 24105, quantity: 400 },
    { price: 24110, quantity: 250 },
  ],
};

const getDepthMock = vi.fn(() => Promise.resolve(mockDepthData));

vi.mock("@/services/api", () => ({
  getDepth: (...args: unknown[]) => getDepthMock(...args),
}));

// ---------------------------------------------------------------------------
// Import hook after mocks
// ---------------------------------------------------------------------------

import { useDepthData } from "../useDepthData";

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
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useDepthData", () => {
  it("fetches depth data when enabled with a valid symbol", async () => {
    const { result } = renderHook(
      () => useDepthData("NIFTY", "NSE_INDEX", true),
      { wrapper: createWrapper() },
    );

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(getDepthMock).toHaveBeenCalledWith("NIFTY", "NSE_INDEX");
    expect(result.current.data).toEqual(mockDepthData);
  });

  it("does not fetch when enabled is false (explore mode)", () => {
    const { result } = renderHook(
      () => useDepthData("NIFTY", "NSE_INDEX", false),
      { wrapper: createWrapper() },
    );

    expect(result.current.fetchStatus).toBe("idle");
    expect(getDepthMock).not.toHaveBeenCalled();
  });

  it("does not fetch when symbol is empty", () => {
    const { result } = renderHook(
      () => useDepthData("", "NSE_INDEX", true),
      { wrapper: createWrapper() },
    );

    expect(result.current.fetchStatus).toBe("idle");
    expect(getDepthMock).not.toHaveBeenCalled();
  });
});
