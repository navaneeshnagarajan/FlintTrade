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
 *
 * Contract under test (beyond atom writes):
 *   - Honest health report: `active`, `lastUpdatedAt`, `isStale`
 *   - Honest cap: prioritised polling + `truncated`/`droppedKeys` reporting
 *   - MCX futures-suffix subscriptions write to display-name atoms
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { createStore, Provider } from "jotai";
import React from "react";
import { tickAtomFamily, selectedSymbolAtom } from "@/atoms/marketAtoms";
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

import {
  useTickerFallback,
  tickerFallbackStatusAtom,
  prioritiseFallbackInstruments,
  MAX_INSTRUMENTS,
  STALE_AFTER_MS,
} from "../useTickerFallback";

// Wrap the hook in a custom Jotai Provider so we can inspect the store.
function makeWrapper(store: ReturnType<typeof createStore>) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(Provider, { store }, children);
  };
}

/** Flush chained microtasks (pollAll → allSettled → status report). */
async function flushMicrotasks(times = 6): Promise<void> {
  for (let i = 0; i < times; i += 1) {
    await Promise.resolve();
  }
}

function makeQuote(symbol: string, exchange: string, ltp: number): Quote {
  return { symbol, exchange, ltp, open: 0, high: 0, low: 0, close: 0, volume: 0 };
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

  it("caps polling at MAX_INSTRUMENTS, prioritising most-recently-subscribed, and reports the truncation", async () => {
    _wsConnected = false;
    // Build 15 fake instruments (subscription order: SYM0 oldest … SYM14 newest)
    const instruments: WsInstrument[] = Array.from({ length: 15 }, (_, i) => ({
      symbol: `SYM${i}`,
      exchange: "NSE",
    }));
    mockGetSubscriptions.mockReturnValue(instruments);
    mockGetTicker.mockImplementation(async (symbol, exchange) =>
      makeQuote(symbol, exchange, 100),
    );

    const { result } = renderHook(() => useTickerFallback(), {
      wrapper: makeWrapper(store),
    });

    await act(async () => {
      await flushMicrotasks();
    });

    // Only MAX_INSTRUMENTS are polled — most recently subscribed first (the
    // newest subscriptions belong to the widgets currently on screen).
    expect(mockGetTicker).toHaveBeenCalledTimes(MAX_INSTRUMENTS);
    expect(mockGetTicker).toHaveBeenCalledWith("SYM14", "NSE");
    expect(mockGetTicker).toHaveBeenCalledWith("SYM5", "NSE");
    expect(mockGetTicker).not.toHaveBeenCalledWith("SYM4", "NSE");
    expect(mockGetTicker).not.toHaveBeenCalledWith("SYM0", "NSE");

    // The cap is reported honestly — never silently swallowed.
    expect(result.current.truncated).toBe(true);
    expect(result.current.polledKeys).toHaveLength(MAX_INSTRUMENTS);
    expect(result.current.droppedKeys).toEqual([
      "NSE:SYM4", "NSE:SYM3", "NSE:SYM2", "NSE:SYM1", "NSE:SYM0",
    ]);
  });

  it("polls the selected instrument first when the cap bites", async () => {
    _wsConnected = false;
    const instruments: WsInstrument[] = Array.from({ length: 15 }, (_, i) => ({
      symbol: `SYM${i}`,
      exchange: "NSE",
    }));
    mockGetSubscriptions.mockReturnValue(instruments);
    mockGetTicker.mockImplementation(async (symbol, exchange) =>
      makeQuote(symbol, exchange, 100),
    );
    // SYM0 is the oldest subscription — MRU ordering alone would drop it.
    store.set(selectedSymbolAtom, { symbol: "SYM0", exchange: "NSE" });

    const { result } = renderHook(() => useTickerFallback(), {
      wrapper: makeWrapper(store),
    });

    await act(async () => {
      await flushMicrotasks();
    });

    // The selected instrument survives the cap — it drives the chart/OrderPad.
    expect(mockGetTicker).toHaveBeenCalledWith("SYM0", "NSE");
    expect(result.current.polledKeys[0]).toBe("NSE:SYM0");
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

  it("routes an MCX futures-suffix subscription to the display-name atom", async () => {
    _wsConnected = false;
    // The WS subscription list carries the FULL nearest-futures symbol.
    mockGetSubscriptions.mockReturnValue([
      { symbol: "GOLD02APR26FUT", exchange: "MCX" },
    ]);
    mockGetTicker.mockResolvedValue(makeQuote("GOLD02APR26FUT", "MCX", 95200));

    renderHook(() => useTickerFallback(), {
      wrapper: makeWrapper(store),
    });

    await act(async () => {
      await flushMicrotasks();
    });

    // Polls the contract the WS was subscribed to…
    expect(mockGetTicker).toHaveBeenCalledWith("GOLD02APR26FUT", "MCX");
    // …but writes to the display-name atom the widgets read (mirrors the
    // WS bridge's futures→display routing). The suffix key stays untouched.
    expect(store.get(tickAtomFamily("MCX:GOLD"))?.ltp).toBe(95200);
    expect(store.get(tickAtomFamily("MCX:GOLD02APR26FUT"))).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Health report — staleness must be visible, never silently lied about
// ---------------------------------------------------------------------------

describe("useTickerFallback — health report", () => {
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

  it("reports inactive and fresh while the WebSocket is connected", () => {
    _wsConnected = true;
    mockGetSubscriptions.mockReturnValue([{ symbol: "NIFTY", exchange: "NSE_INDEX" }]);

    const { result } = renderHook(() => useTickerFallback(), {
      wrapper: makeWrapper(store),
    });

    expect(result.current.active).toBe(false);
    expect(result.current.isStale).toBe(false);
    expect(result.current.truncated).toBe(false);
  });

  it("reports stale until the first successful poll lands, then fresh", async () => {
    _wsConnected = false;
    mockGetSubscriptions.mockReturnValue([{ symbol: "NIFTY", exchange: "NSE_INDEX" }]);

    // First poll hangs forever — no data has arrived yet.
    let resolvePoll: ((q: Quote) => void) | null = null;
    mockGetTicker.mockImplementation(
      () => new Promise<Quote>((resolve) => { resolvePoll = resolve; }),
    );

    const { result } = renderHook(() => useTickerFallback(), {
      wrapper: makeWrapper(store),
    });

    // WS down, nothing fetched yet → the report must say so.
    expect(result.current.active).toBe(true);
    expect(result.current.isStale).toBe(true);
    expect(result.current.lastUpdatedAt).toBeNull();

    // Poll resolves → fresh, with a real timestamp.
    await act(async () => {
      resolvePoll?.(makeQuote("NIFTY", "NSE_INDEX", 23500));
      await flushMicrotasks();
    });

    expect(result.current.isStale).toBe(false);
    expect(result.current.lastUpdatedAt).not.toBeNull();
  });

  it("flags data stale after polls keep failing beyond the stale window", async () => {
    _wsConnected = false;
    mockGetSubscriptions.mockReturnValue([{ symbol: "NIFTY", exchange: "NSE_INDEX" }]);
    mockGetTicker.mockResolvedValue(makeQuote("NIFTY", "NSE_INDEX", 23500));

    const { result } = renderHook(() => useTickerFallback(), {
      wrapper: makeWrapper(store),
    });

    // First poll succeeds → fresh.
    await act(async () => {
      await flushMicrotasks();
    });
    expect(result.current.isStale).toBe(false);

    // Broker REST also goes down — every subsequent poll fails.
    mockGetTicker.mockRejectedValue(new Error("broker down"));

    // One failed cycle (5 s) — within the stale window, still fresh.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_001);
    });
    expect(result.current.isStale).toBe(false);

    // Past STALE_AFTER_MS with no successful write → stale, honestly reported.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(STALE_AFTER_MS);
    });
    expect(result.current.isStale).toBe(true);
    expect(result.current.active).toBe(true);
  });

  it("mirrors the health report into tickerFallbackStatusAtom for any widget", async () => {
    _wsConnected = false;
    mockGetSubscriptions.mockReturnValue([{ symbol: "NIFTY", exchange: "NSE_INDEX" }]);
    mockGetTicker.mockResolvedValue(makeQuote("NIFTY", "NSE_INDEX", 23500));

    const { result } = renderHook(() => useTickerFallback(), {
      wrapper: makeWrapper(store),
    });

    await act(async () => {
      await flushMicrotasks();
    });

    expect(store.get(tickerFallbackStatusAtom)).toEqual(result.current);
    expect(store.get(tickerFallbackStatusAtom).active).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// prioritiseFallbackInstruments — the honest-cap ordering contract
// ---------------------------------------------------------------------------

describe("prioritiseFallbackInstruments", () => {
  const inst = (symbol: string, exchange = "NSE"): WsInstrument => ({ symbol, exchange });

  it("puts the selected instrument first", () => {
    const { polled } = prioritiseFallbackInstruments(
      [inst("A"), inst("B"), inst("C")],
      inst("B"),
    );

    expect(polled[0]).toEqual(inst("B"));
  });

  it("prioritises always-visible index instruments before other symbols", () => {
    const { polled } = prioritiseFallbackInstruments(
      [inst("NIFTY", "NSE_INDEX"), inst("A"), inst("SENSEX", "BSE_INDEX"), inst("B")],
      null,
    );

    expect(polled.slice(0, 2)).toEqual([
      inst("NIFTY", "NSE_INDEX"),
      inst("SENSEX", "BSE_INDEX"),
    ]);
  });

  it("orders the remainder most-recently-subscribed first", () => {
    const { polled } = prioritiseFallbackInstruments(
      [inst("OLD"), inst("MID"), inst("NEW")],
      null,
    );

    expect(polled).toEqual([inst("NEW"), inst("MID"), inst("OLD")]);
  });

  it("splits at the cap and reports the dropped instruments", () => {
    const subscribed = Array.from({ length: 6 }, (_, i) => inst(`S${i}`));

    const { polled, dropped } = prioritiseFallbackInstruments(subscribed, null, 4);

    expect(polled).toHaveLength(4);
    expect(dropped).toEqual([inst("S1"), inst("S0")]);
  });

  it("never duplicates an instrument that matches several priority passes", () => {
    const { polled, dropped } = prioritiseFallbackInstruments(
      [inst("NIFTY", "NSE_INDEX"), inst("A")],
      inst("NIFTY", "NSE_INDEX"),
    );

    expect(polled).toEqual([inst("NIFTY", "NSE_INDEX"), inst("A")]);
    expect(dropped).toHaveLength(0);
  });
});
