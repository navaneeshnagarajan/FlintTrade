import { create } from "zustand";
import { devtools } from "zustand/middleware";
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

export const useTradingStore = create<TradingStore>()(
  devtools(
    (set) => ({
      totalPnl: 0,
      totalPnlPercent: 0,
      positionCount: 0,
      openOrderCount: 0,
      usedMargin: 0,
      availableMargin: 0,
      updateFromPositions: (positions) => {
        const totalPnl = positions.reduce((sum, p) => sum + (p.pnl || 0), 0);
        set({ totalPnl, positionCount: positions.length }, false, "updateFromPositions");
      },
      updateFromFunds: (funds) => {
        set({
          usedMargin: funds.usedMargin || 0,
          availableMargin: funds.availableCash || 0,
        }, false, "updateFromFunds");
      },
      setOpenOrderCount: (count) => set({ openOrderCount: count }, false, "setOpenOrderCount"),
    }),
    { name: "trading" }
  )
);
