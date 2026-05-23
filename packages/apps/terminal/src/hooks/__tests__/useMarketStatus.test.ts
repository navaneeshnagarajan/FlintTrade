/**
 * useMarketStatus tests
 *
 * Tests for the 2 TanStack Query hooks:
 *   - useHolidays
 *   - useTimings
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

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

import { useHolidays, useTimings } from "../useMarketStatus";

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
// useHolidays
// ---------------------------------------------------------------------------

describe("useHolidays", () => {
  it("returns loading state initially", () => {
    mockGetHolidays.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useHolidays(), { wrapper: createWrapper() });
    expect(result.current.isLoading).toBe(true);
  });

  it("returns holidays array on success", async () => {
    const holidays = [
      { date: "2026-01-26", description: "Republic Day", holiday_type: "national", closed_exchanges: ["NSE"], open_exchanges: [] },
      { date: "2026-03-30", description: "Id-ul-Fitr", holiday_type: "national", closed_exchanges: ["NSE"], open_exchanges: [] },
    ];
    mockGetHolidays.mockResolvedValue(holidays);

    const { result } = renderHook(() => useHolidays(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(2);
    expect(result.current.data![0].description).toBe("Republic Day");
  });

  it("returns error state on failure", async () => {
    mockGetHolidays.mockRejectedValue(new Error("Holidays unavailable"));

    const { result } = renderHook(() => useHolidays(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});

// ---------------------------------------------------------------------------
// useTimings
// ---------------------------------------------------------------------------

describe("useTimings", () => {
  it("returns loading state initially", () => {
    mockGetTimings.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useTimings(), { wrapper: createWrapper() });
    expect(result.current.isLoading).toBe(true);
  });

  it("returns timings array on success", async () => {
    const timings = [
      { exchange: "NSE", open: "09:15", close: "15:30", status: "closed" },
    ];
    mockGetTimings.mockResolvedValue(timings);

    const { result } = renderHook(() => useTimings(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toHaveLength(1);
    expect(result.current.data![0].exchange).toBe("NSE");
  });

  it("returns error state on failure", async () => {
    mockGetTimings.mockRejectedValue(new Error("Timings unavailable"));

    const { result } = renderHook(() => useTimings(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
