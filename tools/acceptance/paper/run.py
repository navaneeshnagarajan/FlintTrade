"""Private normal-factory prerequisite. Run only inside unchanged isolation.

All wire data is synthetic. No model, native write or qualification is supplied.
"""
from __future__ import annotations

import sys
from pathlib import Path
from paths import artifacts, workspace_root
if sys.flags.optimize:
    raise RuntimeError('Acceptance assertions require non-optimised Python')

import asyncio
import base64
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, time as wall_time
import hashlib
import importlib.util
import json
import os
import secrets
import socket
import threading
import time
import traceback
from zoneinfo import ZoneInfo

OUT = artifacts()
SUPPORT = Path(__file__).resolve().parent
BACKEND = 5100
HEALTH = 5177
CHAT = 5178


def digest(value):
    return hashlib.sha256(value).hexdigest()


def save(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, default=str))


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), SUPPORT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fingerprint():
    roots = [Path('packages/core/core/src'), Path('packages/core/data/src'),
             Path('packages/services/engine/src'), Path('packages/services/ai/src'),
             Path('packages/integrations/gateway/src')]
    paths = [p for root in roots for p in root.rglob('*') if p.is_file() and p.suffix in {'.py', '.toml', '.json'}]
    paths += [p for p in SUPPORT.glob('*.py') if p.is_file()]
    paths += [Path('pyproject.toml'), Path('uv.lock')]
    return {str(p): digest(p.read_bytes()) for p in sorted(paths)}


class Calls:
    def __init__(self):
        self.rows = []
        self.exceptions = []
        self.targets = {
            ('flinttrade_engine/laya.py', 'admit'),
            ('flinttrade_engine/laya_decision.py', 'decide'),
            ('flinttrade_engine/safety.py', 'gate_order'),
            ('flinttrade_engine/safety.py', 'consume'),
            ('flinttrade_gateway/router.py', 'place_order'),
            ('flinttrade_data/sandbox_engine.py', 'place_order'),
            ('flinttrade_core/order_routes.py', '_dispatch_practice_place_locked'),
            ('flinttrade_core/practice_agent_runtime.py', '_persist'),
            ('flinttrade_core/practice_agent_runtime.py', 'chat'),
            ('flinttrade_ai/llm_client.py', 'chat'),
            ('flinttrade_ai/autonomous_agent.py', 'execute'),
            ('flinttrade_core/ai_broker_context.py', 'collect_configured_broker_context'),
            ('flinttrade_core/protection_reads.py', 'collect_protection_quote'),
            ('flinttrade_core/protection_grants.py', 'validate'),
            ('flinttrade_core/run_learning.py', 'chat'),
            ('flinttrade_engine/safety.py', 'broker_write_admission'),
            ('flinttrade_engine/emergency_intents.py', 'blocking_sources'),
            ('flinttrade_core/practice_agent_adapter.py', '_write_admission'),
            ('flinttrade_ai/autonomous_agent.py', '_assess_risk'),
            ('flinttrade_ai/autonomous_agent.py', 'monitor'),
            ('flinttrade_core/practice_agent_model.py', 'reserve'),
        }

    def observe(self, frame, event, value):
        if event not in {'call', 'return'}:
            return
        path = frame.f_code.co_filename.replace('\\', '/')
        target = ('/'.join(path.split('/')[-2:]), frame.f_code.co_name)
        if target not in self.targets:
            return
        row = {'path': path, 'function': target[1], 'event': event,
               'thread': threading.current_thread().name, 'monotonic_ns': time.monotonic_ns()}
        if event == 'return':
            if is_dataclass(value) and not isinstance(value, type):
                row['value'] = asdict(value)
            elif type(value) in (dict, list, str, int, float, bool) or value is None:
                row['value'] = value
        if target[1] == '_persist':
            row['status'] = frame.f_locals.get('status')
        if target[1] in {'blocking_sources', 'broker_write_admission'}:
            row['selector'] = frame.f_locals.get('selector')
            row['owner_type'] = type(frame.f_locals.get('self')).__name__
            row['emergency_reduction'] = frame.f_locals.get('emergency_reduction')
        self.rows.append(row)

    def trace(self, frame, event, value):
        path = frame.f_code.co_filename.replace('\\', '/')
        target = ('/'.join(path.split('/')[-2:]), frame.f_code.co_name)
        if target not in {('flinttrade_engine/safety.py', 'broker_write_admission'),
                           ('flinttrade_engine/emergency_intents.py', 'blocking_sources'),
                           ('flinttrade_core/practice_agent_adapter.py', '_write_admission'),
                           ('flinttrade_core/protection_reads.py', 'collect_protection_quote'),
                           ('flinttrade_core/protection_grants.py', 'validate')}:
            return None
        frame.f_trace_lines = False
        if event == 'exception':
            self.exceptions.append({'path':path,'line':frame.f_lineno,'function':target[1],
                'type':value[0].__name__,'message':str(value[1]),'selector':frame.f_locals.get('selector'),
                'thread':threading.current_thread().name})
        return self.trace

    def start(self):
        threading.setprofile_all_threads(self.observe)
        threading.settrace_all_threads(self.trace)

    def close(self):
        threading.setprofile_all_threads(None)
        threading.settrace_all_threads(None)
        save('calls.json', self.rows)
        save('admission-exceptions.json', self.exceptions)


