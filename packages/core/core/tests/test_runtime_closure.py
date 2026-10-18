"""Runtime consumer closure over real canonical books and immutable learning."""
from __future__ import annotations

import pytest

from packages.core.core.tests.test_practice_agent_runtime import desk as desk, _wait_for
from packages.core.core.tests.test_protection_ingress import protection_desk as protection_desk

pytestmark = pytest.mark.integration

SCOPES = ['admin.services.read', 'admin.services.write', 'admin.accounts.read', 'admin.accounts.write']


def installed(desk, tmp_path):
    from flinttrade_core.knowledge_integration import install_knowledge_runtime
    from flinttrade_core.run_adoption import install_run_services
    from flinttrade_core.protection_grants import install_protection_services
    from flinttrade_core.execution_sessions_routes import install_execution_sessions, get_execution_sessions

    workspace = tmp_path / 'runtime'
    workspace.mkdir(mode=0o700)
    install_knowledge_runtime(desk.app, workspace)
    knowledge = desk.app.config['KNOWLEDGE_RUNTIME']
    services = install_run_services(desk.app, workspace)
    protection = install_protection_services(desk.app, workspace)
    install_execution_sessions(desk.app, workspace)
    return get_execution_sessions(desk.app), services, knowledge, protection


def start(desk, sessions, identity='learning', **changes):
    from flinttrade_core.execution_session import ExecutionSession
    from flinttrade_core.practice_agent_runtime import validate_practice_config

    scope = ExecutionSession(identity, desk.owner, 'paper:run:' + identity, 'paper')
    sessions.create(scope, kind='practice', config=validate_practice_config(
        {'symbols': ['RELIANCE'], 'cycle_interval_sec': 3600, **changes}))
    sessions.start(scope, token=desk.token(mode='live', scopes=SCOPES), expected_generation=0)
    _wait_for(lambda: sessions.owners[identity].run.snapshot.get('cycle_count') == 1)
    return scope, sessions.owners[identity].run


def test_restart_seam_never_manufactures_registry_from_empty_existing_directory(desk, tmp_path):
    from flinttrade_core.execution_sessions_routes import resume_execution_protection
    path = tmp_path / 'unknown-registry'
    desk.app.config['EXECUTION_SESSIONS_PATH'] = path
    assert resume_execution_protection(desk.app) == {'state': 'not_initialised', 'runs': []}
    assert not path.exists() and 'EXECUTION_SESSIONS' not in desk.app.config
    path.mkdir()
    assert resume_execution_protection(desk.app) == {'state': 'unavailable', 'runs': None}
    assert 'EXECUTION_SESSIONS' not in desk.app.config
    assert not (path / 'registry.sqlite').exists()


def test_never_used_protection_owner_closes_without_creating_a_registry(desk, tmp_path):
    from flinttrade_core.protection_grants import install_protection_services
    owner = install_protection_services(desk.app, tmp_path / 'never-used')
    owner.close()
    owner.close()
    assert not owner.workspace.exists()


def test_exhausted_inference_budget_still_records_actual_local_learning(desk, tmp_path):
    from flinttrade_ai.memory_ledger import MemoryDomain

    sessions, services, knowledge, _protection = installed(desk, tmp_path)
    desk.signal = 'BUY'
    try:
        scope, run = start(desk, sessions, model_call_limit=1)
        assert run.model_budget.exhausted
        budget = run.model_budget.snapshot()
        assert run.trader.learning_client is run.trader.learning_records is services.learning(scope.run_id)
        sessions.close_positions(scope, expected_generation=sessions.status(scope)['generation'])
        _wait_for(lambda: not run.thread.is_alive())
        assert run.trader.join_background_learning(0)
        assert len(sessions.status(scope)['books']['trades']) == 2
        records = [event for event in knowledge.ledger.history(MemoryDomain.EPISODIC)
                   if event.payload.get('kind') == 'closed-trade']
        assert len(records) == 1, 'inference exhaustion must not discard local evidence'
        assert dict(records[0].payload['values']) == run.trader.state.closed_trades[0]
        assert records[0].payload['account_id'] == scope.account
        assert run.model_budget.snapshot() == budget
    finally:
        assert sessions.shutdown(5)
        sessions.close()
        services.close()
        knowledge.close()


