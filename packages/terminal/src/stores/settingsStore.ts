import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import type { StateCreator } from "zustand";

interface RiskLimits {
  maxPositionLots: number;
  mtmStoploss: number;
  mtmTarget: number;
  maxOrdersPerMin: number;
}

interface SettingsStore {
  persona: "trader" | "investor" | "beginner";
  theme: "dark";
  density: "compact" | "comfortable";
  defaultExchange: string;
  defaultProduct: string;
  defaultQty: number;
  riskLimits: RiskLimits;
  setPersona: (persona: "trader" | "investor" | "beginner") => void;
  setDensity: (density: "compact" | "comfortable") => void;
  setTradingDefaults: (defaults: Partial<Pick<SettingsStore, "defaultExchange" | "defaultProduct" | "defaultQty">>) => void;
  setRiskLimits: (limits: Partial<RiskLimits>) => void;
}

// Inner StateCreator (no middleware mutators — persist is applied outside)
const storeImpl: StateCreator<SettingsStore, [["zustand/persist", unknown]]> = (set) => ({
  persona: "trader",
  theme: "dark" as const,
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
  setPersona: (persona) => set({ persona }),
  setDensity: (density) => set({ density }),
  setTradingDefaults: (defaults) => set((state) => ({ ...state, ...defaults })),
  setRiskLimits: (limits) =>
    set((state) => ({ riskLimits: { ...state.riskLimits, ...limits } })),
});

const persistedStore = persist(storeImpl, { name: "flinttrade:settings" });

export const useSettingsStore = import.meta.env.DEV
  ? create<SettingsStore>()(devtools(persistedStore, { name: "settings" }))
  : create<SettingsStore>()(persistedStore);
