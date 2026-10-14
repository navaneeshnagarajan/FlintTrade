import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ServiceConnectionSetup from "../ServiceConnectionSetup";
import { useAuthStore } from "@/stores/authStore";
const id="5a765bd0-48c1-4b8a-8db7-c94633b1abca";
const tx="2c607ae2-54e0-427c-b5cc-6eaf214b5932";
const tag='"'+"a".repeat(64)+'"'; const next='"'+"b".repeat(64)+'"';
const row={schema_version:1 as const,connection_id:id,provider_id:"llm:openai",label:"Synthetic",model:"test-model-v1",endpoint:"https://api.openai.com/v1/chat/completions",auth_mode:"chatgpt_oauth",credential_configured:false,created_at:"2026-01-01T00:00:00Z",updated_at:"2026-01-01T00:00:00Z"};
const snapshot={etag:tag,connections:[row],oauth:{configured:true as const,providers:["llm:openai" as const,"llm:openrouter" as const]}};
beforeEach(()=>useAuthStore.setState({status:"logged-in",token:"synthetic-session",username:"synthetic",sessionGeneration:1}));
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
const reply=(value:unknown,etag=tag,status=200)=>new Response(JSON.stringify(value),{status,headers:{ETag:etag}});
it("uses explicit PKCE actions without extra startup GETs or token fields",async()=>{
 const calls:string[]=[];const unexpected:string[]=[];const changed=vi.fn();
 vi.stubGlobal("fetch",vi.fn(async(url:string,init:RequestInit)=>{
  const path=new URL(url,"http://localhost").pathname;calls.push(`${init.method} ${path}`);
  if(path.endsWith("/oauth/start")&&init.method==="POST")return reply({transaction_id:tx,authorization_url:"https://auth.openai.com/api/accounts/authorize?state=synthetic",expires_at:1900000000});
  if(path.endsWith("/oauth/complete")&&init.method==="POST")return reply({status:"connected"},next);
  if(path.endsWith("/oauth/status")&&init.method==="GET")return reply({status:"ready",rotation:0,remote_revocation:null},next);
  if(path.endsWith("/connections")&&init.method==="GET")return reply({connections:[{...row,credential_configured:true}],oauth:snapshot.oauth},next);
  unexpected.push(path);return reply({},tag,404);
 }));
 render(<ServiceConnectionSetup snapshot={snapshot} unavailable={false} onChanged={changed} onRefresh={vi.fn()}/>);
 expect(calls).toHaveLength(0);
 fireEvent.click(screen.getByRole("button",{name:"Continue with ChatGPT"}));
 expect(await screen.findByRole("link",{name:"Open provider sign-in"})).toHaveAttribute("rel","noreferrer noopener");
 fireEvent.click(screen.getByRole("button",{name:"Complete sign-in"}));
 expect(await screen.findByText(/Provider grant connected and read back/)).toBeInTheDocument();
 expect(changed).toHaveBeenCalledTimes(1);expect(calls).toHaveLength(4);expect(unexpected).toEqual([]);
 expect(screen.queryByLabelText("Connection credential")).not.toBeInTheDocument();
});
it("retires a delayed acquisition result when the operator changes",async()=>{
 let resolve!:(r:Response)=>void;
 const fetch=vi.fn(()=>new Promise<Response>(r=>{resolve=r;}));vi.stubGlobal("fetch",fetch);
 const changed=vi.fn();render(<ServiceConnectionSetup snapshot={snapshot} unavailable={false} onChanged={changed} onRefresh={vi.fn()}/>);
 fireEvent.click(screen.getByRole("button",{name:"Continue with ChatGPT"}));expect(fetch).toHaveBeenCalledTimes(1);
 await act(async()=>{useAuthStore.setState({token:"replacement",sessionGeneration:2});resolve(reply({transaction_id:tx,authorization_url:"https://auth.openai.com/api/accounts/authorize?state=synthetic",expires_at:1900000000}));});
 expect(screen.queryByRole("link",{name:"Open provider sign-in"})).not.toBeInTheDocument();expect(changed).not.toHaveBeenCalled();
});