def test_normal_start_attaches_without_grant_and_preserves_fixed_close(desk, tmp_path):
    sessions, services, knowledge, protection = installed(desk, tmp_path)
    desk.signal = 'BUY'
    try:
        scope, run = start(desk, sessions, identity='grantless')
        assert run.adapter._protection == (protection, scope), 'actual caller must attach its exact owner'
        assert not protection.has_grant(scope)
        with pytest.raises(RuntimeError, match='protection'):
            protection.close()
        headers = {'Authorization': 'Bearer ' + desk.token(mode='live', scopes=SCOPES)}
        before = list(protection._owners)
        response = desk.client.get('/api/v1/protection/grants/' + scope.run_id, headers=headers)
        assert response.status_code == 200, response.json
        data = response.json['data']
        assert data['revision'] == 0 and data['policy'] is None and data['authority_state'] == 'not_issued'
        assert data['duty'] == {'state': 'not_granted', 'remaining_quantity': None,
                                'reconciliation_required': False, 'attempts': []}
        assert response.headers['Cache-Control'] == 'no-store'
        assert not (protection.workspace / 'protection.sqlite').exists()
        missing = desk.client.get('/api/v1/protection/grants/unknown', headers=headers)
        assert missing.status_code == 403 and missing.json['code'] == 'protection_owner_unproved'
        assert list(protection._owners) == before
        sessions.close_positions(scope, expected_generation=sessions.status(scope)['generation'])
        _wait_for(lambda: not run.thread.is_alive())
        assert sessions.status(scope)['books']['positions'] == []
        assert len(sessions.status(scope)['books']['trades']) == 2
    finally:
        if 'run' in locals() and run.thread.is_alive():
            sessions.close_positions(scope, expected_generation=sessions.status(scope)['generation'])
            _wait_for(lambda: not run.thread.is_alive())
        assert sessions.shutdown(5)
        sessions.close()
        services.close()
        knowledge.close()


def test_same_id_rearm_retains_policy_and_learner_only_after_actual_drain(desk, tmp_path):
    from flinttrade_core.execution_sessions import ExecutionSessions
    from flinttrade_core.practice_agent_runtime import PracticeAgentSupervisor

    sessions, services, knowledge, protection = installed(desk, tmp_path)
    try:
        scope, first = start(desk, sessions, identity='same-id')
        original = services.runs.owner(scope.run_id)
        learner = services.learning(scope.run_id)
        original.configure(scope.run_id, 'access', {'operations': ['evaluation.read'], 'valid_until': 9999999999},
                           expected_revision=0)
        first_store = original.store
        policy = first_store.model_control(scope.run_id, 'access')
        # Retired control is deliberately non-authorising. Rearm may not turn
        # this persisted model boundary into unrestricted legacy inference.
        original.configure(scope.run_id, 'grant:reasoning', {'valid_until': 0, 'role': 'reasoning'}, expected_revision=0)
        retired_grant = first_store.model_control(scope.run_id, 'grant:reasoning')
        with pytest.raises(ValueError):
            sessions.start(scope, token=desk.token(mode='live', scopes=SCOPES),
                           expected_generation=sessions.status(scope)['generation'], rearm=True)
        assert services.runs.owner(scope.run_id) is original
        # A second wrapper is not a drained owner, even with identical scope/books.
        impostor = object.__new__(PracticeAgentSupervisor)
        impostor.__dict__.update(original.supervisor.__dict__)
        with pytest.raises(ValueError, match='ownership'):
            services.attach_practice(impostor)
        assert services.learning(scope.run_id) is learner
        assert sessions.shutdown(5)
        sessions.close()
        sessions = ExecutionSessions(desk.app, sessions.path)
        desk.app.config['EXECUTION_SESSIONS'] = sessions
        status = sessions.status(scope)
        sessions.start(scope, token=desk.token(mode='live', scopes=SCOPES),
                       expected_generation=status['generation'], rearm=True)
        second = sessions.owners[scope.run_id].run
        _wait_for(lambda: second.snapshot.get('cycle_count') == 1)
        replacement = services.runs.owner(scope.run_id)
        assert replacement is not original
        assert replacement.store.model_control(scope.run_id, 'access') == policy
        assert replacement.store.model_control(scope.run_id, 'grant:reasoning') == retired_grant
        assert second.adapter._model_admission is not None, 'persisted generation/permission gates must survive rearm'
        assert services.learning(scope.run_id) is learner and learner.run is second
        assert protection._owners[scope.run_id][2] is second.adapter
        assert sessions.status(scope)['books']['trades'] == []
    finally:
        assert sessions.shutdown(5)
        sessions.close()
        services.close()
        knowledge.close()


