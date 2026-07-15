import { create } from "zustand";
import { devtools } from "zustand/middleware";
import type { StateCreator } from "zustand";
import type { Position, Funds } from "@/types/api";

interface TradingStore {
  totalPnl: number;
  totalPnlPercent: number;
  positionCount: number;
  openOrderCount: number;
  usedMargin: number;
  availableMargin: number;
  updateFromPositions: (positions: Position[]) => void;
  updateFromFunds: (funds: Funds) => void;
  setOpenOrderCount: (count: number) => void;
  resetSessionState: () => void;
}

const EMPTY_TRADING_SESSION = {
  totalPnl: 0,
  totalPnlPercent: 0,
  positionCount: 0,
  openOrderCount: 0,
  usedMargin: 0,
  availableMargin: 0,
};

const storeImpl: StateCreator<TradingStore> = (set) => ({
  ...EMPTY_TRADING_SESSION,
  updateFromPositions: (positions) => {
    const totalPnl = positions.reduce((sum, p) => sum + (p.pnl || 0), 0);
    const totalInvested = positions.reduce(
      (sum, p) => sum + Math.abs(p.averagePrice * p.quantity),
      0,
    );
    const totalPnlPercent = totalInvested > 0 ? (totalPnl / totalInvested) * 100 : 0;
    set({ totalPnl, totalPnlPercent, positionCount: positions.length });
  },
  updateFromFunds: (funds) => {
    set({
      usedMargin: funds.usedMargin || 0,
      availableMargin: funds.availableCash || 0,
    });
  },
  setOpenOrderCount: (count) => set({ openOrderCount: count }),
  resetSessionState: () => set(EMPTY_TRADING_SESSION),
});

export const useTradingStore = import.meta.env.DEV
  ? create<TradingStore>()(devtools(storeImpl, { name: "trading" }))
  : create<TradingStore>()(storeImpl);
