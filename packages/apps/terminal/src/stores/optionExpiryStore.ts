/**
 * optionExpiryStore — shared selected expiry for Option Chain and OI Chart.
 *
 * UI state only. The expiry *list* still comes from `getExpiry` (TanStack /
 * widget fetch). This store remembers which listed expiry the operator picked
 * for a symbol/exchange so both widgets open on the same contract.
 */

import { useCallback } from "react";
import { create } from "zustand";

import { optionExpiryIdentity } from "@/lib/optionExpiry";

export { optionExpiryIdentity } from "@/lib/optionExpiry";

interface OptionExpiryState {
  selectedByIdentity: Record<string, string>;
  setSelected: (identity: string, expiry: string | null) => void;
}

export const useOptionExpiryStore = create<OptionExpiryState>((set) => ({
  selectedByIdentity: {},
  setSelected: (identity, expiry) => set((state) => {
    if (!expiry) {
      if (!(identity in state.selectedByIdentity)) return state;
      const next = { ...state.selectedByIdentity };
      delete next[identity];
      return { selectedByIdentity: next };
    }
    if (state.selectedByIdentity[identity] === expiry) return state;
    return {
      selectedByIdentity: { ...state.selectedByIdentity, [identity]: expiry },
    };
  }),
}));

/** Reactive selected expiry for one symbol/exchange under a market-data authority. */
export function useSharedOptionExpirySelection(
  dataScope: string,
  symbol: string,
  exchange: string,
): {
  identity: string;
  sharedSelected: string | null;
  publishSelected: (expiry: string | null) => void;
} {
  const identity = optionExpiryIdentity(dataScope, symbol, exchange);
  const sharedSelected = useOptionExpiryStore((state) => state.selectedByIdentity[identity] ?? null);
  const setSelected = useOptionExpiryStore((state) => state.setSelected);
  const publishSelected = useCallback(
    (expiry: string | null) => setSelected(identity, expiry),
    [identity, setSelected],
  );
  return { identity, sharedSelected, publishSelected };
}
