import fs from 'node:fs/promises';
import {assessCompleteCapture,exportCapture} from './paged-capture.mjs';
import {sealOriginalWindow,materializeSeal,assessSealedCapture} from './seal.mjs';

interface WitnessInfo {testId:string;outputPath(name:string):string}
interface WitnessPage {isClosed():boolean}
interface WitnessClient {call(name:string,args:Record<string,unknown>):Promise<unknown>}
const owners=new Map<string,{info:WitnessInfo;page:WitnessPage;record:object;retired:boolean}>();
const records=new Map<string,any>();
export function startWitness(page:any,info:any){
  const previous=owners.get(info.testId);
  if(previous){previous.retired=true;throw Error('case witness owner replaced');}
 const r={wire:[] as any[],frames:[] as any[],otherSockets:[] as string[],bytes:0,capture:{schema:'r88.capture.v1',startedBeforeNavigation:page.url()==='about:blank',originalSince:0,startedAtMs:Date.now(),observedAtMs:0,connectedSockets:0,closedSockets:0,socketErrors:0,hellos:0,sessionId:'',documentId:'',serverIncarnation:''}};
 records.set(info.testId,r);
  owners.set(info.testId,{info,page,record:r,retired:false});
 page.on('websocket',ws=>{
  if(new URL(ws.url()).pathname!=='/reticle'){r.otherSockets.push(ws.url());return;}
  const socket=r.capture.connectedSockets++;
  ws.on('close',()=>r.capture.closedSockets++);ws.on('socketerror',()=>r.capture.socketErrors++);
  ws.on('framesent',frame=>{
   const payload=frame.payload.toString();r.bytes+=Buffer.byteLength(payload);
   if(r.bytes>67108864||r.frames.length>=200000){r.capture.socketErrors++;return;}
   r.frames.push({socket,index:r.frames.length,atMs:Date.now(),payload});
   let v:any;try{v=JSON.parse(payload);}catch{r.capture.socketErrors++;return;}
   if(v.kind==='hello'){r.capture.hellos++;r.capture.sessionId ||=v.sessionId;}
   if(v.kind==='event'){r.wire.push(v.event);r.capture.documentId ||=v.event.documentId;}
  });
 });
 page.on('close',()=>{void fs.writeFile(info.outputPath('r101-final-wire-lifecycle.json'),JSON.stringify(r,null,2));});
}
function caseScope(info:WitnessInfo){
  const owner=owners.get(info.testId),r=records.get(info.testId);
  if(!owner||owner.info!==info||owner.record!==r||owner.retired||owner.page.isClosed())throw Error('case witness owner unavailable or replaced');
  const c=r.capture;
  if(c.startedBeforeNavigation!==true||c.connectedSockets!==1||c.closedSockets!==0||c.socketErrors!==0||
        typeof c.sessionId!=='string'||!c.sessionId||typeof c.documentId!=='string'||!c.documentId)throw Error('case witness lifecycle or identity incomplete');
  // Validate the current prefix without changing the approved snapshot endpoint.
  // Retain every frame: a document/epoch change away and back still invalidates it.
  const first:unknown=r.wire[0];
  if(!object(first))throw Error('case witness producer identity missing');
  const epoch=JSON.stringify(first.editEpoch);
  if(r.wire.some((event:unknown)=>!object(event)||event.documentId!==c.documentId||JSON.stringify(event.editEpoch)!==epoch))throw Error('case witness document or epoch changed');
  if(r.frames.some((frame:{payload:string})=>{const value:unknown=JSON.parse(frame.payload);return object(value)&&value.kind==='hello'&&value.sessionId!==c.sessionId;}))throw Error('case witness announcement identity changed');
  return {owner,sessionId:c.sessionId,documentId:c.documentId,epoch};
}
const object=(value:unknown):value is Record<string,unknown>=>value!==null&&typeof value==='object'&&!Array.isArray(value);
export async function callWitness(client:WitnessClient,info:WitnessInfo,name:string,args:Record<string,unknown>):Promise<Record<string,unknown>>{
  if(!['reticle_look','reticle_observe','reticle_assert'].includes(name))throw Error('unsupported case witness operation');
  const before=caseScope(info);
  if(Object.hasOwn(args,'sessionId')&&args.sessionId!==before.sessionId)throw Error('foreign case witness session');
  const result=await client.call(name,{...args,sessionId:before.sessionId});
  const after=caseScope(info);
  if(after.owner!==before.owner||after.sessionId!==before.sessionId||after.documentId!==before.documentId||after.epoch!==before.epoch)throw Error('case witness changed during operation');
  if(!object(result))throw Error('case witness result is not an object');
  if(object(result.session_lease)&&result.session_lease.sessionId!==before.sessionId)throw Error('foreign case witness lease');
  if(Array.isArray(result.events)&&result.events.some(event=>!object(event)||event.documentId!==before.documentId))throw Error('foreign case witness document');
  if(object(result.capture)){
    const scope=result.capture.scope;
    if(!object(scope)||scope.sessionId!==before.sessionId||scope.documentId!==before.documentId)throw Error('foreign case witness capture');
  }
  // Registry-incarnation checks remain in the unchanged sealed/fresh native gate.
  // This routing operation neither exports a new snapshot nor manufactures scope.
  return result;
}
export async function finishWitness(client:any,verdict:any,info:any,name:string,predicate:any){
 const r=records.get(info.testId);if(!r)throw Error('capture did not start');
 let pages:any[]=[],wirePages:any[]=[],failure:any;
 try{pages=await exportCapture(client,'live',r.capture.sessionId);}catch(e){failure=String(e);}
 // Exact R83 endpoint: stamp and copy before ANY supplemental export/drain await.
 r.capture.observedAtMs=Date.now();r.capture.serverIncarnation ||=pages[0]?.response?.capture?.scope?.incarnation;
 const envelope={pages,wirePages,verdict,wire:[...r.wire],frames:[...r.frames],capture:{...r.capture},otherSockets:[...r.otherSockets],exportFailure:failure};
 const throughSeq=envelope.wire.at(-1)?.seq;
 try{envelope.wirePages=await exportCapture(client,'wire',r.capture.sessionId,throughSeq);}catch(e){envelope.exportFailure=String(e);}
 const initialAssessment=assessCompleteCapture(envelope);
 // The raw snapshot above is fixed; only receipts for its exact last sequence
 // have been materialised. Never recopy raw frames or move observedAtMs.
 const seal=sealOriginalWindow(envelope,predicate);
 await fs.writeFile(info.outputPath(name+'-initial-full-window.json'),JSON.stringify({envelope,initialAssessment,seal},null,2));
 let materialization:any,assessment:any;
 try{materialization=await materializeSeal(client,seal);assessment=assessSealedCapture(materialization);}
 catch(e){assessment={accepted:false,faults:['causal materialisation refused: '+String(e)]};}
 await fs.writeFile(info.outputPath(name+'-full-window.json'),JSON.stringify({envelope,initialAssessment,materialization,assessment},null,2));
 return assessment;
}