class Clock:
    """External market clock; third worker call is after real entry checks."""
    def __init__(self):
        self.release = threading.Event()
        self.entered = threading.Event()
        self.rows = []
        self.worker_calls = 0
        self.closed = False
        self.at = datetime(2026, 10, 9, 10, 0, tzinfo=ZoneInfo('Asia/Kolkata'))

    def now_ist(self):
        worker = threading.current_thread().name == 'practice-agent'
        if worker:
            self.worker_calls += 1
        self.rows.append({'operation': 'now_ist', 'thread': threading.current_thread().name,
                          'worker_calls': self.worker_calls,
                          'stack': [r.name for r in traceback.extract_stack()[-9:-1]]})
        if worker and self.worker_calls == 3:
            self.entered.set()
            if not self.release.wait(30):
                raise RuntimeError('R84 clock hold exceeded')
        return self.at

    def get_market_session(self, exchange: str, *, on: date, symbol: str):
        assert exchange == 'NSE' and symbol == 'RELIANCE'
        self.rows.append({'operation': 'session', 'closed': self.closed, 'date': on.isoformat()})
        return None if self.closed else (wall_time(9, 15), wall_time(15, 30))


class Desk:
    def __init__(self, scenario):
        assert str(Path.home()) == '/run/test/home'
        self.scenario = scenario
        self.initial_threads = {t.ident for t in threading.enumerate()}
        self.network = []
        self.failures = []
        self.rows = []
        self.client_rows = []
        self.clock = Clock()
        self.calls = Calls()
        self.fixtures = None
        self.registry = None
        self.closed = False
        self.workspace = workspace_root()
        self.workspace.mkdir(mode=0o700)
        os.environ['FLINTTRADE_WORKSPACE_DIR'] = str(self.workspace)
        os.environ['FLINTTRADE_API_KEY'] = secrets.token_urlsafe(32)
        os.environ['FLINTTRADE_FRONTEND_DIST'] = '/run/test/artifacts/no-frontend'
        master = self.workspace / 'master_password'
        master.write_text(secrets.token_urlsafe(48)); master.chmod(0o600)
        self.allowed_ports = {BACKEND}
        self.probe = load('probe').DenialProbe(self.failures, self.network)
        load('network').install(self)
        def audit(event, args):
            self.probe.audit(event, args)
            if event in {'socket.connect', 'socket.bind', 'socket.getaddrinfo', 'urllib.Request'}:
                if event in {'socket.connect', 'socket.bind'}:
                    addr = args[1]
                    allowed = type(addr) is tuple and addr[0] == '127.0.0.1' and addr[1] in self.allowed_ports
                elif event == 'socket.getaddrinfo':
                    addr = args[:2]
                    allowed = addr[0] == '127.0.0.1' and addr[1] in (self.allowed_ports | {str(p) for p in self.allowed_ports})
                else:
                    addr = args[0]
                    allowed = addr == f'http://127.0.0.1:{HEALTH}/health' and HEALTH in self.allowed_ports
                self.network.append({'event': event, 'address': addr, 'allowed': allowed,
                    'stack': [{'file':r.filename,'line':r.lineno,'function':r.name} for r in traceback.extract_stack()[-14:-1]] if not allowed else []})
                if not allowed:
                    self.failures.append(['network', event, str(addr)])
                    raise RuntimeError('R84 unregistered network target')
        sys.addaudithook(audit)
        if scenario not in {'baseline', 'canonical-red', 'owned-red'}:
            self.fixtures = load('wire').Wires(self, scenario)
        from importlib.metadata import distribution
        dependencies = {'python': sys.version, 'executable': str(Path(sys.executable).resolve()),
                        'python_sha256': digest(Path(sys.executable).resolve().read_bytes()), 'distributions': {}}
        for name in ('dhanhq', 'Flask', 'waitress', 'httpx', 'PyJWT', 'pydantic'):
            dist = distribution(name)
            dependencies['distributions'][name] = {'version': dist.version, 'metadata': {
                str(p): digest(Path(dist.locate_file(p)).read_bytes()) for p in dist.files
                if p.name in {'METADATA', 'RECORD'}}}
        from flinttrade_core.broker_sdk_attest import attest_all
        dependencies['attestation'] = [asdict(r) for r in attest_all()]
        save('dependencies.json', dependencies)
        from flinttrade_core.backend_instance import acquire_backend_instance_lease
        from flinttrade_core.app import create_flask_app, _run_flask_server
        from flinttrade_core import auth_routes
        from flask import request
        import httpx
        self.lease = acquire_backend_instance_lease()
        kwargs = self.prepare_dependencies() if hasattr(self, 'prepare_dependencies') else {}
        self.app = app = create_flask_app(backend_lease_proof=self.lease.proof, time_scheduler=self.clock, **kwargs)
        assert app.config['BACKEND_LEASE_READY']
        app.config['AUTH_SERVICE'].setup_account('synthetic-operator', 'synthetic@example.invalid', secrets.token_urlsafe(32))
        with app.app_context():
            self.token = auth_routes._create_token('synthetic-operator')
            self.actor = auth_routes.verify_operator_session_token(self.token).actor_ref
        @app.after_request
        def record(response):
            self.rows.append({'method': request.method, 'path': request.full_path.removesuffix('?'),
                              'status': response.status_code, 'body_sha256': digest(request.get_data(cache=True)),
                              'response_sha256': digest(response.get_data())})
            return response
        def capture(response):
            response.read()
            req = response.request
            self.client_rows.append({'method': req.method, 'path': req.url.raw_path.decode(),
                                     'status': response.status_code, 'body_sha256': digest(req.content),
                                     'response_sha256': digest(response.content),
                                     'body_base64': base64.b64encode(req.content).decode(),
                                     'response_base64': base64.b64encode(response.content).decode()})
        self.listener = _run_flask_server(app, port=BACKEND, host='127.0.0.1')
        self.client = httpx.Client(base_url=f'http://127.0.0.1:{BACKEND}', trust_env=False, timeout=15,
                                  headers={'Authorization': 'Bearer ' + self.token}, event_hooks={'response': [capture]})
        self.calls.start()
        frozen = self.client.post('/api/v1/native/accounts', json={'adapter_id': 'dhan', 'account_id': 'synthetic-unavailable', 'credentials': {}})
        assert frozen.status_code == 503 and frozen.json() == {'error': 'broker_account_cutover_unavailable'}, frozen.text
        self.default_before = self.books(app.config['DATA_SANDBOX_ENGINE'])
        save('bootstrap.json', {'backend': BACKEND, 'health': HEALTH, 'chat': CHAT, 'actor': self.actor,
                                'scenario': scenario, 'native_freeze': frozen.json(), 'synthetic': True})

    @staticmethod
    def books(sandbox):
        return {'positions': sandbox.get_positions(), 'orders': sandbox.get_all_orders(), 'trades': sandbox.get_trades()}

    def order(self, quantity=1, action='BUY', rationale=''):
        return self.client.post('/api/v1/orders/place', headers={'X-FlintTrade-Mode': 'practice'}, json={
            'symbol': 'RELIANCE', 'exchange': 'NSE', 'product': 'MIS', 'action': action,
            'quantity': quantity, 'price': 123.5, 'price_basis': 'ltp', 'order_type': 'MARKET', 'rationale': rationale})

    def refresh(self):
        response = self.client.get('/health')
        ping = self.client.get('/api/v1/ping')
        from flinttrade_core.laya_runtime import process_runtime
        runtime = process_runtime()
        if runtime is not None:
            files = {str(p.relative_to(runtime.runtime_root)): digest(p.read_bytes())
                     for p in runtime.runtime_root.rglob('*') if p.is_file()}
            states = {name: json.loads((runtime.runtime_root / name).read_text())
                      for name in ('state.json',) if (runtime.runtime_root / name).is_file()}
            save('runtime-metadata.json', {'files': files, 'states_written_by_real_runtime': states,
                 'synthetic_health_not_weight_attestation': True, 'artifact': asdict(runtime.ensure_artifact_check())})
            assert not any(name in files for name in ('verification.json', 'run.json', 'sidecar.pid'))
        save('health.json', {'health_status': response.status_code, 'health': response.json(), 'ping': ping.json()})
        return ping.json()

    def start_run(self):
        from flinttrade_core.execution_sessions_routes import get_execution_sessions
        from flinttrade_core.workspace import Workspace
        self.registry = get_execution_sessions(self.app)
        self.run_id = 'r84-paper'
        self.base = '/api/v1/execution-sessions/' + self.run_id
        result = self.client.post('/api/v1/execution-sessions', json={'run_id': self.run_id, 'kind': 'practice', 'config': {
            'symbols': ['RELIANCE'], 'exchange': 'NSE', 'product': 'MIS', 'cycle_interval_sec': 3600,
            'max_position_size': 1, 'model_call_limit': 1, 'model_output_limit': 32,
            'stop_loss_pct': 2.0, 'take_profit_pct': 4.0}})
        assert result.status_code == 201, result.text
        control = {'account': 'paper:run:' + self.run_id, 'environment': 'paper', 'expected_generation': 0}
        disabled = self.client.post(self.base + '/start', json=control)
        assert disabled.status_code == 409 and self.run_id not in self.registry.owners
        Workspace().set('ai.autonomous_agent.enabled', True)
        started = self.client.post(self.base + '/start', json=control)
        assert started.status_code == 202, started.text
        assert self.clock.entered.wait(15)
        self.owner = self.registry.owners[self.run_id]
        status = self.client.get(self.base).json()['data']
        assert status['entries_armed'] and status['generation'] == 1
        assert not self.owner._entry_brake(self.owner.run)
        assert self.client.post(self.base + '/start', json=control).status_code == 409
        assert self.client.post(self.base + '/start', json={**control, 'expected_generation': 1}).status_code == 409
        save('public-start.json', status)

    def close(self):
        from flinttrade_core.app import _close_runtime_request_admission
        from flinttrade_core.desktop import _DesktopShutdownRecoveryOwner
        from flinttrade_core.laya_runtime import process_runtime
        result = {'clean': False, 'runs': []}
        try:
            if self.registry:
                for run_id, owner in self.registry.owners.items():
                    status = self.client.get('/api/v1/execution-sessions/' + run_id).json()['data']
                    stop = self.client.post('/api/v1/execution-sessions/' + run_id + '/stop', json={
                        'account': status['account'], 'environment': 'paper', 'expected_generation': status['generation']})
                    assert stop.status_code == 200, stop.text
                    current = self.client.get('/api/v1/execution-sessions/' + run_id).json()['data']
                    assert current['entries_armed'] is False
                    stopped_entry = asyncio.run(owner.run.adapter.place_order(symbol='RELIANCE', exchange='NSE',
                                                product='MIS', action='BUY', quantity=1))
                    assert stopped_entry['code'] == 'practice_stopped', stopped_entry
                    save('stopped-entry.json', {'entry': stopped_entry, 'readback': current})
                    if owner.sandbox.get_positions():
                        raise RuntimeError('R84 retained nonempty duty: no flat proof; shutdown not claimed')
                self.clock.closed = True
                self.clock.release.set()
                assert self.registry.shutdown(timeout=15), 'retained owner'
                for run_id, owner in self.registry.owners.items():
                    result['runs'].append({'run_id': run_id, 'alive': owner.run.thread.is_alive(),
                                           'cleanup_complete': owner.run.cleanup_complete, 'books': self.books(owner.sandbox),
                                           'budget': owner.run.model_budget.snapshot()})
                    assert not owner.run.thread.is_alive() and owner.run.cleanup_complete
            sandbox = self.app.config['DATA_SANDBOX_ENGINE']
            if sandbox.get_positions():
                reduction = self.order(1, 'SELL')
                assert reduction.status_code == 200 and reduction.json()['status'] == 'COMPLETE', reduction.text
                assert not sandbox.get_positions(), 'manual canonical reduction failed'
                flat = self.client.get('/v1/sandbox/positions')
                assert flat.status_code == 200 and flat.json()['data']['positions'] == []
                save('manual-reduction.json', {'response': reduction.json(), 'books': self.books(sandbox),
                                              'public_readback': flat.json()})
            tracker = _close_runtime_request_admission(self.app)
            result['admission_drained'] = tracker.wait_for_idle(timeout=10)
            if hasattr(self, 'client'):
                self.client.close()
            result['listener_created'] = hasattr(self, 'listener')
            result['listener_stopped'] = self.listener.stop(timeout=10) if result['listener_created'] else True
            assert result['admission_drained'] and result['listener_stopped']
            refresh_owner = self.app.config.get('INSTRUMENT_MASTER_REFRESH_OWNER')
            result['refresh_owner_id'] = id(refresh_owner)
            result['refresh_thread_id'] = refresh_owner.thread.ident if refresh_owner is not None else None
            recovery = _DesktopShutdownRecoveryOwner(self.app, borrowed_keys=frozenset({'TIME_SCHEDULER', 'CREDENTIAL_STORE', 'AUDIT'} if hasattr(self, 'read_bootstrap') else {'TIME_SCHEDULER'}))
            # This private composition also owns borrowed registry/SDK fixtures.
            # Drain the real factory first, but retain our original lease until
            # those roots and all fixture threads have retired below.
            recovery.release(deadline=time.monotonic() + 20)
            if refresh_owner is not None:
                assert not refresh_owner.thread.is_alive()
                result['refresh_joined'] = True
            if self.fixtures:
                from flinttrade_core.instrument_lots import cache_path
                cache = cache_path()
                payload = json.loads(cache.read_text())
                assert payload['rows'] == [] and 'could not be downloaded' in payload['note']
                expected = self.fixtures.text.urls
                actual = [r['url'] for r in self.fixtures.rows if r['kind'] == 'denial-only-kotak' and r['accepted']]
                assert actual == list(expected) and self.fixtures.text.counts['instrument-master-csv'] == 1
                save('reference-refresh.json', {'payload':payload, 'sha256':digest(cache.read_bytes()),
                     'expected_urls':expected, 'actual_urls':actual, 'no_kotak_data':True,
                     'refresh_joined': result.get('refresh_joined',False)})
            runtime = process_runtime()
            if runtime is not None:
                watch = runtime._watch_thread
                runtime.stop_watch()
                assert watch is None or not watch.is_alive()
            if self.fixtures:
                self.fixtures.close()
            if hasattr(self, 'read_bootstrap'):
                self.read_bootstrap.close()
            if hasattr(self, 'chat_fixture'):
                self.chat_fixture.close()
            if hasattr(self, 'client'):
                self.client.close()
            # The exact lease watcher must remain alive while its proof is live;
            # every other owned thread must already be drained before release.
            proof = self.lease.proof
            lease_watchers = [t for t in threading.enumerate()
                if getattr(getattr(t, '_target', None), '__self__', None) is proof
                and getattr(getattr(t, '_target', None), '__func__', None) is type(proof)._watch_local]
            assert len(lease_watchers) == 1
            for t in threading.enumerate():
                if t.ident not in self.initial_threads and t not in lease_watchers:
                    t.join(timeout=2)
            before_release = [t for t in threading.enumerate() if t.ident not in self.initial_threads]
            assert before_release == lease_watchers
            result['only_exact_lease_watcher_before_release'] = True
            with socket.socket() as sock:
                result['listener_closed'] = sock.connect_ex(('127.0.0.1', BACKEND)) != 0
            assert result['listener_closed'], result
            from flinttrade_core.backend_instance import (
                acquire_backend_instance_lease, require_backend_lease_proof, BackendInstanceAlreadyRunning)
            require_backend_lease_proof(self.lease.proof)
            result['lease_held_through_all_owned_cleanup'] = True
            if hasattr(self, 'read_bootstrap'):
                result['borrowed_registry_retired_before_release'] = all(
                    not self.read_bootstrap.registry.snapshot_selector(s).present for s in self.read_bootstrap.selectors)
                assert result['borrowed_registry_retired_before_release']
            try:
                unexpected = acquire_backend_instance_lease()
            except BackendInstanceAlreadyRunning:
                result['lease_exclusion_before_release'] = True
            else:
                unexpected.release()
                raise AssertionError('Original lease failed exclusion before release')
            self.lease.release()
            for t in lease_watchers:
                t.join(timeout=2)
            result['remaining_threads'] = [t.name for t in threading.enumerate() if t.ident not in self.initial_threads]
            assert not result['remaining_threads'], result
            lease2 = acquire_backend_instance_lease(); lease2.release()
            result['lease_reacquired'] = True
            result['clean'] = True
            self.closed = True
        finally:
            save('ipv6-probe.json', self.probe.complete())
            self.calls.close()
            native = [r for r in self.calls.rows if r['event'] == 'call' and
                      (r['path'].endswith('flinttrade_engine/safety.py') and r['function'] in {'gate_order','consume'} or
                       r['path'].endswith('flinttrade_gateway/router.py'))]
            model = [r for r in self.calls.rows if r['event'] == 'call' and r['function'] in {'chat', 'decide'}]
            save('non-use.json', {'native_chain': native, 'model_calls': model,
                                 'scope': 'Paper chain is not Live gate/router coverage'})
            assert not native
            if not hasattr(self, 'chat_fixture'):
                assert not model
            save('drain.json', result)
            save('clock.json', self.clock.rows)
            save('http-server.json', self.rows)
            save('http-client.json', self.client_rows)
            save('network.json', {'attempts': self.network, 'failures': self.failures})
            if self.client_rows:
                keys = ('method', 'path', 'status', 'body_sha256', 'response_sha256')
                client = [{k: x[k] for k in keys} for x in self.client_rows]
                external = [x for x in self.rows if x in client]
                save('http-correspondence.json', {'equal': external == client, 'count': len(client)})
                assert external == client


