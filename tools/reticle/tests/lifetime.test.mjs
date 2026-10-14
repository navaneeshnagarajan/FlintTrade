import path from 'node:path';
import {fileURLToPath} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url));
const appRoot=process.env.FLINTTRADE_E2E_SOURCE_ROOT;
import {test,before,after} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import http from 'node:http';
import {once} from 'node:events';
import {createRequire} from 'node:module';
const C=process.env.RETICLE_TEST_ROOT,require=createRequire(C+'/@reticlehq/server/package.json');
const {chromium}=require(appRoot+'/packages/apps/terminal/node_modules/@playwright/test');
const {z}=require('zod');
const {startDaemon,TOOLS}=await import(C+'/@reticlehq/server/dist/index.js');
const {RETICLE_PROTOCOL_VERSION}=await import(C+'/@reticlehq/core/dist/index.js');
let browser,server,daemon;let ordinal=0;
const wait=async f=>{for(let i=0;i<400;i++){if(f())return;await new Promise(r=>setTimeout(r,5));}throw Error('real seam deadline');};
before(async()=>{server=http.createServer((req,res)=>{res.setHeader('Content-Type','text/html');res.end('<!doctype html><title>owned fixture</title><main>real browser lifecycle</main>');});server.listen(5173,'127.0.0.1');await once(server,'listening');daemon=await startDaemon({port:4400,token:'synthetic-r101',reticleRoot:'/run/test/r101-life',pairingTokenDir:'/run/test/r101-token',captureRetention:{maxEvents:10000,maxAgeMs:120000,maxBytes:33554432}});await daemon.bridge.ready;browser=await chromium.launch({headless:true});});
after(async()=>{await browser?.close();await daemon?.close();if(server)await new Promise(r=>server.close(r));});
const call=async(name,args)=>{const t=TOOLS.find(t=>t.name===name);return t.handler({sessions:daemon.bridge.sessions},z.object(t.inputSchema).parse(args));};
async function fixture(fn){
 const ctx=await browser.newContext({serviceWorkers:'block'}),page=await ctx.newPage();const id='life-'+ordinal++,frames=[],startedAtMs=Date.now();
 page.on('websocket',ws=>ws.on('framesent',f=>frames.push({at:Date.now(),payload:f.payload.toString()})));
 async function connect(sessionId,doc='first',signal='ready'){
  await page.goto('http://127.0.0.1:5173/');
  await page.evaluate(async({sessionId,doc,signal,protocol})=>{let seq=0;window.ws=new WebSocket('ws://127.0.0.1:4400/reticle');await new Promise(r=>window.ws.onopen=r);window.hello={kind:'hello',protocolVersion:protocol,sessionId,url:location.href,title:'owned fixture',adapters:[],token:'synthetic-r101',sdkVersion:'3.6.0',hasCapabilities:false};window.ws.send(JSON.stringify(window.hello));window.emit=(name,documentId=doc,editEpoch=0)=>window.ws.send(JSON.stringify({kind:'event',event:{sessionId:'[REDACTED]',documentId,editEpoch,seq:seq++,t:seq,type:'signal',data:{name,payload:{}}}}));window.emit(signal);},{sessionId,doc,signal,protocol:RETICLE_PROTOCOL_VERSION});
  await wait(()=>daemon.bridge.sessions.all().some(s=>s.id===sessionId&&s.eventsSince(0).some(e=>e.data.name===signal)));
 }
 try{await connect(id);const session=daemon.bridge.sessions.all().find(s=>s.id===id);const app=await call('reticle_observe',{since:0,max_events:2000,sessionId:id,export_page:{}});const wire=await call('reticle_observe',{since:0,max_events:2000,sessionId:id,export_page:{stream:'wire'}});const scope=app.capture.scope??{sessionId:id,incarnation:wire.capture.id,documentId:'first',editEpoch:0};await fn({page,id,session,connect,scope,frames,app,wire,startedAtMs});}finally{await ctx.close();}
}
for(const during of [false,true])for(const sameId of [false,true])test('strict native lifetime rejects '+(during?'during evaluation ':'after exports ')+(sameId?'same-id reload':'successor'),async()=>fixture(async({id,session,connect,scope,frames})=>{
 const name=during?'future':'ready';const request={sessionId:id,since:0,timeout_ms:2000,predicate:{kind:'signal',name,count:1},capture_scope:scope};let result,error;
 if(during){let entered=false;const original=session.onEvent.bind(session);session.onEvent=f=>{entered=true;return original(f);};const task=call('reticle_assert',request).then(r=>{result=r;},e=>{error=String(e);});await wait(()=>entered);await connect(sameId?id:id+'-new','second',name);await task;}
 else{await connect(sameId?id:id+'-new','second',name);try{result=await call('reticle_assert',request);}catch(e){error=String(e);}}
 await fs.writeFile('/run/test/artifacts/r101-life-'+during+'-'+sameId+'.json',JSON.stringify({request,result,error,frames},null,2));
 assert(error||result?.verified!=='yes'||result?.pass!==true,'replacement was accepted as original-lifetime yes/true');
}));
for(const change of ['document','epoch'])test('strict native lifetime rejects same-socket '+change+' drift during evaluation',async()=>fixture(async({page,id,session,scope,frames})=>{
 let entered=false;const on=session.onEvent.bind(session);session.onEvent=f=>{entered=true;return on(f);};let result,error;
 const task=call('reticle_assert',{sessionId:id,since:0,timeout_ms:2000,predicate:{kind:'signal',name:'future',count:1},capture_scope:scope}).then(r=>{result=r;},e=>{error=String(e);});await wait(()=>entered);
 await page.evaluate(change=>window.emit('future',change==='document'?'second':'first',change==='epoch'?1:0),change);await task;
 await fs.writeFile('/run/test/artifacts/r101-life-'+change+'.json',JSON.stringify({scope,result,error,frames},null,2));assert(error||result?.verified!=='yes'||result?.pass!==true,'scope drift was accepted');
}));
for(const control of ['unchanged','capability HELLO','idle revival'])test('strict native lifetime preserves '+control,async()=>fixture(async({page,id,session,scope})=>{
 if(control==='capability HELLO'){await page.evaluate(()=>window.ws.send(JSON.stringify({...window.hello,hasCapabilities:true})));await wait(()=>session.hasCapabilities===true);}
 if(control==='idle revival')session.autoEnd();
 const result=await call('reticle_assert',{sessionId:id,since:0,timeout_ms:2000,predicate:{kind:'signal',name:'ready',count:1},capture_scope:scope});assert.equal(result.verified,'yes');assert.equal(result.pass,true);
 assert.deepEqual(result.capture_scope,scope);
}));
test('ordinary default assertion still follows a successor',async()=>fixture(async({id,connect})=>{await connect(id+'-new','second');const result=await call('reticle_assert',{sessionId:id,since:0,timeout_ms:2000,predicate:{kind:'signal',name:'ready',count:1}});assert.equal(result.verified,'yes');assert.equal(result.pass,true);}));