it.each(["denied","cancelled","expired"] as const)("shows %s without credential readback or replay",async status=>{
 const calls:string[]=[];
 vi.stubGlobal("fetch",vi.fn(async(url:string)=>{calls.push(url);return reply(url.endsWith("/start")?{transaction_id:tx,authorization_url:"https://auth.openai.com/api/accounts/authorize?state=synthetic",expires_at:1900000000}:{status});}));
 const changed=vi.fn();render(<ServiceConnectionSetup snapshot={snapshot} unavailable={false} onChanged={changed} onRefresh={vi.fn()}/>);
 fireEvent.click(screen.getByRole("button",{name:"Continue with ChatGPT"}));await screen.findByRole("link");
 fireEvent.click(screen.getByRole("button",{name:status==="cancelled"?"Cancel sign-in":"Complete sign-in"}));
 await screen.findByText(status==="denied"?/Provider access was denied/:new RegExp(`Sign-in ${status}`));
 expect(calls).toHaveLength(2);expect(changed).not.toHaveBeenCalled();
});
it.each(["confirmed","unconfirmed","unsupported"] as const)("reads back local disconnect separately from remote %s",async remote=>{
 const current={...snapshot,connections:[{...row,credential_configured:true}]};const calls:string[]=[];const unexpected:string[]=[];const changed=vi.fn();
 vi.stubGlobal("fetch",vi.fn(async(url:string,init:RequestInit)=>{
  calls.push(`${init.method} ${url}`);
  if(url.endsWith("/disconnect")&&init.method==="POST")return reply({status:"disconnected",remote_revocation:remote},next);
  if(url.endsWith("/connections")&&init.method==="GET")return reply({connections:[row],oauth:snapshot.oauth},next);
  if(url.endsWith("/status")&&init.method==="GET")return reply({status:"disconnected",rotation:1,remote_revocation:remote},next);
  unexpected.push(url);return reply({},tag,404);
 }));
 render(<ServiceConnectionSetup snapshot={current} unavailable={false} onChanged={changed} onRefresh={vi.fn()}/>);
 expect(calls).toHaveLength(0);fireEvent.click(screen.getByRole("button",{name:"Disconnect provider"}));expect(calls).toHaveLength(0);
 fireEvent.click(screen.getByRole("button",{name:"Confirm provider disconnect"}));
 expect(await screen.findByText(new RegExp(`Remote revocation: ${remote}`))).toBeInTheDocument();
 expect(changed).toHaveBeenCalledTimes(1);expect(calls).toHaveLength(3);expect(unexpected).toEqual([]);
});
it("verifies refresh rotation without changing the connection revision",async()=>{
 const current={...snapshot,connections:[{...row,credential_configured:true}]};const calls:string[]=[];const changed=vi.fn();
 vi.stubGlobal("fetch",vi.fn(async(url:string,init:RequestInit)=>{
  calls.push(`${init.method} ${url}`);
  if(url.endsWith("/refresh"))return reply({status:"refreshed",rotation:2});
  if(url.endsWith("/connections"))return reply({connections:current.connections,oauth:snapshot.oauth});
  if(url.endsWith("/status"))return reply({status:"ready",rotation:2,remote_revocation:null});
  throw new Error("unregistered");
 }));
 render(<ServiceConnectionSetup snapshot={current} unavailable={false} onChanged={changed} onRefresh={vi.fn()}/>);
 fireEvent.click(screen.getByRole("button",{name:"Refresh provider token"}));
 await screen.findByText(/Provider token is current/);expect(changed).toHaveBeenCalledTimes(1);expect(calls).toHaveLength(3);
});
it("retires delayed results on a connection revision change and allows a fresh attempt",async()=>{
 let resolve!:(r:Response)=>void;vi.stubGlobal("fetch",vi.fn(()=>new Promise<Response>(r=>{resolve=r;})));
 const changed=vi.fn();const props={unavailable:false,onChanged:changed,onRefresh:vi.fn()};const view=render(<ServiceConnectionSetup {...props} snapshot={snapshot}/>);
 fireEvent.click(screen.getByRole("button",{name:"Continue with ChatGPT"}));
 view.rerender(<ServiceConnectionSetup {...props} snapshot={{...snapshot,etag:next}}/>);
 await act(async()=>resolve(reply({transaction_id:tx,authorization_url:"https://auth.openai.com/api/accounts/authorize?state=synthetic",expires_at:1900000000})));
 expect(screen.queryByRole("link")).not.toBeInTheDocument();expect(changed).not.toHaveBeenCalled();
 expect(screen.getByRole("button",{name:"Continue with ChatGPT"})).toBeEnabled();
});
