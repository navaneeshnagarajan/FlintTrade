/**
 * useMarketIntel tests
 *
 * Tests for the 4 market intelligence TanStack Query hooks:
 *   - useGex
 *   - useIVSmile
 *   - useMaxPain
 *   - useOIProfile
 *
 * GEX and OI Profile also require a selected expiry. Market hours are mocked
 * to false.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ---------------------------------------------------------------------------
// Mock api service
// ---------------------------------------------------------------------------

const mockGetGex = vi.fn();
const mockGetIVSmile = vi.fn();
const mockGetMaxPain = vi.fn();
const mockGetOIProfile = vi.fn();
const marketMocks = vi.hoisted(() => ({
  isMarketHours: vi.fn(),
}));

vi.mock("@/services/api", () => ({
  getGex: (symbol: string, exchange: string, expiry?: string, signal?: AbortSignal) =>
    mockGetGex(symbol, exchange, expiry, signal),
  getIVSmile: (symbol: string, exchange: string, expiry?: string, signal?: AbortSignal) =>
    mockGetIVSmile(symbol, exchange, expiry, signal),
  getMaxPain: (symbol: string, exchange: string, expiry?: string, signal?: AbortSignal) =>
    mockGetMaxPain(symbol, exchange, expiry, signal),
  getOIProfile: (symbol: string, exchange: string, expiry?: string, signal?: AbortSignal) =>
    mockGetOIProfile(symbol, exchange, expiry, signal),
}));

vi.mock("@/lib/market", () => ({
  isMarketHours: marketMocks.isMarketHours,
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
  marketMocks.isMarketHours.mockReturnValue(false);
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

  it.each([undefined, "", "   "])("is disabled until a valid expiry exists (%s)", (expiry) => {
    const { result } = renderHook(() => useGex("NIFTY", "NFO", expiry), { wrapper: createWrapper() });
    expect(result.current.fetchStatus).toBe("idle");
    expect(result.current.data).toBeUndefined();
    expect(mockGetGex).not.toHaveBeenCalled();
  });

  it("fetches GEX data when symbol and exchange are provided", async () => {
    const gexData = {
      is_sample_data: false,
      rows: [{ strike: 23500, gex: 1200000 }],
    };
    mockGetGex.mockResolvedValue(gexData);

    const { result } = renderHook(() => useGex("NIFTY", "NFO", "2026-04-03"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(gexData);
    expect(mockGetGex).toHaveBeenCalledWith(
      "NIFTY",
      "NFO",
      "2026-04-03",
      expect.any(AbortSignal),
    );
  });

  it("returns sample GEX data in explore mode without calling the API", async () => {
    useModeStore.setState({ mode: "explore" });

    const { result } = renderHook(() => useGex("NIFTY", "NFO", "2026-04-03"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.is_sample_data).toBe(true);
    expect(result.current.data?.rows.length).toBeGreaterThan(0);
    expect(result.current.data?.rows[0]).toHaveProperty("net_gex");
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

  it.each([undefined, "", "   "])("is disabled until a valid expiry exists (%s)", (expiry) => {
    const { result } = renderHook(() => useIVSmile("NIFTY", "NFO", expiry), {
      wrapper: createWrapper(),
    });
    expect(result.current.fetchStatus).toBe("idle");
    expect(result.current.data).toBeUndefined();
    expect(mockGetIVSmile).not.toHaveBeenCalled();
  });

  it("fetches IV smile data on success with a trimmed expiry", async () => {
    const ivData = {
      is_sample_data: false,
      points: [{ strike: 23500, call_iv: 0.152, put_iv: 0.155, moneyness: 1 }],
    };
    mockGetIVSmile.mockResolvedValue(ivData);

    const { result } = renderHook(() => useIVSmile("NIFTY", "NFO", " 2026-04-03 "), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(ivData);
    expect(mockGetIVSmile).toHaveBeenCalledWith(
      "NIFTY",
      "NFO",
      "2026-04-03",
      expect.any(AbortSignal),
    );
  });

  it("returns error state on failure", async () => {
    mockGetIVSmile.mockRejectedValue(new Error("IV data unavailable"));

    const { result } = renderHook(() => useIVSmile("NIFTY", "NFO", "2026-04-03"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });

  it("returns sample IV Smile data in explore mode without calling the API", async () => {
    useModeStore.setState({ mode: "explore" });

    const { result } = renderHook(() => useIVSmile("NIFTY", "NFO", "2026-04-03"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.is_sample_data).toBe(true);
    expect(result.current.data?.points.length).toBeGreaterThan(0);
    expect(result.current.data?.points[0]).toHaveProperty("call_iv");
    expect(result.current.data?.points.find((point) => point.strike === 23500)?.moneyness).toBe(1);
    expect(result.current.data?.points[0]?.call_iv).toBeLessThan(1);
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

  it.each([undefined, "", "   "])("is disabled until a valid expiry exists (%s)", (expiry) => {
    const { result } = renderHook(() => useMaxPain("NIFTY", "NFO", expiry), {
      wrapper: createWrapper(),
    });
    expect(result.current.fetchStatus).toBe("idle");
    expect(result.current.data).toBeUndefined();
    expect(mockGetMaxPain).not.toHaveBeenCalled();
  });

  it("fetches max pain data on success with a trimmed expiry", async () => {
    const maxPainData = { max_pain_strike: 23500, pain_by_strike: {} };
    mockGetMaxPain.mockResolvedValue(maxPainData);

    const { result } = renderHook(() => useMaxPain("NIFTY", "NFO", " 2026-04-03 "), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(maxPainData);
    expect(mockGetMaxPain).toHaveBeenCalledWith(
      "NIFTY",
      "NFO",
      "2026-04-03",
      expect.any(AbortSignal),
    );
  });

  it("polls Max Pain no faster than every 60 seconds", async () => {
    vi.useFakeTimers();
    try {
      marketMocks.isMarketHours.mockReturnValue(true);
      mockGetMaxPain.mockResolvedValue({ max_pain_strike: 23500, strikes: [] });

      renderHook(() => useMaxPain("NIFTY", "NFO", "2026-04-03"), {
        wrapper: createWrapper(),
      });
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      expect(mockGetMaxPain).toHaveBeenCalledTimes(1);

      await act(async () => { await vi.advanceTimersByTimeAsync(59_999); });
      expect(mockGetMaxPain).toHaveBeenCalledTimes(1);

      await act(async () => { await vi.advanceTimersByTimeAsync(1); });
      expect(mockGetMaxPain).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("returns sample max pain data in explore mode without calling the API", async () => {
    useModeStore.setState({ mode: "explore" });

    const { result } = renderHook(() => useMaxPain("NIFTY", "NFO", "2026-04-03"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.is_sample_data).toBe(true);
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

  it.each([undefined, "", "   "])("is disabled until a valid expiry exists (%s)", (expiry) => {
    const { result } = renderHook(() => useOIProfile("NIFTY", "NFO", expiry), {
      wrapper: createWrapper(),
    });
    expect(result.current.fetchStatus).toBe("idle");
    expect(result.current.data).toBeUndefined();
    expect(mockGetOIProfile).not.toHaveBeenCalled();
  });

  it("fetches OI profile data on success", async () => {
    const oiData = {
      is_sample_data: false,
      rows: [{ strike: 23500, ce_oi: 500000, pe_oi: 600000 }],
    };
    mockGetOIProfile.mockResolvedValue(oiData);

    const { result } = renderHook(() => useOIProfile("NIFTY", "NFO", "2026-04-03"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(oiData);
  });

  it("passes expiry parameter to the API", async () => {
    mockGetOIProfile.mockResolvedValue({ is_sample_data: false, rows: [] });

    renderHook(() => useOIProfile("NIFTY", "NFO", "2026-04-03"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(mockGetOIProfile).toHaveBeenCalled());
    expect(mockGetOIProfile).toHaveBeenCalledWith(
      "NIFTY",
      "NFO",
      "2026-04-03",
      expect.any(AbortSignal),
    );
  });

  it("aborts an in-flight live request when its observer unmounts", async () => {
    mockGetOIProfile.mockReturnValue(new Promise(() => {}));
    const { unmount } = renderHook(
      () => useOIProfile("NIFTY", "NFO", "2026-04-03"),
      { wrapper: createWrapper() },
    );
    await waitFor(() => expect(mockGetOIProfile).toHaveBeenCalledOnce());
    const signal = mockGetOIProfile.mock.calls[0]?.[3] as AbortSignal;

    expect(signal.aborted).toBe(false);
    unmount();
    expect(signal.aborted).toBe(true);
  });

  it("returns sample OI profile data in explore mode without calling the API", async () => {
    useModeStore.setState({ mode: "explore" });

    const { result } = renderHook(() => useOIProfile("NIFTY", "NFO", "2026-04-03"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.is_sample_data).toBe(true);
    expect(result.current.data?.rows.length).toBeGreaterThan(0);
    expect(result.current.data?.rows[0]).toHaveProperty("type");
    expect(mockGetOIProfile).not.toHaveBeenCalled();
  });
});
