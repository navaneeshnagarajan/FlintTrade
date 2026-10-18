"""Post-entry negative boundaries, then explicit same-envelope HTTP cleanup.

Every position/monitor/grant is earned by the original actual worker flow.
Expiry cases initially narrow the existing fixture deadlines; after refusal a
fresh explicit operator POST restores only the already-declared original ceiling.
No row insertion, implicit renewal, clock patch, budget increase or new chat.
"""

import sys
from pathlib import Path
if sys.flags.optimize:
    raise RuntimeError('Acceptance assertions require non-optimised Python')
from copy import deepcopy
import importlib.util
import time
import traceback

CASE=sys.argv[1]
assert CASE in {'read-expiry','grant-expiry','read-budget','grant-retirement'}
sys.argv=[sys.argv[0],'positive']
spec=importlib.util.spec_from_file_location('r84_owned',str(Path(__file__).with_name('owned.py')))
owned=importlib.util.module_from_spec(spec);sys.modules[spec.name]=owned;spec.loader.exec_module(owned)
run=owned.run

class Desk(owned.Desk):
    def bound_policy(self, policy):
        self.ceiling=deepcopy(policy)
        narrowed=deepcopy(policy)
        if CASE=='read-expiry':
            narrowed['read']['valid_until']=time.time()+9
        elif CASE=='grant-expiry':
            narrowed['valid_until']=time.time()+9
            narrowed['read']['valid_until']=narrowed['valid_until']
        run.save('boundary-authority-envelope.json',{'original_ceiling':self.ceiling,'initial_policy':narrowed,
                  'cleanup':'Explicit HTTP reauthorisation of original unchanged ceiling after observed refusal'})
        return narrowed

    def boundary(self, policy, details):
        services=self.app.config['PROTECTION_SERVICES']
        scope=self.owner.execution_binding.scope
        uri='/api/v1/protection/grants/'+self.run_id
        expected={'read-expiry':'protection_read_scope_or_expiry','grant-expiry':'protection_grant_retired',
                  'read-budget':'protection_read_budget','grant-retirement':'protection_grant_retired'}[CASE]
        expected_thread='asyncio_0' if CASE in {'read-expiry','read-budget'} else 'practice-agent'
        if CASE=='grant-retirement':
            rev=self.client.get(uri).json()['data']['revision']
            response=self.client.post(uri+'/revoke',json={'expected_revision':rev})
            assert response.status_code==200,response.text
            run.save('boundary-revoke.json',{'status':response.status_code,'body':response.json(),'readback':self.client.get(uri).json()})
        elif CASE=='read-budget':
            # Consume the original 80-call ceiling, without a synthetic counter.
            from flinttrade_core.practice_agent_adapter import PracticeAgentError
            # Never hold the run fence while an HTTP/async read must acquire it
            # on another thread. The real grant transaction owns the counter.
            while services.readback(self.run_id,self.actor)['usage']['reads']<policy['read']['max_reads']:
                try:
                    context=services.collect(scope,'RELIANCE','NSE')
                except PracticeAgentError as exc:
                    assert exc.code=='protection_read_budget'
                    break
                fields={'input_digest':context.receipt['input_digest'],'market_data':context.market_data}
                assert self.read_bootstrap.audit.verify_idempotent_event_receipt(
                    'PROTECTION_QUOTE',event_id=context.receipt['event_id'],fields=fields)
        else:
            deadline=policy['read']['valid_until'] if CASE=='read-expiry' else policy['valid_until']
            # Real wall time passes; only the market-session clock is synthetic.
            time.sleep(max(0,deadline-time.time())+.05)
        owned.wait_for(lambda:any(e['message']==expected and e['thread']==expected_thread for e in self.calls.exceptions),10)
        before=self.snapshot(); grant=self.client.get(uri).json()['data']
        assert len(before['books']['trades'])==1 and before['books']['positions'][0]['net_qty']==1
        assert grant['duty']['remaining_quantity']==1 and grant['duty']['attempts']==[]
        assert before['chat_calls']==1 and before['model_budget']['model_calls_used']==1
        if CASE=='read-budget': assert grant['usage']['reads']==policy['read']['max_reads']==80
        if CASE in {'grant-expiry','grant-retirement'}: assert grant['authority_state']=='retired'
        sdk=len(self.read_bootstrap.rows)
        # A crossing quote cannot be used while authority is refused.
        self.read_bootstrap.price=details['take_profit']+.5
        observed=len([e for e in self.calls.exceptions if e['message']==expected and e['thread']==expected_thread])
        owned.wait_for(lambda:len([e for e in self.calls.exceptions if e['message']==expected and e['thread']==expected_thread])>observed,10)
        refused=self.snapshot(); after=self.client.get(uri).json()['data']
        assert len(self.read_bootstrap.rows)==sdk and len(refused['books']['trades'])==1
        assert after['duty']['remaining_quantity']==1 and after['duty']['attempts']==[]
        run.save('boundary-refusal.json',{'case':CASE,'code':expected,'before':before,'after':refused,
                 'grant':after,'worker_exceptions':[e for e in self.calls.exceptions if e['message']==expected],
                 'sdk_unchanged':len(self.read_bootstrap.rows)==sdk,'not_flat':True})
        # Reset only the external quote to in-band. Never reset any guard/latch.
        self.read_bootstrap.price=details['entry_price']
        assert self.ceiling['valid_until']>time.time() and self.ceiling['read']['valid_until']>time.time()
        response=self.client.post('/api/v1/protection/grants',json={
             'run_id':self.run_id,'expected_revision':after['revision'],'policy':self.ceiling})
        assert response.status_code==201,response.text
        readback=self.client.get(uri).json()['data']
        assert readback['revision']==after['revision']+1 and readback['policy']==self.ceiling
        assert readback['authority_state']=='active' and readback['duty']['remaining_quantity']==1
        run.save('boundary-explicit-reauthorisation.json',{'status':response.status_code,
                 'body':response.json(),'readback':readback,'only_original_ceiling':True})
        # The unmodified positive flow now crosses the bound and verifies its
        # real fixed SELL, exact attempt, flat readback and owner drain.

