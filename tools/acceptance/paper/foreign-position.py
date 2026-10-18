"""Refuse a genuinely filled foreign manual position as run protection scope."""

import sys
from pathlib import Path
if sys.flags.optimize:
    raise RuntimeError('Acceptance assertions require non-optimised Python')
import importlib.util
import time
import traceback

sys.argv=[sys.argv[0],'positive']
spec=importlib.util.spec_from_file_location('r84_owned',str(Path(__file__).with_name('owned.py')))
owned=importlib.util.module_from_spec(spec);sys.modules[spec.name]=owned;spec.loader.exec_module(owned)
run=owned.run
before=run.fingerprint();run.save('sources-before.json',before)
desk=owned.Desk.__new__(owned.Desk);code=1
try:
    desk.__init__('owned-cycle')
    assert desk.refresh()['laya_practice']=='ready'
    desk.start_run();desk.clock.release.set()
    owned.wait_for(lambda:desk.owner.store.get_run(desk.run_id)['snapshot'].get('cycle_count',0)==1)
    entry=desk.snapshot()
    assert len(entry['books']['trades'])==len(entry['books']['positions'])==1
    assert entry['books']['orders'][0]['status']=='COMPLETE' and entry['chat_calls']==1
    assert entry['persisted']['snapshot']['position_details']['RELIANCE']['quantity']==1
    manual=desk.order()
    assert manual.status_code==200 and manual.json()['status']=='COMPLETE',manual.text
    default=desk.books(desk.app.config['DATA_SANDBOX_ENGINE'])
    foreign=manual.json()['order_id']
    assert len(default['positions'])==len(default['trades'])==1 and default['trades'][0]['order_id']==foreign
    assert foreign!=entry['books']['trades'][0]['order_id']
    policy={'policy_revision':'r84-explicit-fixed-protection-v1','valid_until':time.time()+120,
            'position':{'symbol':'RELIANCE','exchange':'NSE','product':'MIS','quantity':1,'entry_order_ids':[foreign]},
            'hedge_scope':[],'risk_policy':'unhedged-cash-reduction-only','max_quantity':1,'max_notional':200.0,
            'read':{'selector':'dhan:Quotes','valid_until':time.time()+100,'max_reads':80,'max_age_seconds':30.0}}
    response=desk.client.post('/api/v1/protection/grants',json={'run_id':desk.run_id,'expected_revision':0,'policy':policy})
    assert response.status_code==403,response.text
    readback=desk.client.get('/api/v1/protection/grants/'+desk.run_id).json()['data']
    assert readback['authority_state']=='not_issued' and readback['revision']==0
    assert desk.books(desk.owner.sandbox)==entry['books']
    assert desk.books(desk.app.config['DATA_SANDBOX_ENGINE'])==default
    run.save('foreign-actual-position.json',{'owned':entry,'foreign_manual':default,'manual_response':manual.json(),
            'refusal':response.json(),'grant_readback':readback,'not_fabricated':True})
    desk.safe_flatten()
    assert desk.books(desk.app.config['DATA_SANDBOX_ENGINE'])==default
    flat=desk.snapshot()
    assert flat['books']['positions']==[] and len(flat['books']['trades'])==2 and flat['chat_calls']==1
    run.save('foreign-isolation-flat.json',{'owned':flat,'unchanged_foreign_manual':default})
    assert not desk.failures,desk.failures
    code=0
except BaseException:
    run.save('failure.json',{'traceback':traceback.format_exc()});traceback.print_exc()
finally:
    if hasattr(desk,'app'):
        try: desk.safe_flatten();desk.close()
        except BaseException:
            code=1;run.save('cleanup-failure.json',{'traceback':traceback.format_exc()});traceback.print_exc()
    after=run.fingerprint();run.save('sources-after.json',after);assert before==after
    if desk.failures:code=1
    run.save('result.json',{'exit_code':code,'clean':desk.closed,'scenario':'foreign-actual-position','source_count':len(before)})
raise SystemExit(code)
