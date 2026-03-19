import { describe, it, expect, vi, beforeEach } from "vitest";
import { WebSocketService } from "../websocket";

class MockWebSocket {
  static OPEN = 1;
  readyState = MockWebSocket.OPEN;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  send = vi.fn();
  close = vi.fn();
}

vi.stubGlobal("WebSocket", MockWebSocket);

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
