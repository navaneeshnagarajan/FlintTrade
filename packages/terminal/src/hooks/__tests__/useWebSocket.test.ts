/**
 * useWebSocket tests
 *
 * Tests the React hook that wraps the WebSocket service.
 * The WS service and connection store are mocked.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import type { WsTick, WsInstrument } from "@/types/api";

// ---------------------------------------------------------------------------
// Fake WS service
// ---------------------------------------------------------------------------

type TickCb = (tick: WsTick) => void;
type StatusCb = (connected: boolean) => void;

let tickCallbacks: Set<TickCb>;
let statusCallbacks: Set<StatusCb>;
const mockConnect = vi.fn();
const mockSubscribe = vi.fn();
const mockUnsubscribe = vi.fn();
let mockIsConnected = false;

function resetFakeWs() {
  tickCallbacks = new Set();
  statusCallbacks = new Set();
  mockConnect.mockClear();
  mockSubscribe.mockClear();
  mockUnsubscribe.mockClear();
  mockIsConnected = false;
}

vi.mock("@/services/websocket", () => ({
  getWsService: (url?: string) => {
    if (!url) return null;
    return {
      get isConnected() { return mockIsConnected; },
      connect: mockConnect,
      subscribe: mockSubscribe,
      unsubscribe: mockUnsubscribe,
      onTick: (cb: TickCb) => {
        tickCallbacks.add(cb);
        return () => tickCallbacks.delete(cb);
      },
      onStatus: (cb: StatusCb) => {
        statusCallbacks.add(cb);
        return () => statusCallbacks.delete(cb);
      },
    };
  },
}));

// ---------------------------------------------------------------------------
// Mock connection store
// ---------------------------------------------------------------------------

let _wsUrl = "ws://127.0.0.1:8765";
let _apiKey = "test-key";

vi.mock("@/stores/connectionStore", () => ({
  useConnectionStore: (selector: (s: { wsUrl: string; apiKey: string }) => unknown) =>
    selector({ wsUrl: _wsUrl, apiKey: _apiKey }),
}));

// ---------------------------------------------------------------------------
// Import after mocks
// ---------------------------------------------------------------------------

import useWebSocket from "../useWebSocket";

// ---------------------------------------------------------------------------
// Setup / teardown
// ---------------------------------------------------------------------------

beforeEach(() => {
  resetFakeWs();
  _wsUrl = "ws://127.0.0.1:8765";
  _apiKey = "test-key";
});

afterEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useWebSocket", () => {
  it("returns empty ticks and disconnected by default", () => {
    const { result } = renderHook(() => useWebSocket());

    expect(result.current.ticks).toEqual({});
    expect(result.current.connected).toBe(false);
  });

  it("calls ws.connect when wsUrl is available", () => {
    renderHook(() => useWebSocket());
    expect(mockConnect).toHaveBeenCalled();
  });

  it("updates connected state when status callback fires", () => {
    const { result } = renderHook(() => useWebSocket());

    act(() => {
      statusCallbacks.forEach((cb) => cb(true));
    });

    expect(result.current.connected).toBe(true);
  });

  it("updates ticks when a tick callback fires", () => {
    const instruments: WsInstrument[] = [{ symbol: "NIFTY", exchange: "NSE_INDEX" }];
    const { result } = renderHook(() => useWebSocket(instruments));

    const tick: WsTick = { symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23500 };
    act(() => {
      tickCallbacks.forEach((cb) => cb(tick));
    });

    expect(result.current.ticks["NSE_INDEX:NIFTY"]).toBeDefined();
    expect(result.current.ticks["NSE_INDEX:NIFTY"].ltp).toBe(23500);
  });

  it("subscribes to instruments when they are provided", () => {
    const instruments: WsInstrument[] = [
      { symbol: "NIFTY", exchange: "NSE_INDEX" },
      { symbol: "BANKNIFTY", exchange: "NSE_INDEX" },
    ];

    renderHook(() => useWebSocket(instruments, "ltp"));

    expect(mockSubscribe).toHaveBeenCalledWith(instruments, "ltp");
  });

  it("unsubscribes on unmount when instruments were subscribed", () => {
    const instruments: WsInstrument[] = [{ symbol: "NIFTY", exchange: "NSE_INDEX" }];
    const { unmount } = renderHook(() => useWebSocket(instruments));

    unmount();

    expect(mockUnsubscribe).toHaveBeenCalled();
  });

  it("accumulates ticks for multiple instruments", () => {
    const instruments: WsInstrument[] = [
      { symbol: "NIFTY", exchange: "NSE_INDEX" },
      { symbol: "SENSEX", exchange: "BSE_INDEX" },
    ];
    const { result } = renderHook(() => useWebSocket(instruments));

    act(() => {
      tickCallbacks.forEach((cb) => cb({ symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23500 }));
      tickCallbacks.forEach((cb) => cb({ symbol: "SENSEX", exchange: "BSE_INDEX", ltp: 77000 }));
    });

    expect(Object.keys(result.current.ticks)).toHaveLength(2);
    expect(result.current.ticks["NSE_INDEX:NIFTY"].ltp).toBe(23500);
    expect(result.current.ticks["BSE_INDEX:SENSEX"].ltp).toBe(77000);
  });

  it("does not connect when wsUrl is empty", () => {
    _wsUrl = "";
    mockConnect.mockClear();

    renderHook(() => useWebSocket());

    // getWsService returns null for empty URL, so connect is not called
    expect(mockConnect).not.toHaveBeenCalled();
  });
});
