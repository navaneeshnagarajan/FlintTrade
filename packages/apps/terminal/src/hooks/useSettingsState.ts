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
  applyOpenAlgoConfigToConnectionCache,
  openAlgoRestPortFromHost,
  openAlgoWsPortFromUrl,
} from "@/hooks/useOpenAlgoConfigHydration";
import { readOpenAlgoConfig } from "@/services/ftApi.openalgo";
import {
  persistLlmConfigPatch,
  readLlmConfig,
  isAcceptedLlmConfigStatus,
  type LlmConfigPatch,
  type LlmConfigResponse,
} from "@/services/ftApi.llm";
import { LLM_PROVIDERS, normaliseLlmHost } from "@/lib/llmProviders";
import type { LlmAuthMode } from "@/lib/llmProviders";

// ---------------------------------------------------------------------------
// Section data shapes (mirror the section component prop interfaces)
// ---------------------------------------------------------------------------

export interface GeneralData {
  fontSize: "small" | "normal" | "large";
}

export interface ConnectionData {
  host: string;
  port: string;
  wsPort: string;
  apiKeyConfigured: boolean;
  apiKeyLast4: string;
}

export interface SavedConnectionData {
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
  | "ollama"
  | "hermes"
  | "openai"
  | "anthropic"
  | "gemini"
  | "deepseek"
  | "groq"
  | "grok"
  | "mistral"
  | "cerebras"
  | "together"
  | "openrouter"
  | "custom";

export interface LlmData {
  provider: LlmProvider;
  authMode: LlmAuthMode;
  host: string;
  model: string;
  apiKey: string;
}

export type LlmSaveState = "saved" | "pending" | "saving" | "error";
export type LlmHydrationState = "loading" | "ready" | "error";

export interface TelegramData {
  enabled: boolean;
  botToken: string;
  chatId: string;
}

export interface DataPathsData {
  fastStoragePath: string;
  archiveStoragePath: string;
}

export { isAcceptedOpenAlgoConfigStatus } from "@/services/ftApi.openalgo";

/**
 * Debounce window for persisting LLM config edits.
 *
 * POST /v1/config/llm is rate limited to 10 requests/min. Ordinary model edits
 * are coalesced and only flushed once typing pauses. Credentials never use this
 * path; they require an explicit transaction.
 */
const LLM_PERSIST_DEBOUNCE_MS = 600;

// ---------------------------------------------------------------------------
// Hook return type
// ---------------------------------------------------------------------------

export interface SettingsState {
  // Selectors
  general: GeneralData;
  trading: TradingData;
  risk: RiskData;
  llm: LlmData;
  llmSetupPending: boolean;
  llmSaveState: LlmSaveState;
  llmHydrationState: LlmHydrationState;
  llmCredentialConfigured: boolean;
  llmCredentialLast4: string;
  telegram: TelegramData;
  dataPaths: DataPathsData;
  connection: ConnectionData;
  restarting: boolean;

  // Actions
  updateGeneral: (field: keyof GeneralData, value: string) => void;
  updateTradingDefaults: (field: keyof TradingData, value: string) => void;
  updateRiskLimits: (field: keyof RiskData, value: string) => void;
  updateLLM: (field: keyof LlmData, value: string) => void;
  updateLLMProvider: (
    provider: LlmProvider,
    host?: string,
    model?: string,
    apiKey?: string,
    authMode?: LlmAuthMode,
  ) => Promise<void>;
  removeLLMCredential: () => Promise<void>;
  updateTelegram: (field: keyof TelegramData, value: string | boolean) => void;
  updateDataPaths: (field: keyof DataPathsData, value: string) => void;
  acceptConnection: (connection: SavedConnectionData) => void;
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
  const llmSetupPending = useSettingsStore((s) => s.llmSetupPending);
  const telegram    = useSettingsStore((s) => s.telegram);
  const dataPaths   = useSettingsStore((s) => s.dataPaths);

  // ---- connectionStore selectors ----
  const connHost    = useConnectionStore((s) => s.host);
  const connApiKey  = useConnectionStore((s) => s.apiKey);
  const connWsUrl   = useConnectionStore((s) => s.wsUrl);

