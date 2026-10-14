import path from 'node:path';
import {fileURLToPath} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url));
const appRoot=process.env.FLINTTRADE_E2E_SOURCE_ROOT;
import {test} from 'node:test';
import assert from 'node:assert/strict';
const core=await import(process.env.RETICLE_TEST_ROOT+'/@reticlehq/core/dist/index.js');
test('core owns receipt, sequence, scope and page contracts',()=>{
 for(const name of ['CaptureSequenceSchema','CaptureScopeSchema','CapturePageSchema','CaptureExportRequestSchema','WireReceiptSchema','CaptureStream','WireReceiptKind'])assert(core[name],name+' missing from shared core');
 const event={sessionId:'[REDACTED]',documentId:'doc',seq:0,t:1,type:'signal',data:{name:'ready',nested:[null,{extra:1}]},nativeExtra:['retained']};
 const row={receipt:0,receivedAt:1,kind:'application',event};assert.deepEqual(core.WireReceiptSchema.parse(row),row);
 for(const value of [null,[],{},'1',true,-1,1.5,100000])assert.equal(core.CaptureSequenceSchema.safeParse(value).success,false);
 for(const mutate of [r=>r.event=null,r=>r.event.data=[],r=>r.event.type='fake.event',r=>r.receipt='0',r=>r.receivedAt=-1,r=>r.kind='arbitrary',r=>r.event.data.urlRaw='synthetic-private']){const r=structuredClone(row);mutate(r);assert.equal(core.WireReceiptSchema.safeParse(r).success,false);}
 assert.equal(core.WireReceiptSchema.safeParse({...row,event:{...event,data:undefined}}).success,false);
});
