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
import { useModeStore } from "@/stores/modeStore";

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
  useModeStore.setState({ mode: "live" });
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

  it("returns sample GEX data in explore mode without calling the API", async () => {
    useModeStore.setState({ mode: "explore" });

    const { result } = renderHook(() => useGex("NIFTY", "NFO"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.length).toBeGreaterThan(0);
    expect(result.current.data?.[0]).toHaveProperty("net_gamma");
    expect(mockGetGex).not.toHaveBeenCalled();
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

  it("returns sample IV Smile data in explore mode without calling the API", async () => {
    useModeStore.setState({ mode: "explore" });

    const { result } = renderHook(() => useIVSmile("NIFTY", "NFO"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.length).toBeGreaterThan(0);
    expect(result.current.data?.[0]).toHaveProperty("call_iv");
    expect(mockGetIVSmile).not.toHaveBeenCalled();
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

  it("returns sample max pain data in explore mode without calling the API", async () => {
    useModeStore.setState({ mode: "explore" });

    const { result } = renderHook(() => useMaxPain("NIFTY", "NFO"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.strikes.length).toBeGreaterThan(0);
    expect(result.current.data?.max_pain_strike).toBeGreaterThan(0);
    expect(mockGetMaxPain).not.toHaveBeenCalled();
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

  it("returns sample OI profile data in explore mode without calling the API", async () => {
    useModeStore.setState({ mode: "explore" });

    const { result } = renderHook(() => useOIProfile("NIFTY", "NFO"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.length).toBeGreaterThan(0);
    expect(result.current.data?.[0]).toHaveProperty("type");
    expect(mockGetOIProfile).not.toHaveBeenCalled();
  });
});