def scenario(desk):
    if desk.scenario in {'baseline', 'canonical-red', 'owned-red'}:
        desk.start_run()
        entry = asyncio.run(desk.owner.run.adapter.place_order(symbol='RELIANCE', exchange='NSE', product='MIS', action='BUY', quantity=1))
        canonical = desk.order()
        save('baseline.json', {'entry': entry, 'canonical_status': canonical.status_code, 'canonical': canonical.json(),
                              'owned': desk.books(desk.owner.sandbox), 'default': desk.books(desk.app.config['DATA_SANDBOX_ENGINE'])})
        assert entry['code'] == 'broker_context_unavailable'
        assert canonical.status_code == 403 and canonical.json()['code'] == 'laya_denied'
        if desk.scenario == 'canonical-red':
            assert canonical.status_code == 200 and canonical.json()['status'] == 'COMPLETE', canonical.text
        if desk.scenario == 'owned-red':
            assert entry.get('status') == 'COMPLETE', entry
        return
    ping = desk.refresh()
    assert ping['laya'] == 'down' and ping['laya_live_qualified'] is False, ping
    response = desk.order(2 if desk.scenario == 'quantity2' else 1)
    save('manual.json', {'ping': ping, 'status': response.status_code, 'body': response.json(),
                         'books': desk.books(desk.app.config['DATA_SANDBOX_ENGINE'])})
    if desk.scenario == 'health-only':
        assert ping['laya_practice'] == 'ready' and ping['laya'] == 'down' and not ping['laya_live_qualified'], ping
        assert response.status_code == 200 and response.json()['status'] == 'COMPLETE', response.text
        trades = desk.app.config['DATA_SANDBOX_ENGINE'].get_trades()
        assert len(trades) == 1 and trades[0]['order_id'] == response.json()['order_id']
        positions = desk.client.get('/v1/sandbox/positions')
        assert positions.status_code == 200 and len(positions.json()['data']['positions']) == 1
        save('manual-position-readback.json', positions.json())
    elif desk.scenario == 'quantity2':
        assert response.status_code == 409 and response.json()['code'] == 'laya_clamp', response.text
        assert not desk.app.config['DATA_SANDBOX_ENGINE'].get_trades()
    else:
        assert response.status_code in {403, 409} and response.json()['code'] in {'laya_denied', 'laya_unverified'}, response.text
        assert not desk.app.config['DATA_SANDBOX_ENGINE'].get_trades()
    save('scenario-oracle.json', {'scenario': desk.scenario, 'assertions_reached': True,
                                 'overall_accepted': False, 'pending': 'strict network/lifetime reconciliation'})