  // ---- restart state (local — not persisted) ----
  const [restarting, setRestarting] = useState(false);
  const [llmSaveState, setLlmSaveState] = useState<LlmSaveState>("saved");
  const [llmHydrationState, setLlmHydrationState] = useState<LlmHydrationState>("loading");
  const [llmCredentialMetadata, setLlmCredentialMetadata] = useState({
    provider: "",
    configured: false,
    last4: "",
  });
  const [connectionCredentialMetadata, setConnectionCredentialMetadata] = useState({
    configured: false,
    last4: "",
  });
  const [connRestPort, setConnRestPort] = useState("");
  const restartRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const connectionRevisionRef = useRef(0);
  const pendingLlmPatchRef = useRef<Partial<LlmData>>({});
  // LLM edits accumulated since the last backend flush, plus the debounce timer.
  // Persistence is debounced (never per keystroke) — see LLM_PERSIST_DEBOUNCE_MS.
  const unsavedLlmPatchRef = useRef<Partial<LlmData>>({});
  const unsavedLlmRevisionsRef = useRef<Partial<Record<keyof LlmData, number>>>({});
  const unsavedLlmProviderRef = useRef<LlmProvider | null>(null);
  const llmSaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const llmWriteTailRef = useRef<Promise<void>>(Promise.resolve());
  const llmProviderRevisionRef = useRef(0);
  const llmProviderTransactionsRef = useRef(0);
  const llmProviderMutationActiveRef = useRef(false);
  const llmProviderMutationPromiseRef = useRef<Promise<void> | null>(null);
  const llmHydratedRef = useRef(false);
  const llmSaveRevisionRef = useRef(0);
  const llmFieldRevisionsRef = useRef<Record<keyof LlmData, number>>({
    provider: 0,
    authMode: 0,
    host: 0,
    model: 0,
    apiKey: 0,
  });

  const applyLlmCredentialMetadata = useCallback((payload: LlmConfigResponse) => {
    if (!isAcceptedLlmConfigStatus(payload.status)) return;
    const data = payload.data ?? {};
    if (typeof data.api_key_configured !== "boolean") return;
    setLlmCredentialMetadata({
      provider: String(data.provider ?? useSettingsStore.getState().llm.provider),
      configured: data.api_key_configured === true,
      last4: String(data.api_key_last4 ?? ""),
    });
  }, []);

