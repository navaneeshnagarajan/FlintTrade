import { useRef, useState } from "react";
import { KnowledgeSelector, revalidateSelectedKnowledge, useSelectedKnowledge } from "./KnowledgeSelector";
import { onlineManager, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { dispatchServiceTask, readServiceControl, readServiceTask, saveServiceControl, type ServiceTaskReceipt } from "@/services/serviceTasks";
import { readConnectionCollection, type ServiceConnectionCollection } from "@/services/serviceConnectionControls";
import { knowledgeRetirementKey, knowledgeScopeKey, useKnowledgeScope } from "@/services/knowledgeScope";
import ServiceConnectionSetup from "./ServiceConnectionSetup";
import { captureAuthSessionFence, isAuthSessionFenceCurrent, useAuthStore } from "@/stores/authStore";
import { isDemoAuthSession } from "@/services/ftApi.helpers";

/** Real R1 advisory-only interface. No secrets, inferred entitlements, invented
 * budgets, default model selection, training grants or trading actions. */
export default function ModelRoutingPanel() {
  const generation = useAuthStore(state => state.sessionGeneration);
  const status = useAuthStore(state => state.status);
  const hasToken = useAuthStore(state => !!state.token);
  const scope = useKnowledgeScope();
  const client = useQueryClient();
  if (status !== "logged-in" || !hasToken || isDemoAuthSession()) return <p role="status" className="p-4 text-sm text-text-muted">Model setup requires an installed operator session. Local help remains available.</p>;
  return <SessionModelRoutingPanel key={knowledgeRetirementKey(client)} generation={generation} scope={scope} />;
}
function SessionModelRoutingPanel({ generation, scope }: { generation: number; scope: string }) {
  const queryClient = useQueryClient();
  const activeKey = ["service-task-active", generation, scope];
  const [recovered] = useState(() => queryClient.getQueryData<{ id: string; receipt: ServiceTaskReceipt | null }>(activeKey));
  const connections = useQuery({ queryKey: ["service-connections", generation], queryFn: () => readConnectionCollection(), retry: false, staleTime: 10_000, refetchOnWindowFocus: false });
  const [connectionId, setConnectionId] = useState("");
  const [mode, setMode] = useState<"fixed" | "automatic">("fixed");
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState("");
  const [prompt, setPrompt] = useState("");
  const [refs, setRefs] = useState("");
  const [selectedSkills, setSelectedSkills] = useSelectedKnowledge();
  const [classification, setClassification] = useState<"public" | "private">("public");
  const [deadline, setDeadline] = useState("");
  const [outputLimit, setOutputLimit] = useState("");
  const [requestId, setRequestId] = useState(recovered?.id ?? "");
  const [receipt, setReceipt] = useState<ServiceTaskReceipt | null>(recovered?.receipt ?? null);
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const [error, setError] = useState("");
  const [path, setPath] = useState("task-routing");
  const [etag, setEtag] = useState("");
  const [policy, setPolicy] = useState("");
  const [notice, setNotice] = useState("");
  // Non-secret uncertainty survives panel disposal within this auth session.
  // It is not a mutation cache: no request body or credential is retained.
  const { data: connectionBlocked = false } = useQuery({ queryKey: ["service-connections-blocked", generation], initialData: false, queryFn: async () => true, enabled: false, gcTime: Infinity });
  function setConnectionBlocked(blocked: boolean) { queryClient.setQueryData(["service-connections-blocked", generation], blocked); }
  function retireSelection() {
    setConnectionId(""); setModel(""); setEffort(""); setEtag(""); setPolicy(""); setNotice("");
  }
  const current = () => scope === knowledgeScopeKey(queryClient);
  async function run(action: () => Promise<void>) {
    if (!current() || pending.current) return;
    pending.current = true;
    setBusy(true); setError("");
    try { await action(); }
    catch (e) { if (current()) setError(e instanceof Error ? e.message : "Request unavailable"); }
    finally { pending.current = false; if (current()) setBusy(false); }
  }
  function publishReceipt(id: string, result: ServiceTaskReceipt) {
    setReceipt(result);
    // Only this mounted scope owns plaintext. The disposable/recoverable cache
    // keeps durable evidence and uncertainty, never prompt or answer text.
    const { output: _output, ...durable } = result;
    queryClient.setQueryData(activeKey, { id, receipt: durable });
  }
  async function reread() {
    const previous = receipt ?? undefined;
    setReceipt(null);
    queryClient.setQueryData(activeKey, { id: requestId, receipt: null });
    const result = await readServiceTask(requestId, previous, current);
    if (current()) publishReceipt(requestId, result);
  }
  async function send() {
    const fence = captureAuthSessionFence();
    // Freeze all task inputs before the first await; preflight never adopts a
    // new account, run, connection revision or edited form on resumption.
    const revision = connections.data?.etag;
    const inventoryCount = queryClient.getQueryState(["service-connections", generation])?.dataUpdateCount;
    const selectionKey = ["knowledge", "selected-skills", scope];
    const selectionCount = queryClient.getQueryState(selectionKey)?.dataUpdateCount;
    const input = { mode, selection: mode === "automatic" ? null : { connection_id: connectionId, connection_revision: revision!, model, effort },
      prompt, classification, purpose: "assistant" as const, deadline_ms: Number(deadline), max_output_tokens: Number(outputLimit), required_hard_controls: ["output_tokens"] };
    const manualRefs = refs ? refs.split(",").map(reference => reference.trim()) : [];
    function assertPendingScope() {
      const inventory = queryClient.getQueryState<ServiceConnectionCollection>(["service-connections", generation]);
      if (!current() || !isAuthSessionFenceCurrent(fence)) throw new Error("Task scope changed before dispatch");
      if (queryClient.getQueryState(selectionKey)?.dataUpdateCount !== selectionCount) throw new Error("Knowledge selection changed before dispatch");
      if (!onlineManager.isOnline() || !revision || inventory?.data?.etag !== revision || inventory.status !== "success"
        || inventory.dataUpdateCount !== inventoryCount || inventory.fetchStatus !== "idle" || inventory.isInvalidated
        || queryClient.getQueryData(["service-connections-blocked", generation])) throw new Error("Connection evidence changed; review before sending");
    }
    assertPendingScope();
    const selectedKnowledgeRefs = await revalidateSelectedKnowledge(queryClient);
    assertPendingScope();
    const id = crypto.randomUUID();
    // Start the exact transport before cache subscribers can retire this scope.
    // No submitted state exists until both preflight and the send fence pass.
    const submission = dispatchServiceTask({ ...input, request_id: id, context_refs: [...new Set([...selectedKnowledgeRefs, ...manualRefs])] }, current);
    queryClient.setQueryData(activeKey, { id, receipt: null });
    if (current()) { setRequestId(id); setReceipt(null); }
    const result = await submission;
    if (current() && isAuthSessionFenceCurrent(fence)) publishReceipt(id, result);
  }
  const unresolved = !!requestId && (!receipt || !["completed", "refused"].includes(receipt.outcome) || receipt.code?.includes("unknown") || receipt.accounting === "unknown");
  const canSend = !unresolved && !connectionBlocked && !connections.isError && !connections.isFetching && !!prompt.trim() && Number.isSafeInteger(Number(deadline)) && Number(deadline) > 0 && Number.isSafeInteger(Number(outputLimit)) && Number(outputLimit) > 0 && !!connections.data && (mode === "automatic" || (!!connections.data.connections.find(row => row.connection_id === connectionId) && !!model && !!effort));
  return <section className="space-y-5 p-4" aria-label="Core model routing">
    <header><h2 className="text-lg font-semibold">Model connections and tasks</h2><p className="text-sm text-text-secondary">Advisory text through the shared core. Configured connections are not qualified providers. Learning, tool execution and trading are not enabled here.</p></header>
    {connections.isError && <p role="alert" className="text-warning">Connections unavailable: {connections.error.message}</p>}
    {connections.data?.connections.length === 0 && <p role="status">No model connections configured. Local help and manual controls remain usable.</p>}
    <ServiceConnectionSetup snapshot={connections.data} blocked={connectionBlocked} unavailable={connections.isError || connections.isFetching || busy} onBlocked={setConnectionBlocked} onChanged={snapshot => { queryClient.setQueryData(["service-connections", generation], snapshot); retireSelection(); }} onRefresh={async () => { const result = await connections.refetch({ throwOnError: true }); retireSelection(); return result; }} />
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="text-xs">Routing<select aria-label="Task routing mode" className="block w-full rounded border border-border-default bg-surface-card p-2" value={mode} onChange={e => setMode(e.target.value as typeof mode)}><option value="fixed">Explicit fixed selection</option><option value="automatic">Configured automatic pool</option></select></label>
      <label className="text-xs">Connection<select aria-label="Task connection" className="block w-full rounded border border-border-default bg-surface-card p-2" value={connectionId} disabled={mode === "automatic"} onChange={e => { setConnectionId(e.target.value); setModel(connections.data?.connections.find(c => c.connection_id === e.target.value)?.model ?? ""); }}><option value="">Choose an existing connection</option>{connections.data?.connections.map(c => <option key={c.connection_id} value={c.connection_id}>{c.label} · {c.provider_id}</option>)}</select></label>
      <label className="text-xs">Exact model<Input aria-label="Task model" value={model} onChange={e => setModel(e.target.value)} disabled={mode === "automatic"} /></label>
      <label className="text-xs">Configured effort key<Input aria-label="Task effort" value={effort} onChange={e => setEffort(e.target.value)} disabled={mode === "automatic"} /></label>
      <label className="text-xs">Deadline (ms)<Input aria-label="Task deadline" type="number" min="1" value={deadline} onChange={e => setDeadline(e.target.value)} /></label>
      <label className="text-xs">Maximum output tokens<Input aria-label="Task output limit" type="number" min="1" value={outputLimit} onChange={e => setOutputLimit(e.target.value)} /></label>
      <label className="text-xs">Classification<select aria-label="Task classification" value={classification} onChange={e => setClassification(e.target.value as typeof classification)} className="block w-full bg-surface-card p-2"><option value="public">Public context</option><option value="private">Private context (requires configured consent)</option></select></label>
      <label className="text-xs">Selected knowledge references<Input aria-label="Task knowledge references" value={refs} onChange={e => setRefs(e.target.value)} placeholder="skill:canonical_name, …" /></label>
    </div>
    <details><summary>Choose canonical knowledge</summary><KnowledgeSelector selected={selectedSkills} onSelection={setSelectedSkills} /></details>
    <label className="block text-sm">Task<textarea aria-label="Advisory task" className="mt-1 min-h-24 w-full rounded border border-border-default bg-surface-card p-3" value={prompt} onChange={e => setPrompt(e.target.value)} /></label>
    <p className="text-xs text-text-muted">Send only context authorised for the selected destination. No credentials. An output-token cap is required; unsupported hard controls refuse instead of silently falling back. No knowledge is selected automatically.</p>
    <Button disabled={busy || !canSend} onClick={() => void run(send)}>Send advisory task</Button>
    {requestId && <div className="space-y-2"><p className="break-all font-mono text-xs">Request {requestId}</p><Button size="sm" variant="outline" disabled={busy} onClick={() => void run(reread)}>Read durable receipt</Button></div>}
    {error && <p role="alert" className="text-sm text-warning">{error}. {requestId ? "A failed response does not prove cancellation; inspect the same request receipt before starting another task." : "Task not submitted. Refresh and review before sending again."}</p>}
    {receipt && <section aria-label="Task receipt" className="space-y-2 rounded border border-border-default p-3"><h3 className="font-semibold">{receipt.outcome}{receipt.code ? ` · ${receipt.code}` : ""}</h3>{receipt.output !== undefined ? <p className="whitespace-pre-wrap text-sm">{receipt.output}</p> : receipt.outcome === "completed" && <p className="text-sm text-text-muted">Output unavailable. Core retains digest-only evidence; this view has no verified transient answer.</p>}<details><summary>Selection, context and usage evidence</summary><pre className="overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(receipt, null, 2)}</pre></details></section>}
    <details className="space-y-3 border-t border-border-default pt-4"><summary>Admission, shared quotas and routing policy</summary>
      <p className="text-xs text-text-muted">Explicit operator-supplied evidence only. No sample grants or budgets are prefilled. Read the exact current revision before editing. Subscription/OAuth acquisition and refresh are not implemented.</p>
      <Input aria-label="Service control path" value={path} onChange={e => { setPath(e.target.value); setEtag(""); setPolicy(""); }} placeholder="task-routing, connection-id/admission, quota-groups/group-id" />
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void run(async () => { const control = await readServiceControl(path); setEtag(control.etag); setPolicy(control.policy == null ? "" : JSON.stringify(control.policy, null, 2)); setNotice(control.policy == null ? "No policy configured" : `Loaded revision ${control.etag}`); })}>Read policy</Button>
      <textarea aria-label="Explicit service policy JSON" className="min-h-40 w-full rounded border border-border-default bg-surface-card p-3 font-mono text-xs" value={policy} onChange={e => setPolicy(e.target.value)} />
      <Button size="sm" disabled={busy || !etag || !policy} onClick={() => void run(async () => { const control = await saveServiceControl(path, etag, JSON.parse(policy)); setEtag(control.etag); setPolicy(JSON.stringify(control.policy, null, 2)); setNotice(`Saved and verified revision ${control.etag}`); })}>Save explicit policy</Button>
      {notice && <p role="status" className="text-xs">{notice}</p>}
    </details>
  </section>;
}
