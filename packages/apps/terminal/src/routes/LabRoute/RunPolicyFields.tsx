import { Input } from "@/components/ui/input";
import { proposalSelector, type ExactControlSelector, type RunConfiguration, type RunProposal } from "@/services/runPolicy";
import { canonicalPolicy } from "@/services/runPolicyTransport";

export const usageDimensions = ["requests", "input_tokens", "output_tokens", "currency_micros", "credits_micros", "compute_milliseconds", "bytes", "concurrency", "storage_bytes"];
export const learningFields = ["symbol", "exchange", "action", "entry_price", "exit_price", "quantity", "pnl", "pnl_pct", "exit_reason", "exit_price_estimated", "timestamp"];
const operations = ["adoption.adopt", "adoption.get", "adoption.reconcile", "training.start", "training.get", "training.cancel", "training.reconcile", "evaluation.read", "evaluation.score"];
type Field = { name: string; label: string; kind?: "number" | "json" | "control" };
const field = (name: string, label: string, kind?: Field["kind"]): Field => ({ name, label, kind });
const expiry = field("valid_until", "Valid until (epoch seconds)", "number");
const evidence = field("evidence", "Policy evidence");
const selection = [field("selection.connection_id", "Connection ID"), field("selection.connection_revision", "Exact connection revision (opaque ETag)"), field("selection.model", "Exact model"), field("selection.effort", "Exact effort")];
const rightsFields = [...selection, field("rights", "Rights resolution JSON", "json"), field("documents", "Reviewed documents (fact ID to UTF-8 text JSON)", "json"), field("review_statement", "Document review statement")];
interface Workflow { id: string; label: string; action: string; key: string; hint: string; fields: Field[]; fixed?: Record<string, unknown>; immutable?: boolean }
export const policyWorkflows: Workflow[] = [
  { id: "access", label: "Run access", action: "access", key: "access", hint: "Choose only the permitted operations. Empty selection retires access. This is not permission to change risk or execution account.", fields: [expiry, evidence] },
  { id: "grant", label: "Reasoning model grant", action: "grant", key: "grant:reasoning", hint: "Pre-authorise the reasoning role with provider-reported-revision identity only. Core derives the unchanged risk fingerprint; qualified handover remains separate.", fields: [expiry, evidence], fixed: { role: "reasoning", identity_scope: "provider-reported-revision" } },
  { id: "revoke-grant", label: "Revoke reasoning grant", action: "revoke-grant", key: "grant:reasoning", hint: "Revoke the exact model-role grant. This is not Close, and does not establish that outstanding exposure is flat.", fields: [], fixed: { role: "reasoning" } },
  { id: "evaluation", label: "Bind sealed evaluation", action: "evaluation", key: "evaluation", immutable: true, hint: "Bind an existing exact trial and unused sealed suite. This neither grades nor supplies qualification results. The backend rechecks immutable control scope.", fields: [field("trial", "Existing trial ID"), field("suite", "Unused sealed suite ID")] },
  { id: "candidate", label: "Configure evaluated candidate", action: "candidate", key: "candidate", immutable: true, hint: "Use a real stored candidate trial with independent and prospective evidence. No score or model hash can be supplied here; configuration does not activate it.", fields: [field("candidate", "Evaluated candidate trial ID"), ...selection, expiry, field("deadline_ms", "Deadline (milliseconds)", "number"), field("max_output_tokens", "Maximum output tokens", "number"), field("readiness_ttl_seconds", "Readiness TTL (seconds)", "number")], fixed: { role: "reasoning", identity_scope: "provider-reported-revision" } },
  ...["source", "output"].map(subject => ({ id: `rights-${subject}`, label: subject === "source" ? "1. Review source document rights" : "2. Review model-output terms", action: "learning-rights", key: `learning-rights:${subject}`, hint: "Operator-reviewed document evidence, not a legal determination or measured entitlement. Supply actual UTF-8 documents and matching LicenceFact SHA-256 values; hashes prove bytes only. Source licences identify closed-trades:<run ID>; output terms identify the exact model. Only isolated-research output use, retention and training/distillation rights are accepted. No stock licence substitution or distribution grant.", fields: rightsFields, fixed: { subject, fields: learningFields } })),
  { id: "learning-dataset", label: "3. Define bounded learning dataset", action: "learning-dataset", key: "learning-dataset", hint: "Reference the separately confirmed canonical source/output rights events. Core derives the dataset scope. Changing accounts, fields, recipients, terms or limits requires new consent, not an enlarged binding.", fields: [field("source_rights", "Canonical source-rights event ID"), field("output_rights", "Canonical output-rights event ID"), field("as_of_start", "As-of start (UTC ISO)"), field("as_of_end", "As-of end (UTC ISO)")] },
  { id: "learning-policy", label: "4. Set reflection destination and limits", action: "learning-policy", key: "learning-policy", hint: "Every usage dimension must be explicit, including zero where appropriate. Hard local/provider controls require evidence; observational caps are not accepted. No provider, effort, price or budget is inferred.", fields: [...selection, ...usageDimensions.flatMap(name => [field(`reservation.${name}`, `Reservation: ${name}`, "number"), field(`controls.${name}`, `Control: ${name}`, "control")]), field("controls_evidence", "Hard-control evidence"), field("principal", "Recipient principal"), field("region", "Recipient region"), field("terms_revision", "Terms revision"), expiry, field("max_output_tokens", "Maximum output tokens", "number"), field("timeout_seconds", "Timeout (seconds)", "number")] },
  { id: "learning-binding", label: "5. Bind an existing learning permission", action: "learning-binding", key: "learning-binding", hint: "First use the separate Learning permissions workflow (/v1/learning/permissions) to approve the exact dataset, recipient, reflection purpose and cumulative limits. Paste only its existing grant ID here. This does not mint or expand consent. Matching future records consume the same limits; expansion requires new consent.", fields: [field("grant_id", "Existing learning grant ID")] },
  { id: "training-backend", label: "Optional training-backend policy", action: "training-backend", key: "training-backend", hint: "Advanced operator policy only. Required: connection_revision, budget (currency/window_start/window_end/all limits), tariff, reservation, quota_group, version, principal, principal_role, region, terms_revision, model_revision, valid_until, isolation (dedicated/pool/evidence), controls, controls_evidence, timeout_seconds. All nine usage dimensions are explicit. The supported Unsloth pin is 3e7898659344873423a9a09438c80d51bc056655. No upload, job start or serving occurs here. Trained-output serving attestation and automatic activation remain unavailable.", fields: [field("connection_id", "Training connection ID"), field("policy", "Complete bounded training policy JSON", "json")] },
];
export type PolicyDraft = Record<string, string>;
export function workflowSelector(workflow: Workflow, draft: PolicyDraft): ExactControlSelector | null {
  return proposalSelector({ action: workflow.action, value: { ...workflow.fixed, ...draft } });
}
export function policyRevision(workflow: Workflow, configuration: RunConfiguration, draft: PolicyDraft): number | null {
  try {
    const selected = workflowSelector(workflow, draft);
    if (!selected) return configuration.controls[workflow.key]?.revision ?? null;
    const observed = configuration.exact_control;
    return observed && canonicalPolicy(observed.selector) === canonicalPolicy(selected) ? observed.revision : null;
  } catch { return null; }
}
export function buildRunProposal(workflow: Workflow, configuration: RunConfiguration, draft: PolicyDraft, selected: string[]): RunProposal {
  const expected_revision = policyRevision(workflow, configuration, draft);
  if (expected_revision === null) throw new Error("Supply the exact current revision from its authority; missing revision is not zero.");
  const value: Record<string, unknown> = { ...workflow.fixed };
  if (workflow.action === "access") value.operations = selected;
  for (const item of workflow.fields) {
    const text = draft[item.name];
    if (!text?.trim()) throw new Error(`Required: ${item.label}. No value is inferred.`);
    let parsed: unknown = text;
    if (item.kind === "number") {
      if (!/^\d+(?:\.\d+)?$/.test(text) || !Number.isFinite(Number(text))) throw new Error(`Invalid numeric ${item.label}.`);
      parsed = Number(text);
    }
    if (item.kind === "json") {
      try { parsed = JSON.parse(text); } catch { throw new Error(`Invalid JSON: ${item.label}.`); }
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error(`Object required: ${item.label}.`);
    }
    const [group, child] = item.name.split(".");
    if (child) { const nested = (value[group] ?? {}) as Record<string, unknown>; nested[child] = parsed; value[group] = nested; }
    else value[group] = parsed;
  }
  return { action: workflow.action, expected_revision, value };
}
export function RunPolicyFields({ workflow, configuration, draft, selected, onChange, onOperations }: { workflow: Workflow; configuration: RunConfiguration; draft: PolicyDraft; selected: string[]; onChange: (name: string, value: string) => void; onOperations: (operations: string[]) => void }) {
  const revision = policyRevision(workflow, configuration, draft);
  const fields = workflow.fields;
  return <>
    <p className="text-sm text-text-secondary">{workflow.hint}</p>
    {revision === null ? <p className="text-xs text-warning">Read the selected exact control before preview. Unavailable custody is not revision zero; no revision is inferred.</p> : <p className="text-xs">Current control revision: {revision}</p>}
    {workflow.action === "learning-rights" ? <p className="text-xs break-words">Source: autonomous-trader.closed-trades:v1 · observations · reflection-prompt:v1. Fields: {learningFields.join(", ")}. Producer evidence is not broker-reconciled accounting; estimated exits retain their flags.</p> : null}
    {workflow.action === "access" ? <div className="grid gap-2 sm:grid-cols-2">{operations.map(operation => <label className="text-sm flex gap-2" key={operation}><input type="checkbox" checked={selected.includes(operation)} onChange={event => onOperations(event.target.checked ? [...selected, operation] : selected.filter(value => value !== operation))} />{operation}</label>)}</div> : null}
    <div className="grid gap-3 sm:grid-cols-2">{fields.map(item => <label key={item.name} className={`block text-sm min-w-0 ${item.kind === "json" ? "sm:col-span-2" : ""}`}>{item.label}
      {item.kind === "json" ? <textarea name={item.name} aria-label={item.label} spellCheck={false} autoComplete="off" className="mt-1 min-h-36 w-full rounded border border-border-default bg-surface-card p-3 font-mono text-xs" value={draft[item.name] ?? ""} onChange={event => onChange(item.name, event.target.value)} />
        : item.kind === "control" ? <select name={item.name} aria-label={item.label} className="mt-1 w-full rounded border border-border-default bg-surface-card p-2" value={draft[item.name] ?? ""} onChange={event => onChange(item.name, event.target.value)}><option value="">Choose explicit control</option>{["hard-local", "hard-provider", "not-applicable"].map(value => <option key={value}>{value}</option>)}</select>
        : <Input name={item.name} aria-label={item.label} autoComplete="off" type={item.kind === "number" ? "number" : "text"} value={draft[item.name] ?? ""} onChange={event => onChange(item.name, event.target.value)} />}
    </label>)}</div>
  </>;
}
