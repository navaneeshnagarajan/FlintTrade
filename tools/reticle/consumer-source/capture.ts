import {withoutUrlRaw} from '../node_modules/@reticlehq/engine/dist/window/event-filters.js';
import {HelloMessageSchema,RETICLE_PROTOCOL_VERSION} from '../node_modules/@reticlehq/core/dist/index.js';
const canonical=(x:any):any=>Array.isArray(x)?x.map(canonical):x!==null&&typeof x==='object'?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
const equal=(a:any,b:any)=>JSON.stringify(canonical(a))===JSON.stringify(canonical(b));
/** The real transport reannounces on one live socket. Bridge refreshIdentity only changes
 * URL/title/adapters/capabilities. All other connection claims must remain identical. */
export function assessAnnouncements(v:any):string[]{
 const faults:string[]=[];const c=v?.capture,frames=v?.frames;
 if(!c||!Array.isArray(frames)||!frames.length||frames.length>200000)return ['full frame witness missing/over budget'];
 let first:any,previous:any;let hellos=0;const events:any[]=[];
 const immutable=(h:any)=>Object.fromEntries(Object.entries(h).filter(([k])=>!['url','title','adapters','hasCapabilities'].includes(k)));
 for(const [i,row] of frames.entries()){
  if(!row||row.index!==i||row.socket!==0||!Number.isSafeInteger(row.atMs)||row.atMs<c.startedAtMs||row.atMs>c.observedAtMs||typeof row.payload!=='string'){faults.push('raw frame lifecycle malformed');continue;}
  let m:any;try{m=JSON.parse(row.payload);}catch{faults.push('malformed raw frame');continue;}
  if(m.kind==='hello'){
   hellos++;
   if(!HelloMessageSchema.strict().safeParse(m).success||m.protocolVersion!==RETICLE_PROTOCOL_VERSION||m.sdkVersion!=='3.6.0'||typeof m.hasCapabilities!=='boolean')faults.push('malformed/source-incompatible announcement');
   if(m.sessionId!==c.sessionId)faults.push('announcement session changed');
   if(!first){first=m;if(i!==0)faults.push('first frame not HELLO');}
   else if(!equal(immutable(first),immutable(m))||previous.hasCapabilities===true&&m.hasCapabilities!==true)faults.push('announcement immutable identity changed');
   previous=m;
  }else if(m.kind==='event'){if(!first)faults.push('event before HELLO');events.push(m.event);}
  else if(m.kind!=='command_result')faults.push('unknown outbound frame');
 }
 if(hellos<1||hellos>64||hellos!==c.hellos)faults.push('announcement accounting incomplete/over budget');
 if(!equal(events,v.wire))faults.push('frame/event correspondence');
 for(const [i,e] of events.entries()){
  if(e?.seq!==i)faults.push('producer sequence reset/gap');
  if(e?.documentId!==c.documentId||!equal(e?.editEpoch,events[0]?.editEpoch))faults.push('document/incarnation changed');
 }
 return [...new Set(faults)];
}
// R88 PRIVATE successor. The immutable R52 witness still rejects multiple HELLOs.
// The caller must archive these observations and bind them to the assertion call.
type Obj = Record<string, unknown>;
const object = (x: unknown): x is Obj => x !== null && typeof x === 'object' && !Array.isArray(x);
const uint = (x: unknown): x is number => Number.isSafeInteger(x) && typeof x === 'number' && x >= 0;
const own = (x: Obj, k: string) => Object.prototype.hasOwnProperty.call(x, k);

