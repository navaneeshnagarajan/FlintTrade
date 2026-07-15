import { buildHeaders, getBase } from "./ftApi.helpers";

export type LocalAiOperationState = "running" | "succeeded" | "failed" | "cancelled" | "indeterminate";
export type LocalAiOperationKind =
  | "install"
  | "update"
  | "repair"
  | "rollback"
  | "uninstall"
  | "start"
  | "pull_model"
  | "delete_model"
  | "prune_models"
  | "reset_model_digests"
  | "accept_model_digest"
  | "provider_transition";

export interface LocalAiModelDigestReset {
  reset: boolean;
}

export interface LocalAiModelDigestAcceptance {
  accepted: boolean;
  model: string;
  source_model: string;
  digest: string;
}

export interface LocalAiModelReclamation {
  deleted: string[];
  pruned: string[];
}

export interface LocalAiModelPullResult {
  model: string;
  status: "success" | "awaiting_digest_acceptance";
  completed: number;
  total: number;
  digest: string;
  previous_digest: string | null;
  digest_changed: boolean;
  acceptance_required: boolean;
  error: null;
}

export type LocalAiOperationResult =
  | LocalAiModelDigestReset
  | LocalAiModelDigestAcceptance
  | LocalAiModelReclamation
  | LocalAiModelPullResult;
export type LocalAiMutationReceipt<T extends LocalAiOperationResult> = T | LocalAiStatus;

export interface LocalAiOperation {
  id: string;
  admission_id: string;
  kind: LocalAiOperationKind;
  state: LocalAiOperationState;
  started_at?: number;
  finished_at?: number | null;
  reconciled_at?: number | null;
  error?: string | null;
  result?: LocalAiOperationResult | null;
}

export interface LocalAiModelPull {
  model: string;
  status: string;
  completed: number;
  total: number;
  digest?: string | null;
  previous_digest?: string | null;
  digest_changed?: boolean;
  acceptance_required?: boolean;
  error?: string | null;
}

export interface LocalAiTeardown {
  state: "idle" | "waiting" | "stopping" | "stopped" | "failed";
  mode: "graceful" | "forced" | null;
  active_inferences: number;
}

export interface LocalAiModelDigestDrift {
  accepted: string;
  current: string;
}

export interface LocalAiStatus {
  version: string;
  active_version: string;
  target_version: string;
  previous_version?: string | null;
  update_available: boolean;
  rollback_available: boolean;
  rollback_allowed: boolean;
  rollback_blocked_reason?: string | null;
  repair_allowed: boolean;
  repair_blocked_reason?: string | null;
  supported: boolean;
  installed: boolean;
  state: string;
  ready: boolean;
  managed_process: boolean;
  external_process: boolean;
  package_variant?: "rocm" | "jetpack5" | "jetpack6" | null;
  inference_processor?: string | null;
  server_version?: string | null;
  downloaded_bytes: number;
  download_total_bytes: number;
  install_required_bytes: number;
  model_pull?: LocalAiModelPull | null;
  model_digest_drift?: Record<string, LocalAiModelDigestDrift>;
  operation?: LocalAiOperation | null;
  unresolved_operation?: LocalAiOperation | null;
  teardown?: LocalAiTeardown;
  error?: string | null;
  log_error?: string | null;
  integrity_error?: string | null;
}

export interface LocalAiModel {
  name?: string;
  model?: string;
  inference_model?: string;
  digest?: string;
  accepted_digest?: string;
  digest_drift?: boolean;
  locked_alias?: boolean;
  size?: number;
  modified_at?: string;
  details?: Record<string, unknown>;
}

