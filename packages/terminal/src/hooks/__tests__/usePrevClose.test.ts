/**
 * Tests for usePrevClose
 *
 * Strategy:
 *   - Mock getMultiQuotes (api.ts) to return deterministic Quote values
 *   - Mock useConnectionStore to control apiKey (enabled/disabled gate)
 *   - Use renderHook with a wrapper that provides both:
 *       - Jotai Provider (custom store for inspection)
 *       - QueryClientProvider (TanStack Query, no retries in tests)
 *   - Verify that prevClose is merged into tickAtomFamily atoms correctly
 *   - Verify graceful handling of failures and missing data
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createStore, Provider } from "jotai";
import React from "react";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import type { Quote } from "@/types/api";

// --- Mocks ------------------------------------------------------------------

const mockGetMultiQuotes = vi.fn<(symbols: Array<{ symbol: string; exchange: string }>) => Promise<Quote[]>>();

vi.mock("@/services/api", () => ({
  getMultiQuotes: (symbols: Array<{ symbol: string; exchange: string }>) =>
    mockGetMultiQuotes(symbols),
}));

let _apiKey = "test-api-key";

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: (selector: (s: { apiKey: string }) => unknown) => {
    return selector({ apiKey: _apiKey });
  },
}));

// ----------------------------------------------------------------------------

import { usePrevClose } from "../usePrevClose";

/** Build a wrapper that provides both Jotai store and TanStack QueryClient. */
function makeWrapper(store: ReturnType<typeof createStore>, queryClient: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(
      QueryClientProvider,
      { client: queryClient },
      React.createElement(Provider, { store }, children),
    );
  };
}

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // No retries in tests so failures surface immediately
        retry: false,
        // No delays — resolve immediately
        gcTime: 0,
      },
    },
  });
}

// ---------------------------------------------------------------------------

