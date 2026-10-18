import { z } from "zod";
import { buildHeaders, getBase, isDemoAuthSession, FtApiError } from "./ftApi.helpers";
import { useAuthStore } from "@/stores/authStore";
import { evaluationScopeKey } from "./backtestReceipt";
import type { BacktestResult } from "./ftApi.backtest";
import { noteObservedFailure } from "@/stores/operatorSignalStore";
import type { OperatorIncidentScope } from "@/lib/operatorIncidentScope";

export const EvidenceId = z.string().regex(/^[a-zA-Z0-9_.:-]{1,128}$/, "Enter an exact evidence identity (no whitespace).");
const TrialId = z.string().regex(/^[a-f0-9]{32}$/, "Enter the exact lowercase immutable trial/experiment ID.");
const RecordBody = z.record(z.string(), z.unknown());
const Trial = z.looseObject({ id: TrialId, experiment_id: TrialId,
  status: z.enum(["completed", "partial", "failed", "unknown", "cancelled"]), evidence: RecordBody });
const Experiment = z.looseObject({ id: TrialId, manifest: z.looseObject({ schema_version: z.literal(1) }), trials: z.array(TrialId) });
const Digest = z.string().regex(/^[a-f0-9]{64}$/);
const Selector = z.string().min(1).refine(value => value === value.trim(), "Selectors must be exact; no whitespace normalisation.");
export const BacktestRunSelector = z.string().regex(/^[A-Za-z0-9_.:-]{1,128}$/, "Enter the exact registered run selector (no whitespace or normalisation).");
export const HistoryBacktestRequest = z.strictObject({ data_manifest_id: Digest, symbol: Selector, exchange: Selector,
  run_id: BacktestRunSelector.optional(),
  interval: z.string().regex(/^[1-9][0-9]*[smhd]$/), strategy: Selector,
  start_date: z.string(), end_date: z.string(), initial_capital: z.number().positive(), position_size_pct: z.number().positive().max(100) });
const BacktestResultSchema = z.looseObject({
  trades: z.array(z.looseObject({ entry_timestamp: z.string(), exit_timestamp: z.string(), symbol: z.string(), side: z.string(),
    quantity: z.number(), entry_price: z.number(), exit_price: z.number(), pnl: z.number(), net_pnl: z.number().optional(), commission: z.number(), bars_held: z.number() })),
  equity_curve: z.array(z.looseObject({ timestamp: z.string(), equity: z.number() })),
  metrics: z.looseObject({ total_return: z.number(), cagr: z.number().optional(), sharpe_ratio: z.number(), sortino_ratio: z.number(),
    max_drawdown: z.number(), win_rate: z.number(), profit_factor: z.number(), total_trades: z.number().int().nonnegative(), expectancy: z.number() }),
  final_equity: z.number(), total_bars: z.number().int().nonnegative(),
});
export async function throwBacktestHttpError(response: Response, scope: OperatorIncidentScope): Promise<never> {
  let raw: unknown;
  try { raw = await response.json(); } catch { /* Keep the original HTTP outcome. */ }
  const parsed = z.looseObject({ message: z.string().optional(), error: z.string().optional(), data: z.unknown().optional() }).safeParse(raw);
  const message = parsed.success ? parsed.data.message ?? parsed.data.error ?? `FT API backtest/run: HTTP ${response.status}` : `FT API backtest/run: HTTP ${response.status}`;
  noteObservedFailure({ message, httpStatus: response.status, provenance: "general", scope });
  throw new FtApiError(message, response.status, parsed.success ? parsed.data.data : undefined);
}
export function assertBacktestResult(value: unknown): asserts value is BacktestResult {
  if (!BacktestResultSchema.safeParse(value).success) throw new EvaluationActionError("unknown", "Malformed backtest result; retain immutable references for readback. No automatic resend.");
}
export const TrainingRequest = z.strictObject({
  request_id: EvidenceId,
  payload: z.strictObject({ model_name: z.string().min(1), training_type: z.string().min(1), format_type: z.string().min(1),
    hf_dataset: z.string().regex(/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/), is_decision: z.boolean().optional() }),
  lineage: z.strictObject({ dataset: Digest, run_id: EvidenceId }),
});
const TrainingJob = z.looseObject({ id: EvidenceId, request_digest: Digest, lineage: TrainingRequest.shape.lineage,
  state: z.enum(["accepted", "running", "completed", "failed", "cancelled", "unknown"]), remote_job_id: z.string().nullable(),
  cancellation: z.enum(["not-requested", "requested", "unknown", "confirmed"]), deletion: z.literal("not-requested"),
  weight_unlearning: z.literal("unavailable"), publication: z.literal("disabled"), events: z.array(RecordBody) });
