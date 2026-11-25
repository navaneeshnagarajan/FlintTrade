import { z } from "zod";
import { captureAuthSessionFence, isAuthSessionFenceCurrent, useAuthStore, type AuthSessionFence } from "@/stores/authStore";
import { buildHeaders, getBase, isDemoAuthSession } from "./ftApi.helpers";

import { nativeConfigSchema, nativeProjectionSchema } from "./executionSessionNative";

const Id = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/);
const RecordValue = z.record(z.string(), z.unknown());
const sessionFields = {
  run_id: Id, actor: z.string().min(1), account: z.string().min(1),
  kind: z.enum(["practice", "strategy"]), config: RecordValue, generation: z.number().int().nonnegative(),
  entries_armed: z.boolean(), state: z.string().min(1), uncertain: z.boolean(), protection: z.string(),
};
const paperSession = z.strictObject({ ...sessionFields, environment: z.literal("paper"), native_ready: z.literal(false),
  autonomy: z.never().optional(),
  books: z.object({ positions: z.array(RecordValue), orders: z.array(RecordValue), trades: z.array(RecordValue), pnl: RecordValue }).nullable(),
}).refine(row => row.account === `paper:run:${row.run_id}`, "Practice identity mismatch");
const legacyLiveSession = z.strictObject({ ...sessionFields, environment: z.literal("live"), native_ready: z.literal(false),
  autonomy: z.never().optional(), books: z.null(),
});
const nativeSession = z.strictObject({ ...sessionFields, environment: z.literal("live"), kind: z.literal("strategy"),
  config: nativeConfigSchema, native_ready: z.boolean(), books: z.null(), autonomy: nativeProjectionSchema,
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
export const executionSessionSchema = z.union([paperSession, legacyLiveSession, nativeSession]);
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
