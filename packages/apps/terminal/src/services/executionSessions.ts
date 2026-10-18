import { z } from "zod";
import { captureAuthSessionFence, isAuthSessionFenceCurrent, useAuthStore, type AuthSessionFence } from "@/stores/authStore";
import { buildHeaders, getBase, isDemoAuthSession } from "./ftApi.helpers";

const Id = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/);
const RecordValue = z.record(z.string(), z.unknown());
export const executionSessionSchema = z.looseObject({
  run_id: Id, actor: z.string().min(1), account: z.string().min(1), environment: z.enum(["paper", "live"]),
  kind: z.enum(["practice", "strategy"]), config: RecordValue, generation: z.number().int().nonnegative(),
  entries_armed: z.boolean(), state: z.string().min(1), uncertain: z.boolean(), protection: z.string(), native_ready: z.literal(false),
  books: z.object({ positions: z.array(RecordValue), orders: z.array(RecordValue), trades: z.array(RecordValue), pnl: RecordValue }).nullable(),
}).refine(row => row.environment !== "paper" || row.account === `paper:run:${row.run_id}`, "Practice identity mismatch");
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
  return durable;
}
export async function createPaperSession(id: string, config: Record<string, unknown>, fence = captureAuthSessionFence()) {
  const kind = typeof config.strategy === "string" ? "strategy" : "practice";
  const result = await mutate(id, "", { run_id: id, kind, config }, fence);
  if (result.kind !== kind || Object.entries(config).some(([key, value]) => JSON.stringify(result.config[key]) !== JSON.stringify(value))) {
    throw new ExecutionSessionError("unknown", "Created run kind/configuration identity mismatch. Read exact status.");
  }
  return result;
}
export function controlExecutionSession(target: ExecutionSessionRecord, operation: SessionOperation, fence = captureAuthSessionFence()) {
  executionSessionSchema.parse(target);
  return mutate(target.run_id, `/${encodeURIComponent(target.run_id)}/${operation}`,
    { account: target.account, environment: target.environment, expected_generation: target.generation }, fence, target);
}
