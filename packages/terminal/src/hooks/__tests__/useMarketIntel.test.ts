/**
 * useMarketIntel tests
 *
 * Tests for the 4 market intelligence TanStack Query hooks:
 *   - useGex
 *   - useIVSmile
 *   - useMaxPain
 *   - useOIProfile
 *
 * All follow the same pattern: enabled when symbol+exchange present,
 * disabled otherwise. Market hours mocked to false.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ---------------------------------------------------------------------------
// Mock api service
// ---------------------------------------------------------------------------

const mockGetGex = vi.fn();
const mockGetIVSmile = vi.fn();
const mockGetMaxPain = vi.fn();
const mockGetOIProfile = vi.fn();

vi.mock("@/services/api", () => ({
  getGex: (symbol: string, exchange: string, expiry?: string) =>
    mockGetGex(symbol, exchange, expiry),
  getIVSmile: (symbol: string, exchange: string, expiry?: string) =>
    mockGetIVSmile(symbol, exchange, expiry),
  getMaxPain: (symbol: string, exchange: string, expiry?: string) =>
    mockGetMaxPain(symbol, exchange, expiry),
  getOIProfile: (symbol: string, exchange: string, expiry?: string) =>
    mockGetOIProfile(symbol, exchange, expiry),
}));

vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import { useGex, useIVSmile, useMaxPain, useOIProfile } from "../useMarketIntel";

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

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// useGex
// ---------------------------------------------------------------------------

describe("useGex", () => {
  it("is disabled when symbol is empty", () => {
    const { result } = renderHook(() => useGex("", "NFO"), { wrapper: createWrapper() });
    expect(result.current.fetchStatus).toBe("idle");
    expect(mockGetGex).not.toHaveBeenCalled();
  });

  it("is disabled when exchange is empty", () => {
    const { result } = renderHook(() => useGex("NIFTY", ""), { wrapper: createWrapper() });
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("fetches GEX data when symbol and exchange are provided", async () => {
    const gexData = [{ strike: 23500, gex: 1200000 }];
    mockGetGex.mockResolvedValue(gexData);

    const { result } = renderHook(() => useGex("NIFTY", "NFO", "2026-04-03"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(gexData);
    expect(mockGetGex).toHaveBeenCalledWith("NIFTY", "NFO", "2026-04-03");
  });
});

// ---------------------------------------------------------------------------
// useIVSmile
// ---------------------------------------------------------------------------

describe("useIVSmile", () => {
  it("is disabled when symbol is empty", () => {
    const { result } = renderHook(() => useIVSmile("", "NFO"), { wrapper: createWrapper() });
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("fetches IV smile data on success", async () => {
    const ivData = [{ strike: 23500, iv: 15.2 }];
    mockGetIVSmile.mockResolvedValue(ivData);

    const { result } = renderHook(() => useIVSmile("NIFTY", "NFO"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(ivData);
  });

  it("returns error state on failure", async () => {
    mockGetIVSmile.mockRejectedValue(new Error("IV data unavailable"));

    const { result } = renderHook(() => useIVSmile("NIFTY", "NFO"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

// ---------------------------------------------------------------------------
// useMaxPain
// ---------------------------------------------------------------------------

describe("useMaxPain", () => {
  it("is disabled when symbol is empty", () => {
    const { result } = renderHook(() => useMaxPain("", "NFO"), { wrapper: createWrapper() });
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("fetches max pain data on success", async () => {
    const maxPainData = { max_pain_strike: 23500, pain_by_strike: {} };
    mockGetMaxPain.mockResolvedValue(maxPainData);

    const { result } = renderHook(() => useMaxPain("NIFTY", "NFO"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(maxPainData);
  });
});

// ---------------------------------------------------------------------------
// useOIProfile
// ---------------------------------------------------------------------------

describe("useOIProfile", () => {
  it("is disabled when exchange is empty", () => {
    const { result } = renderHook(() => useOIProfile("NIFTY", ""), { wrapper: createWrapper() });
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("fetches OI profile data on success", async () => {
    const oiData = [{ strike: 23500, ce_oi: 500000, pe_oi: 600000 }];
    mockGetOIProfile.mockResolvedValue(oiData);

    const { result } = renderHook(() => useOIProfile("NIFTY", "NFO"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(oiData);
  });

  it("passes expiry parameter to the API", async () => {
    mockGetOIProfile.mockResolvedValue([]);

    renderHook(() => useOIProfile("NIFTY", "NFO", "2026-04-03"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(mockGetOIProfile).toHaveBeenCalled());
    expect(mockGetOIProfile).toHaveBeenCalledWith("NIFTY", "NFO", "2026-04-03");
  });
});
