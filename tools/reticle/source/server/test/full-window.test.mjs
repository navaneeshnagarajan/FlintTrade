import {test} from 'node:test';
import assert from 'node:assert/strict';
import {once} from 'node:events';
import fs from 'node:fs/promises';
import {createRequire} from 'node:module';
import {rmSync} from 'node:fs';
const ownedDirectories=[];
// Cleanup at process exit, after asynchronous journal writes have relinquished
// the event loop. Closing the socket alone is not a file-writer drain boundary.
process.once('exit',()=>{for(const dir of ownedDirectories)rmSync(dir,{recursive:true,force:true});});
import {tmpdir} from 'node:os';
import {join} from 'node:path';
process.env.RETICLE_CONNECT='0';
process.env.RETICLE_TELEMETRY='0';
const require=createRequire(import.meta.url);
const {WebSocket}=require('ws');
const {startDaemon,TOOLS}=await import('../dist/index.js');
const {z}=require('zod');
async function observe(server,args){const tool=TOOLS.find(t=>t.name==='reticle_observe');const parsed=z.object(tool.inputSchema).parse(args);return tool.handler({sessions:server.bridge.sessions},parsed);}
const {RETICLE_PROTOCOL_VERSION,RETICLE_WS_PATH}=await import('@reticlehq/core');
const budget={maxEvents:10000,maxAgeMs:120000,maxBytes:33554432};
const {Session}=await import('../dist/portal/session/session.js');
const {evaluatePredicate}=await import('@reticlehq/engine/question/predicate/predicate.js');
const {assertVerdict}=await import('../dist/surface/tools/assert/assert-verdict.js');
function localSession(retention){let now=0;let seq=0;const socket={readyState:1,send(){},close(){}};const session=new Session({kind:'hello',protocolVersion:RETICLE_PROTOCOL_VERSION,sessionId:'local',url:'http://localhost/',title:'synthetic',adapters:[]},socket,()=>now,retention);return {session,socket,time:t=>now=t,push:(type,data,byteSize)=>session.pushEvent({seq:seq++,t:now,sessionId:'local',documentId:'doc',type,data},byteSize)};}
async function judge(session,predicate){const result=await evaluatePredicate(session,predicate,0);const verdict=await assertVerdict(session,predicate,result.pass,result.evidence,0);return {...verdict.decision,pass:result.pass};}
const pause=()=>new Promise(r=>setTimeout(r,5));
async function wait(f){for(let i=0;i<1000;i++){if(f())return;await pause();}throw Error('fixture deadline');}
async function fixture(options,run){
  const dir=await fs.mkdtemp(join(tmpdir(),'reticle-capture-'));ownedDirectories.push(dir);
  const server=await startDaemon({port:0,token:'synthetic-retention-fixture',reticleRoot:dir,pairingTokenDir:dir,...options});
  let ws;
  try{
    const port=await server.bridge.ready;
    ws=new WebSocket(`ws://127.0.0.1:${port}${RETICLE_WS_PATH}`,{origin:'http://localhost'});
    await once(ws,'open');
    ws.send(JSON.stringify({kind:'hello',protocolVersion:RETICLE_PROTOCOL_VERSION,sessionId:'capture',url:'http://localhost/',title:'synthetic',adapters:[],token:'synthetic-retention-fixture',sdkVersion:'3.6.0'}));
    await wait(()=>server.bridge.sessions.all().length===1);
    const session=server.bridge.sessions.all()[0];
    const send=async(n,start=0)=>{
      for(let i=start;i<start+n;i++)ws.send(JSON.stringify({kind:'event',event:{sessionId:'[REDACTED]',documentId:'doc',seq:i,t:i,type:'console.info',data:{args:['record '+i]}}}));
      await wait(()=>session.eventsSince(0).at(-1)?.seq===start+n-1);
    };
    await run({session,send,server,ws});
  }finally{if(ws && ws.readyState!==WebSocket.CLOSED){const closed=once(ws,'close');ws.close();await closed;}await server.close();}
}
test('owned daemon passes explicit bounded retention to the actual session',async()=>{
  await fixture({captureRetention:budget},async({session,send})=>{
    await send(2101);
    assert.deepEqual(session.bufferHealth(),{total:2101,dropped:0});
    assert.deepEqual(session.eventsSince(0).map(e=>e.seq),Array.from({length:2101},(_,i)=>i));
  });
});
test('unfiltered export paginates the complete frozen prefix without narrowing since',async()=>{
  await fixture({captureRetention:budget},async({session,send,server})=>{
    await send(2101);
    const ordinary=await observe(server,{since:0,max_events:2000});
    assert.equal(ordinary.events.length,2000);assert.equal(ordinary.cost.droppedOldest,101);
    const first=await observe(server,{since:0,max_events:1000,export_page:{}});
    assert.equal(first.capture?.total,2101);
    assert.equal(first.capture.complete,false);
    const all=[...first.events];let next=first.capture.next_cursor;
    await send(3,2101); // concurrent appends must not extend this export or move its offsets
    while(next){const page=await observe(server,{since:0,max_events:1000,export_page:{cursor:next}});assert.equal(page.capture.offset,all.length);all.push(...page.events);next=page.capture.next_cursor;if(!next)assert.equal(page.capture.complete,true);}
    assert.deepEqual(all.map(e=>e.seq),Array.from({length:2101},(_,i)=>i));
    assert.equal(session.bufferHealth().dropped,0);
  });
});
test('lost exact count cannot prove itself; an independent anyOf branch still can',async()=>{
  const s=localSession();
  const exact={kind:'net',method:'GET',urlContains:'/record',count:1};
  s.push('net.request',{id:'old',method:'GET',url:'/record',status:200,ok:true});
  s.time(1);s.push('net.request',{id:'new',method:'GET',url:'/record',status:200,ok:true});
  assert.equal((await judge(s.session,exact)).verified,'no');
  s.time(60001);s.push('signal',{name:'independent',payload:{}});
  assert.equal(s.session.bufferHealth().dropped,1);
  const result=await judge(s.session,exact);
  assert.equal(result.pass,true);assert.equal(result.verified,'unknown');
  assert.equal((await judge(s.session,{kind:'allOf',predicates:[exact,{kind:'signal',name:'independent'}]})).verified,'unknown');
  assert.equal((await judge(s.session,{kind:'anyOf',predicates:[exact,{kind:'signal',name:'independent'}]})).verified,'yes');
  assert.equal((await judge(s.session,{kind:'anyOf',predicates:[exact,{kind:'signal',name:'missing'}]})).verified,'unknown');
});

