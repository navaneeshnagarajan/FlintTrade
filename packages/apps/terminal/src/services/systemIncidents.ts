import { z } from 'zod';
import { buildHeaders, getBase } from './ftApi.helpers';
import { captureAuthSessionFence, isAuthSessionFenceCurrent } from '@/stores/authStore';

export const Delivery = z.object({
  id: z.uuid(), channel: z.enum(['desktop', 'telegram', 'email']),
  state: z.enum(['pending', 'browser_pending', 'sending', 'submitted_unobserved', 'unknown', 'failed', 'disabled', 'cancelled', 'revoked', 'backpressure']),
  attempts: z.number().int().min(0).max(3), updated_at: z.string(),
});
export const Timeline = z.object({
  status: z.literal('available'), durable: z.literal(true), retention: z.literal('until_manual_deletion'),
  incidents: z.array(z.object({
    id: z.uuid(), correlation_id: z.string().max(64), observed_at: z.string(),
    source: z.enum(['core_http', 'core_log', 'history_job', 'model_task']), scope: z.literal('core_process'),
    severity: z.enum(['critical','warning']), code: z.enum(['http_failure', 'application_failure', 'history_job_failure', 'model_task_failure']),
    freshness: z.literal('observed'), measurement: z.record(z.string(),z.unknown()),
    root_cause: z.object({ state:z.enum(['unknown','suspected','confirmed']), code:z.string().nullable() }),
    producer: z.object({ kind: z.enum(['historify_job_manager', 'service_usage_ledger']), reference: z.uuid() }).optional(),
    deliveries: z.array(Delivery).max(3),
  })).max(100), has_more:z.boolean(), next_cursor:z.number().int().positive().nullable(),
});
export type IncidentTimeline = z.infer<typeof Timeline>;
export type DeliveryReceipt = z.infer<typeof Delivery>;

export const deliveryLabels: Record<DeliveryReceipt['state'], string> = {
  pending:'Pending', browser_pending:'Browser permission / consumer pending', sending:'Attempt started; outcome pending',
  submitted_unobserved:'Submitted; user delivery unobserved', unknown:'Unknown outcome — not retried',
  failed:'Failed — explicit retry required', disabled:'Disabled — explicit opt-in required', cancelled:'Cancelled before send',
  revoked:'Binding revoked — not sent', backpressure:'Delivery paused by backpressure — incident retained',
};

export async function submitBrowserIncident(receipt: DeliveryReceipt, signal: AbortSignal): Promise<void> {
  signal = AbortSignal.any([signal, AbortSignal.timeout(10_000)]);
  const fence = captureAuthSessionFence();
  const headers = buildHeaders(false);
  const current = () => !signal.aborted && isAuthSessionFenceCurrent(fence);
  const base = `${getBase()}/api/v1/system/incidents/deliveries/${receipt.id}`;
  if (!current() || receipt.state !== 'browser_pending') return;
  const response = await fetch(`${base}/claim`, {method:'POST',headers,signal,cache:'no-store'});
  if (response.status === 409) return; // Another consumer already owns this exact attempt.
  if (!response.ok) throw new Error('Desktop claim unavailable; no notification sent');
  const claim = z.object({id:z.literal(receipt.id),claim:z.uuid(),state:z.literal('sending')}).parse(await response.json());
  if (!current()) return; // Server keeps an uncertain claim; never revive it.
  let state: 'failed' | 'unknown' | 'submitted_unobserved' = 'failed';
  if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
    try {
      new Notification('FlintTrade critical incident', {body:'Open System for retained evidence. Root cause unconfirmed.',tag:receipt.id});
      state = 'submitted_unobserved'; // A constructor is not observed user delivery.
    } catch { state = 'unknown'; }
  }
  if (!current()) return;
  const result = await fetch(`${base}/receipt`, {method:'POST',headers:{...headers,'Content-Type':'application/json'},
    body:JSON.stringify({claim:claim.claim,state}),signal,cache:'no-store'});
  if (!result.ok) throw new Error('Desktop receipt unknown; notification will not be resent');
  const readback = Delivery.parse(await result.json());
  if (readback.id !== receipt.id || readback.state !== state) throw new Error('Desktop receipt mismatch; do not resend');
}

const Channel = z.object({channel:z.enum(['telegram','email']),enabled:z.boolean(),binding:z.string().regex(/^[a-f0-9]{64}$/).nullable(),restart:z.literal('explicit_rebind_required'),in_flight:z.literal('not_recalled')});
export async function configureIncidentChannel(channel:'telegram'|'email', enabled:boolean, recipient:string) {
  const signal = AbortSignal.timeout(10_000);
  const fence=captureAuthSessionFence();
  const url=`${getBase()}/api/v1/system/incidents/channels/${channel}`;
  const headers=buildHeaders(false);
  const response=await fetch(url,{method:'PUT',headers:{...headers,'Content-Type':'application/json'},cache:'no-store',signal,
    body:JSON.stringify(enabled ? {enabled:true,recipient,provider:channel==='email'?'smtp':'telegram'} : {enabled:false})});
  if(!response.ok) throw new Error('Channel change refused or outcome unknown');
  const ack=Channel.parse(await response.json());
  if(!isAuthSessionFenceCurrent(fence) || ack.channel!==channel || ack.enabled!==enabled || (enabled && !ack.binding)) throw new Error('Channel acknowledgement unavailable or retired');
  const read=await fetch(url,{method:'GET',headers,cache:'no-store',signal});
  if(!read.ok) throw new Error('Channel readback unavailable');
  const actual=Channel.extend({effective:z.boolean()}).parse(await read.json());
  if(!isAuthSessionFenceCurrent(fence) || actual.channel!==channel || actual.enabled!==enabled || actual.binding!==ack.binding || actual.effective!==enabled) throw new Error('Channel readback changed or is not bound');
  return actual;
}

export async function incidentAction(id: string, action: 'retry'|'cancel', signal: AbortSignal) {
  signal = AbortSignal.any([signal, AbortSignal.timeout(10_000)]);
  z.uuid().parse(id);
  const fence = captureAuthSessionFence();
  const response = await fetch(`${getBase()}/api/v1/system/incidents/deliveries/${id}/${action}`, {
    method:'POST',headers:buildHeaders(false),signal,cache:'no-store',
  });
  if (!response.ok) throw new Error('Delivery action refused or unavailable');
  const value = Delivery.parse(await response.json());
  if (!isAuthSessionFenceCurrent(fence) || signal.aborted || value.id !== id) throw new Error('Delivery receipt belongs to a retired session');
  return value;
}
