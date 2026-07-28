/**
 * Tests for useWsBridge
 *
 * Strategy:
 *   - useWsBridge manages WebSocket lifecycle and routes ticks into Jotai atoms.
 *   - getWsService (websocket.ts) is mocked with a FakeWsService that captures
 *     registered callbacks and exposes helpers to fire them in tests.
 *   - getExpiry (api.ts) is mocked to control MCX futures resolution.
 *   - useConnectionStore is mocked via a module-level variable so tests can
 *     change wsUrl/apiKey without Zustand's persist layer.
 *   - useStore (jotai) is replaced with a real Jotai createStore instance so
 *     atoms can be inspected directly after ticks are processed.
 *   - requestAnimationFrame is replaced with a synchronous fake so tick-batching
 *     logic can be exercised without browser paint timing.
 *
 * Critical business logic verified:
 *   - prevClose preservation: a WS tick must not erase a REST-fetched prevClose.
 *   - MCX routing: ticks keyed to the full futures symbol are routed to the
 *     display-name atom (e.g. MCX:GOLD02APR26FUT → MCX:GOLD).
 *   - RAF batching: multiple ticks for the same instrument in one rAF frame
 *     result in only the latest write reaching the atom.
 *   - Cleanup: RAF handle and subscriptions are cancelled on unmount.
 *
 * Arrange-Act-Assert pattern is applied to every test.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { createStore, Provider } from "jotai";
import React from "react";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import type { WsTick, WsInstrument } from "@/types/api";
import type { WsFailure } from "@/services/websocket";

// ---------------------------------------------------------------------------
// Fake WebSocketService — thin record/replay stand-in for the real class.
// ---------------------------------------------------------------------------

type TickCb = (tick: WsTick) => void;
type StatusCb = (connected: boolean) => void;
type FailureCb = (failure: WsFailure | null) => void;

interface FakeWsService {
  connect: ReturnType<typeof vi.fn>;
  disconnect: ReturnType<typeof vi.fn>;
  subscribe: ReturnType<typeof vi.fn>;
  unsubscribe: ReturnType<typeof vi.fn>;
  onTick: ReturnType<typeof vi.fn>;
  onStatus: ReturnType<typeof vi.fn>;
  onFailure: ReturnType<typeof vi.fn>;
  failure: WsFailure | null;
  // Test helpers — fire registered callbacks
  _fireTick: (tick: WsTick) => void;
  _fireStatus: (connected: boolean) => void;
  _fireFailure: (failure: WsFailure | null) => void;
  // Registered unsub functions returned by onTick/onStatus/onFailure
  _tickUnsub: ReturnType<typeof vi.fn>;
  _statusUnsub: ReturnType<typeof vi.fn>;
  _failureUnsub: ReturnType<typeof vi.fn>;
}

function makeFakeWsService(): FakeWsService {
  const tickCallbacks = new Set<TickCb>();
  const statusCallbacks = new Set<StatusCb>();
  const failureCallbacks = new Set<FailureCb>();
  const tickUnsub = vi.fn(() => { tickCallbacks.clear(); });
  const statusUnsub = vi.fn(() => { statusCallbacks.clear(); });
  const failureUnsub = vi.fn(() => { failureCallbacks.clear(); });

  return {
    connect: vi.fn(),
    disconnect: vi.fn(),
    subscribe: vi.fn(),
    unsubscribe: vi.fn(),
    onTick: vi.fn((cb: TickCb) => {
      tickCallbacks.add(cb);
      return tickUnsub;
    }),
    onStatus: vi.fn((cb: StatusCb) => {
      statusCallbacks.add(cb);
      return statusUnsub;
    }),
    onFailure: vi.fn((cb: FailureCb) => {
      failureCallbacks.add(cb);
      return failureUnsub;
    }),
    failure: null,
    _fireTick: (tick: WsTick) => tickCallbacks.forEach((cb) => cb(tick)),
    _fireStatus: (connected: boolean) => statusCallbacks.forEach((cb) => cb(connected)),
    _fireFailure: (failure: WsFailure | null) => failureCallbacks.forEach((cb) => cb(failure)),
    _tickUnsub: tickUnsub,
    _statusUnsub: statusUnsub,
    _failureUnsub: failureUnsub,
  };
}

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

let fakeWs: FakeWsService | null = null;

// Controls whether getWsService returns a service or null
let _wsUrl = "ws://127.0.0.1:8765";
let _apiKey = "test-api-key";

vi.mock("@/services/websocket", () => ({
  getWsService: (url?: string, _apiKey?: string) => {
    if (!url) return null;
    return fakeWs;
  },
}));

// connectionStore — module-level variables simulate Zustand state
let _setWsConnectedFn = vi.fn<(connected: boolean) => void>();
let _setWsFailureFn = vi.fn<(failure: unknown) => void>();

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: (selector: (s: {
    setWsConnected: typeof _setWsConnectedFn;
    setWsFailure: typeof _setWsFailureFn;
    apiKey: string;
    wsUrl: string;
  }) => unknown) =>
    selector({
      setWsConnected: _setWsConnectedFn,
      setWsFailure: _setWsFailureFn,
      apiKey: _apiKey,
      wsUrl: _wsUrl,
    }),
}));

// getExpiry — used for MCX futures resolution
const mockGetExpiry = vi.fn<(symbol: string, exchange: string, type: string) => Promise<unknown>>();

vi.mock("@/services/api", () => ({
  getExpiry: (symbol: string, exchange: string, type: string) =>
    mockGetExpiry(symbol, exchange, type),
}));

// jotai useStore — replace with real Jotai createStore so atoms can be inspected
let _jotaiStore: ReturnType<typeof createStore>;

vi.mock("jotai", async (importOriginal) => {
  const actual = await importOriginal<typeof import("jotai")>();
  return {
    ...actual,
    useStore: () => _jotaiStore,
  };
});

// ---------------------------------------------------------------------------
// Hook import — after mocks.
// ---------------------------------------------------------------------------

import { useWsBridge, useTickSubscription } from "../useWsBridge";
import { selectedSymbolAtom } from "@/atoms/marketAtoms";

// ---------------------------------------------------------------------------
// rAF stub — synchronous flush for deterministic tests
// ---------------------------------------------------------------------------

let rafCallbacks: FrameRequestCallback[] = [];
let rafIdCounter = 1;

function installSyncRaf() {
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    const id = rafIdCounter++;
    rafCallbacks.push(cb);
    return id;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => {
    // Remove all pending callbacks (simplification: only one pending per test)
    rafCallbacks = rafCallbacks.filter((_, i) => i !== (id - 1));
  });
}

/**
 * Flush all pending rAF callbacks synchronously.
 * The real hook schedules one rAF per tick batch.
 */
