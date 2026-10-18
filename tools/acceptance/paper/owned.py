"""Actual run-owned worker entry, persisted monitor, HTTP grant and fixed exit."""

import sys
from pathlib import Path
if sys.flags.optimize:
    raise RuntimeError('Acceptance assertions require non-optimised Python')
import importlib.util
import time
import traceback

assert str(Path.home()) == '/run/test/home'
spec = importlib.util.spec_from_file_location('r84_run', str(Path(__file__).with_name('run.py')))
run = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = run
spec.loader.exec_module(run)
VARIANT=sys.argv[1] if len(sys.argv)>1 else 'positive'
assert VARIANT in {'positive','down-after-entry','wrong-acl','bad-quote','bad-history','bad-instrument','empty-chat','malformed-chat'}

def wait_for(fn, seconds=15):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        value=fn()
        if value: return value
        time.sleep(.1)
    raise AssertionError('Bounded wait did not reach actual predicate')

class Desk(run.Desk):
    def prepare_dependencies(self):
        self.read_bootstrap=run.load('read').Bootstrap(self,VARIANT)
        self.chat_fixture=run.load('chat').Chat(self,VARIANT)
        return self.read_bootstrap.inputs()

    def snapshot(self):
        return {'public':self.client.get(self.base).json(),
                'persisted':self.owner.store.get_run(self.owner.run.run_id),
                'events':self.owner.store.events(self.owner.run.run_id,limit=1000),
                'books':self.books(self.owner.sandbox),
                'model_budget':self.owner.run.model_budget.snapshot(),
                'sdk_calls':len(self.read_bootstrap.rows), 'chat_calls':len(self.chat_fixture.rows)}

    def control(self, operation):
        state=self.client.get(self.base).json()['data']
        return self.client.post(self.base+'/'+operation,json={
            'account':state['account'],'environment':state['environment'],'expected_generation':state['generation']})

    def safe_flatten(self):
        if hasattr(self,'owner') and self.owner.sandbox.get_positions():
            response=self.control('close')
            run.save('cleanup-close-command.json',{'status':response.status_code,'body':response.json()})
            assert response.status_code==202, response.text
            wait_for(lambda:not self.owner.sandbox.get_positions() and self.owner.run.cleanup_complete)
            flat=self.snapshot(); run.save('cleanup-close-flat.json',flat)
            assert flat['public']['data']['books']['positions']==[]


