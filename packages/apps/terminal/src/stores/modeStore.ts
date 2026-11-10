import { create } from "zustand";
import { devtools, persist, createJSONStorage } from "zustand/middleware";
import type { StateCreator } from "zustand";
import { z } from "zod";
import {
  isAppMode,
  sessionModeFromPersistedSession,
  sessionModeFromToken,
  type AppMode,
  type SessionMode,
} from "@/lib/modeClaim";
import { readPersistedAuthSession } from "@/lib/homeEntry";
import { safeParse } from "@/lib/safeParse";

export type { AppMode, SessionMode };

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Application operating mode.
 *  - explore:  Demo/sample data, no broker connection required (was "demo")
 *  - practice: Paper trading in the FlintTrade sandbox (was "sandbox")
 *  - live:     Real money, requires PIN confirmation on every mode switch
 *
 *  `unavailable` is not a trading mode. It means the session token has no
 *  usable mode claim. It must not be treated as Live.
 */

interface ModeStore {
  mode: SessionMode;
  setMode: (mode: AppMode) => void;
  /** Copy a JWT mode claim into the store. Opaque tokens are left unchanged. */
  adoptSessionToken: (token: string | null | undefined) => void;
  /** Returns true when switching TO `target` requires PIN entry.
   *  Only "live" mode requires PIN confirmation. */
  requiresPinForMode: (target: AppMode) => boolean;
  /** Convenience getter — true when mode is "practice". */
  isPractice: () => boolean;
}

// ---------------------------------------------------------------------------
// v1 → v2 migration (sessionStorage → localStorage, renamed modes)
// ---------------------------------------------------------------------------

const v1ModeSchema = z.object({
  state: z.object({ mode: z.string() }).optional(),
}).optional();

/** Desk mode when `flinttrade:mode` has no record. Explore is example data, not the signed-in default. */
export const INITIAL_MODE: AppMode = "practice";

function migrateFromV1(): AppMode {
  const raw = sessionStorage.getItem("flinttrade:mode");
  if (!raw) return "explore";
  const parsed = safeParse(raw, v1ModeSchema);
  const old = parsed?.state?.mode;
  if (old === "live") return "live";
  if (old === "sandbox") return "practice";
  // "demo", corrupt, or anything else → explore
  return "explore";
}

// ---------------------------------------------------------------------------
// Store implementation
// ---------------------------------------------------------------------------

function bootMode(): SessionMode {
  return sessionModeFromPersistedSession() ?? INITIAL_MODE;
}

const storeImpl: StateCreator<ModeStore, [["zustand/persist", unknown]]> = (
  set,
  get
) => ({
  mode: bootMode(),

  setMode: (mode) => set({ mode }),

  adoptSessionToken: (token) => {
    const claim = sessionModeFromToken(token);
    if (!claim) return;
    set({ mode: claim });
  },

  requiresPinForMode: (target) => target === "live",

  isPractice: () => get().mode === "practice",
});

const persistedStore = persist(storeImpl, {
  name: "flinttrade:mode",
  version: 2,
  storage: createJSONStorage(() => localStorage),
  // The JWT claim wins. The cache is applied only when this tab has no session.
  merge: (persistedState, currentState) => {
    const claim = sessionModeFromPersistedSession();
    const cached = (persistedState as { mode?: unknown } | undefined)?.mode;
    const mode: SessionMode = claim ?? (isAppMode(cached) ? cached : currentState.mode);
    return { ...currentState, mode };
  },
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
    if (!state) return;
    const session = readPersistedAuthSession();
    const claim = session ? sessionModeFromToken(session.token) : null;
    if (claim) {
      // Rewrite the cache after the claim is assigned. A stale live entry
      // must not survive a Practice session.
      state.adoptSessionToken(session?.token);
      return;
    }
    // On first load, if localStorage holds nothing (version < 2), attempt
    // to recover the last mode from the old sessionStorage key. A session
    // claim, when one exists, already won above.
    if (state.mode === "explore") {
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
