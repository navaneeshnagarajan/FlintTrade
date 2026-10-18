import { useState } from "react";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { knowledgeRequest } from "@/services/knowledgeApi";
const Preview = z.object({ proposal: z.record(z.string(), z.unknown()), confirmation: z.string(), expires_in_seconds: z.number() });
const base = "/v1/learning/permissions";
export default function LearningPermissions() {
  const [proposal, setProposal] = useState(""); const [preview, setPreview] = useState<z.infer<typeof Preview> | null>(null);
  const [grantId, setGrantId] = useState(""); const [attemptId, setAttemptId] = useState(""); const [batchId, setBatchId] = useState("");
  const [result, setResult] = useState<Record<string, unknown> | null>(null); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const grantPath = `${base}/grants/${encodeURIComponent(grantId)}`;
  async function run(action: () => Promise<void>) { setBusy(true); setError(""); setResult(null); try { await action(); } catch (e) { setError(String(e)); } finally { setBusy(false); } }
  async function confirm() {
    if (!preview) return;
    const exact = preview; setPreview(null); // one-shot even on a lost response
    const created = z.looseObject({ grant_id: z.string() }).parse(await knowledgeRequest(`${base}/grants`, { ...exact.proposal, confirmation: exact.confirmation }));
    setGrantId(created.grant_id);
    setResult(await knowledgeRequest(`${base}/grants/${encodeURIComponent(created.grant_id)}`));
  }
  return <section className="space-y-4 p-4" aria-label="Learning permissions"><h2 className="text-lg font-semibold">Learning permissions</h2><p className="text-sm text-text-secondary">Inference access is not learning consent. This optional operator workflow needs the core’s trusted canonical dataset, rights and recipient authority; absent authority refuses. No grant or numeric budget is prefilled.</p>
    <label className="block text-sm">Complete explicit proposal<textarea aria-label="Complete learning proposal JSON" disabled={busy} className="mt-2 min-h-36 w-full rounded border border-border-default bg-surface-card p-3 font-mono text-xs" value={proposal} onChange={e => { setProposal(e.target.value); setPreview(null); }} /></label>
    <p className="text-xs text-text-muted">Required fields: scope, recipient, purpose, operations, valid_from, valid_until, every limits dimension, max_rows, max_trials, retention, derivatives, objective, rights, supersedes. Actor and account authority are resolved by core, not this form.</p>
    <Button variant="outline" disabled={busy || !proposal} onClick={() => void run(async () => { setPreview(null); setPreview(Preview.parse(await knowledgeRequest(`${base}/preview`, JSON.parse(proposal)))); })}>Preview exact permission</Button>
    {preview && <section className="space-y-2"><h3 className="font-semibold">Review the exact permission</h3><p className="text-xs">One-shot confirmation expires after {preview.expires_in_seconds} seconds; core checks it again at confirmation.</p><pre className="overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(preview.proposal, null, 2)}</pre></section>}
    <Button disabled={busy || !preview} onClick={() => void run(confirm)}>Confirm this exact permission</Button>
    <div className="space-y-2 border-t border-border-default pt-4"><Input aria-label="Learning grant ID" disabled={busy} value={grantId} onChange={e => { setGrantId(e.target.value); setResult(null); }} /><div className="flex flex-wrap gap-2"><Button variant="outline" disabled={busy || !grantId} onClick={() => void run(async () => setResult(await knowledgeRequest(grantPath)))}>Read permission status</Button><Button variant="destructive" disabled={busy || !grantId} onClick={() => void run(async () => { await knowledgeRequest(`${grantPath}/revoke`, {}); setResult(await knowledgeRequest(grantPath)); })}>Revoke learning permission</Button></div></div>
    <p className="text-xs text-text-muted">Revocation blocks new sends. It does not prove remote cancellation, deletion or erasure from trained weights. Lost responses remain unknown; read the exact retained record before creating another grant.</p>
    <Input aria-label="Learning batch ID" disabled={busy} value={batchId} onChange={e => setBatchId(e.target.value)} /><Button variant="outline" disabled={busy || !grantId || !batchId} onClick={() => void run(async () => setResult(await knowledgeRequest(`${grantPath}/manifests/${encodeURIComponent(batchId)}`)))}>Read exact batch manifest</Button>
    <Input aria-label="Learning attempt ID" disabled={busy} value={attemptId} onChange={e => setAttemptId(e.target.value)} /><Button variant="outline" disabled={busy || !attemptId} onClick={() => void run(async () => setResult(await knowledgeRequest(`${base}/receipts/${encodeURIComponent(attemptId)}`)))}>Read transfer receipt</Button>
    {error && <p role="alert" className="text-warning">{error}</p>}{result && <pre aria-label="Learning permission evidence" className="overflow-auto whitespace-pre-wrap rounded border border-border-default p-3 text-xs">{JSON.stringify(result, null, 2)}</pre>}
  </section>;
}