def test_same_backend_explicit_rearm_reuses_exact_history_after_close(desk, tmp_path):
    sessions, services, knowledge, _protection = installed(desk, tmp_path)
    try:
        scope, first = start(desk, sessions, identity='same-backend')
        learner = services.learning(scope.run_id)
        sessions.close_positions(scope, expected_generation=sessions.status(scope)['generation'])
        _wait_for(lambda: not first.thread.is_alive())
        events = sessions.owners[scope.run_id].store.events(scope.run_id)
        sessions.start(scope, token=desk.token(mode='live', scopes=SCOPES),
                       expected_generation=sessions.status(scope)['generation'], rearm=True)
        second = sessions.owners[scope.run_id].run
        _wait_for(lambda: second.snapshot.get('cycle_count') == 1)
        assert second is not first and learner.run is second
        assert sessions.owners[scope.run_id].store.events(scope.run_id)[:len(events)] == events
        assert sessions.status(scope)['books']['trades'] == []
    finally:
        assert sessions.shutdown(5)
        sessions.close()
        services.close()
        knowledge.close()


def test_registry_close_retains_books_until_actual_learner_joins(desk, tmp_path):
    import threading
    sessions, services, knowledge, _protection = installed(desk, tmp_path)
    scope, run = start(desk, sessions, identity='held-learning')
    sessions.close_positions(scope, expected_generation=sessions.status(scope)['generation'])
    _wait_for(lambda: not run.thread.is_alive())
    entered, release = threading.Event(), threading.Event()
    def learner():
        entered.set()
        release.wait(5)
    worker = threading.Thread(target=learner)
    run.trader._learning_thread = worker
    worker.start()
    try:
        assert entered.wait(2)
        with pytest.raises(RuntimeError, match='consumer|learning|worker'):
            sessions.close()
        assert not sessions.closed
        assert sessions.status(scope)['books'] is not None
        assert not sessions.shutdown(0)
        with pytest.raises(RuntimeError, match='learning'):
            services.close()
    finally:
        release.set()
        assert run.trader.join_background_learning(5)
        assert sessions.shutdown(5)
        sessions.close()
        services.close()
        knowledge.close()


def test_strategy_close_refuses_a_substituted_raw_adapter_before_invocation(desk):
    import asyncio
    from contextlib import nullcontext
    from types import SimpleNamespace
    from flinttrade_core.execution_strategy import ExecutionStrategyOwner

    writes = []
    async def raw(order):
        writes.append(order)
        return SimpleNamespace(passed=True)
    owner = object.__new__(ExecutionStrategyOwner)
    owner.app, owner.sandbox = desk.app, desk.sandbox
    owner.run = SimpleNamespace(adapter=SimpleNamespace(route_order=raw, protective_action=nullcontext))
    desk.sandbox.place_order('RELIANCE', 'NSE', 'BUY', 1, 123.5)
    with pytest.raises(ValueError):
        asyncio.run(owner._close_positions())
    assert writes == [], 'the fixed caller must prove its concrete canonical receiver'


def protected_run(desk, tmp_path):
    from flinttrade_core.execution_sessions import ExecutionSessions
    # Retire the separate legacy fixture owner with its original session.
    legacy = desk.app.extensions['practice_agent_supervisor']
    legacy.stop(desk.owner)
    _wait_for(lambda: not legacy.run.thread.is_alive())
    sessions = ExecutionSessions(desk.app, tmp_path / 'protected-runs')
    desk.app.config['EXECUTION_SESSIONS'] = sessions
    scope, run = start(desk, sessions, identity='protected')
    book = sessions.binding(scope).sandbox
    policy = {**desk.policy, 'position': {**desk.policy['position'],
              'entry_order_ids': [book.get_trades()[0]['order_id']]}}
    response = desk.client.post('/api/v1/protection/grants', headers=desk.operator_headers,
        json={'run_id': scope.run_id, 'expected_revision': 0, 'policy': policy})
    assert response.status_code == 201, response.json
    return sessions, scope, run, policy


