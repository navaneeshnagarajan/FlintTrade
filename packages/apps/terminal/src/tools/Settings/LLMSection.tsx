/**
 * LLMSection - cloud-provider configuration and managed local AI runtime.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Download,
  Loader2,
  Play,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  Square,
  Trash2,
  Wrench,
} from "lucide-react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { FieldRow, SelectInput, TextInput, SectionTitle } from "./shared";
import {
  CLAUDE_CODE_OAUTH_PROVIDER,
  LLM_PROVIDERS,
  normaliseLlmHost,
  providerSelection,
  selectionForLlmSettings,
} from "@/lib/llmProviders";
import type { LlmAuthMode } from "@/lib/llmProviders";
import {
  acceptLocalAiModelDigest,
  createLocalAiAdmissionId,
  deleteLocalAiModel,
  getLocalAiStatus,
  installLocalAiRuntime,
  isLocalAiModelPullResult,
  isLocalAiOperationResult,
  isLocalAiStatus,
  LocalAiApiError,
  localAiModelAliasesEquivalent,
  listLocalAiModels,
  pruneLocalAiModels,
  pullLocalAiModel,
  reconcileLocalAiOperation,
  repairLocalAiRuntime,
  resetLocalAiModelDigests,
  rollbackLocalAiRuntime,
  startLocalAiRuntime,
  stopLocalAiRuntime,
  uninstallLocalAiRuntime,
  updateLocalAiRuntime,
  type LocalAiModel,
  type LocalAiModelDigestAcceptance,
  type LocalAiOperation,
  type LocalAiOperationResult,
  type LocalAiStatus,
} from "@/services/ftApi.localAi";
import { testLlmConnection } from "@/services/ftApi.llm";

type LlmProvider =
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

const CLAUDE_CODE_OAUTH = CLAUDE_CODE_OAUTH_PROVIDER;
const BUSY_STATES = new Set(["downloading", "extracting", "starting"]);
const LOCKED_MODEL_ALIAS = /^flinttrade\/sha256-([0-9a-f]{64}):locked$/;
const INVALID_MODEL_DIGEST_STATE_ERROR = "managed Ollama model digest state is invalid";
const RUNTIME_POLL_INTERVAL_MS = 1_000;
const RUNTIME_POLL_MAX_BACKOFF_MS = 8_000;
const RUNTIME_ADMISSION_MAX_BACKOFF_EXPONENT = 3;
const DISPLAY_DIAGNOSTIC_LIMIT = 220;

interface LlmSettings {
  provider: LlmProvider;
  authMode?: LlmAuthMode;
  host: string;
  model: string;
  apiKey: string;
}

type EditableLlmField = "provider" | "host" | "model" | "apiKey";

const LLM_PROVIDER_OPTIONS = LLM_PROVIDERS.map((provider) => ({
  value: provider.id,
  label: provider.name,
}));

interface LLMSectionProps {
  settings: LlmSettings;
  onChange: (field: EditableLlmField, value: string) => void;
  onProviderChange: (
    provider: LlmProvider,
    host?: string,
    model?: string,
    apiKey?: string,
    authMode?: LlmAuthMode,
  ) => Promise<void>;
  providerActivationRequired?: boolean;
  onDraftStateChange?: (pending: boolean) => void;
  hydrationState?: "loading" | "ready" | "error";
  credentialConfigured?: boolean;
  credentialLast4?: string;
  onCredentialRemove?: () => Promise<void>;
}

type TestStatus = "idle" | "testing" | "ok" | "error";
type ProviderSelection = LlmProvider | typeof CLAUDE_CODE_OAUTH;
type RuntimeMutationResponse = LocalAiStatus | LocalAiOperationResult;

interface PendingRuntimeAdmission {
  admissionId: string;
  name: string;
  expectedModel?: string;
  expectedDigest?: string;
  invoke: () => Promise<RuntimeMutationResponse>;
  onResult?: (result: LocalAiOperationResult | null) => Promise<void> | void;
  refreshModelsOnSuccess: boolean;
  retryCount: number;
  retryAfter: number;
  completing: boolean;
}

function defaultModelFor(selection: ProviderSelection): string {
  return LLM_PROVIDERS.find((provider) => provider.id === selection)?.defaultModel ?? "";
}

function formatBytes(bytes?: number | null): string {
  if (!bytes || bytes < 1) return "unknown size";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** exponent).toFixed(exponent === 0 ? 0 : 1)} ${units[exponent]}`;
}

function boundedDisplayDiagnostic(value: unknown, limit = DISPLAY_DIAGNOSTIC_LIMIT): string {
  if (typeof value !== "string") return "";
  return value.replace(/[\u0000-\u001f\u007f]+/g, " ").trim().slice(0, limit);
}

function runtimeLabel(status: LocalAiStatus | null, statusError = ""): string {
  if (!status) return statusError ? "Unavailable" : "Checking";
  if (status.external_process) return "External server";
  if (status.operation?.state === "running") {
    const labels: Record<LocalAiOperation["kind"], string> = {
      install: "Installing",
      update: "Updating",
      repair: "Repairing",
      rollback: "Rolling back",
      uninstall: "Uninstalling",
      start: "Starting",
      pull_model: "Pulling model",
      delete_model: "Deleting model",
      prune_models: "Pruning model aliases",
      reset_model_digests: "Resetting model trust state",
      accept_model_digest: "Accepting model digest",
      provider_transition: "Changing provider",
    };
    return labels[status.operation.kind];
  }
  if (status.ready) return "Ready";
  if (status.integrity_error) return status.repair_allowed ? "Repair required" : "Recovery blocked";
  if (!status.installed) return "Not installed";
  if (status.state === "failed") return "Failed";
  return "Installed";
}

function activeRuntimeLabel(
  runtimeAction: string | null,
  runtimeReconciliationPending: boolean,
  runtimeReceiptRefreshPending: boolean,
  runtimeStopReconciliationPending: boolean,
  status: LocalAiStatus | null,
  statusError: string,
): string {
  if (runtimeReconciliationPending) return "Reconciling operation";
  if (runtimeStopReconciliationPending) return "Reconciling stop";
  if (runtimeReceiptRefreshPending) return "Refreshing status";
  if (runtimeAction === "refresh") return "Refreshing status";
  if (runtimeAction === "install") return "Installing";
  if (runtimeAction === "update") return "Updating";
  if (runtimeAction === "repair") return "Repairing";
  if (runtimeAction === "rollback") return "Rolling back";
  if (runtimeAction === "uninstall") return "Uninstalling";
  if (runtimeAction === "start") return "Starting";
  if (runtimeAction === "stop") return "Stopping";
  if (runtimeAction === "pull_model") return "Pulling model";
  if (runtimeAction === "accept-model-digest") return "Accepting model digest";
  if (runtimeAction === "reset-model-digests") return "Resetting model trust state";
  if (runtimeAction === "delete-model") return "Deleting model";
  if (runtimeAction === "prune-models") return "Pruning model aliases";
  if (runtimeAction === "reconcile-indeterminate") return "Reconciling unknown outcome";
  return runtimeLabel(status, statusError);
}

function progressFor(status: LocalAiStatus | null): { completed: number; total: number } | null {
  if (!status || status.operation?.state !== "running") return null;
  if (status.operation.kind === "pull_model" && status.model_pull) {
    return { completed: status.model_pull.completed, total: status.model_pull.total };
  }
  if (
    ["install", "update", "repair"].includes(status.operation.kind)
    && status.download_total_bytes > 0
  ) {
    return { completed: status.downloaded_bytes, total: status.download_total_bytes };
  }
  return null;
}

function operationKindForRuntimeAction(action: string | null): LocalAiOperation["kind"] | null {
  if (!action || action === "refresh" || action === "stop") return null;
  const normalised = action.replaceAll("-", "_");
  return normalised === "accept_model_digest"
    || normalised === "reset_model_digests"
    || normalised === "delete_model"
    || normalised === "prune_models"
    || normalised === "pull_model"
    || normalised === "install"
    || normalised === "update"
    || normalised === "repair"
    || normalised === "rollback"
    || normalised === "uninstall"
    || normalised === "start"
    ? normalised
    : null;
}

function pendingActionRequiresResult(pending: PendingRuntimeAdmission): boolean {
  return [
    "pull_model",
    "reset-model-digests",
    "accept-model-digest",
    "delete-model",
    "prune-models",
  ].includes(pending.name);
}

function operationResultMatchesPending(
  pending: PendingRuntimeAdmission,
  result: LocalAiOperationResult,
): boolean {
  if (pending.name === "pull_model") {
    const expectedModel = pending.expectedModel?.trim() ?? "";
    return isLocalAiModelPullResult(result)
      && Boolean(expectedModel)
      && result.model === expectedModel;
  }
  if (pending.name === "reset-model-digests") return "reset" in result && result.reset === true;
  if (pending.name === "accept-model-digest") {
    const expectedModel = pending.expectedModel?.trim() ?? "";
    const expectedDigest = pending.expectedDigest?.trim().toLowerCase() ?? "";
    return "accepted" in result
      && Boolean(expectedModel && expectedDigest)
      && result.digest === expectedDigest
      && result.model === `flinttrade/sha256-${expectedDigest}:locked`
      && localAiModelAliasesEquivalent(result.source_model, expectedModel);
  }
  if (pending.name === "delete-model") {
    return "deleted" in result
      && result.deleted.length === 1
      && result.deleted[0] === pending.expectedModel
      && result.pruned.length === 0;
  }
  if (pending.name === "prune-models") {
    return "deleted" in result && result.deleted.length === 0;
  }
  return false;
}

function modelName(model: LocalAiModel): string {
  return (model.name || model.model || "").trim();
}

function inferenceModelName(model: LocalAiModel): string {
  return model.inference_model?.trim() || modelName(model);
}

function lockedModelDigest(model: string): string {
  return model.match(LOCKED_MODEL_ALIAS)?.[1] ?? "";
}

function teardownReceipt(status: LocalAiStatus, cancelledOperation: boolean): string {
  const mode = status.teardown?.mode ?? "none";
  const activeInferences = status.teardown?.active_inferences ?? 0;
  return `${cancelledOperation ? "Local AI operation cancelled" : "Managed Ollama stopped"}. `
    + `Teardown mode: ${mode}. Active inferences: ${activeInferences}.`;
}

const actionClass =
  "inline-flex h-8 items-center gap-1.5 rounded border border-border-default bg-surface-hover px-3 text-xs font-medium text-text-secondary transition-colors hover:border-accent/40 hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50";

export function LLMSection({
  settings,
  onChange,
  onProviderChange,
  providerActivationRequired = false,
  onDraftStateChange,
  hydrationState = "ready",
  credentialConfigured = false,
  credentialLast4 = "",
  onCredentialRemove,
}: LLMSectionProps) {
  const [testStatus, setTestStatus] = useState<TestStatus>("idle");
  const [testMessage, setTestMessage] = useState("");
  const [runtimeStatus, setRuntimeStatus] = useState<LocalAiStatus | null>(null);
  const [runtimeError, setRuntimeError] = useState("");
  const [runtimeNotice, setRuntimeNotice] = useState("");
  const [models, setModels] = useState<LocalAiModel[]>([]);
  const [modelsLoaded, setModelsLoaded] = useState(false);
  const [modelsError, setModelsError] = useState("");
  const [runtimeAction, setRuntimeAction] = useState<string | null>(null);
  const [runtimeStatusFresh, setRuntimeStatusFresh] = useState(false);
  const [runtimeReceiptRefreshPending, setRuntimeReceiptRefreshPending] = useState(false);
  const [runtimeStopReconciliationPending, setRuntimeStopReconciliationPending] = useState(false);
  const [runtimeIndeterminateBlocked, setRuntimeIndeterminateBlocked] = useState(false);
  const [stopDialogTarget, setStopDialogTarget] = useState<{ operationId: string | null } | null>(null);
  const [digestDialogTarget, setDigestDialogTarget] = useState<{ model: string; digest: string } | null>(null);
  const [pendingRuntimeAdmission, setPendingRuntimeAdmission] = useState<{
    admissionId: string;
    name: string;
    confirmedRunning: boolean;
  } | null>(null);
  const [providerDraft, setProviderDraft] = useState<ProviderSelection | null>(
    () => providerActivationRequired
      ? selectionForLlmSettings(settings.provider, settings.authMode) as ProviderSelection
      : null,
  );
  const [providerHostDraft, setProviderHostDraft] = useState(
    () => providerActivationRequired ? settings.host : "",
  );
  const [providerModelDraft, setProviderModelDraft] = useState(
    () => providerActivationRequired
      ? settings.model.trim() || defaultModelFor(
        selectionForLlmSettings(settings.provider, settings.authMode) as ProviderSelection,
      )
      : "",
  );
  const [providerApiKeyDraft, setProviderApiKeyDraft] = useState("");
  const [credentialDraft, setCredentialDraft] = useState("");
  const [credentialAction, setCredentialAction] = useState<"replacing" | "removing" | null>(null);
  const [providerAction, setProviderAction] = useState<"saving" | "activating" | null>(null);
  const [providerError, setProviderError] = useState("");
  const [hostError, setHostError] = useState("");
  const [modelError, setModelError] = useState("");
  const [credentialError, setCredentialError] = useState("");
  const [activationFailed, setActivationFailed] = useState(false);
  const activationPersistedRef = useRef(false);
  const activationAttemptSignatureRef = useRef("");
  const providerMutationActiveRef = useRef(false);
  const runtimeRequestSequenceRef = useRef(0);
  const runtimeActionSequenceRef = useRef(0);
  const runtimeRefreshPromiseRef = useRef<Promise<LocalAiStatus | null> | null>(null);
  const runtimeStatusRef = useRef<LocalAiStatus | null>(null);
  const runtimePollFailuresRef = useRef(0);
  const runtimeReceiptRefreshPendingRef = useRef(false);
  const runtimeStopReconciliationPendingRef = useRef(false);
  const runtimeIndeterminateBlockedRef = useRef(false);
  const pendingRuntimeAdmissionRef = useRef<PendingRuntimeAdmission | null>(null);
  const runtimeAdmissionRetryActiveRef = useRef(false);
  const modelsRequestSequenceRef = useRef(0);
  const modelsRefreshPromiseRef = useRef<Promise<void> | null>(null);
  const runtimeReadyRef = useRef(false);
  const providerRequestSequenceRef = useRef(0);
  const testRequestSequenceRef = useRef(0);
  const currentModelRef = useRef(settings.model);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      runtimeRequestSequenceRef.current += 1;
      runtimeActionSequenceRef.current += 1;
      modelsRequestSequenceRef.current += 1;
      providerRequestSequenceRef.current += 1;
      testRequestSequenceRef.current += 1;
      pendingRuntimeAdmissionRef.current = null;
      runtimeAdmissionRetryActiveRef.current = false;
      runtimeRefreshPromiseRef.current = null;
      modelsRefreshPromiseRef.current = null;
    };
  }, []);

  const activeSelection = selectionForLlmSettings(
    settings.provider,
    settings.authMode,
  ) as ProviderSelection;
  const selectedProvider: ProviderSelection = providerDraft
    ?? activeSelection;
  const selectedProviderMapping = providerSelection(selectedProvider);
  const persistedProvider = selectedProviderMapping.provider as LlmProvider;
  const isClaudeCodeOAuth = selectedProvider === CLAUDE_CODE_OAUTH;
  const isManagedOllama = selectedProvider === "ollama";
  const showManagedRuntime = isManagedOllama || activeSelection === "ollama";
  const providerConfig = LLM_PROVIDERS.find((provider) => provider.id === selectedProvider);
  const showHost = providerConfig?.requiresHost === true && !isManagedOllama;
  const showApiKey = providerConfig?.requiresApiKey === true;
  const displayedHost = providerConfig?.requiresHost
    ? providerDraft !== null ? providerHostDraft : settings.host
    : "";
  const displayedModel = providerDraft !== null ? providerModelDraft : settings.model;
  const displayedApiKey = providerDraft !== null ? providerApiKeyDraft : credentialDraft;
  currentModelRef.current = displayedModel;
  const activeOperation = runtimeStatus?.operation?.state === "running"
    && runtimeStatus.operation.id?.trim()
    && (
      pendingRuntimeAdmission === null
      || (
        runtimeStatus.operation.admission_id === pendingRuntimeAdmission.admissionId
        && runtimeStatus.operation.kind === operationKindForRuntimeAction(pendingRuntimeAdmission.name)
      )
    )
    ? runtimeStatus.operation
    : null;
  const operationRunning = runtimeStatus?.operation?.state === "running";
  const unresolvedOperation = runtimeStatus?.unresolved_operation
    ?? (
      runtimeStatus?.operation?.state === "indeterminate"
      && runtimeStatus.operation.reconciled_at == null
        ? runtimeStatus.operation
        : null
    );
  const runtimeReconciliationPending = pendingRuntimeAdmission !== null;
  const runtimeAdmissionConfirmedRunning = pendingRuntimeAdmission?.confirmedRunning === true;
  const runtimePolling = Boolean(
    runtimeReconciliationPending
      || runtimeReceiptRefreshPending
      || runtimeStopReconciliationPending
      || operationRunning
      || (runtimeStatus && BUSY_STATES.has(runtimeStatus.state))
      || !runtimeStatusFresh,
  );
  const runtimeBusy = Boolean(
    runtimeAction
      || runtimeReconciliationPending
      || runtimeReceiptRefreshPending
      || runtimeStopReconciliationPending
      || operationRunning
      || (runtimeStatus && BUSY_STATES.has(runtimeStatus.state)),
  );
  const providerBusy = providerAction !== null;
  const hydrationReady = hydrationState === "ready";
  const formBusy = runtimeBusy
    || providerBusy
    || credentialAction !== null
    || !hydrationReady
    || runtimeIndeterminateBlocked;
  const runtimeMutationDisabled = formBusy || !runtimeStatusFresh || runtimeIndeterminateBlocked;
  const canReconcileIndeterminate = Boolean(
    unresolvedOperation
      && runtimeStatusFresh
      && runtimeAction === null
      && pendingRuntimeAdmission === null
      && !runtimeReceiptRefreshPending
      && !runtimeStopReconciliationPending
      && hydrationReady,
  );
  const managedActivationRequired = Boolean(
    hydrationReady
      && isManagedOllama
      && !activationPersistedRef.current
      && (providerActivationRequired || providerDraft === "ollama"),
  );
  const canRepairRuntime = Boolean(
    runtimeStatus?.repair_allowed
      && runtimeStatus.integrity_error
      && !runtimeStatus.external_process
      && !runtimeStatus.managed_process
      && !runtimeStatus.ready
      && !operationRunning
      && !runtimeMutationDisabled,
  );
  const runtimeStopped = Boolean(
    runtimeStatus
      && !runtimeStatus.managed_process
      && !runtimeStatus.external_process
      && !runtimeStatus.ready
      && !operationRunning
      && !runtimeStatus.integrity_error,
  );
  const cancellingOperation = activeOperation !== null;
  const dialogCancellingOperation = Boolean(stopDialogTarget?.operationId);
  const canStopOrCancelRuntime = Boolean(
    showManagedRuntime
      && !runtimeStatus?.external_process
      && (
        cancellingOperation
        || (
          runtimeStatus?.managed_process
          && !operationRunning
          && !runtimeReconciliationPending
          && runtimeAction === null
          && runtimeStatusFresh
        )
      )
      && runtimeAction !== "stop"
      && hydrationReady,
  );
  const canResetModelDigests = modelsError === INVALID_MODEL_DIGEST_STATE_ERROR && !runtimeMutationDisabled;
  const durableOperationError = unresolvedOperation
    ? unresolvedOperation.error || "Local AI operation outcome is unknown"
    : runtimeStatus?.operation?.state === "failed"
      ? runtimeStatus.operation.error || "Local AI operation failed"
      : runtimeIndeterminateBlocked
        ? "Local AI operation outcome is unknown"
        : "";
  const reconciledOperationWarning = runtimeStatus?.operation?.state === "indeterminate"
    && runtimeStatus.operation.reconciled_at != null
    ? "A previous local AI operation was acknowledged, but its outcome remains unknown. Its original admission will not be retried."
    : "";
  const displayedRuntimeError = (isManagedOllama ? providerError : "")
    || runtimeError
    || durableOperationError
    || (runtimeStatus?.integrity_error
      ? runtimeStatus.repair_blocked_reason || runtimeStatus.integrity_error
      : "")
    || runtimeStatus?.error;
  const progressAction = runtimeAction ?? pendingRuntimeAdmission?.name ?? null;
  const expectedProgressKind = operationKindForRuntimeAction(progressAction);
  const progressAdmissionMismatch = pendingRuntimeAdmission !== null
    && runtimeStatus?.operation?.admission_id !== pendingRuntimeAdmission.admissionId;
  const progress = runtimeReceiptRefreshPending
    || runtimeStopReconciliationPending
    || runtimeAction === "stop"
    || progressAdmissionMismatch
    || (progressAction !== null && expectedProgressKind !== runtimeStatus?.operation?.kind)
    ? null
    : progressFor(runtimeStatus);
  const progressPercent = progress && progress.total > 0
    ? Math.min(100, Math.max(0, (progress.completed / progress.total) * 100))
    : 0;
  const progressDeterminate = Boolean(progress && progress.total > 0);
  const runtimeStatusLabel = activeRuntimeLabel(
    runtimeAction,
    runtimeReconciliationPending && !runtimeAdmissionConfirmedRunning,
    runtimeReceiptRefreshPending,
    runtimeStopReconciliationPending,
    runtimeStatus,
    runtimeError,
  );
  const progressValueText = progressDeterminate && progress
    ? `${formatBytes(progress.completed)} of ${formatBytes(progress.total)}`
    : `${runtimeStatusLabel} in progress`;
  const packageVariant = runtimeStatus?.package_variant;
  const inferenceProcessor = boundedDisplayDiagnostic(runtimeStatus?.inference_processor);
  const runtimeLogError = boundedDisplayDiagnostic(runtimeStatus?.log_error);
  const rollbackBlockedReason = boundedDisplayDiagnostic(runtimeStatus?.rollback_blocked_reason);
  const digestDriftDiagnostics = Object.entries(runtimeStatus?.model_digest_drift ?? {})
    .slice(0, 5)
    .map(([model, drift]) => ({
      model: boundedDisplayDiagnostic(model, 96),
      accepted: boundedDisplayDiagnostic(drift.accepted, 64),
      current: boundedDisplayDiagnostic(drift.current, 64),
    }));

  const invalidateConnectionTest = useCallback(() => {
    testRequestSequenceRef.current += 1;
    setTestStatus("idle");
    setTestMessage("");
  }, []);

  useEffect(() => {
    onDraftStateChange?.(providerDraft !== null || credentialDraft.length > 0);
  }, [credentialDraft, onDraftStateChange, providerDraft]);

  useEffect(() => {
    if (
      !providerActivationRequired
      || activationPersistedRef.current
      || providerDraft !== null
    ) {
      return;
    }
    const selection = selectionForLlmSettings(settings.provider, settings.authMode) as ProviderSelection;
    setProviderDraft(selection);
    setProviderHostDraft(settings.host);
    setProviderModelDraft(settings.model.trim() || defaultModelFor(selection));
    setProviderApiKeyDraft("");
  }, [providerActivationRequired, providerDraft, settings.authMode, settings.host, settings.model, settings.provider]);

  useEffect(() => {
    if (
      !providerActivationRequired
      || providerDraft === null
      || settings.provider !== persistedProvider
    ) {
      return;
    }
    setProviderHostDraft(settings.host);
    setProviderModelDraft(settings.model.trim() || defaultModelFor(providerDraft));
  }, [persistedProvider, providerActivationRequired, providerDraft, settings.host, settings.model, settings.provider]);

  useEffect(() => {
    invalidateConnectionTest();
  }, [displayedApiKey, displayedHost, displayedModel, invalidateConnectionTest, selectedProvider]);

  const installedModelOptions = useMemo(
    () => {
      const options = new Map<string, { value: string; label: string }>();
      for (const model of models) {
        const readableName = modelName(model);
        const inferenceName = inferenceModelName(model);
        if (!readableName || !inferenceName) continue;
        const option = {
          value: inferenceName,
          label: readableName === inferenceName ? readableName : `${readableName} (verified)`,
        };
        const existing = options.get(inferenceName);
        if (!existing || readableName !== inferenceName) options.set(inferenceName, option);
      }
      return [...options.values()];
    },
    [models],
  );
  const managedModelValue = useCallback((value: string) => {
    const matchingModel = models.find((model) => (
      localAiModelAliasesEquivalent(modelName(model), value)
      || localAiModelAliasesEquivalent(inferenceModelName(model), value)
    ));
    return matchingModel?.inference_model?.trim() || value;
  }, [models]);
  const selectedModelName = displayedModel.trim();
  const selectedModel = useMemo(
    () => models.find((model) => localAiModelAliasesEquivalent(modelName(model), selectedModelName))
      ?? models.find((model) => localAiModelAliasesEquivalent(inferenceModelName(model), selectedModelName))
      ?? null,
    [models, selectedModelName],
  );
  const selectedInferenceModelName = selectedModel ? inferenceModelName(selectedModel) : "";
  const installedModelSelection = installedModelOptions.find((option) => (
    localAiModelAliasesEquivalent(option.value, selectedModelName)
    || localAiModelAliasesEquivalent(option.value, selectedInferenceModelName)
  ))?.value ?? "";
  const selectedModelIsLockedAlias = Boolean(
    LOCKED_MODEL_ALIAS.test(selectedModelName)
      || LOCKED_MODEL_ALIAS.test(selectedInferenceModelName)
      || selectedModel?.locked_alias
      || models.some((model) => (
        localAiModelAliasesEquivalent(modelName(model), selectedModelName) && model.locked_alias
      )),
  );
  const unselectedModels = useMemo(
    () => models.filter((model) => {
      const name = modelName(model);
      const inferenceName = inferenceModelName(model);
      return Boolean(
        name
          && !localAiModelAliasesEquivalent(name, selectedModelName)
          && !localAiModelAliasesEquivalent(name, selectedInferenceModelName)
          && !localAiModelAliasesEquivalent(inferenceName, selectedModelName)
          && !localAiModelAliasesEquivalent(inferenceName, selectedInferenceModelName),
      );
    }),
    [models, selectedInferenceModelName, selectedModelName],
  );
  const selectedModelAcceptedDigest = selectedModel?.accepted_digest?.trim() ?? "";
  const selectedModelCurrentDigest = selectedModel?.digest?.trim() ?? "";
  const selectedInferenceModelDigest = lockedModelDigest(selectedInferenceModelName);
  const selectedModelDigestDrift = Boolean(
    selectedModel?.digest_drift
      || (
        selectedModelAcceptedDigest
        && selectedModelCurrentDigest
        && selectedModelAcceptedDigest !== selectedModelCurrentDigest
      ),
  );
  const modelAcceptancePending = Boolean(
    runtimeStatus?.model_pull?.acceptance_required
      && [selectedModelName, selectedModel ? modelName(selectedModel) : "", selectedInferenceModelName]
        .some((model) => localAiModelAliasesEquivalent(runtimeStatus.model_pull?.model ?? "", model)),
  );
  const managedModelReady = Boolean(
    modelsLoaded
      && !modelsError
      && selectedModel
      && selectedInferenceModelName
      && selectedInferenceModelDigest
      && selectedModelAcceptedDigest
      && selectedModelCurrentDigest
      && selectedInferenceModelDigest === selectedModelAcceptedDigest
      && !selectedModelDigestDrift
      && !modelAcceptancePending,
  );
  const selectedModelState = !runtimeStatus?.ready
    ? "Runtime not ready"
    : modelsError
      ? "Model state unavailable"
      : !modelsLoaded
        ? "Checking model"
        : selectedModel
          ? "Model installed"
          : "Model not installed";

  const refreshModels = useCallback(async (force = false) => {
    if (!mountedRef.current || !showManagedRuntime || !runtimeReadyRef.current) return;
    if (force) {
      modelsRequestSequenceRef.current += 1;
      modelsRefreshPromiseRef.current = null;
    }
    const existingRefresh = modelsRefreshPromiseRef.current;
    if (existingRefresh) return existingRefresh;

    const requestId = ++modelsRequestSequenceRef.current;
    const refreshPromise = (async () => {
      try {
        const nextModels = await listLocalAiModels();
        if (!mountedRef.current || requestId !== modelsRequestSequenceRef.current || !runtimeReadyRef.current) return;
        setModels(nextModels);
        setModelsLoaded(true);
        setModelsError("");
      } catch (error) {
        if (!mountedRef.current || requestId !== modelsRequestSequenceRef.current || !runtimeReadyRef.current) return;
        setModelsError(error instanceof Error ? error.message : "Model inventory is unavailable");
      }
    })();
    modelsRefreshPromiseRef.current = refreshPromise;
    try {
      await refreshPromise;
    } finally {
      if (modelsRefreshPromiseRef.current === refreshPromise) {
        modelsRefreshPromiseRef.current = null;
      }
    }
  }, [showManagedRuntime]);

  const clearPendingRuntimeAdmission = useCallback((pending: PendingRuntimeAdmission) => {
    if (pendingRuntimeAdmissionRef.current !== pending) return false;
    pendingRuntimeAdmissionRef.current = null;
    runtimeAdmissionRetryActiveRef.current = false;
    if (mountedRef.current) setPendingRuntimeAdmission(null);
    return true;
  }, []);

  const handlePendingMutationError = useCallback((
    pending: PendingRuntimeAdmission,
    error: unknown,
  ) => {
    if (
      !mountedRef.current
      || pendingRuntimeAdmissionRef.current !== pending
      || pending.completing
    ) return false;
    const message = error instanceof Error ? error.message : "Local AI operation failed";
    const conclusiveClientError = error instanceof LocalAiApiError
      && error.statusCode >= 400
      && error.statusCode < 500
      && error.statusCode !== 408;
    setRuntimeError(message);
    setRuntimeStatusFresh(false);
    if (conclusiveClientError) {
      runtimeReceiptRefreshPendingRef.current = true;
      setRuntimeReceiptRefreshPending(true);
      clearPendingRuntimeAdmission(pending);
      return true;
    }
    return false;
  }, [clearPendingRuntimeAdmission]);

  const completePendingRuntimeAdmission = useCallback(async (
    pending: PendingRuntimeAdmission,
    result: LocalAiOperationResult | null,
    operation?: LocalAiOperation,
    refreshInventory = pending.refreshModelsOnSuccess,
  ) => {
    if (!mountedRef.current || pendingRuntimeAdmissionRef.current !== pending) return false;
    if (pending.completing) return true;
    pending.completing = true;
    if (operation && operation.state !== "succeeded") {
      try {
        if (operation.state === "indeterminate") {
          runtimeIndeterminateBlockedRef.current = true;
          setRuntimeIndeterminateBlocked(true);
          setRuntimeError(operation.error || "Local AI operation outcome is unknown");
        } else if (operation.state === "failed") {
          setRuntimeError(operation.error || "Local AI operation failed");
        } else if (operation.state === "cancelled") {
          setRuntimeError("");
          setRuntimeNotice("Local AI operation cancelled.");
        }
        if (refreshInventory) await refreshModels(true);
      } finally {
        pending.completing = false;
        clearPendingRuntimeAdmission(pending);
      }
      return true;
    }

    setRuntimeError("");
    try {
      await pending.onResult?.(result);
      if (!mountedRef.current) return false;
    } catch (error) {
      if (!mountedRef.current) return false;
      setRuntimeError(error instanceof Error ? error.message : "Local AI operation result could not be applied");
    } finally {
      if (mountedRef.current && refreshInventory) await refreshModels(true);
      pending.completing = false;
      clearPendingRuntimeAdmission(pending);
    }
    return true;
  }, [clearPendingRuntimeAdmission, refreshModels]);

  const reconcilePendingRuntimeAdmission = useCallback(async (nextStatus: LocalAiStatus) => {
    const pending = pendingRuntimeAdmissionRef.current;
    if (!pending || nextStatus.operation?.admission_id !== pending.admissionId) return false;
    const expectedKind = operationKindForRuntimeAction(pending.name);
    if (!expectedKind || nextStatus.operation.kind !== expectedKind) {
      runtimeIndeterminateBlockedRef.current = true;
      setRuntimeIndeterminateBlocked(true);
      setRuntimeError("Managed local AI returned a receipt for the wrong operation; the outcome is unknown");
      return true;
    }
    if (nextStatus.operation.state === "running") {
      setRuntimeError("");
      setPendingRuntimeAdmission((current) => (
        current?.admissionId === pending.admissionId
          ? { ...current, confirmedRunning: true }
          : current
      ));
      return true;
    }
    if (
      nextStatus.operation.state === "succeeded"
      && pendingActionRequiresResult(pending)
      && (
        !nextStatus.operation.result
        || !operationResultMatchesPending(pending, nextStatus.operation.result)
      )
    ) {
      runtimeIndeterminateBlockedRef.current = true;
      setRuntimeIndeterminateBlocked(true);
      setRuntimeError("Managed local AI returned an unverified durable receipt; the outcome is unknown");
      return true;
    }
    return completePendingRuntimeAdmission(
      pending,
      nextStatus.operation.result ?? null,
      nextStatus.operation,
    );
  }, [completePendingRuntimeAdmission]);

  const applyRuntimeStatus = useCallback((nextStatus: LocalAiStatus, requestId: number) => {
    if (!mountedRef.current || requestId !== runtimeRequestSequenceRef.current) return null;
    invalidateConnectionTest();
    runtimeStatusRef.current = nextStatus;
    runtimePollFailuresRef.current = 0;
    const stopWasPending = runtimeStopReconciliationPendingRef.current;
    const teardownState = nextStatus.teardown?.state;
    const stopFailed = stopWasPending && teardownState === "failed";
    const stopStillPending = stopWasPending
      && !stopFailed
      && (
        nextStatus.managed_process
        || nextStatus.operation?.state === "running"
        || teardownState === "waiting"
        || teardownState === "stopping"
      );
    runtimeStopReconciliationPendingRef.current = stopStillPending;
    const preserveRuntimeError = runtimeReceiptRefreshPendingRef.current
      || stopStillPending
      || pendingRuntimeAdmissionRef.current !== null;
    runtimeReceiptRefreshPendingRef.current = false;
    const directUnresolvedOperation = nextStatus.operation?.state === "indeterminate"
      && nextStatus.operation.reconciled_at == null
      ? nextStatus.operation
      : null;
    const authoritativeUnresolvedOperation = nextStatus.unresolved_operation ?? directUnresolvedOperation;
    const indeterminateBlocked = authoritativeUnresolvedOperation
      ? true
      : nextStatus.unresolved_operation !== undefined || nextStatus.operation
        ? false
        : runtimeIndeterminateBlockedRef.current;
    runtimeIndeterminateBlockedRef.current = indeterminateBlocked;
    setRuntimeStatusFresh(true);
    setRuntimeReceiptRefreshPending(false);
    setRuntimeStopReconciliationPending(stopStillPending);
    setRuntimeIndeterminateBlocked(indeterminateBlocked);
    setRuntimeStatus(nextStatus);
    if (stopFailed) {
      setRuntimeError(nextStatus.error || "Managed Ollama stop failed");
    } else if (!preserveRuntimeError) {
      setRuntimeError("");
    }
    runtimeReadyRef.current = nextStatus.ready;
    if (!nextStatus.ready) {
      modelsRequestSequenceRef.current += 1;
      modelsRefreshPromiseRef.current = null;
      setModels([]);
      setModelsLoaded(false);
      setModelsError("");
      return nextStatus;
    }

    void refreshModels();
    return nextStatus;
  }, [invalidateConnectionTest, refreshModels]);

  const applyPendingMutationResponse = useCallback(async (
    pending: PendingRuntimeAdmission,
    response: RuntimeMutationResponse,
    refreshInventoryForDirectResult = true,
  ): Promise<"ignored" | "result" | "status" | "unmatched"> => {
    if (pendingRuntimeAdmissionRef.current !== pending) return "ignored";
    if (pending.completing) return "ignored";
    if (isLocalAiStatus(response)) {
      const requestId = ++runtimeRequestSequenceRef.current;
      const appliedStatus = applyRuntimeStatus(response, requestId);
      if (!appliedStatus) return "unmatched";
      return await reconcilePendingRuntimeAdmission(appliedStatus) ? "status" : "unmatched";
    }
    if (!isLocalAiOperationResult(response) || !operationResultMatchesPending(pending, response)) {
      setRuntimeStatusFresh(false);
      setRuntimeError("Managed local AI returned an unverified operation response; reconciling status");
      return "unmatched";
    }
    await completePendingRuntimeAdmission(
      pending,
      response,
      undefined,
      refreshInventoryForDirectResult,
    );
    return "result";
  }, [applyRuntimeStatus, completePendingRuntimeAdmission, reconcilePendingRuntimeAdmission]);

  const retryPendingRuntimeAdmission = useCallback(async () => {
    const pending = pendingRuntimeAdmissionRef.current;
    if (
      !mountedRef.current
      || !pending
      || pending.completing
      || runtimeAdmissionRetryActiveRef.current
      || Date.now() < pending.retryAfter
    ) {
      return;
    }

    pending.retryCount += 1;
    pending.retryAfter = Date.now() + Math.min(
      RUNTIME_POLL_INTERVAL_MS * 2 ** Math.min(
        pending.retryCount,
        RUNTIME_ADMISSION_MAX_BACKOFF_EXPONENT,
      ),
      RUNTIME_POLL_MAX_BACKOFF_MS,
    );
    runtimeAdmissionRetryActiveRef.current = true;
    try {
      const response = await pending.invoke();
      await applyPendingMutationResponse(pending, response);
    } catch (error) {
      handlePendingMutationError(pending, error);
    } finally {
      if (mountedRef.current) runtimeAdmissionRetryActiveRef.current = false;
    }
  }, [applyPendingMutationResponse, handlePendingMutationError]);

  const refreshRuntime = useCallback(async (showBusy = false, force = false) => {
    if (!mountedRef.current || !showManagedRuntime) return null;
    invalidateConnectionTest();
    if (force) {
      runtimeRequestSequenceRef.current += 1;
      runtimeRefreshPromiseRef.current = null;
    }
    const actionId = showBusy ? ++runtimeActionSequenceRef.current : null;
    if (showBusy) {
      setRuntimeAction("refresh");
      setRuntimeError("");
    }

    const existingRefresh = runtimeRefreshPromiseRef.current;
    if (existingRefresh) {
      try {
        return await existingRefresh;
      } finally {
        if (actionId !== null && actionId === runtimeActionSequenceRef.current) {
          setRuntimeAction(null);
        }
      }
    }

    const requestId = ++runtimeRequestSequenceRef.current;
    const refreshPromise = (async () => {
      try {
        const nextStatus = await getLocalAiStatus();
        const appliedStatus = applyRuntimeStatus(nextStatus, requestId);
        if (!appliedStatus) return null;
        const matchedAdmission = await reconcilePendingRuntimeAdmission(appliedStatus);
        if (!matchedAdmission) await retryPendingRuntimeAdmission();
        return appliedStatus;
      } catch (error) {
        if (requestId !== runtimeRequestSequenceRef.current) return null;
        runtimePollFailuresRef.current += 1;
        setRuntimeStatusFresh(false);
        setRuntimeError(error instanceof Error ? error.message : "Local AI status is unavailable");
        if (!runtimeStatusRef.current) {
          runtimeReadyRef.current = false;
          modelsRequestSequenceRef.current += 1;
          modelsRefreshPromiseRef.current = null;
          setModels([]);
          setModelsLoaded(false);
          setModelsError("");
        }
        await retryPendingRuntimeAdmission();
        return null;
      }
    })();
    runtimeRefreshPromiseRef.current = refreshPromise;

    try {
      return await refreshPromise;
    } finally {
      if (runtimeRefreshPromiseRef.current === refreshPromise) {
        runtimeRefreshPromiseRef.current = null;
      }
      if (actionId !== null && actionId === runtimeActionSequenceRef.current) {
        setRuntimeAction(null);
      }
    }
  }, [
    applyRuntimeStatus,
    invalidateConnectionTest,
    reconcilePendingRuntimeAdmission,
    retryPendingRuntimeAdmission,
    showManagedRuntime,
  ]);

  useEffect(() => {
    if (!showManagedRuntime) {
      runtimeRequestSequenceRef.current += 1;
      runtimeActionSequenceRef.current += 1;
      modelsRequestSequenceRef.current += 1;
      runtimeRefreshPromiseRef.current = null;
      modelsRefreshPromiseRef.current = null;
      runtimeReadyRef.current = false;
      runtimeStatusRef.current = null;
      runtimePollFailuresRef.current = 0;
      runtimeReceiptRefreshPendingRef.current = false;
      runtimeStopReconciliationPendingRef.current = false;
      runtimeIndeterminateBlockedRef.current = false;
      pendingRuntimeAdmissionRef.current = null;
      runtimeAdmissionRetryActiveRef.current = false;
      setRuntimeAction(null);
      setRuntimeStatusFresh(false);
      setRuntimeReceiptRefreshPending(false);
      setRuntimeStopReconciliationPending(false);
      setRuntimeIndeterminateBlocked(false);
      setStopDialogTarget(null);
      setDigestDialogTarget(null);
      setPendingRuntimeAdmission(null);
      setRuntimeStatus(null);
      setRuntimeError("");
      setModels([]);
      setModelsLoaded(false);
      setModelsError("");
      return;
    }
    void refreshRuntime();
    return () => {
      runtimeRequestSequenceRef.current += 1;
      modelsRequestSequenceRef.current += 1;
      runtimeRefreshPromiseRef.current = null;
      modelsRefreshPromiseRef.current = null;
    };
  }, [refreshRuntime, showManagedRuntime]);

  useEffect(() => {
    if (!showManagedRuntime || !runtimePolling) return;
    let cancelled = false;
    let timer: number | null = null;

    const scheduleNextPoll = () => {
      const retryDelay = Math.min(
        RUNTIME_POLL_INTERVAL_MS * 2 ** runtimePollFailuresRef.current,
        RUNTIME_POLL_MAX_BACKOFF_MS,
      );
      timer = window.setTimeout(async () => {
        await refreshRuntime();
        if (!cancelled) scheduleNextPoll();
      }, retryDelay);
    };

    scheduleNextPoll();
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
    };
  }, [refreshRuntime, runtimePolling, showManagedRuntime]);

  const commitProvider = useCallback(async (
    selection: ProviderSelection,
    host: string,
    activation = false,
    model = currentModelRef.current.trim(),
    apiKey = providerApiKeyDraft,
    managedModelTrustConfirmed = false,
  ) => {
    if (
      !mountedRef.current
      || !hydrationReady
      || providerMutationActiveRef.current
      || runtimeIndeterminateBlockedRef.current
    ) return false;
    const config = LLM_PROVIDERS.find((candidate) => candidate.id === selection);
    const mapping = providerSelection(selection);
    const provider = mapping.provider as LlmProvider;
    const nextHost = normaliseLlmHost(
      provider,
      config?.requiresHost ? host.trim() : "",
    );
    if (config?.requiresHost && !nextHost) {
      setHostError(`Host URL is required for ${config.name}`);
      return false;
    }
    let nextModel = model.trim();
    if (selection === "ollama" && activation) {
      if (!managedModelTrustConfirmed && !managedModelReady) {
        setModelError("Select an installed model with an accepted, current digest before activation");
        return false;
      }
      if (!managedModelTrustConfirmed) nextModel = selectedInferenceModelName;
    }
    if (!nextModel) {
      setModelError("Model is required");
      return false;
    }
    const replacementKey = apiKey.trim();
    if (config?.requiresApiKey && !replacementKey) {
      setCredentialError(`Credential is required for ${config.name}`);
      return false;
    }

    providerMutationActiveRef.current = true;
    invalidateConnectionTest();
    const requestId = ++providerRequestSequenceRef.current;
    setProviderAction(activation ? "activating" : "saving");
    setProviderError("");
    setHostError("");
    setModelError("");
    setCredentialError("");
    if (activation) setActivationFailed(false);
    try {
      if (!mountedRef.current) return false;
      if (config?.requiresApiKey) {
        if (mapping.authMode === "claude-code-oauth") {
          await onProviderChange(provider, nextHost, nextModel, replacementKey, mapping.authMode);
        } else {
          await onProviderChange(provider, nextHost, nextModel, replacementKey);
        }
      } else {
        await onProviderChange(provider, nextHost, nextModel);
      }
      if (requestId !== providerRequestSequenceRef.current) return false;
      setProviderDraft(null);
      setProviderHostDraft("");
      setProviderModelDraft("");
      setProviderApiKeyDraft("");
      setCredentialDraft("");
      if (activation) activationPersistedRef.current = true;
      return true;
    } catch (error) {
      if (requestId !== providerRequestSequenceRef.current) return false;
      setProviderError(error instanceof Error ? error.message : "LLM provider could not be activated");
      if (activation) setActivationFailed(true);
      if (activeSelection === "ollama" && selection !== "ollama") await refreshRuntime();
      return false;
    } finally {
      providerMutationActiveRef.current = false;
      if (requestId === providerRequestSequenceRef.current) setProviderAction(null);
    }
  }, [
    hydrationReady,
    activeSelection,
    invalidateConnectionTest,
    managedModelReady,
    onProviderChange,
    providerApiKeyDraft,
    refreshRuntime,
    selectedInferenceModelName,
  ]);

  useEffect(() => {
    if (isManagedOllama) return;
    activationPersistedRef.current = false;
    setActivationFailed(false);
  }, [isManagedOllama]);

  useEffect(() => {
    if (!providerActivationRequired) activationAttemptSignatureRef.current = "";
  }, [providerActivationRequired]);

  useEffect(() => {
    if (
      !providerActivationRequired
      || !hydrationReady
      || isManagedOllama
      || providerConfig?.requiresApiKey
      || activationPersistedRef.current
      || activationFailed
      || providerAction
    ) {
      return;
    }
    const signature = `${selectedProvider}\u0000${displayedHost.trim()}\u0000${displayedModel.trim()}`;
    if (activationAttemptSignatureRef.current === signature) return;
    activationAttemptSignatureRef.current = signature;
    void commitProvider(selectedProvider, displayedHost, true);
  }, [
    activationFailed,
    commitProvider,
    displayedHost,
    displayedModel,
    hydrationReady,
    isManagedOllama,
    providerAction,
    providerActivationRequired,
    providerConfig?.requiresApiKey,
    selectedProvider,
  ]);

  const handleProviderChange = useCallback(
    (value: string) => {
      if (formBusy) return;
      invalidateConnectionTest();
      if (value === selectedProvider) return;
      setProviderError("");
      setHostError("");
      setModelError("");
      setCredentialError("");
      setCredentialDraft("");
      setActivationFailed(false);
      activationPersistedRef.current = false;

      if (providerDraft !== null && value === activeSelection && !providerActivationRequired) {
        setProviderDraft(null);
        setProviderHostDraft("");
        setProviderModelDraft("");
        setProviderApiKeyDraft("");
        return;
      }

      const nextConfig = LLM_PROVIDERS.find((candidate) => candidate.id === value);
      if (value === "ollama") {
        setProviderDraft("ollama");
        setProviderHostDraft("");
        setProviderModelDraft(nextConfig?.defaultModel ?? "");
        setProviderApiKeyDraft("");
        return;
      }
      if (nextConfig?.requiresHost || nextConfig?.requiresApiKey) {
        setProviderDraft(value as ProviderSelection);
        // Never carry the managed Ollama endpoint into Hermes or Custom.
        setProviderHostDraft("");
        setProviderModelDraft(nextConfig.defaultModel);
        setProviderApiKeyDraft("");
        return;
      }
      void commitProvider(value as ProviderSelection, "");
    },
    [
      activeSelection,
      commitProvider,
      invalidateConnectionTest,
      providerActivationRequired,
      providerDraft,
      formBusy,
      selectedProvider,
    ],
  );

  const runRuntimeAction = useCallback(async (
    name: string,
    action: (admissionId: string) => Promise<LocalAiStatus>,
    refreshModelsOnSuccess = false,
    expectations: Pick<PendingRuntimeAdmission, "expectedModel" | "expectedDigest"> = {},
  ) => {
    if (
      !mountedRef.current
      || !runtimeStatusFresh
      || runtimeIndeterminateBlockedRef.current
      || pendingRuntimeAdmissionRef.current
    ) return;
    invalidateConnectionTest();
    const actionId = ++runtimeActionSequenceRef.current;
    const admissionId = createLocalAiAdmissionId();
    const pending: PendingRuntimeAdmission = {
      admissionId,
      name,
      ...expectations,
      invoke: () => action(admissionId),
      onResult: undefined,
      refreshModelsOnSuccess,
      retryCount: 0,
      retryAfter: Date.now() + RUNTIME_POLL_INTERVAL_MS,
      completing: false,
    };
    pendingRuntimeAdmissionRef.current = pending;
    setPendingRuntimeAdmission({ admissionId, name, confirmedRunning: false });
    setRuntimeAction(name);
    setRuntimeError("");
    setRuntimeNotice("");
    try {
      const response = await pending.invoke();
      const responseKind = await applyPendingMutationResponse(pending, response);
      if (responseKind === "unmatched") await refreshRuntime(false, true);
    } catch (error) {
      if (pendingRuntimeAdmissionRef.current === pending && !pending.completing) {
        handlePendingMutationError(pending, error);
        void refreshRuntime(false, true);
      }
    } finally {
      if (actionId === runtimeActionSequenceRef.current) setRuntimeAction(null);
    }
  }, [
    applyPendingMutationResponse,
    handlePendingMutationError,
    invalidateConnectionTest,
    refreshRuntime,
    runtimeStatusFresh,
  ]);

  const runResultAction = useCallback(async (
    name: string,
    action: (admissionId: string) => Promise<RuntimeMutationResponse>,
    onResult?: (result: LocalAiOperationResult | null) => Promise<void> | void,
    refreshModelsOnSuccess = true,
    expectations: Pick<PendingRuntimeAdmission, "expectedModel" | "expectedDigest"> = {},
  ) => {
    if (
      !mountedRef.current
      || !runtimeStatusFresh
      || runtimeIndeterminateBlockedRef.current
      || pendingRuntimeAdmissionRef.current
    ) return;
    invalidateConnectionTest();
    const actionId = ++runtimeActionSequenceRef.current;
    const admissionId = createLocalAiAdmissionId();
    const pending: PendingRuntimeAdmission = {
      admissionId,
      name,
      ...expectations,
      invoke: () => action(admissionId),
      onResult,
      refreshModelsOnSuccess,
      retryCount: 0,
      retryAfter: Date.now() + RUNTIME_POLL_INTERVAL_MS,
      completing: false,
    };
    pendingRuntimeAdmissionRef.current = pending;
    setPendingRuntimeAdmission({ admissionId, name, confirmedRunning: false });
    setRuntimeAction(name);
    setRuntimeError("");
    setRuntimeNotice("");
    try {
      const response = await pending.invoke();
      const responseKind = await applyPendingMutationResponse(pending, response);
      if (responseKind === "result" || responseKind === "unmatched") {
        await refreshRuntime(false, true);
      }
    } catch (error) {
      if (pendingRuntimeAdmissionRef.current === pending && !pending.completing) {
        handlePendingMutationError(pending, error);
        void refreshRuntime(false, true);
      }
    } finally {
      if (actionId === runtimeActionSequenceRef.current) setRuntimeAction(null);
    }
  }, [
    applyPendingMutationResponse,
    handlePendingMutationError,
    invalidateConnectionTest,
    refreshRuntime,
    runtimeStatusFresh,
  ]);

  const handleStopOrCancelRuntime = useCallback(async (expectedOperationId?: string) => {
    if (!mountedRef.current) return;
    const wasCancellation = Boolean(expectedOperationId);
    invalidateConnectionTest();
    const requestId = ++runtimeRequestSequenceRef.current;
    const actionId = ++runtimeActionSequenceRef.current;
    setRuntimeAction("stop");
    setRuntimeError("");
    setRuntimeNotice("");
    try {
      const nextStatus = await stopLocalAiRuntime(expectedOperationId);
      const appliedStatus = applyRuntimeStatus(nextStatus, requestId);
      if (appliedStatus) setRuntimeNotice(teardownReceipt(appliedStatus, wasCancellation));
    } catch (error) {
      if (requestId === runtimeRequestSequenceRef.current) {
        setRuntimeStatusFresh(false);
        runtimeStopReconciliationPendingRef.current = true;
        setRuntimeStopReconciliationPending(true);
        setRuntimeError(error instanceof Error ? error.message : "Managed Ollama could not be stopped");
        void refreshRuntime(false, true);
      }
    } finally {
      if (actionId === runtimeActionSequenceRef.current) setRuntimeAction(null);
    }
  }, [applyRuntimeStatus, invalidateConnectionTest, refreshRuntime]);

  const handleReconcileIndeterminate = useCallback(async (target: LocalAiOperation) => {
    if (!mountedRef.current || target.state !== "indeterminate" || target.reconciled_at != null) return;
    invalidateConnectionTest();
    const requestId = ++runtimeRequestSequenceRef.current;
    const actionId = ++runtimeActionSequenceRef.current;
    setRuntimeAction("reconcile-indeterminate");
    setRuntimeError("");
    setRuntimeNotice("");
    try {
      const nextStatus = await reconcileLocalAiOperation(target.id, target.admission_id);
      const appliedStatus = applyRuntimeStatus(nextStatus, requestId);
      if (appliedStatus) {
        setRuntimeNotice(
          appliedStatus.unresolved_operation
            ? "This unknown outcome was acknowledged. Another indeterminate operation still requires review."
            : "Unknown outcome acknowledged. The original admission remains consumed and will not be retried.",
        );
      }
    } catch (error) {
      if (requestId === runtimeRequestSequenceRef.current) {
        setRuntimeStatusFresh(false);
        setRuntimeError(error instanceof Error ? error.message : "Unknown local AI outcome could not be reconciled");
        void refreshRuntime(false, true);
      }
    } finally {
      if (actionId === runtimeActionSequenceRef.current) setRuntimeAction(null);
    }
  }, [applyRuntimeStatus, invalidateConnectionTest, refreshRuntime]);

  const handleResetModelDigests = useCallback(async () => {
    await runResultAction(
      "reset-model-digests",
      (admissionId) => resetLocalAiModelDigests(admissionId),
      undefined,
    );
  }, [runResultAction]);

  const handleAcceptModelDigest = useCallback(async (target: { model: string; digest: string }) => {
    if (
      target.model !== selectedModelName
      || target.digest !== selectedModelCurrentDigest
    ) {
      setRuntimeError("Model inventory changed; review the current digest before accepting it");
      void refreshModels(true);
      return;
    }
    await runResultAction(
      "accept-model-digest",
      (admissionId) => acceptLocalAiModelDigest(
        target.model,
        target.digest,
        admissionId,
      ),
      async (result) => {
        if (!result || !("accepted" in result) || result.accepted !== true) {
          throw new Error("Model digest acceptance receipt is missing");
        }
        const acceptance = result as LocalAiModelDigestAcceptance;
        const acceptedModel = acceptance.model?.trim() || currentModelRef.current.trim();
        if (managedActivationRequired) {
          setProviderModelDraft(acceptedModel);
          const activated = await commitProvider("ollama", "", true, acceptedModel, "", true);
          if (!activated) return;
        } else if (acceptance.model && acceptance.model !== target.model) {
          onChange("model", acceptance.model);
        }
      },
      true,
      {
        expectedModel: target.model,
        expectedDigest: target.digest,
      },
    );
  }, [
    commitProvider,
    managedActivationRequired,
    onChange,
    refreshModels,
    runResultAction,
    selectedModelCurrentDigest,
    selectedModelName,
  ]);

  const runModelReclamation = useCallback(async (
    name: "delete-model" | "prune-models",
    action: (admissionId: string) => Promise<RuntimeMutationResponse>,
    expectedModel?: string,
  ) => {
    await runResultAction(name, action, undefined, true, { expectedModel });
  }, [runResultAction]);

  const handleTestConnection = useCallback(async () => {
    const requestId = ++testRequestSequenceRef.current;
    setTestStatus("testing");
    setTestMessage("");

    if (providerConfig?.requiresHost && !displayedHost.trim()) {
      setHostError(`Host URL is required for ${providerConfig.name}`);
      setTestStatus("error");
      setTestMessage("Enter a host URL before testing.");
      return;
    }
    if (!displayedModel.trim()) {
      setModelError("Model is required");
      setTestStatus("error");
      setTestMessage("Enter a model before testing.");
      return;
    }
    if (providerDraft !== null && providerConfig?.requiresApiKey && !displayedApiKey.trim()) {
      setCredentialError(`Credential is required for ${providerConfig.name}`);
      setTestStatus("error");
      setTestMessage("Enter an API key before testing.");
      return;
    }

    try {
      const config = {
        provider: persistedProvider,
        host: providerConfig?.requiresHost ? displayedHost.trim() : "",
        model: displayedModel.trim(),
        ...(displayedApiKey.trim() ? { apiKey: displayedApiKey } : {}),
      };
      const response = await testLlmConnection(config);
      if (requestId !== testRequestSequenceRef.current) return;
      setTestStatus("ok");
      setTestMessage(`Connection successful: ${response.data.provider} / ${response.data.model}.`);
    } catch (error) {
      if (requestId !== testRequestSequenceRef.current) return;
      setTestStatus("error");
      setTestMessage(error instanceof Error ? error.message : "Connection failed.");
    }
  }, [
    displayedApiKey,
    displayedHost,
    displayedModel,
    persistedProvider,
    providerDraft,
    providerConfig,
  ]);

  const handleReplaceCredential = useCallback(async () => {
    if (!credentialDraft.trim()) {
      setCredentialError(`Credential is required for ${providerConfig?.name ?? "this provider"}`);
      return;
    }
    setCredentialAction("replacing");
    try {
      await commitProvider(activeSelection, settings.host, false, settings.model, credentialDraft);
    } finally {
      setCredentialAction(null);
    }
  }, [activeSelection, commitProvider, credentialDraft, providerConfig?.name, settings.host, settings.model]);

  const handleRemoveCredential = useCallback(async () => {
    if (!onCredentialRemove || !hydrationReady) return;
    invalidateConnectionTest();
    setCredentialAction("removing");
    setProviderError("");
    try {
      await onCredentialRemove();
      setCredentialDraft("");
    } catch (error) {
      setProviderError(error instanceof Error ? error.message : "The stored credential could not be removed");
    } finally {
      setCredentialAction(null);
    }
  }, [hydrationReady, invalidateConnectionTest, onCredentialRemove]);

  return (
    <div className="space-y-5">
      <SectionTitle>LLM Config</SectionTitle>

      {hydrationState === "loading" && (
        <p className="text-xs text-text-muted" role="status" aria-live="polite">
          Loading AI settings
        </p>
      )}
      {hydrationState === "error" && (
        <p className="flex items-start gap-1.5 text-xs text-loss" role="alert" aria-live="assertive">
          <AlertCircle size={13} className="mt-0.5 shrink-0" />
          AI settings could not be loaded. Editing is disabled to protect the saved configuration.
        </p>
      )}

      <FieldRow
        label="Provider"
        hint="Managed Ollama runs locally; Hermes uses an operator-supplied local host; cloud and custom providers use their own credentials."
      >
        <fieldset
          className="m-0 min-w-0 border-0 p-0 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={formBusy}
        >
          <SelectInput
            value={selectedProvider}
            onChange={handleProviderChange}
            options={LLM_PROVIDER_OPTIONS}
            aria-label="LLM provider"
          />
        </fieldset>
        {providerAction && (
          <p className="flex items-center gap-1.5 text-xs text-text-muted" role="status">
            <Loader2 size={12} className="animate-spin" />
            {providerAction === "activating" ? "Activating provider" : "Saving provider"}
          </p>
        )}
      </FieldRow>

      {isClaudeCodeOAuth && (
        <p className="text-xs text-text-muted -mt-2">
          Claude Code OAuth credential uses the Anthropic backend while remaining a separate authentication choice.
        </p>
      )}

      {showManagedRuntime && (
        <div
          className="space-y-3 border-y border-border-default py-3"
          aria-busy={runtimeBusy}
          aria-label="Managed Ollama runtime"
        >
          <div className="flex min-h-8 flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-text-primary">Managed Ollama</span>
                <span
                  className="text-xs text-text-muted"
                  role="status"
                  aria-live="polite"
                  aria-atomic="true"
                >
                  {runtimeStatusLabel}
                </span>
              </div>
              {runtimeStatus?.server_version && (
                <p className="text-xs text-text-muted">Server {runtimeStatus.server_version}</p>
              )}
              {inferenceProcessor && (
                <p className="max-w-full break-words text-xs text-text-muted">
                  Inference processor {inferenceProcessor}
                </p>
              )}
              {runtimeStatus?.installed && runtimeStatus.active_version && (
                <p className="text-xs text-text-muted">Runtime {runtimeStatus.active_version}</p>
              )}
              {runtimeStatus?.rollback_available
                && runtimeStatus.rollback_allowed
                && runtimeStatus.previous_version
                && (
                <p className="text-xs text-text-muted">
                  Rollback {runtimeStatus.previous_version} available
                </p>
                )}
              {runtimeStatus?.rollback_available
                && !runtimeStatus.rollback_allowed
                && rollbackBlockedReason
                && (
                  <p className="max-w-full break-words text-xs text-text-muted">
                    Rollback unavailable: {rollbackBlockedReason}
                  </p>
                )}
              {packageVariant && (
                <p className="text-xs text-text-muted">
                  Package selection {packageVariant === "rocm"
                    ? "ROCm"
                    : packageVariant === "jetpack5"
                      ? "JetPack 5"
                      : "JetPack 6"}
                </p>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="inline-flex size-8 items-center justify-center rounded border border-border-default text-text-secondary hover:text-text-primary disabled:opacity-50"
                onClick={() => void refreshRuntime(true)}
                disabled={
                  runtimeAction === "refresh"
                  || runtimeAction === "stop"
                  || runtimeStopReconciliationPending
                  || providerBusy
                  || !hydrationReady
                }
                aria-label="Refresh runtime status"
                title="Refresh runtime status"
              >
                <RefreshCw size={14} className={runtimeAction === "refresh" ? "animate-spin" : ""} />
              </button>

              {runtimeStatus
                && !runtimeStatus.installed
                && !runtimeStatus.external_process
                && !runtimeStatus.integrity_error
                && (
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <button type="button" className={actionClass} disabled={runtimeMutationDisabled}>
                        <Download size={13} />
                        Install runtime
                      </button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Install managed Ollama?</AlertDialogTitle>
                        <AlertDialogDescription>
                          FlintTrade will download the pinned official {runtimeStatus.version} archive, verify its
                          SHA-256 hash, and keep it in the local workspace. Reserve at least{" "}
                          {formatBytes(runtimeStatus.install_required_bytes)}. Ollama is distributed under the MIT
                          licence.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction
                          onClick={() => {
                            void runRuntimeAction("install", installLocalAiRuntime);
                          }}
                        >
                          Download and install
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                )}

              {canRepairRuntime && (
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <button type="button" className={actionClass}>
                      <Wrench size={13} />
                      Repair runtime
                    </button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Repair managed Ollama?</AlertDialogTitle>
                      <AlertDialogDescription>
                        FlintTrade will replace the corrupt managed runtime files and download the pinned official
                        archive again. This action is available only while no managed or external Ollama server is
                        active.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={() => void runRuntimeAction("repair", repairLocalAiRuntime)}
                      >
                        Replace and repair
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              )}

              {runtimeStopped
                && runtimeStatus?.installed
                && runtimeStatus.update_available
                && (
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <button type="button" className={actionClass} disabled={runtimeMutationDisabled}>
                        <Download size={13} />
                        Update runtime
                      </button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Update managed Ollama?</AlertDialogTitle>
                        <AlertDialogDescription>
                          FlintTrade will download and verify the pinned official {runtimeStatus.target_version}
                          archive, retain {runtimeStatus.active_version} as the rollback version, and activate the
                          update without changing installed models.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction onClick={() => void runRuntimeAction("update", updateLocalAiRuntime)}>
                          Download and update
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                )}

              {runtimeStatus?.rollback_available
                && runtimeStatus.previous_version
                && (
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <button
                        type="button"
                        className={actionClass}
                        disabled={runtimeMutationDisabled || !runtimeStatus.rollback_allowed}
                      >
                        <RotateCcw size={13} />
                        Rollback runtime
                      </button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Rollback managed Ollama?</AlertDialogTitle>
                        <AlertDialogDescription>
                          FlintTrade will fully rehash the retained {runtimeStatus.previous_version} runtime before
                          switching to it. Installed models and accepted-digest metadata will remain unchanged.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction onClick={() => void runRuntimeAction("rollback", rollbackLocalAiRuntime)}>
                          Switch to {runtimeStatus.previous_version}
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                )}

              {runtimeStopped && runtimeStatus?.installed && (
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <button type="button" className={actionClass} disabled={runtimeMutationDisabled}>
                      <Trash2 size={13} />
                      Uninstall runtime
                    </button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Uninstall managed Ollama?</AlertDialogTitle>
                      <AlertDialogDescription>
                        FlintTrade will remove its managed Ollama runtime archives and executables. Models and
                        accepted-digest metadata will remain so they can be reused after reinstalling.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction onClick={() => void runRuntimeAction("uninstall", uninstallLocalAiRuntime)}>
                        Remove runtime
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              )}

              {runtimeStatus?.installed
                && !runtimeStatus.ready
                && !runtimeStatus.external_process
                && !runtimeStatus.managed_process
                && !runtimeStatus.integrity_error
                && (
                  <button
                    type="button"
                    className={actionClass}
                    disabled={runtimeMutationDisabled}
                    onClick={() => void runRuntimeAction("start", startLocalAiRuntime)}
                    aria-label="Start runtime"
                  >
                    <Play size={13} />
                    Start
                  </button>
                )}

              {canStopOrCancelRuntime && (
                <AlertDialog
                  open={stopDialogTarget !== null}
                  onOpenChange={(open) => {
                    setStopDialogTarget((current) => (
                      open ? current ?? { operationId: activeOperation?.id ?? null } : null
                    ));
                  }}
                >
                  <AlertDialogTrigger asChild>
                    <button
                      type="button"
                      className={actionClass}
                      disabled={runtimeAction === "stop" || providerBusy || !hydrationReady}
                      aria-label={cancellingOperation ? "Cancel local AI operation" : "Stop runtime"}
                      onClick={() => setStopDialogTarget({ operationId: activeOperation?.id ?? null })}
                    >
                      <Square size={12} />
                      {cancellingOperation ? "Cancel operation" : "Stop"}
                    </button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>
                        {dialogCancellingOperation ? "Cancel the local AI operation?" : "Stop managed Ollama?"}
                      </AlertDialogTitle>
                      <AlertDialogDescription>
                        {dialogCancellingOperation
                          ? "FlintTrade will cancel the active download or transition and stop only its owned Ollama process."
                          : "FlintTrade will stop only its owned Ollama process after a bounded inference drain."}
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Keep running</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={() => void handleStopOrCancelRuntime(stopDialogTarget?.operationId ?? undefined)}
                      >
                        {dialogCancellingOperation ? "Cancel operation" : "Stop runtime"}
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              )}

              {managedActivationRequired
                && !activationFailed
                && runtimeStatus?.managed_process
                && runtimeStatus.ready
                && !runtimeStatus.external_process
                && (
                  <button
                    type="button"
                    className={actionClass}
                    disabled={runtimeMutationDisabled || !managedModelReady}
                    onClick={() => void commitProvider(
                      "ollama",
                      "",
                      true,
                      selectedInferenceModelName,
                    )}
                    aria-label="Activate managed Ollama"
                  >
                    <CheckCircle2 size={13} />
                    Activate
                  </button>
                )}

              {managedActivationRequired
                && activationFailed
                && runtimeStatus?.managed_process
                && runtimeStatus.ready
                && (
                  <button
                    type="button"
                    className={actionClass}
                    disabled={runtimeMutationDisabled || !managedModelReady}
                    onClick={() => void commitProvider(
                      "ollama",
                      "",
                      true,
                      selectedInferenceModelName,
                    )}
                    aria-label="Retry activation"
                  >
                    <RefreshCw size={13} />
                    Retry activation
                  </button>
                )}
            </div>
          </div>

          {runtimeBusy && (
            <div
              className="space-y-1"
              role="progressbar"
              aria-label="Local AI operation progress"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={progressDeterminate ? Math.round(progressPercent) : undefined}
              aria-valuetext={progressValueText}
            >
              <div className="h-1.5 w-full overflow-hidden rounded bg-surface-hover">
                <div
                  className={`h-full bg-accent transition-[width] ${progressDeterminate ? "" : "animate-pulse"}`}
                  style={{ width: progressDeterminate ? `${progressPercent}%` : "35%" }}
                />
              </div>
              {progressDeterminate && progress && (
                <p className="text-xs text-text-muted">
                  {formatBytes(progress.completed)} / {formatBytes(progress.total)}
                </p>
              )}
            </div>
          )}

          {displayedRuntimeError && (
            <p className="flex min-w-0 items-start gap-1.5 break-words text-xs text-loss" role="alert">
              <AlertCircle size={13} className="mt-0.5 shrink-0" />
              <span className="min-w-0 break-words">{displayedRuntimeError}</span>
            </p>
          )}

          {unresolvedOperation && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <button type="button" className={actionClass} disabled={!canReconcileIndeterminate}>
                  <ShieldAlert size={13} />
                  Review unknown outcome
                </button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Acknowledge an unknown local AI outcome?</AlertDialogTitle>
                  <AlertDialogDescription>
                    The {unresolvedOperation.kind.replaceAll("_", " ")} operation may have succeeded or partially
                    succeeded. FlintTrade will preserve this receipt, keep its original admission consumed, and permit
                    new operations. It will not replay the unknown operation.
                    <span className="mt-2 block break-all font-mono text-xs">
                      {unresolvedOperation.id} / {unresolvedOperation.admission_id}
                    </span>
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Keep operations blocked</AlertDialogCancel>
                  <AlertDialogAction onClick={() => void handleReconcileIndeterminate(unresolvedOperation)}>
                    Acknowledge unknown outcome
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}

          {reconciledOperationWarning && (
            <p className="min-w-0 break-words text-xs text-text-secondary" role="status">
              {reconciledOperationWarning}
            </p>
          )}

          {runtimeLogError && (
            <p className="min-w-0 break-words text-xs text-loss" role="alert">
              Runtime log diagnostic {runtimeLogError}
            </p>
          )}

          {digestDriftDiagnostics.map((diagnostic) => (
            <p
              key={`${diagnostic.model}:${diagnostic.current}`}
              className="min-w-0 break-all text-xs text-loss"
              role="alert"
            >
              Digest drift reported for {diagnostic.model}. Accepted {diagnostic.accepted}; current {diagnostic.current}.
            </p>
          ))}

          {runtimeNotice && (
            <p className="min-w-0 break-words text-xs text-text-secondary" role="status" aria-live="polite">
              {runtimeNotice}
            </p>
          )}

          {modelsError && (
            <p className="flex min-w-0 items-start gap-1.5 break-words text-xs text-loss" role="alert">
              <AlertCircle size={13} className="mt-0.5 shrink-0" />
              <span className="min-w-0 break-words">{modelsError}</span>
            </p>
          )}

          {canResetModelDigests && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <button type="button" className={actionClass}>
                  <ShieldAlert size={13} />
                  Reset model trust state
                </button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Reset model trust state?</AlertDialogTitle>
                  <AlertDialogDescription>
                    This removes only FlintTrade's invalid accepted-digest metadata. It does not delete Ollama model
                    blobs. Model inventory will be checked again after the reset.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction onClick={() => void handleResetModelDigests()}>
                    Reset trust metadata
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          )}
        </div>
      )}

      {showHost && (
        <FieldRow label="Host URL" hint="Base URL of the OpenAI-compatible inference server.">
          <TextInput
            value={displayedHost}
            onChange={(value) => {
              invalidateConnectionTest();
              setProviderError("");
              setHostError(
                providerConfig?.requiresHost && !value.trim()
                  ? `Host URL is required for ${providerConfig.name}`
                  : "",
              );
              if (providerDraft !== null) {
                setProviderHostDraft(value);
              } else {
                activationPersistedRef.current = false;
                setProviderDraft(activeSelection);
                setProviderHostDraft(value);
                setProviderModelDraft(settings.model.trim() || defaultModelFor(activeSelection));
                // A credential is scoped to its exact destination. Never carry
                // the active endpoint's raw key into a new-host draft.
                setProviderApiKeyDraft("");
                setCredentialDraft("");
              }
            }}
            placeholder={providerConfig?.defaultHost || "https://your-endpoint.example.com"}
            aria-label="LLM host URL"
            aria-invalid={Boolean(hostError)}
            aria-describedby={hostError ? "llm-settings-host-error" : undefined}
            disabled={formBusy}
          />
          {hostError && (
            <p id="llm-settings-host-error" className="text-xs text-loss" role="alert" aria-live="assertive">
              {hostError}
            </p>
          )}
        </FieldRow>
      )}

      {!isManagedOllama && providerError && (
        <div className="flex flex-wrap items-center gap-2">
          <p
            className="flex min-w-0 items-start gap-1.5 break-words text-xs text-loss"
            role="alert"
            aria-live="assertive"
          >
            <AlertCircle size={13} className="mt-0.5 shrink-0" />
            <span className="min-w-0 break-words">{providerError}</span>
          </p>
          {activationFailed && (
            <button
              type="button"
              className={actionClass}
              disabled={formBusy}
              onClick={() => void commitProvider(selectedProvider, displayedHost, true)}
            >
              <RefreshCw size={13} />
              Retry provider setup
            </button>
          )}
        </div>
      )}

      {isManagedOllama && installedModelOptions.length > 0 && (
        <FieldRow label="Installed Models">
          <fieldset
            className="m-0 min-w-0 border-0 p-0 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={runtimeMutationDisabled}
          >
            <SelectInput
              value={installedModelSelection}
              onChange={(value) => {
                if (runtimeMutationDisabled) return;
                invalidateConnectionTest();
                setModelError(value.trim() ? "" : "Model is required");
                const inferenceValue = managedModelValue(value);
                if (providerDraft !== null) setProviderModelDraft(inferenceValue);
                else onChange("model", inferenceValue);
              }}
              options={[{ value: "", label: "Select a model" }, ...installedModelOptions]}
              aria-label="Installed Ollama model"
            />
          </fieldset>
        </FieldRow>
      )}

      {isManagedOllama && modelsLoaded && models.length > 0 && (
        <div className="space-y-2 border-b border-border-default pb-3 text-xs" aria-label="Ollama model inventory">
          {unselectedModels.map((model) => {
            const modelName = model.name || model.model || "";
            return (
              <div key={modelName} className="flex min-h-8 items-center justify-between gap-3">
                <div className="min-w-0">
                  <span className="block truncate font-medium text-text-primary">{modelName}</span>
                  <span className="text-text-muted">{formatBytes(model.size)}</span>
                </div>
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <button
                      type="button"
                      className="inline-flex size-8 shrink-0 items-center justify-center rounded border border-border-default text-text-secondary hover:border-loss/40 hover:text-loss disabled:opacity-50"
                      disabled={runtimeMutationDisabled}
                      aria-label={`Delete ${modelName}`}
                      title={`Delete ${modelName}`}
                    >
                      <Trash2 size={13} />
                    </button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle className="min-w-0 break-all">Delete {modelName}?</AlertDialogTitle>
                      <AlertDialogDescription>
                        This removes the exact Ollama model name from the local server. Shared storage may remain when
                        another model name still references the same data.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction
                        onClick={() => void runModelReclamation(
                          "delete-model",
                          (admissionId) => deleteLocalAiModel(modelName, admissionId),
                          modelName,
                        )}
                      >
                        Delete model
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            );
          })}

          <AlertDialog>
            <AlertDialogTrigger asChild>
              <button
                type="button"
                className={actionClass}
                disabled={runtimeMutationDisabled}
                aria-label="Prune unused model aliases"
              >
                <Trash2 size={13} />
                Prune aliases
              </button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>Prune unused FlintTrade aliases?</AlertDialogTitle>
                <AlertDialogDescription>
                  FlintTrade will remove only its unreferenced digest-locked aliases. It will not scan or delete
                  arbitrary Ollama model files, and configured models remain protected.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancel</AlertDialogCancel>
                <AlertDialogAction
                  onClick={() => void runModelReclamation("prune-models", pruneLocalAiModels)}
                >
                  Prune aliases
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      )}

      {isManagedOllama && selectedModelName && (
        <div
          className="space-y-2 border-b border-border-default pb-3 text-xs"
          aria-label="Selected Ollama model state"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span className="font-medium text-text-primary">{selectedModelState}</span>
            {selectedModel?.size != null && selectedModel.size > 0 && (
              <span className="text-text-muted">{formatBytes(selectedModel.size)}</span>
            )}
          </div>
          {selectedModel && (
            <div className="space-y-1">
              <span className="text-text-muted">Accepted digest</span>
              {selectedModelAcceptedDigest ? (
                <code className="block break-all font-mono text-text-secondary">
                  {selectedModelAcceptedDigest}
                </code>
              ) : (
                <p className="flex items-start gap-1.5 text-loss" role="alert">
                  <AlertCircle size={13} className="mt-0.5 shrink-0" />
                  Accepted digest unavailable for this mutable tag. Treat the configured model as unverifiable.
                </p>
              )}
              {(selectedModelDigestDrift || (!selectedModelAcceptedDigest && selectedModelCurrentDigest)) && (
                <>
                  <span className="block pt-1 text-text-muted">Current digest</span>
                  <code className="block break-all font-mono text-text-secondary">
                    {selectedModelCurrentDigest}
                  </code>
                </>
              )}
              {selectedModelDigestDrift && (
                <p className="flex items-start gap-1.5 pt-1 text-loss" role="alert">
                  <AlertCircle size={13} className="mt-0.5 shrink-0" />
                  Mutable-tag drift detected. The live model no longer matches the digest accepted after download.
                </p>
              )}
              {selectedModelCurrentDigest
                && (selectedModelDigestDrift || !selectedModelAcceptedDigest)
                && (
                  <AlertDialog
                    open={digestDialogTarget !== null}
                    onOpenChange={(open) => {
                      setDigestDialogTarget(open
                        ? { model: selectedModelName, digest: selectedModelCurrentDigest }
                        : null);
                    }}
                  >
                    <AlertDialogTrigger asChild>
                      <button
                        type="button"
                        className={`${actionClass} mt-2`}
                        disabled={runtimeMutationDisabled}
                        aria-label="Accept current model digest"
                      >
                        <ShieldAlert size={13} />
                        Accept digest
                      </button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Accept this model digest?</AlertDialogTitle>
                        <AlertDialogDescription>
                          Confirm the exact current SHA-256 digest for {digestDialogTarget?.model}. FlintTrade will switch
                          inference to a digest-derived locked alias.
                        </AlertDialogDescription>
                        <code className="break-all font-mono text-xs text-text-secondary">
                          {digestDialogTarget?.digest}
                        </code>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction
                          onClick={() => {
                            if (digestDialogTarget) void handleAcceptModelDigest(digestDialogTarget);
                          }}
                        >
                          Accept exact digest
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                )}
            </div>
          )}
        </div>
      )}

      <FieldRow
        label="Model Name"
        hint={isManagedOllama
          ? "Canonical Ollama model identifier, for example qwen3:8b."
          : selectedProvider === "hermes"
            ? "Model identifier served by the configured Hermes host."
            : "Model identifier from the selected provider."}
      >
        <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-2">
          <TextInput
            value={displayedModel}
            onChange={(value) => {
              invalidateConnectionTest();
              setProviderError("");
              setModelError(value.trim() ? "" : "Model is required");
              if (providerDraft !== null) setProviderModelDraft(value);
              else onChange("model", isManagedOllama ? managedModelValue(value) : value);
            }}
            placeholder={providerConfig?.defaultModel || "Enter model identifier"}
            aria-label="LLM model name"
            aria-invalid={Boolean(modelError)}
            aria-describedby={modelError ? "llm-settings-model-error" : undefined}
            disabled={isManagedOllama ? runtimeMutationDisabled : formBusy}
          />
          {isManagedOllama
            && runtimeStatus?.managed_process
            && runtimeStatus.ready
            && !selectedModelIsLockedAlias
            && (
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <button
                  type="button"
                  className={actionClass}
                  disabled={runtimeMutationDisabled || !displayedModel.trim()}
                >
                  <Download size={13} />
                  Pull model
                </button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle className="min-w-0 break-all">
                    Download {displayedModel.trim()}?
                  </AlertDialogTitle>
                  <AlertDialogDescription>
                    Model licence and disk requirements vary by publisher. Confirm that this model is suitable before
                    downloading; model weights commonly require several gigabytes in the FlintTrade workspace.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => void runRuntimeAction(
                      "pull_model",
                      (admissionId) => pullLocalAiModel(displayedModel.trim(), admissionId),
                      true,
                      { expectedModel: displayedModel.trim() },
                    )}
                  >
                    Download model
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
            )}
        </div>
        {modelError && (
          <p id="llm-settings-model-error" className="text-xs text-loss" role="alert" aria-live="assertive">
            {modelError}
          </p>
        )}
      </FieldRow>

      {showApiKey && (
        <FieldRow
          label={isClaudeCodeOAuth ? "OAuth Credential" : "API Key"}
          hint={providerDraft !== null
            ? "Required for this provider draft; stored only after activation succeeds."
            : isClaudeCodeOAuth
              ? "Kept local until you explicitly replace the stored OAuth value."
              : "Kept local until you explicitly replace the stored credential."}
        >
          <TextInput
            value={displayedApiKey}
            onChange={(value) => {
              invalidateConnectionTest();
              setProviderError("");
              setCredentialError("");
              if (providerDraft !== null) setProviderApiKeyDraft(value);
              else setCredentialDraft(value);
            }}
            type="password"
            placeholder={isClaudeCodeOAuth ? "OAuth credential" : "API key"}
            aria-label={isClaudeCodeOAuth ? "Claude Code OAuth credential" : "LLM provider API key"}
            aria-invalid={Boolean(credentialError)}
            aria-describedby={credentialError ? "llm-settings-credential-error" : undefined}
            disabled={formBusy}
          />
          {credentialError && (
            <p id="llm-settings-credential-error" className="text-xs text-loss" role="alert" aria-live="assertive">
              {credentialError}
            </p>
          )}
          {providerDraft === null && credentialConfigured && (
            <p className="text-xs text-text-muted" role="status">
              Stored credential{credentialLast4 ? ` ending in ${credentialLast4}` : " configured"}
            </p>
          )}
          {providerDraft === null && (
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <button
                type="button"
                className={actionClass}
                disabled={formBusy || !credentialDraft.trim()}
                onClick={() => void handleReplaceCredential()}
              >
                {credentialAction === "replacing"
                  ? <Loader2 size={13} className="animate-spin" />
                  : <CheckCircle2 size={13} />}
                Replace credential
              </button>
              {credentialConfigured && onCredentialRemove && (
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <button type="button" className={actionClass} disabled={formBusy}>
                      Remove credential
                    </button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Remove stored LLM credential?</AlertDialogTitle>
                      <AlertDialogDescription>
                        The active provider will remain selected, but authenticated requests will fail until a new
                        credential is stored.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction onClick={() => void handleRemoveCredential()}>
                        Remove stored credential
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              )}
            </div>
          )}
        </FieldRow>
      )}

      {providerDraft !== null && !isManagedOllama && (
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className={actionClass}
            disabled={formBusy}
            onClick={() => void commitProvider(
              providerDraft,
              providerHostDraft,
              providerActivationRequired,
              providerModelDraft,
              providerApiKeyDraft,
            )}
          >
            {providerAction ? <Loader2 size={13} className="animate-spin" /> : <CheckCircle2 size={13} />}
            {providerActivationRequired ? "Activate provider" : "Apply provider"}
          </button>
        </div>
      )}

      <div className="flex min-h-8 flex-wrap items-center gap-3 pt-1">
        <button
          type="button"
          onClick={() => void handleTestConnection()}
          disabled={testStatus === "testing" || formBusy || (isManagedOllama && !runtimeStatusFresh)}
          className={actionClass}
        >
          {testStatus === "testing" ? (
            <Loader2 size={12} className="animate-spin" />
          ) : testStatus === "ok" ? (
            <CheckCircle2 size={12} className="text-profit" />
          ) : testStatus === "error" ? (
            <AlertCircle size={12} className="text-loss" />
          ) : (
            <RefreshCw size={12} />
          )}
          Test Connection
        </button>
        {testMessage && (
          <span
            className={`min-w-0 break-words text-xs ${testStatus === "ok" ? "text-profit" : "text-loss"}`}
            role={testStatus === "error" ? "alert" : "status"}
            aria-live="polite"
            aria-atomic="true"
          >
            {testMessage}
          </span>
        )}
      </div>
    </div>
  );
}
