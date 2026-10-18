import { useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Timeline, deliveryLabels, incidentAction, submitBrowserIncident } from '@/services/systemIncidents';
import { useAuthStore } from '@/stores/authStore';
import { useModeStore } from '@/stores/modeStore';
import { IncidentChannelSettings } from './IncidentChannelSettings';

export function IncidentTimelinePanel({ value, current, refresh }: { value: unknown; current:boolean; refresh:()=>unknown }) {
  const parsed = useMemo(() => Timeline.safeParse(value), [value]);
  const attempted = useRef(new Set<string>());
  const authenticated = useAuthStore(s => s.status === 'logged-in');
  const mode = useModeStore(s => s.mode);
  const [error, setError] = useState<string|null>(null);
  const refreshRef = useRef(refresh); refreshRef.current = refresh;
  useEffect(() => {
    if (!parsed.success || !current || !authenticated || mode === 'explore') return;
    const controller = new AbortController();
    const pending = parsed.data.incidents.flatMap(i=>i.deliveries).filter(r=>r.channel==='desktop' && r.state==='browser_pending' && !attempted.current.has(`${r.id}:${r.attempts}`));
    if (pending.length === 0) return;
    void (async () => {
      for (const receipt of pending) {
        if (controller.signal.aborted) break;
        attempted.current.add(`${receipt.id}:${receipt.attempts}`);
        try { await submitBrowserIncident(receipt, controller.signal); }
        catch { if (!controller.signal.aborted) setError('Desktop delivery or receipt unavailable. No automatic resend.'); }
      }
      if (!controller.signal.aborted) void refreshRef.current();
    })();
    return () => controller.abort();
  }, [parsed, current, authenticated, mode]);
  if (!parsed.success) return <section aria-label="Incident timeline"><h3>Incident timeline</h3><p>Durable timeline unavailable. No delivery success can be inferred.</p></section>;
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
  return <section aria-label="Incident timeline" className="space-y-3 rounded border border-border-default p-3">
    <h3 className="font-medium">Incident timeline</h3>
    <p className="text-sm">Kept until manual deletion. Operational records only; trading journals and learning history are unchanged.</p>
    <p className="text-sm">Submission is not proof that you saw an alert. Telegram and email require explicit configured opt-in. No automatic repair or restart.</p>
    <Button type="button" onClick={()=>void permission()} disabled={!authenticated || mode==='explore'}>Allow browser desktop alerts</Button>
    {authenticated && mode!=='explore' ? <IncidentChannelSettings /> : null}
    {error ? <p role="status">{error}</p> : null}
    {!current ? <p role="status">Stale observation — desktop dispatch paused.</p> : null}
    {parsed.data.incidents.length === 0 ? <p>No retained incidents in this page.</p> : parsed.data.incidents.map(incident=><article key={incident.id} className="space-y-2 border-t border-border-default pt-3" aria-label={`${incident.severity} incident`}>
      <h4>{incident.severity === 'critical' ? 'Critical incident' : 'Warning incident'} · {incident.code.replaceAll('_',' ')}</h4>
      <p>Source: {incident.source} · <time>{incident.observed_at}</time> · {incident.freshness}</p>
      {incident.producer ? <p>Producer: {incident.producer.kind}</p> : null}
      <p className="break-all">Correlation: {incident.correlation_id}</p>
      <p>Root cause: {incident.root_cause.state}</p>
      <ul>{incident.deliveries.map(receipt=><li key={receipt.id} className="flex flex-wrap gap-2"><span>{receipt.channel}:</span><span>{deliveryLabels[receipt.state]}</span>
        {current && receipt.state==='failed' && receipt.attempts<3 ? <Button onClick={()=>void act(receipt.id,'retry')}>Retry {receipt.channel}</Button>:null}
        {current && ['pending','browser_pending','failed','backpressure'].includes(receipt.state) ? <Button onClick={()=>void act(receipt.id,'cancel')}>Cancel {receipt.channel}</Button>:null}
      </li>)}</ul>
    </article>)}
    {parsed.data.has_more ? <p>Older incidents are retained; use the bounded incident API cursor to read earlier pages.</p> : null}
  </section>;
}
