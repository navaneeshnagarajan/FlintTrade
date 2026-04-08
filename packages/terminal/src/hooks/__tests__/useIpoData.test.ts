/**
 * Tests for useIpoData — mode-aware IPO data hook.
 *
 * Verifies that:
 *   1. Explore mode returns fallback IPO data without API calls
 *   2. Live mode fetches from the backend
 *   3. The refetch function is callable
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ---------------------------------------------------------------------------
// Mock modeStore
// ---------------------------------------------------------------------------

let currentMode: "explore" | "practice" | "live" = "explore";
const modeListeners = new Set<() => void>();

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) => {
    const [, setState] = React.useState(0);
    React.useEffect(() => {
      const cb = () => setState((n) => n + 1);
      modeListeners.add(cb);
      return () => { modeListeners.delete(cb); };
    }, []);
    return selector({ mode: currentMode });
  },
}));

// ---------------------------------------------------------------------------
// Mock ftApi service
// ---------------------------------------------------------------------------

const mockUpcoming = {
  ipos: [
    {
      name: "Test IPO Ltd",
      symbol: "TESTIPO",
      issue_size: "\u20B91,000 Cr",
      price_band: "\u20B9100 - \u20B9110",
      lot_size: 100,
      open_date: "2026-06-01",
      close_date: "2026-06-03",
      listing_date: "",
      status: "upcoming",
      listing_gain: undefined,
    },
  ],
  last_updated: "2026-04-08T10:00:00Z",
};

const mockRecent = {
  ipos: [
    {
      name: "Listed Corp",
      symbol: "LISTED",
      issue_size: "\u20B9500 Cr",
      price_band: "\u20B9200 - \u20B9220",
      lot_size: 50,
      open_date: "2026-03-01",
      close_date: "2026-03-03",
      listing_date: "2026-03-06",
      status: "listed",
      listing_gain: 15.0,
    },
  ],
  last_updated: "2026-04-08T10:00:00Z",
};

const getUpcomingMock = vi.fn(() => Promise.resolve(mockUpcoming));
const getRecentMock = vi.fn(() => Promise.resolve(mockRecent));

vi.mock("@/services/ftApi", () => ({
  getUpcomingIPOs: () => getUpcomingMock(),
  getRecentIPOs: () => getRecentMock(),
}));

// ---------------------------------------------------------------------------
// Import hook after mocks
// ---------------------------------------------------------------------------

import { useIpoData } from "../useIpoData";

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
  currentMode = "explore";
  modeListeners.clear();
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useIpoData", () => {
  it("returns fallback IPO data in explore mode without API calls", () => {
    const { result } = renderHook(() => useIpoData(), {
      wrapper: createWrapper(),
    });

    expect(result.current.isLive).toBe(false);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
    // Fallback upcoming has LG Electronics India
    expect(result.current.data.upcoming.length).toBeGreaterThan(0);
    expect(result.current.data.upcoming[0].name).toBe("LG Electronics India");
    // Fallback recent has Hexaware Technologies
    expect(result.current.data.recent.length).toBeGreaterThan(0);
    expect(result.current.data.recent[0].name).toBe("Hexaware Technologies");
    expect(getUpcomingMock).not.toHaveBeenCalled();
    expect(getRecentMock).not.toHaveBeenCalled();
  });

  it("fetches IPO data from backend in live mode", async () => {
    currentMode = "live";

    const { result } = renderHook(() => useIpoData(), {
      wrapper: createWrapper(),
    });

    expect(result.current.isLive).toBe(true);

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(getUpcomingMock).toHaveBeenCalled();
    expect(getRecentMock).toHaveBeenCalled();
    expect(result.current.data.upcoming[0].name).toBe("Test IPO Ltd");
    expect(result.current.data.recent[0].name).toBe("Listed Corp");
    expect(result.current.data.lastUpdated).toBe("2026-04-08T10:00:00Z");
  });

  it("provides a callable refetch function", async () => {
    currentMode = "live";

    const { result } = renderHook(() => useIpoData(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(typeof result.current.refetch).toBe("function");
    // Should not throw
    result.current.refetch();
  });
});
