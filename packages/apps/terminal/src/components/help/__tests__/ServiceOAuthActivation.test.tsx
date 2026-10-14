import { cleanup, fireEvent, render, screen, act } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import ServiceConnectionSetup from '../ServiceConnectionSetup';
import { useAuthStore } from '@/stores/authStore';
const tag = '"' + 'a'.repeat(64) + '"';
const id = '5a765bd0-48c1-4b8a-8db7-c94633b1abca';
const row = { schema_version: 1 as const, connection_id: id, provider_id: 'llm:openai', label: 'Synthetic', model: 'test-model-v1', endpoint: 'https://api.openai.com/v1/chat/completions', auth_mode: 'chatgpt_oauth', credential_configured: false, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z' };
const enabled = { configured: true as const, providers: ['llm:openai' as const, 'llm:openrouter' as const], desktop_activation: true as const };
const reply = (value: unknown) => new Response(JSON.stringify(value), { headers: { ETag: tag } });
beforeEach(() => useAuthStore.setState({ status: 'logged-in', token: 'synthetic-session', username: 'synthetic', sessionGeneration: 1 }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it('requires explicit local OSS confirmation and reads back activation without provider calls', async () => {
 const calls: string[] = [], unexpected: string[] = [];
 const fetch = vi.fn(async (url: string, init: RequestInit) => {
  calls.push(`${init.method} ${url}`);
  if (url.endsWith('/oauth/configuration') && init.method === 'POST') {
   expect(JSON.parse(String(init.body))).toEqual({ deployment: 'local_oss' });
   expect(new Headers(init.headers).get('If-Match')).toBe(tag);
   return reply(enabled);
  }
  if (url.endsWith('/connections') && init.method === 'GET') return reply({ connections: [row], oauth: enabled });
  unexpected.push(url); return new Response('{}', {status: 404});
 }); vi.stubGlobal('fetch', fetch);
 const changed = vi.fn();
 render(<ServiceConnectionSetup snapshot={{etag:tag,connections:[row],oauth:{configured:false,providers:[],desktop_activation:true}}} unavailable={false} onChanged={changed} onRefresh={vi.fn()}/>);
 expect(fetch).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'Enable local/OSS provider sign-in'}));
 expect(fetch).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:'Confirm local/OSS activation'}));
 await screen.findByText(/Local\/OSS activation read back/);
 expect(changed).toHaveBeenCalledTimes(1); expect(calls).toHaveLength(2); expect(unexpected).toEqual([]);
});
it('opens only the scoped local handoff in desktop mode', async () => {
 const launch = window.location.origin + '/v1/services/connections/oauth/launch?ticket=' + 'a'.repeat(43);
 const fetch = vi.fn(async (_url: string, init: RequestInit) => {
  expect(JSON.parse(String(init.body))).toEqual({browser:'external'});
  return reply({transaction_id:'2c607ae2-54e0-427c-b5cc-6eaf214b5932',authorization_url:launch,expires_at:1900000000});
 }); vi.stubGlobal('fetch',fetch);
 render(<ServiceConnectionSetup snapshot={{etag:tag,connections:[row],oauth:enabled}} unavailable={false} onChanged={vi.fn()} onRefresh={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'Continue with ChatGPT'}));
 expect(await screen.findByRole('link',{name:'Open provider sign-in'})).toHaveAttribute('href',launch);
 expect(fetch).toHaveBeenCalledTimes(1);
});
it('does not publish a delayed activation after operator retirement', async () => {
 let resolve!: (r:Response)=>void;
 vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(r=>{resolve=r;})));
 const changed=vi.fn();
 render(<ServiceConnectionSetup snapshot={{etag:tag,connections:[row],oauth:{configured:false,providers:[],desktop_activation:true}}} unavailable={false} onChanged={changed} onRefresh={vi.fn()}/>);
 fireEvent.click(screen.getByRole('button',{name:'Enable local/OSS provider sign-in'}));
 fireEvent.click(screen.getByRole('button',{name:'Confirm local/OSS activation'}));
 await act(async()=>{useAuthStore.setState({token:'replacement',sessionGeneration:2});resolve(reply(enabled));});
 expect(changed).not.toHaveBeenCalled();expect(screen.queryByText(/activation read back/)).not.toBeInTheDocument();
});
it('retires a pending browser handoff through an activation off-on cycle', async () => {
 let resolve!: (r:Response)=>void;
 vi.stubGlobal('fetch',vi.fn(()=>new Promise<Response>(r=>{resolve=r;})));
 const props={unavailable:false,onChanged:vi.fn(),onRefresh:vi.fn()};
 const view=render(<ServiceConnectionSetup {...props} snapshot={{etag:tag,connections:[row],oauth:enabled}}/>);
 fireEvent.click(screen.getByRole('button',{name:'Continue with ChatGPT'}));
 view.rerender(<ServiceConnectionSetup {...props} snapshot={{etag:tag,connections:[row],oauth:{configured:false,providers:[],desktop_activation:true}}}/>);
 view.rerender(<ServiceConnectionSetup {...props} snapshot={{etag:tag,connections:[row],oauth:enabled}}/>);
 const launch=window.location.origin+'/v1/services/connections/oauth/launch?ticket='+'a'.repeat(43);
 await act(async()=>resolve(reply({transaction_id:'2c607ae2-54e0-427c-b5cc-6eaf214b5932',authorization_url:launch,expires_at:1900000000})));
 expect(screen.queryByRole('link',{name:'Open provider sign-in'})).not.toBeInTheDocument();
});