function flushRaf() {
  const pending = [...rafCallbacks];
  rafCallbacks = [];
  rafIdCounter = 1;
  pending.forEach((cb) => cb(0));
}

// ---------------------------------------------------------------------------
// React wrapper — provides the Jotai store used by the hook
// ---------------------------------------------------------------------------

function makeWrapper(store: ReturnType<typeof createStore>) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(Provider, { store }, children);
  };
}

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  _jotaiStore = createStore();
  fakeWs = makeFakeWsService();
  _wsUrl = "ws://127.0.0.1:8765";
  _apiKey = "test-api-key";
  _setWsConnectedFn = vi.fn();
  _setWsFailureFn = vi.fn();
  rafCallbacks = [];
  rafIdCounter = 1;
  mockGetExpiry.mockReset();
  installSyncRaf();

  // Default: getExpiry resolves with empty expiry so MCX resolution completes
  // without blocking but subscribes nothing (simpler baseline for most tests).
  mockGetExpiry.mockResolvedValue({ expiry: [] });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  rafCallbacks = [];
});

// ---------------------------------------------------------------------------
// Connection behaviour
// ---------------------------------------------------------------------------

describe("useWsBridge — connection lifecycle", () => {
  it("calls ws.connect() when wsUrl is provided", () => {
    // Arrange — wsUrl is set (default)

    // Act
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    // Assert
    expect(fakeWs!.connect).toHaveBeenCalledOnce();
  });

  it("does not call ws.connect() when wsUrl is empty", () => {
    // Arrange
    _wsUrl = "";

    // Act
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    // Assert — guard clause: empty wsUrl must short-circuit the effect
    expect(fakeWs!.connect).not.toHaveBeenCalled();
  });

  it("does not connect when live market data is disabled", () => {
    renderHook(() => useWsBridge(false), { wrapper: makeWrapper(_jotaiStore) });

    expect(fakeWs!.connect).not.toHaveBeenCalled();
    expect(fakeWs!.onTick).not.toHaveBeenCalled();
    expect(fakeWs!.onStatus).not.toHaveBeenCalled();
  });

  it("does not connect without a browser-held OpenAlgo API key", () => {
    _apiKey = "";

    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    expect(fakeWs!.connect).not.toHaveBeenCalled();
    expect(fakeWs!.onTick).not.toHaveBeenCalled();
    expect(fakeWs!.onStatus).not.toHaveBeenCalled();
  });

  it("disconnects its owned socket when the bridge is disabled", () => {
    const { rerender } = renderHook(
      ({ enabled }) => useWsBridge(enabled),
      { initialProps: { enabled: true }, wrapper: makeWrapper(_jotaiStore) },
    );

    rerender({ enabled: false });

    expect(fakeWs!.disconnect).toHaveBeenCalledOnce();
  });

  it("registers onTick and onStatus handlers on mount", () => {
    // Arrange + Act
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    // Assert
    expect(fakeWs!.onTick).toHaveBeenCalledOnce();
    expect(fakeWs!.onStatus).toHaveBeenCalledOnce();
  });

  it("calls setWsConnected(true) when the status callback fires with true", () => {
    // Arrange
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    // Act
    act(() => { fakeWs!._fireStatus(true); });

    // Assert
    expect(_setWsConnectedFn).toHaveBeenCalledWith(true);
  });

  it("calls setWsConnected(false) when the status callback fires with false", () => {
    // Arrange
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    // Act
    act(() => { fakeWs!._fireStatus(false); });

    // Assert
    expect(_setWsConnectedFn).toHaveBeenCalledWith(false);
  });
});

