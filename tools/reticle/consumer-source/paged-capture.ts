import {validateCaptureEnvelope} from './boundaries.mjs';
import {withoutUrlRaw} from '../node_modules/@reticlehq/engine/dist/window/event-filters.js';
import {assessRawCapture} from './capture.mjs';
type Obj=Record<string,any>;
const canonical=(x:any):any=>Array.isArray(x)?x.map(canonical):x!==null&&typeof x==='object'?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
const same=(a:any,b:any)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
const uint=(x:any)=>Number.isSafeInteger(x)&&x>=0;
function readPages(rows:any,stream:string,faults:string[]){
 if(!Array.isArray(rows)||!rows.length||rows.length>100000)throw Error('missing/over-budget '+stream+' pages');
 let offset=0,next:any,id:any,total:any,until:any,retention:any;const items:Obj[]=[];
 for(const [i,row] of rows.entries()){
  const {request:q,response:r}=row,c=r?.capture,a=stream==='wire'?r?.records:r?.events;
  if(q?.action!=='events'||q.since!==0||q.max_events!==2000||['filters','until','actionId','window_ms'].some(k=>Object.hasOwn(q,k))||!q.export_page||(stream==='wire'?q.export_page.stream!=='wire':q.export_page.stream!==undefined))faults.push(stream+' original scope');
  if(i===0?q.export_page?.cursor!==undefined:q.export_page?.cursor!==next)faults.push(stream+' cursor chain');
  if(!c||c.source!==stream||c.since!==0||c.offset!==offset||!Array.isArray(a)||c.count!==a.length||c.count>2000||!uint(c.total)||c.total>100000||c.dropped!==0)throw Error(stream+' invalid metadata');
  if(i===0){id=c.id;total=c.total;until=c.until;retention=c.retention;}
  if(c.id!==id||c.total!==total||c.until!==until||!same(c.retention,retention)||typeof id!=='string'||!/^[a-f0-9]{32}$/.test(id)||!uint(until))faults.push(stream+' identity changed');
  if(!retention||!uint(retention.maxEvents)||retention.maxEvents<1||retention.maxEvents>100000||!uint(retention.maxAgeMs)||retention.maxAgeMs<1||retention.maxAgeMs>600000||!uint(retention.maxBytes)||retention.maxBytes<1||retention.maxBytes>67108864||total>retention.maxEvents)faults.push(stream+' retention budget');
  const bytes=Buffer.byteLength(JSON.stringify(a));
  if(c.event_bytes!==bytes||bytes>(q.export_page.max_bytes??262144))faults.push(stream+' byte budget/count');
  if(!r.cost||!uint(r.cost.bytes)||(r.cost.droppedOldest??0)!==0||r.cost.events!==(stream==='wire'?0:c.count)||r.summary?.total!==(stream==='wire'?0:c.count))faults.push(stream+' output truncated');
  if(stream==='wire'&&(r.events?.length!==0||r.cost.bytes<c.event_bytes))faults.push('telemetry became evidence/uncounted bytes');
  if(Object.hasOwn(r,'buffer')){const b=r.buffer;if(!b||!uint(b.held)||!uint(b.dropped)||typeof b.note!=='string'||b.dropped!==0)faults.push(stream+' buffer malformed/lost');}
  if(r.observationLost===true||Object.hasOwn(r,'inconclusive')||r.session?.throttled===true||Object.hasOwn(r.session??{},'versionSkew'))faults.push(stream+' unhealthy');
  items.push(...a);offset+=c.count;next=c.next_cursor;
  if(c.complete!==(offset===total)||Boolean(next)===(offset===total)||i<rows.length-1&&!next||!c.count&&c.total)faults.push(stream+' false completion');
 }
 if(next||offset!==total)faults.push(stream+' incomplete prefix');
 if(Buffer.byteLength(JSON.stringify(items))>retention.maxBytes)faults.push(stream+' aggregate bytes');
 return {items,id,until};
}
/** Reconcile two distinct data classes. Receipt telemetry NEVER feeds the native predicate. */
export function assessCompleteCapture(v:Obj){
 const faults:string[]=[];
 try{
  validateCaptureEnvelope(v);
  const raw=readPages(v.wirePages,'wire',faults),app=readPages(v.pages,'live',faults);
  if(v.capture?.serverIncarnation!==raw.id)faults.push('server incarnation changed');
  const received:Obj[]=[];const application:Obj[]=[];let previous=-1;
  for(const [i,r] of raw.items.entries()){
   if(r.receipt!==i||!uint(r.receivedAt)||r.receivedAt<previous||r.receivedAt>raw.until||!same(r.event,withoutUrlRaw(v.wire?.[i])))faults.push('receipt missing/forged/late');
   previous=r.receivedAt;received.push(r.event);
   if(r.kind!==(r.event.type==='hud.used'?'instrumenter':'application'))faults.push('wrong telemetry classification');
   if(r.kind==='application')application.push(r.event);
  }
  if(raw.items.length!==v.wire?.length)faults.push('unfiltered wire incomplete/late event');
  if(application.length!==app.items.length)faults.push('live evidence incomplete');
  for(const [i,e] of app.items.entries()){
   const r=application[i];if(!r||e.seq!==r.seq||e.type!==r.type||e.documentId!==r.documentId||!same(e.data,r.data)||e.type==='hud.used')faults.push('live/raw evidence mismatch');
  }
  // Explicit DERIVED receipt view, not a substituted daemon response. Every source page stays in v.
  const receiptView={...v,request:{action:'events',since:0,max_events:2000},observed:{events:received,cost:{events:received.length,bytes:Buffer.byteLength(JSON.stringify(received))},summary:{total:received.length}}};
  const assessment=assessRawCapture(receiptView);faults.push(...assessment.faults);
  return {accepted:faults.length===0,faults:[...new Set(faults)],emitted:v.wire?.length??0,receipts:raw.items.length,exported:app.items.length,pages:v.pages.length,wirePages:v.wirePages.length};
 }catch(e){return {accepted:false,faults:[...new Set([...faults,'malformed complete capture: '+String(e)])]};}
}
export async function exportCapture(client:any,stream:'live'|'wire',sessionId:string,throughSeq?:number){
 const pages:Obj[]=[];let cursor;
 for(let i=0;i<100000;i++){
  const request={action:'events',since:0,max_events:2000,sessionId,export_page:{...(stream==='wire'?{stream:'wire'}:{}),...(throughSeq===undefined?{}:{through_seq:throughSeq}),...(cursor?{cursor}:{})}};
  const response=await client.call('reticle_observe',request);pages.push({request,response});
  if(!response.capture)throw Error('capture export absent');cursor=response.capture.next_cursor;if(!cursor)return pages;
 }
 throw Error('capture page budget exhausted');
}