describe("usePrevClose", () => {
  let store: ReturnType<typeof createStore>;
  let queryClient: QueryClient;

  beforeEach(() => {
    store = createStore();
    queryClient = makeQueryClient();
    _apiKey = "test-api-key";
    mockGetMultiQuotes.mockReset();
  });

  afterEach(() => {
    queryClient.clear();
    vi.clearAllMocks();
  });

  it("does nothing when apiKey is empty (query is disabled)", async () => {
    _apiKey = "";
    mockGetMultiQuotes.mockResolvedValue([]);

    renderHook(() => usePrevClose(), {
      wrapper: makeWrapper(store, queryClient),
    });

    // Allow any async effects to settle
    await act(async () => {
      await new Promise((r) => setTimeout(r, 10));
    });

    expect(mockGetMultiQuotes).not.toHaveBeenCalled();
  });

  it("calls getMultiQuotes with all ticker instruments", async () => {
    mockGetMultiQuotes.mockResolvedValue([]);

    renderHook(() => usePrevClose(), {
      wrapper: makeWrapper(store, queryClient),
    });

    await waitFor(() => expect(mockGetMultiQuotes).toHaveBeenCalledTimes(1));

    const [calledWith] = mockGetMultiQuotes.mock.calls[0];
    // Should include at minimum NIFTY and SENSEX
    expect(calledWith).toEqual(
      expect.arrayContaining([
        { symbol: "NIFTY", exchange: "NSE_INDEX" },
        { symbol: "SENSEX", exchange: "BSE_INDEX" },
      ]),
    );
  });

  it("merges prevClose into an existing tick atom", async () => {
    // Pre-seed atom with live LTP data (as WS bridge would do)
    const existingTick = {
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      ltp: 23500,
    };
    store.set(tickAtomFamily("NSE_INDEX:NIFTY"), existingTick);

    mockGetMultiQuotes.mockResolvedValue([
      {
        symbol: "NIFTY",
        exchange: "NSE_INDEX",
        ltp: 23500,
        open: 23000,
        high: 23600,
        low: 22900,
        close: 23150,
        volume: 100000,
      },
    ]);

    renderHook(() => usePrevClose(), {
      wrapper: makeWrapper(store, queryClient),
    });

    await waitFor(() => {
      const tick = store.get(tickAtomFamily("NSE_INDEX:NIFTY"));
      expect(tick?.prevClose).toBe(23150);
    });

    // Original ltp must be preserved
    const tick = store.get(tickAtomFamily("NSE_INDEX:NIFTY"));
    expect(tick?.ltp).toBe(23500);
    expect(tick?.symbol).toBe("NIFTY");
    expect(tick?.exchange).toBe("NSE_INDEX");
  });

  it("pre-seeds a tick atom for instruments not yet seen from WebSocket", async () => {
    mockGetMultiQuotes.mockResolvedValue([
      {
        symbol: "BANKNIFTY",
        exchange: "NSE_INDEX",
        ltp: 51000,
        open: 50500,
        high: 51200,
        low: 50300,
        close: 50800,
        volume: 50000,
      },
    ]);

    // Atom starts as null (no WS data yet)
    expect(store.get(tickAtomFamily("NSE_INDEX:BANKNIFTY"))).toBeNull();

    renderHook(() => usePrevClose(), {
      wrapper: makeWrapper(store, queryClient),
    });

    await waitFor(() => {
      const tick = store.get(tickAtomFamily("NSE_INDEX:BANKNIFTY"));
      expect(tick).not.toBeNull();
    });

    const tick = store.get(tickAtomFamily("NSE_INDEX:BANKNIFTY"));
    expect(tick?.prevClose).toBe(50800);
    expect(tick?.symbol).toBe("BANKNIFTY");
    expect(tick?.exchange).toBe("NSE_INDEX");
    // ltp is 0 as a placeholder — will be updated when WS delivers ticks
    expect(tick?.ltp).toBe(0);
  });

  it("handles multiple instruments in one query response", async () => {
    mockGetMultiQuotes.mockResolvedValue([
      {
        symbol: "NIFTY",
        exchange: "NSE_INDEX",
        ltp: 23500,
        open: 0, high: 0, low: 0,
        close: 23150,
        volume: 0,
      },
      {
        symbol: "SENSEX",
        exchange: "BSE_INDEX",
        ltp: 77000,
        open: 0, high: 0, low: 0,
        close: 76800,
        volume: 0,
      },
      {
        symbol: "INDIAVIX",
        exchange: "NSE_INDEX",
        ltp: 14.5,
        open: 0, high: 0, low: 0,
        close: 13.8,
        volume: 0,
      },
    ]);

    renderHook(() => usePrevClose(), {
      wrapper: makeWrapper(store, queryClient),
    });

    await waitFor(() => {
      expect(store.get(tickAtomFamily("NSE_INDEX:NIFTY"))?.prevClose).toBe(23150);
    });

    expect(store.get(tickAtomFamily("BSE_INDEX:SENSEX"))?.prevClose).toBe(76800);
    expect(store.get(tickAtomFamily("NSE_INDEX:INDIAVIX"))?.prevClose).toBe(13.8);
  });

  it("skips instruments where close is 0 or missing", async () => {
    mockGetMultiQuotes.mockResolvedValue([
      {
        symbol: "NIFTY",
        exchange: "NSE_INDEX",
        ltp: 23500,
        open: 0, high: 0, low: 0,
        close: 0, // invalid — skip
        volume: 0,
      },
      {
        symbol: "SENSEX",
        exchange: "BSE_INDEX",
        ltp: 77000,
        open: 0, high: 0, low: 0,
        close: 76800,
        volume: 0,
      },
    ]);

    renderHook(() => usePrevClose(), {
      wrapper: makeWrapper(store, queryClient),
    });

    await waitFor(() => {
      expect(store.get(tickAtomFamily("BSE_INDEX:SENSEX"))?.prevClose).toBe(76800);
    });

    // NIFTY atom should remain null (close=0 was rejected)
    expect(store.get(tickAtomFamily("NSE_INDEX:NIFTY"))).toBeNull();
  });

  it("does not overwrite prevClose on live tick atoms if query returns empty", async () => {
    // Pre-seed with a tick that already has prevClose
    store.set(tickAtomFamily("NSE_INDEX:NIFTY"), {
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      ltp: 23500,
      prevClose: 23150,
    });

    mockGetMultiQuotes.mockResolvedValue([]);

    renderHook(() => usePrevClose(), {
      wrapper: makeWrapper(store, queryClient),
    });

    await act(async () => {
      await new Promise((r) => setTimeout(r, 20));
    });

    // prevClose must remain intact since query returned empty
    const tick = store.get(tickAtomFamily("NSE_INDEX:NIFTY"));
    expect(tick?.prevClose).toBe(23150);
    expect(tick?.ltp).toBe(23500);
  });

  it("handles getMultiQuotes failure gracefully without throwing", async () => {
    mockGetMultiQuotes.mockRejectedValue(new Error("Network error"));

    // Should not throw
    expect(() => {
      renderHook(() => usePrevClose(), {
        wrapper: makeWrapper(store, queryClient),
      });
    }).not.toThrow();

    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });

    // Atoms remain untouched on query failure
    expect(store.get(tickAtomFamily("NSE_INDEX:NIFTY"))).toBeNull();
  });

  it("handles non-array response from getMultiQuotes", async () => {
    // Some broker adapters may return unexpected shapes — guard against it
    mockGetMultiQuotes.mockResolvedValue(
      null as unknown as Quote[],
    );

    renderHook(() => usePrevClose(), {
      wrapper: makeWrapper(store, queryClient),
    });

    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });

    // No atoms should be set
    expect(store.get(tickAtomFamily("NSE_INDEX:NIFTY"))).toBeNull();
  });
});
