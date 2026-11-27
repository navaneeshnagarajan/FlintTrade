"""Public recovery and concurrent lifecycle regressions with inert broker I/O."""
from __future__ import annotations

import pytest

from packages.core.core.tests.test_native_autonomy import URL, armed, desk as desk


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask
    from flask.testing import FlaskClient


def order_row(*, filled: "int" = 0, state: "str" = 'CANCELLED') -> "dict[str, str]":
    """Construct one synthetic native order observation without inferring its lifecycle.

    Args:
        filled: Observed whole filled quantity for the synthetic order.
        state: Native order-book status emitted verbatim in the synthetic row.

    Returns:
        String-valued native order fields retaining the requested fill and status.
    """
    return {'order_id': 'inert-order-1', 'symbol': 'INFY', 'exchange': 'NSE', 'product': 'CNC',
            'action': 'BUY', 'quantity': '2', 'filled_qty': str(filled), 'status': state,
            'price': '100', 'pricetype': 'LIMIT'}


def restart(app: "Flask") -> None:
    """Reopen the execution-session owner against its existing durable store.

    Args:
        app: App retaining the execution-session and account lifecycle owners.
    """
    from flinttrade_core.execution_sessions import ExecutionSessions
    old = app.config['EXECUTION_SESSIONS']
    old.close()
    app.config['EXECUTION_SESSIONS'] = ExecutionSessions(app, old.path)


@pytest.mark.integration
@pytest.mark.parametrize('book', ['positions', 'holdings', 'trade_book', 'order_book'])
@pytest.mark.parametrize('bad', [None, {}, {'data': [], 'complete': False}, [None], [1], 'missing'])
def test_incomplete_books_never_admit_or_settle(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    monkeypatch: "pytest.MonkeyPatch",
    book: "str",
    bad: "object",
) -> None:
    """Reject incomplete books for both command admission and obligation settlement.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        monkeypatch: Scoped replacements restored after this test.
        book: Broker collection replaced with unavailable or malformed evidence.
        bad: Deliberately invalid input; no canonical production type is implied.
    """
    app, client, headers, _other = desk
    command = armed(desk)
    source = app.config['NATIVE_ADAPTERS']['dhan']
    original = getattr(source, book)

    async def incomplete(_session):
        return bad

    monkeypatch.setattr(source, book, None if bad == 'missing' else incomplete)
    refused = client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers)
    assert refused.status_code in {409, 503}, refused.json
    assert source.writes == []
    monkeypatch.setattr(source, book, original)
    admitted = client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers)
    assert admitted.json['data']['state'] == 'acknowledged'
    source.orders = [order_row()]
    monkeypatch.setattr(source, book, None if bad == 'missing' else incomplete)
    result = client.post(URL + '/bounded-one/autonomy/reconcile', json={}, headers=headers)
    assert result.status_code in {409, 503}, result.json
    status = client.get(URL + '/bounded-one/autonomy', headers=headers).json['data']
    assert status['obligations'] == ['command-one'] and not status['native_ready']
    assert len(source.writes) == 1


@pytest.mark.integration
@pytest.mark.parametrize('reopen', [False, True])
@pytest.mark.parametrize('known,later', [(1, 0), (2, 0), (2, 1)])
def test_known_fill_and_handback_survive_lower_observation_and_restart(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    known: "int",
    later: "int",
    reopen: "bool",
) -> None:
    """Retain known fills and custody despite lower later observations or restart.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        known: Already retained filled quantity before the lower observation.
        later: Subsequent lower filled quantity used to challenge monotonic retention.
        reopen: Whether to reopen the execution owner before checking retained fills.
    """
    app, client, headers, _other = desk
    command = armed(desk)
    source = app.config['NATIVE_ADAPTERS']['dhan']
    assert client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers).json['data'][
        'state'] == 'acknowledged'
    source.orders = [order_row(filled=known, state='FILLED' if known == 2 else 'PARTIAL')]
    first = client.post(URL + '/bounded-one/autonomy/reconcile', json={}, headers=headers).json['data']
    assert first['commands'][0]['filled_quantity'] == known
    if reopen:
        restart(app)
        recovered = client.get(URL + '/bounded-one/autonomy', headers=headers).json['data']
        assert recovered['commands'][0]['filled_quantity'] == known
        assert not recovered['authorised']
    source.orders = [order_row(filled=later)]
    result = client.post(URL + '/bounded-one/autonomy/reconcile', json={}, headers=headers)
    assert result.status_code == 200, result.json
    row = result.json['data']
    assert row['commands'][0]['filled_quantity'] == known
    assert row['commands'][0]['state'] == 'reconciling'
    assert row['obligations'] == ['command-one'] and not row['native_ready']
    assert row['protection'] == 'operator_handback_required'
    assert app.config['EXECUTION_SESSIONS'].shutdown(timeout=0) is False
    assert len(source.writes) == 1


