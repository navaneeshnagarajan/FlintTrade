import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import type { StateCreator } from "zustand";

interface RiskLimits {
  maxPositionLots: number;
  mtmStoploss: number;
  mtmTarget: number;
  maxOrdersPerMin: number;
}

interface LLMSettings {
  provider: string;
  model: string;
}

type ThemeId = "midnight" | "obsidian" | "terminal-green" | "ocean-blue" | "light";

interface SettingsStore {
  persona: "trader" | "investor" | "beginner";
  theme: ThemeId;
  density: "compact" | "comfortable";
  defaultExchange: string;
  defaultProduct: string;
  defaultQty: number;
  riskLimits: RiskLimits;
  llm: LLMSettings;
  name: string;
  interests: string[];
  experience: "beginner" | "intermediate" | "pro" | "custom";
  lastOpenTimestamp: number;
  setPersona: (persona: "trader" | "investor" | "beginner") => void;
  setTheme: (theme: ThemeId) => void;
  setDensity: (density: "compact" | "comfortable") => void;
  setTradingDefaults: (defaults: Partial<Pick<SettingsStore, "defaultExchange" | "defaultProduct" | "defaultQty">>) => void;
  setRiskLimits: (limits: Partial<RiskLimits>) => void;
  setLLM: (llm: Partial<LLMSettings>) => void;
  setName: (name: string) => void;
  setInterests: (interests: string[]) => void;
  setExperience: (exp: "beginner" | "intermediate" | "pro" | "custom") => void;
  setLastOpenTimestamp: (ts: number) => void;
}

// Inner StateCreator (no middleware mutators — persist is applied outside)
const storeImpl: StateCreator<SettingsStore, [["zustand/persist", unknown]]> = (set) => ({
  persona: "trader",
  theme: "midnight" as const,
  density: "compact",
  defaultExchange: "NFO",
  defaultProduct: "MIS",
  defaultQty: 1,
  riskLimits: {
    maxPositionLots: 10,
    mtmStoploss: 5000,
    mtmTarget: 10000,
    maxOrdersPerMin: 30,
  },
  llm: {
    provider: "",
    model: "",
  },
  name: "Trader",
  interests: [],
  experience: "intermediate",
  lastOpenTimestamp: 0,
  setPersona: (persona) => set({ persona }),
  setTheme: (theme) => set({ theme }),
  setDensity: (density) => set({ density }),
  setTradingDefaults: (defaults) => set((state) => ({ ...state, ...defaults })),
  setRiskLimits: (limits) =>
    set((state) => ({ riskLimits: { ...state.riskLimits, ...limits } })),
  setLLM: (llm) =>
    set((state) => ({ llm: { ...state.llm, ...llm } })),
  setName: (name) => set({ name }),
  setInterests: (interests) => set({ interests }),
  setExperience: (experience) => set({ experience }),
  setLastOpenTimestamp: (lastOpenTimestamp) => set({ lastOpenTimestamp }),
});

const persistedStore = persist(storeImpl, {
  name: "flinttrade:settings",
  version: 3,
  migrate: (persistedState: unknown, version: number) => {
    const state = persistedState as Record<string, unknown>;
    if (version < 2) {
      return {
        ...state,
        name: "Trader",
        interests: [],
        experience: "intermediate",
        lastOpenTimestamp: 0,
        theme: "midnight",
      };
    }
    if (version < 3) {
      // Migrate old "dark" theme value to "midnight"
      const oldTheme = state.theme;
      return {
        ...state,
        theme: oldTheme === "dark" || !oldTheme ? "midnight" : oldTheme,
      };
    }
    return state;
  },
});

export const useSettingsStore = import.meta.env.DEV
  ? create<SettingsStore>()(devtools(persistedStore, { name: "settings" }))
  : create<SettingsStore>()(persistedStore);
