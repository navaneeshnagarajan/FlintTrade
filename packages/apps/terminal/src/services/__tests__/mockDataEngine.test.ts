import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { MockDataEngine } from "../mockDataEngine";

// Base prices used in the engine — keep in sync with BASE_PRICES constant.
const BASE_PRICES: Record<string, number> = {
  NIFTY:     24150,
  BANKNIFTY: 51200,
  SENSEX:    79800,
  RELIANCE:  2850,
  TCS:       3720,
  HDFCBANK:  1680,
  INFY:      1520,
  ICICIBANK: 1290,
  SBIN:      780,
  ITC:       440,
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("MockDataEngine", () => {
  let engine: MockDataEngine;

  beforeEach(() => {
    vi.useFakeTimers();
    engine = new MockDataEngine();
  });

  afterEach(() => {
    engine.stop();
    vi.useRealTimers();
  });

  // --- Lifecycle ------------------------------------------------------------

  describe("start / stop lifecycle", () => {
    it("is not running after construction", () => {
      expect(engine.isRunning).toBe(false);
    });

    it("is running after start()", () => {
      engine.start(1000);
      expect(engine.isRunning).toBe(true);
    });

    it("is not running after stop()", () => {
      engine.start(1000);
      engine.stop();
      expect(engine.isRunning).toBe(false);
    });

    it("calling start() twice does not create a second interval", () => {
      const setIntervalSpy = vi.spyOn(globalThis, "setInterval");
      engine.start(1000);
      engine.start(1000); // second call should be a no-op
      expect(setIntervalSpy).toHaveBeenCalledTimes(1);
    });

    it("calling stop() when not running does not throw", () => {
      expect(() => engine.stop()).not.toThrow();
    });
  });

  // --- Price bounds ---------------------------------------------------------

  describe("prices stay within ±5% of base", () => {
    it("all symbols remain in bounds after 100 ticks", () => {
      engine.start(100);
      // Advance 100 ticks
      vi.advanceTimersByTime(100 * 100);

      const snapshot = engine.getSnapshot();
      for (const tick of snapshot) {
        const base = BASE_PRICES[tick.symbol];
        if (base === undefined) continue;
        expect(tick.ltp).toBeGreaterThanOrEqual(base * 0.95);
        expect(tick.ltp).toBeLessThanOrEqual(base * 1.05);
      }
    });

    it("snapshot contains an entry for every base symbol", () => {
      const snapshot = engine.getSnapshot();
      const symbols = snapshot.map((t) => t.symbol);
      for (const sym of Object.keys(BASE_PRICES)) {
        expect(symbols).toContain(sym);
      }
    });
  });

  // --- getMockPositions -----------------------------------------------------

  describe("getMockPositions", () => {
    it("returns exactly 5 positions", () => {
      expect(engine.getMockPositions()).toHaveLength(5);
    });

    it("each position has a valid side", () => {
      for (const pos of engine.getMockPositions()) {
        expect(["BUY", "SELL"]).toContain(pos.side);
      }
    });

    it("each position has a positive quantity", () => {
      for (const pos of engine.getMockPositions()) {
        expect(pos.quantity).toBeGreaterThan(0);
      }
    });

    it("each position has a numeric pnl", () => {
      for (const pos of engine.getMockPositions()) {
        expect(typeof pos.pnl).toBe("number");
        expect(Number.isFinite(pos.pnl)).toBe(true);
      }
    });
  });

  // --- getMockOrders --------------------------------------------------------

  describe("getMockOrders", () => {
    it("returns exactly 8 orders", () => {
      expect(engine.getMockOrders()).toHaveLength(8);
    });

    it("each order has a non-empty orderId", () => {
      for (const order of engine.getMockOrders()) {
        expect(order.orderId.length).toBeGreaterThan(0);
      }
    });

    it("each order has a valid status", () => {
      const validStatuses = ["COMPLETE", "OPEN", "REJECTED", "CANCELLED"];
      for (const order of engine.getMockOrders()) {
        expect(validStatuses).toContain(order.status);
      }
    });

    it("each order has a valid side", () => {
      for (const order of engine.getMockOrders()) {
        expect(["BUY", "SELL"]).toContain(order.side);
      }
    });

    it("each order has a positive price", () => {
      for (const order of engine.getMockOrders()) {
        expect(order.price).toBeGreaterThan(0);
      }
    });
  });

  // --- getMockHoldings ------------------------------------------------------

  describe("getMockHoldings", () => {
    it("returns exactly 10 holdings", () => {
      expect(engine.getMockHoldings()).toHaveLength(10);
    });

    it("each holding has a positive quantity", () => {
      for (const h of engine.getMockHoldings()) {
        expect(h.quantity).toBeGreaterThan(0);
      }
    });

    it("each holding has a positive currentValue", () => {
      for (const h of engine.getMockHoldings()) {
        expect(h.currentValue).toBeGreaterThan(0);
      }
    });

    it("each holding has a finite pnlPct", () => {
      for (const h of engine.getMockHoldings()) {
        expect(Number.isFinite(h.pnlPct)).toBe(true);
      }
    });

    it("currentValue equals ltp * quantity (within floating point tolerance)", () => {
      for (const h of engine.getMockHoldings()) {
        expect(h.currentValue).toBeCloseTo(h.ltp * h.quantity, 1);
      }
    });
  });

  // --- onTick callback ------------------------------------------------------

  describe("onTick callback", () => {
    it("fires once per interval tick", () => {
      const cb = vi.fn();
      engine.onTick(cb);
      engine.start(500);

      vi.advanceTimersByTime(500);
      expect(cb).toHaveBeenCalledTimes(1);

      vi.advanceTimersByTime(500);
      expect(cb).toHaveBeenCalledTimes(2);
    });

    it("callback receives an array of MockTick objects", () => {
      const cb = vi.fn();
      engine.onTick(cb);
      engine.start(500);
      vi.advanceTimersByTime(500);

      const [ticks] = cb.mock.calls[0] as [ReturnType<MockDataEngine["getSnapshot"]>];
      expect(Array.isArray(ticks)).toBe(true);
      expect(ticks.length).toBeGreaterThan(0);
      // Each tick has the expected shape
      const tick = ticks[0];
      expect(tick).toHaveProperty("symbol");
      expect(tick).toHaveProperty("ltp");
      expect(tick).toHaveProperty("changePct");
    });

    it("unsubscribe stops further callback invocations", () => {
      const cb = vi.fn();
      const unsub = engine.onTick(cb);
      engine.start(500);

      vi.advanceTimersByTime(500);
      expect(cb).toHaveBeenCalledTimes(1);

      unsub();
      vi.advanceTimersByTime(1000);
      // Still only 1 call — unsubscribed after first tick
      expect(cb).toHaveBeenCalledTimes(1);
    });

    it("multiple subscribers each receive the same ticks", () => {
      const cb1 = vi.fn();
      const cb2 = vi.fn();
      engine.onTick(cb1);
      engine.onTick(cb2);
      engine.start(500);
      vi.advanceTimersByTime(500);

      expect(cb1).toHaveBeenCalledTimes(1);
      expect(cb2).toHaveBeenCalledTimes(1);

      const ticks1 = cb1.mock.calls[0][0] as ReturnType<MockDataEngine["getSnapshot"]>;
      const ticks2 = cb2.mock.calls[0][0] as ReturnType<MockDataEngine["getSnapshot"]>;
      expect(ticks1).toEqual(ticks2);
    });
  });
});
