import { describe, it, expect, vi, beforeEach } from "vitest";
import { WebSocketService } from "../websocket";

class MockWebSocket {
  static OPEN = 1;
  static lastInstance: MockWebSocket | null = null;
  readyState = MockWebSocket.OPEN;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  send = vi.fn();
  close = vi.fn();

  constructor() {
    MockWebSocket.lastInstance = this;
  }

  /** Simulate the connection opening (no API key → connected immediately). */
  _open(): void {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }
}

vi.stubGlobal("WebSocket", MockWebSocket);

/** All payloads sent over the mock wire, parsed. */
function sentPayloads(sock: MockWebSocket): Array<Record<string, unknown>> {
  return sock.send.mock.calls.map((c) => JSON.parse(c[0] as string) as Record<string, unknown>);
}

function unsubscribeMessages(sock: MockWebSocket): Array<Record<string, unknown>> {
  return sentPayloads(sock).filter((p) => p.action === "unsubscribe");
}

/** Create a service with an open (unauthenticated) socket so send() hits the wire. */
function connectedService(): { svc: WebSocketService; sock: MockWebSocket } {
  const svc = new WebSocketService("ws://localhost:8765");
  MockWebSocket.lastInstance = null;
  svc.connect();
  // Indirect read: TS control-flow analysis narrows the static to `null`
  // after the reset above and cannot see the constructor assignment inside
  // connect(), so a direct read would be typed `null`.
  const sock = ((): MockWebSocket | null => MockWebSocket.lastInstance)();
  if (!sock) throw new Error("MockWebSocket was not constructed");
  sock._open();
  sock.send.mockClear();
  return { svc, sock };
}

