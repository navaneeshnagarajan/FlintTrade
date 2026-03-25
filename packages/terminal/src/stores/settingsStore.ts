import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import type { StateCreator } from "zustand";

// ---------------------------------------------------------------------------
// Sub-interfaces
// ---------------------------------------------------------------------------

interface RiskLimits {
  maxPositionLots: number;
  mtmStoploss: number;
  mtmTarget: number;
  maxOrdersPerMinute: number;
}

interface LLMSettings {
  provider: string;
  model: string;
  host: string;
  apiKey: string;
}

export interface TelegramSettings {
  enabled: boolean;
  botToken: string;
  chatId: string;
}

export interface DataPaths {
  fastStoragePath: string;
  archiveStoragePath: string;
}

// ---------------------------------------------------------------------------
// Store interface (v4 — theme removed, new fields added)
// ---------------------------------------------------------------------------

interface SettingsStore {
  persona: "trader" | "investor" | "beginner";
  density: "compact" | "comfortable";
  fontSize: "small" | "normal" | "large";
  defaultExchange: string;
  defaultProduct: string;
  defaultQty: number;
  defaultOrderType: string;
  riskLimits: RiskLimits;
  llm: LLMSettings;
  telegram: TelegramSettings;
  dataPaths: DataPaths;
  name: string;
  interests: string[];
  experience: "beginner" | "intermediate" | "pro" | "custom";
  lastOpenTimestamp: number;
  sandboxMode: boolean;

  // Actions
  setPersona: (persona: "trader" | "investor" | "beginner") => void;
  setDensity: (density: "compact" | "comfortable") => void;
  setFontSize: (fontSize: "small" | "normal" | "large") => void;
  setTradingDefaults: (defaults: Partial<Pick<SettingsStore, "defaultExchange" | "defaultProduct" | "defaultQty" | "defaultOrderType">>) => void;
  setRiskLimits: (limits: Partial<RiskLimits>) => void;
  setLLM: (llm: Partial<LLMSettings>) => void;
  setTelegram: (telegram: Partial<TelegramSettings>) => void;
  setDataPaths: (dataPaths: Partial<DataPaths>) => void;
  setName: (name: string) => void;
  setInterests: (interests: string[]) => void;
  setExperience: (exp: "beginner" | "intermediate" | "pro" | "custom") => void;
  setLastOpenTimestamp: (ts: number) => void;
  setSandboxMode: (enabled: boolean) => void;
}

// ---------------------------------------------------------------------------
// Store implementation
// ---------------------------------------------------------------------------

const storeImpl: StateCreator<SettingsStore, [["zustand/persist", unknown]]> = (set) => ({
  persona: "trader",
  density: "compact",
  fontSize: "normal",
  defaultExchange: "NFO",
  defaultProduct: "MIS",
  defaultQty: 1,
  defaultOrderType: "MARKET",
  riskLimits: {
    maxPositionLots: 10,
    mtmStoploss: 5000,
    mtmTarget: 10000,
    maxOrdersPerMinute: 30,
  },
  llm: {
    provider: "",
    model: "",
    host: "",
    apiKey: "",
  },
  telegram: {
    enabled: false,
    botToken: "",
    chatId: "",
  },
  dataPaths: {
    fastStoragePath: "",
    archiveStoragePath: "",
  },
  name: "Trader",
  interests: [],
  experience: "intermediate",
  lastOpenTimestamp: 0,
  sandboxMode: false,

  setPersona: (persona) => set({ persona }),
  setDensity: (density) => set({ density }),
  setFontSize: (fontSize) => set({ fontSize }),
  setTradingDefaults: (defaults) => set((state) => ({ ...state, ...defaults })),
  setRiskLimits: (limits) =>
    set((state) => ({ riskLimits: { ...state.riskLimits, ...limits } })),
  setLLM: (llm) =>
    set((state) => ({ llm: { ...state.llm, ...llm } })),
  setTelegram: (telegram) =>
    set((state) => ({ telegram: { ...state.telegram, ...telegram } })),
  setDataPaths: (dataPaths) =>
    set((state) => ({ dataPaths: { ...state.dataPaths, ...dataPaths } })),
  setName: (name) => set({ name }),
  setInterests: (interests) => set({ interests }),
  setExperience: (experience) => set({ experience }),
  setLastOpenTimestamp: (lastOpenTimestamp) => set({ lastOpenTimestamp }),
  setSandboxMode: (sandboxMode) => set({ sandboxMode }),
});

