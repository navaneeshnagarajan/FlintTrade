// Passive query-owner/timer provenance for the original isolated browser cases.
// No query functions, clocks, options, results, stores or responses are replaced.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {createHash} from 'node:crypto';

export const PERIODIC_READS = Object.freeze({
  '/ft-api/api/v1/ping': {key:'["operator","ping"]', cadence:1500, attempts:1, caller:'/src/lib/operatorProbes.ts', name:'probeLocalPing'},
  '/ft-api/health': {key:'["operator","health"]', cadence:30000, attempts:1, caller:'/src/lib/operatorProbes.ts', name:'probeDeskHealth'},
  '/ft-api/api/v1/native/accounts': {key:'["broker","accounts"]', cadence:10000, attempts:3, caller:'/src/hooks/useBrokerAccounts.ts', name:'queryFn'},
});
const probes = [
  ['subscribe',2173,2,'if (this.listeners.size === 1) {'],
  ['unsubscribe',2181,2,'if (!this.hasListeners()) this.destroy();'],
  ['destroy',2207,2,'this.listeners = /* @__PURE__ */ new Set();'],
  ['execute',2383,2,'this.#updateQuery();'],
  ['schedule',2407,2,'this.#refetchIntervalId = timeoutManager.setInterval(() => {'],
  ['interval',2408,3,'if (this.options.refetchIntervalInBackground || focusManager.isFocused()) this.#executeFetch();'],
  ['clear',2422,2,'if (this.#refetchIntervalId !== void 0) {'],
  ['fetch',1913,3,'return queryFn(queryFnContext);'],
];

/** Pure admission over independently captured native facts; errors never reset. */
export function admitPeriodic(facts, contract, used, now, deadline) {
  const {request, fetch, execute, interval, schedule, current} = facts;
  assert.equal(request.method,'GET','periodic method');
  assert.equal(request.url,contract.url,'periodic exact URL');
  assert.equal(request.body,null,'periodic body');
  assert.equal(request.scope,contract.scope,'periodic scope');
  assert.equal(request.document,contract.document,'periodic document');
  assert.ok(now < deadline,'periodic deadline');
  assert.equal(fetch.key,contract.key,'periodic query');
  assert.equal(fetch.query,execute.query,'periodic query owner');
  assert.equal(execute.owner,interval.owner,'periodic timer owner');
  assert.equal(execute.generation,interval.generation,'periodic timer generation');
  assert.equal(interval.generation,schedule.generation,'periodic schedule generation');
  assert.equal(interval.owner,schedule.owner,'periodic schedule owner');
  assert.equal(interval.query,schedule.query,'periodic scheduled query');
  assert.equal(interval.cadence,contract.cadence,'periodic cadence');
  assert.equal(schedule.cadence,contract.cadence,'periodic scheduled cadence');
  assert.ok(Number.isSafeInteger(interval.timer) && interval.timer > 0,'periodic native timer');
  assert.ok(interval.time - schedule.time >= contract.cadence,'periodic early callback');
  assert.ok(execute.time >= interval.time && fetch.time >= execute.time,'periodic causal order');
  assert.equal(execute.listeners,1,'periodic subscribed owner');
  assert.equal(execute.activeObservers,1,'periodic unique observer');
  assert.equal(current.owner,execute.owner,'periodic current owner');
  assert.equal(current.query,execute.query,'periodic current query');
  assert.equal(current.retired,false,'periodic retired owner');
  assert.ok(Number.isSafeInteger(fetch.failures) && fetch.failures >= 0 && fetch.failures < contract.attempts,'periodic retry bound');
  assert.equal(request.caller,true,'periodic native caller');
  const id = `${request.document}:${execute.query}:${execute.serial}:${fetch.failures}`;
  assert.ok(!used.has(id),'periodic duplicate attempt');
  assert.ok(!used.has('request:'+request.id),'periodic duplicate correlation');
  assert.ok(used.size / 2 < Math.floor(contract.windowMs / contract.cadence) * contract.attempts,'periodic finite ceiling');
  used.add(id); used.add('request:'+request.id);
  return true;
}

