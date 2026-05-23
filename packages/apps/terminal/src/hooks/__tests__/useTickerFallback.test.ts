/**
 * Tests for useTickerFallback
 *
 * Strategy:
 *   - Mock getTicker (api.ts) to return deterministic Quote values
 *   - Mock getWsService (websocket.ts) to control subscriptions and avoid real WS
 *   - Mock useConnectionStore (connectionStore.ts) to flip wsConnected
 *   - Use renderHook (react testing library) + Jotai createStore to verify
 *     that atoms are written correctly when WS is disconnected
 *   - Use vi.useFakeTimers to control the 5 s polling interval
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { createStore, Provider } from "jotai";
import React from "react";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import type { Quote, WsInstrument } from "@/types/api";

// --- Mocks ------------------------------------------------------------------

// api.ts — getTicker
const mockGetTicker = vi.fn<(symbol: string, exchange: string) => Promise<Quote>>();

vi.mock("@/services/api", () => ({
  getTicker: (symbol: string, exchange: string) => mockGetTicker(symbol, exchange),
}));

// websocket.ts — getWsService returns an object with getSubscriptions()
const mockGetSubscriptions = vi.fn<(mode: string) => WsInstrument[]>();

vi.mock("@/services/websocket", () => ({
  getWsService: () => ({ getSubscriptions: mockGetSubscriptions }),
}));

// connectionStore — exposes wsConnected as a reactive Zustand value.
// We use a simple module-level variable to simulate state changes.
let _wsConnected = false;

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: (selector: (s: { wsConnected: boolean }) => unknown) => {
    // React-like subscription: re-run selector on every render.
    // For this mock, just return current value based on the selector.
    return selector({ wsConnected: _wsConnected });
  },
}));


// ----------------------------------------------------------------------------

import { useTickerFallback } from "../useTickerFallback";

// Wrap the hook in a custom Jotai Provider so we can inspect the store.
function makeWrapper(store: ReturnType<typeof createStore>) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(Provider, { store }, children);
  };
}

describe("useTickerFallback", () => {
  let store: ReturnType<typeof createStore>;

  beforeEach(() => {
    vi.useFakeTimers();
    store = createStore();
    _wsConnected = false;
    mockGetTicker.mockReset();
    mockGetSubscriptions.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("does nothing when WebSocket is connected", async () => {
    _wsConnected = true;
    mockGetSubscriptions.mockReturnValue([
      { symbol: "NIFTY", exchange: "NSE_INDEX" },
    ]);
    mockGetTicker.mockResolvedValue({
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      ltp: 23000,
      open: 22900,
      high: 23100,
      low: 22800,
      close: 22950,
      volume: 100000,
    });

    renderHook(() => useTickerFallback(), {
      wrapper: makeWrapper(store),
    });

    // Advance time well past one interval
    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });

    expect(mockGetTicker).not.toHaveBeenCalled();
    expect(store.get(tickAtomFamily("NSE_INDEX:NIFTY"))).toBeNull();
  });

  it("does nothing when there are no subscribed instruments", async () => {
    _wsConnected = false;
    mockGetSubscriptions.mockReturnValue([]);

    renderHook(() => useTickerFallback(), {
      wrapper: makeWrapper(store),
    });

    await act(async () => {
      vi.advanceTimersByTime(10_000);
    });

    expect(mockGetTicker).not.toHaveBeenCalled();
  });

  it("polls immediately on mount when WS is disconnected", async () => {
    _wsConnected = false;
    mockGetSubscriptions.mockReturnValue([
      { symbol: "NIFTY", exchange: "NSE_INDEX" },
    ]);
    mockGetTicker.mockResolvedValue({
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      ltp: 23500,
      open: 23400,
      high: 23600,
      low: 23300,
      close: 23450,
      volume: 50000,
    });

    renderHook(() => useTickerFallback(), {
      wrapper: makeWrapper(store),
    });

    // Let the immediate Promise resolve
    await act(async () => {
      await Promise.resolve();
    });

    expect(mockGetTicker).toHaveBeenCalledWith("NIFTY", "NSE_INDEX");
    const tick = store.get(tickAtomFamily("NSE_INDEX:NIFTY"));
    expect(tick?.ltp).toBe(23500);
    expect(tick?.symbol).toBe("NIFTY");
    expect(tick?.exchange).toBe("NSE_INDEX");
  });

  it("writes all optional Quote fields into the WsTick atom", async () => {
    _wsConnected = false;
    mockGetSubscriptions.mockReturnValue([
      { symbol: "BANKNIFTY", exchange: "NSE_INDEX" },
    ]);
    mockGetTicker.mockResolvedValue({
      symbol: "BANKNIFTY",
      exchange: "NSE_INDEX",
      ltp: 51000,
      open: 50900,
      high: 51200,
      low: 50800,
      close: 50950,
      volume: 200000,
      change: 50,
      pct: 0.1,
    });

    renderHook(() => useTickerFallback(), {
      wrapper: makeWrapper(store),
    });

    await act(async () => {
      await Promise.resolve();
    });

    const tick = store.get(tickAtomFamily("NSE_INDEX:BANKNIFTY"));
    expect(tick).toMatchObject({
      symbol: "BANKNIFTY",
      exchange: "NSE_INDEX",
      ltp: 51000,
      open: 50900,
      high: 51200,
      low: 50800,
      close: 50950,
      volume: 200000,
      change: 50,
      pct: 0.1,
    });
  });

  it("polls again after the 5 s interval", async () => {
    _wsConnected = false;
    mockGetSubscriptions.mockReturnValue([
      { symbol: "NIFTY", exchange: "NSE_INDEX" },
    ]);
    mockGetTicker.mockResolvedValue({
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      ltp: 23500,
      open: 23400,
      high: 23600,
      low: 23300,
      close: 23450,
      volume: 50000,
    });

    renderHook(() => useTickerFallback(), {
      wrapper: makeWrapper(store),
    });

    // Immediate poll
    await act(async () => {
      await Promise.resolve();
    });
    expect(mockGetTicker).toHaveBeenCalledTimes(1);

    // Advance past first interval
    await act(async () => {
      vi.advanceTimersByTime(5_001);
      await Promise.resolve();
    });
    expect(mockGetTicker).toHaveBeenCalledTimes(2);

    // Advance past second interval
    await act(async () => {
      vi.advanceTimersByTime(5_001);
      await Promise.resolve();
    });
    expect(mockGetTicker).toHaveBeenCalledTimes(3);
  });

  it("polls multiple subscribed instruments", async () => {
    _wsConnected = false;
    const instruments: WsInstrument[] = [
      { symbol: "NIFTY", exchange: "NSE_INDEX" },
      { symbol: "BANKNIFTY", exchange: "NSE_INDEX" },
      { symbol: "SENSEX", exchange: "BSE_INDEX" },
    ];
    mockGetSubscriptions.mockReturnValue(instruments);

    mockGetTicker.mockImplementation(async (symbol, exchange) => ({
      symbol,
      exchange,
      ltp: symbol === "NIFTY" ? 23500 : symbol === "BANKNIFTY" ? 51000 : 77000,
      open: 0,
      high: 0,
      low: 0,
      close: 0,
      volume: 0,
    }));

    renderHook(() => useTickerFallback(), {
      wrapper: makeWrapper(store),
    });

    await act(async () => {
      await Promise.resolve();
    });

    expect(mockGetTicker).toHaveBeenCalledWith("NIFTY", "NSE_INDEX");
    expect(mockGetTicker).toHaveBeenCalledWith("BANKNIFTY", "NSE_INDEX");
    expect(mockGetTicker).toHaveBeenCalledWith("SENSEX", "BSE_INDEX");

    expect(store.get(tickAtomFamily("NSE_INDEX:NIFTY"))?.ltp).toBe(23500);
    expect(store.get(tickAtomFamily("NSE_INDEX:BANKNIFTY"))?.ltp).toBe(51000);
    expect(store.get(tickAtomFamily("BSE_INDEX:SENSEX"))?.ltp).toBe(77000);
  });

  it("caps polling at MAX_INSTRUMENTS (10) when more are subscribed", async () => {
    _wsConnected = false;
    // Build 15 fake instruments
    const instruments: WsInstrument[] = Array.from({ length: 15 }, (_, i) => ({
      symbol: `SYM${i}`,
      exchange: "NSE",
    }));
    mockGetSubscriptions.mockReturnValue(instruments);
    mockGetTicker.mockResolvedValue({
      symbol: "SYM0",
      exchange: "NSE",
      ltp: 100,
      open: 100,
      high: 100,
      low: 100,
      close: 100,
      volume: 0,
    });

    renderHook(() => useTickerFallback(), {
      wrapper: makeWrapper(store),
    });

    await act(async () => {
      await Promise.resolve();
    });

    // Only the first 10 should be polled
    expect(mockGetTicker).toHaveBeenCalledTimes(10);
    expect(mockGetTicker).toHaveBeenCalledWith("SYM0", "NSE");
    expect(mockGetTicker).toHaveBeenCalledWith("SYM9", "NSE");
    expect(mockGetTicker).not.toHaveBeenCalledWith("SYM10", "NSE");
  });

  it("swallows per-instrument errors and continues polling others", async () => {
    _wsConnected = false;
    mockGetSubscriptions.mockReturnValue([
      { symbol: "NIFTY", exchange: "NSE_INDEX" },
      { symbol: "BANKNIFTY", exchange: "NSE_INDEX" },
    ]);

    // NIFTY fails, BANKNIFTY succeeds
    mockGetTicker.mockImplementation(async (symbol, exchange) => {
      if (symbol === "NIFTY") throw new Error("ticker error");
      return {
        symbol,
        exchange,
        ltp: 51000,
        open: 0,
        high: 0,
        low: 0,
        close: 0,
        volume: 0,
      };
    });

    renderHook(() => useTickerFallback(), {
      wrapper: makeWrapper(store),
    });

    // Should not throw
    await act(async () => {
      await Promise.resolve();
    });

    // NIFTY atom untouched (null), BANKNIFTY updated
    expect(store.get(tickAtomFamily("NSE_INDEX:NIFTY"))).toBeNull();
    expect(store.get(tickAtomFamily("NSE_INDEX:BANKNIFTY"))?.ltp).toBe(51000);
  });

  it("stops polling when WS reconnects", async () => {
    _wsConnected = false;
    mockGetSubscriptions.mockReturnValue([
      { symbol: "NIFTY", exchange: "NSE_INDEX" },
    ]);
    mockGetTicker.mockResolvedValue({
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      ltp: 23500,
      open: 0,
      high: 0,
      low: 0,
      close: 0,
      volume: 0,
    });

    const { rerender } = renderHook(() => useTickerFallback(), {
      wrapper: makeWrapper(store),
    });

    // Immediate poll fires
    await act(async () => {
      await Promise.resolve();
    });
    expect(mockGetTicker).toHaveBeenCalledTimes(1);

    // WS reconnects — simulate by flipping the store value and re-rendering
    _wsConnected = true;
    rerender();

    // Advance well past two intervals — interval should be cleared
    await act(async () => {
      vi.advanceTimersByTime(15_000);
      await Promise.resolve();
    });

    // Still only the single call from before reconnect
    expect(mockGetTicker).toHaveBeenCalledTimes(1);
  });

  it("uses the correct atom key format {exchange}:{symbol}", async () => {
    _wsConnected = false;
    mockGetSubscriptions.mockReturnValue([
      { symbol: "GOLD", exchange: "MCX" },
    ]);
    mockGetTicker.mockResolvedValue({
      symbol: "GOLD",
      exchange: "MCX",
      ltp: 95000,
      open: 94800,
      high: 95200,
      low: 94600,
      close: 94900,
      volume: 5000,
    });

    renderHook(() => useTickerFallback(), {
      wrapper: makeWrapper(store),
    });

    await act(async () => {
      await Promise.resolve();
    });

    // Key must be "MCX:GOLD" — matching the goldAtom convenience alias
    const tick = store.get(tickAtomFamily("MCX:GOLD"));
    expect(tick?.ltp).toBe(95000);

    // Wrong-order key must remain null
    expect(store.get(tickAtomFamily("GOLD:MCX"))).toBeNull();
  });
});
