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
import { evaluateThresholds } from "@/lib/upgradeThresholds";

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
  spotlightTours: false,
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
   * Action names already counted into `widgetsUsed`, so a widget viewed a
   * hundred times still counts once. Persisted — the metric is "distinct
   * widgets you have used", not "views this session".
   */
  seenWidgetActions: string[];

  /**
   * Increment a named counter for a domain.
   *
   * Two shapes are accepted:
   * - A declared metric key — trackAction("trade", "ordersPlaced")
   *   increments metrics.trade.ordersPlaced directly.
   * - A widget-view event — trackAction("trade", "widget_view_<name>")
   *   increments the domain's `widgetsUsed` once per DISTINCT name.
   *   Every widget emits one of these on mount, and for months they were
   *   all silently dropped: `widgetsUsed` gates the trade
   *   intermediate → advanced suggestion at 15, so that suggestion could
   *   never fire.
   *
   * Anything else (fine-grained interaction telemetry like
   * "calculator_tab_sizing") has no declared counter and is a no-op by
   * design — but that is now this documented contract, not an accident.
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
  seenWidgetActions: [] as string[],
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

      // Widget-view events count as "a distinct widget used", once each.
      if (action.startsWith("widget_view_")) {
        if (state.seenWidgetActions.includes(action)) return state;
        if (typeof domainMetrics["widgetsUsed"] !== "number") return state;
        return {
          seenWidgetActions: [...state.seenWidgetActions, action],
          metrics: {
            ...state.metrics,
            [domain]: {
              ...domainMetrics,
              widgetsUsed: (domainMetrics["widgetsUsed"] as number) + 1,
            },
          },
        };
      }

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

  getSuggestions: () => {
    const { metrics, globalLevel, routeOverrides, dismissedSuggestions } = get();
    const domains: Domain[] = ["trade", "invest", "learn", "lab", "automate", "ai"];
    const currentLevels = Object.fromEntries(
      domains.map((d) => [d, routeOverrides[d] ?? globalLevel]),
    ) as Record<Domain, SkillLevel>;

    return evaluateThresholds(metrics, currentLevels)
      .filter((t) => !dismissedSuggestions.includes(`${t.domain}:${t.to}`))
      .map((t) => {
        // Interpolate {placeholder} tokens in the message using domain metrics
        const domainMetrics = metrics[t.domain] as Record<string, number>;
        const reason = t.message.replace(/\{(\w+)\}/g, (_, key) =>
          String(domainMetrics[key] ?? 0),
        );
        return {
          domain: t.domain,
          fromLevel: t.from,
          toLevel: t.to,
          reason,
          timestamp: Date.now(),
        } satisfies UpgradeSuggestion;
      });
  },
});

// ---------------------------------------------------------------------------
// Persist config — only data fields, not computed functions
// ---------------------------------------------------------------------------

const persistedStore = persist(storeImpl, {
  name: "flinttrade:skill",
  version: 2,
  partialize: (state) => ({
    globalLevel: state.globalLevel,
    routeOverrides: state.routeOverrides,
    helpPrefs: state.helpPrefs,
    metrics: state.metrics,
    dismissedSuggestions: state.dismissedSuggestions,
    seenWidgetActions: state.seenWidgetActions,
  }),
  // v1 → v2: seenWidgetActions added so widget_view_* events can feed
  // `widgetsUsed`. Old snapshots simply start with an empty seen-set.
  migrate: (persisted, version) => {
    const state = persisted as Partial<SkillState>;
    if (version < 2 && !Array.isArray(state.seenWidgetActions)) {
      state.seenWidgetActions = [];
    }
    return state as SkillState;
  },
});

// ---------------------------------------------------------------------------
// Export — devtools enabled in dev mode only (matches settingsStore pattern)
// ---------------------------------------------------------------------------

export const useSkillStore = import.meta.env.DEV
  ? create<SkillState>()(devtools(persistedStore, { name: "skill" }))
  : create<SkillState>()(persistedStore);
