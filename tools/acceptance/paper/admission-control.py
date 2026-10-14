"""Scoped admission diagnostic; original refusal remains in inherited evidence."""

import sys
from pathlib import Path
if sys.flags.optimize:
    raise RuntimeError('Acceptance assertions require non-optimised Python')
import importlib.util
from dataclasses import asdict
import traceback

assert str(Path.home())=='/run/test/home'
spec=importlib.util.spec_from_file_location('r84_owned',str(Path(__file__).with_name('owned.py')))
owned=importlib.util.module_from_spec(spec); sys.modules[spec.name]=owned; spec.loader.exec_module(owned)
run=owned.run
before=run.fingerprint(); run.save('sources-before.json',before)
desk=owned.Desk.__new__(owned.Desk); code=1
try:
    desk.__init__('owned-cycle')
    ping=desk.refresh(); assert ping['laya_practice']=='ready' and ping['laya']=='down' and not ping['laya_live_qualified']
    desk.start_run(); desk.clock.release.set()
    owned.wait_for(lambda:any(e['kind']=='cycle_finished' for e in desk.owner.store.events(desk.owner.run.run_id,limit=1000)))
    owned.wait_for(lambda:desk.owner.store.get_run(desk.owner.run.run_id)['snapshot'].get('cycle_count',0)>=1)
    snapshot=desk.snapshot()
    run.save('admission-frontier.json',snapshot)
    assert len(snapshot['books']['positions'])==len(snapshot['books']['orders'])==len(snapshot['books']['trades'])==1
    assert snapshot['public']['data']['books']['trades']==snapshot['books']['trades']
    assert desk.books(desk.app.config['DATA_SANDBOX_ENGINE'])==desk.default_before
    assert snapshot['chat_calls']==1 and snapshot['model_budget']['model_calls_used']==1
    reserves=[e for e in snapshot['events'] if e['kind']=='model_attempt_reserved']
    assert len(reserves)==1 and reserves[0]['data']['operation']=='analysis'
    # A successful run_cycle now reaches its post-fill monitor: four additional
    # real ordinary reads, unlike the preserved pre-fix failed-entry frontier.
    assert snapshot['sdk_calls']==12
    fill=next(r for r in desk.calls.rows if r['function']=='place_order' and r['event']=='call' and r['path'].endswith('sandbox_engine.py'))
    assert len([r for r in desk.read_bootstrap.rows if r['monotonic_ns']<fill['monotonic_ns']])==8
    contexts=[r['value'] for r in desk.calls.rows if r['function']=='collect_configured_broker_context' and r['event']=='return' and r.get('value') is not None]
    assert len(contexts)==3
    for context in contexts:
        fields={'input_digest':context['receipt']['input_digest'],'market_data':context['market_data']}
        assert desk.read_bootstrap.audit.verify_idempotent_event_receipt('AI_BROKER_ANALYSIS_INPUT',event_id=context['receipt']['event_id'],fields=fields)
    chain=desk.read_bootstrap.audit.verify_chain(); assert chain['ok'] and chain['anchored_at_genesis']
    risk=[r['value'] for r in desk.calls.rows if r['function']=='_assess_risk' and r['event']=='return']
    assert len(risk)==1 and risk[0]['allowed'] and risk[0]['position_qty']==1
    laya=[r['value'] for r in desk.calls.rows if r['function']=='admit' and r['event']=='return']
    assert len(laya)==1 and laya[0]['allow'] and laya[0]['applied_quantity']==1
    dispatch=[e for e in snapshot['events'] if e['kind']=='dispatch_result']
    assert len(dispatch)==1 and dispatch[0]['data']['response']['status']=='COMPLETE'
    assert dispatch[0]['data']['response']['order_id']==snapshot['books']['trades'][0]['order_id']
    journal=desk.app.config['EMERGENCY_INTENT_JOURNAL']
    validation=asdict(desk.app.config['SAFETY'].l5_kill.validate())
    episodes=journal.active_episodes('l5')
    assert validation['verdict']=='PASS' and episodes==()
    exceptions=desk.calls.exceptions
    assert exceptions==[]
    scoped=[r for r in desk.calls.rows if r['function'] in {'blocking_sources','broker_write_admission'} and r['event']=='call']
    assert scoped and all(r['selector']==desk.owner.execution_binding.scope.account for r in scoped)
    assert all(r['thread']=='practice-agent' for r in scoped)
    assert desk.owner.execution_binding.scope.account=='paper:run:'+desk.run_id
    assert any(r['owner_type']=='EmergencyIntentJournal' for r in scoped)
    assert any(r['function']=='place_order' and r['path'].endswith('sandbox_engine.py') for r in desk.calls.rows)
    run.save('admission-control.json',{'status':'correctly-scoped-real-worker-admitted','validation':validation,
        'scoped_calls':scoped,'prior_failure_class':'normal worker admitted with wrong journal selector',
        'active_episodes':episodes,'exceptions':exceptions,'audit_chain':chain,'contexts':contexts,'risk':risk,'laya':laya,
        'model_reservations':reserves,'knowledge_memory_type':type(desk.owner.run.trader.memory).__name__,
        'frozen_llm_type':type(desk.owner.run.llm).__name__})
    assert not desk.failures,desk.failures
    code=0
except BaseException:
    run.save('failure.json',{'traceback':traceback.format_exc()}); traceback.print_exc()
finally:
    if hasattr(desk,'app'):
        try: desk.safe_flatten(); desk.close()
        except BaseException:
            code=1;run.save('cleanup-failure.json',{'traceback':traceback.format_exc()});traceback.print_exc()
    after=run.fingerprint();run.save('sources-after.json',after);assert before==after
    if desk.failures: code=1
    run.save('result.json',{'exit_code':code,'clean':desk.closed,'scenario':'admission-scoped-control','source_count':len(before)})
raise SystemExit(code)