@pytest.mark.integration
@pytest.mark.parametrize('operation', ['submit', 'cancel', 'reconcile'])
@pytest.mark.parametrize('retire', ['stop', 'revoke'])
def test_broker_book_wait_never_blocks_entry_retirement(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    monkeypatch: "pytest.MonkeyPatch",
    operation: "str",
    retire: "str",
) -> None:
    """Allow Stop or revoke to finish while the real broker read remains held.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        monkeypatch: Scoped replacements restored after this test.
        operation: Public lifecycle or command operation exercised by this control.
        retire: Stop or revoke action attempted while the broker read is held.
    """
    import threading
    from flinttrade_core.broker_client import BrokerClient
    from flinttrade_core.config import Settings

    app, client, headers, _other = desk
    shared = BrokerClient(Settings())
    shared.bind(app)
    app.config['CLIENT'] = shared
    command = armed(desk, actions=['place', 'cancel'])
    source = app.config['NATIVE_ADAPTERS']['dhan']
    if operation != 'submit':
        assert client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers).json['data'][
            'state'] == 'acknowledged'
        source.orders = [order_row(state='OPEN')]
    target = dict(command)
    if operation == 'cancel':
        target.pop('order')
        target.update(command_id='cancel-one', cancel={'placement_command_id': 'command-one'})
    before = client.get(URL + '/bounded-one', headers=headers).json['data']
    entered, release, retired = threading.Event(), threading.Event(), threading.Event()
    original = source.positions

    async def held(session):
        entered.set()
        assert release.wait(4), 'coordinator did not release inert book reader'
        return await original(session)

    monkeypatch.setattr(source, 'positions', held)
    responses = {}

    def inspect():
        path = '/bounded-one/autonomy/reconcile' if operation == 'reconcile' else '/bounded-one/autonomy/commands'
        responses['read'] = app.test_client().post(URL + path, json={} if operation == 'reconcile' else target,
            headers=headers)

    def stop():
        if retire == 'stop':
            responses['stop'] = app.test_client().post(URL + '/bounded-one/stop', headers=headers, json={
                'account': before['account'], 'environment': 'live', 'expected_generation': before['generation']})
        else:
            responses['stop'] = app.test_client().post(URL + '/bounded-one/autonomy/revoke', headers=headers,
                                                       json={'grant_id': 'grant-one'})
        retired.set()

    reading = threading.Thread(target=inspect, daemon=True)
    stopping = threading.Thread(target=stop, daemon=True)
    try:
        reading.start()
        assert entered.wait(2)
        stopping.start()
        assert retired.wait(1), 'entry retirement waited for external book I/O'
    finally:
        release.set()
        reading.join(5)
        if stopping.ident is not None:
            stopping.join(5)
        shared.close_sync()
    assert not reading.is_alive() and not stopping.is_alive()
    assert responses['stop'].status_code == 200
    assert responses['read'].status_code == 409, responses['read'].json
    assert len(source.writes) == (0 if operation == 'submit' else 1)
    assert client.get(URL + '/bounded-one/autonomy', headers=headers).json['data']['authorised'] is False