def main():
    assert str(Path.home()) == '/run/test/home' and not Path('.local').exists()
    assert len(sys.argv) == 2 and sys.argv[1] in {'baseline', 'canonical-red', 'owned-red', 'health-only',
           'quantity2', 'missing-pin', 'wrong-pin', 'malformed-health', 'health-down'}
    before = fingerprint(); save('sources-before.json', before)
    for path in SUPPORT.glob('*.py'):
        if path.is_file():
            (OUT / ('source-' + path.name)).write_bytes(path.read_bytes())
    desk = Desk.__new__(Desk)
    code = 1
    try:
        desk.__init__(sys.argv[1])
        scenario(desk)
        assert not desk.failures, desk.failures
        code = 0
    except BaseException:
        save('failure.json', {'traceback': traceback.format_exc()})
        traceback.print_exc()
    finally:
        if hasattr(desk, 'app'):
            try:
                desk.close()
            except BaseException:
                code = 1
                save('cleanup-failure.json', {'traceback': traceback.format_exc()})
                traceback.print_exc()
        after = fingerprint(); save('sources-after.json', after)
        assert before == after, 'source/dependency input drift'
        if desk.failures:
            code = 1
        save('result.json', {'exit_code': code, 'scenario': sys.argv[1], 'clean': desk.closed,
                             'source_count': len(before), 'no_source_drift': before == after})
    return code


if __name__ == '__main__':
    raise SystemExit(main())
