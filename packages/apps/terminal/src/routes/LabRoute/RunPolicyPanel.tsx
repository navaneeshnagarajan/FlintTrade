import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";
import { RunPolicyFields, buildRunProposal, policyRevision, policyWorkflows, workflowSelector, type PolicyDraft } from "./RunPolicyFields";
import { createRunPolicyClient, RunPolicyReadbackUnavailable, type RunConfiguration, type RunPolicyClient, type RunPreview } from "@/services/runPolicy";
import { RunPolicyError, runPolicyAuthorityKey, subscribeRunPolicyAuthority, type RunScope } from "@/services/runPolicyTransport";

export function RunPolicyPanel({ scope }: { scope: RunScope }) {
  const generation = useSyncExternalStore(subscribeRunPolicyAuthority, runPolicyAuthorityKey, runPolicyAuthorityKey);
  return <ScopedRunPolicyPanel key={JSON.stringify([generation, scope.run_id, scope.actor, scope.account, scope.environment])} scope={scope} />;
}
function ScopedRunPolicyPanel({ scope }: { scope: RunScope }) {
  const [acknowledgement, setAcknowledgement] = useState<Record<string, unknown> | null>(null);
  const [configuration, setConfiguration] = useState<RunConfiguration | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [draft, setDraft] = useState<PolicyDraft>({});
  const [workflowId, setWorkflowId] = useState("access");
  const workflow = policyWorkflows.find(value => value.id === workflowId) ?? policyWorkflows[0];
  const [preview, setPreview] = useState<RunPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const owner = useRef<RunPolicyClient | null>(null);
  const pending = useRef(false);
  const { run_id, actor, account, environment } = scope;
  useEffect(() => {
    const client = createRunPolicyClient({ run_id, actor, account, environment }); owner.current = client;
    void client.read().then(data => { if (owner.current === client) setConfiguration(data); }).catch(() => { if (owner.current === client) setError("Run configuration unavailable. This is not an empty policy."); });
    return () => {
      owner.current = null; client.dispose(); pending.current = false;
      // Activity disconnects effects without discarding state: erase private
      // draft/confirmation owners on hide as well as actual disposal.
      setDraft({}); setSelected([]); setPreview(null); setConfiguration(null);
      setNotice(""); setError(""); setBusy(false); setAcknowledgement(null);
    };
  }, [run_id, actor, account, environment]);
  function edit() { owner.current?.cancel(); setPreview(null); setNotice(""); }
  async function run(work: (client: RunPolicyClient) => Promise<void>) {
    const client = owner.current;
    if (!client || pending.current) return;
    pending.current = true; setBusy(true); setError(""); setNotice("");
    try { await work(client); }
    catch (reason) { if (owner.current === client) {
      setError(reason instanceof Error ? reason.message : "Policy unavailable");
      if (reason instanceof RunPolicyError) setConfiguration(null);
      if (reason instanceof RunPolicyReadbackUnavailable) setAcknowledgement(reason.result);
    } }
    finally { if (owner.current === client) { pending.current = false; setBusy(false); } }
  }
  return <section aria-label={`Run policy ${run_id}`} className="space-y-3 min-w-0 border-t border-border-default pt-4">
    <h4 className="font-semibold">Run policy and learning</h4>
    <p className="text-xs text-text-secondary">Operator-supplied policy, not activation or qualification. Configuration does not start training, serve a model or rearm trading.</p>
    {configuration ? <>
      <p className="text-xs break-all">Authoritative scope: {configuration.scope.actor} · {configuration.scope.account} · {configuration.scope.environment} · {configuration.scope.run_id}</p>
      <dl className="grid gap-2 sm:grid-cols-2 text-xs">{["access", "grant:reasoning", "learning-dataset", "learning-policy", "learning-binding"].map(key => <div key={key}><dt className="text-text-secondary">{key}</dt><dd>{configuration.controls[key] ? `Revision ${configuration.controls[key].revision} · ${configuration.controls[key].value ? "Configured policy (not activation)" : "Not configured"}` : "Unavailable"}</dd></div>)}</dl>
      <details><summary>Current policy values and limits</summary><PolicyEvidence value={configuration.controls} /></details>
      <label className="block text-sm">Policy workflow<select aria-label="Policy workflow" className="mt-1 w-full rounded border border-border-default bg-surface-card p-2" disabled={busy} value={workflowId} onChange={event => { edit(); setDraft({}); setSelected([]); setWorkflowId(event.target.value); setConfiguration(current => current ? { ...current, exact_control: undefined } : null); setError(""); }}>{policyWorkflows.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
      <fieldset disabled={busy} className="space-y-3"><legend className="font-medium">{workflow.label}</legend>
        <RunPolicyFields workflow={workflow} configuration={configuration} draft={draft} selected={selected} onChange={(name, value) => { edit(); if (["candidate", "trial", "suite", "connection_id"].includes(name)) setConfiguration(current => current ? { ...current, exact_control: undefined } : null); setDraft(values => ({ ...values, [name]: value })); }} onOperations={value => { edit(); setSelected(value); }} />
      </fieldset>
      {["learning-rights", "candidate", "evaluation", "training-backend"].includes(workflow.action) ? <>
        <Button variant="outline" disabled={busy} onClick={() => void run(async client => {
          edit(); const selector = workflowSelector(workflow, draft);
          if (!selector) return;
          const result = await client.readControl(selector);
          if (owner.current === client) setConfiguration(current => current ? { ...current, exact_control: result.exact_control } : null);
        })}>Read selected control</Button>
        {configuration.exact_control ? <aside aria-label="Selected control evidence" className="text-xs space-y-2"><p>Selected control revision: {configuration.exact_control.revision} · {configuration.exact_control.value === null ? "Not configured (proven unissued)" : "Configured policy — not activated"}</p><PolicyEvidence value={configuration.exact_control} /></aside> : null}
      </> : null}
      <Button variant="outline" disabled={busy || policyRevision(workflow, configuration, draft) === null} onClick={() => void run(async client => {
        const result = await client.preview(buildRunProposal(workflow, configuration, draft, selected));
        if (owner.current === client) setPreview(result);
      })}>Preview policy</Button>
    </> : <p role="status">Read authoritative policy before editing.</p>}
    {preview ? <div className="space-y-2 rounded border border-warning p-3"><h5 className="font-medium">Review exact policy</h5><p className="text-xs">{preview.proposal.action} · revision {preview.proposal.expected_revision} · one-use confirmation. No automatic refresh.</p><pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words text-xs">{JSON.stringify(preview.proposal.value, null, 2)}</pre>
      <Button disabled={busy} onClick={() => { const exact = preview; setPreview(null); setDraft(values => Object.fromEntries(Object.entries(values).filter(([key]) => ["trial", "suite", "candidate", "connection_id"].includes(key)))); void run(async client => { const result = await client.confirm(exact); if (owner.current === client) { setConfiguration(result); setNotice("Policy verified by exact readback. Not activated or qualified."); } }); }}>Confirm exact policy</Button>
      <Button variant="outline" disabled={busy} onClick={edit}>Cancel proposal</Button></div> : null}
    <Button variant="outline" disabled={busy} onClick={() => { edit(); void run(async client => { const result = await client.read(); if (owner.current === client) setConfiguration(result); }); }}>Read exact policy</Button>
    {busy ? <p role="status">Policy request pending. Do not resend.</p> : null}
    {notice ? <p role="status">{notice}</p> : null}{error ? <p role="alert" className="text-warning text-sm">{error}</p> : null}
    {acknowledgement ? <aside className="border border-warning p-3 space-y-2"><h5 className="text-sm font-medium">Unverified acknowledgement — not an independent readback</h5><PolicyEvidence value={acknowledgement} /><Button variant="outline" onClick={() => setAcknowledgement(null)}>Clear acknowledgement</Button></aside> : null}
  </section>;
}

function PolicyEvidence({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span>Not configured / unavailable</span>;
  if (Array.isArray(value)) return <ul className="space-y-1">{value.map((item, index) => <li key={index}><PolicyEvidence value={item} /></li>)}</ul>;
  if (typeof value === "object") return <dl className="space-y-2 text-xs min-w-0">{Object.entries(value).map(([key, item]) => <div className="border-l border-border-default pl-2 break-words" key={key}><dt className="font-medium">{key}</dt><dd className="pl-2 whitespace-pre-wrap"><PolicyEvidence value={item} /></dd></div>)}</dl>;
  return <span className="break-all">{String(value)}</span>;
}
