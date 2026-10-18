import { useLayoutEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { captureAuthSessionFence, isAuthSessionFenceCurrent, useAuthStore } from "@/stores/authStore";
import { providerOAuthAction, startProviderOAuth, type OAuthAttempt } from "@/services/serviceOAuth";
import type { ServiceConnection, ServiceConnectionCollection } from "@/services/serviceConnectionControls";
interface Props { snapshot:ServiceConnectionCollection; row:ServiceConnection; disabled:boolean; onChanged:(value:ServiceConnectionCollection)=>void; onBlocked?:(blocked:boolean)=>void }
export default function ServiceOAuthControls(props:Props){
 const generation=useAuthStore(state=>state.sessionGeneration);
 return <ScopedOAuth key={`${generation}:${props.row.connection_id}:${props.snapshot.oauth?.configured}`} {...props}/>;
}
function ScopedOAuth({snapshot,row,disabled,onChanged,onBlocked}:Props){
 const [attempt,setAttempt]=useState<OAuthAttempt|null>(null);
 const [busy,setBusy]=useState(false);const [notice,setNotice]=useState("");const [confirm,setConfirm]=useState(false);
 const epoch=useRef(0); const scope=useRef(snapshot.etag);const inFlight=useRef(false);
 useLayoutEffect(()=>{scope.current=snapshot.etag;const generation=++epoch.current;setBusy(false);setAttempt(null);setConfirm(false);inFlight.current=false;return()=>{epoch.current=generation+1;};},[snapshot.etag]);
 async function run(operation:"start"|"complete"|"cancel"|"refresh"|"disconnect"){
  if(disabled||inFlight.current)return;
  const fence=captureAuthSessionFence(),version=epoch.current;
  const current=()=>isAuthSessionFenceCurrent(fence)&&epoch.current===version&&scope.current===snapshot.etag;
  inFlight.current=true;setBusy(true);setNotice("");
  try{
   if(operation==="start"){
    const value=await startProviderOAuth(snapshot,row);if(current())setAttempt(value);
   }else{
    const value=await providerOAuthAction(snapshot,row,operation,operation==="complete"||operation==="cancel"?attempt?.transaction_id:undefined);
    if(!current())return;
    setAttempt(null);setConfirm(false);
    setNotice(value.status==="connected"?"Provider grant connected and read back. Admission, budget and qualification remain separate.":value.status==="disconnected"?`Local disconnect read back. Remote revocation: ${value.remote_revocation}. Accepted work is not proven cancelled.`:value.status==="denied"?"Provider access was denied; nothing was connected.":value.status==="refreshed"||value.status==="current"?"Provider token is current; connection and policy scope are unchanged.":`Sign-in ${value.status}.`);
    setBusy(false);
    if(value.snapshot)onChanged(value.snapshot);
   }
  }catch{
   if(current()){setAttempt(null);setNotice("Provider authentication outcome unavailable or refused. Refresh and review before a new action; no request was retried.");onBlocked?.(true);}
  }finally{if(current()){inFlight.current=false;setBusy(false);}}
 }
 const available=snapshot.oauth?.providers.some(provider=>provider===row.provider_id)&&((row.provider_id==="llm:openai"&&row.auth_mode==="chatgpt_oauth")||(row.provider_id==="llm:openrouter"&&row.auth_mode==="api_key"));
 if(!available)return null;
 return <section aria-label={`Provider authentication ${row.label}`} className="space-y-2">
  <p className="text-xs text-text-muted">{row.provider_id==="llm:openai"?"Local/OSS direct ChatGPT plan flow. Responses only; no Decisions or training entitlement and no hard output-token cap.":"OpenRouter PKCE creates a user-controlled API key. No rotating refresh or remote revocation is supported by this route; manage the key in OpenRouter."}</p>
  <Button size="sm" variant="outline" disabled={disabled||busy||!!attempt} onClick={()=>void run("start")}>{row.provider_id==="llm:openai"?"Continue with ChatGPT":"Sign in with OpenRouter"}</Button>
  {attempt&&<div className="space-x-2"><a href={attempt.authorization_url} target="_blank" rel="noreferrer noopener">Open provider sign-in</a><Button size="sm" disabled={disabled||busy} onClick={()=>void run("complete")}>Complete sign-in</Button><Button size="sm" variant="outline" disabled={disabled||busy} onClick={()=>void run("cancel")}>Cancel sign-in</Button></div>}
  {row.credential_configured&&<><Button size="sm" variant="outline" disabled={disabled||busy||row.provider_id!=="llm:openai"} onClick={()=>void run("refresh")}>Refresh provider token</Button><Button size="sm" variant="outline" disabled={disabled||busy} onClick={()=>setConfirm(true)}>Disconnect provider</Button></>}
  {confirm&&<div><p className="text-xs">Disconnect this exact local connection and attempt remote session revocation. No task, role or budget will be changed. Remote failure does not prevent local disconnect.</p><Button size="sm" disabled={disabled||busy} onClick={()=>void run("disconnect")}>Confirm provider disconnect</Button></div>}
  {notice&&<p role="status" className="text-xs">{notice}</p>}
 </section>;
}
