import { create } from "zustand";
import { devtools, persist, createJSONStorage } from "zustand/middleware";
import type { StateCreator } from "zustand";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Application operating mode.
 *  - explore:  Demo/sample data, no broker connection required (was "demo")
 *  - practice: Paper trading against a live broker sandbox (was "sandbox")
 *  - live:     Real money, requires PIN confirmation on every mode switch
 */
export type AppMode = "explore" | "practice" | "live";

interface ModeStore {
  mode: AppMode;
  setMode: (mode: AppMode) => void;
  /** Returns true when switching TO `target` requires PIN entry.
   *  Only "live" mode requires PIN confirmation. */
  requiresPinForMode: (target: AppMode) => boolean;
  /** Convenience getter — true when mode is "practice". */
  isPractice: () => boolean;
}

// ---------------------------------------------------------------------------
// v1 → v2 migration (sessionStorage → localStorage, renamed modes)
// ---------------------------------------------------------------------------

function migrateFromV1(): AppMode {
  try {
    const raw = sessionStorage.getItem("flinttrade:mode");
    if (!raw) return "explore";
    const parsed = JSON.parse(raw) as { state?: { mode?: string } };
    const old = parsed?.state?.mode;
    if (old === "live") return "live";
    if (old === "sandbox") return "practice";
    // "demo" or anything else → explore
    return "explore";
  } catch {
    // Ignore parse errors or missing sessionStorage in test environments
    return "explore";
  }
}

// ---------------------------------------------------------------------------
// Store implementation
// ---------------------------------------------------------------------------

const storeImpl: StateCreator<ModeStore, [["zustand/persist", unknown]]> = (
  set,
  get
) => ({
  mode: "explore",

  setMode: (mode) => set({ mode }),

  requiresPinForMode: (target) => target === "live",

  isPractice: () => get().mode === "practice",
});

const persistedStore = persist(storeImpl, {
  name: "flinttrade:mode",
  version: 2,
  storage: createJSONStorage(() => localStorage),
  migrate: (persistedState: unknown, version: number) => {
    // v1 stored an older shape in sessionStorage; v2 uses localStorage.
    // If Zustand finds a v1 record somehow (e.g. via a cross-tab read),
    // re-map the legacy mode names to the new vocabulary.
    if (version < 2) {
      const state = persistedState as Record<string, unknown>;
      const old = state?.mode as string | undefined;
      const mapped: AppMode =
        old === "live" ? "live" : old === "sandbox" ? "practice" : "explore";
      return { ...state, mode: mapped };
    }
    return persistedState as Record<string, unknown>;
  },
  onRehydrateStorage: () => (state) => {
    // On first load, if localStorage holds nothing (version < 2), attempt
    // to recover the last mode from the old sessionStorage key.
    if (state && state.mode === "explore") {
      const recovered = migrateFromV1();
      if (recovered !== "explore") {
        state.setMode(recovered);
      }
    }
  },
});

export const useModeStore = import.meta.env.DEV
  ? create<ModeStore>()(devtools(persistedStore, { name: "ModeStore", enabled: true }))
  : create<ModeStore>()(persistedStore);
