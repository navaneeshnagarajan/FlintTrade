"""Event-held public command races; real gate, router and client loop."""
from __future__ import annotations

import sys
import threading
import time
import traceback
from dataclasses import replace

import pytest

from packages.core.core.tests.test_native_autonomy import CONFIG, URL, armed, desk as desk
from packages.core.core.tests.test_native_autonomy_recovery import order_row


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask
    from flask.testing import FlaskClient
    from flinttrade_core.native_autonomy import NativeQualificationEvidence
    from typing import Any


def second_run(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    first: "dict[str, Any]",
    monkeypatch: "pytest.MonkeyPatch",
) -> "tuple[dict[str, Any], threading.local, tuple[NativeQualificationEvidence, NativeQualificationEvidence]]":
    """Two independent synthetic attestations, selected by their test callers.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        first: First run's command used as the template for the independent second run.
        monkeypatch: Scoped replacements restored after this test.

    Returns:
        Second command, thread-local selector and the two original qualification observations.

    Raises:
        AssertionError: A real configuration, qualification or grant route rejects the second control.
    """
    from flinttrade_core.native_autonomy import NativeQualificationEvidence
    app, client, headers, _other = desk
    provider = app.config['NATIVE_AUTONOMY_QUALIFIER']
    first_evidence = provider.evidence
    local = threading.local()
    monkeypatch.setattr(provider, 'current_evidence', lambda: getattr(local, 'evidence', provider.evidence))
    config = {**CONFIG, 'run_id': 'second-run'}
    created = client.post(URL + '/native', json=config, headers=headers)
    assert created.status_code == 201
    owner = app.config['EXECUTION_SESSIONS'].autonomy
    app.config['NATIVE_AUTONOMY_BINDINGS']['second-run'] = config
    provider.evidence = NativeQualificationEvidence(
        created.json['data']['revision'], owner.qualification_binding('second-run'), 'second-inert-proof',
        'synthetic-inert-external-adapter-only', time.time() + 300)
    assert client.post(URL + '/second-run/autonomy/qualify', json={}, headers=headers).status_code == 200
    grant = {'grant_id': 'grant-two', 'expires_at': time.time() + 60,
             'instruments': [{'symbol': 'INFY', 'exchange': 'NSE'}], 'actions': ['place'],
             'max_order_quantity': 2, 'max_total_quantity': 2, 'max_total_notional': 220,
             'max_loss': 220, 'max_commands': 1}
    assert client.post(URL + '/second-run/autonomy/grant', json=grant, headers=headers).status_code == 200
    command = {**first, 'expected_revision': created.json['data']['revision'], 'grant_id': 'grant-two'}
    return command, local, (first_evidence, provider.evidence)