// ---------------------------------------------------------------------------
// Failure pipe — WS failure state mirrored into the connection store
// ---------------------------------------------------------------------------

describe("useWsBridge — failure pipe to connection store", () => {
  const AUTH_FAILURE: WsFailure = {
    kind: "auth",
    reason: "Invalid API key",
    attempts: 3,
    fatal: true,
  };

  it("registers an onFailure handler and seeds the store with the current failure", () => {
    // Arrange — the service latched an auth failure BEFORE the hook mounted
    fakeWs!.failure = AUTH_FAILURE;

    // Act
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    // Assert — handler registered, and the pre-existing failure was seeded
    expect(fakeWs!.onFailure).toHaveBeenCalledOnce();
    expect(_setWsFailureFn).toHaveBeenCalledWith(AUTH_FAILURE);
  });

  it("pipes a failure event into setWsFailure", () => {
    // Arrange
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });
    _setWsFailureFn.mockClear();

    // Act
    act(() => { fakeWs!._fireFailure(AUTH_FAILURE); });

    // Assert
    expect(_setWsFailureFn).toHaveBeenCalledWith(AUTH_FAILURE);
  });

  it("pipes the null (cleared) failure state into setWsFailure", () => {
    // Arrange
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });
    act(() => { fakeWs!._fireFailure(AUTH_FAILURE); });
    _setWsFailureFn.mockClear();

    // Act — auth succeeds, service clears the failure
    act(() => { fakeWs!._fireFailure(null); });

    // Assert
    expect(_setWsFailureFn).toHaveBeenCalledWith(null);
  });

  it("unsubscribes the failure handler on unmount", () => {
    // Arrange
    const { unmount } = renderHook(() => useWsBridge(), {
      wrapper: makeWrapper(_jotaiStore),
    });

    // Act
    unmount();

    // Assert
    expect(fakeWs!._failureUnsub).toHaveBeenCalledOnce();
  });
});

// ---------------------------------------------------------------------------
// INDEX_INSTRUMENTS subscription
// ---------------------------------------------------------------------------

