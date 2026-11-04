"""Public bounded-run tests. All broker/provider observations here are inert."""
from __future__ import annotations

import time

import pytest
from flask import Flask

from flinttrade_core.auth_routes import _create_token
from flinttrade_core.backend_instance import acquire_backend_instance_lease
from flinttrade_core.execution_sessions_routes import install_execution_sessions


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from flask.testing import FlaskClient
    from flinttrade_core.native_autonomy import NativeQualificationEvidence
    from flinttrade_gateway.brokers._base import Session
    from pathlib import Path
    from typing import Any


class InertBrokerIO:
    """Only external I/O is doubled; no auth, risk, ledger or router stubs."""
    def __init__(self) -> None:
        self.writes = []
        self.orders = []
        self.position_rows = []
        self.timeout = False
        self.on_quotes = None
    async def positions(self, session: "Session") -> "list[dict[str, Any]]":
        """Return a detached list of the configured inert position observations.

        Args:
            session: Broker session supplied by the real adapter call.

        Returns:
            Synthetic position rows, without inferring completeness beyond this fixture.
        """
        return list(self.position_rows)
    async def order_book(self, session: "Session") -> "list[dict[str, Any]]":
        """Return detached copies of the configured inert native order rows.

        Args:
            session: Broker session supplied by the real adapter call.

        Returns:
            Synthetic order rows retaining the configured quantities, statuses and identities.
        """
        return [dict(row) for row in self.orders]
    async def trade_book(self, session: "Session") -> "list[dict[str, Any]]":
        """Supply the fixture's explicitly empty trade collection.

        Args:
            session: Broker session supplied by the real adapter call.

        Returns:
            An empty trade list from the inert transport.
        """
        return []
    async def holdings(self, session: "Session") -> "list[dict[str, Any]]":
        """Supply the fixture's explicitly empty holdings collection.

        Args:
            session: Broker session supplied by the real adapter call.

        Returns:
            An empty holdings list from the inert transport.
        """
        return []
    async def funds(self, session: "Session") -> "dict[str, str]":
        """Supply the fixed synthetic funding observation for bounded-run tests.

        Args:
            session: Broker session supplied by the real adapter call.

        Returns:
            The fixture's string-valued balance, used margin and opening capital fields.
        """
        return {'used_margin': '0', 'total_balance': '1000000', 'opening_risk_capital': '1000000'}
    async def quotes(self, session: "Session", symbols: "list[str]") -> "list[dict[str, Any]]":
        """Observe the optional race callback before returning synthetic requested quotes.

        Args:
            session: Broker session supplied by the real adapter call.
            symbols: Exchange-prefixed instrument names requested by the quote reader.

        Returns:
            Fixed-price quote rows preserving each requested exchange and symbol.
        """
        if self.on_quotes:
            self.on_quotes()
        return [{'symbol': s.split(':')[1], 'exchange': s.split(':')[0], 'ltp': 100,
                 'prev_close': 100, 'previous_close_trusted': True} for s in symbols]
    async def margin_calculator(self, session: "Session", orders: "list[dict[str, Any]]") -> "dict[str, str]":
        """Supply the fixed inert margin observation without computing trading authority.

        Args:
            session: Broker session supplied by the real adapter call.
            orders: Order dictionaries passed to the inert margin endpoint.

        Returns:
            The fixture's required-margin dictionary.
        """
        return {'required_margin': '200'}
    def cancel_order(self, order_id: "str") -> "dict[str, Any]":
        """Record an inert cancellation and echo its exact native order identity.

        Args:
            order_id: Exact broker order identity recorded in the cancellation receipt.

        Returns:
            Synthetic successful cancellation acknowledgement, not settlement evidence.
        """
        self.writes.append({'cancel_order_id': order_id})
        return {'status': 'success', 'data': {'orderId': order_id}}
    def place_order(self, **fields: "Any") -> "dict[str, Any]":
        """Record native placement fields before returning or losing the synthetic acknowledgement.

        Args:
            fields: Native placement keyword values recorded without coercion.

        Returns:
            Synthetic placement acknowledgement for the fixture's fixed order identity.

        Raises:
            TimeoutError: The configured lost-response control is active after recording the write.
        """
        self.writes.append(dict(fields))
        if self.timeout:
            raise TimeoutError('inert lost response')
        return {'status': 'success', 'data': {'orderId': 'inert-order-1'}}


