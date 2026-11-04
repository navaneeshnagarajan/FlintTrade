import { z } from "zod";
import { onlineManager } from "@tanstack/react-query";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import {
  GrantRequestV2Schema, InspectRequestV2Schema, StartRequestV2Schema, TransferAcceptRequestV2Schema,
  TransferReceiptV2Schema, type GrantRequestV2, type InspectRequestV2, type TransferReceiptV2,
} from "@/generated/nativeAutonomyV2";
import { captureAuthSessionFence, isAuthSessionFenceCurrent, useAuthStore, type AuthSessionFence } from "@/stores/authStore";
import { buildHeaders, getBase, isDemoAuthSession } from "./ftApi.helpers";

import {
  nativeConfigSchema, nativeProjectionSchema, nativeV2ConfigurationSchema, nativeV2ViewSchema,
  nativeV2PreviewSchema, type NativeV2Preview, type NativeV2View,
} from "./executionSessionNative";
import { canonicalPolicy, runPolicyAuthorityKey, subscribeRunPolicyAuthority } from "./runPolicyTransport";

const Id = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}(?![\s\S])/);
const RecordValue = z.record(z.string(), z.unknown());
const sessionFields = {
  run_id: Id, actor: z.string().min(1), account: z.string().min(1),
  kind: z.enum(["practice", "strategy"]), config: RecordValue, generation: z.number().int().nonnegative(),
  entries_armed: z.boolean(), state: z.string().min(1), uncertain: z.boolean(), protection: z.string(),
};
const paperSession = z.strictObject({ ...sessionFields, environment: z.literal("paper"), native_ready: z.literal(false),
  autonomy: z.never().optional(), autonomy_v2: z.never().optional(),
  books: z.object({ positions: z.array(RecordValue), orders: z.array(RecordValue), trades: z.array(RecordValue), pnl: RecordValue }).nullable(),
}).refine(row => row.account === `paper:run:${row.run_id}`, "Practice identity mismatch");
const legacyLiveSession = z.strictObject({ ...sessionFields, environment: z.literal("live"), native_ready: z.literal(false),
  autonomy: z.never().optional(), autonomy_v2: z.never().optional(), books: z.null(),
});
const nativeSession = z.strictObject({ ...sessionFields, environment: z.literal("live"), kind: z.literal("strategy"),
  config: nativeConfigSchema, native_ready: z.boolean(), books: z.null(), autonomy: nativeProjectionSchema,
  autonomy_v2: z.never().optional(),
}).superRefine((row, ctx) => {
  const native = row.autonomy;
  const binding = native.binding;
  if (row.run_id !== binding.run_id || row.account !== binding.account || row.actor !== native.operator
    || row.environment !== binding.environment || row.state !== native.state
    || row.native_ready !== native.native_ready || row.protection !== native.protection
    || row.config.run_id !== binding.run_id || row.config.broker !== binding.broker
    || row.config.account_id !== binding.account_id || row.config.strategy_revision !== binding.strategy_revision
    || row.config.config_revision !== binding.config_revision || row.config.policy_revision !== binding.policy_revision
    || row.config.provider_revision !== binding.provider_revision) {
    ctx.addIssue({ code: "custom", message: "Native outer/projection identity mismatch" });
  }
});
const nativeV2Session = z.strictObject({
  ...sessionFields, environment: z.literal("live"), kind: z.literal("strategy"), books: z.null(),
  native_ready: z.literal(false), entries_armed: z.boolean(),
  autonomy: z.never().optional(), autonomy_v2: nativeV2ViewSchema,
}).superRefine((row, ctx) => {
  const view = row.autonomy_v2;
  if (row.run_id !== view.scope.run_id || row.account !== `${view.scope.broker}:${view.scope.account_id}`
    || row.actor !== view.scope.operator || row.state !== view.entry_state || row.protection !== view.duty_state
    || canonicalPolicy(row.config) !== canonicalPolicy(view.config)) {
    ctx.addIssue({ code: "custom", message: "Native v2 outer/projection identity mismatch" });
  }
});
export const executionSessionSchema = z.union([paperSession, legacyLiveSession, nativeSession, nativeV2Session]);
export type ExecutionSessionRecord = z.infer<typeof executionSessionSchema>;
export type SessionOperation = "start" | "stop" | "rearm" | "close";
export class ExecutionSessionError extends Error {
  constructor(readonly outcome: "retired" | "refused" | "unknown" | "unavailable", message: string) { super(`${outcome}: ${message}`); }
}
function current(fence: AuthSessionFence) {
  if (!isAuthSessionFenceCurrent(fence)) throw new ExecutionSessionError("retired", "Operator session changed; the original run remains backend-owned.");
}
async function request(path: string, method: "GET" | "POST", fence: AuthSessionFence, body?: unknown): Promise<unknown> {
  current(fence);
  if (isDemoAuthSession() || useAuthStore.getState().status !== "logged-in" || !useAuthStore.getState().token) {
    throw new ExecutionSessionError("refused", "An installed operator session is required.");
  }
  const headers = buildHeaders(body !== undefined);
  delete headers["X-API-Key"];
  // No mode/account header: the signed operator authenticates the caller; the
  // immutable run target specifies execution. Never alter Terminal selection.
  let response: Response;
  let raw: unknown;
  try {
    response = await fetch(`${getBase()}/api/v1/execution-sessions${path}`, {
      method, headers, cache: "no-store", ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    raw = await response.json();
  } catch {
    current(fence);
    throw new ExecutionSessionError(method === "POST" ? "unknown" : "unavailable", "Exact run readback required. No automatic resend.");
  }
  current(fence);
  const result = z.object({ status: z.string(), data: z.unknown().optional(), code: z.string().optional() }).safeParse(raw);
  if (!result.success || !response.ok || result.data.status !== "success") {
    throw new ExecutionSessionError(method === "POST" && response.status >= 500 ? "unknown" : "unavailable",
      result.success ? result.data.code ?? "Core refused the operation" : "Malformed core response");
  }
  return result.data.data;
}
function decode(raw: unknown, id?: string): ExecutionSessionRecord {
  const result = executionSessionSchema.safeParse(raw);
  if (!result.success || (id !== undefined && result.data.run_id !== id)) {
    throw new ExecutionSessionError("unknown", "Execution identity/readback mismatch; never resend.");
  }
  return result.data;
}
export async function listExecutionSessions(fence = captureAuthSessionFence()): Promise<ExecutionSessionRecord[]> {
  const raw = await request("", "GET", fence);
  if (!Array.isArray(raw)) throw new ExecutionSessionError("unavailable", "Incomplete session census");
  const rows = raw.map(value => decode(value));
  if (new Set(rows.map(row => row.run_id)).size !== rows.length) throw new ExecutionSessionError("unavailable", "Duplicate session identities");
  return rows;
}
export async function readExecutionSession(id: string, fence = captureAuthSessionFence()): Promise<ExecutionSessionRecord> {
  Id.parse(id);
  return decode(await request(`/${encodeURIComponent(id)}`, "GET", fence), id);
}
const sent = new Set<string>();
async function mutate(id: string, path: string, body: unknown, fence: AuthSessionFence, target?: ExecutionSessionRecord) {
  Id.parse(id); current(fence);
  const key = JSON.stringify([fence, id, path, body]);
  if (sent.has(key)) throw new ExecutionSessionError("refused", `Command already sent for ${id}. Read exact status; do not replay.`);
  sent.add(key);
  let acknowledgement: ExecutionSessionRecord | undefined;
  let acknowledgementError: unknown;
  try { acknowledgement = decode(await request(path, "POST", fence, body), id); }
  catch (error) {
    if (error instanceof ExecutionSessionError && error.outcome === "retired") throw error;
    acknowledgementError = error;
  }
  const durable = await readExecutionSession(id, fence);
  if (acknowledgementError || !acknowledgement) throw new ExecutionSessionError("unknown", "Command outcome needs reconciliation; exact run read, no automatic resend.");
  if (acknowledgement.actor !== durable.actor || acknowledgement.account !== durable.account
      || acknowledgement.environment !== durable.environment || acknowledgement.generation !== durable.generation
      || acknowledgement.kind !== durable.kind || JSON.stringify(acknowledgement.config) !== JSON.stringify(durable.config)
      || (target && (durable.actor !== target.actor || durable.account !== target.account || durable.environment !== target.environment
        || durable.generation !== target.generation + 1 || durable.kind !== target.kind || JSON.stringify(durable.config) !== JSON.stringify(target.config)))) {
    throw new ExecutionSessionError("unknown", "Exact target/generation changed during readback. No automatic resend.");
  }
  if (target?.environment === "live") {
    // Native Stop is retirement only. Neither an agreeing armed ACK/GET nor a
    // vanished projection establishes that retained native authority retired.
    for (const observed of [acknowledgement, durable]) {
      if (!target.autonomy || !observed.autonomy || observed.autonomy.revision !== target.autonomy.revision
        || observed.autonomy.grant?.grant_id !== target.autonomy.grant?.grant_id
        || observed.autonomy.authorised || observed.autonomy.native_ready || observed.entries_armed
        || observed.autonomy.qualification !== null || observed.autonomy.grant?.revoked !== true
        || observed.state !== "entries_stopped") {
        throw new ExecutionSessionError("unknown", "Native entry retirement not confirmed. Read exact status; never resend.");
      }
    }
  }
  return durable;
}
export async function createPaperSession(id: string, config: Record<string, unknown>, fence = captureAuthSessionFence()) {
  const kind = typeof config.strategy === "string" ? "strategy" : "practice";
  const result = await mutate(id, "", { run_id: id, kind, config }, fence);
  if (result.environment !== "paper" || result.kind !== kind || Object.entries(config).some(([key, value]) => JSON.stringify(result.config[key]) !== JSON.stringify(value))) {
    throw new ExecutionSessionError("unknown", "Created run kind/configuration identity mismatch. Read exact status.");
  }
  return result;
}
// Retirement withdraws a retained grant; effective entry permission is not a prerequisite.
// Callers use decoded observations. Scope, generation and authentication are still
// checked by the canonical Stop request and its independent ACK/exact GET validation.
export function hasRetainedNativeGrant(target: ExecutionSessionRecord): boolean {
  return target.environment === "live" && target.autonomy?.grant?.revoked === false;
}
export async function controlExecutionSession(target: ExecutionSessionRecord, operation: SessionOperation, fence = captureAuthSessionFence()) {
  executionSessionSchema.parse(target);
  if (target.environment === "live" && (operation !== "stop" || !hasRetainedNativeGrant(target))) {
    throw new ExecutionSessionError("refused", "Native inspection only; Stop entries requires an observed non-revoked retained grant.");
  }
  return mutate(target.run_id, `/${encodeURIComponent(target.run_id)}/${operation}`,
    { account: target.account, environment: target.environment, expected_generation: target.generation }, fence, target);
}

/** Completed local validation only; a server response never creates this type. */
export class NativeV2PreflightError extends ExecutionSessionError {
  constructor(message: string) { super("refused", message); }
}

let nativeSelectionGeneration = 0;
let observingNativeSelection = false;
const nativeScopeListeners = new Set<() => void>();
function selectedNativeKey(): string {
  const store = useBrokerStore.getState();
  const account = store.getActiveAccount();
  return JSON.stringify([store.activeAccountId, account ? brokerAccountKey(account) : null]);
}
export function nativeStudioScopeKey(): string {
  if (!observingNativeSelection) {
    observingNativeSelection = true;
    let previous = selectedNativeKey();
    useBrokerStore.subscribe(() => {
      const next = selectedNativeKey();
      if (next !== previous) {
        previous = next;
        nativeSelectionGeneration++;
        nativeScopeListeners.forEach(notify => notify());
      }
    });
  }
  return `${runPolicyAuthorityKey()}:${nativeSelectionGeneration}`;
}
export function subscribeNativeStudioScope(notify: () => void): () => void {
  nativeStudioScopeKey();
  nativeScopeListeners.add(notify);
  const unsubscribe = subscribeRunPolicyAuthority(notify);
  return () => { nativeScopeListeners.delete(notify); unsubscribe(); };
}

export interface NativeV2Observation {
  readonly session: ExecutionSessionRecord;
  readonly view: NativeV2View;
  readonly preview?: NativeV2Preview;
  readonly transfer?: TransferReceiptV2;
}
const nativeCommandsSent = new Set<string>();
function viewIdentity(view: NativeV2View): string {
  // Local time/account checks may age freshness between two genuine reads.
  const { observation_freshness: _freshness, ...identity } = view;
  return canonicalPolicy(identity);
}

/** Account-selected inspection lifetime. Disposal aborts reads, never stops a run. */
export function createNativeV2Client() {
  const scopeKey = nativeStudioScopeKey();
  const fence = captureAuthSessionFence();
  const selected = useBrokerStore.getState().getActiveAccount();
  const account = selected ? { broker: selected.broker, account_id: selected.account_id, source: selected.source } : null;
  const abort = new AbortController();
  let disposed = false;
  let custody: { preview: NativeV2Preview; receipt?: TransferReceiptV2; acceptedIdentity?: string } | null = null;
  const inFlight = new Set<string>();
  const isCurrent = () => !disposed && scopeKey === nativeStudioScopeKey() && isAuthSessionFenceCurrent(fence);
  const unsubscribe = subscribeNativeStudioScope(() => { if (!isCurrent()) abort.abort(); });
  const assertCurrent = () => {
    if (!isCurrent()) throw new ExecutionSessionError("retired", "Account or operator changed; previous results detached.");
    if (!onlineManager.isOnline()) throw new ExecutionSessionError("unavailable", "Offline. Read exact status after reconnecting.");
    if (isDemoAuthSession() || !useAuthStore.getState().token || useAuthStore.getState().status !== "logged-in") {
      throw new NativeV2PreflightError("An installed operator session is required.");
    }
    if (!account || account.source !== "native") throw new NativeV2PreflightError("Select an exact native account.");
  };
  const requireAccount = (view: NativeV2View) => {
    if (view.scope.broker !== account?.broker || view.scope.account_id !== account?.account_id) {
      throw new ExecutionSessionError("unknown", "Native response belongs to a different account; no authority inferred.");
    }
    return view;
  };
  const decodeView = (raw: unknown, id: string): NativeV2View => {
    const result = nativeV2ViewSchema.safeParse(raw);
    if (!result.success || result.data.scope.run_id !== id) {
      throw new ExecutionSessionError("unknown", "Invalid nominal native response or exact run identity.");
    }
    return requireAccount(result.data);
  };
  async function requestV2(path: string, body?: unknown): Promise<unknown> {
    assertCurrent();
    const headers = buildHeaders(body !== undefined); delete headers["X-API-Key"];
    let response: Response;
    let raw: unknown;
    try {
      response = await fetch(`${getBase()}/api/v1/execution-sessions${path}`, {
        method: body === undefined ? "GET" : "POST", headers, cache: "no-store", redirect: "error",
        signal: abort.signal, ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      raw = await response.json();
    } catch {
      assertCurrent();
      throw new ExecutionSessionError(body === undefined ? "unavailable" : "unknown",
        "Native outcome unavailable. Read exact status; no automatic resend.");
    }
    assertCurrent();
    const envelope = z.object({ status: z.string(), data: z.unknown().optional(), code: z.string().optional() }).safeParse(raw);
    if (!response.ok || !envelope.success || envelope.data.status !== "success") {
      const refused = response.status >= 400 && response.status < 500;
      const code = envelope.success && /^[a-z0-9_]{1,100}$/.test(envelope.data.code ?? "")
        ? envelope.data.code : "native_response_unavailable";
      throw new ExecutionSessionError(refused ? "refused" : body === undefined ? "unavailable" : "unknown",
        `Core ${response.status}: ${code}. Read exact status; do not resend.`);
    }
    return envelope.data.data;
  }
  async function read(id: string): Promise<NativeV2Observation> {
    Id.parse(id); assertCurrent();
    const view = decodeView(await requestV2(`/${encodeURIComponent(id)}/autonomy-v2`), id);
    const session = decode(await requestV2(`/${encodeURIComponent(id)}`), id);
    if (!session.autonomy_v2 || viewIdentity(session.autonomy_v2) !== viewIdentity(view)) {
      throw new ExecutionSessionError("unknown", "Native views disagree; generation or evidence changed. Read again.");
    }
    return { view, session };
  }
  async function readAfterWrite(id: string): Promise<NativeV2Observation> {
    try { return await read(id); }
    catch (error) {
      if (error instanceof ExecutionSessionError && error.outcome === "retired") throw error;
      throw new ExecutionSessionError("unknown", "Write acknowledgement could not be reconciled. Read exact status; never resend.");
    }
  }
  function claim(id: string, operation: string, body: unknown) {
    assertCurrent();
    const key = canonicalPolicy([fence, account, id, operation, body]);
    if (nativeCommandsSent.has(key)) throw new NativeV2PreflightError("Command already sent. Read exact status; never replay.");
    nativeCommandsSent.add(key);
  }
  async function mutateView(id: string, path: string, body: unknown, expectedConfig: NativeV2View["config"],
    expected?: NativeV2View, matches: (view: NativeV2View) => boolean = () => true) {
    claim(id, path, [body, expected?.scope, expected?.report?.report_ref]);
    let acknowledgement: NativeV2View | undefined;
    let failure: unknown;
    try { acknowledgement = decodeView(await requestV2(path, body), id); }
    catch (error) {
      if (error instanceof ExecutionSessionError && ["retired", "refused"].includes(error.outcome)) throw error;
      failure = error;
    }
    const durable = await readAfterWrite(id);
    if (failure || !acknowledgement || !matches(acknowledgement) || !matches(durable.view)
      || viewIdentity(acknowledgement) !== viewIdentity(durable.view)
      || canonicalPolicy(durable.view.config) !== canonicalPolicy(expectedConfig)
      || (expected && canonicalPolicy(expected.scope) !== canonicalPolicy(durable.view.scope))) {
      throw new ExecutionSessionError("unknown", failure instanceof ExecutionSessionError ? failure.message : "Native acknowledgement/readback mismatch. Never resend automatically.");
    }
    return durable;
  }
  const equal = (left: unknown, right: unknown) => canonicalPolicy(left) === canonicalPolicy(right);
  function selectionFor(target: NativeV2View, raw: unknown): { view: NativeV2View; selection: GrantRequestV2 } {
    assertCurrent();
    const view = requireAccount(nativeV2ViewSchema.parse(target));
    const parsed = GrantRequestV2Schema.safeParse(raw);
    if (!parsed.success || parsed.data.run_id !== view.scope.run_id
      || parsed.data.expected_binding_revision !== view.scope.binding_revision
      || !equal(parsed.data.policy_ref, view.config.risk.policy_ref)
      || !equal(parsed.data.report_ref, view.report?.report_ref)
      || parsed.data.expires_at_ms <= Date.now()
      || parsed.data.expires_at_ms - Date.now() > parsed.data.limits.max_duration_ms) {
      throw new NativeV2PreflightError("Exact finite selection and current report required; no permission defaults.");
    }
    return { view, selection: parsed.data };
  }
  function requireEntryEvidence(view: NativeV2View) {
    assertCurrent();
    const selectedAccount = useBrokerStore.getState().getActiveAccount();
    if (selectedAccount?.read_only || selectedAccount?.status !== "connected" || view.global_kill
      || view.loss_threshold_latched || view.report?.status !== "eligible"
      || view.report.expires_at_ms <= Date.now()) {
      throw new NativeV2PreflightError("Current writable account and eligible evidence required; read exact status.");
    }
  }
  async function once<T>(id: string, action: () => Promise<T>): Promise<T> {
    if (inFlight.has(id)) throw new NativeV2PreflightError("Native lifecycle action pending. Do not duplicate it.");
    inFlight.add(id);
    try { return await action(); } finally { inFlight.delete(id); }
  }
  async function custodyMutation<T>(view: NativeV2View, operation: string, body: unknown,
    schema: z.ZodType<T>, matches: (value: T, observation: NativeV2Observation) => boolean) {
    const path = `/${encodeURIComponent(view.scope.run_id)}/autonomy-v2/${operation}`;
    claim(view.scope.run_id, path, body);
    let ack: T | undefined;
    let failed = false;
    try { ack = schema.parse(await requestV2(path, body)); }
    catch (error) {
      if (error instanceof ExecutionSessionError && ["retired", "refused"].includes(error.outcome)) throw error;
      failed = true;
    }
    const observation = await readAfterWrite(view.scope.run_id);
    if (failed || ack === undefined || !equal(view.scope, observation.view.scope)
      || !equal(view.config, observation.view.config) || !equal(view.grant, observation.view.grant)
      || view.entry_state !== observation.view.entry_state || view.producer_state !== observation.view.producer_state
      || !matches(ack, observation)) {
      throw new ExecutionSessionError("unknown", "Custody acknowledgement/readback mismatch. No grant inferred; never resend.");
    }
    return { ack, observation };
  }
  return {
    isCurrent, read,
    dispose: () => { disposed = true; unsubscribe(); abort.abort(); },
    async configure(raw: unknown) {
      assertCurrent();
      const parsed = nativeV2ConfigurationSchema.safeParse(raw);
      if (!parsed.success) throw new NativeV2PreflightError("Complete the exact cash/options configuration; no defaults supplied.");
      const request = parsed.data;
      if (request.config.broker !== account?.broker || request.config.account_id !== account?.account_id
        || request.config.environment !== "production") throw new NativeV2PreflightError("Configuration account/environment mismatch.");
      const currentAccount = useBrokerStore.getState().getActiveAccount();
      if (currentAccount?.read_only || currentAccount?.status !== "connected") {
        throw new NativeV2PreflightError("Configuration is read-only until this native account is connected and writable.");
      }
      Id.parse(request.config.run_id);
      return mutateView(request.config.run_id, "/native-v2", request, request.config);
    },
    async inspect(target: NativeV2View, raw: InspectRequestV2) {
      assertCurrent();
      const view = requireAccount(nativeV2ViewSchema.parse(target));
      const parsed = InspectRequestV2Schema.safeParse(raw);
      if (!parsed.success || parsed.data.run_id !== view.scope.run_id
        || parsed.data.expected_binding_revision !== view.scope.binding_revision
        || parsed.data.read_plan.deadline_ms <= Date.now() || parsed.data.read_plan.deadline_ms - Date.now() > 60_000) {
        throw new NativeV2PreflightError("Inspection needs the exact binding and an explicit finite canonical read plan.");
      }
      return mutateView(view.scope.run_id, `/${encodeURIComponent(view.scope.run_id)}/autonomy-v2/inspect`,
        parsed.data, view.config, view);
    },
    async qualify(target: NativeV2View) {
      assertCurrent();
      const view = requireAccount(nativeV2ViewSchema.parse(target));
      return mutateView(view.scope.run_id, `/${encodeURIComponent(view.scope.run_id)}/autonomy-v2/qualify`, {}, view.config, view);
    },
    async preview(target: NativeV2View, raw: unknown): Promise<NativeV2Observation> {
      const { view, selection } = selectionFor(target, raw);
      custody = null;
      return once(view.scope.run_id, async () => {
        const { ack, observation } = await custodyMutation(view, "transfer-preview", selection,
          nativeV2PreviewSchema, (preview, next) => equal(preview.selection, selection)
            && equal(preview.duty.scope, view.scope) && equal(preview.duty, next.view.duty));
        custody = { preview: nativeV2PreviewSchema.parse(ack) };
        return { ...observation, preview: ack };
      });
    },
    async accept(target: NativeV2View, raw: unknown): Promise<NativeV2Observation> {
      assertCurrent();
      const view = requireAccount(nativeV2ViewSchema.parse(target));
      const preview = nativeV2PreviewSchema.parse(raw);
      if (!custody || !equal(custody.preview, preview) || custody.receipt
        || !equal(view.duty, preview.duty) || !equal(view.scope, preview.duty.scope)) {
        throw new NativeV2PreflightError("Read and preview this exact finite custody before accepting it.");
      }
      selectionFor(view, preview.selection);
      const body = TransferAcceptRequestV2Schema.parse({ schema_version: "2", preview_ref: preview.preview_ref,
        expected_duty_revision: preview.duty.duty_ref.revision });
      return once(view.scope.run_id, async () => {
        const { ack, observation } = await custodyMutation(view, "transfer-accept", body,
          TransferReceiptV2Schema, (receipt, next) => equal(receipt.scope, view.scope)
            && equal(next.view.transfer_receipts.filter(value => equal(value.transfer_ref, receipt.transfer_ref)), [receipt])
            && receipt.accepted_at_ms < preview.selection.expires_at_ms
            && equal(receipt.duty_ref, preview.duty.duty_ref)
            && receipt.obligation_revision === preview.duty.obligation_revision
            && equal(receipt.obligations, preview.duty.obligations)
            && equal(receipt.model_obligations, preview.duty.model_obligations)
            && receipt.unknown_possible_writes === preview.duty.unknown_possible_writes
            && receipt.reconciliation_required === (preview.duty.obligations.length > 0 || preview.duty.model_obligations.length > 0
              || preview.duty.cumulative_entry_fill !== preview.duty.cumulative_exit_fill)
            && equal(next.view.duty?.receiving_acceptance_ref, receipt.transfer_ref)
            && equal(next.view.duty?.duty_ref, receipt.duty_ref)
            && next.view.duty?.obligation_revision === receipt.obligation_revision
            && equal(next.view.duty?.obligations, receipt.obligations)
            && equal(next.view.duty?.model_obligations, receipt.model_obligations)
            && next.view.duty?.custody === "operator" && next.view.duty.coverage === "operator_accepted");
        custody = { preview: nativeV2PreviewSchema.parse(preview), receipt: TransferReceiptV2Schema.parse(ack),
          acceptedIdentity: viewIdentity(observation.view) };
        return { ...observation, preview, transfer: ack };
      });
    },
    async grant(target: NativeV2View, raw: unknown): Promise<NativeV2Observation> {
      const { view, selection } = selectionFor(target, raw);
      requireEntryEvidence(view);
      if (!custody?.receipt || custody.acceptedIdentity !== viewIdentity(view)
        || !equal(custody.preview.selection, selection)
        || !equal(view.transfer_receipts.filter(value => equal(value.transfer_ref, custody!.receipt!.transfer_ref)), [custody.receipt])
        || !equal(view.duty?.receiving_acceptance_ref, custody.receipt.transfer_ref)
        || view.duty?.obligation_revision !== custody.receipt.obligation_revision) {
        throw new NativeV2PreflightError("Explicit receiving acceptance for this exact finite selection required.");
      }
      return once(view.scope.run_id, () => mutateView(view.scope.run_id,
        `/${encodeURIComponent(view.scope.run_id)}/autonomy-v2/grant`, selection, view.config, view,
        next => next.entry_state === "granted" && next.producer_state === "not_started"
          && next.requested_authority === "bounded_entry" && next.effective_authority === "none"
          && next.grant?.state === "active" && equal(next.grant.limits, selection.limits)
          && equal(next.grant.report_ref, selection.report_ref) && equal(next.grant.policy_ref, selection.policy_ref)
          && next.grant.expires_at_ms === selection.expires_at_ms
          && equal(next.report, view.report) && equal(next.duty, view.duty)
          && equal(next.transfer_receipts, view.transfer_receipts)));
    },
    async start(target: ExecutionSessionRecord): Promise<NativeV2Observation> {
      assertCurrent();
      const original = executionSessionSchema.parse(target);
      if (!original.autonomy_v2) throw new NativeV2PreflightError("Exact native v2 observation required for Start.");
      const view = requireAccount(original.autonomy_v2);
      requireEntryEvidence(view);
      if (view.entry_state !== "granted" || view.producer_state !== "not_started"
        || view.grant?.state !== "active" || view.grant.expires_at_ms <= Date.now()) {
        throw new NativeV2PreflightError("A current finite grant and separate explicit Start are required.");
      }
      const body = StartRequestV2Schema.parse({ schema_version: "2", run_id: view.scope.run_id,
        expected_binding_revision: view.scope.binding_revision, grant_ref: view.grant.grant_ref });
      return once(view.scope.run_id, async () => {
        const next = await mutateView(view.scope.run_id, `/${encodeURIComponent(view.scope.run_id)}/autonomy-v2/start`,
          body, view.config, view, value => value.entry_state === "started" && value.producer_state === "running"
            && equal(value.grant, view.grant));
        if (next.session.generation !== original.generation + 1 || !next.session.entries_armed) {
          throw new ExecutionSessionError("unknown", "Start generation/readback unconfirmed. Read exact status; never resend.");
        }
        return next;
      });
    },
    async stop(target: ExecutionSessionRecord): Promise<NativeV2Observation> {
      assertCurrent();
      const original = executionSessionSchema.parse(target);
      if (!original.autonomy_v2) throw new NativeV2PreflightError("Exact native v2 observation required for Stop.");
      const view = requireAccount(original.autonomy_v2);
      const path = `/${encodeURIComponent(original.run_id)}/stop`;
      const body = { account: original.account, environment: original.environment, expected_generation: original.generation };
      claim(original.run_id, path, body);
      let ack: ExecutionSessionRecord | undefined;
      let failure: unknown;
      try { ack = decode(await requestV2(path, body), original.run_id); }
      catch (error) {
        if (error instanceof ExecutionSessionError && ["retired", "refused"].includes(error.outcome)) throw error;
        failure = error;
      }
      const durable = await readAfterWrite(original.run_id);
      for (const row of [ack, durable.session]) {
        if (failure || !row?.autonomy_v2 || row.generation !== original.generation + 1
          || row.actor !== original.actor || row.account !== original.account || row.environment !== original.environment
          || canonicalPolicy(row.autonomy_v2.scope) !== canonicalPolicy(view.scope)
          || canonicalPolicy(row.config) !== canonicalPolicy(original.config)
          || (view.grant ? row.autonomy_v2.grant?.state !== "revoked"
            || !equal({ ...row.autonomy_v2.grant, state: view.grant.state }, view.grant)
            : row.autonomy_v2.grant !== null)
          || row.entries_armed || row.autonomy_v2.entry_state !== "retired"
          || row.autonomy_v2.effective_authority !== "none"
          || !["not_started", "stopping", "stopped", "failed"].includes(row.autonomy_v2.producer_state)) {
          throw new ExecutionSessionError("unknown", "Entry retirement unconfirmed. Stop is not settlement; never resend.");
        }
      }
      if (ack?.autonomy_v2) {
        const before = ack.autonomy_v2;
        // Stop withdraws permission synchronously; a retained worker can finish
        // between ACK and readback. Only that forward drain transition may differ.
        const drained = before.producer_state === "stopping"
          && ["stopped", "failed"].includes(durable.view.producer_state);
        const comparable = drained ? { ...before, producer_state: durable.view.producer_state } : before;
        if (viewIdentity(comparable) !== viewIdentity(durable.view)) {
          throw new ExecutionSessionError("unknown", "Stop acknowledgement/readback disagree. Custody remains unresolved.");
        }
      }
      return durable;
    },
  };
}

