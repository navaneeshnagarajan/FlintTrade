"""Explicit synthetic configuration custody; no inference/data/order work.

One controlled scope fixture: actual Practice supervisors/typed run books are
held by an injected external clock protocol before their first market session
read. Entries remain unarmed. No core method, session verifier or policy reply
is replaced. This is configuration acceptance, not started-run qualification.
"""

import sys
if sys.flags.optimize:
    raise RuntimeError('Acceptance assertions require non-optimised Python')
from datetime import UTC, datetime, timedelta
from pathlib import Path
import hashlib
import json
import threading


class HeldSessionClock:
    def __init__(self):
        self.release = threading.Event()
        self.entered = threading.Event()

    def now_ist(self):
        self.entered.set()
        if not self.release.wait(1200):
            raise RuntimeError('Synthetic clock owner not released')
        return datetime.now(UTC)

    def get_market_session(self, *_args, **_kwargs):
        return None


class NoInference:
    def chat(self, *_args, **_kwargs):
        raise AssertionError('R46 must never invoke inference')

    def close(self):
        pass


def bootstrap(server, output):
    from dataclasses import asdict
    from flinttrade_core.auth_routes import verify_operator_session_token
    from flinttrade_core.execution_sessions_routes import get_execution_sessions
    from flinttrade_core.practice_agent_runtime import PracticeAgentSupervisor, validate_practice_config
    from flinttrade_ai.run_store import AgentRunStore
    from flinttrade_core.run_learning import FIELDS
    from flinttrade_core.service_providers import LicenceFact, RightsBasis, RightsGrant, intersect_rights
    from packages.core.core.tests.test_learning_consent import rights
    app, client = server.app, server.client
    with app.app_context():
        actor = verify_operator_session_token(server.token).actor_ref
    registry = get_execution_sessions(app)
    server.r46_registry = registry
    now = datetime.now(UTC)
    end = now + timedelta(hours=1)
    bootstrap_path = Path('/run/test/bootstrap.json')
    state = json.loads(bootstrap_path.read_text())
    state['runs'] = []
    for identity in ('r46-paper-a', 'r46-paper-b'):
        response = client.post('/api/v1/execution-sessions', json={'run_id': identity, 'kind': 'practice', 'config': {'symbols': ['RELIANCE'], 'cycle_interval_sec': 3600}})
        assert response.status_code == 201, response.text
        scope = registry.scope(identity, actor)
        store = AgentRunStore(registry.path / identity / 'runs.sqlite')
        supervisor = PracticeAgentSupervisor(app, store, execution_binding=registry.binding(scope))
        registry.owners[identity] = supervisor
        supervisor.start(server.token, actor, validate_practice_config({'symbols': ['RELIANCE'], 'cycle_interval_sec': 3600}), llm=NoInference())
        state['runs'].append(asdict(scope))
    assert server.r46_clock.entered.wait(15)
    model_owner = app.config['MODEL_RUN_SERVICES']
    model_owner.dispatcher()
    for row in state['runs']:
        model_owner.learning(row['run_id'])
        assert registry.status(registry.scope(row['run_id'], actor))['entries_armed'] is False
        assert client.get('/v1/model-runs/' + row['run_id'] + '/configuration').status_code == 200
    revision = client.get('/v1/services/connections').headers['etag']
    selection = {'connection_id': server.connection_id, 'connection_revision': revision, 'model': 'test-model-v1', 'effort': 'balanced'}
    state['values'] = {
        'access': {'operations': ['evaluation.read'], 'valid_until': end.timestamp(), 'evidence': 'R46 explicit synthetic access; no score/adoption/trading'},
        'grant': {'role': 'reasoning', 'identity_scope': 'provider-reported-revision', 'valid_until': end.timestamp(), 'evidence': 'R46 synthetic reasoning configuration, not activation'},
        'revoke-grant': {'role': 'reasoning'},
    }
    for subject in ('source', 'output'):
        document = 'Synthetic reviewed UTF-8 bytes only: नमस्ते 🚦 "quoted"\\path\n' + ('Bounded private policy review, not measured entitlement.\n' * 12) + subject
        basis = RightsBasis.LICENCE if subject == 'source' else RightsBasis.PROVIDER_TERMS
        fact = LicenceFact('r46-' + subject, 'dataset' if subject == 'source' else 'provider-output',
            'closed-trades:r46-paper-a' if subject == 'source' else selection['model'],
            'https://example.invalid/synthetic', 'r46-v1', hashlib.sha256(document.encode()).hexdigest(), now.isoformat(), basis)
        resolved = intersect_rights(RightsGrant('r46-' + subject, basis, rights().rights, (fact,)))
        state['values']['rights-' + subject] = {'subject': subject, 'selection': selection, 'rights': resolved.to_public_dict(),
            'documents': {fact.fact_id: document}, 'fields': list(FIELDS), 'review_statement': 'Explicit R46 synthetic review, not entitlement'}
    state['times'] = {'now': now.isoformat(), 'end': end.isoformat(), 'valid_until': end.timestamp()}
    state['selection'] = selection
    evidence = app.config['EVALUATION_STORE']
    evidence._graders['r46-independent'] = lambda *_: {'score': 1}
    for category in ('evaluation', 'candidate'):
        manifest = {'schema_version': 1, 'model': selection, 'data': 'r46-synthetic', 'skill': 'fixed', 'strategy': 'fixed', 'config': 'fixed',
            'producer': 'r46-synthetic-producer', 'evaluator': 'r46-independent', 'role': 'reasoning', 'control_scope': state['runs'][0]}
        trial = evidence.begin(evidence.create(manifest))
        suite = 'r46-sealed-' + category
        evidence.freeze(suite, {name: [{'id': name, 'group': name, 'as_of': n}] for n, name in enumerate(('development', 'calibration', 'final'))},
            evaluator='r46-independent', policy={'thresholds': {'score': {'min': 1}}, 'budgets': {'max_trials': 1}})
        if category == 'candidate':
            evidence.score_final(suite, trial, prospective={'candidate': manifest, 'receipt': 'r46-synthetic-prospective'})
            state['values'][category] = {'candidate': trial, 'selection': selection, 'role': 'reasoning', 'identity_scope': 'provider-reported-revision',
                'valid_until': end.timestamp(), 'deadline_ms': 2000, 'max_output_tokens': 256, 'readiness_ttl_seconds': 60}
        else:
            state['values'][category] = {'trial': trial, 'suite': suite}
    assert not server.wires
    import os
    if 'training-backend' in os.environ.get('R46_SCENARIO', ''):
        from uuid import uuid4
        from flinttrade_core.service_usage_contracts import USAGE_DIMENSIONS
        from flinttrade_core.training_jobs import UNSLOTH_PIN
        from packages.core.core.tests.test_service_tasks import policy
        base = '/v1/services/connections'
        created = client.post(base, headers={'If-Match': client.get(base).headers['etag'], 'Idempotency-Key': str(uuid4())},
            json={'provider_id': 'llm:custom', 'label': 'R46 inert training destination', 'model': 'test-model-v1',
                  'endpoint': 'http://127.0.0.1:8765', 'auth_mode': 'api_key', 'credential': 'synthetic-only'})
        assert created.status_code == 201, created.text
        raw = policy(created.headers['etag'])
        config = {key: raw[key] for key in ('connection_revision', 'budget', 'tariff', 'reservation', 'quota_group')}
        config['quota_group'] = 'r46-separate-training-account'
        config['budget'].update(window_start=now.isoformat(), window_end=end.isoformat(), limits={key: 100000 for key in USAGE_DIMENSIONS})
        config['tariff'].update(provider_id='llm:custom', effective_from=now.isoformat(), effective_until=end.isoformat())
        config['reservation'] = {key: 0 for key in USAGE_DIMENSIONS} | {'requests': 1, 'concurrency': 1, 'bytes': 10000, 'currency_micros': 100}
        config.update(version=UNSLOTH_PIN, principal='synthetic-owner', principal_role='owner', region='test-region',
            terms_revision='synthetic-terms', model_revision='test-model-v1', valid_until=end.timestamp(),
            isolation={'dedicated': True, 'pool': 'r46-training-only', 'evidence': 'r46-synthetic-capacity'},
            controls={key:'hard-provider' for key in USAGE_DIMENSIONS}, controls_evidence='r46-synthetic-controls', timeout_seconds=2)
        state['values']['training-backend'] = {'connection_id': created.json()['connection_id'], 'policy': config}
    if 'R46 history' in os.environ.get('R46_SCENARIO', ''):
        model_owner.configure_access('r46-paper-a', actor=actor, expected_revision=0, **state['values']['access'])
    if 'binding refusal' in os.environ.get('R46_SCENARIO', ''):
        from flinttrade_core.service_usage_contracts import USAGE_DIMENSIONS
        url = '/v1/model-runs/r46-paper-a/configuration'
        def configure(action, value, revision=0):
            proposal = {'action': action, 'expected_revision': revision, 'value': value}
            preview = client.post(url + '/preview', json=proposal)
            assert preview.status_code == 200, preview.text
            result = client.post(url + '/confirm', json={**proposal, 'confirmation': preview.json()['confirmation']})
            assert result.status_code == 200, result.text
            return result.json()['result']
        source = configure('learning-rights', state['values']['rights-source'])
        target = configure('learning-rights', state['values']['rights-output'])
        dataset_value = {'source_rights':source['event_id'], 'output_rights':target['event_id'], 'as_of_start':now.isoformat(), 'as_of_end':end.isoformat()}
        dataset = configure('learning-dataset', dataset_value)
        reservation = {key:0 for key in USAGE_DIMENSIONS} | {'requests':1,'concurrency':1,'input_tokens':32768,'output_tokens':256,'bytes':32768,'currency_micros':1000}
        configured = configure('learning-policy', {'selection':selection,'reservation':reservation,'controls':{key:'hard-local' for key in USAGE_DIMENSIONS},
            'controls_evidence':'R46 synthetic controls', 'principal':'r46-synthetic-recipient','region':'test-region','terms_revision':'r46-terms',
            'valid_until':end.timestamp(),'max_output_tokens':256,'timeout_seconds':5})
        scenario = os.environ['R46_SCENARIO']
        grant_end = datetime.now(UTC) + timedelta(seconds=1) if 'expired' in scenario else end
        permission = {'scope':dataset['scope'],'recipient':configured['recipient'],'purpose':'reflection','operations':['chat'],
            'valid_from':now.isoformat(),'valid_until':grant_end.isoformat(),'limits':{key:1000000 for key in USAGE_DIMENSIONS},
            'max_rows':10,'max_trials':10,'retention':'synthetic-one-day','derivatives':'same-scope-no-publication','objective':'synthetic-reflection',
            'rights':state['values']['rights-source']['rights'],'supersedes':None}
        preview = client.post('/v1/learning/permissions/preview',json=permission)
        assert preview.status_code == 200, preview.text
        grant = client.post('/v1/learning/permissions/grants',json={**permission,'confirmation':preview.json()['confirmation']})
        assert grant.status_code == 200, grant.text
        grant_id = grant.json()['grant_id']
        if 'revoked' in scenario:
            revoked = client.post('/v1/learning/permissions/grants/'+grant_id+'/revoke',json={})
            assert revoked.status_code == 200, revoked.text
        if 'expanded' in scenario:
            configure('learning-dataset', {**dataset_value,'as_of_end':(end+timedelta(hours=1)).isoformat()},1)
        state['values']['learning-binding'] = {'grant_id':grant_id}
        state['refusal_setup'] = {'grant_id':grant_id,'valid_until':grant_end.isoformat(),'reason':scenario}
    if 'custody unavailable' in os.environ.get('R46_SCENARIO', ''):
        server.r46_fault = app.config['PROTECTION_SERVICES'].workspace / 'protection.registry'
        assert not server.r46_fault.exists()
        server.r46_fault.write_text('R46 explicit synthetic missing-database custody fault')
    state['scope_fixture'] = 'actual unarmed supervisors held at injected external session clock; no model/data/order invocation'
    state['setup_http_rows'] = len(server.rows)
    bootstrap_path.write_text(json.dumps(state))
    (output / 'r46-bootstrap-public.json').write_text(json.dumps({k: v for k, v in state.items() if k != 'session'}, indent=2))
    (output / 'r46-setup-boundary.json').write_text(json.dumps({'setup_http_rows': len(server.rows), 'provider_calls': len(server.wires), 'native_freeze': True,
        'controlled_scope_fixture': state['scope_fixture'], 'entries_armed': False, 'runs': state['runs']}, indent=2))


