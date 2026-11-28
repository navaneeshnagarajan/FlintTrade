"""Late canonical completions must not replace public broker evidence."""
from __future__ import annotations

import sys
import threading
from contextlib import contextmanager

import pytest

from packages.core.core.tests.test_native_autonomy import URL, armed, desk as desk
from packages.core.core.tests.test_native_autonomy_recovery import order_row, restart


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterator
    from flask import Flask
    from flask.testing import FlaskClient
    from types import FrameType
    from typing import Any
    from werkzeug.test import TestResponse


def post(client: "FlaskClient", headers: "dict[str, str]", suffix: "str", body: "dict[str, Any]") -> "TestResponse":
    """Send a bounded-run command or lifecycle body through its existing HTTP suffix.

    Args:
        client: Test client for the existing bounded-run HTTP routes.
        headers: Authentication headers belonging to the synthetic operator.
        suffix: Bounded-run route suffix appended to the existing autonomy prefix.
        body: JSON request body sent unchanged to the bounded-run route.

    Returns:
        Actual route response, without translating its disposition.
    """
    return client.post(URL + '/bounded-one/autonomy/' + suffix, json=body, headers=headers)


def cancel_request(command: "dict[str, Any]") -> "dict[str, Any]":
    """Derive the fixture cancellation body while retaining the original grant and revision.

    Args:
        command: Original bounded command body whose scope and revision are retained.

    Returns:
        Cancellation request referring to the fixture's original placement command.
    """
    return {k: v for k, v in command.items() if k != 'order'} | {
        'command_id': 'cancel-one', 'cancel': {'placement_command_id': 'command-one'}}


def status(client: "FlaskClient", headers: "dict[str, str]") -> "dict[str, Any]":
    """Read the synthetic run's retained status through the public HTTP route.

    Args:
        client: Test client for the existing bounded-run HTTP routes.
        headers: Authentication headers belonging to the synthetic operator.

    Returns:
        The route's data dictionary, including retained commands and obligations.
    """
    return client.get(URL + '/bounded-one/autonomy', headers=headers).json['data']


@contextmanager
def paused_request(
    app: "Flask",
    headers: "dict[str, str]",
    command: "dict[str, Any]",
    predicate: "Callable[[FrameType, str], bool]",
) -> "Iterator[list[TestResponse]]":
    """Observe real execution; hold only its scheduling, restore trace on exit.

    Args:
        app: App retaining the execution-session and account lifecycle owners.
        headers: Authentication headers belonging to the synthetic operator.
        command: Original bounded command body whose scope and revision are retained.
        predicate: Trace predicate selecting the real request scheduling boundary to hold.

    Yields:
        Mutable response list populated by the held request as it completes.

    Raises:
        AssertionError: The boundary is not reached, the worker fails to drain, or its response is not successful.
    """
    entered, release = threading.Event(), threading.Event()
    responses, errors = [], []

    def observer(frame, event, arg):
        if not entered.is_set() and predicate(frame, event):
            entered.set()
            assert release.wait(7), 'request scheduling barrier was not released'
        return observer

    def submit():
        previous = sys.gettrace()
        sys.settrace(observer)
        try:
            responses.append(post(app.test_client(), headers, 'commands', command))
        except BaseException as exc:
            errors.append(exc)
        finally:
            sys.settrace(previous)

    worker = threading.Thread(target=submit, daemon=True)
    worker.start()
    try:
        assert entered.wait(3), 'actual request did not reach scheduling barrier'
        yield responses
    finally:
        release.set()
        worker.join(5)
        assert not worker.is_alive(), 'request worker did not drain'
        assert not errors, errors
    assert len(responses) == 1 and responses[0].status_code == 200, responses


def canonical_return(frame: "FrameType", event: "str") -> "bool":
    """Identify return from the real canonical native dispatch function.

    Args:
        frame: Executing Python frame observed by the scheduling trace.
        event: Trace event name supplied by Python.

    Returns:
        True only for that module-qualified return event.
    """
    return (event == 'return' and frame.f_code.co_name == 'dispatch_native_command'
            and frame.f_globals.get('__name__') == 'flinttrade_core.order_routes')


