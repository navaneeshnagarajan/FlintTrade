import { create } from "zustand";
import { devtools } from "zustand/middleware";
import type { StateCreator } from "zustand";
import type { Position, Funds } from "@/types/api";

import { useAccountReadContext } from "@/hooks/useAccountReadsEnabled";
import type { AccountQueryAvailability } from "@/lib/accountQueryState";

export type AggregateStatus = AccountQueryAvailability;

interface AccountSnapshot {
  scopeKey: string | null;
  fundsStatus: AggregateStatus;
  positionsStatus: AggregateStatus;
  funds?: Funds;
  positions?: Position[];
}

interface TradingStore {
  scopeKey: string | null;
  fundsStatus: AggregateStatus;
  positionsStatus: AggregateStatus;
  syncAccountSnapshot: (snapshot: AccountSnapshot) => void;
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
  scopeKey: null as string | null,
  fundsStatus: "unavailable" as AggregateStatus,
  positionsStatus: "unavailable" as AggregateStatus,
  totalPnl: 0,
  totalPnlPercent: 0,
  positionCount: 0,
  openOrderCount: 0,
  usedMargin: 0,
  availableMargin: 0,
};

function aggregatePositions(positions: readonly Position[] = []) {
  let totalPnl = 0;
  let invested = 0;
  let positionCount = 0;
  for (const position of positions) {
    totalPnl += position.pnl || 0;
    invested += Math.abs(position.averagePrice * position.quantity);
    if (position.quantity !== 0) positionCount += 1;
  }
  return {
    totalPnl,
    totalPnlPercent: invested > 0 ? (totalPnl / invested) * 100 : 0,
    positionCount,
  };
}

function aggregateFunds(funds?: Funds) {
  return { availableMargin: funds?.availableCash ?? 0, usedMargin: funds?.usedMargin ?? 0 };
}

const storeImpl: StateCreator<TradingStore> = (set) => ({
  ...EMPTY_TRADING_SESSION,
  // One atomic publication: neither resource can retain a foreign generation.
  syncAccountSnapshot: ({ scopeKey, fundsStatus, positionsStatus, funds, positions }) => {
    set((state) => ({
      scopeKey, fundsStatus, positionsStatus,
      ...aggregatePositions(positions),
      ...aggregateFunds(funds),
      openOrderCount: state.scopeKey === scopeKey ? state.openOrderCount : 0,
    }));
  },
  updateFromPositions: (positions) => set(aggregatePositions(positions)),
  updateFromFunds: (funds) => set(aggregateFunds(funds)),
  setOpenOrderCount: (count) => set({ openOrderCount: count }),
  resetSessionState: () => set(EMPTY_TRADING_SESSION),
});

export const useTradingStore = import.meta.env.DEV
  ? create<TradingStore>()(devtools(storeImpl, { name: "trading" }))
  : create<TradingStore>()(storeImpl);

/** Guard presentation during the render before the app-root mirror effect. */
export function useCurrentTradingState() {
  const context = useAccountReadContext();
  const state = useTradingStore();
  if (state.scopeKey !== context.identity.scopeKey) {
    const status: AggregateStatus = state.scopeKey !== null && context.enabled ? "loading" : "unavailable";
    return { ...EMPTY_TRADING_SESSION, fundsStatus: status, positionsStatus: status };
  }
  if (!context.enabled) {
    return {
      ...state,
      fundsStatus: state.fundsStatus === "ready" || state.fundsStatus === "stale" ? "stale" as const : "unavailable" as const,
      positionsStatus: state.positionsStatus === "ready" || state.positionsStatus === "stale" ? "stale" as const : "unavailable" as const,
    };
  }
  return state;
}