@pytest.mark.integration
@pytest.mark.parametrize('race', ['cross-run', 'replay-place', 'replay-cancel'])
def test_simultaneous_commands_preserve_account_fence_and_exact_replay(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    monkeypatch: "pytest.MonkeyPatch",
    race: "str",
) -> None:
    """Preserve account exclusion and exact replay under simultaneous commands.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        monkeypatch: Scoped replacements restored after this test.
        race: Competing cross-run or identical-command replay arrangement.
    """
    app, client, headers, _other = desk
    first = armed(desk, actions=['place', 'cancel'])
    source = app.config['NATIVE_ADAPTERS']['dhan']
    writes_before = 0
    if race == 'replay-cancel':
        assert client.post(URL + '/bounded-one/autonomy/commands', json=first, headers=headers).json['data'][
            'state'] == 'acknowledged'
        source.orders = [order_row(state='OPEN')]
        first = {key: value for key, value in first.items() if key != 'order'}
        first.update(command_id='cancel-one', cancel={'placement_command_id': 'command-one'})
        writes_before = 1
    second, local, evidence = first, None, None
    if race == 'cross-run':
        second, local, evidence = second_run(desk, first, monkeypatch)
    entered = [threading.Event(), threading.Event()]
    released = [threading.Event(), threading.Event()]
    responses = {}
    original = source.positions

    async def held(session):
        index = 0 if threading.current_thread().name == 'first-command' else 1
        entered[index].set()
        assert released[index].wait(5)
        return await original(session)

    monkeypatch.setattr(source, 'positions', held)

    def submit(index, command):
        if local is not None:
            local.evidence = evidence[index]
        run = 'second-run' if race == 'cross-run' and index == 1 else 'bounded-one'
        responses[index] = app.test_client().post(URL + f'/{run}/autonomy/commands', json=command, headers=headers)

    threads = [threading.Thread(target=submit, args=(i, command), name=name, daemon=True)
               for i, command, name in ((0, first, 'first-command'), (1, second, 'second-command'))]
    try:
        for thread in threads:
            thread.start()
        assert all(event.wait(2) for event in entered), 'both public commands must reach their external book read'
        released[0].set()
        threads[0].join(4)
        assert not threads[0].is_alive()
        assert responses[0].status_code == 200, responses[0].json
        assert responses[0].json['data']['state'] == ('cancel_requested' if race == 'replay-cancel' else 'acknowledged')
        released[1].set()
    finally:
        for event in released:
            event.set()
        for thread in threads:
            thread.join(5)
    assert all(not t.is_alive() for t in threads)
    assert len(source.writes) == writes_before + 1
    if race == 'cross-run':
        assert responses[1].status_code == 409, responses[1].json
    else:
        assert responses[1].json == responses[0].json


@pytest.mark.integration
@pytest.mark.timeout(65)
@pytest.mark.parametrize('retire', [False, True])
def test_shared_loop_invocation_and_reconciliation_never_form_a_lock_cycle(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    monkeypatch: "pytest.MonkeyPatch",
    retire: "bool",
) -> None:
    """Complete public reconciliation without a registry/shared-loop lock cycle.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        monkeypatch: Scoped replacements restored after this test.
        retire: Whether entry permission is retired while the invocation is held.
    """
    from flinttrade_core.broker_client import BrokerClient
    from flinttrade_core.config import Settings
    app, client, headers, _other = desk
    shared = BrokerClient(Settings())
    shared.bind(app)
    app.config['CLIENT'] = shared
    command = armed(desk)
    before = client.get(URL + '/bounded-one', headers=headers).json['data']
    router = app.config['BROKER_ROUTER']
    original = router._session_provider
    entered, release = threading.Event(), threading.Event()

    def session(ctx, broker, account):
        if ctx is not None:
            entered.set()
            assert release.wait(5)
        return original(ctx, broker, account)

    monkeypatch.setattr(router, '_session_provider', session)  # external session lookup only
    responses = {}

    def submit():
        responses['submit'] = app.test_client().post(URL + '/bounded-one/autonomy/commands', json=command,
            headers=headers)

    def reconcile():
        responses['reconcile'] = app.test_client().post(URL + '/bounded-one/autonomy/reconcile', json={},
            headers=headers)

    placing = threading.Thread(target=submit, daemon=True)
    reading = threading.Thread(target=reconcile, daemon=True)
    try:
        placing.start()
        assert entered.wait(2)
        reading.start()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            frame = sys._current_frames().get(reading.ident)
            if frame and any(f.name == 'run_sync' for f in traceback.extract_stack(frame)):
                break
            time.sleep(.01)
        else:
            pytest.fail('reconciliation did not queue its real client-loop read')
        if retire:
            stopped = client.post(URL + '/bounded-one/stop', headers=headers, json={
                'account': before['account'], 'environment': 'live', 'expected_generation': before['generation']})
            assert stopped.status_code == 200
        release.set()
        placing.join(2)
        reading.join(2)
        assert not placing.is_alive() and not reading.is_alive(), 'shared loop and registry formed a wait cycle'
    finally:
        release.set()
        placing.join(50)
        if reading.ident is not None:
            reading.join(5)
        shared.close_sync()
    assert responses['submit'].json['data']['state'] == ('refused' if retire else 'acknowledged')
    assert responses['reconcile'].status_code == 409, responses['reconcile'].json
    assert len(app.config['NATIVE_ADAPTERS']['dhan'].writes) == (0 if retire else 1)