@pytest.mark.integration
@pytest.mark.parametrize('book_state,filled,expected', [
    ('OPEN', 0, 'working'), ('PARTIAL', 1, 'partial'), ('FILLED', 2, 'filled'),
    ('CANCELLED', 0, 'settled'), ('UNKNOWN', 0, 'reconciling'),
])
def test_late_placement_ack_preserves_reconciled_state_cause_and_history(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    book_state: "str",
    filled: "int",
    expected: "str",
) -> None:
    """Prevent late placement acknowledgement from regressing reconciled state or history.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        book_state: Native order-book status supplied while acknowledgement adoption is held.
        filled: Observed whole filled quantity for the synthetic order.
        expected: Expected result value for this parameterised control.
    """
    app, client, headers, _ = desk
    command = armed(desk, actions=['place', 'cancel'])
    source = app.config['NATIVE_ADAPTERS']['dhan']
    with paused_request(app, headers, command, canonical_return) as responses:
        attempts = app.config['ORDER_LIFECYCLE_LEDGER'].list_dispatch_attempts()
        assert len(attempts) == 1 and attempts[0]['broker_order_id'] == 'inert-order-1'
        source.orders = [order_row(state=book_state, filled=filled)]
        observed = post(client, headers, 'reconcile', {}).json['data']['commands'][0]
        assert observed['state'] == expected
    after = status(client, headers)
    receipt = after['commands'][0]
    assert receipt['state'] == expected
    assert receipt['cause'] == observed['cause']
    assert receipt['events'] == observed['events']
    assert receipt['broker_order_id'] == 'inert-order-1'
    assert receipt.get('filled_quantity', 0) == filled
    assert responses[0].json['data'] == receipt
    assert post(client, headers, 'commands', command).json['data'] == receipt
    assert len(source.writes) == 1
    if filled:
        source.orders = [order_row(state='OPEN')]
        refused = post(client, headers, 'commands', cancel_request(command))
        assert refused.status_code == 409
        assert len(source.writes) == 1
        assert after['obligations'] == ['command-one']
        assert after['protection'] == 'operator_handback_required'


@pytest.mark.integration
@pytest.mark.parametrize('filled', [0, 1])
def test_late_cancel_ack_preserves_settlement_or_exposure(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    monkeypatch: "pytest.MonkeyPatch",
    filled: "int",
) -> None:
    """Retain settlement or known exposure when cancellation acknowledgement arrives late.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        monkeypatch: Scoped replacements restored after this test.
        filled: Observed whole filled quantity for the synthetic order.
    """
    app, client, headers, _ = desk
    command = armed(desk, actions=['place', 'cancel'])
    source = app.config['NATIVE_ADAPTERS']['dhan']
    assert post(client, headers, 'commands', command).json['data']['state'] == 'acknowledged'
    source.orders = [order_row(state='OPEN')]
    original = source.cancel_order
    entered, release = threading.Event(), threading.Event()
    responses = []

    def held(order_id):
        result = original(order_id)
        entered.set()
        assert release.wait(7)
        return result

    monkeypatch.setattr(source, 'cancel_order', held)
    worker = threading.Thread(target=lambda: responses.append(
        post(app.test_client(), headers, 'commands', cancel_request(command))), daemon=True)
    worker.start()
    try:
        assert entered.wait(3)
        source.orders = [order_row(state='CANCELLED', filled=filled)]
        observed = post(client, headers, 'reconcile', {}).json['data']
        before = next(c for c in observed['commands'] if c['command_id'] == 'cancel-one')
        assert before['state'] == ('partial' if filled else 'settled')
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    after = status(client, headers)
    assert after['commands'] == observed['commands']
    assert after['obligations'] == observed['obligations']
    assert responses[0].json['data'] == before
    assert post(client, headers, 'commands', cancel_request(command)).json['data'] == before
    assert len(source.writes) == 2


