import { useSystemDiagnostics } from "@/hooks/useSystemDiagnostics";
import { Button } from "@/components/ui/button";
import { IncidentTimelinePanel } from './IncidentTimelinePanel';
function Evidence({ value }: { value: unknown }) {
  if (value == null) return <span className="text-text-muted">Not measured / unavailable</span>;
  if (typeof value !== "object") return <span className="break-all font-mono text-xs">{String(value)}</span>;
  return <dl className="space-y-2">{Object.entries(value).map(([key, child]) => <div key={key} className="grid grid-cols-[minmax(8rem,1fr)_2fr] gap-3 border-b border-border-default/40 py-1"><dt className="break-all text-xs text-text-secondary">{key.replaceAll("_", " ")}</dt><dd className="min-w-0"><Evidence value={child} /></dd></div>)}</dl>;
}
export function SystemDiagnostics() {
  const query = useSystemDiagnostics();
  const data = query.data;
  return <section className="space-y-4 p-4"><header className="flex flex-wrap items-start justify-between gap-2"><div><h2 className="text-lg font-semibold">Core diagnostics</h2><p className="text-sm text-text-secondary">Passive core observations. Host bytes are not DNS/TLS/internet tests; missing values never imply healthy or zero.</p></div><Button size="sm" variant="outline" disabled={query.fetchStatus === "fetching"} onClick={() => void query.refetch()}>Refresh diagnostics</Button></header>
    {query.error && <p role="alert" className="text-warning">{query.error.message}</p>}
    {!data ? <p role="status">{query.fetchStatus === "fetching" ? "Reading diagnostics…" : "Diagnostics unavailable. Use an authenticated installed session; public Sandbox has no host measurements."}</p> : <>
      <p className="text-xs">Source: {data.scope} · Observed <time>{data.observed_at}</time>{query.isError ? " · Stale: refresh failed" : ""}</p>
      <IncidentTimelinePanel value={data.operational_events} current={!query.isStale && !query.isError && query.fetchStatus !== 'paused'} refresh={query.refetch} />
      <div className="grid gap-4 xl:grid-cols-2">{([['resources', 'Resources'], ['acquisition', 'Data acquisition'], ['models', 'Models'], ['jobs', 'Jobs'], ['network_diagnosis', 'Network diagnosis'], ['operational_events', 'Operational events'], ['recovery', 'Recovery authority']] as const).map(([key, label]) => <section aria-label={label} key={key} className="rounded border border-border-default p-3"><h3 className="mb-3 font-medium">{label}</h3><Evidence value={data[key]} /></section>)}</div>
    </>}
  </section>;
}
