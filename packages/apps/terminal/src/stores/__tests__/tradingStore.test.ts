import { describe, it, expect, beforeEach } from "vitest";
import { useTradingStore } from "../tradingStore";
import type { Position } from "@/types/api";

describe("tradingStore", () => {
  beforeEach(() => {
    useTradingStore.setState(useTradingStore.getInitialState());
  });

  it("initializes with zero P&L", () => {
    const state = useTradingStore.getState();
    expect(state.totalPnl).toBe(0);
    expect(state.positionCount).toBe(0);
  });

  it("updates aggregated P&L from positions", () => {
    useTradingStore.getState().updateFromPositions([
      { symbol: "NIFTY", exchange: "NFO", product: "MIS", quantity: 1, averagePrice: 100, ltp: 115, pnl: 1500, pnlPercent: 15 },
      { symbol: "BANKNIFTY", exchange: "NFO", product: "MIS", quantity: 1, averagePrice: 200, ltp: 195, pnl: -500, pnlPercent: -2.5 },
    ] satisfies Position[]);
    const state = useTradingStore.getState();
    expect(state.totalPnl).toBe(1000);
    expect(state.positionCount).toBe(2);
  });

  const long: Position = { symbol: "SYNTHETIC-LONG", exchange: "NSE", product: "MIS", quantity: 2, averagePrice: 100, ltp: 110, pnl: 20, pnlPercent: 10 };
  const short: Position = { ...long, symbol: "SYNTHETIC-SHORT", quantity: -1, averagePrice: 200, ltp: 210, pnl: -10, pnlPercent: -5 };
  const flat: Position = { ...long, symbol: "SYNTHETIC-FLAT", quantity: 0, pnl: 30 };

  it.each([
    { name: "mixed flat and open rows", positions: [long, short, flat], expected: { totalPnl: 40, totalPnlPercent: 10, positionCount: 2 } },
    { name: "open long and short rows", positions: [long, short], expected: { totalPnl: 10, totalPnlPercent: 2.5, positionCount: 2 } },
    { name: "only flat rows", positions: [flat], expected: { totalPnl: 30, totalPnlPercent: 0, positionCount: 0 } },
    { name: "empty rows", positions: [], expected: { totalPnl: 0, totalPnlPercent: 0, positionCount: 0 } },
  ])("public aggregate setters agree on $name", ({ positions, expected }) => {
    useTradingStore.getState().updateFromPositions(positions);
    expect(useTradingStore.getState()).toMatchObject(expected);
    useTradingStore.getState().resetSessionState();
    const publications: Array<{ scopeKey: string | null; totalPnl: number; totalPnlPercent: number; positionCount: number; availableMargin: number; usedMargin: number }> = [];
    const unsubscribe = useTradingStore.subscribe(({ scopeKey, totalPnl, totalPnlPercent, positionCount, availableMargin, usedMargin }) => {
      publications.push({ scopeKey, totalPnl, totalPnlPercent, positionCount, availableMargin, usedMargin });
    });
    try {
      useTradingStore.getState().syncAccountSnapshot({
        scopeKey: "live:native:dhan:A1", fundsStatus: "ready", positionsStatus: "ready",
        positions, funds: { availableCash: 80, usedMargin: 20, totalBalance: 100 },
      });
      expect(useTradingStore.getState()).toMatchObject({ ...expected, fundsStatus: "ready", positionsStatus: "ready" });
      expect(publications).toEqual([{ scopeKey: "live:native:dhan:A1", ...expected, availableMargin: 80, usedMargin: 20 }]);
    } finally {
      unsubscribe();
    }
  });

  it.each([
    { funds: { availableCash: 80, usedMargin: 20, totalBalance: 100 }, expected: { availableMargin: 80, usedMargin: 20 } },
    { funds: { availableCash: 0, usedMargin: 0, totalBalance: 0 }, expected: { availableMargin: 0, usedMargin: 0 } },
    { funds: { availableCash: -20, usedMargin: 30, totalBalance: 10 }, expected: { availableMargin: -20, usedMargin: 30 } },
  ])("public funds setters preserve $funds", ({ funds, expected }) => {
    useTradingStore.getState().updateFromFunds(funds);
    expect(useTradingStore.getState()).toMatchObject(expected);
    useTradingStore.getState().resetSessionState();
    useTradingStore.getState().syncAccountSnapshot({ scopeKey: "live:native:dhan:A1", fundsStatus: "ready", positionsStatus: "ready", funds, positions: [] });
    expect(useTradingStore.getState()).toMatchObject(expected);
  });

  it("updates margin info from funds", () => {
    useTradingStore.getState().updateFromFunds({
      availableCash: 50000,
      usedMargin: 10000,
      totalBalance: 60000,
    });
    const state = useTradingStore.getState();
    expect(state.availableMargin).toBe(50000);
    expect(state.usedMargin).toBe(10000);
  });

  it("preserves same-scope order counts during funds/positions refresh and retires them on scope change", () => {
    const snapshot = { scopeKey: "live:native:dhan:A1", fundsStatus: "ready" as const, positionsStatus: "ready" as const, funds: { availableCash: 1, usedMargin: 0, totalBalance: 1 }, positions: [] };
    useTradingStore.getState().syncAccountSnapshot(snapshot);
    useTradingStore.getState().setOpenOrderCount(3);
    useTradingStore.getState().syncAccountSnapshot(snapshot);
    expect(useTradingStore.getState().openOrderCount).toBe(3);
    useTradingStore.getState().syncAccountSnapshot({ ...snapshot, scopeKey: "live:native:upstox:B2" });
    expect(useTradingStore.getState().openOrderCount).toBe(0);
  });

  it("clears every principal-derived aggregate", () => {
    useTradingStore.getState().updateFromPositions([
      { symbol: "NIFTY", exchange: "NFO", product: "MIS", quantity: 1, averagePrice: 100, ltp: 115, pnl: 1500, pnlPercent: 15 },
    ] satisfies Position[]);
    useTradingStore.getState().updateFromFunds({
      availableCash: 50000,
      usedMargin: 10000,
      totalBalance: 60000,
    });
    useTradingStore.getState().setOpenOrderCount(3);

    useTradingStore.getState().resetSessionState();

    expect(useTradingStore.getState()).toMatchObject({
      totalPnl: 0,
      totalPnlPercent: 0,
      positionCount: 0,
      openOrderCount: 0,
      usedMargin: 0,
      availableMargin: 0,
    });
  });
});