for(const [name,config] of [
 ['null',null],['array',[]],['missing',{}],['extra',{...budget,unbounded:true}],
 ...['maxEvents','maxAgeMs','maxBytes'].flatMap(k=>[0,-1,1.5,Infinity,NaN,true,'10000'].map(v=>[k+' '+String(v),{...budget,[k]:v}])),
 ['count ceiling',{...budget,maxEvents:100001}],['age ceiling',{...budget,maxAgeMs:600001}],['bytes ceiling',{...budget,maxBytes:67108865}],
]) test('reject invalid explicit retention '+name,async()=>{
  assert.throws(()=>localSession(config),/captureRetention/);
  await assert.rejects(startDaemon({port:0,captureRetention:config}),/captureRetention/);
});
test('daemon defaults and ordinary output budgets are unchanged',async()=>{
  await fixture({},async({session,send,server})=>{
    await send(2101);assert.deepEqual(session.bufferHealth(),{total:2000,dropped:101});
    assert.deepEqual(session.retention,{maxEvents:2000,maxAgeMs:60000,maxBytes:8388608});
    assert.equal((await observe(server,{since:0})).events.length,200);
    await assert.rejects(observe(server,{since:0,max_events:10000}));
    await assert.rejects(observe(server,{since:0,export_page:{}}),/lost events/);
  });
});
test('supported daemon environment reaches real retained sessions',async()=>{
  process.env.RETICLE_CAPTURE_RETENTION=JSON.stringify(budget);
  try{await fixture({},async({session,send})=>{await send(2101);assert.equal(session.bufferHealth().dropped,0);assert.deepEqual(session.retention,budget);});}
  finally{delete process.env.RETICLE_CAPTURE_RETENTION;}
  for(const value of ['not JSON','{}','null','{"maxEvents":false}']){
    process.env.RETICLE_CAPTURE_RETENTION=value;
    try{await assert.rejects(startDaemon({port:0}),/captureRetention|RETICLE_CAPTURE_RETENTION/);}
    finally{delete process.env.RETICLE_CAPTURE_RETENTION;}
  }
});
test('age and byte retention remain bounded; loss refuses complete export',()=>{
  for(const config of [undefined,budget]){
    const s=localSession(config);s.push('console.info',{args:['before']});
    s.time(60001);s.push('console.info',{args:['after']});
    assert.equal(s.session.bufferHealth().dropped,config?0:1);
    if(config){assert.equal(s.session.exportCapture(2000,{}).capture.total,2);s.time(120001);s.push('console.info',{args:['tail']});}
    assert.throws(()=>s.session.exportCapture(2000,{}),/lost events/);
  }
  const s=localSession({...budget,maxBytes:300});
  for(let i=0;i<10;i++)s.push('console.info',{args:['x'.repeat(300)]});
  assert.equal(s.session.bufferHealth().total,1);assert.equal(s.session.bufferHealth().dropped,9);
  assert.throws(()=>s.session.exportCapture(2000,{}),/lost events/);
});
test('all emitted bytes must fit the explicit capture even for sole oversized survivor',()=>{
  const s=localSession({...budget,maxBytes:256});s.push('console.info',{args:['x'.repeat(1000)]});
  assert.equal(s.session.bufferHealth().total,1); // preserve the published soft-cap sole survivor
  assert.throws(()=>s.session.exportCapture(2000,{}),/byte budget/);
});
test('paged output respects bytes and refuses oversized events without truncation',()=>{
  const s=localSession(budget);for(let i=0;i<10;i++)s.push('console.info',{args:['x'.repeat(100)]});
  const page=s.session.exportCapture(2000,{max_bytes:512});assert.ok(page.events.length<10);assert.ok(page.capture.event_bytes<=512);
  assert.equal(page.capture.complete,false);assert.equal(s.session.bufferHealth().dropped,0);
  const big=localSession(budget);big.push('console.info',{args:['x'.repeat(2000)]});
  assert.throws(()=>big.session.exportCapture(2000,{max_bytes:256}),/no event was truncated/);
  assert.equal(big.session.exportCapture(2000,{}).events.length,1);
});
test('cursor is session and scope bound, expiring and tamper evident',async()=>{
  const a=localSession(budget),b=localSession(budget);for(const s of [a,b])for(let i=0;i<5;i++)s.push('console.info',{args:[i]});
  const first=a.session.exportCapture(2,{}),cursor=first.capture.next_cursor;
  assert.throws(()=>b.session.exportCapture(2,{cursor}),/another session/);
  assert.throws(()=>a.session.exportCapture(2,{cursor:cursor+'x'}),/altered/);
  assert.throws(()=>a.session.exportCapture(3,{cursor}),/window changed/);
  assert.throws(()=>a.session.exportCapture(2,{cursor,max_bytes:1024}),/window changed/);
  a.time(120001);assert.throws(()=>a.session.exportCapture(2,{cursor}),/age budget|expired/);
  const c=localSession({...budget,maxAgeMs:600000});for(let i=0;i<3;i++)c.push('console.info',{args:[i]});const cc=c.session.exportCapture(1,{}).capture.next_cursor;c.time(120001);assert.throws(()=>c.session.exportCapture(1,{cursor:cc}),/expired/);
});
test('cursor does not revive after an ended session or document round trip',()=>{
  const a=localSession(budget);for(let i=0;i<4;i++)a.push('console.info',{args:[i]});
  const cursor=a.session.exportCapture(1,{}).capture.next_cursor;
  a.session.setState('ended');assert.throws(()=>a.session.exportCapture(1,{cursor}),/not live/);
  a.session.setState('active');assert.throws(()=>a.session.exportCapture(1,{cursor}),/another session/);
  const b=localSession(budget);for(let i=0;i<4;i++)b.push('console.info',{args:[i]});const cb=b.session.exportCapture(1,{}).capture.next_cursor;
  b.session.pushEvent({seq:4,t:0,type:'console.info',sessionId:'local',documentId:'next',data:{args:[]}});
  b.push('console.info',{args:[]});
  assert.throws(()=>b.session.exportCapture(1,{cursor:cb}),/another session/);
});
test('export rejects filtered or narrowed scope and invalid page arguments',async()=>{
  await fixture({captureRetention:budget},async({send,server})=>{
    await send(5);
    for(const change of [{since:1},{until:5},{filters:[]},{actionId:'a1'},{window_ms:3}])await assert.rejects(observe(server,{since:0,export_page:{},...change}),/original unfiltered/);
    for(const page of [null,[],{extra:true},{max_bytes:0},{max_bytes:1048577},{cursor:8}])await assert.rejects(observe(server,{since:0,export_page:page}));
  });
});
