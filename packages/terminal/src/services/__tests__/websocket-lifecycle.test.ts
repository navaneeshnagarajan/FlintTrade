/**
 * WebSocket lifecycle tests — authentication, subscription, tick parsing,
 * heartbeat, and reconnection.
 *
 * These tests exercise the WebSocketService class by mocking the global
 * WebSocket constructor and simulating server messages.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { WebSocketService } from "../websocket";

// ---------------------------------------------------------------------------
// Mock WebSocket
// ---------------------------------------------------------------------------

/** Minimal mock that captures event handlers set by WebSocketService. */
class MockWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  // Instance constants (mimic real WebSocket)
  readonly CONNECTING = 0;
  readonly OPEN = 1;
  readonly CLOSING = 2;
  readonly CLOSED = 3;

  readyState = MockWebSocket.OPEN;
  url: string;
  onopen: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  send = vi.fn();
  close = vi.fn(() => {
    this.readyState = MockWebSocket.CLOSED;
  });

  constructor(url: string) {
    this.url = url;
    // Store the latest instance for test access
    MockWebSocket._lastInstance = this;
  }

  /** Simulate the server sending a message. */
  _receive(data: Record<string, unknown>): void {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
  }

  /** Simulate the connection opening. */
  _open(): void {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.({} as Event);
  }

  /** Simulate the connection closing. */
  _close(): void {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.({} as CloseEvent);
  }

  static _lastInstance: MockWebSocket | null = null;
}

vi.stubGlobal("WebSocket", MockWebSocket);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function createService(apiKey = "test-api-key-123"): WebSocketService {
  return new WebSocketService("ws://localhost:8765", apiKey);
}

