/**
 * Tests for useSectorMovers — mode-aware sector-mover hook.
 *
 * Verifies that:
 *   1. Explore mode returns sample rows without API calls (isLive false)
 *   2. Live mode fetches multi-quotes and derives sector movers (isLive true)
 *   3. A failed fetch falls back to sample rows and NEVER reports isLive
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

const getMultiQuotesMock = vi.fn((_symbols: unknown) => Promise.resolve(mockQuotes));

vi.mock("@/services/api", () => ({
  getMultiQuotes: (symbols: unknown) => getMultiQuotesMock(symbols),
  normaliseMultiQuotes: (raw: unknown) => (Array.isArray(raw) ? raw : []),
}));

// Mock sample data
vi.mock("@/widgets/utility/Scanner/sampleData", () => ({
  SAMPLE_OI_CHANGES: [{ symbol: "SAMPLE_OI", oiChange: 1000 }],
  SAMPLE_SECTOR_MOVERS: [{ sector: "SAMPLE_SECTOR", avgChange: 1.1 }],
}));

// ---------------------------------------------------------------------------
// Import hook after mocks
// ---------------------------------------------------------------------------

import { useSectorMovers, deriveSectorMovers } from "../useSectorMovers";
import type { Quote } from "@/types/api";

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
  getMultiQuotesMock.mockImplementation(() => Promise.resolve(mockQuotes));
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useSectorMovers", () => {
  it("returns sample rows in explore mode without API calls", () => {
    const { result } = renderHook(() => useSectorMovers(), {
      wrapper: createWrapper(),
    });

    expect(result.current.isLive).toBe(false);
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
    expect(result.current.data).toEqual([{ sector: "SAMPLE_SECTOR", avgChange: 1.1 }]);
    expect(getMultiQuotesMock).not.toHaveBeenCalled();
  });

  it("fetches multi-quotes in live mode and derives sector movers", async () => {
    currentMode = "live";

    const { result } = renderHook(() => useSectorMovers(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isLive).toBe(true));

    expect(getMultiQuotesMock).toHaveBeenCalled();
    const sectors = result.current.data.map((row) => row.sector);
    expect(sectors).toContain("Auto"); // TATAMOTORS
    expect(sectors).toContain("Banking"); // HDFCBANK
    expect(sectors).not.toContain("SAMPLE_SECTOR");
  });

  it("falls back to sample rows on fetch failure and never claims live", { timeout: 15000 }, async () => {
    currentMode = "live";
    getMultiQuotesMock.mockImplementation(() => Promise.reject(new Error("OpenAlgo down")));

    const { result } = renderHook(() => useSectorMovers(), {
      wrapper: createWrapper(),
    });

    // The hook retries twice with backoff before surfacing the error — allow
    // the full retry window before asserting.
    await waitFor(() => expect(result.current.error).not.toBeNull(), { timeout: 9000 });

    expect(result.current.isLoading).toBe(false);
    expect(result.current.isLive).toBe(false);
    expect(result.current.data).toEqual([{ sector: "SAMPLE_SECTOR", avgChange: 1.1 }]);
  });

  it("provides a refetch function", async () => {
    currentMode = "live";

    const { result } = renderHook(() => useSectorMovers(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isLive).toBe(true));

    expect(typeof result.current.refetch).toBe("function");
    // Should not throw
    result.current.refetch();
  });
});

describe("deriveSectorMovers", () => {
  it("groups quotes into sector aggregates with top gainer/loser", () => {
    const rows = deriveSectorMovers(mockQuotes as unknown as Quote[]);
    const auto = rows.find((r) => r.sector === "Auto");
    expect(auto).toBeDefined();
    expect(auto?.advancers).toBe(1);
    expect(auto?.topGainer).toBe("TATAMOTORS");
  });

  it("skips quotes without a usable previous close", () => {
    const rows = deriveSectorMovers([
      { symbol: "TATAMOTORS", exchange: "NSE", ltp: 510, prev_close: 0, close: 0 },
    ] as unknown as Quote[]);
    expect(rows).toEqual([]);
  });
});