export const AdoptionRequest = z.strictObject({ request_id: EvidenceId, run_id: EvidenceId, role: EvidenceId, candidate: EvidenceId,
  expected_generation: z.number().int().nonnegative(), kind: z.enum(["adopt", "rollback"]) });
const AdoptionBinding = z.looseObject({ run_id: EvidenceId, role: EvidenceId, account: z.string().min(1), environment: z.string().min(1),
  generation: z.number().int().nonnegative(), config_generation: z.number().int().nonnegative(), risk_fingerprint: z.string().min(1),
  frontier: z.string().min(1), protection_id: z.string().min(1), protection_verified: z.boolean(), binding: EvidenceId, entries_armed: z.boolean() });
const Adoption = z.looseObject({ id: EvidenceId, request: AdoptionRequest.omit({ request_id: true }),
  status: z.enum(["completed", "refused", "unknown"]), events: z.array(RecordBody), reason: z.string().optional(),
  phase: z.string().optional(), bound: AdoptionBinding.optional() }).refine(value => value.status !== "completed" || (
    ["verified", "reconciled_no_rearm"].includes(value.phase ?? "") && value.bound?.run_id === value.request.run_id && value.bound.role === value.request.role
    && value.bound.binding === value.request.candidate && value.bound.generation === value.request.expected_generation + 1 && value.bound.protection_verified === true), "Core binding readback is incomplete or mismatched.");
