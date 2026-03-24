import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import type { StateCreator } from "zustand";
import type {
  SkillLevel,
  Domain,
  DomainMetrics,
  HelpPrefs,
  UpgradeSuggestion,
} from "@/types/skill";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const defaultMetrics = (): DomainMetrics => ({
  trade: { ordersPlaced: 0, widgetsUsed: 0, daysActive: 0, lastActiveDate: "" },
  invest: { holdingsViewed: 0, sipsCreated: 0, goalsSet: 0 },
  learn: { lessonsCompleted: 0, quizzesPassed: 0, articlesRead: 0 },
  lab: { backtestsRun: 0, strategiesCreated: 0, optimizationsRun: 0 },
  automate: { flowsCreated: 0, alertsSet: 0, strategiesUploaded: 0 },
  ai: { questionsAsked: 0, strategiesGenerated: 0, signalsActedOn: 0 },
});

const defaultHelpPrefs = (): HelpPrefs => ({
  inlineHints: true,
  spotlightTours: true,
  aiTutor: true,
});

// ---------------------------------------------------------------------------
// State interface
// ---------------------------------------------------------------------------

export interface SkillState {
  // Core state
  globalLevel: SkillLevel;
  routeOverrides: Partial<Record<Domain, SkillLevel>>;
  helpPrefs: HelpPrefs;
  metrics: DomainMetrics;

  /**
   * Keys in "domain:level" format, e.g. "trade:intermediate".
   * Dismissed suggestions are filtered out of getSuggestions().
   */
  dismissedSuggestions: string[];

  // Actions
  setGlobalLevel: (level: SkillLevel) => void;
  setRouteOverride: (domain: Domain, level: SkillLevel) => void;
  clearRouteOverride: (domain: Domain) => void;
  setHelpPref: (key: keyof HelpPrefs, value: boolean) => void;
  /**
   * Increment a named counter for a domain.
   * E.g. trackAction("trade", "ordersPlaced") increments metrics.trade.ordersPlaced.
   * Unknown action names are silently ignored.
   */
  trackAction: (domain: Domain, action: string) => void;
  dismissSuggestion: (key: string) => void;
  resetToDefaults: () => void;

  // Computed selectors (non-persisted, derived at call time)
  /**
   * Returns the per-domain override if one is set,
   * otherwise falls back to globalLevel.
   */
  getEffectiveLevel: (domain: Domain) => SkillLevel;
  /**
   * Returns upgrade suggestions based on behavior thresholds.
   * Thresholds are defined in lib/upgradeThresholds.ts (Task 3).
   * Returns an empty array until that module is wired up.
   */
  getSuggestions: () => UpgradeSuggestion[];
}

// ---------------------------------------------------------------------------
// Default / initial state snapshot (reused by resetToDefaults)
// ---------------------------------------------------------------------------

const defaultState = {
  globalLevel: "beginner" as SkillLevel,
  routeOverrides: {} as Partial<Record<Domain, SkillLevel>>,
  helpPrefs: defaultHelpPrefs(),
  metrics: defaultMetrics(),
  dismissedSuggestions: [] as string[],
};

// ---------------------------------------------------------------------------
// Store implementation
// ---------------------------------------------------------------------------

const storeImpl: StateCreator<SkillState, [["zustand/persist", unknown]]> = (
  set,
  get,
) => ({
  ...defaultState,

  setGlobalLevel: (level) => set({ globalLevel: level }),

  setRouteOverride: (domain, level) =>
    set((state) => ({
      routeOverrides: { ...state.routeOverrides, [domain]: level },
    })),

  clearRouteOverride: (domain) =>
    set((state) => {
      const next = { ...state.routeOverrides };
      delete next[domain];
      return { routeOverrides: next };
    }),

  setHelpPref: (key, value) =>
    set((state) => ({ helpPrefs: { ...state.helpPrefs, [key]: value } })),

  trackAction: (domain, action) =>
    set((state) => {
      const domainMetrics = state.metrics[domain] as Record<string, unknown>;
      // Only increment if the key exists and is currently a number
      if (typeof domainMetrics[action] !== "number") return state;
      return {
        metrics: {
          ...state.metrics,
          [domain]: {
            ...domainMetrics,
            [action]: (domainMetrics[action] as number) + 1,
          },
        },
      };
    }),

  dismissSuggestion: (key) =>
    set((state) => ({
      dismissedSuggestions: [...state.dismissedSuggestions, key],
    })),

  resetToDefaults: () =>
    set({
      globalLevel: defaultState.globalLevel,
      routeOverrides: {},
      helpPrefs: defaultHelpPrefs(),
      metrics: defaultMetrics(),
      dismissedSuggestions: [],
    }),

  getEffectiveLevel: (domain) => {
    const { routeOverrides, globalLevel } = get();
    return routeOverrides[domain] ?? globalLevel;
  },

  // Thresholds will be imported from lib/upgradeThresholds.ts in Task 3.
  getSuggestions: () => [],
});

// ---------------------------------------------------------------------------
// Persist config — only data fields, not computed functions
// ---------------------------------------------------------------------------

const persistedStore = persist(storeImpl, {
  name: "flinttrade:skill",
  version: 1,
  partialize: (state) => ({
    globalLevel: state.globalLevel,
    routeOverrides: state.routeOverrides,
    helpPrefs: state.helpPrefs,
    metrics: state.metrics,
    dismissedSuggestions: state.dismissedSuggestions,
  }),
});

// ---------------------------------------------------------------------------
// Export — devtools enabled in dev mode only (matches settingsStore pattern)
// ---------------------------------------------------------------------------

export const useSkillStore = import.meta.env.DEV
  ? create<SkillState>()(devtools(persistedStore, { name: "skill" }))
  : create<SkillState>()(persistedStore);
