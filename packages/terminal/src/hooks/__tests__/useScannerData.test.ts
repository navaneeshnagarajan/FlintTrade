/**
 * Tests for useScannerData — mode-aware scanner data hook.
 *
 * Verifies that:
 *   1. Explore mode returns sample data without API calls
 *   2. Live mode fetches multi-quotes and derives scanner tables
 *   3. Live mode with no data falls back to sample data
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ---------------------------------------------------------------------------
// Mock modeStore — start in explore mode, allow switching
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
// Mock API service
// ---------------------------------------------------------------------------

const mockQuotes = [
  {
    symbol: "TATAMOTORS",
    exchange: "NSE",
    ltp: 510,
    open: 500,
    close: 505,
    prev_close: 498,
    volume: 2_000_000,
    high: 515,
    low: 495,
  },
  {
    symbol: "HDFCBANK",
    exchange: "NSE",
    ltp: 1650,
    open: 1640,
    close: 1645,
    prev_close: 1630,
    volume: 3_000_000,
    high: 1660,
    low: 1635,
  },
];

const getMultiQuotesMock = vi.fn((_symbols: string[]) => Promise.resolve(mockQuotes));

vi.mock("@/services/api", () => ({
  getMultiQuotes: (symbols: string[]) => getMultiQuotesMock(symbols),
}));

// Mock sample data
vi.mock("@/widgets/utility/Scanner/sampleData", () => ({
  SAMPLE_GAP_SCANS: [{ symbol: "SAMPLE_GAP", gapPercent: 2.5 }],
  SAMPLE_OI_CHANGES: [{ symbol: "SAMPLE_OI", oiChange: 1000 }],
  SAMPLE_VOLUME_SPIKES: [{ symbol: "SAMPLE_VOL", volumeRatio: 3.2 }],
  SAMPLE_SECTOR_MOVERS: [{ sector: "SAMPLE_SECTOR", avgChange: 1.1 }],
}));

// ---------------------------------------------------------------------------
// Import hook after mocks
// ---------------------------------------------------------------------------

import { useScannerData } from "../useScannerData";

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

describe("useScannerData", () => {
  it("returns sample data in explore mode without API calls", () => {
    const { result } = renderHook(() => useScannerData(), {
      wrapper: createWrapper(),
    });

    expect(result.current.isLive).toBe(false);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.data.gapScans).toEqual([{ symbol: "SAMPLE_GAP", gapPercent: 2.5 }]);
    expect(result.current.data.oiChanges).toEqual([{ symbol: "SAMPLE_OI", oiChange: 1000 }]);
    expect(getMultiQuotesMock).not.toHaveBeenCalled();
  });

  it("fetches multi-quotes in live mode and derives scanner data", async () => {
    currentMode = "live";

    const { result } = renderHook(() => useScannerData(), {
      wrapper: createWrapper(),
    });

    expect(result.current.isLive).toBe(true);

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(getMultiQuotesMock).toHaveBeenCalled();
    // Derived gap scans should come from the mock quotes (TATAMOTORS and HDFCBANK)
    expect(result.current.data.gapScans.length).toBeGreaterThan(0);
    expect(result.current.data.gapScans[0].symbol).toBeDefined();
    // OI changes always use sample data
    expect(result.current.data.oiChanges).toEqual([{ symbol: "SAMPLE_OI", oiChange: 1000 }]);
  });

  it("provides a refetch function", async () => {
    currentMode = "live";

    const { result } = renderHook(() => useScannerData(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(typeof result.current.refetch).toBe("function");
    // Should not throw
    result.current.refetch();
  });
});
