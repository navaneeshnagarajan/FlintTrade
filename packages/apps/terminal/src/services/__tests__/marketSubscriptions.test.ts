import { describe, expect, it, vi } from "vitest";
import { WebSocketService } from "../websocket";
const instrument = { symbol: "INFY", exchange: "NSE" };
describe("native market interest registry", () => {
  it("reference-counts widget interests across subscription modes", () => {
    const feed = new WebSocketService();
    feed.subscribe([instrument], "ltp");
    feed.subscribe([instrument], "ltp");
    feed.subscribe([instrument], "quote");
    feed.unsubscribe([instrument], "ltp");
    expect(feed.getSubscriptions("ltp")).toEqual([instrument]);
    feed.unsubscribe([instrument], "ltp");
    expect(feed.getSubscriptions("ltp")).toEqual([]);
    expect(feed.getSubscriptions("quote")).toEqual([instrument]);
  });
  it("never creates an external socket or reports streaming connection", () => {
    const socket = vi.fn(); vi.stubGlobal("WebSocket", socket);
    const feed = new WebSocketService();
    feed.subscribe([instrument]);
    feed.publishTick({ ...instrument, ltp: 1 });
    expect(socket).not.toHaveBeenCalled();
    expect(feed.isConnected).toBe(false);
    vi.unstubAllGlobals();
  });
  it("delivers native polling ticks and unsubscribes listeners", () => {
    const feed = new WebSocketService();
    const handler = vi.fn(); const off = feed.onTick(handler);
    const tick = { ...instrument, ltp: 1500 };
    feed.publishTick(tick);
    expect(handler).toHaveBeenCalledWith(tick);
    expect(feed.diagnostics.lastTickTimestamp).toBeGreaterThan(0);
    off(); feed.publishTick(tick); expect(handler).toHaveBeenCalledTimes(1);
  });
});