export function assessRawCapture(value: unknown): {accepted: boolean; faults: string[]} {
  const faults: string[] = [];
  const bad = (name: string) => { faults.push(name); };
  if (!object(value)) return {accepted:false,faults:['capture envelope missing/malformed']};
  const {verdict, capture, request, observed, wire} = value;
  faults.push(...assessAnnouncements(value));
  if (!object(verdict) || verdict.verified !== 'yes' || verdict.pass !== true) bad('verdict must be yes AND true');
  if (!object(capture) || capture.schema !== 'r88.capture.v1') return {accepted:false,faults:[...faults,'capture metadata missing/malformed']};
  if (!object(request) || request.since !== 0 || request.action !== 'events' || own(request,'until') || own(request,'filters') || request.max_events !== 2000) bad('original unfiltered since:0 request required');
  if (capture.startedBeforeNavigation !== true || capture.originalSince !== 0 || capture.connectedSockets !== 1 || capture.closedSockets !== 0 || capture.socketErrors !== 0) bad('capture lifecycle incomplete/gapped');
  if (typeof capture.sessionId !== 'string' || !capture.sessionId || typeof capture.documentId !== 'string' || !capture.documentId) bad('capture identity missing/malformed');
  if (!uint(capture.observedAtMs) || !uint(capture.startedAtMs) || capture.observedAtMs < capture.startedAtMs) bad('capture time metadata missing/malformed');
  for (const [label, result] of [['verdict',verdict],['observed',observed]] as const) {
    if (!object(result)) {bad(`${label} missing/malformed`);continue;}
    if (own(result,'buffer')) {
      const b=result.buffer;
      if (!object(b) || !uint(b.held) || !uint(b.dropped) || typeof b.note !== 'string') bad(`${label} buffer malformed`);
      else if (b.dropped !== 0) bad(`${label} buffer evicted events`);
    }
    if (result.observationLost === true || own(result,'inconclusive')) bad(`${label} observation lost/inconclusive`);
    if (object(result.session) && (result.session.throttled === true || own(result.session,'versionSkew'))) bad(`${label} unhealthy session`);
  }
  if (!object(observed) || !Array.isArray(observed.events) || !object(observed.cost) || !uint(observed.cost.events) || !uint(observed.cost.bytes) || !object(observed.summary) || !uint(observed.summary.total)) return {accepted:false,faults:[...faults,'observed capture metadata missing/malformed']};
  if (own(observed.cost,'droppedOldest') && (!uint(observed.cost.droppedOldest) || observed.cost.droppedOldest !== 0)) bad('query output incomplete/malformed');
  if (observed.cost.events !== observed.events.length || observed.summary.total !== observed.events.length) bad('query count mismatch');
  if (!Array.isArray(wire) || !wire.length || !observed.events.length) return {accepted:false,faults:[...faults,'raw capture missing/empty']};
  const bySeq=new Map<number,Obj>();
  for (const event of wire) {
    if (!object(event) || !uint(event.seq) || !uint(event.t) || typeof event.type !== 'string' || !object(event.data)) {bad('raw event malformed');continue;}
    // The SDK's supported serializer redacts the credential-shaped sessionId key.
    // Bind the single socket's HELLO identity independently; never disable redaction.
    if (event.sessionId !== '[REDACTED]' || event.documentId !== capture.documentId) bad('raw capture identity changed');
    if (bySeq.has(event.seq)) bad('raw duplicate sequence');
    bySeq.set(event.seq,event);
  }
  const seqs=[...bySeq.keys()].sort((a,b)=>a-b);
  if (seqs.some((s,i)=>s!==i)) bad('producer sequence gap');
  const seen=new Set<number>();
  for (const event of observed.events) {
    if (!object(event) || !uint(event.seq) || !uint(event.t) || typeof event.type !== 'string' || !object(event.data)) {bad('retained event malformed');continue;}
    if (seen.has(event.seq)) bad('retained duplicate sequence');
    seen.add(event.seq);
    const raw=bySeq.get(event.seq);
    // The daemon re-stamps time and may defensively redact payloads; identity/type
    // correspondence is mandatory. Exact native bodies remain in the guard ledger.
    if (!raw || raw.type!==event.type || event.documentId!==capture.documentId) bad('retained/raw identity mismatch');
    if (raw && JSON.stringify((withoutUrlRaw(raw) as Obj).data)!==JSON.stringify(event.data)) bad('retained/raw payload mismatch');
    if (['transport.overflow','truncated','rate-limited'].includes(event.type)) bad('producer capture loss marker');
    if(event.type==='blind-spot' && event.data.kind==='rate-limited') bad('bridge rate-limited capture');
  }
  if (seqs.length !== seen.size || seqs.some(s=>!seen.has(s))) bad('retained window missing producer events');
  return {accepted:faults.length===0,faults:[...new Set(faults)]};
}