before=run.fingerprint();run.save('sources-before.json',before)
desk=Desk.__new__(Desk);code=1
try:
    desk.__init__('owned-cycle')
    owned.scenario(desk)
    assert not desk.failures,desk.failures
    code=0
except BaseException:
    run.save('failure.json',{'traceback':traceback.format_exc()});traceback.print_exc()
    run.save('failure-observers.json',{'calls':desk.calls.rows,'exceptions':desk.calls.exceptions,
             'sdk':desk.read_bootstrap.rows,'network':desk.network,'failures':desk.failures})
    if hasattr(desk,'ceiling') and desk.ceiling['read']['valid_until']>time.time():
        # Explicit bounded cleanup authority, never a reset or a passed oracle.
        current=desk.client.get('/api/v1/protection/grants/'+desk.run_id).json()['data']
        if current['policy'] is not None and not current['duty']['attempts']:
            response=desk.client.post('/api/v1/protection/grants',json={
                'run_id':desk.run_id,'expected_revision':current['revision'],'policy':desk.ceiling})
            readback=desk.client.get('/api/v1/protection/grants/'+desk.run_id).json()
            run.save('failed-control-explicit-cleanup-authority.json',{'status':response.status_code,
                'body':response.json(),'readback':readback})
finally:
    if hasattr(desk,'app'):
        try: desk.safe_flatten();desk.close()
        except BaseException:
            code=1;run.save('cleanup-failure.json',{'traceback':traceback.format_exc()});traceback.print_exc()
    after=run.fingerprint();run.save('sources-after.json',after);assert before==after
    if desk.failures:code=1
    run.save('result.json',{'exit_code':code,'clean':desk.closed,'scenario':CASE,'source_count':len(before)})
raise SystemExit(code)
