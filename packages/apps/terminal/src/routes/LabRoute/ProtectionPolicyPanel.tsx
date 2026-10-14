import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createProtectionPolicyClient, protectionPolicySchema, type ProtectionPolicy, type ProtectionReadback } from "@/services/protectionPolicy";
import { runPolicyAuthorityKey, subscribeRunPolicyAuthority, type RunScope } from "@/services/runPolicyTransport";

const fields = [
  ["policy_revision", "Policy revision identifier"], ["valid_until", "Protection valid until (epoch seconds)", "number"],
  ["position.symbol", "Exact position symbol"], ["position.exchange", "Exact position exchange"], ["position.product", "Exact position product"],
  ["position.entry_order_ids", "Completed entry order IDs (one per line)"], ["position.quantity", "Owned position quantity", "number"],
  ["max_quantity", "Maximum protection quantity", "number"], ["max_notional", "Maximum protection notional", "number"],
  ["read.selector", "Exact quote-read selector"], ["read.valid_until", "Quote-read valid until (epoch seconds)", "number"],
  ["read.max_reads", "Maximum quote reads", "number"], ["read.max_age_seconds", "Maximum quote age (seconds)", "number"],
];
function proposal(draft: Record<string, string>): ProtectionPolicy {
  function text(key: string) { if (!draft[key]?.trim()) throw new Error(`Required: ${fields.find(item => item[0] === key)?.[1] ?? key}. No economic defaults.`); return draft[key]; }
  function number(key: string) { const value = text(key); if (!/^\d+(?:\.\d+)?$/.test(value)) throw new Error("Explicit positive numeric protection bounds required."); return Number(value); }
  const parsed = protectionPolicySchema.safeParse({ policy_revision: text("policy_revision"), valid_until: number("valid_until"), hedge_scope: [], risk_policy: "unhedged-cash-reduction-only",
    position: { symbol: text("position.symbol"), exchange: text("position.exchange"), product: text("position.product"), entry_order_ids: text("position.entry_order_ids").split("\n"), quantity: number("position.quantity") },
    max_quantity: number("max_quantity"), max_notional: number("max_notional"), read: { selector: text("read.selector"), valid_until: number("read.valid_until"), max_reads: number("read.max_reads"), max_age_seconds: number("read.max_age_seconds") } });
  if (!parsed.success) throw new Error("Complete unhedged NSE/BSE cash protection policy required. Quantities must be positive integers; quote age must not exceed 60 seconds; read expiry/quantity cannot exceed grant bounds.");
  return parsed.data;
}
function PolicySummary({ policy }: { policy: ProtectionPolicy }) {
  return <dl className="grid gap-2 sm:grid-cols-2 text-xs break-words">
    <div><dt>Policy / expiry</dt><dd>{policy.policy_revision} · {policy.valid_until} epoch seconds</dd></div>
    <div><dt>Owned position</dt><dd>{policy.position.symbol} · {policy.position.exchange} · {policy.position.product} · quantity {policy.position.quantity}</dd></div>
    <div><dt>Completed entry orders</dt><dd>{policy.position.entry_order_ids.join(", ")}</dd></div>
    <div><dt>Protection bounds</dt><dd>Quantity {policy.max_quantity} · notional {policy.max_notional} (book units)</dd></div>
    <div><dt>Quote authority</dt><dd>{policy.read.selector} · expires {policy.read.valid_until} epoch seconds</dd></div>
    <div><dt>Quote limits</dt><dd>{policy.read.max_reads} reads · maximum age {policy.read.max_age_seconds} seconds</dd></div>
    <div><dt>Risk scope</dt><dd>{policy.risk_policy} · no hedge legs</dd></div>
  </dl>;
}
export function ProtectionPolicyPanel({ scope }: { scope: RunScope }) {
  const generation = useSyncExternalStore(subscribeRunPolicyAuthority, runPolicyAuthorityKey, runPolicyAuthorityKey);
  return <ScopedProtectionPolicyPanel key={JSON.stringify([generation, scope.run_id, scope.actor, scope.account, scope.environment])} scope={scope} />;
}
function ScopedProtectionPolicyPanel({ scope }: { scope: RunScope }) {
  const [snapshot, setSnapshot] = useState<ProtectionReadback | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [review, setReview] = useState<{ target: ProtectionReadback; policy?: ProtectionPolicy } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const owner = useRef<ReturnType<typeof createProtectionPolicyClient> | null>(null);
  const pending = useRef(false);
  const { run_id, actor, account, environment } = scope;
  useEffect(() => {
    const client = createProtectionPolicyClient({ run_id, actor, account, environment }); owner.current = client;
    void client.read().then(value => { if (owner.current === client) setSnapshot(value); }).catch(() => { if (owner.current === client) setError("Protection custody unavailable. Authority, exposure and duty are unknown, not absent."); });
    return () => { owner.current = null; client.dispose(); pending.current = false; setDraft({}); setSnapshot(null); setReview(null); setBusy(false); setNotice(""); setError(""); };
  }, [run_id, actor, account, environment]);
  async function run(work: (client: ReturnType<typeof createProtectionPolicyClient>) => Promise<ProtectionReadback>, mutation = false) {
    const client = owner.current; if (!client || pending.current) return;
    pending.current = true; setBusy(true); setError(""); setNotice("");
    try { const result = await work(client); if (owner.current === client) { setSnapshot(result); if (mutation) setNotice("Protection policy readback verified. This is not proof of execution or flatness."); } }
    catch (reason) { if (owner.current === client) { setSnapshot(null); setError(reason instanceof Error ? reason.message : "Protection unavailable"); } }
    finally { if (owner.current === client) { pending.current = false; setBusy(false); } }
  }
  return <section aria-label={`Protection policy ${run_id}`} className="space-y-3 min-w-0 border-t border-border-default pt-4">
    <h4 className="font-semibold">Bounded independent protection</h4>
    <p className="text-xs text-text-secondary">Only this run’s proved unhedged cash position. Native, netted and hedged duties remain unavailable. Attachment alone gives no independent restart protection. Never rearm entries, replay unknown orders or assume flatness from expiry/revocation.</p>
    {snapshot ? <>
      <p className="text-xs break-all">{snapshot.scope.actor} · {snapshot.scope.account} · {snapshot.scope.environment} · revision {snapshot.revision}</p>
      <p>Authority: {snapshot.authority_state} · Supervision: {snapshot.supervision}</p>
      <p>Duty: {snapshot.duty.state} · Remaining quantity: {snapshot.duty.remaining_quantity ?? "unknown"} · Reconciliation: {snapshot.duty.reconciliation_required ? "required" : "not reported required"}</p>
      <p className="text-xs">Active authority is not guaranteed execution. Unavailable supervision is not a running protector. Revocation never discards unresolved duty.</p>
      {snapshot.usage ? <p className="text-xs">Usage: {snapshot.usage.reads} quote reads · {snapshot.usage.quantity_used} quantity · {snapshot.usage.notional_used} notional</p> : <p className="text-xs">No issued-grant usage.</p>}
      {snapshot.duty.attempts.length ? <ul className="text-xs break-all">{snapshot.duty.attempts.map(attempt => <li key={attempt.id}>{attempt.id} · {attempt.state} · order {attempt.order_id ?? "unknown"}</li>)}</ul> : null}
      {snapshot.policy ? <details><summary>Current complete protection policy</summary><PolicySummary policy={snapshot.policy} /></details> : null}
      <fieldset disabled={busy} className="space-y-3"><legend className="text-sm font-medium">Explicit complete policy — no numeric defaults</legend>
        <p className="text-xs">Review exact canonical completed entry IDs, contract and original owned quantity. Read access is quote-only with its own selector, expiry, count and freshness bounds. Server rechecks ownership, credentials, risk and current revision.</p>
        <div className="grid gap-3 sm:grid-cols-2">{fields.map(([name, label, kind]) => <label key={name} className="text-sm min-w-0">{label}{name === "position.entry_order_ids" ? <textarea name={name} aria-label={label} autoComplete="off" className="w-full rounded border border-border-default bg-surface-card p-2 text-xs" value={draft[name] ?? ""} onChange={event => { setReview(null); setDraft(value => ({ ...value, [name]: event.target.value })); }} /> : <Input name={name} aria-label={label} autoComplete="off" type={kind ?? "text"} value={draft[name] ?? ""} onChange={event => { setReview(null); setDraft(value => ({ ...value, [name]: event.target.value })); }} />}</label>)}</div>
      </fieldset>
      <div className="flex flex-wrap gap-2"><Button variant="outline" disabled={busy} onClick={() => { setError(""); setReview(null); try { setReview({ target: structuredClone(snapshot), policy: proposal(draft) }); } catch (reason) { setError(reason instanceof Error ? reason.message : "Complete policy required"); } }}>Review protection policy</Button>
      <Button variant="outline" disabled={busy || !snapshot.policy} onClick={() => setReview({ target: structuredClone(snapshot) })}>Review protection revocation</Button></div>
    </> : <p role="status">Read exact protection custody before any policy approval.</p>}
    {review ? <div className="rounded border border-warning p-3 space-y-3"><p>Confirm only {run_id} on {account}, revision {review.target.revision}. {review.policy ? "This approves every displayed bound." : "This retires authority, not duty or exposure."}</p>{review.policy ? <PolicySummary policy={review.policy} /> : null}<Button disabled={busy} onClick={() => { const exact = review; setReview(null); void run(client => exact.policy ? client.approve(exact.target, exact.policy) : client.revoke(exact.target), true); }}>{review.policy ? "Approve exact protection policy" : "Confirm protection revocation"}</Button><Button variant="outline" disabled={busy} onClick={() => setReview(null)}>Cancel protection review</Button></div> : null}
    <Button variant="outline" disabled={busy} onClick={() => { setReview(null); void run(client => client.read()); }}>Read exact protection</Button>
    {busy ? <p role="status">Protection request pending. Do not resend.</p> : null}{notice ? <p role="status">{notice}</p> : null}{error ? <p role="alert" className="text-sm text-warning">{error}</p> : null}
  </section>;
}