@pytest.mark.integration
@pytest.mark.timeout(65)
def test_pending_real_client_timeout_is_uncertain_even_without_invocation_or_lifecycle_row(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    """Retain possible invocation after client timeout even without a lifecycle row.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        monkeypatch: Scoped replacements restored after this test.
    """
    from flinttrade_core.broker_client import BrokerClient
    from flinttrade_core.config import Settings
    app, client, headers, _other = desk
    shared = BrokerClient(Settings())
    shared.bind(app)
    app.config['CLIENT'] = shared
    command = armed(desk)
    router = app.config['BROKER_ROUTER']
    original = router._session_provider
    entered, release = threading.Event(), threading.Event()

    def session(ctx, broker, account):
        if ctx is not None:
            entered.set()
            assert release.wait(55)
        return original(ctx, broker, account)

    monkeypatch.setattr(router, '_session_provider', session)
    responses = []
    thread = threading.Thread(target=lambda: responses.append(app.test_client().post(
        URL + '/bounded-one/autonomy/commands', json=command, headers=headers)), daemon=True)
    try:
        thread.start()
        assert entered.wait(3)
        assert app.config['ORDER_LIFECYCLE_LEDGER'].list_dispatch_attempts() == []
        assert app.config['NATIVE_ADAPTERS']['dhan'].writes == []
        # Use the unchanged real 45-second client deadline, not a fake timeout.
        thread.join(48)
        assert not thread.is_alive()
        receipt = responses[0].json['data']
        assert receipt['state'] == 'uncertain'
        assert 'dispatched' not in receipt['events']
        status = client.get(URL + '/bounded-one/autonomy', headers=headers).json['data']
        assert status['obligations'] == ['command-one']
        assert client.post(URL + '/bounded-one/autonomy/commands', json=command,
            headers=headers).json == responses[0].json
    finally:
        release.set()
        thread.join(5)
        shared.close_sync()
    assert app.config['NATIVE_ADAPTERS']['dhan'].writes == []


@pytest.mark.integration
@pytest.mark.parametrize('error', ['timeout', 'value', 'safety'])
def test_exception_class_and_http_refusal_after_invocation_never_prove_nonexecution(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    monkeypatch: "pytest.MonkeyPatch",
    error: "str",
) -> None:
    """Keep post-invocation errors uncertain regardless of exception class or HTTP shape.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        monkeypatch: Scoped replacements restored after this test.
        error: Post-invocation exception class selected for the uncertainty control.
    """
    from flinttrade_core.exceptions import SafetyBypassError
    app, client, headers, _other = desk
    command = armed(desk)
    source = app.config['NATIVE_ADAPTERS']['dhan']
    exception = {'timeout': TimeoutError, 'value': ValueError, 'safety': SafetyBypassError}[error]

    def lost(**fields):
        source.writes.append(fields)
        raise exception('inert possible acceptance followed by error')

    monkeypatch.setattr(source, 'place_order', lost)
    response = client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers)
    assert response.json['data']['state'] == 'uncertain'
    assert 'dispatched' in response.json['data']['events']
    assert client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers).json == response.json
    assert len(source.writes) == 1


