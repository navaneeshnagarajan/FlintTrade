/**
 * useSettingsState — shared hook for SettingsRoute and SettingsTool.
 *
 * Reads from settingsStore + connectionStore and returns typed selectors
 * plus update actions. Both the full-page settings route and the canvas
 * panel consume this hook so they share identical data shapes.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSettingsStore } from "@/stores/settingsStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { resetWsService } from "@/services/websocket";

// ---------------------------------------------------------------------------
// Section data shapes (mirror the section component prop interfaces)
// ---------------------------------------------------------------------------

export interface GeneralData {
  fontSize: "small" | "normal" | "large";
  density: "compact" | "comfortable";
}

export interface ConnectionData {
  host: string;
  apiKey: string;
  wsPort: string;
}

export interface TradingData {
  exchange: string;
  product: "MIS" | "NRML" | "CNC";
  orderType: "MARKET" | "LIMIT" | "SL" | "SL-M";
  quantity: string;
}

export interface RiskData {
  maxPositionLots: string;
  mtmStoploss: string;
  mtmTarget: string;
  maxOrdersPerMinute: string;
}

export type LlmProvider =
  | "lmstudio"
  | "ollama"
  | "openai"
  | "anthropic"
  | "gemini"
  | "deepseek"
  | "groq"
  | "grok"
  | "mistral"
  | "together"
  | "openrouter"
  | "custom";

export interface LlmData {
  provider: LlmProvider;
  host: string;
  model: string;
  apiKey: string;
}

export interface TelegramData {
  enabled: boolean;
  botToken: string;
  chatId: string;
}

export interface DataPathsData {
  fastStoragePath: string;
  archiveStoragePath: string;
}

// ---------------------------------------------------------------------------
// Hook return type
// ---------------------------------------------------------------------------

export interface SettingsState {
  // Selectors
  general: GeneralData;
  trading: TradingData;
  risk: RiskData;
  llm: LlmData;
  telegram: TelegramData;
  dataPaths: DataPathsData;
  connection: ConnectionData;
  restarting: boolean;

  // Actions
  updateGeneral: (field: keyof GeneralData, value: string) => void;
  updateTradingDefaults: (field: keyof TradingData, value: string) => void;
  updateRiskLimits: (field: keyof RiskData, value: string) => void;
  updateLLM: (field: keyof LlmData, value: string) => void;
  updateTelegram: (field: keyof TelegramData, value: string | boolean) => void;
  updateDataPaths: (field: keyof DataPathsData, value: string) => void;
  updateConnection: (field: keyof ConnectionData, value: string) => void;
  handleRestart: (onDone?: (msg: string) => void) => void;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useSettingsState(): SettingsState {
  // ---- settingsStore selectors ----
  const fontSize    = useSettingsStore((s) => s.fontSize);
  const density     = useSettingsStore((s) => s.density);

  const defaultExchange   = useSettingsStore((s) => s.defaultExchange);
  const defaultProduct    = useSettingsStore((s) => s.defaultProduct);
  const defaultQty        = useSettingsStore((s) => s.defaultQty);
  const defaultOrderType  = useSettingsStore((s) => s.defaultOrderType);

  const riskLimits  = useSettingsStore((s) => s.riskLimits);
  const llm         = useSettingsStore((s) => s.llm);
  const telegram    = useSettingsStore((s) => s.telegram);
  const dataPaths   = useSettingsStore((s) => s.dataPaths);

  // ---- connectionStore selectors ----
  const connHost    = useConnectionStore((s) => s.host);
  const connApiKey  = useConnectionStore((s) => s.apiKey);
  const connWsUrl   = useConnectionStore((s) => s.wsUrl);

  // ---- restart state (local — not persisted) ----
  const [restarting, setRestarting] = useState(false);
  const restartRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Cleanup pending restart timer when the component that owns this hook unmounts
  useEffect(() => {
    return () => { if (restartRef.current) clearTimeout(restartRef.current); };
  }, []);

  // ---- Actions ----

  const updateGeneral = useCallback((field: keyof GeneralData, value: string) => {
    if (field === "fontSize") {
      useSettingsStore.getState().setFontSize(value as GeneralData["fontSize"]);
    } else if (field === "density") {
      useSettingsStore.getState().setDensity(value as GeneralData["density"]);
    }
  }, []);

  const updateTradingDefaults = useCallback((field: keyof TradingData, value: string) => {
    if (field === "exchange") {
      useSettingsStore.getState().setTradingDefaults({ defaultExchange: value });
    } else if (field === "product") {
      useSettingsStore.getState().setTradingDefaults({ defaultProduct: value });
    } else if (field === "orderType") {
      useSettingsStore.getState().setTradingDefaults({ defaultOrderType: value });
    } else if (field === "quantity") {
      const qty = parseFloat(value);
      if (!isNaN(qty)) {
        useSettingsStore.getState().setTradingDefaults({ defaultQty: qty });
      }
    }
  }, []);

  const updateRiskLimits = useCallback((field: keyof RiskData, value: string) => {
    const num = parseFloat(value);
    if (field === "maxPositionLots") {
      useSettingsStore.getState().setRiskLimits({ maxPositionLots: isNaN(num) ? 0 : num });
    } else if (field === "mtmStoploss") {
      useSettingsStore.getState().setRiskLimits({ mtmStoploss: isNaN(num) ? 0 : num });
    } else if (field === "mtmTarget") {
      useSettingsStore.getState().setRiskLimits({ mtmTarget: isNaN(num) ? 0 : num });
    } else if (field === "maxOrdersPerMinute") {
      useSettingsStore.getState().setRiskLimits({ maxOrdersPerMinute: isNaN(num) ? 0 : num });
    }
  }, []);

  const updateLLM = useCallback((field: keyof LlmData, value: string) => {
    useSettingsStore.getState().setLLM({ [field]: value });
  }, []);

  const updateTelegram = useCallback((field: keyof TelegramData, value: string | boolean) => {
    useSettingsStore.getState().setTelegram({ [field]: value });
  }, []);

  const updateDataPaths = useCallback((field: keyof DataPathsData, value: string) => {
    useSettingsStore.getState().setDataPaths({ [field]: value });
  }, []);

  const updateConnection = useCallback((field: keyof ConnectionData, value: string) => {
    if (field === "host") {
      useConnectionStore.getState().setConfig({ host: value });
    } else if (field === "apiKey") {
      useConnectionStore.getState().setConfig({ apiKey: value });
    } else if (field === "wsPort") {
      // Derive wsUrl from current host + new port
      const host = useConnectionStore.getState().host;
      try {
        const hostname = new URL(host).hostname;
        useConnectionStore.getState().setConfig({ wsUrl: `ws://${hostname}:${value}` });
      } catch {
        // If host isn't a valid URL yet, just store the partial wsUrl
        useConnectionStore.getState().setConfig({ wsUrl: `ws://127.0.0.1:${value}` });
      }
    }
  }, []);

  const handleRestart = useCallback((onDone?: (msg: string) => void) => {
    if (restarting) return;
    setRestarting(true);
    resetWsService();
    restartRef.current = setTimeout(() => {
      setRestarting(false);
      onDone?.("Services restarted");
    }, 800);
  }, [restarting]);

  // ---- Derive section shapes expected by components ----
  // All derived objects are memoized so consumers only re-render when their
  // specific slice of state actually changes.

  const general = useMemo<GeneralData>(
    () => ({ fontSize, density }),
    [fontSize, density],
  );

  const trading = useMemo<TradingData>(
    () => ({
      exchange: defaultExchange,
      product: defaultProduct as TradingData["product"],
      orderType: defaultOrderType as TradingData["orderType"],
      quantity: String(defaultQty),
    }),
    [defaultExchange, defaultProduct, defaultOrderType, defaultQty],
  );

  // Use != null (not truthiness) so that 0 is preserved as "0", not "".
  const risk = useMemo<RiskData>(
    () => ({
      maxPositionLots:   riskLimits.maxPositionLots   != null ? String(riskLimits.maxPositionLots)   : "",
      mtmStoploss:       riskLimits.mtmStoploss       != null ? String(riskLimits.mtmStoploss)       : "",
      mtmTarget:         riskLimits.mtmTarget         != null ? String(riskLimits.mtmTarget)         : "",
      maxOrdersPerMinute:riskLimits.maxOrdersPerMinute != null ? String(riskLimits.maxOrdersPerMinute) : "",
    }),
    [riskLimits],
  );

  const llmData = useMemo<LlmData>(
    () => ({
      provider: (llm.provider || "lmstudio") as LlmProvider,
      host: llm.host,
      model: llm.model,
      apiKey: llm.apiKey,
    }),
    [llm],
  );

  const telegramData = useMemo<TelegramData>(
    () => ({
      enabled: telegram.enabled,
      botToken: telegram.botToken,
      chatId: telegram.chatId,
    }),
    [telegram],
  );

  const dataPathsData = useMemo<DataPathsData>(
    () => ({
      fastStoragePath: dataPaths.fastStoragePath,
      archiveStoragePath: dataPaths.archiveStoragePath,
    }),
    [dataPaths],
  );

  const connection = useMemo<ConnectionData>(() => {
    // Extract port from wsUrl; fall back to "8765"
    let wsPort = "8765";
    try {
      const wsUrlObj = new URL(connWsUrl.replace(/^ws/, "http"));
      wsPort = wsUrlObj.port || "8765";
    } catch {
      // default
    }
    return { host: connHost, apiKey: connApiKey, wsPort };
  }, [connHost, connApiKey, connWsUrl]);

  return {
    general,
    trading,
    risk,
    llm: llmData,
    telegram: telegramData,
    dataPaths: dataPathsData,
    connection,
    restarting,
    updateGeneral,
    updateTradingDefaults,
    updateRiskLimits,
    updateLLM,
    updateTelegram,
    updateDataPaths,
    updateConnection,
    handleRestart,
  };
}
