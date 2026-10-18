import { z } from "zod";
import { ConnectionControlError, OAuthCapabilities, isConnectionEtag, readConnectionCollection, type ServiceConnection, type ServiceConnectionCollection } from "./serviceConnectionControls";
import { buildHeaders, getBase, isDemoAuthSession } from "./ftApi.helpers";
import { captureAuthSessionFence, isAuthSessionFenceCurrent, useAuthStore, type AuthSessionFence } from "@/stores/authStore";
const uuid=z.string().uuid();
const Start=z.strictObject({transaction_id:uuid,authorization_url:z.string().max(4096),expires_at:z.number().finite().positive()});
export type OAuthAttempt=z.infer<typeof Start>;
function invalid():never {throw new ConnectionControlError("Provider authentication outcome unavailable or refused. Refresh and review; no request was retried.");}
async function action(snapshot:ServiceConnectionCollection,target:ServiceConnection,operation:string,body:object,method:"GET"|"POST"="POST",fence:AuthSessionFence=captureAuthSessionFence()){
 const check=()=>{if(!isAuthSessionFenceCurrent(fence))invalid();};
 if(isDemoAuthSession()||useAuthStore.getState().status!=="logged-in"||!useAuthStore.getState().token||!isConnectionEtag(snapshot.etag)||!snapshot.connections.some(row=>JSON.stringify(row)===JSON.stringify(target)))invalid();
 check();
 const response=await fetch(`${getBase()}/v1/services/connections/${target.connection_id}/oauth/${operation}`,{method,credentials:"include",cache:"no-store",redirect:"error",headers:{...buildHeaders(true),"If-Match":snapshot.etag},...(method==="POST"?{body:JSON.stringify(body)}:{})}).catch(invalid);
 check();if(!response.ok)invalid();
 const data:unknown=await response.json().catch(invalid);check();
 const etag=response.headers.get("ETag")??"";if(!isConnectionEtag(etag))invalid();
 return {data,etag,fence};
}
export async function startProviderOAuth(snapshot:ServiceConnectionCollection,target:ServiceConnection):Promise<OAuthAttempt>{
 if(!snapshot.oauth?.providers.some(provider=>provider===target.provider_id))invalid();
 const external=snapshot.oauth?.desktop_activation===true;
 const result=await action(snapshot,target,"start",external?{browser:"external"}:{});const parsed=Start.safeParse(result.data);if(!parsed.success)invalid();
 const url=new URL(parsed.data.authorization_url);
 const expected=external?new URL(getBase()||window.location.origin,window.location.origin).origin+"/v1/services/connections/oauth/launch":target.provider_id==="llm:openai"?"https://auth.openai.com/api/accounts/authorize":"https://openrouter.ai/auth";
 if(external&&!/^\?ticket=[A-Za-z0-9_-]{43}$/.test(url.search))invalid();
 if(url.origin+url.pathname!==expected||url.username||url.password||url.hash||url.searchParams.has("id_token_hint")||result.etag!==snapshot.etag)invalid();
 return parsed.data;
}
export async function providerOAuthAction(snapshot:ServiceConnectionCollection,target:ServiceConnection,operation:"complete"|"cancel"|"refresh"|"disconnect",transaction?:string){
 if((operation==="complete"||operation==="cancel")&&!uuid.safeParse(transaction).success)invalid();
 const result=await action(snapshot,target,operation,transaction?{transaction_id:transaction}:{});
 const parsed=z.strictObject({status:z.enum(["connected","cancelled","denied","expired","refreshed","current","disconnected"]),remote_revocation:z.enum(["confirmed","unconfirmed","unsupported"]).optional(),rotation:z.number().int().nonnegative().optional()}).safeParse(result.data);
 if(!parsed.success)invalid();const value=parsed.data;
 const expected={complete:["connected","denied","expired","cancelled"],cancel:["cancelled"],refresh:["refreshed","current"],disconnect:["disconnected"]}[operation];
 if(!expected.includes(value.status)||(operation==="disconnect")!==(value.remote_revocation!==undefined))invalid();
 if(["denied","expired","cancelled"].includes(value.status))return {...value,snapshot:undefined};
 const read=await readConnectionCollection(result.fence);const row=read.connections.find(item=>item.connection_id===target.connection_id);
 if(read.etag!==result.etag||!row||row.provider_id!==target.provider_id||row.auth_mode!==target.auth_mode||row.model!==target.model||row.endpoint!==target.endpoint||row.credential_configured!==(operation!=="disconnect"))invalid();
 if((operation==="complete"||operation==="disconnect")&&read.etag===snapshot.etag)invalid();
 const status=await action(read,row,"status",{},"GET",result.fence);
 const verified=z.strictObject({status:z.enum(["ready","disconnected","refresh_unknown","not_connected"]),rotation:z.number().int().nonnegative(),remote_revocation:z.enum(["confirmed","unconfirmed","unsupported"]).nullable()}).safeParse(status.data);
 if(!verified.success||status.etag!==read.etag||verified.data.status!==(operation==="disconnect"?"disconnected":"ready")||verified.data.remote_revocation!==(value.remote_revocation??null)||(operation==="refresh"&&(value.rotation===undefined||verified.data.rotation!==value.rotation)))invalid();
 return {...value,snapshot:read};
}

export async function configureProviderOAuth(snapshot:ServiceConnectionCollection,deployment:"local_oss"|"api_only") {
 const fence=captureAuthSessionFence();
 if(!snapshot.oauth?.desktop_activation||!isConnectionEtag(snapshot.etag)||isDemoAuthSession()||useAuthStore.getState().status!=="logged-in"||!useAuthStore.getState().token)invalid();
 const response=await fetch(`${getBase()}/v1/services/connections/oauth/configuration`,{method:"POST",credentials:"include",cache:"no-store",redirect:"error",headers:{...buildHeaders(true),"If-Match":snapshot.etag},body:JSON.stringify({deployment})}).catch(invalid);
 if(!isAuthSessionFenceCurrent(fence)||!response.ok||response.headers.get("ETag")!==snapshot.etag)invalid();
 const value=OAuthCapabilities.safeParse(await response.json().catch(invalid));
 if(!isAuthSessionFenceCurrent(fence)||!value.success||value.data.configured!==(deployment==="local_oss")||!value.data.desktop_activation)invalid();
 const read=await readConnectionCollection(fence);
 if(read.etag!==snapshot.etag||JSON.stringify(read.oauth)!==JSON.stringify(value.data))invalid();
 return read;
}
