import {CaptureScopeSchema} from '../node_modules/@reticlehq/core/dist/index.js';
import {SealSchema,SealedCaptureSchema} from './boundaries.mjs';
import {createHash} from 'node:crypto';
import {assessCompleteCapture,exportCapture} from './paged-capture.mjs';
type Obj=Record<string,any>;
const hash=(v:any)=>createHash('sha256').update(JSON.stringify(v)).digest('hex');
const same=(a:any,b:any)=>JSON.stringify(a)===JSON.stringify(b);
/** Called at exactly the pre-existing observation endpoint, BEFORE asynchronous materialisation. */
export function sealOriginalWindow(original:Obj,predicate:Obj){
 const snapshot=structuredClone(original),claim=structuredClone(predicate);
 return {schema:'r88.causal-seal.v1',original:snapshot,predicate:claim,originalSha256:hash(snapshot),predicateSha256:hash(claim),throughSeq:snapshot.wire.at(-1)?.seq,sealedAtMs:snapshot.capture.observedAtMs};
}
/** One materialisation attempt; no retries, no observer/clock changes, no new observation endpoint. */
export async function materializeSeal(client:any,seal:Obj){
 SealSchema.parse(seal);
 CaptureScopeSchema.parse(seal.original.pages[0].response.capture.scope);
 const startedAtMs=Date.now();
 const pages=await exportCapture(client,'live',seal.original.capture.sessionId,seal.throughSeq);
 const wirePages=await exportCapture(client,'wire',seal.original.capture.sessionId,seal.throughSeq);
 const request={predicate:seal.predicate,since:0,timeout_ms:2000,sessionId:seal.original.capture.sessionId,capture_scope:seal.original.pages[0].response.capture.scope};
 const freshVerdict=await client.call('reticle_assert',request);
 return {seal,startedAtMs,completedAtMs:Date.now(),pages,wirePages,request,freshVerdict};
}
export function assessSealedCapture(result:Obj){
 try{
  SealedCaptureSchema.parse(result);
  const {seal}=result,original=seal.original;const faults:string[]=[];
  if(seal.schema!=='r88.causal-seal.v1'||hash(original)!==seal.originalSha256||hash(seal.predicate)!==seal.predicateSha256)faults.push('sealed original/predicate changed');
  if(!Number.isSafeInteger(seal.throughSeq)||seal.throughSeq!==original.wire.length-1||seal.throughSeq!==original.wire.at(-1)?.seq)faults.push('seal narrowed or rebased original raw window');
  if(!Number.isSafeInteger(result.startedAtMs)||!Number.isSafeInteger(result.completedAtMs)||seal.sealedAtMs!==original.capture.observedAtMs||result.startedAtMs<seal.sealedAtMs||result.completedAtMs<result.startedAtMs)faults.push('observation endpoint changed/invalid drain times');
  if(!same(result.request,{predicate:seal.predicate,since:0,timeout_ms:2000,sessionId:original.capture.sessionId,capture_scope:original.pages[0].response.capture.scope}))faults.push('fresh predicate/window changed');
  if(result.freshVerdict?.verified!=='yes'||result.freshVerdict?.pass!==true)faults.push('fresh native verdict must also be yes AND true');
  if(!same(result.freshVerdict.capture_scope,result.request.capture_scope))faults.push('fresh native lifetime binding missing/changed');
  // The unchanged prefix gate still refuses the late-event gap. Only receipt incompleteness
  // can be repaired; malformed pages, payloads, loss markers and lifecycle faults remain fatal.
  const initial=assessCompleteCapture(original);
  const materialisable=new Set(['unfiltered wire incomplete/late event','retained window missing producer events']);
  // Only a verified exact application prefix can have its missing suffix materialised.
  const initialEvents=original.pages.flatMap((p:Obj)=>p.response.events),finalEvents=result.pages.flatMap((p:Obj)=>p.response.events);
  if(initialEvents.length<=finalEvents.length&&same(initialEvents,finalEvents.slice(0,initialEvents.length)))materialisable.add('live evidence incomplete');
  faults.push(...initial.faults.filter((f:string)=>!materialisable.has(f)));
  if(original.exportFailure)faults.push('original export refused');
  for(const rows of [result.pages,result.wirePages])for(const row of rows){
   if(row.request.export_page.through_seq!==seal.throughSeq||row.response.capture.through_seq!==seal.throughSeq||row.request.sessionId!==original.capture.sessionId||!same(row.response.capture.scope,result.request.capture_scope))faults.push('drain sequence/session binding');
  }
  const derived={...original,pages:result.pages,wirePages:result.wirePages};
  const assessment=assessCompleteCapture(derived);faults.push(...assessment.faults);
  const freshAssessment=assessCompleteCapture({...derived,verdict:result.freshVerdict});faults.push(...freshAssessment.faults);
  return {...assessment,accepted:faults.length===0,faults:[...new Set(faults)],initialAssessment:initial,originalSha256:seal.originalSha256,throughSeq:seal.throughSeq};
 }catch(e){return {accepted:false,faults:['malformed causal seal: '+String(e)]};}
}
