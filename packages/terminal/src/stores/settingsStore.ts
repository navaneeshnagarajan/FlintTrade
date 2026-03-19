import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";

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

export const useSettingsStore = create<SettingsStore>()(
  devtools(
    persist(
      (set) => ({
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
        setPersona: (persona) => set({ persona }, false, "setPersona"),
        setDensity: (density) => set({ density }, false, "setDensity"),
        setTradingDefaults: (defaults) =>
          set((state) => ({ ...state, ...defaults }), false, "setTradingDefaults"),
        setRiskLimits: (limits) =>
          set(
            (state) => ({
              riskLimits: { ...state.riskLimits, ...limits },
            }),
            false,
            "setRiskLimits"
          ),
      }),
      { name: "flinttrade:settings" }
    ),
    { name: "settings" }
  )
);
