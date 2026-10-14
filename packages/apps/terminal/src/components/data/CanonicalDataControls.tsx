import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CanonicalDataClient, canonicalDataAvailable, canonicalError, useCanonicalDataOnline, useCanonicalScopeKey, type Dataset, type DatasetLease, type HistoryManifest } from "@/services/canonicalData";

export function CanonicalDataControls() {
  const scopeKey = useCanonicalScopeKey();
  return <section aria-label="Canonical datasets and leases" className="min-w-0 space-y-3 rounded border border-border-default p-3 text-sm">
    <h2 className="font-semibold">Canonical datasets and leases</h2>
    <p>Only server-qualified, explicitly selected datasets. Recorded history is not a live feed. Acquiring data never changes the execution account, trading mode or provider.</p>
    {canonicalDataAvailable() ? <DataSession key={scopeKey} scopeKey={scopeKey} /> : <p>Installed operator session required. Data controls are unavailable in the public preview.</p>}
  </section>;
}
function DataSession({ scopeKey }: { scopeKey: number }) {
  const online = useCanonicalDataOnline();
  const [view, setView] = useState<{ client: CanonicalDataClient; generation: number } | null>(null);
  const [cleanupAttempt, setCleanupAttempt] = useState(0);
  const [unresolved, setUnresolved] = useState<string[]>([]);
  const lifetime = useRef<{ client: CanonicalDataClient; retirement?: ReturnType<CanonicalDataClient["dispose"]> } | null>(null);
  // Effects, not retained component state, own a transport lifetime. StrictMode
  // and Activity both disconnect effects without discarding that state.
  useEffect(() => {
    if (!online) return;
    let active = true;
    let owned: typeof lifetime.current = null;
    const open = () => {
      if (!active) return;
      const client = new CanonicalDataClient();
      owned = { client };
      lifetime.current = owned;
      setView(previous => ({ client, generation: (previous?.generation ?? 0) + 1 }));
    };
    const previous = lifetime.current;
    if (previous?.retirement) void previous.retirement.then(() => {
      if (!active) return;
      const handles = previous.client.pendingLeaseIds();
      if (handles.length) setUnresolved(handles);
      else open();
    });
    else open();
    return () => { active = false; if (owned) owned.retirement = owned.client.dispose(); };
  }, [cleanupAttempt, online]);
  const available = online && !unresolved.length && !!view?.client.current();
  return <>
    {!online ? <p role="status">Offline. Data controls are retired; cleanup is not confirmed until exact readback.</p> : unresolved.length ? <>
    <p role="alert" className="break-all">Retired lease ownership is unresolved: {unresolved.join(", ")}. New acquisition is blocked; no cleanup success is inferred.</p>
    <Button size="sm" onClick={() => {
      if (!lifetime.current) return;
      lifetime.current.retirement = lifetime.current.client.dispose();
      setUnresolved([]);
      setCleanupAttempt(attempt => attempt + 1);
    }}>Retry exact retired-lease cleanup</Button>
    </> : !available ? <p role="status">Retiring the previous data view before opening a fresh one…</p> : null}
    {/* The scope-keyed session owns drafts; only transports have generations.
        Retain the actual inner view/input while exact retirement is pending. */}
    {view ? <DataView scopeKey={scopeKey} client={view.client} generation={view.generation} available={available} /> : null}
  </>;
}
function DataView({ scopeKey, client, generation, available }: { scopeKey: number; client: CanonicalDataClient; generation: number; available: boolean }) {
  const catalogue = useQuery({ queryKey: ["canonical-data", "datasets", scopeKey, generation], queryFn: () => client.datasets(), enabled: available, gcTime: 0, retry: false });
  const [leaseState, setLease] = useState<(DatasetLease & { viewRevision: number }) | null>(null);
  const lease = leaseState?.viewRevision === client.viewRevision() && client.pendingLeaseIds().includes(leaseState.lease_id) ? leaseState : null;
  const [busyRevision, setBusy] = useState<number | null>(null);
  const busy = busyRevision === client.viewRevision();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [snapshotId, setSnapshotId] = useState("");
  const [manifest, setManifest] = useState<HistoryManifest | null>(null);
  const [receiptOwner, setReceiptOwner] = useState(client);
  // Clear transport-bound presentation BEFORE committing the new generation.
  // Revisions are client-local (both fresh clients start at zero), not identity.
  // The only retained draft is nonsecret snapshotId; the outer scope key still
  // discards this entire component for account/session/backend/mode retirement.
  if (receiptOwner !== client) {
    setReceiptOwner(client);
    setLease(null); setBusy(null); setError(""); setNotice(""); setManifest(null);
  }
  const cache = useQueryClient();
  const mounted = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  async function run(action: () => Promise<void>) {
    if (!available || busy) return;
    const revision = client.viewRevision();
    setBusy(revision); setError(""); setNotice("");
    try { await action(); }
    catch (failure) { if (mounted.current && client.current() && revision === client.viewRevision()) setError(canonicalError(failure)); }
    finally { if (mounted.current && client.current() && revision === client.viewRevision()) setBusy(null); }
  }
  async function acquire(dataset: Dataset) {
    if (!catalogue.data || catalogue.error || lease) return;
    const result = await client.acquire(dataset, catalogue.data.scope);
    if (mounted.current && client.current()) setLease({ ...result, viewRevision: client.viewRevision() });
  }
  async function readLease(full = false) {
    if (!lease) return;
    const result = await client.readLease(lease, full ? undefined : lease.snapshot.sequence ?? undefined);
    if (mounted.current && client.current()) setLease({ ...result, viewRevision: client.viewRevision() });
  }
  async function inspect() {
    if (!catalogue.data || catalogue.error) return;
    setManifest(null);
    const dataset = catalogue.data.datasets.find(item => item.source_kind === "recorded_history" && item.snapshot_id === snapshotId);
    const result = await cache.fetchQuery({ queryKey: ["canonical-data", "manifest", scopeKey, generation, snapshotId], queryFn: () => client.history(snapshotId, catalogue.data.scope, dataset), gcTime: 0, retry: false });
    if (mounted.current && client.current()) setManifest(result);
  }
  async function release(id = lease?.lease_id) {
    if (!id) return;
    const revision = client.viewRevision();
    const released = await client.release(id);
    if (mounted.current && client.current() && revision === client.viewRevision()) {
      setLease(null);
      setNotice(released ? "Release confirmed by exact readback." : "Lease already absent or retired; release was not confirmed. Reacquire explicitly if needed.");
    }
  }
  return <>
    {available ? <>
    <Button size="sm" variant="outline" disabled={busy || catalogue.isFetching || !!lease} onClick={() => void catalogue.refetch()}>Read dataset catalogue</Button>
    {catalogue.isPending ? <p role="status">Reading dataset catalogue…</p> : null}
    {catalogue.error ? <p role="alert">{canonicalError(catalogue.error)}</p> : null}
    {error ? <p role="alert">{error} No mutation success is inferred from a timeout.</p> : null}
    {busy ? <p role="status">Checking exact data receipt…</p> : null}
    {notice ? <p role="status">{notice}</p> : null}
    {catalogue.data && !catalogue.error ? <>
      <p className="break-all">Server data scope: {JSON.stringify(catalogue.data.scope)}</p>
      <p>Legacy history: {catalogue.data.legacy_history}</p>
      {!catalogue.data.datasets.length ? <p>No qualified datasets available in this server catalogue. This does not establish an empty account or complete history.</p> : null}
      <ul className="max-h-64 space-y-2 overflow-auto">{catalogue.data.datasets.map(dataset => <li key={dataset.dataset_id} className="space-y-1 border-t border-border-default pt-2">
        <p className="break-all">{dataset.dataset_id} · {dataset.label} · {dataset.status}</p>
        {dataset.source_kind === "native" ? <p>{dataset.reason}</p> : <p>{dataset.identity.instrument_id} · {dataset.identity.venue} · {dataset.identity.currency} · Coverage: {dataset.coverage.observed}/{dataset.coverage.expected}</p>}
        <Button size="sm" variant="outline" className="max-w-full whitespace-normal break-all" disabled={busy || !!lease || client.pendingLeaseIds().length > 0 || dataset.status === "unavailable"} onClick={() => void run(() => acquire(dataset))}>Acquire {dataset.dataset_id}</Button>
      </li>)}</ul>
    </> : null}
    </> : null}
    <form className="space-y-2" onSubmit={event => { event.preventDefault(); void run(inspect); }}>
      <label className="block">Immutable history snapshot ID<Input value={snapshotId} disabled={!available || busy} onChange={event => { setSnapshotId(event.target.value); setManifest(null); }} autoComplete="off" /></label>
      <Button type="submit" size="sm" variant="outline" disabled={!available || busy || !catalogue.data || !!catalogue.error || !snapshotId}>Inspect exact manifest</Button>
    </form>
    {available ? <>
    {manifest ? <div className="space-y-2">
      <p className="break-all">Manifest readback: {manifest.snapshot_id}</p>
      <p>Manifest status: {manifest.status} · Coverage: {manifest.coverage.observed}/{manifest.coverage.expected} · Rights: {manifest.rights}</p>
      <p>Server integrity-checked immutable evidence, not a verified valuation or permission to trade. Missing coverage is not filled.</p>
      <pre aria-label="Exact immutable manifest" className="max-h-80 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(manifest, null, 2)}</pre>
    </div> : null}
    {!lease ? client.pendingLeaseIds().map(id => <div key={id} className="space-y-2"><p className="break-all">Unconfirmed lease: {id}. Ownership is unresolved; new acquisition is blocked.</p><Button size="sm" disabled={busy} onClick={() => void run(() => release(id))}>Release unconfirmed lease {id}</Button></div>) : null}
    <p className="text-xs">Closing or retiring this view attempts exact-lease release using the original session. A failed or lost receipt is not confirmed cleanup; core expiry and shutdown must retire unresolved resources. No automatic re-acquisition.</p>
    {lease ? <div className="space-y-2 rounded border border-border-default p-2">
      <p className="break-all">Lease: {lease.lease_id} · Dataset: {lease.snapshot.dataset_id}</p>
      <p>Freshness: {lease.snapshot.status} (server at last read) · Reason: {lease.snapshot.reason || "none reported"} · Age seconds: {lease.snapshot.age_seconds ?? "unavailable"}</p>
      <p>Sequence: {lease.snapshot.sequence ?? "unavailable"} · Replay gap: {String(lease.snapshot.replay_gap)} · Lease expiry (Unix seconds): {lease.snapshot.expires_at}</p>
      <p>Observed: {lease.snapshot.observed_at ?? "unavailable"} · Published: {lease.snapshot.published_at ?? "unavailable"} · Retrieved: {lease.snapshot.retrieved_at ?? "unavailable"}</p>
      <details><summary>Exact source, identity and observation</summary><pre className="max-h-72 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify(lease.snapshot, null, 2)}</pre></details>
      {lease.snapshot.replay_gap ? <p role="alert">Replay gap detected. Updates are incomplete; read a full snapshot explicitly. No provider fallback was attempted.</p> : null}
      <p>Not continuously refreshed. Expiry may have passed; read again before use.</p>
      <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busy || lease.snapshot.replay_gap} onClick={() => void run(() => readLease())}>Read lease updates</Button><Button size="sm" variant="outline" disabled={busy} onClick={() => void run(() => readLease(true))}>Read full snapshot</Button><Button size="sm" variant="outline" disabled={busy} onClick={() => void run(() => release())}>Release exact lease</Button></div>
    </div> : null}
    </> : null}
  </>;
}
