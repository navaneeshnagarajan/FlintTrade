import { useSystemDiagnostics } from "@/hooks/useSystemDiagnostics";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { IncidentTimelinePanel } from './IncidentTimelinePanel';
function Evidence({ value }: { value: unknown }) {
  if (value == null) return <span className="text-xs text-text-muted">Not measured / unavailable</span>;
  if (typeof value !== "object") return <span className="break-all font-mono text-xs text-text-primary">{String(value)}</span>;
  return <dl className="min-w-0">{Object.entries(value).map(([key, child]) => <div key={key} className="grid grid-cols-[minmax(7rem,1fr)_2fr] gap-3 border-b border-border-default/40 py-1.5 last:border-b-0"><dt className="break-words text-xs text-text-secondary first-letter:uppercase">{key.replaceAll("_", " ")}</dt><dd className="min-w-0"><Evidence value={child} /></dd></div>)}</dl>;
}
export function SystemDiagnostics() {
  const query = useSystemDiagnostics();
  const data = query.data;
  return <section className="mx-auto w-full max-w-[var(--ft-page-width-wide)] space-y-4 px-[var(--ft-page-gutter)] py-5"><header className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><h2 className="ft-text-section-title text-text-primary">Core diagnostics</h2><p className="mt-1 max-w-3xl text-sm text-text-secondary">Passive core observations. Host bytes are not DNS/TLS/internet tests; missing values never imply healthy or zero.</p></div><Button size="sm" variant="outline" disabled={query.fetchStatus === "fetching"} onClick={() => void query.refetch()}><RefreshCw aria-hidden="true" className={query.fetchStatus === "fetching" ? "animate-spin" : undefined} />Refresh diagnostics</Button></header>
    {query.error && <p role="alert" className="rounded-lg border border-warning/30 bg-warning/[0.08] px-3.5 py-2.5 text-sm text-[var(--color-warning-text,var(--color-warning))]">{query.error.message}</p>}
    {!data ? <p role="status" className="rounded-lg border border-border-default bg-surface-card px-3.5 py-6 text-center text-sm text-text-secondary">{query.fetchStatus === "fetching" ? "Reading diagnostics…" : "Diagnostics unavailable. Use an authenticated installed session; public preview has no host measurements."}</p> : <>
      <p className="text-xs text-text-muted">Source: {data.scope} · Observed <time>{data.observed_at}</time>{query.isError ? " · Stale: refresh failed" : ""}</p>
      <IncidentTimelinePanel value={data.operational_events} current={!query.isStale && !query.isError && query.fetchStatus !== 'paused'} refresh={query.refetch} />
      <div className="grid gap-4 xl:grid-cols-2">{([['resources', 'Resources'], ['acquisition', 'Data acquisition'], ['models', 'Models'], ['jobs', 'Jobs'], ['network_diagnosis', 'Network diagnosis'], ['operational_events', 'Operational events'], ['recovery', 'Recovery authority']] as const).map(([key, label]) => <section aria-label={label} key={key} className="min-w-0 rounded-lg border border-border-default bg-surface-card p-4"><h3 className="ft-text-card-title mb-2 text-text-primary">{label}</h3><Evidence value={data[key]} /></section>)}</div>
    </>}
  </section>;
}