const RUNTIME_ENDPOINT = "ai/local-runtime";
export const LOCAL_AI_REQUEST_TIMEOUT_MS = 10_000;
const LOCAL_AI_ADMISSION_ID = /^adm_[0-9a-f]{32}$/;
const LOCAL_AI_OPERATION_ID = /^op_[0-9a-f]{32}$/;
const LOCAL_AI_MODEL_DIGEST = /^[0-9a-f]{64}$/;
const LOCAL_AI_LOCKED_MODEL_ALIAS = /^flinttrade\/sha256-([0-9a-f]{64}):locked$/;
const LOCAL_AI_OPERATION_KINDS = new Set<LocalAiOperationKind>([
  "install",
  "update",
  "repair",
  "rollback",
  "uninstall",
  "start",
  "pull_model",
  "delete_model",
  "prune_models",
  "reset_model_digests",
  "accept_model_digest",
  "provider_transition",
]);
const LOCAL_AI_OPERATION_STATES = new Set<LocalAiOperationState>([
  "running",
  "succeeded",
  "failed",
  "cancelled",
  "indeterminate",
]);

type UnknownRecord = Record<string, unknown>;
type ResponseValidator<T> = (value: unknown) => value is T;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isOptionalString(value: unknown): value is string | null | undefined {
  return value === undefined || value === null || typeof value === "string";
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isLocalAiModelDigestReset(value: unknown): value is LocalAiModelDigestReset {
  return isRecord(value) && value.reset === true;
}

function isLocalAiModelDigestAcceptance(value: unknown): value is LocalAiModelDigestAcceptance {
  return isRecord(value)
    && value.accepted === true
    && typeof value.model === "string"
    && value.model.trim().length > 0
    && typeof value.source_model === "string"
    && value.source_model.trim().length > 0
    && typeof value.digest === "string"
    && LOCAL_AI_MODEL_DIGEST.test(value.digest);
}

function isLocalAiModelReclamation(value: unknown): value is LocalAiModelReclamation {
  return isRecord(value) && isStringArray(value.deleted) && isStringArray(value.pruned);
}

export function isLocalAiModelPullResult(value: unknown): value is LocalAiModelPullResult {
  if (!isRecord(value)) return false;
  const previousDigest = value.previous_digest;
  const digest = value.digest;
  const acceptanceRequired = previousDigest !== digest;
  return typeof value.model === "string"
    && value.model.trim().length > 0
    && (value.status === "success" || value.status === "awaiting_digest_acceptance")
    && isFiniteNumber(value.completed)
    && Number.isSafeInteger(value.completed)
    && isFiniteNumber(value.total)
    && Number.isSafeInteger(value.total)
    && value.total > 0
    && value.completed === value.total
    && typeof digest === "string"
    && LOCAL_AI_MODEL_DIGEST.test(digest)
    && (previousDigest === null || (
      typeof previousDigest === "string" && LOCAL_AI_MODEL_DIGEST.test(previousDigest)
    ))
    && typeof value.digest_changed === "boolean"
    && value.digest_changed === Boolean(previousDigest && previousDigest !== digest)
    && typeof value.acceptance_required === "boolean"
    && value.acceptance_required === acceptanceRequired
    && value.status === (acceptanceRequired ? "awaiting_digest_acceptance" : "success")
    && value.error === null;
}

function isOperationResultForKind(
  kind: LocalAiOperationKind,
  state: LocalAiOperationState,
  result: unknown,
): boolean {
  if (state !== "succeeded") return result === undefined || result === null;
  if (kind === "pull_model") return isLocalAiModelPullResult(result);
  if (kind === "reset_model_digests") return isLocalAiModelDigestReset(result);
  if (kind === "accept_model_digest") return isLocalAiModelDigestAcceptance(result);
  if (kind === "delete_model") {
    return isLocalAiModelReclamation(result)
      && result.deleted.length === 1
      && result.pruned.length === 0;
  }
  if (kind === "prune_models") {
    return isLocalAiModelReclamation(result) && result.deleted.length === 0;
  }
  return result === undefined || result === null;
}

export function isLocalAiOperationResult(value: unknown): value is LocalAiOperationResult {
  return isLocalAiModelDigestReset(value)
    || isLocalAiModelDigestAcceptance(value)
    || isLocalAiModelReclamation(value)
    || isLocalAiModelPullResult(value);
}

function isLocalAiOperation(value: unknown): value is LocalAiOperation {
  if (!isRecord(value)) return false;
  if (
    typeof value.kind !== "string"
    || !LOCAL_AI_OPERATION_KINDS.has(value.kind as LocalAiOperationKind)
    || typeof value.state !== "string"
    || !LOCAL_AI_OPERATION_STATES.has(value.state as LocalAiOperationState)
  ) return false;
  return typeof value.id === "string"
    && LOCAL_AI_OPERATION_ID.test(value.id)
    && typeof value.admission_id === "string"
    && LOCAL_AI_ADMISSION_ID.test(value.admission_id)
    && (value.started_at === undefined || isFiniteNumber(value.started_at))
    && (value.finished_at === undefined || value.finished_at === null || isFiniteNumber(value.finished_at))
    && (
      value.reconciled_at === undefined
      || value.reconciled_at === null
      || (
        value.state === "indeterminate"
        && isFiniteNumber(value.reconciled_at)
        && (value.finished_at === undefined || value.finished_at === null || value.reconciled_at >= value.finished_at)
      )
    )
    && isOptionalString(value.error)
    && isOperationResultForKind(
      value.kind as LocalAiOperationKind,
      value.state as LocalAiOperationState,
      value.result,
    );
}

function isExpectedDigestAcceptance(
  value: unknown,
  sourceModel: string,
  digest: string,
): value is LocalAiModelDigestAcceptance {
  const expectedDigest = digest.trim().toLowerCase();
  return isLocalAiModelDigestAcceptance(value)
    && value.digest === expectedDigest
    && value.model === `flinttrade/sha256-${expectedDigest}:locked`
    && localAiModelAliasesEquivalent(value.source_model, sourceModel);
}

function isLocalAiModelPull(value: unknown): value is LocalAiModelPull {
  return isRecord(value)
    && typeof value.model === "string"
    && typeof value.status === "string"
    && isFiniteNumber(value.completed)
    && isFiniteNumber(value.total)
    && isOptionalString(value.digest)
    && isOptionalString(value.previous_digest)
    && (value.digest_changed === undefined || typeof value.digest_changed === "boolean")
    && (value.acceptance_required === undefined || typeof value.acceptance_required === "boolean")
    && isOptionalString(value.error);
}

function isLocalAiTeardown(value: unknown): value is LocalAiTeardown {
  return isRecord(value)
    && ["idle", "waiting", "stopping", "stopped", "failed"].includes(String(value.state))
    && (value.mode === null || value.mode === "graceful" || value.mode === "forced")
    && isFiniteNumber(value.active_inferences);
}

function isLocalAiDigestDriftMap(value: unknown): value is Record<string, LocalAiModelDigestDrift> {
  return isRecord(value) && Object.values(value).every((entry) => (
    isRecord(entry)
    && typeof entry.accepted === "string"
    && LOCAL_AI_MODEL_DIGEST.test(entry.accepted)
    && typeof entry.current === "string"
    && LOCAL_AI_MODEL_DIGEST.test(entry.current)
  ));
}

export function isLocalAiStatus(value: unknown): value is LocalAiStatus {
  if (!isRecord(value)) return false;
  return typeof value.version === "string"
    && typeof value.active_version === "string"
    && typeof value.target_version === "string"
    && isOptionalString(value.previous_version)
    && typeof value.update_available === "boolean"
    && typeof value.rollback_available === "boolean"
    && typeof value.rollback_allowed === "boolean"
    && isOptionalString(value.rollback_blocked_reason)
    && typeof value.repair_allowed === "boolean"
    && isOptionalString(value.repair_blocked_reason)
    && typeof value.supported === "boolean"
    && typeof value.installed === "boolean"
    && typeof value.state === "string"
    && typeof value.ready === "boolean"
    && typeof value.managed_process === "boolean"
    && typeof value.external_process === "boolean"
    && (
      value.package_variant === undefined
      || value.package_variant === null
      || value.package_variant === "rocm"
      || value.package_variant === "jetpack5"
      || value.package_variant === "jetpack6"
    )
    && isFiniteNumber(value.downloaded_bytes)
    && isFiniteNumber(value.download_total_bytes)
    && isFiniteNumber(value.install_required_bytes)
    && (value.operation === undefined || value.operation === null || isLocalAiOperation(value.operation))
    && (
      value.unresolved_operation === undefined
      || value.unresolved_operation === null
      || (
        isLocalAiOperation(value.unresolved_operation)
        && value.unresolved_operation.state === "indeterminate"
        && (
          value.unresolved_operation.reconciled_at === undefined
          || value.unresolved_operation.reconciled_at === null
        )
      )
    )
    && (value.model_pull === undefined || value.model_pull === null || isLocalAiModelPull(value.model_pull))
    && (value.model_digest_drift === undefined || isLocalAiDigestDriftMap(value.model_digest_drift))
    && (value.teardown === undefined || isLocalAiTeardown(value.teardown))
    && isOptionalString(value.server_version)
    && isOptionalString(value.inference_processor)
    && isOptionalString(value.error)
    && isOptionalString(value.log_error)
    && isOptionalString(value.integrity_error);
}

function isLocalAiModel(value: unknown): value is LocalAiModel {
  if (!isRecord(value)) return false;
  const modelName = typeof value.name === "string" ? value.name : value.model;
  if (!(typeof modelName === "string"
    && modelName.trim().length > 0
    && isOptionalString(value.name)
    && isOptionalString(value.model)
    && isOptionalString(value.inference_model)
    && isOptionalString(value.digest)
    && isOptionalString(value.accepted_digest)
    && (value.digest_drift === undefined || typeof value.digest_drift === "boolean")
    && (value.locked_alias === undefined || typeof value.locked_alias === "boolean")
    && (value.size === undefined || isFiniteNumber(value.size))
    && isOptionalString(value.modified_at)
    && (value.details === undefined || isRecord(value.details)))) return false;

  const digest = typeof value.digest === "string" ? value.digest : "";
  const acceptedDigest = typeof value.accepted_digest === "string" ? value.accepted_digest : "";
  const inferenceModel = typeof value.inference_model === "string" ? value.inference_model.trim() : "";
  if (digest && !LOCAL_AI_MODEL_DIGEST.test(digest)) return false;
  if (acceptedDigest && !LOCAL_AI_MODEL_DIGEST.test(acceptedDigest)) return false;

  const inferenceDigest = inferenceModel.match(LOCAL_AI_LOCKED_MODEL_ALIAS)?.[1] ?? "";
  const modelAliasDigest = modelName.trim().match(LOCAL_AI_LOCKED_MODEL_ALIAS)?.[1] ?? "";
  if (inferenceModel && !inferenceDigest) return false;
  if (inferenceDigest && acceptedDigest !== inferenceDigest) return false;
  if (acceptedDigest && !inferenceDigest && acceptedDigest !== modelAliasDigest) return false;
  if (value.locked_alias === true && (
    !modelAliasDigest
    || digest !== modelAliasDigest
    || acceptedDigest !== modelAliasDigest
  )) return false;
  if (value.digest_drift !== undefined && (
    !digest
    || !acceptedDigest
    || value.digest_drift !== (digest !== acceptedDigest)
  )) return false;
  return true;
}

function isLocalAiModelList(value: unknown): value is LocalAiModel[] {
  return Array.isArray(value) && value.every(isLocalAiModel);
}

function mutationReceiptValidator<T extends LocalAiOperationResult>(
  resultValidator: ResponseValidator<T>,
): ResponseValidator<LocalAiMutationReceipt<T>> {
  return (value: unknown): value is LocalAiMutationReceipt<T> => (
    isLocalAiStatus(value) || resultValidator(value)
  );
}

export function createLocalAiAdmissionId(): string {
  const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `adm_${hex}`;
}

function admittedMutationBody(body: object, admissionId?: string): object {
  const selectedAdmissionId = admissionId ?? createLocalAiAdmissionId();
  if (!LOCAL_AI_ADMISSION_ID.test(selectedAdmissionId)) {
    throw new Error("Managed local AI admission ID is invalid");
  }
  return { ...body, admission_id: selectedAdmissionId };
}

function canonicalLocalAiModelAlias(model: string): string {
  const trimmed = model.trim();
  const tail = trimmed.slice(trimmed.lastIndexOf("/") + 1);
  return tail.endsWith(":latest") ? trimmed.slice(0, -":latest".length) : trimmed;
}

export function localAiModelAliasesEquivalent(left: string, right: string): boolean {
  const canonicalLeft = canonicalLocalAiModelAlias(left);
  const canonicalRight = canonicalLocalAiModelAlias(right);
  return Boolean(canonicalLeft && canonicalLeft === canonicalRight);
}

export class LocalAiApiError extends Error {
  readonly reason?: string;
  readonly correlationId?: string;
  readonly statusCode: number;

  constructor(
    message: string,
    options: { reason?: string; correlationId?: string; statusCode: number },
  ) {
    const details = [
      options.reason ? `Reason: ${options.reason}.` : "",
      options.correlationId ? `Diagnostic ID: ${options.correlationId}.` : "",
    ].filter(Boolean);
    super([message, ...details].join(" "));
    this.name = "LocalAiApiError";
    this.reason = options.reason;
    this.correlationId = options.correlationId;
    this.statusCode = options.statusCode;
  }
}

function boundedDiagnostic(value: unknown, limit: number): string | undefined {
  if (typeof value !== "string") return undefined;
  const normalised = value.replace(/[\u0000-\u001f\u007f]+/g, " ").trim();
  return normalised ? normalised.slice(0, limit) : undefined;
}

function errorFromResponse(payload: unknown, statusCode: number, endpoint: string): LocalAiApiError {
  const envelope = payload !== null && typeof payload === "object"
    ? payload as Record<string, unknown>
    : null;
  const data = envelope?.data !== null && typeof envelope?.data === "object"
    ? envelope.data as Record<string, unknown>
    : null;
  const message = boundedDiagnostic(envelope?.message ?? envelope?.error, 300)
    ?? `FT API ${endpoint}: HTTP ${statusCode}`;
  return new LocalAiApiError(message, {
    reason: boundedDiagnostic(data?.reason, 300),
    correlationId: boundedDiagnostic(data?.correlation_id, 96),
    statusCode,
  });
}

async function requestLocalAi<T>(
  endpoint: string,
  method: "GET" | "POST",
  validator: ResponseValidator<T>,
  body?: object,
): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), LOCAL_AI_REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${getBase()}/v1/${endpoint}`, {
      ...(method === "POST" ? { method, body: JSON.stringify(body ?? {}) } : {}),
      headers: buildHeaders(method === "POST"),
      signal: controller.signal,
    });
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      if (!response.ok) throw errorFromResponse(null, response.status, endpoint);
      throw new LocalAiApiError("Managed local AI returned an invalid response", {
        statusCode: response.status,
      });
    }
    const failedEnvelope = payload !== null
      && typeof payload === "object"
      && "status" in payload
      && (payload as { status: unknown }).status === "error";
    if (!response.ok || failedEnvelope) {
      throw errorFromResponse(payload, response.status, endpoint);
    }
    const data = payload !== null && typeof payload === "object" && "data" in payload
      ? (payload as { data: unknown }).data
      : payload;
    if (!validator(data)) {
      throw new LocalAiApiError("Managed local AI returned an invalid response", {
        statusCode: response.status,
      });
    }
    return data;
  } catch (error) {
    if (controller.signal.aborted) {
      throw new LocalAiApiError("Managed local AI request timed out", { statusCode: 408 });
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

function getRuntime<T>(path: string, validator: ResponseValidator<T>): Promise<T> {
  return requestLocalAi<T>(`${RUNTIME_ENDPOINT}/${path}`, "GET", validator);
}

function postRuntime<T>(path: string, body: object, validator: ResponseValidator<T>): Promise<T> {
  return requestLocalAi<T>(`${RUNTIME_ENDPOINT}/${path}`, "POST", validator, body);
}

export function getLocalAiStatus(): Promise<LocalAiStatus> {
  return getRuntime("status", isLocalAiStatus);
}

export function installLocalAiRuntime(admissionId?: string): Promise<LocalAiStatus> {
  return postRuntime("install", admittedMutationBody({ confirmed: true }, admissionId), isLocalAiStatus);
}

export function updateLocalAiRuntime(admissionId?: string): Promise<LocalAiStatus> {
  return postRuntime("update", admittedMutationBody({ confirmed: true }, admissionId), isLocalAiStatus);
}

export function repairLocalAiRuntime(admissionId?: string): Promise<LocalAiStatus> {
  return postRuntime("repair", admittedMutationBody({ confirmed: true }, admissionId), isLocalAiStatus);
}

export function rollbackLocalAiRuntime(admissionId?: string): Promise<LocalAiStatus> {
  return postRuntime("rollback", admittedMutationBody({ confirmed: true }, admissionId), isLocalAiStatus);
}

export function uninstallLocalAiRuntime(admissionId?: string): Promise<LocalAiStatus> {
  return postRuntime("uninstall", admittedMutationBody({ confirmed: true }, admissionId), isLocalAiStatus);
}

export function startLocalAiRuntime(admissionId?: string): Promise<LocalAiStatus> {
  return postRuntime("start", admittedMutationBody({}, admissionId), isLocalAiStatus);
}

export function stopLocalAiRuntime(expectedOperationId?: string): Promise<LocalAiStatus> {
  return postRuntime(
    "stop",
    expectedOperationId ? { expected_operation_id: expectedOperationId } : {},
    isLocalAiStatus,
  );
}

export function reconcileLocalAiOperation(
  operationId: string,
  admissionId: string,
): Promise<LocalAiStatus> {
  if (!LOCAL_AI_OPERATION_ID.test(operationId)) {
    throw new Error("Managed local AI operation ID is invalid");
  }
  if (!LOCAL_AI_ADMISSION_ID.test(admissionId)) {
    throw new Error("Managed local AI admission ID is invalid");
  }
  return postRuntime(
    "operations/reconcile",
    { confirmed: true, operation_id: operationId, admission_id: admissionId },
    isLocalAiStatus,
  );
}

export function listLocalAiModels(): Promise<LocalAiModel[]> {
  return getRuntime("models", isLocalAiModelList);
}

export function resetLocalAiModelDigests(
  admissionId?: string,
): Promise<LocalAiMutationReceipt<LocalAiModelDigestReset>> {
  return postRuntime(
    "models/digests/reset",
    admittedMutationBody({ confirmed: true }, admissionId),
    mutationReceiptValidator(isLocalAiModelDigestReset),
  );
}

export function acceptLocalAiModelDigest(
  model: string,
  digest: string,
  admissionId?: string,
): Promise<LocalAiMutationReceipt<LocalAiModelDigestAcceptance>> {
  return postRuntime(
    "models/digests/accept",
    admittedMutationBody({ model, digest, confirmed: true }, admissionId),
    mutationReceiptValidator((value): value is LocalAiModelDigestAcceptance => (
      isExpectedDigestAcceptance(value, model, digest)
    )),
  );
}

export function pullLocalAiModel(model: string, admissionId?: string): Promise<LocalAiStatus> {
  return postRuntime(
    "models/pull",
    admittedMutationBody({ model, confirmed: true }, admissionId),
    isLocalAiStatus,
  );
}

export function deleteLocalAiModel(
  model: string,
  admissionId?: string,
): Promise<LocalAiMutationReceipt<LocalAiModelReclamation>> {
  return postRuntime(
    "models/delete",
    admittedMutationBody({ model, confirmed: true }, admissionId),
    mutationReceiptValidator(isLocalAiModelReclamation),
  );
}

export function pruneLocalAiModels(
  admissionId?: string,
): Promise<LocalAiMutationReceipt<LocalAiModelReclamation>> {
  return postRuntime(
    "models/prune",
    admittedMutationBody({ confirmed: true }, admissionId),
    mutationReceiptValidator(isLocalAiModelReclamation),
  );
}