describe("useWsBridge — INDEX_INSTRUMENTS subscription on connect", () => {
  it("subscribes to all four index instruments when status becomes connected", () => {
    // Arrange
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    // Act — simulate successful WebSocket connection
    act(() => { fakeWs!._fireStatus(true); });

    // Assert — ws.subscribe was called (MCX resolution also triggers subscribe
    // asynchronously, so check the first synchronous call for indices)
    expect(fakeWs!.subscribe).toHaveBeenCalledWith(
      expect.arrayContaining<WsInstrument>([
        { symbol: "NIFTY", exchange: "NSE_INDEX" },
        { symbol: "BANKNIFTY", exchange: "NSE_INDEX" },
        { symbol: "SENSEX", exchange: "BSE_INDEX" },
        { symbol: "INDIAVIX", exchange: "NSE_INDEX" },
      ]),
      "ltp",
    );
  });

  it("subscribes to exactly the canonical INDEX_INSTRUMENTS (no extras)", () => {
    // Arrange
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    // Act
    act(() => { fakeWs!._fireStatus(true); });

    // Retrieve the first subscribe call (synchronous index subscription)
    const indexCall = fakeWs!.subscribe.mock.calls.find(
      (c) => Array.isArray(c[0]) && (c[0] as WsInstrument[]).some(
        (i) => i.exchange === "NSE_INDEX" || i.exchange === "BSE_INDEX"
      )
    );

    // Assert — the index subscription is exactly the canonical set. FINNIFTY
    // and NIFTYIT joined it because the Index Strip and the Market Overview
    // indices tab RENDER cards for them; unsubscribed, those cards sat on
    // "Awaiting tick" forever.
    expect(indexCall).toBeDefined();
    const subscribed = (indexCall![0] as WsInstrument[]).map((i) => i.symbol).sort();
    expect(subscribed).toEqual(
      ["BANKNIFTY", "FINNIFTY", "INDIAVIX", "NIFTY", "NIFTYIT", "SENSEX"],
    );
  });

  it("does not subscribe when status fires as false (disconnection)", async () => {
    // Arrange
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    // Act — simulate disconnection (not reconnection)
    act(() => { fakeWs!._fireStatus(false); });

    // Let any async MCX resolution settle
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });

    // Assert — no subscription call when disconnected
    expect(fakeWs!.subscribe).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// Tick routing into Jotai atoms
// ---------------------------------------------------------------------------

describe("useWsBridge — tick routing to atoms", () => {
  it("writes a tick into the correct atom key {exchange}:{symbol}", () => {
    // Arrange
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    const tick: WsTick = { symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23500 };

    // Act — deliver tick and flush the rAF batch
    act(() => {
      fakeWs!._fireTick(tick);
      flushRaf();
    });

    // Assert
    const stored = _jotaiStore.get(tickAtomFamily("NSE_INDEX:NIFTY"));
    expect(stored).not.toBeNull();
    expect(stored!.ltp).toBe(23500);
    expect(stored!.symbol).toBe("NIFTY");
    expect(stored!.exchange).toBe("NSE_INDEX");
  });

  it("routes multiple ticks for different instruments to their respective atoms", () => {
    // Arrange
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    const niftyTick: WsTick = { symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23500 };
    const sensexTick: WsTick = { symbol: "SENSEX", exchange: "BSE_INDEX", ltp: 77000 };

    // Act
    act(() => {
      fakeWs!._fireTick(niftyTick);
      fakeWs!._fireTick(sensexTick);
      flushRaf();
    });

    // Assert — each instrument lands in its own atom
    expect(_jotaiStore.get(tickAtomFamily("NSE_INDEX:NIFTY"))?.ltp).toBe(23500);
    expect(_jotaiStore.get(tickAtomFamily("BSE_INDEX:SENSEX"))?.ltp).toBe(77000);
  });

  it("does not write to the atom until the rAF callback fires", () => {
    // Arrange
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    // Act — deliver tick but do NOT flush rAF
    act(() => {
      fakeWs!._fireTick({ symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23500 });
      // Deliberately NOT calling flushRaf()
    });

    // Assert — atom still null (rAF has not fired)
    expect(_jotaiStore.get(tickAtomFamily("NSE_INDEX:NIFTY"))).toBeNull();
  });

  it("writes optional tick fields (open/high/low) to the atom", () => {
    // Arrange
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    const tick: WsTick = {
      symbol: "BANKNIFTY",
      exchange: "NSE_INDEX",
      ltp: 51000,
      open: 50500,
      high: 51200,
      low: 50300,
    };

    // Act
    act(() => {
      fakeWs!._fireTick(tick);
      flushRaf();
    });

    // Assert
    const stored = _jotaiStore.get(tickAtomFamily("NSE_INDEX:BANKNIFTY"));
    expect(stored?.open).toBe(50500);
    expect(stored?.high).toBe(51200);
    expect(stored?.low).toBe(50300);
  });
});

// ---------------------------------------------------------------------------
// prevClose preservation — the critical business logic
// ---------------------------------------------------------------------------

describe("useWsBridge — prevClose preservation", () => {
  it("preserves prevClose from the existing atom when a WS tick arrives", () => {
    // Arrange — pre-seed the atom with a prevClose (as usePrevClose would do)
    _jotaiStore.set(tickAtomFamily("NSE_INDEX:NIFTY"), {
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      ltp: 23490,
      prevClose: 23150, // REST-fetched; WS LTP mode does not send this
    });

    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    // Act — WS tick arrives without prevClose
    const wsTick: WsTick = { symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23510 };
    act(() => {
      fakeWs!._fireTick(wsTick);
      flushRaf();
    });

    // Assert — prevClose is preserved from the existing atom
    const stored = _jotaiStore.get(tickAtomFamily("NSE_INDEX:NIFTY"));
    expect(stored!.ltp).toBe(23510);       // updated from WS
    expect(stored!.prevClose).toBe(23150); // preserved — must NOT be erased
  });

  it("does not set prevClose when the existing atom has no prevClose", () => {
    // Arrange — atom exists but without prevClose (e.g. never fetched from REST)
    _jotaiStore.set(tickAtomFamily("NSE_INDEX:NIFTY"), {
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      ltp: 23490,
      // no prevClose field
    });

    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    // Act
    act(() => {
      fakeWs!._fireTick({ symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23510 });
      flushRaf();
    });

    // Assert — prevClose stays absent (undefined), ltp is updated
    const stored = _jotaiStore.get(tickAtomFamily("NSE_INDEX:NIFTY"));
    expect(stored!.ltp).toBe(23510);
    expect(stored!.prevClose).toBeUndefined();
  });

  it("preserves prevClose when the atom starts at null (first WS tick, no REST yet)", () => {
    // Arrange — atom is null (no REST data fetched yet, no prior WS tick)
    // This is the normal cold-start path for a newly subscribed instrument.
    expect(_jotaiStore.get(tickAtomFamily("NSE_INDEX:NIFTY"))).toBeNull();

    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    // Act
    act(() => {
      fakeWs!._fireTick({ symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23500 });
      flushRaf();
    });

    // Assert — tick is written, prevClose is absent (atom was null, no prevClose to merge)
    const stored = _jotaiStore.get(tickAtomFamily("NSE_INDEX:NIFTY"));
    expect(stored).not.toBeNull();
    expect(stored!.ltp).toBe(23500);
    expect(stored!.prevClose).toBeUndefined();
  });

  it("preserves prevClose when prevClose is zero (explicit zero is a valid price)", () => {
    // Arrange — prevClose of 0 is a valid (unusual) value; must not be treated as falsy
    _jotaiStore.set(tickAtomFamily("NSE_INDEX:NIFTY"), {
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      ltp: 100,
      prevClose: 0,
    });

    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    // Act
    act(() => {
      fakeWs!._fireTick({ symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 105 });
      flushRaf();
    });

    // Assert — the hook checks `existing?.prevClose != null` (not falsy check),
    // so prevClose: 0 must be preserved
    const stored = _jotaiStore.get(tickAtomFamily("NSE_INDEX:NIFTY"));
    expect(stored!.prevClose).toBe(0);
  });

  it("preserves prevClose across multiple sequential ticks for the same instrument", () => {
    // Arrange
    _jotaiStore.set(tickAtomFamily("NSE_INDEX:NIFTY"), {
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      ltp: 23490,
      prevClose: 23150,
    });

    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    // Act — three ticks in separate rAF frames
    act(() => {
      fakeWs!._fireTick({ symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23510 });
      flushRaf();
    });
    act(() => {
      fakeWs!._fireTick({ symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23520 });
      flushRaf();
    });
    act(() => {
      fakeWs!._fireTick({ symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23530 });
      flushRaf();
    });

    // Assert — prevClose survives all three updates
    const stored = _jotaiStore.get(tickAtomFamily("NSE_INDEX:NIFTY"));
    expect(stored!.ltp).toBe(23530);
    expect(stored!.prevClose).toBe(23150);
  });
});

// ---------------------------------------------------------------------------
// rAF batching
// ---------------------------------------------------------------------------

describe("useWsBridge — RAF tick batching", () => {
  it("deduplicates multiple ticks for the same instrument in one rAF frame", () => {
    // Arrange
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    // Act — three NIFTY ticks arrive before a single rAF fires
    act(() => {
      fakeWs!._fireTick({ symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23500 });
      fakeWs!._fireTick({ symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23510 });
      fakeWs!._fireTick({ symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23520 });
      flushRaf();
    });

    // Assert — only the last tick (23520) is written to the atom
    const stored = _jotaiStore.get(tickAtomFamily("NSE_INDEX:NIFTY"));
    expect(stored!.ltp).toBe(23520);
  });

  it("schedules exactly one rAF even when multiple ticks arrive before it fires", () => {
    // Arrange
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    const rafSpy = vi.spyOn(globalThis, "requestAnimationFrame");

    // Act — deliver three ticks before flush
    act(() => {
      fakeWs!._fireTick({ symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23500 });
      fakeWs!._fireTick({ symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23510 });
      fakeWs!._fireTick({ symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23520 });
    });

    // Assert — only one rAF was scheduled for all three ticks
    expect(rafSpy).toHaveBeenCalledTimes(1);

    // Cleanup
    act(() => { flushRaf(); });
  });

  it("allows a new rAF to be scheduled after the previous one is flushed", () => {
    // Arrange
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    const rafSpy = vi.spyOn(globalThis, "requestAnimationFrame");

    // Act — first batch
    act(() => {
      fakeWs!._fireTick({ symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23500 });
      flushRaf();
    });

    // Second batch
    act(() => {
      fakeWs!._fireTick({ symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23520 });
      flushRaf();
    });

    // Assert — two separate rAFs were scheduled (one per batch)
    expect(rafSpy).toHaveBeenCalledTimes(2);
    expect(_jotaiStore.get(tickAtomFamily("NSE_INDEX:NIFTY"))?.ltp).toBe(23520);
  });
});

// ---------------------------------------------------------------------------
// Cleanup on unmount
// ---------------------------------------------------------------------------

describe("useWsBridge — cleanup on unmount", () => {
  it("calls the tick unsubscribe function returned by onTick", () => {
    // Arrange
    const { unmount } = renderHook(() => useWsBridge(), {
      wrapper: makeWrapper(_jotaiStore),
    });

    // Act
    unmount();

    // Assert
    expect(fakeWs!._tickUnsub).toHaveBeenCalledOnce();
  });

  it("calls the status unsubscribe function returned by onStatus", () => {
    // Arrange
    const { unmount } = renderHook(() => useWsBridge(), {
      wrapper: makeWrapper(_jotaiStore),
    });

    // Act
    unmount();

    // Assert
    expect(fakeWs!._statusUnsub).toHaveBeenCalledOnce();
  });

  it("cancels a pending rAF when the hook unmounts", () => {
    // Arrange — deliver a tick to schedule a rAF, then unmount before flush
    renderHook(
      () => useWsBridge(),
      { wrapper: makeWrapper(_jotaiStore) },
    ).unmount;

    const { unmount } = renderHook(() => useWsBridge(), {
      wrapper: makeWrapper(_jotaiStore),
    });

    const cancelSpy = vi.spyOn(globalThis, "cancelAnimationFrame");

    // Deliver tick — this schedules a rAF
    act(() => {
      fakeWs!._fireTick({ symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23500 });
    });

    // Pending rAF exists — now unmount before it fires
    act(() => { unmount(); });

    // Assert — cancelAnimationFrame was called to discard the pending flush
    expect(cancelSpy).toHaveBeenCalled();
  });

  it("does not write a pending tick to the atom after unmount", () => {
    // Arrange — deliver a tick but unmount before rAF fires
    const { unmount } = renderHook(() => useWsBridge(), {
      wrapper: makeWrapper(_jotaiStore),
    });

    act(() => {
      fakeWs!._fireTick({ symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23500 });
    });

    // Atom still null (rAF not flushed yet)
    expect(_jotaiStore.get(tickAtomFamily("NSE_INDEX:NIFTY"))).toBeNull();

    // Act — unmount then flush (simulates rAF firing after React tree is gone)
    act(() => { unmount(); });
    act(() => { flushRaf(); }); // rAF was cancelled by cleanup, so this is a no-op

    // Assert — atom must remain null; stale tick must NOT have been written
    expect(_jotaiStore.get(tickAtomFamily("NSE_INDEX:NIFTY"))).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// MCX futures routing
// ---------------------------------------------------------------------------

describe("useWsBridge — MCX futures tick routing", () => {
  it("subscribes to resolved MCX futures instruments when expiry is available", async () => {
    // Arrange — GOLD resolves to GOLD02APR26FUT
    mockGetExpiry.mockImplementation(async (name) => {
      if (name === "GOLD") return { expiry: ["02-APR-26"] };
      return { expiry: [] };
    });

    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    // Trigger the onStatus(true) path which starts MCX resolution
    act(() => { fakeWs!._fireStatus(true); });

    // Wait for the async MCX resolution to complete
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });

    // Assert — ws.subscribe was called with the resolved GOLD futures symbol
    const mcxCall = fakeWs!.subscribe.mock.calls.find(
      (c) => Array.isArray(c[0]) && (c[0] as WsInstrument[]).some(
        (i) => i.exchange === "MCX"
      )
    );
    expect(mcxCall).toBeDefined();

    const mcxInstruments = mcxCall![0] as WsInstrument[];
    const goldSub = mcxInstruments.find((i) => i.symbol === "GOLD02APR26FUT");
    expect(goldSub).toBeDefined();
    expect(goldSub!.exchange).toBe("MCX");
  });

  it("routes a futures tick to the display-name atom (GOLD02APR26FUT → MCX:GOLD)", async () => {
    // Arrange — GOLD resolves to GOLD02APR26FUT
    mockGetExpiry.mockImplementation(async (name) => {
      if (name === "GOLD") return { expiry: ["02-APR-26"] };
      return { expiry: [] };
    });

    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    act(() => { fakeWs!._fireStatus(true); });

    // Wait for MCX resolution and futuresMap population
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });

    // Act — deliver a tick keyed to the full futures symbol
    const futuresTick: WsTick = {
      symbol: "GOLD02APR26FUT",
      exchange: "MCX",
      ltp: 95000,
    };
    act(() => {
      fakeWs!._fireTick(futuresTick);
      flushRaf();
    });

    // Assert — tick lands in the display-name atom, not the full futures key
    const goldAtom = _jotaiStore.get(tickAtomFamily("MCX:GOLD"));
    expect(goldAtom).not.toBeNull();
    expect(goldAtom!.ltp).toBe(95000);

    // The full futures key must remain null (routing happened)
    expect(_jotaiStore.get(tickAtomFamily("MCX:GOLD02APR26FUT"))).toBeNull();
  });

  it("does not subscribe to MCX when all expiry lookups return empty", async () => {
    // Arrange — all commodities return empty expiry
    mockGetExpiry.mockResolvedValue({ expiry: [] });

    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });
    act(() => { fakeWs!._fireStatus(true); });

    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });

    // Assert — ws.subscribe called only once for indices (no MCX call)
    const mcxCall = fakeWs!.subscribe.mock.calls.find(
      (c) => Array.isArray(c[0]) && (c[0] as WsInstrument[]).some(
        (i) => i.exchange === "MCX"
      )
    );
    expect(mcxCall).toBeUndefined();
  });

  it("continues connecting even when all MCX expiry lookups reject", async () => {
    // Arrange — getExpiry throws for all commodities
    mockGetExpiry.mockRejectedValue(new Error("MCX data unavailable"));

    // Act — should not throw
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    await expect(
      act(async () => {
        fakeWs!._fireStatus(true);
        await new Promise((r) => setTimeout(r, 0));
      })
    ).resolves.not.toThrow();

    // Assert — indices subscription still happened
    expect(fakeWs!.subscribe).toHaveBeenCalledWith(
      expect.arrayContaining<WsInstrument>([
        { symbol: "NIFTY", exchange: "NSE_INDEX" },
      ]),
      "ltp",
    );
  });
});