@pytest.mark.integration
def test_effective_kill_readiness_agrees_with_admission_and_keeps_read_only_inspection(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
) -> None:
    """Expose effective kill refusal consistently without losing read-only inspection.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
    """
    from flinttrade_core.auth_routes import _create_token
    app, client, headers, _other = desk
    command = armed(desk)
    with app.app_context():
        token = _create_token('synthetic-operator', mode='practice',
                              scopes=('admin.accounts.read', 'admin.services.read'))
    read_headers = {'Authorization': 'Bearer ' + token}
    assert client.get(URL + '/bounded-one/autonomy', headers=read_headers).json['data']['native_ready']
    app.config['SAFETY'].l5_kill.activate('inert-kill-readiness-control')
    status = client.get(URL + '/bounded-one/autonomy', headers=read_headers)
    assert status.status_code == 200
    row = status.json['data']
    assert row['authorised'] is False and row['native_ready'] is False
    assert row['state'] == 'entries_stopped'
    assert row['admission_reason'] == 'kill_switch_latched'
    registry = client.get(URL + '/bounded-one', headers=read_headers).json['data']
    assert registry['native_ready'] is False and registry['state'] == 'entries_stopped'
    refused = client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers)
    assert refused.status_code == 409
    assert app.config['NATIVE_ADAPTERS']['dhan'].writes == []


@pytest.mark.integration
@pytest.mark.parametrize('storage', ['database-only', 'marker-only', 'intact', 'absent'])
def test_native_storage_custody_is_honest_through_status_stop_logout_shutdown(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    storage: "str",
) -> None:
    """Preserve honest custody across status, Stop, logout and shutdown for each storage state.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        storage: Native database/authority-marker presence combination under inspection.
    """
    from flinttrade_core.auth_routes import _create_token, auth_bp
    from flinttrade_core.execution_session import ExecutionSession
    from flinttrade_core.execution_sessions_routes import get_execution_sessions

    app, client, headers, _other = desk
    app.register_blueprint(auth_bp)
    if storage == 'absent':
        owner = get_execution_sessions(app)
        from flinttrade_core.auth_routes import verify_operator_session_token
        with app.app_context():
            actor = verify_operator_session_token(headers['Authorization'][7:]).actor_ref
        owner.create(ExecutionSession('bounded-one', actor, 'dhan:inert-account', 'live'), kind='strategy', config={})
    else:
        command = armed(desk)
        assert client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers).json['data'][
            'state'] == 'acknowledged'
        owner = app.config['EXECUTION_SESSIONS']
    path = owner.path
    owner.close()
    if storage == 'database-only':
        (path / 'autonomy.sqlite.authority.json').unlink()
    elif storage == 'marker-only':
        (path / 'autonomy.sqlite').unlink()
    from flinttrade_core.execution_sessions import ExecutionSessions
    app.config['EXECUTION_SESSIONS'] = ExecutionSessions(app, path)
    owner = app.config['EXECUTION_SESSIONS']
    row = client.get(URL + '/bounded-one', headers=headers).json['data']
    incomplete = storage in {'database-only', 'marker-only'}
    if incomplete:
        assert row['state'] == 'custody_unknown'
        assert row['native_ready'] is False
    elif storage == 'intact':
        assert row['autonomy']['obligations'] == ['command-one']
    else:
        assert row['state'] == 'native_unavailable'
    stop = client.post(URL + '/bounded-one/stop', headers=headers, json={
        'account': row['account'], 'environment': 'live', 'expected_generation': row['generation']})
    assert stop.status_code == (409 if incomplete else 200), stop.json
    logout = client.post('/v1/auth/logout', headers=headers, json={})
    assert logout.status_code == 200, logout.json
    with app.app_context():
        fresh = _create_token('synthetic-operator', mode='practice')
    observed = client.get(URL + '/bounded-one', headers={'Authorization': 'Bearer ' + fresh}).json['data']
    assert not observed['native_ready']
    if incomplete:
        assert observed['state'] == 'custody_unknown'
        with pytest.raises(ValueError):
            owner.retire_actor(row['actor'])
    assert owner.shutdown(timeout=0) is (storage == 'absent')
    assert (path / 'autonomy.sqlite').exists() is (storage in {'intact', 'database-only'})
    assert (path / 'autonomy.sqlite.authority.json').exists() is (storage in {'intact', 'marker-only'})


@pytest.mark.integration
def test_closed_registry_is_not_proof_native_obligations_drained(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
) -> None:
    """Keep closed-registry state distinct from drained native obligations.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
    """
    app, client, headers, _other = desk
    command = armed(desk)
    assert client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers).json['data'][
        'state'] == 'acknowledged'
    owner = app.config['EXECUTION_SESSIONS']
    owner.close()
    assert owner.shutdown(timeout=0) is False
    restart(app)
    row = client.get(URL + '/bounded-one/autonomy', headers=headers).json['data']
    assert row['obligations'] == ['command-one']
    assert not row['authorised']