@pytest.mark.integration
@pytest.mark.parametrize('evidence', ['partial', 'filled', 'conflicting', 'settled'])
def test_cancel_rechecks_durable_placement_at_actual_invocation(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    evidence: "str",
) -> None:
    """Recheck durable placement evidence at the actual cancellation invocation boundary.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        evidence: Retained placement evidence introduced before cancellation invocation.
    """
    app, client, headers, _ = desk
    command = armed(desk, actions=['place', 'cancel'])
    source = app.config['NATIVE_ADAPTERS']['dhan']
    assert post(client, headers, 'commands', command).json['data']['state'] == 'acknowledged'
    source.orders = [order_row(state='OPEN')]

    def before_invoke(frame, event):
        return (event == 'call' and frame.f_code.co_name == 'on_invoke'
                and frame.f_globals.get('__name__') == 'flinttrade_core.native_autonomy')

    cancel = cancel_request(command)
    with paused_request(app, headers, cancel, before_invoke) as responses:
        pending = next(c for c in status(client, headers)['commands'] if c['command_id'] == 'cancel-one')
        assert pending['state'] == 'admitted'
        assert len(source.writes) == 1
        fill = 1 if evidence == 'partial' else 2 if evidence == 'filled' else 0
        book_state = {'partial': 'PARTIAL', 'filled': 'FILLED', 'conflicting': 'UNKNOWN',
            'settled': 'CANCELLED'}[evidence]
        source.orders = [order_row(filled=fill, state=book_state)]
        observed = post(client, headers, 'reconcile', {}).json['data']
        placement = next(c for c in observed['commands'] if c['command_id'] == 'command-one')
        assert placement['state'] == ('reconciling' if evidence == 'conflicting' else evidence)
        # A newer zero-fill response must not revive the authority already minted.
        source.orders = [order_row(state='OPEN')]
    refused = responses[0].json['data']
    assert refused['state'] == 'refused'
    assert refused['cause'] == 'canonical_completed_pre_invocation_refusal'
    assert refused['events'] == ['pending_admission', 'admitted', 'refused']
    assert len(source.writes) == 1
    assert post(client, headers, 'commands', cancel).json['data'] == refused
    after = status(client, headers)
    assert next(c for c in after['commands'] if c['command_id'] == 'command-one') == placement
    assert post(client, headers, 'commands', {**cancel, 'command_id': 'cancel-two'}).status_code == 409
    assert len(source.writes) == 1


