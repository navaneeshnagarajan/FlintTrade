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
});
