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
}

const storeImpl: StateCreator<TradingStore> = (set) => ({
  totalPnl: 0,
  totalPnlPercent: 0,
  positionCount: 0,
  openOrderCount: 0,
  usedMargin: 0,
  availableMargin: 0,
  updateFromPositions: (positions) => {
    const totalPnl = positions.reduce((sum, p) => sum + (p.pnl || 0), 0);
    set({ totalPnl, positionCount: positions.length });
  },
  updateFromFunds: (funds) => {
    set({
      usedMargin: funds.usedMargin || 0,
      availableMargin: funds.availableCash || 0,
    });
  },
  setOpenOrderCount: (count) => set({ openOrderCount: count }),
});

export const useTradingStore = import.meta.env.DEV
  ? create<TradingStore>()(devtools(storeImpl, { name: "trading" }))
  : create<TradingStore>()(storeImpl);
