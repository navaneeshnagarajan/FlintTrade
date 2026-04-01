import { create } from "zustand";
import { devtools, persist, createJSONStorage } from "zustand/middleware";
import type { StateCreator } from "zustand";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type AppMode = "demo" | "sandbox" | "live";

interface ModeStore {
  mode: AppMode;
  setMode: (mode: AppMode) => void;
  /**
   * Returns true when switching TO `target` requires PIN entry.
   * Only "live" mode requires PIN confirmation.
   */
  requiresPinForMode: (target: AppMode) => boolean;
}

// ---------------------------------------------------------------------------
// Store implementation
// ---------------------------------------------------------------------------

const storeImpl: StateCreator<ModeStore, [["zustand/persist", unknown]]> = (
  set
) => ({
  mode: "demo",

  setMode: (mode) => set({ mode }),

  requiresPinForMode: (target) => target === "live",
});

const persistedStore = persist(storeImpl, {
  name: "flinttrade:mode",
  version: 1,
  // Session-only: mode resets when browser closes
  storage: createJSONStorage(() => sessionStorage),
});

export const useModeStore = import.meta.env.DEV
  ? create<ModeStore>()(devtools(persistedStore, { name: "mode" }))
  : create<ModeStore>()(persistedStore);
