import fs from 'node:fs/promises';
import {assessCompleteCapture,exportCapture} from './paged-capture.mjs';
import {sealOriginalWindow,materializeSeal,assessSealedCapture} from './seal.mjs';
const records=new Map<string,any>();
export function startWitness(page:any,info:any){
 const r={wire:[] as any[],frames:[] as any[],otherSockets:[] as string[],bytes:0,capture:{schema:'r88.capture.v1',startedBeforeNavigation:page.url()==='about:blank',originalSince:0,startedAtMs:Date.now(),observedAtMs:0,connectedSockets:0,closedSockets:0,socketErrors:0,hellos:0,sessionId:'',documentId:'',serverIncarnation:''}};
 records.set(info.testId,r);
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
