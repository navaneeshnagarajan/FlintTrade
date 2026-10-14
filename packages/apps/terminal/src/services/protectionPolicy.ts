import { z } from "zod";
import { canonicalPolicy, createRunPolicyTransport, RunPolicyError, runScopeSchema, sameRunScope, type RunScope } from "./runPolicyTransport";
const positive = z.number().finite().positive();
const integer = z.number().int().positive().max(Number.MAX_SAFE_INTEGER);
const text = z.string().min(1);
export const protectionPolicySchema = z.strictObject({
  policy_revision: text.max(128), valid_until: positive,
  position: z.strictObject({ symbol: text, exchange: z.enum(["NSE", "BSE"]), product: z.enum(["CNC", "MIS"]), entry_order_ids: z.array(text).min(1).refine(ids => new Set(ids).size === ids.length), quantity: integer }),
  hedge_scope: z.array(z.never()).length(0), risk_policy: z.literal("unhedged-cash-reduction-only"), max_quantity: integer, max_notional: positive,
  read: z.strictObject({ selector: text, valid_until: positive, max_reads: integer, max_age_seconds: positive.max(60) }),
}).refine(value => value.max_quantity <= value.position.quantity && value.read.valid_until <= value.valid_until, "Protection bounds must not exceed position or grant expiry");
export type ProtectionPolicy = z.infer<typeof protectionPolicySchema>;
const readbackSchema = z.object({
  scope: runScopeSchema, revision: z.number().int().nonnegative(), policy: protectionPolicySchema.nullable(),
  authority_state: z.enum(["not_issued", "active", "retired", "unavailable"]),
  usage: z.object({ reads: z.number().int().nonnegative(), quantity_used: z.number().nonnegative(), notional_used: z.number().nonnegative() }).nullable(),
  duty: z.object({ state: z.enum(["not_granted", "retained", "settled", "unknown"]), remaining_quantity: z.number().nonnegative().nullable(), reconciliation_required: z.boolean(), attempts: z.array(z.object({ id: text, state: text, order_id: z.string().nullable() })) }),
  supervision: z.enum(["supervising", "unavailable"]),
}).refine(value => value.authority_state === "not_issued" ? value.revision === 0 && value.policy === null && value.usage === null && value.duty.state === "not_granted" && value.duty.remaining_quantity === null && value.duty.attempts.length === 0 && !value.duty.reconciliation_required && value.supervision === "unavailable" : value.revision > 0 && value.policy !== null && value.usage !== null && value.duty.state !== "not_granted");
export type ProtectionReadback = z.infer<typeof readbackSchema>;
const envelope = z.object({ status: z.literal("success"), data: z.unknown() });
export function createProtectionPolicyClient(scope: RunScope) {
  scope = runScopeSchema.parse(scope);
  const transport = createRunPolicyTransport(scope);
  const base = "/api/v1/protection/grants";
  const path = `${base}/${encodeURIComponent(scope.run_id)}`;
  let snapshot: ProtectionReadback | null = null;
  let needsRead = false;
  const attempted = new Set<string>();
  function decode(raw: unknown): ProtectionReadback {
    const parsed = envelope.safeParse(raw);
    const result = readbackSchema.safeParse(parsed.success ? parsed.data.data : null);
    if (!result.success || !sameRunScope(scope, result.data.scope)) throw new RunPolicyError("unknown", "Protection scope or duty readback is unavailable. No absence or flatness is inferred.");
    return result.data;
  }
  async function read() { const value = decode(await transport.request(path)); snapshot = structuredClone(value); needsRead = false; return value; }
  async function mutate(target: ProtectionReadback, policy?: ProtectionPolicy) {
    transport.assertCurrent();
    if (needsRead || !snapshot || canonicalPolicy(target) !== canonicalPolicy(snapshot) || !sameRunScope(scope, target.scope)) throw new RunPolicyError("unknown", "Read the exact current protection revision before approval.");
    target = structuredClone(target);
    if (policy) {
      policy = protectionPolicySchema.parse(policy);
      if (policy.valid_until <= Date.now() / 1000 || policy.read.valid_until <= Date.now() / 1000) throw new RunPolicyError("refused", "Explicit future protection and quote-read expiry required.");
    } else if (!target.policy) throw new RunPolicyError("refused", "No issued grant to revoke; unknown duties are not discarded.");
    const body = policy ? { run_id: scope.run_id, expected_revision: target.revision, policy: structuredClone(policy) } : { expected_revision: target.revision };
    const key = canonicalPolicy(body);
    if (attempted.has(key)) throw new RunPolicyError("refused", "Exact protection command already attempted; never replay. Read and reconcile.");
    attempted.add(key); needsRead = true;
    let ack: unknown;
    let failure: unknown;
    try { ack = await transport.request(policy ? base : `${path}/revoke`, body); } catch (reason) { transport.assertCurrent(); failure = reason; }
    const durable = decode(await transport.request(path));
    const expectedAck = policy ? z.object({ scope: runScopeSchema, revision: z.number().int(), policy: protectionPolicySchema }) : z.object({ scope: runScopeSchema, revision: z.number().int(), revoked: z.literal(true), duty_retained: z.literal(true) });
    const outer = envelope.safeParse(ack);
    const parsed = expectedAck.safeParse(outer.success ? outer.data.data : null);
    if (failure || !parsed.success || !sameRunScope(scope, parsed.data.scope) || parsed.data.revision !== target.revision + 1 || durable.revision !== parsed.data.revision
      || (policy ? canonicalPolicy(durable.policy) !== canonicalPolicy(policy) || !("policy" in parsed.data) || canonicalPolicy(parsed.data.policy) !== canonicalPolicy(policy) : durable.authority_state !== "retired" || canonicalPolicy(durable.policy) !== canonicalPolicy(target.policy))) throw new RunPolicyError("unknown", "Protection outcome unknown or changed. Exact read attempted; read and reconcile. No automatic replay.");
    snapshot = structuredClone(durable); needsRead = false;
    return durable;
  }
  return { read, approve: (target: ProtectionReadback, policy: ProtectionPolicy) => mutate(target, policy), revoke: (target: ProtectionReadback) => mutate(target), dispose: () => { snapshot = null; attempted.clear(); transport.dispose(); } };
}
