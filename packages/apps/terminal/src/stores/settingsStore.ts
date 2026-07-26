import { create } from "zustand";
import { devtools, persist } from "zustand/middleware";
import type { StateCreator } from "zustand";
import { normaliseLlmHost } from "@/lib/llmProviders";
import type { LlmAuthMode } from "@/lib/llmProviders";

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
  authMode: LlmAuthMode;
  model: string;
  host: string;
  apiKey: string;
}

function normaliseLlmSettings(settings: LLMSettings): LLMSettings {
  const provider = settings.provider.trim() || "ollama";
  return {
    ...settings,
    authMode: provider === "anthropic" && settings.authMode === "claude-code-oauth"
      ? "claude-code-oauth"
      : "api-key",
    host: normaliseLlmHost(provider, settings.host),
    // Credentials live only in component-local drafts and the backend secret
    // file. Shared frontend state never owns a raw credential.
    apiKey: "",
  };
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
// Store interface (v6 — ticker fields added)
// ---------------------------------------------------------------------------

export type TickerMode = "off" | "pinned" | "scroll" | "marquee";

export const DEFAULT_TICKER_SYMBOLS: string[] = [
  "NSE_INDEX:NIFTY",
  "BSE_INDEX:SENSEX",
  "NSE_INDEX:BANKNIFTY",
  "NSE_INDEX:INDIAVIX",
  "MCX:GOLD",
  "MCX:SILVER",
  "MCX:CRUDEOIL",
  "MCX:NATURALGAS",
];

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
  llmSetupPending: boolean;
  telegram: TelegramSettings;
  dataPaths: DataPaths;
  name: string;
  interests: string[];
  experience: "beginner" | "intermediate" | "pro" | "custom";
  lastOpenTimestamp: number;

  // Ticker settings (added v6)
  tickerMode: TickerMode;
  tickerSymbols: string[];
  tickerSpeed: number; // marquee animation duration in seconds (default 30)

  // Actions
  setPersona: (persona: "trader" | "investor" | "beginner") => void;
  setDensity: (density: "compact" | "comfortable") => void;
  setFontSize: (fontSize: "small" | "normal" | "large") => void;
  setTradingDefaults: (defaults: Partial<Pick<SettingsStore, "defaultExchange" | "defaultProduct" | "defaultQty" | "defaultOrderType">>) => void;
  setRiskLimits: (limits: Partial<RiskLimits>) => void;
  setLLM: (llm: Partial<LLMSettings>) => void;
  setLLMSetupDraft: (
    llm: Pick<LLMSettings, "provider" | "model" | "host"> & Partial<Pick<LLMSettings, "authMode">>,
  ) => void;
  clearLLMSetupDraft: () => void;
  setTelegram: (telegram: Partial<TelegramSettings>) => void;
  setDataPaths: (dataPaths: Partial<DataPaths>) => void;
  setName: (name: string) => void;
  setInterests: (interests: string[]) => void;
  setExperience: (exp: "beginner" | "intermediate" | "pro" | "custom") => void;
  setLastOpenTimestamp: (ts: number) => void;
  setTickerMode: (mode: TickerMode) => void;
  setTickerSymbols: (symbols: string[]) => void;
  setTickerSpeed: (speed: number) => void;
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
    authMode: "api-key",
    model: "",
    host: "",
    apiKey: "",
  },
  llmSetupPending: false,
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

  // Ticker defaults (v6)
  tickerMode: "marquee",
  tickerSymbols: DEFAULT_TICKER_SYMBOLS,
  tickerSpeed: 30,

  setPersona: (persona) => set({ persona }),
  setDensity: (density) => set({ density }),
  setFontSize: (fontSize) => set({ fontSize }),
  setTradingDefaults: (defaults) => set((state) => ({ ...state, ...defaults })),
  setRiskLimits: (limits) =>
    set((state) => ({ riskLimits: { ...state.riskLimits, ...limits } })),
  setLLM: (llm) =>
    set((state) => ({ llm: normaliseLlmSettings({ ...state.llm, ...llm }) })),
  setLLMSetupDraft: (llm) => set({
    llm: normaliseLlmSettings({ authMode: "api-key", ...llm, apiKey: "" }),
    llmSetupPending: true,
  }),
  clearLLMSetupDraft: () => set({ llmSetupPending: false }),
  setTelegram: (telegram) =>
    set((state) => ({ telegram: { ...state.telegram, ...telegram } })),
  setDataPaths: (dataPaths) =>
    set((state) => ({ dataPaths: { ...state.dataPaths, ...dataPaths } })),
  setName: (name) => set({ name }),
  setInterests: (interests) => set({ interests }),
  setExperience: (experience) => set({ experience }),
  setLastOpenTimestamp: (lastOpenTimestamp) => set({ lastOpenTimestamp }),
  setTickerMode: (tickerMode) => set({ tickerMode }),
  setTickerSymbols: (tickerSymbols) => set({ tickerSymbols }),
  setTickerSpeed: (tickerSpeed) => set({ tickerSpeed }),
});

