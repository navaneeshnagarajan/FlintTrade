// Test source: GNU AGPL v3, as licensed in the repository LICENSE.
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';
import { SystemDiagnostics } from '@/chrome/SystemDiagnostics';
import { useAuthStore } from '@/stores/authStore';
import { useModeStore } from '@/stores/modeStore';

const id = '44444444-4444-4444-8444-444444444444';
const claim = '55555555-5555-4555-8555-555555555555';
const instant = '2026-10-12T00:00:00Z';
const incident = { id:'66666666-6666-4666-8666-666666666666', correlation_id:'77777777.7777.4777.8777.777777777777', observed_at:instant, source:'core_http', scope:'core_process', severity:'critical', code:'http_failure', freshness:'observed', measurement:{state:'measured',duration_ms:12,status_code:503}, root_cause:{state:'unknown',code:null} };
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it('shows durable critical evidence and records browser submission without claiming user delivery', async () => {
  useAuthStore.setState({ status:'logged-in', token:'inert-incident' });
  useModeStore.setState({ mode:'live' });
  let state = 'browser_pending';
  const unexpected: string[] = []; const calls: string[] = []; const shown: unknown[] = [];
  class Notification { static permission = 'granted'; constructor(...args: unknown[]) { shown.push(args); } }
  vi.stubGlobal('Notification', Notification);
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit) => {
    const key = `${init.method} ${input}`; calls.push(key);
    if (key === 'GET /ft-api/api/v1/system/diagnostics') return new Response(JSON.stringify({status:'success',data:{schema_version:1,observed_at:instant,scope:'core_process',resources:{},acquisition:{},models:{capacity:null},jobs:{active:null},network_diagnosis:{cause:null},recovery:{restart_performed:false},operational_events:{status:'available',durable:true,retention:'until_manual_deletion',incidents:[{...incident,deliveries:[{id,channel:'desktop',state,attempts:state==='browser_pending'?0:1,updated_at:instant}]}],has_more:false,next_cursor:null}}}));
    if (key === `POST /ft-api/api/v1/system/incidents/deliveries/${id}/claim`) { state='sending'; return new Response(JSON.stringify({id,claim,state})); }
    if (key === `POST /ft-api/api/v1/system/incidents/deliveries/${id}/receipt`) { expect(JSON.parse(init.body as string)).toEqual({claim,state:'submitted_unobserved'}); state='submitted_unobserved'; return new Response(JSON.stringify({id,channel:'desktop',state,attempts:1,updated_at:instant})); }
    unexpected.push(key); throw new Error(key);
  }));
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><SystemDiagnostics /></QueryClientProvider>);
  expect(await screen.findByRole('region',{name:'Incident timeline'})).toHaveTextContent('Kept until manual deletion');
  await waitFor(() => expect(shown).toHaveLength(1));
  expect(await screen.findByText('Submitted; user delivery unobserved')).toBeVisible();
  expect(screen.getByText('Root cause: unknown')).toBeVisible();
  expect(calls.filter(c=>c.endsWith('/claim'))).toHaveLength(1);
  expect(calls.filter(c=>c.startsWith('GET '))).toHaveLength(2);
  expect(unexpected).toEqual([]);
});

it('enables only an explicit configured channel and verifies exact readback without startup channel fetches', async () => {
  useAuthStore.setState({status:'logged-in',token:'inert-incident-config'}); useModeStore.setState({mode:'live'});
  const calls: string[]=[]; const unexpected: string[]=[];
  const receipt={channel:'telegram',enabled:true,binding:'a'.repeat(64),restart:'explicit_rebind_required',in_flight:'not_recalled'};
  vi.stubGlobal('fetch',vi.fn(async(input:string,init:RequestInit)=>{
    const key=`${init.method} ${input}`; calls.push(key);
    if(key==='GET /ft-api/api/v1/system/diagnostics') return new Response(JSON.stringify({status:'success',data:{schema_version:1,observed_at:instant,scope:'core_process',resources:{},acquisition:{},models:{},jobs:{},network_diagnosis:{},recovery:{},operational_events:{status:'available',durable:true,retention:'until_manual_deletion',incidents:[],has_more:false,next_cursor:null}}}));
    if(key==='PUT /ft-api/api/v1/system/incidents/channels/telegram') { expect(JSON.parse(init.body as string)).toEqual({enabled:true,recipient:'inert-chat',provider:'telegram'}); return new Response(JSON.stringify(receipt)); }
    if(key==='GET /ft-api/api/v1/system/incidents/channels/telegram') return new Response(JSON.stringify({...receipt,effective:true}));
    unexpected.push(key); throw Error(key);
  }));
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><SystemDiagnostics /></QueryClientProvider>);
  const recipient=await screen.findByLabelText('Configured alert recipient');
  expect(calls).toEqual(['GET /ft-api/api/v1/system/diagnostics']);
  fireEvent.change(recipient,{target:{value:'inert-chat'}});
  fireEvent.click(screen.getByLabelText('Allow this channel to receive critical incident notices'));
  fireEvent.click(screen.getByRole('button',{name:'Enable selected channel'}));
  expect(await screen.findByText('Channel enabled — exact binding readback verified.')).toBeVisible();
  expect(recipient).toHaveValue('');
  expect(calls).toEqual(['GET /ft-api/api/v1/system/diagnostics','PUT /ft-api/api/v1/system/incidents/channels/telegram','GET /ft-api/api/v1/system/incidents/channels/telegram']);
  expect(unexpected).toEqual([]);
});
