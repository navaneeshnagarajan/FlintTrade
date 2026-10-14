import path from 'node:path';
import {fileURLToPath} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url));
const appRoot=process.env.FLINTTRADE_E2E_SOURCE_ROOT;
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {once} from 'node:events';
import {createRequire} from 'node:module';
import fs from 'node:fs/promises';
const C=process.env.RETICLE_TEST_ROOT,require=createRequire(C+'/@reticlehq/server/package.json');
const {WebSocket}=require('ws'),{z}=require('zod');
const {startDaemon,TOOLS}=await import(C+'/@reticlehq/server/dist/index.js');
const {RETICLE_PROTOCOL_VERSION}=await import(C+'/@reticlehq/core/dist/index.js');
const budget={maxEvents:10000,maxAgeMs:120000,maxBytes:33554432};
const {Session}=await import(C+'/@reticlehq/server/dist/portal/session/session.js');
function local(retention=budget){let now=0;const session=new Session({kind:'hello',protocolVersion:RETICLE_PROTOCOL_VERSION,sessionId:'local',url:'http://localhost/',title:'fixture',adapters:[]},{readyState:1,send(){},close(){}},()=>now,retention);return {session,time:t=>now=t,push:(seq,documentId='doc',editEpoch=0)=>session.pushEvent({sessionId:'[REDACTED]',documentId,editEpoch,seq,t:now,type:'hud.used',data:{view:'expanded',panel:'chat'}})};}
test('wire capture refuses document replacement even when only HUD observed it',()=>{const f=local();f.push(0);f.push(1,'changed');assert.throws(()=>f.session.exportWireCapture(2000,{}),/lifecycle/);});
test('wire capture refuses code-incarnation change even when only HUD observed it',()=>{const f=local();f.push(0);f.push(1,'doc',1);assert.throws(()=>f.session.exportWireCapture(2000,{}),/lifecycle/);});
test('wire capture stays unavailable when normal daemon omitted explicit profile',async()=>{await fixture(async({send,observe})=>{await send('hud.used',{view:'expanded',panel:'chat'});await assert.rejects(observe({since:0,max_events:2000,export_page:{stream:'wire'}}),/explicit captureRetention/);},null);});
const tool=TOOLS.find(t=>t.name==='reticle_observe');
const wait=async f=>{for(let i=0;i<500;i++){if(f())return;await new Promise(r=>setTimeout(r,5));}throw Error('receipt deadline');};
async function fixture(fn,retention=budget){
 const root=await fs.mkdtemp('/run/test/r88-wire-');
 const daemon=await startDaemon({port:0,token:'r88-wire',reticleRoot:root,pairingTokenDir:root,...(retention===null?{}:{captureRetention:retention})});
 let ws;
 try{
  const port=await daemon.bridge.ready;ws=new WebSocket(`ws://127.0.0.1:${port}/reticle`,{origin:'http://localhost'});await once(ws,'open');
  ws.send(JSON.stringify({kind:'hello',protocolVersion:RETICLE_PROTOCOL_VERSION,sessionId:'wire',url:'http://localhost/',title:'wire',adapters:[],token:'r88-wire',sdkVersion:'3.6.0'}));await wait(()=>daemon.bridge.sessions.all().length===1);
  const session=daemon.bridge.sessions.all()[0];let seq=0;const sent=[];
  const send=async(type,data)=>{const event={sessionId:'[REDACTED]',documentId:'doc',editEpoch:0,seq:seq++,t:17+seq,type,data};sent.push(event);ws.send(JSON.stringify({kind:'event',event}));await new Promise(r=>setTimeout(r,10));return event;};
  const observe=async(request)=>tool.handler({sessions:daemon.bridge.sessions},z.object(tool.inputSchema).parse(request));
  await fn({session,send,sent,observe});
 }finally{if(ws&&ws.readyState!==WebSocket.CLOSED){const end=once(ws,'close');ws.close();await end;}await daemon.close();}
}
test('auto-end invalidates old cursors but a same-transport revival retains the original full window',()=>{const f=local();f.push(0);f.push(1);const old=f.session.exportWireCapture(1,{}).capture.next_cursor;f.session.autoEnd();assert.throws(()=>f.session.exportWireCapture(1,{}),/lifecycle/);f.session.markAgentActivity();f.push(2);assert.throws(()=>f.session.exportWireCapture(1,{cursor:old}),/signature|lifecycle/);assert.deepEqual(f.session.exportWireCapture(2000,{}).records.map(r=>r.event.seq),[0,1,2]);});
const {findContradictions}=await import(C+'/@reticlehq/engine/dist/disagreement/contradictions.js');
test('HUD cannot settle, satisfy a signal, or erase state-versus-render contradictions',async()=>{await fixture(async({session,send,observe})=>{const heard=[];const off=session.onEvent(e=>heard.push(e));await send('state.change',{store:'app',path:'todos'});const before=findContradictions(session.eventsSince(0),{actionSince:0});assert(before.some(c=>c.kind==='state-vs-render'));await send('hud.used',{view:'expanded',panel:'chat'});assert.deepEqual(findContradictions(session.eventsSince(0),{actionSince:0}),before);assert.equal(heard.length,1);assert(!session.eventsSince(0).some(e=>e.type==='hud.used'));const page=await observe({since:0,max_events:2000,export_page:{stream:'wire'}});assert(page.records.some(r=>r.kind==='instrumenter'));off();});});
test('HUD cannot erase genuine denied-write plus custom-success contradiction',async()=>{await fixture(async({session,send})=>{await send('signal',{name:'orders:saved',payload:{saved:true}});await send('net.request',{id:'denied',url:'/api/orders',method:'POST',status:403,ok:false});const before=findContradictions(session.eventsSince(0),{actionSince:0});assert(before.some(c=>c.kind==='signal-contradicted'));await send('hud.used',{view:'expanded',panel:'chat'});assert.deepEqual(findContradictions(session.eventsSince(0),{actionSince:0}),before);});});
for(const [name,retention] of [['event budget',{...budget,maxEvents:1}],['byte budget',{...budget,maxBytes:1}]])test('wire '+name+' overrun refuses even when all traffic is HUD',()=>{const f=local(retention);f.push(0);f.push(1);assert.throws(()=>f.session.exportWireCapture(2000,{}),/lost/);assert.deepEqual(f.session.eventsSince(0),[]);});
test('wire age overrun refuses without relying on an app event to evict it',()=>{const f=local({...budget,maxAgeMs:1});f.push(0);f.time(2);assert.throws(()=>f.session.exportWireCapture(2000,{}),/age/);});
test('wire signed cursor refuses tampering, changed page budget, expiry and a different session',()=>{const f=local({...budget,maxAgeMs:600000});f.push(0);f.push(1);const first=f.session.exportWireCapture(1,{}),cursor=first.capture.next_cursor;assert(cursor);assert.throws(()=>f.session.exportWireCapture(1,{cursor:cursor+'x'}),/signature/);assert.throws(()=>f.session.exportWireCapture(2,{cursor}),/budget/);const other=local();other.push(0);other.push(1);assert.throws(()=>other.session.exportWireCapture(1,{cursor}),/signature/);f.time(120001);assert.throws(()=>f.session.exportWireCapture(1,{cursor}),/expired/);});
test('wire paging cannot truncate an individually oversized record',()=>{const f=local();f.session.pushEvent({sessionId:'[REDACTED]',documentId:'doc',seq:0,t:0,type:'hud.used',data:{view:'expanded',note:'x'.repeat(500)}});assert.throws(()=>f.session.exportWireCapture(2000,{max_bytes:256}),/exceeds page/);assert.equal(f.session.exportWireCapture(2000,{}).records.length,1);});
test('explicit end and transport disconnect remain terminal capture refusals',()=>{const f=local();f.push(0);f.session.setState('ended');f.session.markAgentActivity();assert.throws(()=>f.session.exportWireCapture(2000,{}),/lifecycle/);const g=local();g.push(0);g.session.disconnect('fixture');g.session.markAgentActivity();assert.throws(()=>g.session.exportWireCapture(2000,{}),/lifecycle/);});
for(const [label,export_page] of [['wrong stream',{stream:'app'}],['null stream',{stream:null}],['unknown property',{stream:'wire',extra:true}],['oversized cursor',{stream:'wire',cursor:'x'.repeat(2049)}],['too many bytes',{stream:'wire',max_bytes:1048577}],['tiny bytes',{stream:'wire',max_bytes:255}],['string bytes',{stream:'wire',max_bytes:'256'}]])test('real tool schema rejects '+label,async()=>{await fixture(async({observe})=>assert.rejects(observe({since:0,max_events:2000,export_page})));});
test('sequence-bound causal drain includes every pre-seal receipt without restarting since zero',async()=>{await fixture(async({send,observe})=>{await send('console.info',{message:'before frozen prefix'});const prefix=await observe({since:0,max_events:2000,export_page:{stream:'wire'}});await send('perf',{metric:'longtask',value:100,at:10});const endSeq=1;await send('console.info',{message:'after declared observation endpoint'});const raw=await observe({since:0,max_events:2000,export_page:{stream:'wire',through_seq:endSeq}});const app=await observe({since:0,max_events:2000,export_page:{through_seq:endSeq}});assert.equal(prefix.records.length,1);assert.deepEqual(raw.records.map(r=>r.event.seq),[0,1]);assert.deepEqual(app.events.map(e=>e.seq),[0,1]);assert.equal(raw.capture.through_seq,endSeq);assert.equal(app.capture.through_seq,endSeq);await assert.rejects(observe({since:0,max_events:2000,export_page:{stream:'wire',through_seq:3}}),/receipt|sequence/);});});
test('full wire capture receives HUD separately without making it application evidence',async()=>{
 await fixture(async({session,send,sent,observe})=>{
  await send('signal',{name:'application-ready',payload:{}});await send('hud.used',{view:'expanded',panel:'chat'});await send('console.info',{args:['after']});
  assert.deepEqual(session.eventsSince(0).map(e=>e.type),['signal','console.info']);
  const page=await observe({since:0,max_events:2000,export_page:{stream:'wire'}});
  assert.deepEqual(page.records.map(r=>r.event),sent);
  assert.deepEqual(page.records.map(r=>r.kind),['application','instrumenter','application']);
  assert.equal(page.capture.source,'wire');assert.equal(page.capture.complete,true);assert(page.cost.bytes>=page.capture.event_bytes,'wire cost must account for received records');
  await fs.writeFile('/run/test/artifacts/r88-wire-positive.json',JSON.stringify({sent,page},null,2));
 });
});