// ---------------------------------------------------------------------------
// Persist with migration chain v1 → v5
// ---------------------------------------------------------------------------

const persistedStore = persist(storeImpl, {
  name: "flinttrade:settings",
  version: 11,
  partialize: (state) => {
    const { llm, telegram, ...rest } = state;
    return {
      ...rest,
      llm: { ...llm, apiKey: "" },         // never persist LLM API key to localStorage
      telegram: { ...telegram, botToken: "" }, // never persist bot token to localStorage
    };
  },
  migrate: (persistedState: unknown, version: number) => {
    // IMPORTANT: Zustand calls migrate ONCE with the stored version number.
    // All blocks must fall through so a v1 user reaches v5 in a single call.
    // Each block spreads/mutates `state` and the final return emits the result.
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

    // v2 → v3: normalise old "dark" theme alias (theme field is deleted in v4 step)
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
        authMode: "api-key",
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

    // v4 → v5: drop sandboxMode — mode ownership transferred to modeStore
    if (version < 5) {
      const { sandboxMode: _sandboxMode, ...rest } = state as Record<string, unknown> & { sandboxMode?: unknown };
      state = rest;
    }

    // v5 → v6: add ticker fields
    if (version < 6) {
      state = {
        ...state,
        tickerMode: "marquee" as TickerMode,
        tickerSymbols: DEFAULT_TICKER_SYMBOLS,
        tickerSpeed: 30,
      };
    }

    // v6 → v7: previously added the WhatsApp settings section. WhatsApp
    // alerting was retired in the dedup wave, so this step is now a no-op —
    // any persisted whatsapp key is stripped by the v10 → v11 step below.

    // v7 -> v8: retire the named LM Studio integration in favour of the
    // application-managed Ollama runtime, regardless of the legacy endpoint.
    if (version < 8) {
      const oldLlm = (state.llm as Record<string, unknown> | undefined) ?? {};
      const provider = String(oldLlm.provider ?? "").trim().toLowerCase();
      if (provider === "lmstudio") {
        state = {
          ...state,
          llm: {
            ...oldLlm,
            provider: "ollama",
            host: "",
            apiKey: "",
          } as LLMSettings,
        };
      }
    }

    // v8 -> v9: managed Ollama's endpoint is runtime-owned and must never be
    // persisted in frontend state. Also accept LM Studio values that reached a
    // v8 snapshot without the earlier migration having run.
    if (version < 9) {
      const oldLlm = (state.llm as Record<string, unknown> | undefined) ?? {};
      let provider = String(oldLlm.provider ?? "").trim().toLowerCase();
      let host = String(oldLlm.host ?? "").trim().replace(/\/$/, "");
      if (provider === "lmstudio") {
        provider = "ollama";
        host = "";
      }
      if (provider === "ollama") host = "";
      state = {
        ...state,
        llm: {
          ...oldLlm,
          provider,
          host,
          apiKey: provider === "ollama" ? "" : String(oldLlm.apiKey ?? ""),
        } as LLMSettings,
      };
    }

    // v9 -> v10: retain Claude Code OAuth as an explicit frontend auth choice
    // while the backend continues to receive the real Anthropic provider.
    if (version < 10) {
      const oldLlm = (state.llm as Record<string, unknown> | undefined) ?? {};
      const provider = String(oldLlm.provider ?? "").trim().toLowerCase();
      state = {
        ...state,
        llm: {
          ...oldLlm,
          authMode: provider === "anthropic" && oldLlm.authMode === "claude-code-oauth"
            ? "claude-code-oauth"
            : "api-key",
          apiKey: "",
        } as LLMSettings,
      };
    }

    // v10 -> v11: WhatsApp alerting was retired — drop its persisted settings.
    if (version < 11) {
      const { whatsapp: _whatsapp, ...rest } = state as Record<string, unknown> & { whatsapp?: unknown };
      state = rest;
    }

    return state;
  },
});

export const useSettingsStore = import.meta.env.DEV
  ? create<SettingsStore>()(devtools(persistedStore, { name: "settings" }))
  : create<SettingsStore>()(persistedStore);