@pytest.fixture
def desk(tmp_path: "Path") -> "Iterator[tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]]":
    """Own a bounded-run HTTP fixture with real safety, router and ledger owners.

    Args:
        tmp_path: Disposable workspace directory supplied by pytest.

    Yields:
        App, client, owner headers and foreign-operator headers until the owned teardown runs.
    """
    lease = acquire_backend_instance_lease()
    app = Flask(__name__)
    from types import SimpleNamespace
    from flinttrade_engine.safety import SafetySystem, SafetyConfig, SafetyGate, set_safety_gate_secret
    from flinttrade_gateway.brokers._base import Session
    from flinttrade_gateway.brokers.dhan import DhanAdapter
    from flinttrade_gateway.router import BrokerRouter
    from flinttrade_engine.local_state_provider import OrderLifecycleLedger
    from flinttrade_engine.laya import process_laya, DecisionStatus, reset_process_laya_for_tests
    reset_process_laya_for_tests()
    process_laya().set_status(DecisionStatus.READY)
    set_safety_gate_secret(b'inert-autonomy-suite-only-signing-key')
    source = InertBrokerIO()
    session = Session('inert-session', 4102444800.0, 'inert-account', 'dhan')
    def session_for(ctx, broker, account):
        assert (broker, account) == ('dhan', 'inert-account')
        if ctx is not None:
            assert ctx.actor_type == 'agent' and ctx.actor_id == 'bounded:bounded-one'
        return session
    adapter = DhanAdapter(client_factory=lambda _session: source, security_resolver=lambda s,e: 'inert-security')
    ledger = OrderLifecycleLedger(ledger_path=tmp_path / 'lifecycle.sqlite')
    router = BrokerRouter({'dhan': adapter}, session_for, consume_gate=SafetyGate().consume,
                          backend_lease_proof=lease.proof, lifecycle_store=ledger)
    app.config.update(TESTING=True, BACKEND_LEASE_PROOF=lease.proof, RUNTIME_ACCEPTING_REQUESTS=True,
                      BROKER_ROUTER=router, NATIVE_ADAPTERS={'dhan': source},
                      REGISTRY=SimpleNamespace(get_session_for=lambda b,a: session_for(None,b,a)),
                      SAFETY=SafetySystem(SafetyConfig(check_market_hours=False)), SAFETY_CONFIG_READY=True,
                      ORDER_LIFECYCLE_LEDGER=ledger)
    install_execution_sessions(app, tmp_path)
    with app.app_context():
        token = _create_token('synthetic-operator', mode='live', live_mode_unlocked=True)
        other = _create_token('different-synthetic-operator', mode='live', live_mode_unlocked=True)
    headers = {'Authorization': 'Bearer ' + token}
    try:
        yield app, app.test_client(), headers, {'Authorization': 'Bearer ' + other}
    finally:
        owner = app.config.get('EXECUTION_SESSIONS')
        if owner is not None:
            owner.close()
        router.revoke_and_drain(timeout=0)
        reset_process_laya_for_tests()
        lease.release()


CONFIG = {'run_id': 'bounded-one', 'broker': 'dhan', 'account_id': 'inert-account',
          'strategy_revision': 'strategy-1', 'config_revision': 'config-1',
          'policy_revision': 'policy-1', 'provider_revision': 'provider-1'}
URL = '/api/v1/execution-sessions'


@pytest.mark.integration
def test_native_configuration_is_durable_not_execution_permission(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
) -> None:
    """Persist native configuration without implying qualification or entry permission.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
    """
    app, client, headers, other = desk
    assert client.post(URL + '/native', json=CONFIG).status_code == 403
    response = client.post(URL + '/native', json=CONFIG, headers=headers)
    assert response.status_code == 201, response.json
    row = response.json['data']
    assert row['binding']['account'] == 'dhan:inert-account'
    assert row['binding']['actor'] == 'bounded:bounded-one'
    assert row['configured'] is True
    assert row['qualified'] is False and row['authorised'] is False
    assert row['commands'] == []
    listed = client.get(URL, headers=headers).json['data']
    assert listed[0]['state'] == 'configured'
    assert listed[0]['autonomy']['binding'] == row['binding']
    assert client.get(URL + '/bounded-one/autonomy', headers=other).status_code == 409
    assert client.post(URL + '/bounded-one/autonomy/qualify', headers=headers, json={}).status_code == 409
    assert client.get(URL + '/bounded-one/autonomy', headers=headers).json['data']['qualified'] is False


class InertAttestationProvider:
    """External independent qualification evidence, never a real-broker claim.

    Production has no provider installed. These synthetic attestations describe
    only this fixture's inert transport; no test evidence is shipped as a pin.
    """
    def __init__(self) -> None:
        self.evidence = None

    def current_evidence(self) -> "NativeQualificationEvidence | None":
        """Expose only the synthetic qualification evidence currently held by this fixture.

        Returns:
            The configured qualification evidence, or None before any is supplied.
        """
        return self.evidence