export const EVIDENCE_KINDS = { trials: "Trial", experiments: "Experiment", "training/jobs": "Training job", adoptions: "Adoption" } as const;
export type EvidenceKind = keyof typeof EVIDENCE_KINDS;
export type CoreEvidence = Record<string, unknown> & { id: string };
export class EvaluationActionError extends Error {
  constructor(readonly outcome: "refused" | "unavailable" | "unknown" | "retired", message: string) { super(`${outcome === "unknown" ? "Unknown remote outcome" : outcome}: ${message}`); }
}
function current(scope: string) {
  if (scope !== evaluationScopeKey()) throw new EvaluationActionError("retired", "Session/account changed. No response or readback may enter the new scope.");
}
async function request(path: string, method: "GET" | "POST", scope: string, body?: unknown) {
  current(scope);
  if (isDemoAuthSession() || useAuthStore.getState().status !== "logged-in" || !useAuthStore.getState().token) {
    throw new EvaluationActionError("refused", "An installed operator session is required; preview and inference access are not authority.");
  }
  // R9 model_control_auth rejects the generic API-key carrier. Keep the verified
  // operator bearer from the shared builder; client fields never confer authority.
  const headers = buildHeaders(body !== undefined);
  delete headers["X-API-Key"];
  let response: Response;
  let raw: unknown;
  try {
    response = await fetch(`${getBase()}/api/v1/backtest/${path}`, { method, headers, cache: "no-store", ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    raw = await response.json();
  } catch {
    current(scope);
    throw new EvaluationActionError(method === "POST" ? "unknown" : "unavailable", "Transport or malformed JSON; read exact evidence. No automatic resend.");
  }
  current(scope);
  const envelope = z.looseObject({ status: z.string(), data: z.unknown().optional(), message: z.string().optional(), error: z.string().optional(), code: z.string().optional() }).safeParse(raw);
  if (!envelope.success) throw new EvaluationActionError(method === "POST" ? "unknown" : "unavailable", "Malformed core response.");
  const value = envelope.data;
  if ((!response.ok && !(response.status === 422 && value.status === "failed" && value.data)) || !["success", "completed", "failed"].includes(value.status)) {
    const outcome = value.status === "unknown" ? "unknown" : value.status === "unavailable" ? "unavailable" : response.status < 500 ? "refused" : "unknown";
    throw new EvaluationActionError(outcome, [value.code, value.message ?? value.error].filter(Boolean).join(": ") || `Core returned HTTP ${response.status}. Read exact evidence before retrying.`);
  }
  return value.data;
}
function decode(kind: EvidenceKind, id: string, raw: unknown): CoreEvidence {
  const schema = kind === "trials" ? Trial : kind === "experiments" ? Experiment : kind === "training/jobs" ? TrainingJob : Adoption;
  const parsed = schema.safeParse(raw);
  if (!parsed.success) throw new EvaluationActionError("unavailable", "Malformed evidence record; not completion evidence.");
  if (parsed.data.id !== id) throw new EvaluationActionError("unavailable", "Evidence identity mismatch.");
  return parsed.data;
}
export async function readEvaluationEvidence(kind: EvidenceKind, id: string, scope = evaluationScopeKey()): Promise<CoreEvidence> {
  (kind === "trials" || kind === "experiments" ? TrialId : EvidenceId).parse(id);
  return decode(kind, id, await request(`${kind}/${encodeURIComponent(id)}`, "GET", scope));
}
// Volatile duplicate-send guard, not a permission ledger or durable job owner.
const sentCommands = new Map<string, string>();
async function mutateEvidence(kind: EvidenceKind, identity: string, path: string, body: unknown, scope: string, replayKey?: string) {
  current(scope);
  if (replayKey) {
    const key = `${scope}:${replayKey}`;
    const fingerprint = JSON.stringify(body);
    const prior = sentCommands.get(key);
    if (prior !== undefined) throw new EvaluationActionError("refused", prior === fingerprint
      ? "Request already sent. Read or reconcile the exact target; do not resubmit."
      : "Immutable request identity conflict. Read the original target.");
    sentCommands.set(key, fingerprint);
  }
  let sent: CoreEvidence | undefined;
  let acknowledgementError: unknown;
  try {
    const raw = await request(path, "POST", scope, body);
    try { sent = decode(kind, identity, raw); } catch (error) { acknowledgementError = error; }
  } catch (error) {
    // The mounted routes report unavailable before dispatch when trusted core
    // authority is absent. Allow a later explicit confirmation after setup;
    // uncertain sends and identity conflicts remain fenced against replay.
    if (error instanceof EvaluationActionError && error.outcome === "unavailable" && replayKey) sentCommands.delete(`${scope}:${replayKey}`);
    if (error instanceof EvaluationActionError && error.outcome !== "unknown") throw error;
    acknowledgementError = error;
  }
  // Exactly one read even after an uncertain send. Never turn a malformed ACK
  // into success, and never retry the mutation to discover its outcome.
  try {
    const durable = await readEvaluationEvidence(kind, identity, scope);
    if (acknowledgementError || !sent) throw acknowledgementError ?? new Error("Acknowledgment unavailable");
    return { sent, durable };
  } catch (error) {
    current(scope);
    throw new EvaluationActionError("unknown", `Command sent; exact acknowledgement/readback could not be verified. ${String(error)} No automatic resend.`);
  }
}
async function trainingMutation(path: string, identity: string, body: unknown, scope: string, lineage?: z.infer<typeof TrainingRequest>["lineage"]) {
  const { sent, durable } = await mutateEvidence("training/jobs", identity, path, body, scope, path.endsWith("/reconcile") ? undefined : `${path}:${identity}`);
  try {
    const target = lineage ?? TrainingJob.parse(sent).lineage;
    const actual = TrainingJob.parse(durable);
    if (actual.request_digest !== sent.request_digest || actual.lineage.dataset !== target.dataset || actual.lineage.run_id !== target.run_id
        || actual.remote_job_id !== sent.remote_job_id) throw new Error("Training identity mismatch.");
    return durable;
  } catch (error) {
    current(scope);
    throw new EvaluationActionError("unknown", `Training command sent but exact readback failed. ${String(error)} No automatic resend.`);
  }
}
export function startTraining(input: unknown, scope = evaluationScopeKey()) {
  const body = TrainingRequest.parse(input);
  return trainingMutation("training/jobs", body.request_id, body, scope, body.lineage);
}
export function controlTraining(identity: string, operation: "cancel" | "reconcile", scope = evaluationScopeKey()) {
  EvidenceId.parse(identity);
  return trainingMutation(`training/jobs/${encodeURIComponent(identity)}/${operation}`, identity, {}, scope);
}
async function adoptionMutation(path: string, identity: string, body: unknown, scope: string, expected?: z.infer<typeof AdoptionRequest>) {
  const result = await mutateEvidence("adoptions", identity, path, body, scope, path.endsWith("/reconcile") ? undefined : `adoptions:${identity}`);
  try {
    const sent = Adoption.parse(result.sent);
    const durable = Adoption.parse(result.durable);
    const target = expected ?? sent.request;
    for (const key of ["run_id", "role", "candidate", "expected_generation", "kind"] as const) {
      if (durable.request[key] !== target[key] || sent.request[key] !== target[key]) throw new Error("Adoption identity mismatch.");
    }
    return durable;
  } catch (error) {
    current(scope);
    throw new EvaluationActionError("unknown", `Adoption command sent but exact readback failed. ${String(error)} No automatic resend.`);
  }
}
export function adoptArtifact(input: unknown, scope = evaluationScopeKey()) {
  const body = AdoptionRequest.parse(input);
  return adoptionMutation("adoptions", body.request_id, body, scope, body);
}
export function reconcileAdoption(identity: string, scope = evaluationScopeKey()) {
  EvidenceId.parse(identity);
  return adoptionMutation(`adoptions/${encodeURIComponent(identity)}/reconcile`, identity, {}, scope);
}
export function evidenceNotice(evidence: CoreEvidence): string {
  if ("request" in evidence) {
    const record = Adoption.parse(evidence);
    const label = record.request.kind === "rollback" ? "Rollback" : "Adoption";
    return record.status === "completed" ? `${label} completed; exact core binding read back. No local promotion, re-arming or ledger rewind.`
      : `${label} ${record.status}: ${record.reason ?? "Read or reconcile exact evidence; do not replay."}`;
  }
  if ("manifest" in evidence) return "Exact immutable experiment read back. Not qualification by itself.";
  if ("state" in evidence) {
    if (evidence.cancellation === "requested") return "Cancellation requested; remote stop is not confirmed. Read or reconcile the exact job.";
    if (evidence.state === "cancelled" && evidence.cancellation === "confirmed") return "Remote stop confirmed. Deletion and trained-weight erasure are not established.";
    if (evidence.state === "accepted") return "Training accepted; not completed. No model activation follows.";
    if (evidence.state === "unknown" || evidence.cancellation === "unknown") return "Unknown remote outcome; reconcile the exact training job. Do not resubmit.";
    return `Training ${String(evidence.state)}; exact job read back. No model activation follows.`;
  }
  return `Evaluation ${String(evidence.status)}; exact trial read back. Qualification does not activate a model.`;
}
export async function scoreEvaluation(suite: string, trial: string, scope = evaluationScopeKey()) {
  EvidenceId.parse(suite); TrialId.parse(trial);
  const { sent, durable } = await mutateEvidence("trials", trial, `evaluation/suites/${encodeURIComponent(suite)}/score`, { trial_id: trial }, scope, `suite:${suite}`);
  try {
    if (durable.experiment_id !== sent.experiment_id || (durable.status === "completed" && RecordBody.parse(durable.evidence).suite !== suite)) {
      throw new Error("Evaluation identity mismatch.");
    }
    return durable;
  } catch (error) {
    current(scope);
    throw new EvaluationActionError("unknown", `Evaluation sent but exact readback failed. ${String(error)} No automatic resend.`);
  }
}
