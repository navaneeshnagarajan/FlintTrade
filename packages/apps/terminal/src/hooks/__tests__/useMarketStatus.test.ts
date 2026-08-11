/**
 * useMarketStatus tests
 *
 * Tests for the 2 TanStack Query hooks:
 *   - useHolidays
 *   - useTimings
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import type { MarketTiming } from "@/types/api";

// ---------------------------------------------------------------------------
// Mock api service
// ---------------------------------------------------------------------------

const mockGetHolidays = vi.fn();
const mockGetTimings = vi.fn();

vi.mock("@/services/api", () => ({
  getHolidays: () => mockGetHolidays(),
  getTimings: () => mockGetTimings(),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import {
  MARKET_TIMINGS_MAX_AGE_MS,
  MARKET_TIMINGS_REFRESH_INTERVAL_MS,
  useHolidays,
  useTimings,
} from "../useMarketStatus";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createHarness() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        gcTime: Infinity,
        retry: false,
      },
    },
  });
  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children);
  return { queryClient, wrapper };
}

function timing(exchange: string): MarketTiming {
  return { exchange, start_time: 1, end_time: 2 };
}

async function advanceFakeTime(milliseconds: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(milliseconds);
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(1);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  mockGetHolidays.mockReset();
  mockGetTimings.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// useHolidays
// ---------------------------------------------------------------------------

describe("useHolidays", () => {
  it("returns loading state initially", () => {
    mockGetHolidays.mockReturnValue(new Promise(() => {}));
    const { wrapper } = createHarness();
    const { result } = renderHook(() => useHolidays(), { wrapper });
    expect(result.current.isLoading).toBe(true);
  });

  it("returns holidays array on success", async () => {
    const holidays = [
      { date: "2026-01-26", description: "Republic Day", holiday_type: "national", closed_exchanges: ["NSE"], open_exchanges: [] },
      { date: "2026-03-30", description: "Id-ul-Fitr", holiday_type: "national", closed_exchanges: ["NSE"], open_exchanges: [] },
    ];
    mockGetHolidays.mockResolvedValue(holidays);
    const { wrapper } = createHarness();

    const { result } = renderHook(() => useHolidays(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(2);
    expect(result.current.data![0].description).toBe("Republic Day");
  });

  it("returns error state on failure", async () => {
    mockGetHolidays.mockRejectedValue(new Error("Holidays unavailable"));
    const { wrapper } = createHarness();

    const { result } = renderHook(() => useHolidays(), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

// ---------------------------------------------------------------------------
// useTimings
// ---------------------------------------------------------------------------

describe("useTimings", () => {
  it("returns loading state initially", () => {
    mockGetTimings.mockReturnValue(new Promise(() => {}));
    const { wrapper } = createHarness();
    const { result } = renderHook(() => useTimings(), { wrapper });
    expect(result.current.isLoading).toBe(true);
  });

  it("returns timings array on success", async () => {
    mockGetTimings.mockResolvedValue([timing("NSE")]);
    const { wrapper } = createHarness();

    const { result } = renderHook(() => useTimings(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data![0].exchange).toBe("NSE");
  });

  it("returns error state on failure", async () => {
    mockGetTimings.mockRejectedValue(new Error("Timings unavailable"));
    const { wrapper } = createHarness();

    const { result } = renderHook(() => useTimings(), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });

  it("shares a refresh cadence shorter than the UI truth TTL", () => {
    expect(MARKET_TIMINGS_MAX_AGE_MS).toBe(60 * 60_000);
    expect(MARKET_TIMINGS_REFRESH_INTERVAL_MS).toBeGreaterThan(0);
    expect(MARKET_TIMINGS_REFRESH_INTERVAL_MS).toBeLessThan(
      MARKET_TIMINGS_MAX_AGE_MS,
    );
  });

  it("does not fetch initially or poll while disabled", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-10T04:30:00.000Z"));
    mockGetTimings.mockResolvedValue([timing("NSE")]);
    const { wrapper } = createHarness();

    const { result } = renderHook(() => useTimings(false), { wrapper });
    await advanceFakeTime(MARKET_TIMINGS_MAX_AGE_MS * 2);

    expect(result.current.fetchStatus).toBe("idle");
    expect(mockGetTimings).not.toHaveBeenCalled();
  });

  it("attempts an automatic refresh before timing truth expires", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-10T04:30:00.000Z"));
    const startedAt = Date.now();
    mockGetTimings
      .mockResolvedValueOnce([timing("NSE")])
      .mockResolvedValueOnce([timing("NSE_REFRESHED")]);
    const { wrapper } = createHarness();

    const { result } = renderHook(() => useTimings(), { wrapper });
    await advanceFakeTime(0);
    expect(result.current.data?.[0].exchange).toBe("NSE");

    await advanceFakeTime(MARKET_TIMINGS_REFRESH_INTERVAL_MS);
    expect(result.current.data?.[0].exchange).toBe("NSE_REFRESHED");

    expect(mockGetTimings).toHaveBeenCalledTimes(2);
    expect(Date.now() - startedAt).toBeLessThan(MARKET_TIMINGS_MAX_AGE_MS);
  });

  it("reports a failed refresh, then recovers after more than one hour without remounting", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-10T04:30:00.000Z"));
    const startedAt = Date.now();
    const refreshError = new Error("Timings refresh failed");
    mockGetTimings
      .mockResolvedValueOnce([timing("NSE")])
      .mockRejectedValueOnce(refreshError)
      .mockResolvedValueOnce([timing("NSE_RECOVERED")]);
    const { queryClient, wrapper } = createHarness();

    const { result } = renderHook(() => useTimings(), { wrapper });
    await advanceFakeTime(0);
    expect(result.current.data?.[0].exchange).toBe("NSE");
    expect(result.current.isError).toBe(false);

    await advanceFakeTime(MARKET_TIMINGS_REFRESH_INTERVAL_MS);
    expect(mockGetTimings).toHaveBeenCalledTimes(2);
    expect(queryClient.getQueryState(["timings"])?.status).toBe("error");
    expect(result.current.fetchStatus).toBe("idle");
    expect(result.current.isError).toBe(true);
    expect(result.current.error).toBe(refreshError);
    expect(result.current.data?.[0].exchange).toBe("NSE");

    await advanceFakeTime(MARKET_TIMINGS_REFRESH_INTERVAL_MS);
    expect(result.current.data?.[0].exchange).toBe("NSE_RECOVERED");

    expect(result.current.isSuccess).toBe(true);
    expect(mockGetTimings).toHaveBeenCalledTimes(3);
    expect(Date.now() - startedAt).toBeGreaterThan(MARKET_TIMINGS_MAX_AGE_MS);
  });
});
