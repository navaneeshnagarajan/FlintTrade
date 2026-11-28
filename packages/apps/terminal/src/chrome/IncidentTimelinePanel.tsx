import { useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Timeline, browserIncidentQueue, deliveryLabels, incidentAction } from '@/services/systemIncidents';
import { useAuthStore } from '@/stores/authStore';
import { useModeStore } from '@/stores/modeStore';
import { IncidentChannelSettings } from './IncidentChannelSettings';

export function IncidentTimelinePanel({ value, current, refresh }: { value: unknown; current:boolean; refresh:()=>unknown }) {
  const parsed = useMemo(() => Timeline.safeParse(value), [value]);
  const authenticated = useAuthStore(s => s.status === 'logged-in');
  const mode = useModeStore(s => s.mode);
  const client = useQueryClient();
  const [error, setError] = useState<string|null>(null);
  const refreshRef = useRef(refresh); refreshRef.current = refresh;
  useEffect(() => {
    if (!parsed.success || !current || !authenticated || mode === 'explore') return;
    let visible = true;
    const queue = browserIncidentQueue(client);
    const pending = queue.discover(parsed.data, true);
    const refreshIfNeeded = () => {
      if (!visible) return;
      if (queue.takeRefresh().needed) void refreshRef.current();
    };
    if (pending) void pending.then(refreshIfNeeded);
    else refreshIfNeeded();
    return () => { visible = false; };
  }, [parsed, current, authenticated, mode, client]);
  if (!parsed.success) return <section aria-label="Incident timeline" className="space-y-2 rounded-lg border border-border-default bg-surface-card p-4"><h3 className="ft-text-card-title text-text-primary">Incident timeline</h3><p className="text-sm text-text-secondary">Durable timeline unavailable. No delivery success can be inferred.</p></section>;
  async function act(id:string, action:'retry'|'cancel') {
    setError(null);
    try { await incidentAction(id,action,new AbortController().signal); void refreshRef.current(); }
    catch { setError('Delivery action refused or its receipt is unknown. Refresh before another action.'); }
  }
  async function permission() {
    if (typeof Notification === 'undefined') { setError('Browser desktop notifications are unsupported.'); return; }
    try { const result = await Notification.requestPermission(); setError(result==='granted' ? 'Permission granted. Explicitly retry any failed browser receipt.' : 'Desktop permission not granted.'); }
    catch { setError('Desktop permission unavailable.'); }
  }
  return <section aria-label="Incident timeline" className="min-w-0 space-y-3 rounded-lg border border-border-default bg-surface-card p-4">
    <h3 className="ft-text-card-title text-text-primary">Incident timeline</h3>
    <p className="text-sm text-text-secondary">Kept until manual deletion. Operational records only; trading journals and learning history are unchanged.</p>
    <p className="text-sm text-text-secondary">Submission is not proof that you saw an alert. Telegram and email require explicit configured opt-in. No automatic repair or restart.</p>
    <Button type="button" size="sm" variant="outline" onClick={()=>void permission()} disabled={!authenticated || mode==='explore'}>Allow browser desktop alerts</Button>
    {authenticated && mode!=='explore' ? <IncidentChannelSettings /> : null}
    {error ? <p role="status" className="text-xs text-text-secondary">{error}</p> : null}
    {!current ? <p role="status" className="text-xs text-[var(--color-warning-text,var(--color-warning))]">Stale observation — desktop dispatch paused.</p> : null}
    {parsed.data.incidents.length === 0 ? <p className="text-sm text-text-muted">No retained incidents in this page.</p> : parsed.data.incidents.map(incident=><article key={incident.id} className="space-y-1.5 border-t border-border-default pt-3 text-xs text-text-secondary" aria-label={`${incident.severity} incident`}>
      <h4 className={`text-sm font-medium ${incident.severity === 'critical' ? 'text-[var(--color-bearish-text,var(--color-loss))]' : 'text-text-primary'}`}>{incident.severity === 'critical' ? 'Critical incident' : 'Warning incident'} · {incident.code.replaceAll('_',' ')}</h4>
      <p>Source: {incident.source} · <time>{incident.observed_at}</time> · {incident.freshness}</p>
      {incident.producer ? <p>Producer: {incident.producer.kind}</p> : null}
      <p className="break-all font-mono">Correlation: {incident.correlation_id}</p>
      <p>Root cause: {incident.root_cause.state}</p>
      <ul className="space-y-1">{incident.deliveries.map(receipt=><li key={receipt.id} className="flex flex-wrap items-center gap-2"><span className="font-medium text-text-primary">{receipt.channel}:</span><span>{deliveryLabels[receipt.state]}</span>
        {current && receipt.state==='failed' && receipt.attempts<3 ? <Button size="xs" variant="outline" onClick={()=>void act(receipt.id,'retry')}>Retry {receipt.channel}</Button>:null}
        {current && ['pending','browser_pending','failed','backpressure'].includes(receipt.state) ? <Button size="xs" variant="ghost" onClick={()=>void act(receipt.id,'cancel')}>Cancel {receipt.channel}</Button>:null}
      </li>)}</ul>
    </article>)}
    {parsed.data.has_more ? <p className="text-xs text-text-muted">Older incidents are retained; use the bounded incident API cursor to read earlier pages.</p> : null}
  </section>;
}
