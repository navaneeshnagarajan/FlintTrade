/**
 * valueVisibilityStore.ts
 *
 * Zustand v5 store for the net-worth / portfolio value-visibility (privacy)
 * toggle. When `hidden` is true, monetary figures across the Invest surfaces
 * are masked so a user can share their screen without exposing rupee amounts.
 *
 * UI-only state (per the frontend-state-boundary rule), persisted to
 * localStorage under "flinttrade-value-visibility".
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface ValueVisibilityState {
  /** When true, monetary values are masked in the UI. */
  hidden: boolean;
  toggle: () => void;
  setHidden: (hidden: boolean) => void;
}

export const useValueVisibilityStore = create<ValueVisibilityState>()(
  persist(
    (set) => ({
      hidden: false,
      toggle: () => set((s) => ({ hidden: !s.hidden })),
      setHidden: (hidden: boolean) => set({ hidden }),
    }),
    { name: "flinttrade-value-visibility" },
  ),
);