def armed(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    *,
    actions: "list[str] | None" = None,
    lifetime: "float" = 60,
    issue_grant: "bool" = True,
) -> "dict[str, Any]":
    """Configure and qualify the synthetic run, optionally submitting its explicit grant.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        actions: Requested grant actions, or None for the fixture's placement default.
        lifetime: Grant lifetime in seconds relative to the current fixture clock.
        issue_grant: Whether to submit the grant rather than return its request body.

    Returns:
        Grant request when issue_grant is false; otherwise the scoped placement command body.

    Raises:
        AssertionError: The real configuration, qualification or grant route rejects the control.
    """
    from flinttrade_core.native_autonomy import NativeQualificationEvidence
    app, client, headers, other = desk
    created = client.post(URL + '/native', json=CONFIG, headers=headers)
    assert created.status_code == 201, created.json
    owner = app.config['EXECUTION_SESSIONS'].autonomy
    provider = InertAttestationProvider()
    app.config['NATIVE_AUTONOMY_BINDINGS'] = {'bounded-one': dict(CONFIG)}
    app.config['NATIVE_AUTONOMY_QUALIFIER'] = provider
    provider.evidence = NativeQualificationEvidence(
        created.json['data']['revision'], owner.qualification_binding('bounded-one'),
        'inert-external-proof', 'synthetic-inert-external-adapter-only', time.time() + 300)
    assert client.post(URL + '/bounded-one/autonomy/qualify', json={}, headers=headers).status_code == 200
    grant = {'grant_id': 'grant-one', 'expires_at': time.time() + lifetime,
             'instruments': [{'symbol': 'INFY', 'exchange': 'NSE'}], 'actions': actions or ['place'],
             'max_order_quantity': 2, 'max_total_quantity': 2, 'max_total_notional': 220,
             'max_loss': 220, 'max_commands': 2}
    if not issue_grant:
        return grant
    result = client.post(URL + '/bounded-one/autonomy/grant', json=grant, headers=headers)
    assert result.status_code == 200, result.json
    command = {'command_id': 'command-one', 'grant_id': 'grant-one',
               'expected_revision': created.json['data']['revision'],
               'order': {'symbol': 'INFY', 'exchange': 'NSE', 'action': 'BUY', 'product': 'CNC',
                         'order_type': 'LIMIT', 'quantity': 2, 'price': 100}}
    return command


@pytest.mark.integration
def test_admitted_command_is_ack_only_replay_safe_and_settled_by_broker_evidence(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
) -> None:
    """Keep acknowledgement replay-safe and require broker evidence for settlement.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
    """
    app, client, headers, other = desk
    command = armed(desk)
    result = client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers)
    assert result.status_code == 200, result.json
    receipt = result.json['data']
    assert receipt['state'] == 'acknowledged' and receipt['broker_order_id'] == 'inert-order-1'
    assert receipt['events'] == ['pending_admission', 'admitted', 'dispatched', 'acknowledged']
    source = app.config['NATIVE_ADAPTERS']['dhan']
    assert len(source.writes) == 1
    again = client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers)
    assert again.json['data'] == receipt and len(source.writes) == 1
    changed = {**command, 'order': {**command['order'], 'quantity': 1}}
    assert client.post(URL + '/bounded-one/autonomy/commands', json=changed, headers=headers).status_code == 409
    source.orders = [{'order_id': 'inert-order-1', 'symbol': 'INFY', 'exchange': 'NSE',
                      'product': 'CNC', 'action': 'BUY', 'quantity': '2', 'filled_qty': '0',
                      'status': 'REJECTED', 'price': '100', 'pricetype': 'LIMIT'}]
    reconciled = client.post(URL + '/bounded-one/autonomy/reconcile', json={}, headers=headers)
    assert reconciled.status_code == 200, reconciled.json
    assert reconciled.json['data']['commands'][0]['state'] == 'settled'
    assert reconciled.json['data']['commands'][0]['cause'] == 'broker_rejected_zero_fill'
    assert reconciled.json['data']['obligations'] == []
    assert len(source.writes) == 1


@pytest.mark.integration
@pytest.mark.parametrize('mutation', ['absent', 'expired', 'revoked', 'wrong-principal', 'account', 'revision',
                                     'quantity', 'price', 'symbol', 'action', 'provider', 'policy', 'source',
                                     'runtime', 'kill', 'external', 'client-mode', 'jwt-revoked'])