@pytest.mark.integration
@pytest.mark.parametrize('outcome', ['different-identity', 'unknown', 'multiple-ids'])
@pytest.mark.parametrize('filled', [0, 1])
def test_contradictory_completion_retains_identity_and_obligation_after_restart(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    monkeypatch: "pytest.MonkeyPatch",
    outcome: "str",
    filled: "int",
) -> None:
    """An early public lifecycle ACK can disagree with the real late transport.

    Record the early observation through the lifecycle owner's public interface,
    never by changing native command state or replacing gate/router execution.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        monkeypatch: Scoped replacements restored after this test.
        outcome: Late completion shape that conflicts with the already observed command.
        filled: Observed whole filled quantity for the synthetic order.
    """
    app, client, headers, _ = desk
    command = armed(desk, actions=['place', 'cancel'])
    source = app.config['NATIVE_ADAPTERS']['dhan']
    ledger = app.config['ORDER_LIFECYCLE_LEDGER']
    entered, release = threading.Event(), threading.Event()
    original = source.place_order
    responses = []

    def held(**fields):
        result = original(**fields)
        entered.set()
        assert release.wait(7)
        if outcome == 'unknown':
            raise TimeoutError('inert response lost after possible acceptance')
        if outcome == 'multiple-ids':
            return {'status': 'success', 'data': [{'orderId': 'inert-order-1'}, {'orderId': 'inert-order-2'}]}
        return result

    monkeypatch.setattr(source, 'place_order', held)
    worker = threading.Thread(target=lambda: responses.append(
        post(app.test_client(), headers, 'commands', command)), daemon=True)
    worker.start()
    try:
        assert entered.wait(3)
        attempts = ledger.list_dispatch_attempts()
        assert len(attempts) == 1 and attempts[0]['dispatch_state'] == 'INVOKED'
        # Independent early completion evidence for the same actual attempt.
        ledger.acknowledge(attempts[0]['attempt_id'], 'inert-observed-order')
        assert ledger.list_dispatch_attempts()[0]['broker_order_id'] == 'inert-observed-order'
        source.orders = [{**order_row(state='CANCELLED', filled=filled), 'order_id': 'inert-observed-order'}]
        observed = post(client, headers, 'reconcile', {}).json['data']['commands'][0]
        assert observed['state'] == ('partial' if filled else 'settled')
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive()
    assert len(responses) == 1 and responses[0].status_code == 200
    current = responses[0].json['data']
    assert current['state'] in {'reconciling', 'uncertain'}
    assert current['broker_order_id'] == 'inert-observed-order'
    assert current['filled_quantity'] == filled
    assert current['events'][:len(observed['events'])] == observed['events']
    for reopen in (False, True):
        if reopen:
            restart(app)
        # The old single-order book cannot resolve a contradictory completion.
        after = post(client, headers, 'reconcile', {}).json['data']
        assert after['commands'][0]['state'] in {'reconciling', 'uncertain'}
        assert after['commands'][0]['broker_order_id'] == 'inert-observed-order'
        assert after['commands'][0]['filled_quantity'] == filled
        assert after['obligations'] == ['command-one']
        assert after['protection'] == 'operator_handback_required'
        assert not after['native_ready']
        assert post(client, headers, 'commands', command).json['data'] == after['commands'][0]
        source.orders = [{**order_row(state='OPEN'), 'order_id': 'inert-observed-order'}]
        assert post(client, headers, 'commands', cancel_request(command)).status_code == 409
        assert len(source.writes) == 1
    source.orders = [{**order_row(state='FILLED', filled=2), 'order_id': 'inert-observed-order'}]
    newer = post(client, headers, 'reconcile', {}).json['data']
    assert newer['commands'][0]['filled_quantity'] == 2
    assert newer['commands'][0]['state'] == 'reconciling'
    assert newer['obligations'] == ['command-one']
    assert app.config['EXECUTION_SESSIONS'].shutdown(timeout=0) is False


