import { z } from "zod";
import { canonicalPolicy, createRunPolicyTransport, RunPolicyError, runScopeSchema, sameRunScope, type RunScope } from "./runPolicyTransport";

const record = z.record(z.string(), z.unknown());
const control = z.object({ revision: z.number().int().nonnegative(), value: record.nullable() });
const provenance = z.literal("operator-supplied-not-measured-entitlement");
const token = z.string().regex(/^[A-Za-z0-9_.:-]{1,128}$/);
const sha256 = z.string().regex(/^[a-f0-9]{64}$/);
const connectionId = z.string().regex(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
const selectorSchema = z.union([
  z.strictObject({ action: z.literal("learning-rights"), subject: z.enum(["source", "output"]) }),
  z.strictObject({ action: z.literal("candidate"), trial: token }),
  z.strictObject({ action: z.literal("evaluation"), trial: token, suite: token }),
  z.strictObject({ action: z.literal("training-backend"), connection_id: connectionId }),
]);
export type ExactControlSelector = z.infer<typeof selectorSchema>;
const selection = z.strictObject({ connection_id: connectionId, connection_revision: z.string().min(1), model: z.string().min(1), effort: z.string().min(1) });
const identities = {
  "learning-rights": z.strictObject({ event_id: token, rights_digest: sha256 }),
  candidate: z.strictObject({ trial: token, experiment_id: token, manifest_digest: sha256, evidence_digest: sha256, serving_identity: z.string().regex(/^provider-reported-revision:[a-f0-9]{64}$/) }),
  evaluation: z.strictObject({ trial: token, experiment_id: token, manifest_digest: sha256, suite_digest: sha256 }),
  "training-backend": z.strictObject({ connection_id: connectionId, connection_revision: z.string().min(1) }),
};
const values = {
  "learning-rights": z.strictObject({ subject: z.enum(["source", "output"]), selection, fields: z.array(z.string()), rights_digest: sha256, document_digests: z.record(z.string(), sha256), review_statement_digest: sha256 }),
  candidate: z.strictObject({ candidate: token, selection, role: z.literal("reasoning"), identity_scope: z.literal("provider-reported-revision"), valid_until: z.number().positive(), deadline_ms: z.number().int().positive(), max_output_tokens: z.number().int().positive(), readiness_ttl_seconds: z.number().positive(), identity: z.string().regex(/^provider-reported-revision:[a-f0-9]{64}$/), model_revision: z.string().min(1) }),
  evaluation: z.strictObject({ trial: token, suite: token, suite_digest: sha256, manifest_digest: sha256 }),
  "training-backend": z.strictObject({ connection_id: connectionId, policy: z.strictObject({ connection_revision: z.string().min(1), budget: record, tariff: record, reservation: record, quota_group: z.string().min(1), version: z.string().min(1), principal: z.string().min(1), principal_role: z.enum(["owner", "member"]), region: z.string().min(1), terms_revision: z.string().min(1), model_revision: z.string().min(1), valid_until: z.number().positive(), isolation: record, controls: record, controls_evidence: z.string().min(1), timeout_seconds: z.number().positive() }) }),
};
const exactControlSchema = z.strictObject({ selector: selectorSchema, revision: z.number().int().nonnegative(), value: record.nullable(), identity: record.nullable() }).superRefine((snapshot, context) => {
  const { action } = snapshot.selector;
  const invalid = (snapshot.revision === 0) !== (snapshot.value === null)
    || (snapshot.value !== null && !values[action].safeParse(snapshot.value).success)
    || (action === "learning-rights" && snapshot.revision === 0 ? snapshot.identity !== null : !identities[action].safeParse(snapshot.identity).success)
    || (["candidate", "evaluation"].includes(action) && snapshot.revision > 1);
  if (invalid) {
    context.addIssue({ code: "custom", message: "Exact control is incomplete or malformed" });
    return;
  }
  const { selector, value, identity } = snapshot;
  // Receipt equality cannot make a selector/value/identity contradiction valid.
  const contradictory = selector.action === "learning-rights" && value !== null
    && (value.subject !== selector.subject || value.rights_digest !== identity?.rights_digest)
    || selector.action === "candidate" && (identity?.trial !== selector.trial
      || value !== null && (value.candidate !== selector.trial || value.identity !== identity?.serving_identity))
    || selector.action === "evaluation" && (identity?.trial !== selector.trial
      || value !== null && (value.trial !== selector.trial || value.suite !== selector.suite
        || value.manifest_digest !== identity?.manifest_digest || value.suite_digest !== identity?.suite_digest))
    || selector.action === "training-backend" && (identity?.connection_id !== selector.connection_id
      || value !== null && (value.connection_id !== selector.connection_id
        || (value.policy as Record<string, unknown>).connection_revision !== identity?.connection_revision));
  if (contradictory) context.addIssue({ code: "custom", message: "Exact control selector, value and identity contradict each other" });
});
export type ExactControl = z.infer<typeof exactControlSchema>;
const exactSchema = z.object({ scope: runScopeSchema, policy_provenance: provenance, exact_control: exactControlSchema });
export type RunExactConfiguration = z.infer<typeof exactSchema>;
const configurationSchema = z.object({ scope: runScopeSchema, policy_provenance: provenance, controls: z.record(z.string(), control), result: record.nullable().optional(), exact_control: exactControlSchema.optional() });

export function proposalSelector(proposal: Pick<RunProposal, "action" | "value">): ExactControlSelector | null {
  const { action, value } = proposal;
  const selected = action === "learning-rights" ? { action, subject: value.subject }
    : action === "candidate" ? { action, trial: value.candidate }
      : action === "evaluation" ? { action, trial: value.trial, suite: value.suite }
        : action === "training-backend" ? { action, connection_id: value.connection_id } : null;
  if (selected === null) return null;
  const parsed = selectorSchema.safeParse(selected);
  if (!parsed.success) throw new RunPolicyError("refused", "Enter the exact control selector before reading. No token is normalised.");
  return parsed.data;
}
async function hashText(text: string): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, "0")).join("");
}
// RightsResolution contains string/array/object/null values only. Python's
// canonical JSON escapes DEL/non-ASCII; raw UTF-8 hashes are only for documents.
function rightsCanonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(rightsCanonical).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.keys(value).sort().map(key => `${rightsCanonical(key)}:${rightsCanonical((value as Record<string, unknown>)[key])}`).join(",")}}`;
  if (value !== null && typeof value !== "string") throw new RunPolicyError("refused", "Malformed rights review; nothing submitted.");
  return JSON.stringify(value).replace(/[\u007f-\uffff]/g, char => `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`);
}
async function comparableProposal(proposal: RunProposal): Promise<Record<string, unknown>> {
  if (proposal.action !== "learning-rights") return structuredClone(proposal.value);
  const { documents, review_statement, rights, ...publicValue } = proposal.value;
  const docs = z.record(z.string(), z.string()).parse(documents);
  const document_digests = Object.fromEntries(await Promise.all(Object.entries(docs).map(async ([key, text]) => [key, await hashText(text)])));
  return { ...publicValue, rights_digest: await hashText(rightsCanonical(rights)), document_digests, review_statement_digest: await hashText(z.string().parse(review_statement)) };
}
const requiredControls = ["access", "grant:reasoning", "learning-dataset", "learning-policy", "learning-binding"];
export type RunConfiguration = z.infer<typeof configurationSchema>;
export interface RunProposal { action: string; expected_revision: number; value: Record<string, unknown> }
const previewSchema = z.object({ scope: runScopeSchema, policy_provenance: provenance, confirmation: z.string().min(1), expires_in_seconds: z.number().positive().max(120), proposal: z.object({ action: z.string(), expected_revision: z.number().int().nonnegative(), value: record }), target_identity: record.nullable().optional() });
export interface RunPreview { proposal: RunProposal; expiresAt: number }
export class RunPolicyReadbackUnavailable extends RunPolicyError {
  readonly result: Record<string, unknown> | null;
  constructor(result: Record<string, unknown> | null) {
    super("unknown", "Acknowledged only — exact control readback unavailable. Do not repeat this write; independently verify the retained result before relying on it.");
    const safe: Record<string, unknown> = {};
    const fields = { event_id: token, candidate: token, rights_digest: sha256, policy_provenance: z.literal("operator-reviewed-document-evidence"), revision: z.number().int().nonnegative() };
    for (const [key, schema] of Object.entries(fields)) {
      const parsed = schema.safeParse(result?.[key]);
      if (parsed.success) safe[key] = parsed.data;
    }
    this.result = Object.keys(safe).length ? safe : null;
  }
}

export function createRunPolicyClient(scope: RunScope) {
  scope = runScopeSchema.parse(scope);
  const transport = createRunPolicyTransport(scope);
  const path = `/v1/model-runs/${encodeURIComponent(scope.run_id)}/configuration`;
  let pending: { view: RunPreview; token: string; captured: string; expiresAt: number; compared: Record<string, unknown>; target: Record<string, unknown> | null | undefined } | null = null;
  let previewGeneration = 0;
  function cancel() { pending = null; previewGeneration++; }
  let needsRead = false;
  let observedExact: ExactControl | null = null;
  function decode(raw: unknown): RunConfiguration {
    const result = configurationSchema.safeParse(raw);
    if (!result.success || !sameRunScope(scope, result.data.scope) || requiredControls.some(key => !(key in result.data.controls))) throw new RunPolicyError("unknown", "Authoritative run scope or configuration mismatch. Read again.");
    return result.data;
  }
  function decodeExact(raw: unknown, selector: ExactControlSelector): RunExactConfiguration {
    const parsed = exactSchema.safeParse(raw);
    if (!parsed.success || !sameRunScope(scope, parsed.data.scope) || canonicalPolicy(selector) !== canonicalPolicy(parsed.data.exact_control.selector)) throw new RunPolicyError("unknown", "Exact control readback missing, malformed or scope changed. Do not resend.");
    return parsed.data;
  }
  async function readControl(selector: ExactControlSelector) {
    selector = selectorSchema.parse(selector); cancel();
    const generation = previewGeneration;
    const value = decodeExact(await transport.request(`${path}/control?${new URLSearchParams(selector)}`), selector);
    if (generation !== previewGeneration) throw new RunPolicyError("retired", "Exact read cancelled; observation retired.");
    observedExact = structuredClone(value.exact_control);
    needsRead = false; return value;
  }
  async function read() { cancel(); const value = decode(await transport.request(path)); needsRead = false; return value; }
  async function preview(proposal: RunProposal): Promise<RunPreview> {
    if (needsRead) throw new RunPolicyError("unknown", "Read exact policy before a new proposal. The prior write is unverified.");
    cancel();
    const generation = previewGeneration;
    const frozen = structuredClone(proposal);
    const requestedAt = Date.now();
    const selector = proposalSelector(frozen);
    const compared = frozen.action === "learning-rights" ? await comparableProposal(frozen) : structuredClone(frozen.value);
    transport.assertCurrent();
    if (generation !== previewGeneration) throw new RunPolicyError("retired", "Preview cancelled while hashing; nothing submitted.");
    const result = previewSchema.safeParse(await transport.request(`${path}/preview`, frozen));
    if (generation !== previewGeneration) throw new RunPolicyError("retired", "Preview cancelled while waiting. No confirmation retained.");
    if (!result.success || !sameRunScope(scope, result.data.scope) || canonicalPolicy(frozen) !== canonicalPolicy(result.data.proposal)) throw new RunPolicyError("unknown", "Preview scope or complete proposal mismatch. Nothing can be confirmed.");
    if (selector && selector.action !== "learning-rights") decodeExact({ scope, policy_provenance: result.data.policy_provenance, exact_control: { selector, revision: 0, value: null, identity: result.data.target_identity } }, selector);
    if (selector && observedExact && canonicalPolicy(selector) === canonicalPolicy(observedExact.selector)
      && (observedExact.revision !== frozen.expected_revision || (selector.action !== "learning-rights" && canonicalPolicy(observedExact.identity) !== canonicalPolicy(result.data.target_identity)))) throw new RunPolicyError("unknown", "Selected control identity changed after the displayed read. Read and review again.");
    const view = { proposal: frozen, expiresAt: requestedAt + result.data.expires_in_seconds * 1000 };
    pending = { view, token: result.data.confirmation, captured: canonicalPolicy(frozen), expiresAt: view.expiresAt, compared, target: result.data.target_identity };
    return view;
  }
  async function confirm(view: RunPreview) {
    transport.assertCurrent();
    const generation = previewGeneration;
    const captured = pending; pending = null;
    if (!captured || captured.view !== view || Date.now() >= captured.expiresAt) throw new RunPolicyError("refused", "Confirmation expired, cancelled or consumed. Explicitly preview again.");
    if (captured.captured !== canonicalPolicy(view.proposal)) throw new RunPolicyError("refused", "Complete proposal changed after preview.");
    needsRead = true;
    const proposal = structuredClone(view.proposal);
    let acknowledged: RunConfiguration | undefined;
    let failure: unknown;
    try { acknowledged = decode(await transport.request(`${path}/confirm`, { ...proposal, confirmation: captured.token })); }
    catch (reason) { transport.assertCurrent(); failure = reason; }
    const selector = proposalSelector(proposal);
    if (selector) {
      let durable: RunExactConfiguration;
      try { durable = decodeExact(await transport.request(`${path}/control?${new URLSearchParams(selector)}`), selector); }
      catch {
        transport.assertCurrent();
        if (failure || !acknowledged) throw new RunPolicyError("unknown", "Confirm outcome unknown; exact readback unavailable. Do not resend.");
        throw new RunPolicyReadbackUnavailable(acknowledged.result ?? null);
      }
      // Cancellation retires publication, not the backend write or its outcome.
      if (generation !== previewGeneration) throw new RunPolicyError("retired", "Confirmation observation cancelled. The write may have completed; read again, never resend.");
      if (failure || !acknowledged?.exact_control) throw new RunPolicyError("unknown", "Confirm outcome unknown or malformed. One exact read attempted; never replay confirmation.");
      const observed = durable.exact_control;
      const ack = decodeExact(acknowledged, selector).exact_control;
      const expected = captured.compared;
      if (observed.revision !== proposal.expected_revision + 1 || canonicalPolicy(ack) !== canonicalPolicy(observed)
        || observed.value === null || Object.entries(expected).some(([key, value]) => canonicalPolicy(observed.value?.[key]) !== canonicalPolicy(value))
        || (selector.action !== "learning-rights" && canonicalPolicy(captured.target) !== canonicalPolicy(observed.identity))) throw new RunPolicyError("unknown", "Acknowledgement/value/immutable identity not verified by exact readback. Do not resend.");
      transport.assertCurrent(); needsRead = false; observedExact = structuredClone(observed);
      return { ...acknowledged, result: null, exact_control: observed };
    }
    const durable = decode(await transport.request(path));
    if (generation !== previewGeneration) throw new RunPolicyError("retired", "Confirmation observation cancelled. The write may have completed; read again, never resend.");
    if (failure || !acknowledged) throw new RunPolicyError("unknown", "Confirm outcome unknown or refused. Exact read attempted; explicitly read and review before any new proposal. Never replay confirmation.");
    const key = proposal.action === "grant" || proposal.action === "revoke-grant" ? "grant:reasoning" : proposal.action === "learning-rights" ? `learning-rights:${proposal.value.subject}` : proposal.action;
    if (!durable.controls[key]) throw new RunPolicyReadbackUnavailable(acknowledged.result ?? null);
    if (durable.controls[key].revision !== proposal.expected_revision + 1 || canonicalPolicy(acknowledged.controls[key]) !== canonicalPolicy(durable.controls[key])) throw new RunPolicyError("unknown", "Acknowledgement is not verified policy: exact revision readback unavailable or changed. Do not resend.");
    const stored = durable.controls[key].value;
    const compared = proposal.action === "learning-policy" ? stored?.value : stored;
    const submittedMatches = compared !== null && typeof compared === "object" && Object.entries(proposal.value).every(([name, value]) => canonicalPolicy((compared as Record<string, unknown>)[name]) === canonicalPolicy(value));
    if (proposal.action === "revoke-grant" ? stored?.role !== "reasoning" || stored?.valid_until !== 0
      : ["access", "grant", "learning-dataset", "learning-policy", "learning-binding"].includes(proposal.action) && !submittedMatches) throw new RunPolicyError("unknown", "Confirmed policy value differs from the captured proposal. Exact readback is not verified.");
    needsRead = false;
    return durable;
  }
  return { read, readControl, preview, confirm, cancel, dispose: () => { cancel(); observedExact = null; transport.dispose(); } };
}
export type RunPolicyClient = ReturnType<typeof createRunPolicyClient>;