def test_scope_and_negative_guards_send_no_broker_write(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    mutation: "str",
) -> None:
    """Refuse changed scope, intent or authority before any broker write.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        mutation: Authority, intent or runtime mutation that must prevent a broker write.
    """
    from dataclasses import replace
    app, client, headers, other = desk
    command = armed(desk)
    if mutation == 'absent':
        command['grant_id'] = 'missing'
    elif mutation == 'expired':
        provider = app.config['NATIVE_AUTONOMY_QUALIFIER']
        provider.evidence = replace(provider.evidence, expires_at=time.time() - 1)
    elif mutation == 'revoked':
        assert client.post(URL + '/bounded-one/autonomy/revoke', json={'grant_id': 'grant-one'},
            headers=headers).status_code == 200
    elif mutation == 'wrong-principal':
        headers = other
    elif mutation == 'account':
        command['order']['account_id'] = 'wrong-account'
    elif mutation == 'revision':
        command['expected_revision'] = 'different'
    elif mutation == 'quantity':
        command['order']['quantity'] = 3
    elif mutation == 'price':
        command['order']['price'] = 111
    elif mutation == 'symbol':
        command['order']['symbol'] = 'OTHER'
    elif mutation == 'action':
        command['order']['action'] = 'SELL'
    elif mutation in {'provider', 'policy'}:
        app.config['NATIVE_AUTONOMY_BINDINGS']['bounded-one'][mutation + '_revision'] = 'changed'
    elif mutation == 'source':
        app.config['NATIVE_ADAPTERS'] = {'dhan': InertBrokerIO()}
    elif mutation == 'runtime':
        app.config['RUNTIME_ACCEPTING_REQUESTS'] = False
    elif mutation == 'kill':
        app.config['SAFETY'].l5_kill.activate('synthetic-test')
    elif mutation == 'external':
        app.config['NATIVE_ADAPTERS']['dhan'].position_rows = [{'symbol': 'OTHER', 'exchange': 'NSE',
            'product': 'CNC', 'quantity': '1'}]
    elif mutation == 'client-mode':
        headers = {**headers, 'X-FlintTrade-Mode': 'practice'}
    elif mutation == 'jwt-revoked':
        from flinttrade_core.auth_routes import decode_token, _revoke_jti
        with app.app_context():
            claims = decode_token(headers['Authorization'][7:])
            _revoke_jti(claims['jti'], claims['exp'])
    result = client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers)
    assert result.status_code in {403, 409}, result.json
    assert app.config['NATIVE_ADAPTERS']['dhan'].writes == []


@pytest.mark.integration
def test_timeout_and_restart_retain_obligations_without_replay(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
) -> None:
    """Retain uncertain obligations across restart without dispatching a replacement.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
    """
    from flinttrade_core.execution_sessions import ExecutionSessions
    app, client, headers, other = desk
    command = armed(desk)
    source = app.config['NATIVE_ADAPTERS']['dhan']
    source.timeout = True
    first = client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers)
    assert first.status_code == 200, first.json
    assert first.json['data']['state'] == 'uncertain'
    assert len(source.writes) == 1
    sessions = app.config['EXECUTION_SESSIONS']
    path = sessions.path
    sessions.close()
    app.config['EXECUTION_SESSIONS'] = ExecutionSessions(app, path)
    status = client.get(URL + '/bounded-one/autonomy', headers=headers).json['data']
    assert not status['authorised'] and not status['qualified']
    assert status['commands'][0]['state'] == 'reconciling'
    assert status['obligations'] == ['command-one']
    again = client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers)
    assert again.status_code == 200 and again.json['data']['state'] == 'reconciling'
    reconciled = client.post(URL + '/bounded-one/autonomy/reconcile', json={}, headers=headers)
    assert reconciled.status_code == 200, reconciled.json
    assert reconciled.json['data']['obligations'] == ['command-one']
    assert len(source.writes) == 1


@pytest.mark.integration
@pytest.mark.parametrize('filled,state', [(1, 'partial'), (2, 'filled')])
def test_fill_is_not_settled_exposure_and_revoke_keeps_inspection(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    filled: "int",
    state: "str",
) -> None:
    """Retain observed fill obligations and inspection after grant revocation.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        filled: Observed whole filled quantity for the synthetic order.
        state: Expected lifecycle state associated with the supplied fill observation.
    """
    app, client, headers, other = desk
    command = armed(desk)
    assert client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers).json['data'][
        'state'] == 'acknowledged'
    source = app.config['NATIVE_ADAPTERS']['dhan']
    source.orders = [{'order_id': 'inert-order-1', 'symbol': 'INFY', 'exchange': 'NSE', 'product': 'CNC',
                      'action': 'BUY', 'quantity': '2', 'filled_qty': str(filled),
                          'status': 'PARTIAL' if filled == 1 else 'FILLED',
                      'price': '100', 'pricetype': 'LIMIT'}]
    response = client.post(URL + '/bounded-one/autonomy/reconcile', json={}, headers=headers)
    assert response.status_code == 200, response.json
    assert response.json['data']['commands'][0]['state'] == state
    assert response.json['data']['obligations'] == ['command-one']
    revoked = client.post(URL + '/bounded-one/autonomy/revoke', json={'grant_id': 'grant-one'}, headers=headers)
    assert revoked.status_code == 200 and revoked.json['data']['obligations'] == ['command-one']
    assert len(source.writes) == 1