@pytest.mark.integration
@pytest.mark.parametrize('multiple', [False, True])
def test_real_typed_ack_preserves_single_id_but_never_settles_multiple_ids(
    desk: "tuple[Flask, FlaskClient, dict[str, str], dict[str, str]]",
    monkeypatch: "pytest.MonkeyPatch",
    multiple: "bool",
) -> None:
    """A real native adapter builds the receipt; no canonical outcome is faked.

    Args:
        desk: Synthetic bounded-run app, HTTP client, owner headers and foreign-operator headers.
        monkeypatch: Scoped replacements restored after this test.
        multiple: Whether the real typed acknowledgement contains multiple order identities.
    """
    import time
    from types import SimpleNamespace

    from flinttrade_core.native_autonomy import NativeQualificationEvidence
    from flinttrade_engine.safety import SafetyGate
    from flinttrade_gateway.brokers._base import Session
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter
    from flinttrade_gateway.router import BrokerRouter
    from packages.core.core.tests.test_native_autonomy import CONFIG, InertAttestationProvider

    app, client, headers, _ = desk
    source = app.config['NATIVE_ADAPTERS']['dhan']
    session = Session('inert-upstox-session', 4102444800.0, 'inert-account', 'upstox')

    def session_for(ctx, broker, account):
        assert (broker, account) == ('upstox', 'inert-account')
        if ctx is not None:
            assert ctx.actor_type == 'agent' and ctx.actor_id == 'bounded:bounded-one'
        return session

    ids = ['inert-order-1', 'inert-order-2'] if multiple else ['inert-order-1']
    entered, release = threading.Event(), threading.Event()

    def place(params):
        source.writes.append(dict(params))
        entered.set()
        assert release.wait(7)
        return {'status': 'success', 'data': {'order_ids': ids}}

    monkeypatch.setattr(source, 'place_order', place)
    adapter = UpstoxAdapter(client_factory=lambda _session: source,
                            instrument_resolver=lambda _symbol, _exchange: 'NSE_EQ|INE009A01021')
    ledger = app.config['ORDER_LIFECYCLE_LEDGER']
    router = BrokerRouter({'upstox': adapter}, session_for, consume_gate=SafetyGate().consume,
                          backend_lease_proof=app.config['BACKEND_LEASE_PROOF'], lifecycle_store=ledger)
    app.config.update(BROKER_ROUTER=router, NATIVE_ADAPTERS={'upstox': source},
                      REGISTRY=SimpleNamespace(get_session_for=lambda b, a: session_for(None, b, a)))
    try:
        config = {**CONFIG, 'broker': 'upstox'}
        created = client.post(URL + '/native', json=config, headers=headers)
        assert created.status_code == 201
        owner = app.config['EXECUTION_SESSIONS'].autonomy
        provider = InertAttestationProvider()
        app.config['NATIVE_AUTONOMY_BINDINGS'] = {'bounded-one': config}
        app.config['NATIVE_AUTONOMY_QUALIFIER'] = provider
        provider.evidence = NativeQualificationEvidence(
            created.json['data']['revision'], owner.qualification_binding('bounded-one'),
            'inert-upstox-proof', 'synthetic-inert-external-adapter-only', time.time() + 300)
        assert post(client, headers, 'qualify', {}).status_code == 200
        grant = {'grant_id': 'grant-one', 'expires_at': time.time() + 60,
                 'instruments': [{'symbol': 'INFY', 'exchange': 'NSE'}], 'actions': ['place'],
                 'max_order_quantity': 2, 'max_total_quantity': 2, 'max_total_notional': 220,
                 'max_loss': 220, 'max_commands': 2}
        assert post(client, headers, 'grant', grant).status_code == 200
        command = {'command_id': 'command-one', 'grant_id': 'grant-one',
                   'expected_revision': created.json['data']['revision'],
                   'order': {'symbol': 'INFY', 'exchange': 'NSE', 'action': 'BUY', 'product': 'CNC',
                             'order_type': 'LIMIT', 'quantity': 2, 'price': 100}}

        responses = []
        worker = threading.Thread(target=lambda: responses.append(
            post(app.test_client(), headers, 'commands', command)), daemon=True)
        worker.start()
        try:
            assert entered.wait(3), 'actual Upstox external call must reach the barrier'
            attempts = ledger.list_dispatch_attempts()
            assert len(attempts) == 1 and attempts[0]['dispatch_state'] == 'INVOKED'
            ledger.acknowledge(attempts[0]['attempt_id'], 'inert-order-1')
            source.orders = [order_row(state='CANCELLED')]
            observed = post(client, headers, 'reconcile', {}).json['data']['commands'][0]
            assert observed['state'] == 'settled'
        finally:
            release.set()
            worker.join(5)
        assert not worker.is_alive()
        assert len(responses) == 1 and responses[0].status_code == 200
        receipt = responses[0].json['data']
        assert receipt['broker_order_id'] == 'inert-order-1'
        assert receipt['state'] == ('uncertain' if multiple else 'settled')
        if multiple:
            assert receipt['cause'] == 'canonical_completion_conflicting'
        else:
            assert receipt == observed
        assert post(client, headers, 'commands', command).json['data'] == receipt
        restart(app)
        after = post(client, headers, 'reconcile', {}).json['data']
        assert after['obligations'] == (['command-one'] if multiple else [])
        assert len(source.writes) == 1
    finally:
        router.revoke_and_drain(timeout=0)
