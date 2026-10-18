// Test source: GNU AGPL v3, as licensed in the repository LICENSE.
import { afterEach, expect, it, vi } from 'vitest';
import { submitBrowserIncident, configureIncidentChannel } from '@/services/systemIncidents';
import { useAuthStore } from '@/stores/authStore';
const id='11111111-1111-4111-8111-111111111111',claim='22222222-2222-4222-8222-222222222222';
const receipt={id,channel:'desktop' as const,state:'browser_pending' as const,attempts:0,updated_at:'2026-10-12T00:00:00Z'};
afterEach(()=>{vi.unstubAllGlobals();});
it.each([{permission:'denied',throws:false,state:'failed',shows:0},{permission:'default',throws:false,state:'failed',shows:0},{permission:'granted',throws:true,state:'unknown',shows:1}])('keeps $permission / throws=$throws honest with one receipt',async ({permission,throws,state,shows})=>{
 useAuthStore.setState({status:'logged-in',token:'incident-scope-a'});
 const shown=vi.fn(()=>{if(throws)throw Error('inert OS failure');});
 class Notification {static permission=permission;constructor(){shown();}}
 vi.stubGlobal('Notification',Notification);
 const posts:unknown[]=[];
 vi.stubGlobal('fetch',vi.fn(async (_url:string,init:RequestInit)=>{
  if(init.body){posts.push(JSON.parse(init.body as string));return new Response(JSON.stringify({...receipt,state}));}
  return new Response(JSON.stringify({id,claim,state:'sending'}));
 }));
 await submitBrowserIncident(receipt,new AbortController().signal);
 expect(shown).toHaveBeenCalledTimes(shows);
 expect(posts).toEqual([{claim,state}]);
 expect(fetch).toHaveBeenCalledTimes(2);
});
it('does not show or report a late claim after session retirement',async()=>{
 useAuthStore.setState({status:'logged-in',token:'incident-old'});
 const shown=vi.fn(); class Notification {static permission='granted';constructor(){shown();}} vi.stubGlobal('Notification',Notification);
 let resolve!:(r:Response)=>void;
 const held=new Promise<Response>(r=>{resolve=r;});
 vi.stubGlobal('fetch',vi.fn(()=>held));
 const pending=submitBrowserIncident(receipt,new AbortController().signal);
 useAuthStore.getState().setLoggedOut();
 useAuthStore.getState().setLoggedIn('incident-new','replacement-operator','2099-01-01T00:00:00Z');
 resolve(new Response(JSON.stringify({id,claim,state:'sending'})));
 await pending;
 expect(shown).not.toHaveBeenCalled(); expect(fetch).toHaveBeenCalledTimes(1);
});
it('rejects a malformed enable ACK without claiming verified enablement or resending',async()=>{
 useAuthStore.setState({status:'logged-in',token:'incident-config'});
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({enabled:true}))));
 await expect(configureIncidentChannel('telegram',true,'inert')).rejects.toThrow();
 expect(fetch).toHaveBeenCalledTimes(1);
});
it('rejects claim replay conflict without a browser side effect',async()=>{
 useAuthStore.setState({status:'logged-in',token:'incident-scope-a'});
 const shown=vi.fn(); class Notification {static permission='granted';constructor(){shown();}} vi.stubGlobal('Notification',Notification);
 vi.stubGlobal('fetch',vi.fn(async()=>new Response('{}',{status:409})));
 await submitBrowserIncident(receipt,new AbortController().signal);
 expect(shown).not.toHaveBeenCalled();expect(fetch).toHaveBeenCalledTimes(1);
});