@pytest.mark.integration
def test_cancel_is_owned_scoped_request_not_a_flat_receipt(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
) -> None:
    """Cancel only the owned placement and require zero-fill evidence for settlement.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
    """
    app, client, headers, other = desk
    command = armed(desk, actions=['place', 'cancel'])
    first = client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers)
    assert first.json['data']['state'] == 'acknowledged'
    source = app.config['NATIVE_ADAPTERS']['dhan']
    source.orders = [{'order_id': 'inert-order-1', 'symbol': 'INFY', 'exchange': 'NSE', 'product': 'CNC',
                      'action': 'BUY', 'quantity': '2', 'filled_qty': '0', 'status': 'OPEN',
                      'price': '100', 'pricetype': 'LIMIT'}]
    cancel = {key: value for key, value in command.items() if key != 'order'}
    cancel.update(command_id='cancel-one', cancel={'placement_command_id': 'command-one'})
    denied = {**cancel, 'cancel': {'placement_command_id': 'someone-elses-entry'}}
    assert client.post(URL + '/bounded-one/autonomy/commands', json=denied, headers=headers).status_code == 409
    response = client.post(URL + '/bounded-one/autonomy/commands', json=cancel, headers=headers)
    assert response.status_code == 200, response.json
    assert response.json['data']['state'] == 'cancel_requested'
    assert len(source.writes) == 2 and source.writes[-1] == {'cancel_order_id': 'inert-order-1'}
    again = client.post(URL + '/bounded-one/autonomy/commands', json=cancel, headers=headers)
    assert again.json == response.json and len(source.writes) == 2
    status = client.get(URL + '/bounded-one/autonomy', headers=headers).json['data']
    assert set(status['obligations']) == {'command-one', 'cancel-one'}
    pending = client.post(URL + '/bounded-one/autonomy/reconcile', json={}, headers=headers)
    assert pending.status_code == 200, pending.json
    receipts = {c['command_id']: c for c in pending.json['data']['commands']}
    assert receipts['cancel-one']['state'] == 'cancel_requested'
    assert receipts['command-one']['state'] == 'working'
    source.orders[0]['status'] = 'CANCELLED'
    settled = client.post(URL + '/bounded-one/autonomy/reconcile', json={}, headers=headers)
    assert settled.status_code == 200, settled.json
    assert settled.json['data']['obligations'] == []
    assert all(c['state'] == 'settled' for c in settled.json['data']['commands'])


@pytest.mark.integration
@pytest.mark.parametrize('change', ['revoke', 'external', 'kill'])
def test_change_during_provider_io_is_rechecked_before_dispatch(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    change: "str",
) -> None:
    """Recheck concurrent authority changes after provider I/O and before dispatch.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        change: Named mutation applied to the otherwise valid control.
    """
    app, client, headers, other = desk
    command = armed(desk)
    source = app.config['NATIVE_ADAPTERS']['dhan']
    def alter():
        if change == 'revoke':
            response = client.post(URL + '/bounded-one/autonomy/revoke', json={'grant_id': 'grant-one'},
                headers=headers)
            assert response.status_code == 200
        elif change == 'external':
            source.position_rows = [{'symbol': 'OTHER', 'exchange': 'NSE', 'product': 'CNC', 'quantity': '1'}]
        else:
            app.config['SAFETY'].l5_kill.activate('inert-concurrent-kill')
    source.on_quotes = alter
    response = client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers)
    assert response.status_code == 200, response.json
    assert response.json['data']['state'] == 'refused'
    assert 'dispatched' not in response.json['data']['events']
    assert source.writes == []


@pytest.mark.integration
def test_grant_expiry_and_retained_agent_port_fail_closed(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
) -> None:
    """Refuse an expired grant through both the retained producer port and HTTP.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
    """
    app, client, headers, other = desk
    command = armed(desk, lifetime=1)
    port = app.config['EXECUTION_SESSIONS'].autonomy.port(headers['Authorization'][7:], 'bounded-one')
    assert not hasattr(port, 'grant') and not hasattr(port, 'revoke')
    time.sleep(1.05)
    with pytest.raises(ValueError):
        port.submit(command)
    result = client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers)
    assert result.status_code == 409
    assert client.get(URL + '/bounded-one/autonomy', headers=headers).json['data']['authorised'] is False
    assert app.config['NATIVE_ADAPTERS']['dhan'].writes == []


