"""Real factory/lease retained across external constructor fault boundaries."""

import sys
from pathlib import Path
if sys.flags.optimize:
    raise RuntimeError('Acceptance assertions require non-optimised Python')
import importlib.util
import threading
import traceback
from unittest.mock import patch

assert str(Path.home()) == '/run/test/home'
spec = importlib.util.spec_from_file_location('r84_run', str(Path(__file__).with_name('run.py')))
run = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = run
spec.loader.exec_module(run)
mode = sys.argv[1]
assert mode in {'listener', 'client'}
before = run.fingerprint()
run.save('sources-before.json',before)
class InjectedFailure(OSError):
    pass
calls = []
def fail(*a, **k):
    calls.append({'thread':threading.current_thread().name,'stack':[x.name for x in traceback.extract_stack()[-12:]]})
    raise InjectedFailure('R84 constructor fault before acquiring next owner')
# Fail inside the real external constructor called by normal startup.
target = 'waitress.adjustments.Adjustments.__init__' if mode == 'listener' else 'httpx.Client._init_transport'
desk = run.Desk.__new__(run.Desk)
try:
    with patch(target, fail):
        try:
            desk.__init__('health-only')
        except InjectedFailure:
            pass
        else:
            raise AssertionError('Fault not reached')
    assert len(calls) == 1
    retained = {'app':desk.app, 'lease':desk.lease, 'listener':getattr(desk,'listener',None),
                'threads':list(threading.enumerate()),
                'refresh':desk.app.config.get('INSTRUMENT_MASTER_REFRESH_OWNER')}
    assert not hasattr(desk,'client')
    assert hasattr(desk,'listener') == (mode == 'client')
    desk.close()
    assert desk.closed and not desk.failures
    assert all(not t.is_alive() for t in retained['threads'] if t.ident not in desk.initial_threads)
    run.save('lifetime-fault.json',{'boundary':mode,'fault_calls':calls,'retained_app_id':id(retained['app']),
             'retained_lease_id':id(retained['lease']),'retained_listener_id':id(retained['listener']),
             'threads_before_close':[t.name for t in retained['threads']], 'clean':True})
finally:
    if hasattr(desk,'app') and not desk.closed:
        desk.close()
    after=run.fingerprint(); run.save('sources-after.json',after)
    assert before == after
print('LIFETIME_FAULT_OK',mode)