def scenario(desk):
    assert desk.refresh()['laya_practice']=='ready'
    deps=desk.app.extensions.get('flinttrade_broker_dependencies')
    run.save('factory-read-owners.json',{'dependencies':type(deps).__name__,
             'audit':type(desk.app.config.get('AUDIT')).__name__,
             'adapters':{k:type(v).__name__ for k,v in deps.adapters.items()} if deps else {},
             'read_owner':type(deps.read_owner).__name__ if deps else None,
             'publication_owned':deps.registry_publication_owner.owns(deps.registry) if deps else False})
    assert deps is not None, 'Real factory did not publish read dependencies'
    desk.start_run()
    desk.clock.release.set()
    wait_for(lambda:any(e['kind']=='cycle_finished' for e in desk.owner.store.events(desk.owner.run.run_id,limit=1000)))
    wait_for(lambda:desk.owner.store.get_run(desk.owner.run.run_id)['snapshot'].get('cycle_count',0)>=1)
    entry=desk.snapshot(); run.save('owned-frontier.json',entry)
    from dataclasses import asdict
    safety=desk.app.config['SAFETY']
    run.save('l5-observation.json',{'validation':asdict(safety.l5_kill.validate()),
        'journal_type':type(desk.app.config['EMERGENCY_INTENT_JOURNAL']).__name__,
        'active_episodes':[asdict(e) for e in desk.app.config['EMERGENCY_INTENT_JOURNAL'].active_episodes('l5')],
        'exceptions':desk.calls.exceptions})
    if VARIANT in {'wrong-acl','bad-quote','bad-history','bad-instrument','empty-chat','malformed-chat'}:
        assert entry['books']['trades']==[] and entry['books']['orders']==[]
        assert entry['public']['data']['entries_armed'] is False
        events=entry['events']
        expected='model_unavailable' if VARIANT.endswith('chat') else 'data_unavailable'
        assert any(e['kind']==expected for e in events), events
        assert entry['chat_calls']==(1 if VARIANT.endswith('chat') else 0)
        run.save('negative-oracle.json',{'variant':VARIANT,'before_fill_refused':True,'kind':expected})
        return
    books=entry['books']
    assert len(books['trades'])==len(books['orders'])==len(books['positions'])==1, 'Actual worker did not produce owned fill'
    order=books['orders'][0]; trade=books['trades'][0]
    assert order['status']=='COMPLETE' and trade['order_id']==order['order_id']
    assert order['action']==trade['action']=='BUY' and order['quantity']==trade['quantity']==1
    details=entry['persisted']['snapshot']['position_details']['RELIANCE']
    assert details['stop_loss']<order['fill_price']<details['take_profit']
    cycles=[e for e in entry['events'] if e['kind']=='cycle_finished']
    assert len(cycles)==1 and cycles[0]['data']['actions']['RELIANCE']['order']['status']=='success'
    assert cycles[0]['data']['actions']['RELIANCE']['order']['data']['orderid']==order['order_id']
    dispatch=[e for e in entry['events'] if e['kind']=='dispatch_result']
    assert len(dispatch)==1 and dispatch[0]['data']['response']['status']=='COMPLETE'
    assert dispatch[0]['data']['response']['orderid']==dispatch[0]['data']['response']['order_id']==order['order_id']
    assert entry['chat_calls']==1 and entry['model_budget']['model_calls_used']==1
    assert desk.books(desk.app.config['DATA_SANDBOX_ENGINE'])==desk.default_before
    uri='/api/v1/protection/grants/'+desk.run_id
    missing=desk.client.get(uri)
    assert missing.status_code==200 and missing.json()['data']['authority_state']=='not_issued'
    policy={'policy_revision':'r84-explicit-fixed-protection-v1','valid_until':time.time()+120,
            'position':{'symbol':'RELIANCE','exchange':'NSE','product':'MIS','quantity':1,'entry_order_ids':[order['order_id']]},
            'hedge_scope':[],'risk_policy':'unhedged-cash-reduction-only','max_quantity':1,'max_notional':200.0,
            'read':{'selector':'dhan:Quotes','valid_until':time.time()+100,'max_reads':80,'max_age_seconds':30.0}}
    if hasattr(desk,'bound_policy'):
        policy=desk.bound_policy(policy)
    # Missing/foreign entry and missing owner refuse before any permission is issued.
    for name, rid, changed in [('missing-position',desk.run_id,{k:v for k,v in policy.items() if k!='position'}),
          ('foreign-position',desk.run_id,{**policy,'position':{**policy['position'],'entry_order_ids':['not-an-observed-order']}}),
          ('no-owner','no-such-owned-run',policy)]:
        refused=desk.client.post('/api/v1/protection/grants',json={'run_id':rid,'expected_revision':0,'policy':changed})
        assert refused.status_code==403, refused.text
        run.save('grant-negative-'+name+'.json',{'body':refused.json(),'books':desk.books(desk.owner.sandbox)})
    grant=desk.client.post('/api/v1/protection/grants',json={'run_id':desk.run_id,'expected_revision':0,'policy':policy})
    run.save('grant-command.json',{'status':grant.status_code,'body':grant.json()})
    assert grant.status_code==201, grant.text
    granted=desk.client.get(uri).json()['data']
    assert granted['revision']==1 and granted['policy']==policy and granted['authority_state']=='active'
    assert granted['duty']['remaining_quantity']==1 and granted['duty']['state']=='retained'
    run.save('grant-readback.json',granted)
    stop=desk.control('stop'); assert stop.status_code==200,stop.text
    stopped=desk.snapshot(); duty=desk.client.get(uri).json()['data']
    assert stopped['public']['data']['entries_armed'] is False
    assert stopped['books']['positions'] and duty['duty']['remaining_quantity']==1
    reads=granted['usage']['reads']
    wait_for(lambda:desk.client.get(uri).json()['data']['usage']['reads']>=reads+2,10)
    retained=desk.snapshot(); duty=desk.client.get(uri).json()['data']
    assert len(retained['books']['trades'])==1 and duty['duty']['remaining_quantity']==1
    assert retained['chat_calls']==1
    run.save('retained-nonempty-duty.json',{'snapshot':retained,'grant':duty})
    if hasattr(desk,'boundary'):
        desk.boundary(policy, details)
    if VARIANT=='down-after-entry':
        desk.fixtures.mode='health-down'
        ping=desk.refresh()
        assert ping['laya_practice']=='down' and ping['laya']=='down'
    # Only an owned external quote changes; monitor/risk/positions remain product-owned.
    desk.read_bootstrap.price=details['take_profit']+.5
    wait_for(lambda:desk.owner.run.cleanup_complete,20)
    final=desk.snapshot(); grant_final=desk.client.get(uri).json()['data']
    run.save('fixed-reduction.json',{'snapshot':final,'grant':grant_final,'crossed_price':desk.read_bootstrap.price})
    assert final['public']['data']['books']['positions']==final['books']['positions']==[]
    assert len(final['books']['trades'])==len(final['books']['orders'])==2
    exits=[o for o in final['books']['orders'] if o['action']=='SELL']
    assert len(exits)==1 and exits[0]['status']=='COMPLETE' and exits[0]['quantity']==1
    assert len([t for t in final['books']['trades'] if t['order_id']==exits[0]['order_id'] and t['quantity']==1])==1
    attempts=grant_final['duty']['attempts']
    assert len(attempts)==1 and attempts[0]['state']=='completed' and attempts[0]['order_id']==exits[0]['order_id']
    assert exits[0]['strategy']=='Protection:'+attempts[0]['id']
    assert grant_final['usage']['quantity_used']==1 and grant_final['duty']['remaining_quantity']==0
    assert final['chat_calls']==1 and final['model_budget']['model_calls_used']==1
    assert desk.books(desk.app.config['DATA_SANDBOX_ENGINE'])==desk.default_before
    assert any(e['kind']=='session_learning_finished' for e in final['events'])
    run.save('owned-oracle.json',{'entry_order':order['order_id'],'entry_trade':trade['trade_id'],
        'exit_order':exits[0]['order_id'],'attempt':attempts[0]['id'],'run_id':desk.run_id,
        'entry_worker':desk.owner.run.thread.name,'fixed_exit_and_flat':True,'variant':VARIANT})

def main():
    before=run.fingerprint(); run.save('sources-before.json',before)
    desk=Desk.__new__(Desk); code=1
    try:
        desk.__init__('owned-cycle')
        scenario(desk)
        assert not desk.failures,desk.failures
        code=0
    except BaseException:
        run.save('failure.json',{'traceback':traceback.format_exc()}); traceback.print_exc()
    finally:
        if hasattr(desk,'app'):
            try:
                desk.safe_flatten()
                desk.close()
            except BaseException:
                code=1; run.save('cleanup-failure.json',{'traceback':traceback.format_exc()}); traceback.print_exc()
        after=run.fingerprint(); run.save('sources-after.json',after)
        assert before==after
        if desk.failures: code=1
        run.save('result.json',{'exit_code':code,'clean':desk.closed,'scenario':VARIANT,'source_count':len(before)})
    return code

if __name__=='__main__':
    raise SystemExit(main())