@pytest.mark.integration
@pytest.mark.parametrize('change', ['partial', 'wrong-id', 'external', 'revoked', 'ungranted', 'changed-quantity'])
def test_cancel_never_removes_unowned_or_changed_protection(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    change: "str",
) -> None:
    """Reject cancellation when ownership, fill, protection or grant evidence has changed.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        change: Named mutation applied to the otherwise valid control.
    """
    app, client, headers, other = desk
    command = armed(desk, actions=['place'] if change == 'ungranted' else ['place', 'cancel'])
    assert client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers).status_code == 200
    source = app.config['NATIVE_ADAPTERS']['dhan']
    source.orders = [{'order_id': 'inert-order-1', 'symbol': 'INFY', 'exchange': 'NSE', 'product': 'CNC',
                      'action': 'BUY', 'quantity': '2', 'filled_qty': '0', 'status': 'OPEN', 'price': '100',
                          'pricetype': 'LIMIT'}]
    if change == 'partial':
        source.orders[0].update(filled_qty='1', status='PARTIAL')
    elif change == 'wrong-id':
        source.orders[0]['order_id'] = 'unowned'
    elif change == 'external':
        source.position_rows = [{'symbol': 'INFY', 'exchange': 'NSE', 'product': 'CNC', 'quantity': '-1'}]
    elif change == 'revoked':
        assert client.post(URL + '/bounded-one/autonomy/revoke', json={'grant_id': 'grant-one'},
            headers=headers).status_code == 200
    elif change == 'changed-quantity':
        source.orders[0]['quantity'] = '3'
    cancel = {key: value for key, value in command.items() if key != 'order'}
    cancel.update(command_id='cancel-one', cancel={'placement_command_id': 'command-one'})
    response = client.post(URL + '/bounded-one/autonomy/commands', json=cancel, headers=headers)
    assert response.status_code == 409, response.json
    assert len(source.writes) == 1


@pytest.mark.integration
def test_observed_binding_drift_cannot_resurrect_an_old_qualification(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
) -> None:
    """Keep a retired qualification invalid after its old binding values return.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
    """
    app, client, headers, other = desk
    armed(desk)
    binding = app.config['NATIVE_AUTONOMY_BINDINGS']['bounded-one']
    binding['provider_revision'] = 'retired-provider'
    changed = client.get(URL + '/bounded-one/autonomy', headers=headers)
    assert changed.json['data']['qualified'] is False
    binding['provider_revision'] = 'provider-1'
    restored = client.get(URL + '/bounded-one/autonomy', headers=headers)
    assert restored.json['data']['qualified'] is False
    assert client.post(URL + '/bounded-one/autonomy/qualify', json={}, headers=headers).status_code == 409


@pytest.mark.integration
def test_new_run_cannot_escape_another_runs_uncertain_account_obligation(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
) -> None:
    """Keep uncertain account obligations effective across independently configured runs.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
    """
    from flinttrade_core.native_autonomy import NativeQualificationEvidence
    app, client, headers, other = desk
    command = armed(desk)
    source = app.config['NATIVE_ADAPTERS']['dhan']
    source.timeout = True
    first = client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers)
    assert first.json['data']['state'] == 'uncertain'
    config = {**CONFIG, 'run_id': 'second-run'}
    created = client.post(URL + '/native', json=config, headers=headers)
    assert created.status_code == 201
    owner = app.config['EXECUTION_SESSIONS'].autonomy
    app.config['NATIVE_AUTONOMY_BINDINGS']['second-run'] = config
    app.config['NATIVE_AUTONOMY_QUALIFIER'].evidence = NativeQualificationEvidence(
        created.json['data']['revision'], owner.qualification_binding('second-run'), 'second-inert-proof',
        'synthetic-inert-external-adapter-only', time.time() + 300)
    assert client.post(URL + '/second-run/autonomy/qualify', json={}, headers=headers).status_code == 200
    grant = {'grant_id': 'grant-two', 'expires_at': time.time() + 60,
             'instruments': [{'symbol': 'INFY', 'exchange': 'NSE'}], 'actions': ['place'],
             'max_order_quantity': 2, 'max_total_quantity': 2, 'max_total_notional': 220,
             'max_loss': 220, 'max_commands': 1}
    assert client.post(URL + '/second-run/autonomy/grant', json=grant, headers=headers).status_code == 200
    command.update(expected_revision=created.json['data']['revision'], grant_id='grant-two')
    second = client.post(URL + '/second-run/autonomy/commands', json=command, headers=headers)
    assert second.status_code == 409, second.json
    assert len(source.writes) == 1


@pytest.mark.integration
def test_existing_registry_stop_retires_native_entry_permission(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
) -> None:
    """Retire native entry authority through the existing registry Stop operation.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
    """
    app, client, headers, other = desk
    command = armed(desk)
    before = client.get(URL + '/bounded-one', headers=headers).json['data']
    stopped = client.post(URL + '/bounded-one/stop', headers=headers, json={
        'account': before['account'], 'environment': 'live', 'expected_generation': before['generation']})
    assert stopped.status_code == 200, stopped.json
    assert stopped.json['data']['autonomy']['authorised'] is False
    assert client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers).status_code == 409
    assert app.config['NATIVE_ADAPTERS']['dhan'].writes == []