@pytest.mark.parametrize('case', ['api', 'foreign', 'expired', 'scoped', 'origin', 'unknown'])
def test_protection_readback_requires_current_exact_operator_without_creating_authority(protection_desk, case):
    desk = protection_desk
    headers = dict(desk.operator_headers)
    identity = desk.scope.run_id
    if case == 'api':
        headers = {'X-API-Key': 'synthetic'}
    elif case == 'foreign':
        headers = {'Authorization': 'Bearer ' + desk.token(sub='other', scopes=SCOPES)}
    elif case == 'expired':
        headers = {'Authorization': 'Bearer ' + desk.token(exp=1, scopes=SCOPES)}
    elif case == 'scoped':
        headers = {'Authorization': 'Bearer ' + desk.token(scopes=['admin.accounts.read'])}
    elif case == 'origin':
        headers['Origin'] = 'https://foreign.invalid'
    else:
        identity = 'unknown'
    before = dict(desk.protection._owners)
    response = desk.client.get('/api/v1/protection/grants/' + identity, headers=headers)
    assert response.status_code == 403
    assert response.headers['Cache-Control'] == 'no-store'
    assert desk.protection._owners == before
    assert not (desk.protection_path / 'protection.sqlite').exists()
    assert desk.read_calls == []


def test_issued_readback_is_nonmutating_and_revocation_retains_exact_duty(protection_desk):
    from packages.core.core.tests.test_protection_ingress import grant
    desk = protection_desk
    assert grant(desk).status_code == 201
    path = '/api/v1/protection/grants/' + desk.scope.run_id
    response = desk.client.get(path, headers=desk.operator_headers)
    assert response.status_code == 200, response.json
    data = response.json['data']
    assert data['revision'] == 1 and data['policy'] == desk.policy
    assert data['authority_state'] == 'active'
    assert data['usage'] == {'reads': 0, 'quantity_used': 0, 'notional_used': 0.0}
    assert data['duty'] == {'state': 'retained', 'remaining_quantity': 1,
                            'reconciliation_required': False, 'attempts': []}
    assert desk.client.get(path, headers=desk.operator_headers).json == response.json
    assert desk.read_calls == []
    revoked = desk.client.post(path + '/revoke', headers=desk.operator_headers, json={'expected_revision': 1})
    assert revoked.status_code == 200
    retired = desk.client.get(path, headers=desk.operator_headers).json['data']
    assert retired['authority_state'] == 'retired' and retired['revision'] == 2
    assert retired['duty']['state'] == 'retained' and retired['duty']['remaining_quantity'] == 1
    assert desk.read_calls == []


def test_recovered_grant_readback_reports_unknown_without_constructing_owner(protection_desk):
    from flinttrade_core.protection_grants import ProtectionServices
    from packages.core.core.tests.test_protection_ingress import grant
    desk = protection_desk
    assert grant(desk).status_code == 201
    desk.app.extensions['practice_agent_supervisor'].stop(desk.owner)
    _wait_for(lambda: not desk.run.thread.is_alive())
    recovered = ProtectionServices(desk.app, desk.protection_path)
    desk.app.config['PROTECTION_SERVICES'] = recovered
    reads = list(desk.read_calls)
    response = desk.client.get('/api/v1/protection/grants/' + desk.scope.run_id, headers=desk.operator_headers)
    assert response.status_code == 200, response.json
    data = response.json['data']
    assert data['revision'] == 1 and data['policy'] == desk.policy
    assert data['authority_state'] == 'unavailable'
    assert data['duty']['state'] == 'unknown' and data['duty']['remaining_quantity'] is None
    assert data['duty']['reconciliation_required']
    assert data['supervision'] == 'unavailable'
    assert recovered._owners == {} and recovered._reconciled == set()
    assert desk.read_calls == reads