def drain(server, output):
    if hasattr(server, 'r46_fault'):
        assert server.r46_fault.read_text() == 'R46 explicit synthetic missing-database custody fault'
        server.r46_fault.unlink()
    server.r46_clock.release.set()
    registry = getattr(server, 'r46_registry', None)
    result = {'clock_released': True, 'provider_calls': len(server.wires), 'runs': []}
    result['training_job_store_exists'] = (server.app.config['MODEL_RUN_SERVICES'].workspace / 'training-jobs.sqlite').exists()
    assert result['training_job_store_exists'] is False
    if registry is not None:
        assert registry.shutdown(timeout=20), 'Actual retained duty must not be killed'
        for run_id, owner in registry.owners.items():
            result['runs'].append({'run_id': run_id, 'thread_alive': owner.run.thread.is_alive(), 'cleanup_complete': owner.run.cleanup_complete,
                'positions': owner.sandbox.get_positions(), 'orders': owner.sandbox.get_all_orders(), 'trades': owner.sandbox.get_trades()})
        assert all(not row['thread_alive'] and row['cleanup_complete'] and not row['orders'] and not row['positions'] for row in result['runs'])
        registry.close()
    protection = server.app.config.get('PROTECTION_SERVICES')
    if protection is not None:
        assert protection.close() is not False
    assert not server.wires
    (output / 'r46-owner-drain.json').write_text(json.dumps(result, indent=2))