@pytest.mark.integration
def test_shutdown_with_native_obligation_is_not_a_flat_receipt(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
) -> None:
    """Keep shutdown incomplete while acknowledged native obligations remain.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
    """
    app, client, headers, other = desk
    command = armed(desk)
    assert client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers).json['data'][
        'state'] == 'acknowledged'
    assert app.config['EXECUTION_SESSIONS'].shutdown(timeout=0) is False
    status = client.get(URL + '/bounded-one/autonomy', headers=headers).json['data']
    assert status['authorised'] is False and status['obligations'] == ['command-one']
    assert len(app.config['NATIVE_ADAPTERS']['dhan'].writes) == 1


@pytest.mark.integration
@pytest.mark.parametrize('change', ['omitted', 'zero', 'negative', 'boolean', 'nonfinite', 'expired',
    'unlimited', 'empty-instruments', 'wrong-action'])
def test_grants_never_default_to_unlimited(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    change: "str",
) -> None:
    """Reject omitted, invalid or unbounded grant limits without issuing authority.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        change: Named mutation applied to the otherwise valid control.
    """
    app, client, headers, other = desk
    grant = armed(desk, issue_grant=False)
    if change == 'omitted':
        del grant['max_total_notional']
    elif change in {'zero', 'negative', 'boolean', 'nonfinite'}:
        grant['max_order_quantity'] = {'zero': 0, 'negative': -1, 'boolean': True, 'nonfinite': float('inf')}[change]
    elif change == 'expired':
        grant['expires_at'] = time.time() - 1
    elif change == 'unlimited':
        grant['max_commands'] = None
    elif change == 'empty-instruments':
        grant['instruments'] = []
    else:
        grant['actions'] = ['close-all']
    result = client.post(URL + '/bounded-one/autonomy/grant', json=grant, headers=headers)
    assert result.status_code == 409, result.json
    row = client.get(URL + '/bounded-one/autonomy', headers=headers).json['data']
    assert row['grant'] is None and not row['authorised']
    assert app.config['NATIVE_ADAPTERS']['dhan'].writes == []


@pytest.mark.integration
def test_scoped_producer_port_uses_same_authority_without_operator_credentials(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
) -> None:
    """Dispatch through the scoped producer port without copying operator credentials.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
    """
    app, client, headers, other = desk
    command = armed(desk)
    port = app.config['EXECUTION_SESSIONS'].autonomy.port(headers['Authorization'][7:], 'bounded-one')
    with app.test_request_context(headers={'X-FlintTrade-Mode': 'practice'}):
        result = port.submit(command)
    assert result['state'] == 'acknowledged'
    assert result['body']['account_id'] == 'inert-account'
    assert len(app.config['NATIVE_ADAPTERS']['dhan'].writes) == 1


@pytest.mark.integration
def test_read_only_operator_can_inspect_during_degradation_without_auth_material(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
) -> None:
    """Allow degraded read-only inspection without exposing session or grant secrets.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
    """
    app, client, headers, other = desk
    armed(desk)
    with app.app_context():
        read_token = _create_token('synthetic-operator', mode='practice', scopes=('admin.accounts.read',
            'admin.services.read'))
    app.config['RUNTIME_ACCEPTING_REQUESTS'] = False
    response = client.get(URL + '/bounded-one/autonomy', headers={'Authorization': 'Bearer ' + read_token})
    assert response.status_code == 200, response.json
    row = response.json['data']
    assert row['authorised'] is False
    assert 'jti' not in row['grant'] and 'session_binding' not in row['grant']
    assert client.post(URL + '/bounded-one/autonomy/qualify', json={'qualified': True},
        headers=headers).status_code == 409


@pytest.mark.integration
def test_grant_does_not_bypass_canonical_laya_admission(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
) -> None:
    """Preserve canonical Laya refusal and command replay despite a valid grant.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
    """
    from flinttrade_engine.laya import process_laya, DecisionStatus
    app, client, headers, other = desk
    command = armed(desk)
    process_laya().set_status(DecisionStatus.DOWN)
    result = client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers)
    assert result.status_code == 200, result.json
    assert result.json['data']['state'] == 'refused'
    assert 'admitted' not in result.json['data']['events']
    assert 'dispatched' not in result.json['data']['events']
    assert app.config['NATIVE_ADAPTERS']['dhan'].writes == []
    process_laya().set_status(DecisionStatus.READY)
    replay = client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers)
    assert replay.json == result.json
    status = client.get(URL + '/bounded-one/autonomy', headers=headers).json['data']
    assert status['obligations'] == []
    # Refusal retires the obligation, not the explicit conservative budget.
    replacement = {**command, 'command_id': 'replacement'}
    assert client.post(URL + '/bounded-one/autonomy/commands', json=replacement, headers=headers).status_code == 409
    assert app.config['ORDER_LIFECYCLE_LEDGER'].list_dispatch_attempts() == []
    assert app.config['NATIVE_ADAPTERS']['dhan'].writes == []