test('R83 endpoint excludes event injected during supplemental wire export',async()=>{
 
 const packages=await fs.readdir(appRoot+'/node_modules/.pnpm');
 const esbuild=require(appRoot+'/node_modules/.pnpm/'+packages.find(n=>n.startsWith('esbuild@'))+'/node_modules/esbuild');
 const out='/run/test/endpoint-witness.mjs';await esbuild.build({entryPoints:[here+'/../runtime/consumer/witness.mjs'],outfile:out,bundle:true,platform:'node',format:'esm',packages:'external',external:[C+'/*']});
 const {startWitness,finishWitness}=await import(out);
 const ctx=await browser.newContext({serviceWorkers:'block'}),page=await ctx.newPage();const name='endpoint',info={testId:name,outputPath:n=>'/run/test/artifacts/'+n};startWitness(page,info);
 try{
  await page.goto('http://127.0.0.1:5173/');await page.evaluate(async protocol=>{let seq=0;window.ws=new WebSocket('ws://127.0.0.1:4400/reticle');await new Promise(r=>window.ws.onopen=r);window.ws.send(JSON.stringify({kind:'hello',protocolVersion:protocol,sessionId:'endpoint',url:location.href,title:'endpoint',adapters:[],token:'synthetic-r101',sdkVersion:'3.6.0',hasCapabilities:false}));window.emit=name=>window.ws.send(JSON.stringify({kind:'event',event:{sessionId:'[REDACTED]',documentId:'enddoc',editEpoch:0,seq:seq++,t:seq,type:'signal',data:{name,payload:{}}}}));window.emit('ready');window.emit('before-original-endpoint');},RETICLE_PROTOCOL_VERSION);
  await wait(()=>daemon.bridge.sessions.all().some(s=>s.id==='endpoint'&&s.eventsSince(0).length===2));
  const predicate={kind:'signal',name:'ready',count:1};const verdict=await call('reticle_assert',{sessionId:'endpoint',since:0,predicate});let injected=false;
  const client={call:async(n,q)=>{if(n==='reticle_observe'&&q.export_page?.stream==='wire'&&!injected){injected=true;await page.evaluate(()=>window.emit('during-supplemental-export'));await wait(()=>daemon.bridge.sessions.all().find(s=>s.id==='endpoint').eventsSince(0).length===3);}return call(n,q);}};
  const assessment=await finishWitness(client,verdict,info,name,predicate);
  const packet=JSON.parse(await fs.readFile(info.outputPath(name+'-full-window.json'),'utf8'));
  assert(packet.envelope.wire.some(e=>e.data.name==='before-original-endpoint'));
  assert(!packet.envelope.wire.some(e=>e.data.name==='during-supplemental-export'),'supplemental await extended the original endpoint');
  assert.equal(packet.materialization.seal.throughSeq,1);assert.equal(assessment.accepted,true,JSON.stringify(assessment));
 }finally{await ctx.close();}
});