def test_legacy_granted_loop_survives_logout_without_blanket_liquidation(protection_desk, monkeypatch):
    from packages.core.core.tests.test_protection_ingress import grant
    desk = protection_desk
    assert grant(desk).status_code == 201
    budget = desk.run.model_budget.snapshot()
    desk.revoked.add('practice-session')
    _wait_for(lambda: len(desk.read_calls) >= 3 or not desk.run.thread.is_alive())
    assert desk.run.thread.is_alive(), 'logout must retain independently granted fixed supervision'
    assert len(desk.read_calls) >= 3, 'observe repeated monitor cycles, not an in-flight forced close'
    assert len(desk.sandbox.get_trades()) == 1, 'logout itself is not a risk exit'
    async def loss_quote(session, symbols):
        desk.read_calls.append(('RELIANCE', 'NSE'))
        return [{'symbol': 'RELIANCE', 'exchange': 'NSE', 'ltp': 100.0, 'available': True}]
    monkeypatch.setattr(desk.app.config['ACTIVE_BROKER_ADAPTERS']['dhan'], 'quotes', loss_quote)
    _wait_for(lambda: len(desk.sandbox.get_trades()) == 2)
    _wait_for(lambda: not desk.run.thread.is_alive())
    assert desk.run.model_budget.snapshot() == budget
    assert desk.sandbox.get_positions() == []


def test_failed_registry_shutdown_keeps_live_duty_until_explicit_close(protection_desk, tmp_path):
    desk = protection_desk
    sessions, scope, run, _policy = protected_run(desk, tmp_path)
    try:
        assert not sessions.shutdown(5)
        assert run.thread.is_alive(), 'refused shutdown must not strand a resumable fixed duty'
        assert sessions.owners[scope.run_id].run is run
        assert not sessions.status(scope)['entries_armed']
        sessions.close_positions(scope, expected_generation=sessions.status(scope)['generation'])
        _wait_for(lambda: not run.thread.is_alive())
        assert sessions.status(scope)['books']['positions'] == []
        assert sessions.shutdown(5)
        sessions.close()
        desk.protection.close()
    finally:
        if not sessions.closed:
            release_dead_process_fixture(sessions, desk)


def release_dead_process_fixture(sessions, desk):
    """Model lost process resources only after joining every real worker."""
    from flinttrade_core.protection_grants import ProtectionServices
    sessions.shutdown(5)
    for owner in sessions.owners.values():
        owner.shutdown(5)  # Abrupt-process fixture, not the registry stop policy.
        assert not owner.run.thread or not owner.run.thread.is_alive()
        owner.store.close()
        owner._lease.release()
    for book in sessions.books.values():
        book.close()
    sessions.lease.release()
    desk.app.config.pop('EXECUTION_SESSIONS', None)
    desk.app.config['EXECUTION_SESSIONS_PATH'] = sessions.path
    desk.app.config['PROTECTION_SERVICES'] = ProtectionServices(desk.app, desk.protection_path)


@pytest.mark.parametrize('accepted', [False, True])
def test_restart_exact_uncertain_write_reconciles_or_retains_without_replay(protection_desk, tmp_path, monkeypatch, accepted):
    from flinttrade_core.execution_sessions_routes import resume_execution_protection
    desk = protection_desk
    sessions, scope, run, _policy = protected_run(desk, tmp_path)
    book = sessions.binding(scope).sandbox
    original = book.place_order
    writes = []
    def uncertain(**kwargs):
        writes.append(kwargs)
        if accepted:
            original(**kwargs)
        raise TimeoutError('synthetic unknown acknowledgement')
    with monkeypatch.context() as patch:
        patch.setattr(book, 'place_order', uncertain)
        sessions.close_positions(scope, expected_generation=sessions.status(scope)['generation'])
        _wait_for(lambda: not run.thread.is_alive())
    assert len(writes) == 1
    assert run.adapter.reconciliation_required
    count = len(book.get_trades())
    assert count == (2 if accepted else 1)
    assert not sessions.shutdown(0)
    release_dead_process_fixture(sessions, desk)
    try:
        result = resume_execution_protection(desk.app)
        sessions = desk.app.config['EXECUTION_SESSIONS']
        expected = 'settled' if accepted else 'unavailable'
        assert result == {'state': 'observed', 'runs': [{'run_id': scope.run_id, 'state': expected}]}
        retained = sessions.owners[scope.run_id]
        assert not retained.run.thread
        assert not sessions.status(scope)['entries_armed']
        assert len(sessions.status(scope)['books']['trades']) == count
        assert resume_execution_protection(desk.app) == result
        assert sessions.owners[scope.run_id] is retained
        if accepted:
            assert sessions.shutdown(5)
        else:
            assert not sessions.shutdown(0)
            assert desk.app.config['PROTECTION_SERVICES'].maintenance_snapshot()['disposal_authorised'] is False
    finally:
        # The negative intentionally retains unknown exposure. Only this
        # synthetic process-loss fixture disposes its dead test resources.
        release_dead_process_fixture(sessions, desk)