@pytest.mark.integration
@pytest.mark.parametrize('changes', [{'filled_qty': 'broken'}, {'filled_qty': '3'}, {'status': 'UNKNOWN'}, {
    'qty': '3'}, {'orderid': 'other'}])
def test_contradictory_broker_receipt_cannot_settle_obligation(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    changes: "dict[str, str]",
) -> None:
    """Keep contradictory broker aliases unresolved instead of settling the command.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        changes: Conflicting native order aliases overlaid on the otherwise coherent row.
    """
    app, client, headers, other = desk
    command = armed(desk)
    assert client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers).json['data'][
        'state'] == 'acknowledged'
    source = app.config['NATIVE_ADAPTERS']['dhan']
    source.orders = [{'order_id': 'inert-order-1', 'symbol': 'INFY', 'exchange': 'NSE', 'product': 'CNC',
                      'action': 'BUY', 'quantity': '2', 'filled_qty': '0', 'status': 'CANCELLED',
                          'price': '100', 'pricetype': 'LIMIT', **changes}]
    result = client.post(URL + '/bounded-one/autonomy/reconcile', json={}, headers=headers)
    assert result.status_code == 200, result.json
    assert result.json['data']['commands'][0]['state'] == 'reconciling'
    assert result.json['data']['obligations'] == ['command-one']
    assert len(source.writes) == 1


@pytest.mark.integration
def test_grant_is_operator_bound_explicit_and_revocable(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
) -> None:
    """Bind an explicit grant to its operator and prevent reuse after revocation.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
    """
    from flinttrade_core import native_autonomy
    assert hasattr(native_autonomy, 'NativeQualificationEvidence'), 'server qualification evidence seam missing'
    from flinttrade_core.native_autonomy import NativeQualificationEvidence
    app, client, headers, other = desk
    created = client.post(URL + '/native', json=CONFIG, headers=headers)
    assert created.status_code == 201
    owner = app.config['EXECUTION_SESSIONS'].autonomy
    provider = InertAttestationProvider()
    # Trusted backend configuration, not a body or role header.
    app.config['NATIVE_AUTONOMY_BINDINGS'] = {'bounded-one': dict(CONFIG)}
    app.config['NATIVE_AUTONOMY_QUALIFIER'] = provider
    provider.evidence = NativeQualificationEvidence(
        binding_revision=created.json['data']['revision'],
        runtime_fingerprint=owner.qualification_binding('bounded-one'),
        evidence_id='inert-external-proof', provenance='synthetic-inert-external-adapter-only',
        expires_at=time.time() + 300,
    )
    qualified = client.post(URL + '/bounded-one/autonomy/qualify', json={}, headers=headers)
    assert qualified.status_code == 200, qualified.json
    assert qualified.json['data']['qualified'] is True
    grant = {'grant_id': 'grant-one', 'expires_at': time.time() + 60,
             'instruments': [{'symbol': 'INFY', 'exchange': 'NSE'}], 'actions': ['place'],
             'max_order_quantity': 2, 'max_total_quantity': 2, 'max_total_notional': 220,
             'max_loss': 220, 'max_commands': 1}
    assert client.post(URL + '/bounded-one/autonomy/grant', json=grant, headers=other).status_code == 409
    result = client.post(URL + '/bounded-one/autonomy/grant', json=grant, headers=headers)
    assert result.status_code == 200, result.json
    row = result.json['data']
    assert row['authorised'] is True
    assert row['grant']['operator'] == row['operator']
    assert row['grant']['binding_revision'] == row['revision']
    revoke = client.post(URL + '/bounded-one/autonomy/revoke', json={'grant_id': 'grant-one'}, headers=headers)
    assert revoke.status_code == 200, revoke.json
    assert revoke.json['data']['authorised'] is False
    assert client.post(URL + '/bounded-one/autonomy/grant', json=grant, headers=headers).status_code == 409


@pytest.mark.integration
def test_unavailable_books_cannot_authorise_an_empty_account(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    """Distinguish unavailable books from complete empty account evidence.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        monkeypatch: Scoped replacements restored after this test.
    """
    app, client, headers, _other = desk
    command = armed(desk)
    source = app.config['NATIVE_ADAPTERS']['dhan']

    async def unavailable(_session):
        return None

    for name in ('positions', 'holdings', 'order_book', 'trade_book'):
        monkeypatch.setattr(source, name, unavailable)
    result = client.post(URL + '/bounded-one/autonomy/commands', json=command, headers=headers)
    assert result.status_code == 409, result.json
    assert source.writes == []
    assert client.get(URL + '/bounded-one/autonomy', headers=headers).json['data']['commands'] == []