test('relocated consumers preserve raw native boundaries',async t=>{
 const {assessCompleteCapture}=await import(here+'/../runtime/consumer/paged-capture.mjs');
 const {validateCaptureEnvelope,NativeVerdictSchema}=await import(here+'/../runtime/consumer/boundaries.mjs');
 // This fixture is this invocation's actual endpoint control, not an archived app packet.
 const packet=JSON.parse(await fs.readFile('/run/test/artifacts/endpoint-full-window.json','utf8'));
 const v={...packet.envelope,pages:packet.materialization.pages,wirePages:packet.materialization.wirePages};
 assert.equal(assessCompleteCapture(v).accepted,true);
 await t.test('raw identity unknown keys nested arrays and absent loss',()=>{
  const value=structuredClone(v);value.nativeUnknown={array:[null,false,{deeper:['x']}]};value.verdict.nativeUnknown=[1,null,{x:true}];value.wirePages[0].response.nativeUnknown={unfiltered:[1,2]};const before=JSON.stringify(value);
  assert.strictEqual(validateCaptureEnvelope(value),value);assert.equal(JSON.stringify(value),before);assert.deepEqual(NativeVerdictSchema.parse(value.verdict),value.verdict);assert(!Object.hasOwn(value.verdict,'buffer'));
 });
 for(const [name,edit] of [
  ['null loss',x=>x.wirePages[0].response.cost.droppedOldest=null],
  ['null buffer',x=>x.verdict.buffer=null],['array buffer',x=>x.verdict.buffer=[]],['array session',x=>x.verdict.session=[]],['null session',x=>x.verdict.session=null],
  ['string loss',x=>x.wirePages[0].response.cost.droppedOldest='0'],['boolean loss',x=>x.wirePages[0].response.cost.droppedOldest=false],['positive loss',x=>x.wirePages[0].response.cost.droppedOldest=1],
  ['positive wrong count',x=>x.wirePages[0].response.capture.count++],['metadata null',x=>x.wirePages[0].response.capture=null],['receipt array',x=>x.wirePages[0].response.records[0]=[]],['event array',x=>x.wirePages[0].response.records[0].event=[]],
  ['unknown native verdict',x=>x.verdict.verified='unrecognised'],['native unknown',x=>x.verdict.verified='unknown'],['native no true',x=>x.verdict.verified='no'],['native yes false',x=>x.verdict.pass=false],
  ['private URL in receipt',x=>x.wirePages[0].response.records[0].event.data.urlRaw='synthetic'],['changed other raw field',x=>x.wirePages[0].response.records[0].event.data.extra='unmatched'],
 ])await t.test('refuses '+name,()=>{const value=structuredClone(v);edit(value);assert.equal(assessCompleteCapture(value).accepted,false);});
});

for(const sameId of [false,true])test('full causal seal refuses actual post-export '+(sameId?'same-id reload':'successor'),async()=>fixture(async({id,connect,frames,app,wire,startedAtMs})=>{
 const {sealOriginalWindow,materializeSeal,assessSealedCapture}=await import(here+'/../runtime/consumer/seal.mjs');
 const predicate={kind:'signal',name:'ready',count:1},verdict=await call('reticle_assert',{sessionId:id,since:0,predicate});
 const raw=frames.map((f,index)=>({socket:0,index,atMs:f.at,payload:f.payload}));const events=raw.map(f=>JSON.parse(f.payload)).filter(f=>f.kind==='event').map(f=>f.event);
 const request=stream=>({action:'events',since:0,max_events:2000,sessionId:id,export_page:stream==='wire'?{stream}:{}});
 const original={verdict,wire:events,frames:raw,pages:[{request:request('live'),response:app}],wirePages:[{request:request('wire'),response:wire}],capture:{schema:'r88.capture.v1',startedBeforeNavigation:true,originalSince:0,startedAtMs,observedAtMs:Date.now(),connectedSockets:1,closedSockets:0,socketErrors:0,hellos:1,sessionId:id,documentId:events[0].documentId,serverIncarnation:wire.capture.id}};
 const seal=sealOriginalWindow(original,predicate);let error,result,assessment;const client={call:async(n,q)=>{if(n==='reticle_assert')await connect(sameId?id:id+'-new','second');return call(n,q);}};
 try{result=await materializeSeal(client,seal);assessment=assessSealedCapture(result);}catch(e){error=String(e);}
 await fs.writeFile('/run/test/artifacts/r101-full-seal-'+sameId+'.json',JSON.stringify({seal,result,assessment,error,frames},null,2));assert(error||!assessment.accepted,'successor native yes/true accepted by the complete seal gate');
}));