// ---------------------------------------------------------------------------
// wsUrl empty guard
// ---------------------------------------------------------------------------

describe("useWsBridge — wsUrl guard", () => {
  it("registers no tick/status handlers when wsUrl is empty (no service created)", () => {
    // Arrange
    _wsUrl = "";

    // Act
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    // Assert — no handlers registered because the effect returns early
    expect(fakeWs!.onTick).not.toHaveBeenCalled();
    expect(fakeWs!.onStatus).not.toHaveBeenCalled();
  });

  it("does not throw when wsUrl becomes available after being empty", () => {
    // Arrange — start with empty wsUrl
    _wsUrl = "";
    const { rerender } = renderHook(() => useWsBridge(), {
      wrapper: makeWrapper(_jotaiStore),
    });

    // Act — wsUrl populated on re-render
    _wsUrl = "ws://127.0.0.1:8765";

    expect(() => rerender()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// Selected-instrument subscription — feeds tickAtomFamily for the active
// instrument (OrderPad fund-mode sizing, OrderLadder atom fallback).
// ---------------------------------------------------------------------------

describe("useWsBridge — selected-instrument subscription", () => {
  it("subscribes independently per FDC3 channel (not just the red/legacy selection)", async () => {
    // Arrange
    const { channelInstrumentAtoms } = await import("@/services/fdc3/channels");
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    // Act — instruments land on two non-red channels
    act(() => {
      _jotaiStore.set(channelInstrumentAtoms["fdc3.channel.green"], { symbol: "TCS", exchange: "NSE" });
      _jotaiStore.set(channelInstrumentAtoms["fdc3.channel.blue"], { symbol: "GOLD", exchange: "MCX" });
    });

    // Assert — one live subscription per channel
    expect(fakeWs!.subscribe).toHaveBeenCalledWith([{ symbol: "TCS", exchange: "NSE" }], "ltp");
    expect(fakeWs!.subscribe).toHaveBeenCalledWith([{ symbol: "GOLD", exchange: "MCX" }], "ltp");

    // And clearing one channel unsubscribes only that channel's instrument.
    act(() => {
      _jotaiStore.set(channelInstrumentAtoms["fdc3.channel.blue"], null);
    });
    expect(fakeWs!.unsubscribe).toHaveBeenCalledWith([{ symbol: "GOLD", exchange: "MCX" }], "ltp");
    expect(fakeWs!.unsubscribe).not.toHaveBeenCalledWith([{ symbol: "TCS", exchange: "NSE" }], "ltp");
  });

  it("subscribes to a selection that existed before the bridge mounted", () => {
    // Arrange — a watchlist click happened before the bridge (re)mounted
    _jotaiStore.set(selectedSymbolAtom, { symbol: "RELIANCE", exchange: "NSE" });

    // Act
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });

    // Assert
    expect(fakeWs!.subscribe).toHaveBeenCalledWith(
      [{ symbol: "RELIANCE", exchange: "NSE" }],
      "ltp",
    );
  });

  it("subscribes when the selection atom is set after mount", () => {
    // Arrange
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });
    expect(fakeWs!.subscribe).not.toHaveBeenCalled();

    // Act — watchlist row click
    act(() => {
      _jotaiStore.set(selectedSymbolAtom, { symbol: "TCS", exchange: "NSE" });
    });

    // Assert
    expect(fakeWs!.subscribe).toHaveBeenCalledWith(
      [{ symbol: "TCS", exchange: "NSE" }],
      "ltp",
    );
  });

  it("moves the subscription when the selection changes", () => {
    // Arrange
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });
    act(() => {
      _jotaiStore.set(selectedSymbolAtom, { symbol: "TCS", exchange: "NSE" });
    });

    // Act — select a different instrument
    act(() => {
      _jotaiStore.set(selectedSymbolAtom, { symbol: "INFY", exchange: "NSE" });
    });

    // Assert — old released, new acquired
    expect(fakeWs!.unsubscribe).toHaveBeenCalledWith(
      [{ symbol: "TCS", exchange: "NSE" }],
      "ltp",
    );
    expect(fakeWs!.subscribe).toHaveBeenCalledWith(
      [{ symbol: "INFY", exchange: "NSE" }],
      "ltp",
    );
  });

  it("does not resubscribe when the same instrument is selected again", () => {
    // Arrange
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });
    act(() => {
      _jotaiStore.set(selectedSymbolAtom, { symbol: "TCS", exchange: "NSE" });
    });

    // Act — same instrument, new object identity (fresh click on the same row)
    act(() => {
      _jotaiStore.set(selectedSymbolAtom, { symbol: "TCS", exchange: "NSE" });
    });

    // Assert — exactly one subscribe, zero unsubscribes
    expect(fakeWs!.subscribe).toHaveBeenCalledTimes(1);
    expect(fakeWs!.unsubscribe).not.toHaveBeenCalled();
  });

  it("releases the selected-instrument subscription on unmount", () => {
    // Arrange
    const { unmount } = renderHook(() => useWsBridge(), {
      wrapper: makeWrapper(_jotaiStore),
    });
    act(() => {
      _jotaiStore.set(selectedSymbolAtom, { symbol: "TCS", exchange: "NSE" });
    });

    // Act
    unmount();

    // Assert
    expect(fakeWs!.unsubscribe).toHaveBeenCalledWith(
      [{ symbol: "TCS", exchange: "NSE" }],
      "ltp",
    );
  });

  it("releases the subscription when the selection is cleared", () => {
    // Arrange
    renderHook(() => useWsBridge(), { wrapper: makeWrapper(_jotaiStore) });
    act(() => {
      _jotaiStore.set(selectedSymbolAtom, { symbol: "TCS", exchange: "NSE" });
    });

    // Act
    act(() => {
      _jotaiStore.set(selectedSymbolAtom, null);
    });

    // Assert — released, and nothing new subscribed
    expect(fakeWs!.unsubscribe).toHaveBeenCalledWith(
      [{ symbol: "TCS", exchange: "NSE" }],
      "ltp",
    );
    expect(fakeWs!.subscribe).toHaveBeenCalledTimes(1);
  });
});