// ---------------------------------------------------------------------------
// Persist with migration v3 → v4
// ---------------------------------------------------------------------------

const persistedStore = persist(storeImpl, {
  name: "flinttrade:settings",
  version: 4,
  migrate: (persistedState: unknown, version: number) => {
    // IMPORTANT: Zustand calls migrate ONCE with the stored version number.
    // All blocks must fall through so a v1 user reaches v4 in a single call.
    // Each block mutates `state` in place and the final return emits the result.
    let state = persistedState as Record<string, unknown>;

    // v1 → v2: add profile fields
    if (version < 2) {
      state = {
        ...state,
        name: "Trader",
        interests: [],
        experience: "intermediate",
        lastOpenTimestamp: 0,
      };
    }

    // v2 → v3: normalize old "dark" theme alias (theme field is deleted in v4 step)
    if (version < 3) {
      const oldTheme = state.theme as string | undefined;
      state = {
        ...state,
        theme: oldTheme === "dark" || !oldTheme ? "midnight" : oldTheme,
      };
    }

    // v3 → v4: rename maxOrdersPerMin, fix google→gemini, add new fields, remove theme
    if (version < 4) {
      // Rename maxOrdersPerMin → maxOrdersPerMinute
      const oldRisk = state.riskLimits as Record<string, unknown> | undefined;
      const migratedRisk: RiskLimits = {
        maxPositionLots: (oldRisk?.maxPositionLots as number) ?? 10,
        mtmStoploss: (oldRisk?.mtmStoploss as number) ?? 5000,
        mtmTarget: (oldRisk?.mtmTarget as number) ?? 10000,
        maxOrdersPerMinute:
          (oldRisk?.maxOrdersPerMinute as number) ??
          (oldRisk?.maxOrdersPerMin as number) ??
          30,
      };

      // Fix provider: "google" → "gemini"
      const oldLlm = state.llm as Record<string, unknown> | undefined;
      const migratedLlm: LLMSettings = {
        provider: oldLlm?.provider === "google" ? "gemini" : ((oldLlm?.provider as string) ?? ""),
        model: (oldLlm?.model as string) ?? "",
        host: (oldLlm?.host as string) ?? "",
        apiKey: (oldLlm?.apiKey as string) ?? "",
      };

      // Remove the "flinttrade:appearance" localStorage key (was separate)
      try {
        localStorage.removeItem("flinttrade:appearance");
      } catch {
        // Silently ignore in environments without localStorage (tests, SSR)
      }

      // Build v4 state — explicitly exclude theme
      const { theme: _theme, ...rest } = state as Record<string, unknown> & { theme?: unknown };

      state = {
        ...rest,
        riskLimits: migratedRisk,
        llm: migratedLlm,
        fontSize: (state.fontSize as string) ?? "normal",
        defaultOrderType: (state.defaultOrderType as string) ?? "MARKET",
        telegram: {
          enabled: false,
          botToken: "",
          chatId: "",
          ...((state.telegram as Record<string, unknown>) ?? {}),
        } as TelegramSettings,
        dataPaths: {
          fastStoragePath: "",
          archiveStoragePath: "",
          ...((state.dataPaths as Record<string, unknown>) ?? {}),
        } as DataPaths,
      };
    }

    return state;
  },
});

export const useSettingsStore = import.meta.env.DEV
  ? create<SettingsStore>()(devtools(persistedStore, { name: "settings" }))
  : create<SettingsStore>()(persistedStore);