describe("WebSocketService", () => {
  let ws: WebSocketService;

  beforeEach(() => {
    ws = new WebSocketService("ws://localhost:8765");
  });

  it("tracks subscription state per mode", () => {
    ws.subscribe([{ symbol: "NIFTY", exchange: "NSE_INDEX" }], "ltp");
    expect(ws.getSubscriptions("ltp")).toHaveLength(1);
  });

  it("does not duplicate subscriptions", () => {
    const inst = [{ symbol: "NIFTY", exchange: "NSE_INDEX" }];
    ws.subscribe(inst, "ltp");
    ws.subscribe(inst, "ltp");
    expect(ws.getSubscriptions("ltp")).toHaveLength(1);
  });

  it("removes subscriptions on unsubscribe", () => {
    const inst = [{ symbol: "NIFTY", exchange: "NSE_INDEX" }];
    ws.subscribe(inst, "ltp");
    ws.unsubscribe(inst, "ltp");
    expect(ws.getSubscriptions("ltp")).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Reference-counted subscribe/unsubscribe
//
// Regression suite for the silent price-freeze bug: two widgets sharing one
// instrument+mode (e.g. Scalper + Time & Sales on NIFTY quote) share ONE
// server subscription. Before refcounting, whichever widget unmounted first
// sent the wire unsubscribe for both — the survivor's prices froze at the
// last tick with the connection indicator still green.
// ---------------------------------------------------------------------------

describe("WebSocketService — reference-counted subscriptions", () => {
  const NIFTY = { symbol: "NIFTY", exchange: "NSE_INDEX" };
  const BANKNIFTY = { symbol: "BANKNIFTY", exchange: "NSE_INDEX" };

  it("two subscribers + one unsubscribe = still subscribed, no wire unsubscribe", () => {
    const { svc, sock } = connectedService();

    // Two independent consumers subscribe to the same instrument+mode.
    svc.subscribe([NIFTY], "quote"); // consumer A (e.g. Scalper)
    svc.subscribe([NIFTY], "quote"); // consumer B (e.g. Time & Sales)

    // One wire subscribe only — the second call takes a reference.
    expect(sentPayloads(sock).filter((p) => p.action === "subscribe")).toHaveLength(1);

    // Consumer B unmounts.
    svc.unsubscribe([NIFTY], "quote");

    // The subscription must survive for consumer A: no wire unsubscribe,
    // still tracked in both the per-mode record and the refcount map.
    expect(unsubscribeMessages(sock)).toHaveLength(0);
    expect(svc.getSubscriptions("quote")).toHaveLength(1);
    expect(svc.getSubscriptionCount()).toBe(1);
  });

  it("sends the wire unsubscribe only when the last consumer releases", () => {
    const { svc, sock } = connectedService();

    svc.subscribe([NIFTY], "quote");
    svc.subscribe([NIFTY], "quote");
    svc.unsubscribe([NIFTY], "quote");
    expect(unsubscribeMessages(sock)).toHaveLength(0);

    // Last consumer releases — NOW the server subscription is torn down.
    svc.unsubscribe([NIFTY], "quote");
    const unsubs = unsubscribeMessages(sock);
    expect(unsubs).toHaveLength(1);
    expect(unsubs[0].symbols).toEqual([{ symbol: "NIFTY", exchange: "NSE_INDEX" }]);
    expect(svc.getSubscriptions("quote")).toHaveLength(0);
    expect(svc.getSubscriptionCount()).toBe(0);
  });

  it("a mixed unsubscribe only wire-drops the instruments whose last reference released", () => {
    const { svc, sock } = connectedService();

    svc.subscribe([NIFTY, BANKNIFTY], "quote"); // consumer A holds both
    svc.subscribe([NIFTY], "quote"); // consumer B holds NIFTY too

    // Consumer A unmounts, releasing both instruments.
    svc.unsubscribe([NIFTY, BANKNIFTY], "quote");

    // Only BANKNIFTY (refcount reached zero) goes over the wire; NIFTY stays
    // live for consumer B.
    const unsubs = unsubscribeMessages(sock);
    expect(unsubs).toHaveLength(1);
    expect(unsubs[0].symbols).toEqual([{ symbol: "BANKNIFTY", exchange: "NSE_INDEX" }]);
    expect(svc.getSubscriptions("quote")).toEqual([NIFTY]);
  });

  it("reference counts are per mode — releasing quote does not touch ltp", () => {
    const { svc, sock } = connectedService();

    svc.subscribe([NIFTY], "quote");
    svc.subscribe([NIFTY], "ltp");

    svc.unsubscribe([NIFTY], "quote");

    // The quote subscription dropped (its only consumer left) but the ltp
    // one is untouched.
    expect(unsubscribeMessages(sock)).toHaveLength(1);
    expect(svc.getSubscriptions("quote")).toHaveLength(0);
    expect(svc.getSubscriptions("ltp")).toHaveLength(1);
  });

  it("duplicate instruments within a single subscribe call count as one reference", () => {
    const { svc, sock } = connectedService();

    svc.subscribe([NIFTY, NIFTY], "quote"); // one consumer, sloppy input
    svc.unsubscribe([NIFTY], "quote");

    // One balanced release must fully tear down — no leaked reference.
    expect(unsubscribeMessages(sock)).toHaveLength(1);
    expect(svc.getSubscriptionCount()).toBe(0);
  });

  it("releaseSubscription is refcount-aware and a no-op for untracked instruments", () => {
    const { svc, sock } = connectedService();

    // Untracked release — nothing goes over the wire.
    svc.releaseSubscription(NIFTY, "quote");
    expect(unsubscribeMessages(sock)).toHaveLength(0);

    // Two consumers, released one at a time via releaseSubscription.
    svc.subscribe([NIFTY], "quote");
    svc.subscribe([NIFTY], "quote");
    svc.releaseSubscription(NIFTY, "quote");
    expect(unsubscribeMessages(sock)).toHaveLength(0);
    svc.releaseSubscription(NIFTY, "quote");
    expect(unsubscribeMessages(sock)).toHaveLength(1);
  });

  it("batchSubscribe references interoperate with unsubscribe releases", async () => {
    const { svc, sock } = connectedService();

    await svc.batchSubscribe([{ instrument: NIFTY, mode: "quote" }], 0); // consumer A
    svc.subscribe([NIFTY], "quote"); // consumer B

    svc.unsubscribe([NIFTY], "quote"); // consumer B leaves
    expect(unsubscribeMessages(sock)).toHaveLength(0);
    expect(svc.getSubscriptions("quote")).toHaveLength(1);

    svc.unsubscribe([NIFTY], "quote"); // consumer A leaves
    expect(unsubscribeMessages(sock)).toHaveLength(1);
  });
});