// ---------------------------------------------------------------------------
// useTickSubscription — declarative per-widget tick interest
// ---------------------------------------------------------------------------

describe("useTickSubscription", () => {
  it("subscribes to the instrument on mount (ltp by default)", () => {
    // Act
    renderHook(() => useTickSubscription("RELIANCE", "NSE"), {
      wrapper: makeWrapper(_jotaiStore),
    });

    // Assert
    expect(fakeWs!.subscribe).toHaveBeenCalledWith(
      [{ symbol: "RELIANCE", exchange: "NSE" }],
      "ltp",
    );
  });

  it("passes an explicit mode through to the service", () => {
    // Act
    renderHook(() => useTickSubscription("NIFTY24JULFUT", "NFO", "quote"), {
      wrapper: makeWrapper(_jotaiStore),
    });

    // Assert
    expect(fakeWs!.subscribe).toHaveBeenCalledWith(
      [{ symbol: "NIFTY24JULFUT", exchange: "NFO" }],
      "quote",
    );
  });

  it("unsubscribes on unmount (balanced ref-count release)", () => {
    // Arrange
    const { unmount } = renderHook(() => useTickSubscription("RELIANCE", "NSE"), {
      wrapper: makeWrapper(_jotaiStore),
    });

    // Act
    unmount();

    // Assert
    expect(fakeWs!.unsubscribe).toHaveBeenCalledWith(
      [{ symbol: "RELIANCE", exchange: "NSE" }],
      "ltp",
    );
  });

  it("re-subscribes when the instrument changes", () => {
    // Arrange
    const { rerender } = renderHook(
      ({ symbol }: { symbol: string }) => useTickSubscription(symbol, "NSE"),
      { wrapper: makeWrapper(_jotaiStore), initialProps: { symbol: "TCS" } },
    );

    // Act
    rerender({ symbol: "INFY" });

    // Assert — old released, new acquired
    expect(fakeWs!.unsubscribe).toHaveBeenCalledWith(
      [{ symbol: "TCS", exchange: "NSE" }],
      "ltp",
    );
    expect(fakeWs!.subscribe).toHaveBeenCalledWith(
      [{ symbol: "INFY", exchange: "NSE" }],
      "ltp",
    );
  });

  it("is a no-op when symbol or exchange is missing", () => {
    // Act
    renderHook(() => useTickSubscription(null, "NSE"), {
      wrapper: makeWrapper(_jotaiStore),
    });
    renderHook(() => useTickSubscription("TCS", ""), {
      wrapper: makeWrapper(_jotaiStore),
    });

    // Assert
    expect(fakeWs!.subscribe).not.toHaveBeenCalled();
    expect(fakeWs!.unsubscribe).not.toHaveBeenCalled();
  });

  it("is a no-op when wsUrl is empty (no service yet)", () => {
    // Arrange
    _wsUrl = "";

    // Act
    renderHook(() => useTickSubscription("TCS", "NSE"), {
      wrapper: makeWrapper(_jotaiStore),
    });

    // Assert
    expect(fakeWs!.subscribe).not.toHaveBeenCalled();
  });
});
