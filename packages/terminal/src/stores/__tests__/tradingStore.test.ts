import { describe, it, expect, beforeEach } from "vitest";
import { useTradingStore } from "../tradingStore";

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
      { pnl: 1500 },
      { pnl: -500 },
    ] as any[]);
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