def test_restart_resumes_only_explicit_fixed_duty_without_model_or_replay(protection_desk, tmp_path, monkeypatch):
    from flinttrade_core import execution_sessions_routes as routes, agent_routes
    from flinttrade_core.protection_grants import ProtectionServices
    from flinttrade_core.run_adoption import ModelRunServices
    desk = protection_desk
    models = ModelRunServices(desk.app, tmp_path / 'model-owner')
    desk.app.config['MODEL_RUN_SERVICES'] = models
    sessions, scope, run, policy = protected_run(desk, tmp_path)
    try:
        # Logout does not force time liquidation. The actual loop keeps the duty.
        desk.revoked.add('practice-session')
        _wait_for(lambda: not sessions.status(scope)['entries_armed'])
        assert run.thread.is_alive() and len(sessions.status(scope)['books']['trades']) == 1
        observed = desk.client.get('/api/v1/protection/grants/' + scope.run_id,
            headers={'Authorization': 'Bearer ' + desk.token(jti='new-session', scopes=SCOPES)})
        assert observed.status_code == 200 and observed.json['data']['policy'] == policy
        assert observed.json['data']['supervision'] == 'supervising'
        # Abrupt-process-loss fixture: first prove every old worker is dead.
        # Ordinary shutdown correctly refuses to release outstanding duty.
        assert not sessions.shutdown(5)
        assert run.thread.is_alive()
        prior = sessions.owners[scope.run_id]
        assert not prior.shutdown(5)  # Simulate process loss only after actual join.
        assert not run.thread.is_alive()
        assert run.cleanup_complete
        prior.store.close()
        prior._lease.release()
        for book in sessions.books.values():
            book.close()
        sessions.lease.release()
        desk.app.config.pop('EXECUTION_SESSIONS')
        desk.app.config['EXECUTION_SESSIONS_PATH'] = sessions.path
        replacement = ProtectionServices(desk.app, desk.protection_path)
        desk.app.config['PROTECTION_SERVICES'] = replacement
        # No login/model operation may be used to restore independent duty.
        monkeypatch.setattr(agent_routes, '_build_llm', lambda: pytest.fail('recovery invoked inference'))
        assert hasattr(routes, 'resume_execution_protection'), 'restart supervision seam missing'
        result = routes.resume_execution_protection(desk.app)
        assert result == {'state': 'observed', 'runs': [{'run_id': scope.run_id, 'state': 'supervising'}]}
        sessions = desk.app.config['EXECUTION_SESSIONS']
        resumed = sessions.owners[scope.run_id].run
        assert resumed is not run and resumed.thread.is_alive()
        assert models.runs.owner(scope.run_id).supervisor is sessions.owners[scope.run_id]
        assert models.runs.scope(scope.run_id) == scope
        assert not sessions.status(scope)['entries_armed']
        assert len(sessions.status(scope)['books']['trades']) == 1
        assert routes.resume_execution_protection(desk.app) == result
        assert sessions.owners[scope.run_id].run is resumed
        async def loss_quote(session, symbols):
            desk.read_calls.append(('RELIANCE', 'NSE'))
            return [{'symbol': 'RELIANCE', 'exchange': 'NSE', 'ltp': 100.0, 'available': True}]
        monkeypatch.setattr(desk.app.config['ACTIVE_BROKER_ADAPTERS']['dhan'], 'quotes', loss_quote)
        _wait_for(lambda: len(sessions.status(scope)['books']['trades']) == 2)
        _wait_for(lambda: not resumed.thread.is_alive())
        assert sessions.status(scope)['books']['positions'] == []
        assert not sessions.status(scope)['entries_armed']
        assert len(desk.sandbox.get_trades()) == 2, 'manual/other book unchanged'
        assert sessions.shutdown(5)
        # No replay or read occurs after completed recovery.
        assert routes.resume_execution_protection(desk.app)['runs'][0]['state'] == 'settled'
        sessions.close()
        replacement.close()
        replacement.close()
        assert replacement._closed
    finally:
        for owner in sessions.owners.values():
            owner.shutdown(5)
            if owner.run and owner.run.thread:
                assert not owner.run.thread.is_alive()
        sessions.close()