/** Join the actual browser response with its native CDP exchange. */
export function corroboratePeriodicWire(native, headers, status, wireIds) {
  assert.ok(native,'periodic correlated native response missing');
  const id=headers['x-diagnostic-request-id'];
  assert.ok(id,'periodic server correlation missing');
  assert.equal(Object.entries(native.headers).find(([key])=>key.toLowerCase()==='x-diagnostic-request-id')?.[1],id,'periodic swapped native correlation');
  assert.ok(!wireIds.has(id),'periodic duplicate server correlation');
  assert.equal(native.status,status,'periodic native response status');
  wireIds.add(id);
  return id;
}

export async function installPeriodicReadProbe(page, cdp, info) {
  const evidence = {caseId:info.testId,title:info.title,windowMs:info.timeout,events:[],network:[],sources:[],resolved:[],admissions:[],errors:[]};
  const started = Date.now(), deadline = started + info.timeout;
  let document, scope, retired = false;
  const used = new Map(Object.keys(PERIODIC_READS).map(path=>[path,new Set()]));
  const matched = new Set();
  const responses = new Map(), completions = [], wireIds = new Set(), nativeFailures = new Map();
  await cdp.send('Runtime.enable');
  await cdp.send('Runtime.addBinding',{name:'__periodicReadBinding'});
  cdp.on('Runtime.bindingCalled',event=>{
    if(event.name==='__periodicReadBinding') evidence.events.push({...JSON.parse(event.payload),context:event.executionContextId});
  });
  cdp.on('Debugger.scriptParsed',event=>{
    if(/\/modern-DufwN3iA\.js(?:\?|$)/.test(event.url)) void cdp.send('Debugger.getScriptSource',{scriptId:event.scriptId}).then(({scriptSource})=>{
      const verified=probes.every(([,line,,text])=>scriptSource.split('\n')[line]?.trim()===text);
      evidence.sources.push({scriptId:event.scriptId,url:event.url,sha256:createHash('sha256').update(scriptSource).digest('hex'),verified});
      if(!verified)evidence.errors.push('Query observer source pin mismatch');
    }).catch(error=>evidence.errors.push(String(error)));
  });
  cdp.on('Network.requestWillBeSent',event=>{
    if(Object.hasOwn(PERIODIC_READS,new URL(event.request.url).pathname)) evidence.network.push(event);
  });
  cdp.on('Network.responseReceived',event=>responses.set(event.requestId,event.response));
  cdp.on('Network.loadingFailed',event=>nativeFailures.set(event.requestId,event));
  await page.addInitScript(()=>{
    const ids=new WeakMap(), queries=new WeakMap(), states=new WeakMap(), executions=new WeakMap();
    let next=0,nextQuery=0,serial=0;
    const queryId=query=>{if(!queries.has(query))queries.set(query,++nextQuery);return queries.get(query);};
    Object.defineProperty(globalThis,'__periodicReadObservation',{value:{record(owner,phase,timer,cadence){
      const key=JSON.stringify(owner.options?.queryKey);
      if(!['["operator","ping"]','["operator","health"]','["broker","accounts"]'].includes(key))return;
      const query=phase==='fetch'?owner:owner.getCurrentQuery();
      if(!query)return;
      if(!ids.has(owner))ids.set(owner,++next);
      const state=states.get(owner)??{generation:0}; states.set(owner,state);
      if(phase==='schedule')state.generation++;
      const row={serial:++serial,phase,key,owner:ids.get(owner),query:queryId(query),generation:state.generation,
        timer,cadence,time:performance.now(),wall:Date.now(),listeners:owner.listeners?.size,
        observers:query.getObserversCount(),activeObservers:query.observers.filter(o=>o.options.enabled!==false && o.hasListeners()).length,failures:query.state.fetchFailureCount,fetchStatus:query.state.fetchStatus,
        scope:sessionStorage.getItem('flinttrade:auth-session'),url:location.href,
        execution:phase==='fetch'?executions.get(query):undefined};
      if(phase==='execute' && query.state.fetchStatus!=='fetching') executions.set(query,row.serial);
      globalThis.__periodicReadBinding(JSON.stringify(row));
    }},writable:false});
  });
  for(const [phase,lineNumber,columnNumber] of probes){
    const args=phase==='fetch'?`this,${JSON.stringify(phase)},null,null`:`this,${JSON.stringify(phase)},this.#refetchIntervalId,this.#currentRefetchInterval`;
    const result=await cdp.send('Debugger.setBreakpointByUrl',{
      urlRegex:String.raw`^http://127\.0\.0\.1:5173/@fs/run/test/cache/qualified-vite/deps/modern-DufwN3iA\.js(?:\?.*)?$`,
      lineNumber,columnNumber,condition:`(globalThis.__periodicReadObservation?.record(${args}),false)`,
    });
    evidence.resolved.push({phase,...result});
  }
  function frames(stack){return stack?[...(stack.callFrames??[]),...frames(stack.parent)]:[];}
  return {
    bindScope(value){assert.equal(scope,undefined,'periodic scope bound twice');scope=value;},
    async classify(request){
      try {
        assert.equal(retired,false,'periodic case retired');
        assert.ok(Date.now()<deadline,'periodic case deadline');
        const path=new URL(request.url()).pathname;
        const contract=PERIODIC_READS[path]; assert.ok(contract,'periodic exact registered path');
        assert.equal(request.url(),'http://127.0.0.1:5173'+path,'periodic exact URL');
        assert.equal(request.method(),'GET'); assert.equal(request.postData(),null);
        // Flush this CDP connection, without waiting for application quiet or moving capture endpoints.
        await cdp.send('Runtime.evaluate',{expression:'0',returnByValue:true});
        assert.equal(evidence.errors.length,0,'historical periodic fault retained');
        assert.equal(evidence.sources.filter(s=>s.verified).length,1,'periodic pinned query source');
        const candidates=evidence.network.filter(e=>e.request.url===request.url() && e.request.method==='GET'
          && (e.request.postData??null)===request.postData() && !matched.has(e.requestId)
          && (nativeFailures.get(e.requestId)?.errorText==='net::ERR_ABORTED')===(request.failure()?.errorText==='net::ERR_ABORTED'));
        assert.equal(candidates.length,1,'periodic exact native request correlation');
        const net=candidates[0]; matched.add(net.requestId);
        // The only unclaimed exact native request must also resolve to the same
        // real response correlation. Neither URL order nor a guessed timestamp
        // alone constitutes admitted wire custody.
        let admittedPeriodic=false;
        completions.push((async()=>{
          const response=await request.response();
          const error=response ? await response.finished() : request.failure();
          if(error && !admittedPeriodic && request.failure()?.errorText==='net::ERR_ABORTED') {
            evidence.admissions.push({requestId:net.requestId,initialCancellation:'net::ERR_ABORTED'});return;
          }
          assert.ok(response,'periodic native response missing');
          assert.equal(error,null,'periodic native body incomplete');
          await cdp.send('Runtime.evaluate',{expression:'0',returnByValue:true});
          const id=corroboratePeriodicWire(responses.get(net.requestId),await response.allHeaders(),response.status(),wireIds);
          evidence.admissions.push({requestId:net.requestId,wireCorrelation:id,completed:true});
        })().catch(error=>evidence.errors.push(String(error))));
        document??=net.loaderId; assert.equal(net.loaderId,document,'periodic document replaced');
        const at=net.wallTime*1000;
        const fetch=evidence.events.filter(e=>e.phase==='fetch' && e.key===contract.key && e.wall<=at+1).at(-1);
        const execute=fetch && evidence.events.find(e=>e.serial===fetch.execution && e.context===fetch.context);
        const interval=execute && evidence.events.filter(e=>e.phase==='interval' && e.owner===execute.owner && e.serial<execute.serial && e.context===execute.context).at(-1);
        const stack=frames(net.initiator.stack);
        const caller=stack.some(f=>new URL(f.url||'about:blank').origin==='http://127.0.0.1:5173'
          && new URL(f.url||'about:blank').pathname===contract.caller && f.functionName===contract.name);
        // A real chart mount can follow the account timer without belonging to
        // it. Native caller identity, not the most recent timer, selects capacity.
        const periodic=!!(caller && interval && interval.generation===execute.generation && execute.serial===interval.serial+1);
        if(!periodic){
          const known=caller
            || path.endsWith('/native/accounts') && stack.some(f=>new URL(f.url||'about:blank').origin==='http://127.0.0.1:5173' && new URL(f.url||'about:blank').pathname==='/src/services/api.ts'
              && ['getNativeIntervals','readPrimaryNative'].includes(f.functionName));
          assert.ok(known,'unidentified initial read caller');
          if(!path.endsWith('/native/accounts')) {
            assert.ok(fetch && execute && !interval,'health initial subscription provenance');
            assert.equal(fetch.scope,scope,'health initial scope');
            assert.equal(execute.listeners,1,'health initial owner');
            assert.equal(execute.observers,1,'health initial query');
          }
          // A non-timer request spends only the original initial/mount registration.
          // It receives no periodic capacity, including on ambiguous/missing provenance.
          evidence.admissions.push({requestId:net.requestId,path,kind:'initial',at}); return false;
        }
        assert.equal(fetch.scope,scope,'periodic scope replaced');
        const schedule=evidence.events.filter(e=>e.phase==='schedule' && e.owner===execute.owner
          && e.context===execute.context && e.generation===interval.generation && e.serial<interval.serial).at(-1);
        assert.ok(schedule,'periodic schedule missing');
        const later=evidence.events.filter(e=>e.owner===execute.owner && e.context===execute.context && e.serial>execute.serial);
        const latest=later.at(-1)??execute;
        const current={owner:latest.owner,query:latest.query,retired:later.some(e=>e.phase==='destroy'||e.phase==='unsubscribe'&&e.listeners===0)};
        const facts={request:{id:net.requestId,method:request.method(),url:request.url(),body:request.postData(),scope:fetch.scope,document:net.loaderId,
          caller},
          fetch,execute,interval,schedule,current};
        admitPeriodic(facts,{...contract,url:'http://127.0.0.1:5173'+path,scope,document,windowMs:info.timeout},used.get(path),Date.now(),deadline);
        admittedPeriodic=true; evidence.admissions.push({requestId:net.requestId,path,kind:'periodic',at,facts}); return true;
      } catch(error){evidence.errors.push(String(error));throw error;}
    },
    async finish(){
      retired=true;
      try {
        await Promise.all(completions);
        const unmatched=evidence.network.filter(event=>!matched.has(event.requestId));
        evidence.unmatched=unmatched; evidence.nativeFailures=[...nativeFailures];
        // Chromium may cancel StrictMode's initial subscription before a route
        // handler exists. This is not a completed read or periodic capacity.
        assert.ok(unmatched.length<=1,'unmatched native read count');
        for(const event of unmatched){
          const failure=nativeFailures.get(event.requestId);
          assert.equal(failure?.errorText,'net::ERR_ABORTED','unmatched native cancellation');
          assert.equal(failure?.canceled,true,'unmatched native cancelled flag');
          assert.ok(event.request.url.endsWith('/api/v1/native/accounts'),'unmatched native exact path');
          assert.ok(frames(event.initiator.stack).some(f=>f.functionName==='onSubscribe' && /\/modern-DufwN3iA\.js/.test(f.url)),'unmatched initial subscription');
        }
        assert.equal(evidence.errors.length,0,'historical periodic fault retained');
      } finally {
        await fs.writeFile(info.outputPath('periodic-provenance.json'),JSON.stringify(evidence,null,2));
      }
    },
  };
}