test('R101 privacy real observe exports exact safe projection and budget',async()=>{await fixture(async({session,send,observe})=>{const marker='SYNTHETIC_R101_NOT_A_SECRET';const raw='https://user:'+marker+'@example.invalid/path?token='+marker;const event=await send('net.request',{id:'privacy',method:'GET',url:'https://example.invalid/path?token=[REDACTED]',urlRaw:raw,status:200,ok:true});const page=await observe({action:'events',since:0,max_events:2000,export_page:{stream:'wire'}});await fs.writeFile('/run/test/artifacts/r101-privacy-raw.json',JSON.stringify({event,page,privateEvent:session.eventsSince(0)[0]},null,2));assert(!JSON.stringify(page).includes(marker),'grader-only urlRaw leaked at real reticle_observe');const expected=structuredClone(event);delete expected.data.urlRaw;assert.deepEqual(page.records[0].event,expected);assert.equal(page.capture.event_bytes,Buffer.byteLength(JSON.stringify(page.records)));assert.equal(session.eventsSince(0)[0].data.urlRaw,raw,'private grader custody must remain');
const bounded=await observe({since:0,max_events:2000,export_page:{stream:'wire',max_bytes:Math.max(256,page.capture.event_bytes)}});assert.equal(bounded.records.length,1);
const live=await observe({since:0,max_events:2000,export_page:{}}),ordinary=await observe({since:0,max_events:2000});
const at=TOOLS.find(t=>t.name==='reticle_assert');const verdict=await at.handler({sessions:{resolve:()=>session,all:()=>[session]}},z.object(at.inputSchema).parse({since:0,predicate:{kind:'net',method:'GET',urlContains:marker,count:1}}));
assert.equal(verdict.verified,'yes');assert.equal(verdict.pass,true);assert(!JSON.stringify({bounded,live,ordinary,verdict}).includes(marker),'agent observe/evidence/transcript leaked raw URL');
await fs.writeFile('/run/test/artifacts/r101-privacy-agent-transcript.json',JSON.stringify({bounded,live,ordinary,verdict},null,2));});});
