/**
 * useSettingsState — shared hook for SettingsRoute and QuickAccessPanel.
 *
 * Reads from settingsStore + connectionStore and returns typed selectors
 * plus update actions. Both the full-page settings route and the quick
 * access panel consume this hook so they share identical data shapes.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSettingsStore } from "@/stores/settingsStore";
import { useConnectionStore } from "@/stores/connectionStore";
import { resetWsService } from "@/services/websocket";
import { emitNotification } from "@/components/NotificationCentre/useNotificationFeed";
import {
  deriveOpenAlgoWsUrl,
  openAlgoRestPortFromHost,
  openAlgoWsPortFromUrl,
} from "@/hooks/useOpenAlgoConfigHydration";
import {
  persistOpenAlgoConfigPatch,
  readOpenAlgoConfig,
} from "@/services/ftApi.openalgo";
import {
  persistLlmConfigPatch,
  readLlmConfig,
} from "@/services/ftApi.llm";

// ---------------------------------------------------------------------------
// Section data shapes (mirror the section component prop interfaces)
// ---------------------------------------------------------------------------

export interface GeneralData {
  fontSize: "small" | "normal" | "large";
}

export interface ConnectionData {
  host: string;
  port: string;
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
  | "hermes"
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

export interface WhatsAppData {
  enabled: boolean;
  phoneE164: string;
  adminUrl: string;
}

export interface DataPathsData {
  fastStoragePath: string;
  archiveStoragePath: string;
}

export { isAcceptedOpenAlgoConfigStatus } from "@/services/ftApi.openalgo";

async function persistOpenAlgoPatch(connection: Partial<ConnectionData>): Promise<void> {
  await persistOpenAlgoConfigPatch(connection);
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
  whatsapp: WhatsAppData;
  dataPaths: DataPathsData;
  connection: ConnectionData;
  restarting: boolean;

  // Actions
  updateGeneral: (field: keyof GeneralData, value: string) => void;
  updateTradingDefaults: (field: keyof TradingData, value: string) => void;
  updateRiskLimits: (field: keyof RiskData, value: string) => void;
  updateLLM: (field: keyof LlmData, value: string) => void;
  updateTelegram: (field: keyof TelegramData, value: string | boolean) => void;
  updateWhatsApp: (field: keyof WhatsAppData, value: string | boolean) => void;
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

  const defaultExchange   = useSettingsStore((s) => s.defaultExchange);
  const defaultProduct    = useSettingsStore((s) => s.defaultProduct);
  const defaultQty        = useSettingsStore((s) => s.defaultQty);
  const defaultOrderType  = useSettingsStore((s) => s.defaultOrderType);

  const riskLimits  = useSettingsStore((s) => s.riskLimits);
  const llm         = useSettingsStore((s) => s.llm);
  const telegram    = useSettingsStore((s) => s.telegram);
  const whatsapp    = useSettingsStore((s) => s.whatsapp);
  const dataPaths   = useSettingsStore((s) => s.dataPaths);

  // ---- connectionStore selectors ----
  const connHost    = useConnectionStore((s) => s.host);
  const connApiKey  = useConnectionStore((s) => s.apiKey);
  const connWsUrl   = useConnectionStore((s) => s.wsUrl);

  // ---- restart state (local — not persisted) ----
  const [restarting, setRestarting] = useState(false);
  const [connRestPort, setConnRestPort] = useState("");
  const restartRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingConnectionPatchRef = useRef<Partial<ConnectionData>>({});
  const pendingLlmPatchRef = useRef<Partial<LlmData>>({});

  // Cleanup pending restart timer when the component that owns this hook unmounts
  useEffect(() => {
    return () => { if (restartRef.current) clearTimeout(restartRef.current); };
  }, []);

  useEffect(() => {
    let cancelled = false;
    void readOpenAlgoConfig()
      .then((payload) => {
        if (cancelled || payload.status !== "success") return;
        const data = payload.data ?? {};
        const patch = pendingConnectionPatchRef.current;
        const host = "host" in patch ? String(patch.host ?? "") : String(data.host ?? "");
        const hostPort = openAlgoRestPortFromHost(host);
        const port = "port" in patch
          ? String(patch.port ?? "")
          : (hostPort || String(data.port ?? "5000"));
        const apiKey = "apiKey" in patch ? String(patch.apiKey ?? "") : useConnectionStore.getState().apiKey;
        const wsPort = "wsPort" in patch ? String(patch.wsPort ?? "") : String(data.ws_port ?? "8765");
        setConnRestPort(port);
        useConnectionStore.getState().setConfig({
          host,
          apiKey,
          wsUrl: deriveOpenAlgoWsUrl(host, wsPort),
        });
      })
      .catch((err) => {
        console.warn("[settings] failed to hydrate OpenAlgo config:", err);
      });

    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    void readLlmConfig()
      .then((payload) => {
        if (cancelled || payload.status !== "success") return;
        const data = payload.data ?? {};
        const patch = pendingLlmPatchRef.current;
        const current = useSettingsStore.getState().llm;
        useSettingsStore.getState().setLLM({
          provider: "provider" in patch ? String(patch.provider ?? "") : String(data.provider ?? current.provider),
          host: "host" in patch ? String(patch.host ?? "") : String(data.host ?? current.host),
          model: "model" in patch ? String(patch.model ?? "") : String(data.model ?? current.model),
          apiKey: "apiKey" in patch ? String(patch.apiKey ?? "") : current.apiKey,
        });
      })
      .catch((err) => {
        console.warn("[settings] failed to hydrate LLM config:", err);
      });

    return () => { cancelled = true; };
  }, []);

  // ---- Actions ----

  const updateGeneral = useCallback((field: keyof GeneralData, value: string) => {
    if (field === "fontSize") {
      useSettingsStore.getState().setFontSize(value as GeneralData["fontSize"]);
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
    pendingLlmPatchRef.current = { ...pendingLlmPatchRef.current, [field]: value };
    useSettingsStore.getState().setLLM({ [field]: value });
    const save = persistLlmConfigPatch({ [field]: value });
    void save.catch((err: unknown) => {
      console.warn("[settings] failed to persist LLM config:", err);
      emitNotification({
        category: "system",
        title: "LLM settings not saved",
        body: err instanceof Error ? err.message : "The LLM settings could not be saved.",
      });
    });
  }, []);

  const updateTelegram = useCallback((field: keyof TelegramData, value: string | boolean) => {
    useSettingsStore.getState().setTelegram({ [field]: value });
  }, []);

  const updateWhatsApp = useCallback((field: keyof WhatsAppData, value: string | boolean) => {
    useSettingsStore.getState().setWhatsApp({ [field]: value });
  }, []);

  const updateDataPaths = useCallback((field: keyof DataPathsData, value: string) => {
    useSettingsStore.getState().setDataPaths({ [field]: value });
  }, []);

  const updateConnection = useCallback((field: keyof ConnectionData, rawValue: string) => {
    // Ports are numeric-or-empty; a whitespace-only value means "cleared".
    const value = field === "port" || field === "wsPort" ? rawValue.trim() : rawValue;
    pendingConnectionPatchRef.current = { ...pendingConnectionPatchRef.current, [field]: value };
    const current = useConnectionStore.getState();
    let host = current.host;
    let port = connRestPort || openAlgoRestPortFromHost(current.host) || "5000";
    let apiKey = current.apiKey;
    let wsPort = openAlgoWsPortFromUrl(current.wsUrl);

    if (field === "host") {
      host = value;
      port = openAlgoRestPortFromHost(value) || port;
      setConnRestPort(port);
    } else if (field === "port") {
      port = value;
      setConnRestPort(port);
    } else if (field === "apiKey") {
      apiKey = value;
    } else if (field === "wsPort") {
      wsPort = value;
    }
    const wsUrl = deriveOpenAlgoWsUrl(host, wsPort);
    useConnectionStore.getState().setConfig({ host, apiKey, wsUrl });

    // Backend contract (/v1/config/openalgo): port and ws_port must be
    // integers 1–65535 when present — {"port": ""} 400s. A cleared port field
    // means "no explicit override" (fall back to the host's port / defaults),
    // so omit the key from the persisted patch instead of sending "".
    if ((field === "port" || field === "wsPort") && value === "") {
      return;
    }
    const save = persistOpenAlgoPatch({ [field]: value });
    void save.catch((err: unknown) => {
      console.warn("[settings] failed to persist OpenAlgo config:", err);
      // A silent 400/500 here means the operator believes the gateway settings
      // are saved when they are not — surface it (item 6).
      emitNotification({
        category: "system",
        title: "Connection settings not saved",
        body: err instanceof Error ? err.message : "The broker gateway settings could not be saved.",
      });
    });
  }, [connRestPort]);

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
    () => ({ fontSize }),
    [fontSize],
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

  const whatsappData = useMemo<WhatsAppData>(
    () => ({
      enabled: whatsapp?.enabled ?? false,
      phoneE164: whatsapp?.phoneE164 ?? "",
      adminUrl: whatsapp?.adminUrl ?? "",
    }),
    [whatsapp],
  );

  const dataPathsData = useMemo<DataPathsData>(
    () => ({
      fastStoragePath: dataPaths.fastStoragePath,
      archiveStoragePath: dataPaths.archiveStoragePath,
    }),
    [dataPaths],
  );

  const connection = useMemo<ConnectionData>(() => {
    return {
      host: connHost,
      port: connRestPort || openAlgoRestPortFromHost(connHost) || "5000",
      apiKey: connApiKey,
      wsPort: openAlgoWsPortFromUrl(connWsUrl),
    };
  }, [connHost, connRestPort, connApiKey, connWsUrl]);

  return {
    general,
    trading,
    risk,
    llm: llmData,
    telegram: telegramData,
    whatsapp: whatsappData,
    dataPaths: dataPathsData,
    connection,
    restarting,
    updateGeneral,
    updateTradingDefaults,
    updateRiskLimits,
    updateLLM,
    updateTelegram,
    updateWhatsApp,
    updateDataPaths,
    updateConnection,
    handleRestart,
  };
}
