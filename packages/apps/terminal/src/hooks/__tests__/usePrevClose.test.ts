/**
 * Tests for usePrevClose
 *
 * Strategy:
 *   - Mock getMultiQuotes and getQuotes (api.ts) to return deterministic Quote values
 *   - Mock native broker connectivity to control the query (enabled/disabled gate)
 *   - Use renderHook with a wrapper that provides both:
 *       - Jotai Provider (custom store for inspection)
 *       - QueryClientProvider (TanStack Query, no retries in tests)
 *   - Verify that prevClose is merged into tickAtomFamily atoms correctly
 *   - Verify graceful handling of failures and missing data
 *   - Verify fallback to individual getQuotes when multiquotes fails
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createStore, Provider } from "jotai";
import React from "react";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { useModeStore } from "@/stores/modeStore";
import { useBrokerStore } from "@/stores/brokerStore";
import type { BrokerAccount } from "@/types/broker";
function selectNativeAccount(accountId = "A1") {
  useModeStore.setState({ mode: "live" });
  useBrokerStore.setState({ accounts: [{ account_id: accountId, broker: "dhan", source: "native", label: "Test", status: "connected", connected_at: null, error_message: null, is_primary: true } as BrokerAccount], activeAccountId: `native:dhan:${accountId}` });
}
import type { Quote } from "@/types/api";

// --- Mocks ------------------------------------------------------------------

const mockGetMultiQuotes = vi.fn<(symbols: Array<{ symbol: string; exchange: string }>, signal?: AbortSignal, scope?: string) => Promise<Quote[]>>();
const mockGetQuotes = vi.fn<(symbol: string, exchange: string, signal?: AbortSignal, scope?: string) => Promise<Quote>>();

vi.mock("@/services/api", () => ({
  getMultiQuotes: (symbols: Array<{ symbol: string; exchange: string }>, signal?: AbortSignal, scope?: string) =>
    mockGetMultiQuotes(symbols, signal, scope),
  getQuotes: (symbol: string, exchange: string, signal?: AbortSignal, scope?: string) =>
    mockGetQuotes(symbol, exchange, signal, scope),
}));

let _connected = true;

vi.mock("@/hooks/useBrokerConnected", () => ({ useBrokerConnected: () => _connected }));
let mockScope = "live:native:dhan:A1";
vi.mock("@/hooks/useDataScope", () => ({
  useMarketDataScope: () => mockScope,
  requireCurrentMarketDataScope: (scope: string) => { if (scope !== mockScope) throw new Error("Authority changed"); },
  MarketDataAuthorityChangedError: class extends Error {},
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
    _connected = true;
    mockScope = "live:native:dhan:A1";
    selectNativeAccount();
    mockGetMultiQuotes.mockReset();
    mockGetQuotes.mockReset();
  });

  afterEach(() => {
    queryClient.clear();
    vi.clearAllMocks();
  });

  it("does nothing when no native broker is connected (query is disabled)", async () => {
    _connected = false;
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
    // fallback: no individual calls return data
    mockGetQuotes.mockRejectedValue(new Error("not found"));

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

  it("reads prev_close (native broker field) as the primary prevClose source", async () => {
    // Pre-seed atom with live LTP data (as WS bridge would do)
    store.set(tickAtomFamily("NSE_INDEX:NIFTY"), {
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      ltp: 23500,
    });

    mockGetMultiQuotes.mockResolvedValue([
      {
        symbol: "NIFTY",
        exchange: "NSE_INDEX",
        ltp: 23500,
        open: 23000,
        high: 23600,
        low: 22900,
        close: 23490,      // current session OHLC close — NOT used as prevClose
        prev_close: 23150, // previous session close — this is the correct field
        volume: 100000,
      },
    ]);

    renderHook(() => usePrevClose(), {
      wrapper: makeWrapper(store, queryClient),
    });

    await waitFor(() => {
      const tick = store.get(tickAtomFamily("NSE_INDEX:NIFTY"));
      expect(tick?.prevClose).toBe(23150); // must come from prev_close, not close
    });

    // Original ltp must be preserved
    const tick = store.get(tickAtomFamily("NSE_INDEX:NIFTY"));
    expect(tick?.ltp).toBe(23500);
    expect(tick?.symbol).toBe("NIFTY");
    expect(tick?.exchange).toBe("NSE_INDEX");
  });

  it("falls back to close field when prev_close is absent (broker adapter compat)", async () => {
    store.set(tickAtomFamily("NSE_INDEX:NIFTY"), {
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      ltp: 23500,
    });

    mockGetMultiQuotes.mockResolvedValue([
      {
        symbol: "NIFTY",
        exchange: "NSE_INDEX",
        ltp: 23500,
        open: 23000,
        high: 23600,
        low: 22900,
        close: 23150, // prev_close absent — fall back to close
        volume: 100000,
        // no prev_close field
      },
    ]);

    renderHook(() => usePrevClose(), {
      wrapper: makeWrapper(store, queryClient),
    });

    await waitFor(() => {
      const tick = store.get(tickAtomFamily("NSE_INDEX:NIFTY"));
      expect(tick?.prevClose).toBe(23150);
    });
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
        close: 50750,
        prev_close: 50800,
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
    expect(tick?.prevClose).toBe(50800); // from prev_close
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
        close: 23490,
        prev_close: 23150,
        volume: 0,
      },
      {
        symbol: "SENSEX",
        exchange: "BSE_INDEX",
        ltp: 77000,
        open: 0, high: 0, low: 0,
        close: 76950,
        prev_close: 76800,
        volume: 0,
      },
      {
        symbol: "INDIAVIX",
        exchange: "NSE_INDEX",
        ltp: 14.5,
        open: 0, high: 0, low: 0,
        close: 14.3,
        prev_close: 13.8,
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

  it("skips instruments where both prev_close and close are 0 or missing", async () => {
    mockGetMultiQuotes.mockResolvedValue([
      {
        symbol: "NIFTY",
        exchange: "NSE_INDEX",
        ltp: 23500,
        open: 0, high: 0, low: 0,
        close: 0,      // invalid
        prev_close: 0, // invalid — skip
        volume: 0,
      },
      {
        symbol: "SENSEX",
        exchange: "BSE_INDEX",
        ltp: 77000,
        open: 0, high: 0, low: 0,
        close: 76800,
        prev_close: 76800,
        volume: 0,
      },
    ]);

    // Individual fallback for NIFTY also returns nothing useful
    mockGetQuotes.mockImplementation((symbol: string, exchange: string) => {
      if (symbol === "NIFTY" && exchange === "NSE_INDEX") {
        return Promise.resolve({
          symbol: "NIFTY",
          exchange: "NSE_INDEX",
          ltp: 23500,
          open: 0, high: 0, low: 0,
          close: 0,
          volume: 0,
        });
      }
      return Promise.reject(new Error("unexpected call"));
    });

    renderHook(() => usePrevClose(), {
      wrapper: makeWrapper(store, queryClient),
    });

    await waitFor(() => {
      expect(store.get(tickAtomFamily("BSE_INDEX:SENSEX"))?.prevClose).toBe(76800);
    });

    // NIFTY atom should remain null (both prev_close and close were 0/invalid)
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
    // fallback also fails for all instruments — no overwrite
    mockGetQuotes.mockRejectedValue(new Error("unavailable"));

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

  it("handles getMultiQuotes failure gracefully and uses individual fallback", async () => {
    mockGetMultiQuotes.mockRejectedValue(new Error("Network error"));

    // Individual fallback returns data for NIFTY only
    mockGetQuotes.mockImplementation((symbol: string, exchange: string) => {
      if (symbol === "NIFTY" && exchange === "NSE_INDEX") {
        return Promise.resolve({
          symbol: "NIFTY",
          exchange: "NSE_INDEX",
          ltp: 23500,
          open: 0, high: 0, low: 0,
          close: 0,
          prev_close: 23150,
          volume: 0,
        });
      }
      return Promise.reject(new Error("not found"));
    });

    renderHook(() => usePrevClose(), {
      wrapper: makeWrapper(store, queryClient),
    });

    // Wait for the fallback to complete (individual calls are staggered 100ms)
    await waitFor(
      () => {
        const tick = store.get(tickAtomFamily("NSE_INDEX:NIFTY"));
        expect(tick?.prevClose).toBe(23150);
      },
      { timeout: 3000 },
    );
  });

  it("handles non-array response from getMultiQuotes gracefully", async () => {
    // Some broker adapters may return unexpected shapes — guard against it
    mockGetMultiQuotes.mockResolvedValue(
      null as unknown as Quote[],
    );
    // Individual fallback also returns nothing
    mockGetQuotes.mockRejectedValue(new Error("not found"));

    renderHook(() => usePrevClose(), {
      wrapper: makeWrapper(store, queryClient),
    });

    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });

    // No atoms should be set
    expect(store.get(tickAtomFamily("NSE_INDEX:NIFTY"))).toBeNull();
  });
  it("aborts old previous-close authority without starting fallback reads or seeding its atoms", async () => {
    const requests: Array<{ symbols: Array<{ symbol: string; exchange: string }>; signal: AbortSignal; scope: string; finish: (value: Quote[]) => void }> = [];
    mockGetMultiQuotes.mockImplementation((symbols, signal, scope) => new Promise((finish) => { requests.push({ symbols, signal: signal!, scope: scope!, finish }); }));
    const { rerender } = renderHook(() => usePrevClose(), { wrapper: makeWrapper(store, queryClient) });
    await waitFor(() => expect(requests).toHaveLength(1));
    mockScope = "practice:native:upstox:B1";
    useModeStore.setState({ mode: "practice" });
    useBrokerStore.setState({ accounts: [{ account_id: "B1", broker: "upstox", source: "native", label: "B", status: "connected", is_primary: true, connected_at: null, error_message: null }], activeAccountId: "native:upstox:B1" });
    rerender();
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(requests[0].signal.aborted).toBe(true);
    expect(requests[1].scope).toBe(mockScope);
    await act(async () => { requests[0].finish(requests[0].symbols.map((s) => ({ ...s, ltp: 100, prev_close: 90 }) as Quote)); });
    expect(store.get(tickAtomFamily("NSE_INDEX:NIFTY"))).toBeNull();
    expect(mockGetQuotes).not.toHaveBeenCalled();
    await act(async () => { requests[1].finish(requests[1].symbols.map((s) => ({ ...s, ltp: 100, prev_close: 110 }) as Quote)); });
    await waitFor(() => expect(store.get(tickAtomFamily("NSE_INDEX:NIFTY"))?.prevClose).toBe(110));
  });

  it("restores previous-close fetching after root StrictMode replay and aborts on unmount", async () => {
    const requests: Array<{ signal: AbortSignal; finish: (value: Quote[]) => void }> = [];
    mockGetMultiQuotes.mockImplementation((_symbols, signal) => new Promise((finish) => { requests.push({ signal: signal!, finish }); }));
    const { unmount } = renderHook(() => usePrevClose(), { wrapper: makeWrapper(store, queryClient), reactStrictMode: true });
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(requests[0].signal.aborted).toBe(true);
    expect(requests[1].signal.aborted).toBe(false);
    unmount();
    expect(requests[1].signal.aborted).toBe(true);
    await act(async () => { requests.forEach((request) => request.finish([])); });
    expect(mockGetQuotes).not.toHaveBeenCalled();
    expect(store.get(tickAtomFamily("NSE_INDEX:NIFTY"))).toBeNull();
  });

  it("refuses a pending A reference after batched return and admits the fresh returned-A result", async () => {
    const requests: Array<{ symbols: Array<{ symbol: string; exchange: string }>; signal: AbortSignal; finish: (value: Quote[]) => void }> = [];
    mockGetMultiQuotes.mockImplementation((symbols, signal) => new Promise((finish) => { requests.push({ symbols, signal: signal!, finish }); }));
    renderHook(() => usePrevClose(), { wrapper: makeWrapper(store, queryClient) });
    await waitFor(() => expect(requests).toHaveLength(1));
    act(() => { selectNativeAccount("A2"); selectNativeAccount(); });
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(requests[0].signal.aborted).toBe(true);
    await act(async () => { requests[0].finish(requests[0].symbols.map((s) => ({ ...s, ltp: 999, prev_close: 999 }) as Quote)); });
    expect(store.get(tickAtomFamily("NSE_INDEX:NIFTY"))).toBeNull();
    expect(mockGetQuotes).not.toHaveBeenCalled();
    await act(async () => { requests[1].finish(requests[1].symbols.map((s) => ({ ...s, ltp: 101, prev_close: 90 }) as Quote)); });
    await waitFor(() => expect(store.get(tickAtomFamily("NSE_INDEX:NIFTY"))?.prevClose).toBe(90));
  });

  it("clears the cached A reference on batched return until a fresh reference arrives", async () => {
    let finish!: (quotes: Quote[]) => void;
    let symbols: Array<{ symbol: string; exchange: string }> = [];
    mockGetMultiQuotes.mockImplementationOnce((items) => Promise.resolve(items.map((s) => ({ ...s, ltp: 101, prev_close: 90 }) as Quote)));
    mockGetMultiQuotes.mockImplementation((items) => {
      symbols = items;
      return new Promise((resolve) => { finish = resolve; });
    });
    renderHook(() => usePrevClose(), { wrapper: makeWrapper(store, queryClient) });
    await waitFor(() => expect(store.get(tickAtomFamily("NSE_INDEX:NIFTY"))?.prevClose).toBe(90));
    act(() => { selectNativeAccount("A2"); selectNativeAccount(); });
    expect(store.get(tickAtomFamily("NSE_INDEX:NIFTY"))).toBeNull();
    await waitFor(() => expect(mockGetMultiQuotes).toHaveBeenCalledTimes(2));
    expect(store.get(tickAtomFamily("NSE_INDEX:NIFTY"))).toBeNull();
    await act(async () => { finish(symbols.map((s) => ({ ...s, ltp: 102, prev_close: 91 }) as Quote)); });
    await waitFor(() => expect(store.get(tickAtomFamily("NSE_INDEX:NIFTY"))?.prevClose).toBe(91));
  });

  it("retires a pending individual fallback across batched return without dispatching its remaining instruments", async () => {
    let finish!: (quote: Quote) => void;
    let freshFinish!: (quotes: Quote[]) => void;
    let freshSymbols: Array<{ symbol: string; exchange: string }> = [];
    mockGetMultiQuotes.mockResolvedValueOnce([]);
    mockGetMultiQuotes.mockImplementation((symbols) => {
      freshSymbols = symbols;
      return new Promise((resolve) => { freshFinish = resolve; });
    });
    mockGetQuotes.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    renderHook(() => usePrevClose(), { wrapper: makeWrapper(store, queryClient) });
    await waitFor(() => expect(mockGetQuotes).toHaveBeenCalledTimes(1));
    const retiredSignal = mockGetQuotes.mock.calls[0][2]!;
    act(() => { selectNativeAccount("A2"); selectNativeAccount(); });
    await waitFor(() => expect(mockGetMultiQuotes).toHaveBeenCalledTimes(2));
    expect(retiredSignal.aborted).toBe(true);
    await act(async () => { finish({ symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 999, prev_close: 999 } as Quote); });
    expect(store.get(tickAtomFamily("NSE_INDEX:NIFTY"))).toBeNull();
    expect(mockGetQuotes).toHaveBeenCalledTimes(1);
    await act(async () => { freshFinish(freshSymbols.map((s) => ({ ...s, ltp: 102, prev_close: 91 }) as Quote)); });
    await waitFor(() => expect(store.get(tickAtomFamily("NSE_INDEX:NIFTY"))?.prevClose).toBe(91));
  });

  it("refuses non-finite prior closes instead of seeding tick references", async () => {
    mockGetMultiQuotes.mockImplementation((symbols) => Promise.resolve(symbols.map((s) => ({ ...s, ltp: 100, prev_close: Infinity, close: -Infinity }) as Quote)));
    mockGetQuotes.mockResolvedValue({ symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 100, prev_close: Infinity, close: Infinity } as Quote);
    renderHook(() => usePrevClose(), { wrapper: makeWrapper(store, queryClient) });
    await waitFor(() => expect(mockGetQuotes).toHaveBeenCalledTimes(10), { timeout: 2500 });
    await act(async () => { await Promise.resolve(); });
    expect(store.get(tickAtomFamily("NSE_INDEX:NIFTY"))).toBeNull();
  });

});