  // Cleanup pending restart timer when the component that owns this hook unmounts
  useEffect(() => {
    return () => { if (restartRef.current) clearTimeout(restartRef.current); };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const connectionRevision = connectionRevisionRef.current;
    void readOpenAlgoConfig()
      .then((payload) => {
        if (
          cancelled
          || connectionRevision !== connectionRevisionRef.current
          || payload.status !== "success"
        ) return;
        const data = payload.data ?? {};
        const host = String(data.host ?? "");
        const hostPort = openAlgoRestPortFromHost(host);
        setConnRestPort(hostPort || String(data.port ?? "5000"));
        setConnectionCredentialMetadata({
          configured: data.api_key_configured === true || Boolean(data.api_key),
          last4: String(data.api_key_last4 ?? ""),
        });
        applyOpenAlgoConfigToConnectionCache(data);
      })
      .catch((err) => {
        console.warn("[settings] failed to hydrate OpenAlgo config:", err);
      });

    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const providerRevision = llmProviderRevisionRef.current;
    void readLlmConfig()
      .then((payload) => {
        if (cancelled || providerRevision !== llmProviderRevisionRef.current) return;
        if (!isAcceptedLlmConfigStatus(payload.status)) {
          llmHydratedRef.current = false;
          setLlmHydrationState("error");
          return;
        }
        applyLlmCredentialMetadata(payload);
        if (!useSettingsStore.getState().llmSetupPending) {
          const data = payload.data ?? {};
          const current = useSettingsStore.getState().llm;
          const provider = String(data.provider ?? current.provider);
          useSettingsStore.getState().setLLM({
            provider,
            authMode: provider === current.provider ? current.authMode : "api-key",
            host: normaliseLlmHost(provider || "ollama", String(data.host ?? current.host)),
            model: String(data.model ?? current.model),
            apiKey: "",
          });
        }
        llmHydratedRef.current = true;
        setLlmHydrationState("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        llmHydratedRef.current = false;
        setLlmHydrationState("error");
        console.warn("[settings] failed to hydrate LLM config:", err);
      });

    return () => { cancelled = true; };
  }, [applyLlmCredentialMetadata]);

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

  const applyAuthoritativeLlm = useCallback((payload: LlmConfigResponse) => {
    if (!isAcceptedLlmConfigStatus(payload.status)) return;
    applyLlmCredentialMetadata(payload);
    const data = payload.data ?? {};
    const current = useSettingsStore.getState().llm;
    const provider = String(data.provider ?? current.provider);
    useSettingsStore.getState().setLLM({
      provider,
      authMode: provider === current.provider ? current.authMode : "api-key",
      host: normaliseLlmHost(provider || "ollama", String(data.host ?? current.host)),
      model: String(data.model ?? current.model),
      // GET is deliberately metadata-only. Never retain a raw failed secret as
      // though the backend had accepted it.
      apiKey: "",
    });
  }, [applyLlmCredentialMetadata]);

  const restoreAuthoritativeLlm = useCallback(async () => {
    try {
      const payload = await readLlmConfig();
      applyLlmCredentialMetadata(payload);
      // Setup choices are an intentional local draft. A failed authenticated
      // activation must not replace that retry target with the old backend state.
      if (useSettingsStore.getState().llmSetupPending) return;
      applyAuthoritativeLlm(payload);
    } catch (error) {
      console.warn("[settings] failed to restore authoritative LLM config:", error);
    }
  }, [applyAuthoritativeLlm, applyLlmCredentialMetadata]);

  const enqueueLlmWrite = useCallback((patch: Partial<LlmConfigPatch>) => {
    const saveRevision = ++llmSaveRevisionRef.current;
    setLlmSaveState("saving");
    const operation = llmWriteTailRef.current.then(async () => {
      try {
        const payload = await persistLlmConfigPatch(patch);
        applyLlmCredentialMetadata(payload);
        if (
          saveRevision === llmSaveRevisionRef.current
          && Object.keys(unsavedLlmPatchRef.current).length === 0
        ) {
          const current = useSettingsStore.getState().llm;
          const currentProvider = current.provider || "ollama";
          const currentConfig = LLM_PROVIDERS.find((candidate) => candidate.id === currentProvider);
          setLlmSaveState(
            !current.model.trim() || (currentConfig?.requiresHost && !current.host.trim())
              ? "error"
              : "saved",
          );
        }
        return payload;
      } catch (error) {
        await restoreAuthoritativeLlm();
        if (saveRevision === llmSaveRevisionRef.current) setLlmSaveState("error");
        console.warn("[settings] failed to persist LLM config:", error);
        emitNotification({
          category: "system",
          title: "LLM settings not saved",
          body: error instanceof Error ? error.message : "The LLM settings could not be saved.",
        });
        throw error;
      }
    });
    llmWriteTailRef.current = operation.then(() => undefined, () => undefined);
    return operation;
  }, [applyLlmCredentialMetadata, restoreAuthoritativeLlm]);

  // Flush the coalesced LLM edits to the same serial write chain used by
  // provider transactions. Edits made while one request is in flight remain in
  // the next snapshot, so the latest value cannot be dropped.
  const flushLlmConfig = useCallback(() => {
    if (!llmHydratedRef.current) return;
    if (llmSaveTimerRef.current) {
      clearTimeout(llmSaveTimerRef.current);
      llmSaveTimerRef.current = null;
    }
    const patch = unsavedLlmPatchRef.current;
    if (Object.keys(patch).length === 0) return;
    unsavedLlmPatchRef.current = {};
    const revisions = unsavedLlmRevisionsRef.current;
    unsavedLlmRevisionsRef.current = {};
    unsavedLlmProviderRef.current = null;
    const persistedPatch: Partial<LlmConfigPatch> = { ...patch };
    const save = enqueueLlmWrite(persistedPatch);
    void save.then((payload) => {
      const data = payload.data ?? {};
      const accepted: Partial<LlmData> = {};
      for (const field of Object.keys(patch) as (keyof LlmData)[]) {
        if (llmFieldRevisionsRef.current[field] !== revisions[field]) continue;
        if (field === "host") {
          const activeProvider = useSettingsStore.getState().llm.provider || "ollama";
          accepted.host = normaliseLlmHost(activeProvider, String(data.host ?? patch.host ?? ""));
        } else if (field === "model") {
          accepted.model = String(data.model ?? patch.model ?? "");
        }
      }
      if (Object.keys(accepted).length > 0) useSettingsStore.getState().setLLM(accepted);
    }).catch(() => undefined);
    void save.catch(() => undefined);
    return save;
  }, [enqueueLlmWrite]);

  // Flush any pending LLM edit when the settings surface unmounts, so a
  // debounced save is not lost when the operator navigates away before it fires.
  useEffect(() => {
    return () => { flushLlmConfig(); };
  }, [flushLlmConfig]);

  const updateLLMProvider = useCallback((
    provider: LlmProvider,
    host?: string,
    model?: string,
    apiKey?: string,
    authMode: LlmAuthMode = "api-key",
  ) => {
    if (!llmHydratedRef.current) {
      return Promise.reject(new Error("LLM settings are still loading"));
    }
    if (llmProviderMutationActiveRef.current) {
      return llmProviderMutationPromiseRef.current ?? Promise.reject(new Error("LLM settings are already being saved"));
    }

    const effectiveAuthMode: LlmAuthMode = provider === "anthropic" && authMode === "claude-code-oauth"
      ? "claude-code-oauth"
      : "api-key";
    const providerConfigId = effectiveAuthMode === "claude-code-oauth" ? "claude-code-oauth" : provider;
    const config = LLM_PROVIDERS.find((candidate) => candidate.id === providerConfigId);
    if (!config) return Promise.reject(new Error(`Unsupported LLM provider: ${provider}`));

    let nextHost = "";
    if (config.requiresHost) {
      nextHost = (host ?? config.defaultHost ?? "").trim();
      if (!nextHost) return Promise.reject(new Error(`Host URL is required for ${config.name}`));
    }
    const nextModel = (model ?? config.defaultModel).trim();
    if (!nextModel) return Promise.reject(new Error("Model is required"));

    const settingsState = useSettingsStore.getState();
    const activeProvider = (settingsState.llm.provider || "ollama") as LlmProvider;
    const activeHost = normaliseLlmHost(activeProvider, settingsState.llm.host).trim();
    const destinationChanged = settingsState.llmSetupPending
      || provider !== activeProvider
      || effectiveAuthMode !== settingsState.llm.authMode
      || nextHost !== activeHost;
    const replacementKey = apiKey?.trim() ?? "";
    if (config.requiresApiKey && destinationChanged && !replacementKey) {
      return Promise.reject(new Error(`API key is required for ${config.name}`));
    }

    llmProviderMutationActiveRef.current = true;
    llmProviderTransactionsRef.current += 1;
    const operation = (async () => {
      llmProviderRevisionRef.current += 1;
      // Preserve edits for the currently active provider before changing the
      // backend provider. The shared queue prevents overlap and API-key rebinding.
      const pendingSave = flushLlmConfig();
      if (pendingSave) await pendingSave;
      llmFieldRevisionsRef.current.host += 1;
      llmFieldRevisionsRef.current.apiKey += 1;
      llmFieldRevisionsRef.current.model += 1;
      llmFieldRevisionsRef.current.authMode += 1;

      const patch: Partial<LlmConfigPatch> = { provider, host: nextHost, model: nextModel };
      if (replacementKey) patch.apiKey = replacementKey;
      const payload = await enqueueLlmWrite(patch);
      const data = payload.data ?? {};
      const current = useSettingsStore.getState().llm;
      const acceptedProvider = String(data.provider ?? provider);
      useSettingsStore.getState().setLLM({
        provider: acceptedProvider,
        authMode: acceptedProvider === provider ? effectiveAuthMode : "api-key",
        host: normaliseLlmHost(acceptedProvider, String(data.host ?? nextHost)),
        model: String(data.model ?? nextModel ?? current.model),
        apiKey: "",
      });
      useSettingsStore.getState().clearLLMSetupDraft();
    })();
    const trackedOperation = operation.finally(() => {
      llmProviderTransactionsRef.current -= 1;
      llmProviderMutationActiveRef.current = false;
      if (llmProviderMutationPromiseRef.current === trackedOperation) {
        llmProviderMutationPromiseRef.current = null;
      }
    });
    llmProviderMutationPromiseRef.current = trackedOperation;
    return trackedOperation;
  }, [enqueueLlmWrite, flushLlmConfig]);

  const removeLLMCredential = useCallback(() => {
    if (!llmHydratedRef.current) {
      return Promise.reject(new Error("LLM settings are still loading"));
    }
    if (llmProviderMutationActiveRef.current) {
      return llmProviderMutationPromiseRef.current ?? Promise.reject(new Error("LLM settings are already being saved"));
    }

    const current = useSettingsStore.getState().llm;
    const provider = (current.provider || "ollama") as LlmProvider;
    const configId = current.authMode === "claude-code-oauth" ? "claude-code-oauth" : provider;
    const config = LLM_PROVIDERS.find((candidate) => candidate.id === configId);
    if (!config?.requiresApiKey) return Promise.reject(new Error("The active provider has no stored credential"));
    const model = current.model.trim();
    if (!model) return Promise.reject(new Error("Model is required"));
    const host = normaliseLlmHost(provider, current.host).trim();
    if (config.requiresHost && !host) {
      return Promise.reject(new Error(`Host URL is required for ${config.name}`));
    }

    llmProviderMutationActiveRef.current = true;
    llmProviderTransactionsRef.current += 1;
    const operation = (async () => {
      llmProviderRevisionRef.current += 1;
      const pendingSave = flushLlmConfig();
      if (pendingSave) await pendingSave;
      llmFieldRevisionsRef.current.apiKey += 1;
      const payload = await enqueueLlmWrite({ provider, host, model, apiKey: "" });
      const data = payload.data ?? {};
      const acceptedProvider = String(data.provider ?? provider);
      useSettingsStore.getState().setLLM({
        provider: acceptedProvider,
        authMode: acceptedProvider === provider ? current.authMode : "api-key",
        host: normaliseLlmHost(acceptedProvider, String(data.host ?? host)),
        model: String(data.model ?? model),
        apiKey: "",
      });
      setLlmCredentialMetadata({ provider: acceptedProvider, configured: false, last4: "" });
    })();
    const trackedOperation = operation.finally(() => {
      llmProviderTransactionsRef.current -= 1;
      llmProviderMutationActiveRef.current = false;
      if (llmProviderMutationPromiseRef.current === trackedOperation) {
        llmProviderMutationPromiseRef.current = null;
      }
    });
    llmProviderMutationPromiseRef.current = trackedOperation;
    return trackedOperation;
  }, [enqueueLlmWrite, flushLlmConfig]);

  const updateLLM = useCallback((field: keyof LlmData, value: string) => {
    if (!llmHydratedRef.current) return;
    // Credentials are deliberately outside the generic autosave path. They are
    // only accepted by explicit provider/replace/remove transactions.
    if (field === "apiKey" || field === "authMode") return;
    if (field === "provider") {
      void updateLLMProvider(value as LlmProvider).catch(() => undefined);
      return;
    }
    const currentProvider = useSettingsStore.getState().llm.provider as LlmProvider;
    const providerConfig = LLM_PROVIDERS.find((candidate) => candidate.id === currentProvider);
    // A host change creates a new credential trust destination. Credentialled
    // providers must use the explicit full provider transaction so a stored key
    // can neither follow the host nor be removed by generic autosave.
    if (field === "host" && providerConfig?.requiresApiKey) return;
    if (llmProviderTransactionsRef.current > 0) return;
    if (currentProvider === "ollama" && field === "host") return;
    if (
      unsavedLlmProviderRef.current
      && currentProvider
      && unsavedLlmProviderRef.current !== currentProvider
    ) {
      flushLlmConfig();
    }
    llmFieldRevisionsRef.current[field] += 1;
    const currentLlm = useSettingsStore.getState().llm;
    const hostDestinationChanged = field === "host"
      && normaliseLlmHost(currentProvider, value).trim()
        !== normaliseLlmHost(currentProvider, currentLlm.host).trim();
    if (hostDestinationChanged) llmFieldRevisionsRef.current.apiKey += 1;
    // Reflect the edit in the store immediately (responsive field) and record
    // it for both the late-hydration merge and the pending backend flush.
    const pendingPatch = { ...pendingLlmPatchRef.current, [field]: value };
    const localPatch: Partial<LlmData> = { [field]: value };
    if (hostDestinationChanged) {
      delete pendingPatch.apiKey;
      localPatch.apiKey = "";
    }
    pendingLlmPatchRef.current = pendingPatch;
    useSettingsStore.getState().setLLM(localPatch);

    const invalidHost = field === "host" && providerConfig?.requiresHost && !value.trim();
    const invalidModel = field === "model" && !value.trim();
    if (invalidHost || invalidModel) {
      const remainingPatch = { ...unsavedLlmPatchRef.current };
      const remainingRevisions = { ...unsavedLlmRevisionsRef.current };
      delete remainingPatch[field];
      delete remainingRevisions[field];
      if (hostDestinationChanged) {
        delete remainingPatch.apiKey;
        delete remainingRevisions.apiKey;
      }
      unsavedLlmPatchRef.current = remainingPatch;
      unsavedLlmRevisionsRef.current = remainingRevisions;
      if (Object.keys(remainingPatch).length === 0) {
        unsavedLlmProviderRef.current = null;
        if (llmSaveTimerRef.current) clearTimeout(llmSaveTimerRef.current);
        llmSaveTimerRef.current = null;
      }
      setLlmSaveState("error");
      return;
    }

    unsavedLlmProviderRef.current = currentProvider || null;
    const unsavedPatch = { ...unsavedLlmPatchRef.current, [field]: value };
    const unsavedRevisions = {
      ...unsavedLlmRevisionsRef.current,
      [field]: llmFieldRevisionsRef.current[field],
    };
    if (hostDestinationChanged) {
      delete unsavedPatch.apiKey;
      delete unsavedRevisions.apiKey;
    }
    unsavedLlmPatchRef.current = unsavedPatch;
    unsavedLlmRevisionsRef.current = unsavedRevisions;
    setLlmSaveState("pending");
    // Debounce ordinary non-secret backend writes to avoid the 10/min endpoint
    // rate limit while keeping the field responsive.
    if (llmSaveTimerRef.current) clearTimeout(llmSaveTimerRef.current);
    llmSaveTimerRef.current = setTimeout(flushLlmConfig, LLM_PERSIST_DEBOUNCE_MS);
  }, [flushLlmConfig, updateLLMProvider]);

  const updateTelegram = useCallback((field: keyof TelegramData, value: string | boolean) => {
    useSettingsStore.getState().setTelegram({ [field]: value });
  }, []);

  const updateDataPaths = useCallback((field: keyof DataPathsData, value: string) => {
    useSettingsStore.getState().setDataPaths({ [field]: value });
  }, []);

  const acceptConnection = useCallback((connection: SavedConnectionData) => {
    connectionRevisionRef.current += 1;
    setConnRestPort(connection.port);
    const cachedApiKey = useConnectionStore.getState().apiKey;
    setConnectionCredentialMetadata((current) => {
      const acceptedApiKey = connection.apiKey.trim() || cachedApiKey;
      return {
        configured: Boolean(acceptedApiKey) || current.configured,
        last4: acceptedApiKey ? acceptedApiKey.slice(-4) : current.last4,
      };
    });
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
    () => {
      const provider = (llm.provider || "ollama") as LlmProvider;
      return {
        provider,
        authMode: provider === "anthropic" && llm.authMode === "claude-code-oauth"
          ? "claude-code-oauth"
          : "api-key",
        host: normaliseLlmHost(provider, llm.host),
        model: llm.model,
        apiKey: "",
      };
    },
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
    return {
      host: connHost,
      port: connRestPort || openAlgoRestPortFromHost(connHost) || "5000",
      wsPort: openAlgoWsPortFromUrl(connWsUrl),
      apiKeyConfigured: connectionCredentialMetadata.configured || Boolean(connApiKey),
      apiKeyLast4: connectionCredentialMetadata.last4 || connApiKey.slice(-4),
    };
  }, [connHost, connRestPort, connApiKey, connWsUrl, connectionCredentialMetadata]);

  return {
    general,
    trading,
    risk,
    llm: llmData,
    llmSetupPending,
    llmSaveState,
    llmHydrationState,
    llmCredentialConfigured: !llmSetupPending
      && llmCredentialMetadata.provider === llmData.provider
      && llmCredentialMetadata.configured,
    llmCredentialLast4: !llmSetupPending && llmCredentialMetadata.provider === llmData.provider
      ? llmCredentialMetadata.last4
      : "",
    telegram: telegramData,
    dataPaths: dataPathsData,
    connection,
    restarting,
    updateGeneral,
    updateTradingDefaults,
    updateRiskLimits,
    updateLLM,
    updateLLMProvider,
    removeLLMCredential,
    updateTelegram,
    updateDataPaths,
    acceptConnection,
    handleRestart,
  };
}