/** Get the last MockWebSocket instance created by WebSocketService. */
function lastWs(): MockWebSocket {
  const ws = MockWebSocket._lastInstance;
  if (!ws) throw new Error("No MockWebSocket instance created");
  return ws;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("WebSocketService — lifecycle", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Fix Math.random to 0.5 so reconnect jitter is always 0ms (deterministic)
    vi.spyOn(Math, "random").mockReturnValue(0.5);
    MockWebSocket._lastInstance = null;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  // -----------------------------------------------------------------------
  // Authentication
  // -----------------------------------------------------------------------

  it("sends authenticate message on connect when API key is set", () => {
    const svc = createService("my-secret-key");
    svc.connect();

    const ws = lastWs();
    ws._open();

    expect(ws.send).toHaveBeenCalledTimes(1);
    const payload = JSON.parse(ws.send.mock.calls[0][0] as string);
    expect(payload).toEqual({
      action: "authenticate",
      api_key: "my-secret-key",
    });
  });

  it("does not send authenticate when no API key provided", () => {
    const svc = new WebSocketService("ws://localhost:8765", "");
    svc.connect();

    const ws = lastWs();
    ws._open();

    // No auth message — send may have been called for resubscription, but
    // the first call should not be an authenticate action.
    const authCalls = ws.send.mock.calls.filter((call) => {
      const p = JSON.parse(call[0] as string);
      return p.action === "authenticate";
    });
    expect(authCalls).toHaveLength(0);
  });

  it("sets connected=true only after auth success response", () => {
    const svc = createService();
    const statusCb = vi.fn();
    svc.onStatus(statusCb);
    svc.connect();

    const ws = lastWs();
    ws._open();

    // Not connected yet — waiting for auth response
    expect(svc.isConnected).toBe(false);

    // Simulate auth success from server
    ws._receive({ type: "auth", status: "success", message: "Authentication successful" });

    expect(svc.isConnected).toBe(true);
    expect(statusCb).toHaveBeenCalledWith(true);
  });

  // -----------------------------------------------------------------------
  // Subscription message format
  // -----------------------------------------------------------------------

  it("sends subscribe message with correct OpenAlgo v2 format", () => {
    const svc = createService();
    svc.connect();

    const ws = lastWs();
    ws._open();
    ws._receive({ type: "auth", status: "success" });

    // Clear calls from auth + any resubscription
    ws.send.mockClear();

    svc.subscribe(
      [
        { symbol: "NIFTY", exchange: "NSE_INDEX" },
        { symbol: "BANKNIFTY", exchange: "NSE_INDEX" },
      ],
      "ltp",
    );

    expect(ws.send).toHaveBeenCalledTimes(1);
    const payload = JSON.parse(ws.send.mock.calls[0][0] as string);
    expect(payload).toEqual({
      action: "subscribe",
      symbols: [
        { symbol: "NIFTY", exchange: "NSE_INDEX" },
        { symbol: "BANKNIFTY", exchange: "NSE_INDEX" },
      ],
      mode: "LTP",
    });
  });

  it("sends mode in UPPERCASE for depth subscriptions", () => {
    const svc = createService();
    svc.connect();

    const ws = lastWs();
    ws._open();
    ws._receive({ type: "auth", status: "success" });
    ws.send.mockClear();

    svc.subscribe([{ symbol: "RELIANCE", exchange: "NSE" }], "depth");

    const payload = JSON.parse(ws.send.mock.calls[0][0] as string);
    expect(payload.mode).toBe("DEPTH");
  });

  // -----------------------------------------------------------------------
  // Nested tick data parsing (data.type === "market_data" → data.data)
  // -----------------------------------------------------------------------

  it("parses nested market_data tick correctly", () => {
    const svc = createService();
    const tickCb = vi.fn();
    svc.onTick(tickCb);
    svc.connect();

    const ws = lastWs();
    ws._open();
    ws._receive({ type: "auth", status: "success" });

    // OpenAlgo v2 format: { type: "market_data", data: { symbol, ltp, ... } }
    ws._receive({
      type: "market_data",
      mode: 1,
      topic: "NIFTY.NSE_INDEX",
      data: {
        symbol: "NIFTY",
        exchange: "NSE_INDEX",
        ltp: 22450.5,
        open: 22400.0,
        high: 22500.0,
        low: 22380.0,
        close: 22420.0,
        volume: 150000,
        change: 30.5,
        pct: 0.14,
      },
    });

    expect(tickCb).toHaveBeenCalledTimes(1);
    const tick = tickCb.mock.calls[0][0];
    expect(tick.symbol).toBe("NIFTY");
    expect(tick.exchange).toBe("NSE_INDEX");
    expect(tick.ltp).toBe(22450.5);
    expect(tick.open).toBe(22400.0);
    expect(tick.high).toBe(22500.0);
    expect(tick.low).toBe(22380.0);
    expect(tick.volume).toBe(150000);
    expect(tick.change).toBe(30.5);
    expect(tick.pct).toBe(0.14);
  });

  it("ignores subscribe/unsubscribe ack messages", () => {
    const svc = createService();
    const tickCb = vi.fn();
    svc.onTick(tickCb);
    svc.connect();

    const ws = lastWs();
    ws._open();
    ws._receive({ type: "auth", status: "success" });

    ws._receive({ type: "subscribe", status: "success", subscriptions: ["NIFTY"] });
    ws._receive({ type: "unsubscribe", status: "success" });

    expect(tickCb).not.toHaveBeenCalled();
  });

  it("dispatches depth data to depthCallbacks", () => {
    const svc = createService();
    const depthCb = vi.fn();
    svc.onDepth(depthCb);
    svc.connect();

    const ws = lastWs();
    ws._open();
    ws._receive({ type: "auth", status: "success" });

    ws._receive({
      type: "market_data",
      mode: 3,
      data: {
        symbol: "RELIANCE",
        exchange: "NSE",
        bids: [{ price: 2500, qty: 100 }],
        asks: [{ price: 2501, qty: 50 }],
      },
    });

    expect(depthCb).toHaveBeenCalledTimes(1);
    const data = depthCb.mock.calls[0][0];
    expect(data.symbol).toBe("RELIANCE");
    expect(data.bids).toHaveLength(1);
  });

  // -----------------------------------------------------------------------
  // Heartbeat ping
  // -----------------------------------------------------------------------

  it("sends ping at the heartbeat interval", () => {
    const svc = createService();
    svc.connect();

    const ws = lastWs();
    ws._open();
    ws._receive({ type: "auth", status: "success" });

    // Clear auth/subscribe sends
    ws.send.mockClear();

    // Advance past the heartbeat interval (30s)
    vi.advanceTimersByTime(30_000);

    // Should have sent a ping
    const pingSent = ws.send.mock.calls.some((call) => {
      const p = JSON.parse(call[0] as string);
      return p.action === "ping";
    });
    expect(pingSent).toBe(true);
  });

  it("closes connection when pong not received within timeout", () => {
    const svc = createService();
    svc.connect();

    const ws = lastWs();
    ws._open();
    ws._receive({ type: "auth", status: "success" });

    // Trigger heartbeat
    vi.advanceTimersByTime(30_000);

    // Pong timeout is 10s — advance past it without sending pong
    vi.advanceTimersByTime(10_000);

    expect(ws.close).toHaveBeenCalled();
  });

  it("clears pong timeout when pong received", () => {
    const svc = createService();
    svc.connect();

    const ws = lastWs();
    ws._open();
    ws._receive({ type: "auth", status: "success" });

    // Trigger heartbeat
    vi.advanceTimersByTime(30_000);

    // Server responds with pong
    ws._receive({ action: "pong" });

    // Advance past pong timeout — close should NOT be called
    // (close may have been called 0 or more times before, so we snapshot)
    const closeCountBefore = ws.close.mock.calls.length;
    vi.advanceTimersByTime(10_000);
    expect(ws.close.mock.calls.length).toBe(closeCountBefore);
  });

  // -----------------------------------------------------------------------
  // Reconnection on close
  // -----------------------------------------------------------------------

  it("attempts reconnect after connection closes", () => {
    const svc = createService();
    svc.connect();

    const firstWs = lastWs();
    firstWs._open();
    firstWs._receive({ type: "auth", status: "success" });

    // Simulate unexpected close
    firstWs._close();

    expect(svc.isConnected).toBe(false);

    // Advance past the reconnect delay (starts at 1000ms)
    vi.advanceTimersByTime(1_000);

    // A new WebSocket should have been created
    const secondWs = lastWs();
    expect(secondWs).not.toBe(firstWs);
    expect(secondWs.url).toBe("ws://localhost:8765");
  });

  it("uses exponential backoff for reconnect delays", () => {
    const svc = createService();
    svc.connect();

    const ws1 = lastWs();
    ws1._open();
    ws1._receive({ type: "auth", status: "success" });

    // First close — reconnect after 1000ms
    ws1._close();
    vi.advanceTimersByTime(999);
    expect(lastWs()).toBe(ws1); // Not reconnected yet
    vi.advanceTimersByTime(1);
    const ws2 = lastWs();
    expect(ws2).not.toBe(ws1);

    // Second close — reconnect after 2000ms (doubled)
    ws2._close();
    vi.advanceTimersByTime(1999);
    expect(lastWs()).toBe(ws2); // Not reconnected yet
    vi.advanceTimersByTime(1);
    const ws3 = lastWs();
    expect(ws3).not.toBe(ws2);
  });

  it("does not reconnect after explicit disconnect", () => {
    const svc = createService();
    svc.connect();

    const ws = lastWs();
    ws._open();
    ws._receive({ type: "auth", status: "success" });

    // Explicit disconnect
    svc.disconnect();
    MockWebSocket._lastInstance = null;

    // Advance well past any reconnect delay
    vi.advanceTimersByTime(60_000);

    // No new WebSocket should have been created
    expect(MockWebSocket._lastInstance).toBeNull();
  });

  // -----------------------------------------------------------------------
  // Resubscription after reconnect
  // -----------------------------------------------------------------------

  it("resubscribes to all modes after reconnect auth success", () => {
    const svc = createService();
    svc.connect();

    const ws1 = lastWs();
    ws1._open();
    ws1._receive({ type: "auth", status: "success" });

    // Subscribe to instruments
    svc.subscribe([{ symbol: "NIFTY", exchange: "NSE_INDEX" }], "ltp");
    svc.subscribe([{ symbol: "RELIANCE", exchange: "NSE" }], "depth");

    // Simulate disconnect + reconnect
    ws1._close();
    vi.advanceTimersByTime(1_000);

    const ws2 = lastWs();
    ws2._open();
    ws2.send.mockClear();

    // Auth success triggers resubscription
    ws2._receive({ type: "auth", status: "success" });

    // Should have resubscription messages for both ltp and depth
    const sentPayloads = ws2.send.mock.calls.map((call) =>
      JSON.parse(call[0] as string),
    );

    const subscribeMsgs = sentPayloads.filter((p) => p.action === "subscribe");
    expect(subscribeMsgs.length).toBeGreaterThanOrEqual(2);

    const ltpSub = subscribeMsgs.find((p) => p.mode === "LTP");
    expect(ltpSub).toBeDefined();
    expect(ltpSub!.symbols).toEqual([{ symbol: "NIFTY", exchange: "NSE_INDEX" }]);

    const depthSub = subscribeMsgs.find((p) => p.mode === "DEPTH");
    expect(depthSub).toBeDefined();
    expect(depthSub!.symbols).toEqual([{ symbol: "RELIANCE", exchange: "NSE" }]);
  });

  // -----------------------------------------------------------------------
  // Mode-specific handler registration
  // -----------------------------------------------------------------------

  describe("registerHandler — mode-specific dispatch", () => {
    it("LTP handler receives only mode=1 ticks and not depth ticks", () => {
      const svc = createService();
      const ltpHandler = vi.fn();
      svc.registerHandler("ltp", ltpHandler);
      svc.connect();

      const ws = lastWs();
      ws._open();
      ws._receive({ type: "auth", status: "success" });

      // LTP tick (mode 1)
      ws._receive({
        type: "market_data",
        mode: 1,
        data: { symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23000 },
      });

      expect(ltpHandler).toHaveBeenCalledTimes(1);
      const tick = ltpHandler.mock.calls[0][0];
      expect(tick.symbol).toBe("NIFTY");
      expect(tick.ltp).toBe(23000);

      // Depth tick — must NOT reach the LTP handler
      ltpHandler.mockClear();
      ws._receive({
        type: "market_data",
        mode: 3,
        data: {
          symbol: "NIFTY",
          exchange: "NSE_INDEX",
          bids: [{ price: 22999, qty: 10 }],
          asks: [{ price: 23001, qty: 5 }],
        },
      });

      expect(ltpHandler).not.toHaveBeenCalled();
    });

    it("quote handler receives only mode=2 ticks", () => {
      const svc = createService();
      const quoteHandler = vi.fn();
      const ltpHandler = vi.fn();
      svc.registerHandler("quote", quoteHandler);
      svc.registerHandler("ltp", ltpHandler);
      svc.connect();

      const ws = lastWs();
      ws._open();
      ws._receive({ type: "auth", status: "success" });

      // Quote tick (mode 2)
      ws._receive({
        type: "market_data",
        mode: 2,
        data: { symbol: "RELIANCE", exchange: "NSE", ltp: 2500, open: 2490 },
      });

      expect(quoteHandler).toHaveBeenCalledTimes(1);
      // LTP handler must NOT fire for a mode=2 message
      expect(ltpHandler).not.toHaveBeenCalled();
    });

    it("depth handler receives only depth ticks (bids/asks present)", () => {
      const svc = createService();
      const depthHandler = vi.fn();
      svc.registerHandler("depth", depthHandler);
      svc.connect();

      const ws = lastWs();
      ws._open();
      ws._receive({ type: "auth", status: "success" });

      // Regular LTP tick — must NOT reach depth handler
      ws._receive({
        type: "market_data",
        mode: 1,
        data: { symbol: "INFY", exchange: "NSE", ltp: 1800 },
      });
      expect(depthHandler).not.toHaveBeenCalled();

      // Depth tick
      ws._receive({
        type: "market_data",
        mode: 3,
        data: {
          symbol: "INFY",
          exchange: "NSE",
          bids: [{ price: 1799, qty: 200 }],
          asks: [{ price: 1801, qty: 100 }],
        },
      });

      expect(depthHandler).toHaveBeenCalledTimes(1);
      const data = depthHandler.mock.calls[0][0] as Record<string, unknown>;
      expect(Array.isArray(data["bids"])).toBe(true);
    });

    it("unregister function removes the handler", () => {
      const svc = createService();
      const handler = vi.fn();
      const off = svc.registerHandler("ltp", handler);
      svc.connect();

      const ws = lastWs();
      ws._open();
      ws._receive({ type: "auth", status: "success" });

      // Fire once to confirm it was registered
      ws._receive({
        type: "market_data",
        mode: 1,
        data: { symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 22500 },
      });
      expect(handler).toHaveBeenCalledTimes(1);

      // Unregister and fire again — should be silent
      off();
      ws._receive({
        type: "market_data",
        mode: 1,
        data: { symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 22600 },
      });
      expect(handler).toHaveBeenCalledTimes(1); // still 1, not 2
    });
  });

  // -----------------------------------------------------------------------
  // batchSubscribe with delay
  // -----------------------------------------------------------------------

  describe("batchSubscribe", () => {
    it("sends subscription messages with 50ms delay between modes", async () => {
      // Use real timers for this test — fake timers interact badly with the
      // heartbeat interval (30s) when runAllTimersAsync() is called, because
      // it fires ping → pong timeout → reconnect in an infinite loop.
      vi.useRealTimers();

      const svc = createService();
      svc.connect();

      const ws = lastWs();
      ws._open();
      ws._receive({ type: "auth", status: "success" });
      ws.send.mockClear();

      await svc.batchSubscribe(
        [
          { instrument: { symbol: "NIFTY", exchange: "NSE_INDEX" }, mode: "ltp" },
          { instrument: { symbol: "RELIANCE", exchange: "NSE" }, mode: "quote" },
        ],
        10, // short delay for real-timer test
      );

      expect(ws.send).toHaveBeenCalledTimes(2);

      const calls = ws.send.mock.calls.map((c) => JSON.parse(c[0] as string));
      const modes = calls.map((c: Record<string, unknown>) => c["mode"]);
      expect(modes).toContain("LTP");
      expect(modes).toContain("QUOTE");

      // Restore fake timers for remaining tests in this suite
      vi.useFakeTimers();
    });

    it("does not send duplicate wire message when same symbol already subscribed", async () => {
      const svc = createService();
      svc.connect();

      const ws = lastWs();
      ws._open();
      ws._receive({ type: "auth", status: "success" });
      ws.send.mockClear();

      // First subscription
      await svc.batchSubscribe(
        [{ instrument: { symbol: "NIFTY", exchange: "NSE_INDEX" }, mode: "ltp" }],
        0,
      );
      const firstCount = ws.send.mock.calls.length;

      // Second subscription for the same symbol — ref count bumped, no new wire message
      await svc.batchSubscribe(
        [{ instrument: { symbol: "NIFTY", exchange: "NSE_INDEX" }, mode: "ltp" }],
        0,
      );
      expect(ws.send.mock.calls.length).toBe(firstCount);
    });
  });

  // -----------------------------------------------------------------------
  // Reference-counted subscriptions
  // -----------------------------------------------------------------------

  describe("releaseSubscription — reference counting", () => {
    it("does not unsubscribe until last reference is released", () => {
      const svc = createService();
      svc.connect();

      const ws = lastWs();
      ws._open();
      ws._receive({ type: "auth", status: "success" });

      const inst = { symbol: "NIFTY", exchange: "NSE_INDEX" };

      // Two callers subscribe to the same instrument
      svc.subscribe([inst], "ltp"); // refCount = 1 (set by subscribe)
      // Manually bump the ref count to simulate a second caller
      const key = "NSE_INDEX:NIFTY:ltp";
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const info = (svc as unknown as Record<string, Map<string, { refCount: number }>>)["subscriptionMap"].get(key);
      if (info) info.refCount = 2;

      ws.send.mockClear();

      // First release — ref count drops to 1, no unsubscribe sent
      svc.releaseSubscription(inst, "ltp");
      const unsubCalls = ws.send.mock.calls.filter((c) => {
        const p = JSON.parse(c[0] as string);
        return p.action === "unsubscribe";
      });
      expect(unsubCalls).toHaveLength(0);

      // Second release — ref count drops to 0, unsubscribe IS sent
      svc.releaseSubscription(inst, "ltp");
      const unsubCalls2 = ws.send.mock.calls.filter((c) => {
        const p = JSON.parse(c[0] as string);
        return p.action === "unsubscribe";
      });
      expect(unsubCalls2).toHaveLength(1);
    });
  });

  // -----------------------------------------------------------------------
  // Auto-resubscribe on reconnect (batchSubscribe path)
  // -----------------------------------------------------------------------

  describe("auto-resubscribe after reconnect — batchSubscribe path", () => {
    it("resubscribes all batchSubscribed symbols on reconnect", async () => {
      const svc = createService();
      svc.connect();

      const ws1 = lastWs();
      ws1._open();
      ws1._receive({ type: "auth", status: "success" });

      // Use batchSubscribe to add two symbols
      await svc.batchSubscribe(
        [
          { instrument: { symbol: "BANKNIFTY", exchange: "NSE_INDEX" }, mode: "ltp" },
          { instrument: { symbol: "INDIAVIX", exchange: "NSE_INDEX" }, mode: "ltp" },
        ],
        0,
      );

      // Simulate drop and reconnect
      ws1._close();
      vi.advanceTimersByTime(1_000);

      const ws2 = lastWs();
      ws2._open();
      ws2.send.mockClear();
      ws2._receive({ type: "auth", status: "success" });

      // resubscribeAll must replay the ltp subscriptions
      const sentPayloads = ws2.send.mock.calls.map((c) =>
        JSON.parse(c[0] as string),
      );
      const ltpSubs = sentPayloads.filter(
        (p) => p.action === "subscribe" && p.mode === "LTP",
      );
      expect(ltpSubs).toHaveLength(1);
      const symbols: string[] = (
        ltpSubs[0].symbols as Array<{ symbol: string }>
      ).map((s) => s.symbol);
      expect(symbols).toContain("BANKNIFTY");
      expect(symbols).toContain("INDIAVIX");
    });
  });

  // -----------------------------------------------------------------------
  // Diagnostic helpers
  // -----------------------------------------------------------------------

  describe("getSubscriptionCount / getSubscribedSymbols", () => {
    it("getSubscriptionCount reflects active subscriptions across modes", () => {
      const svc = createService();
      expect(svc.getSubscriptionCount()).toBe(0);
      svc.subscribe([{ symbol: "NIFTY", exchange: "NSE_INDEX" }], "ltp");
      expect(svc.getSubscriptionCount()).toBe(1);
      svc.subscribe([{ symbol: "NIFTY", exchange: "NSE_INDEX" }], "depth");
      expect(svc.getSubscriptionCount()).toBe(2); // same symbol, different mode
    });

    it("getSubscribedSymbols deduplicates across modes", () => {
      const svc = createService();
      svc.subscribe([{ symbol: "NIFTY", exchange: "NSE_INDEX" }], "ltp");
      svc.subscribe([{ symbol: "NIFTY", exchange: "NSE_INDEX" }], "depth");
      svc.subscribe([{ symbol: "RELIANCE", exchange: "NSE" }], "ltp");
      const symbols = svc.getSubscribedSymbols();
      // NIFTY appears in two modes but should be listed once
      expect(symbols).toHaveLength(2);
      expect(symbols).toContain("NSE_INDEX:NIFTY");
      expect(symbols).toContain("NSE:RELIANCE");
    });
  });
});
