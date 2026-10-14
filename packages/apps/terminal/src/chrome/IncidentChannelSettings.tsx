import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { configureIncidentChannel } from '@/services/systemIncidents';
import { captureAuthSessionFence, isAuthSessionFenceCurrent, useAuthStore } from '@/stores/authStore';

export function IncidentChannelSettings() {
  const [channel,setChannel]=useState<'telegram'|'email'>('telegram');
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState('');
  const recipient=useRef<HTMLInputElement|null>(null);
  const confirmation=useRef<HTMLInputElement|null>(null);
  const token=useAuthStore(s=>s.token);
  const lifetime=useRef(0);
  useEffect(()=>{
    const owner = lifetime;
    owner.current++;
    if(recipient.current) recipient.current.value='';
    if(confirmation.current) confirmation.current.checked=false;
    setMessage(''); setBusy(false);
    return ()=>{ owner.current++; };
  },[token]);
  async function change(enabled:boolean) {
    if(enabled && (!confirmation.current?.checked || !recipient.current?.value)) { setMessage('Confirm the exact recipient and opt in first.'); return; }
    const selected=channel, generation=lifetime.current, fence=captureAuthSessionFence();
    const target=recipient.current?.value || '';
    if(recipient.current) recipient.current.value='';
    if(confirmation.current) confirmation.current.checked=false;
    setBusy(true); setMessage('');
    try {
      await configureIncidentChannel(selected,enabled,target);
      if(generation===lifetime.current && isAuthSessionFenceCurrent(fence)) setMessage(enabled ? 'Channel enabled — exact binding readback verified.' : 'Channel disabled — readback verified. In-flight sends cannot be recalled.');
    } catch { if(generation===lifetime.current && isAuthSessionFenceCurrent(fence)) setMessage('Channel change refused or unverified. No automatic resend; recheck configuration before trying again.'); }
    finally { if(generation===lifetime.current && isAuthSessionFenceCurrent(fence)) setBusy(false); }
  }
  return <fieldset className="space-y-2 border-t border-border-default pt-3" disabled={busy}>
    <legend>Optional critical incident delivery</legend>
    <p>Uses existing configured Telegram or SMTP service credentials. No provider fallback. Restart requires explicit rebinding; disabled receipts are not replayed.</p>
    <label>Alert channel <select value={channel} onChange={event=>{setChannel(event.target.value as 'telegram'|'email');setMessage('');if(recipient.current)recipient.current.value='';if(confirmation.current)confirmation.current.checked=false;}}><option value="telegram">Telegram</option><option value="email">Email (SMTP)</option></select></label>
    <label>Configured alert recipient <Input autoComplete="off" maxLength={254} ref={node=>{recipient.current=node;return()=>{if(node)node.value='';};}} /></label>
    <label><Input type="checkbox" className="inline-block h-4 w-4" ref={confirmation} /> Allow this channel to receive critical incident notices</label>
    <div className="flex flex-wrap gap-3"><Button type="button" onClick={()=>void change(true)}>Enable selected channel</Button><Button type="button" onClick={()=>void change(false)}>Disable selected channel</Button></div>
    {message ? <p role="status">{message}</p>:null}
  </fieldset>;
}