@pytest.mark.integration
@pytest.mark.parametrize('drift', ['revision', 'account-session'])
def test_scope_drift_during_book_wait_is_not_adopted(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    monkeypatch: "pytest.MonkeyPatch",
    drift: "str",
) -> None:
    """Refuse changed scope after a held book read returns.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        monkeypatch: Scoped replacements restored after this test.
        drift: Scope component changed while the real book read is held.
    """
    app, client, headers, _other = desk
    command = armed(desk)
    source = app.config['NATIVE_ADAPTERS']['dhan']
    original = source.positions
    changed = False

    async def change(session):
        nonlocal changed
        if not changed:
            changed = True
            if drift == 'revision':
                app.config['NATIVE_AUTONOMY_BINDINGS']['bounded-one']['config_revision'] = 'changed'
            else:
                wrong = replace(session, account_id='Inert-account')
                monkeypatch.setattr(app.config['REGISTRY'], 'get_session_for', lambda _b, _a: wrong)
        return await original(session)

    monkeypatch.setattr(source, 'positions', change)
    response = client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers)
    assert response.status_code == 409, response.json
    assert source.writes == []


@pytest.mark.integration
@pytest.mark.parametrize('operation', ['place', 'cancel'])
def test_completed_queued_refusal_retires_only_the_refused_command(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    monkeypatch: "pytest.MonkeyPatch",
    operation: "str",
) -> None:
    """Retire only the command whose queued refusal completed before invocation.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        monkeypatch: Scoped replacements restored after this test.
        operation: Public lifecycle or command operation exercised by this control.
    """
    from flinttrade_core.exceptions import SafetyBypassError
    app, client, headers, _other = desk
    command = armed(desk, actions=['place', 'cancel'])
    source = app.config['NATIVE_ADAPTERS']['dhan']
    if operation == 'cancel':
        assert client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers).json['data'][
            'state'] == 'acknowledged'
        source.orders = [order_row(state='OPEN')]
        command = {k: v for k, v in command.items() if k != 'order'}
        command.update(command_id='cancel-one', cancel={'placement_command_id': 'command-one'})

    def unavailable(_ctx, _broker, _account):
        raise SafetyBypassError('inert session resolution refused before adapter invocation')

    monkeypatch.setattr(app.config['BROKER_ROUTER'], '_session_provider', unavailable)
    response = client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers)
    assert response.json['data']['state'] == 'refused'
    assert response.json['data']['events'] == ['pending_admission', 'admitted', 'refused']
    assert response.json['data']['cause'] == 'canonical_completed_pre_invocation_refusal'
    assert client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers).json == response.json
    status = client.get(URL + '/bounded-one/autonomy', headers=headers).json['data']
    assert status['obligations'] == (['command-one'] if operation == 'cancel' else [])
    assert len(source.writes) == (1 if operation == 'cancel' else 0)


@pytest.mark.integration
def test_completed_refusal_does_not_fence_a_new_independently_granted_run(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    """Permit an independently granted run after the prior command's completed refusal.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        monkeypatch: Scoped replacements restored after this test.
    """
    from flinttrade_engine.laya import DecisionStatus, process_laya
    app, client, headers, _other = desk
    first = armed(desk)
    process_laya().set_status(DecisionStatus.DOWN)
    refused = client.post(URL + '/bounded-one/autonomy/commands', json=first, headers=headers)
    assert refused.json['data']['state'] == 'refused'
    process_laya().set_status(DecisionStatus.READY)
    second, _local, _evidence = second_run(desk, first, monkeypatch)
    # The inert session resolver explicitly accepts this second exact actor;
    # risk, one-shot gate, router ACL/frontier and lifecycle remain unchanged.
    def session(ctx, broker, account):
        assert ctx.actor_type == 'agent' and ctx.actor_id == 'bounded:second-run'
        assert (broker, account) == ('dhan', 'inert-account')
        return app.config['REGISTRY'].get_session_for(broker, account)
    monkeypatch.setattr(app.config['BROKER_ROUTER'], '_session_provider', session)
    admitted = client.post(URL + '/second-run/autonomy/commands', json=second, headers=headers)
    assert admitted.json['data']['state'] == 'acknowledged', admitted.json
    assert client.post(URL + '/bounded-one/autonomy/commands', json=first, headers=headers).json == refused.json
    assert len(app.config['NATIVE_ADAPTERS']['dhan'].writes) == 1
