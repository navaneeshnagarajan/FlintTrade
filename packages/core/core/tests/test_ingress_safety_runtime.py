"""Ingress safety closure: public runtime negatives with real gates/SDKs.

Fixture rows/ACKs below are synthetic
adversarial observations, not invented broker fixtures or account eligibility.
"""
from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from dhanhq import Order as SDKOrder

from packages.core.core.tests.test_order_route_evidence_runtime import (
    route_stack as route_stack,
    _place,
)
from packages.core.core.tests.test_dhan_super_route_correspondence import (
    route_stack as _super_stack,
    modify as modify_super,
)
from packages.core.core.tests.test_upstox_native_propagation import (
    native_stack as native_stack,
    _place as place_upstox,
)

super_stack = _super_stack
pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def exact_egress_latch(monkeypatch):
    """Unexpected native external transports fail and stay latched."""
    import httpx
    import requests.adapters
    import socket
    import urllib.request
    import hashlib
    from pathlib import Path

    root = Path(__file__).resolve().parents[4]
    scoped = [Path(__file__).resolve(), *(root / value for value in (
        "packages/core/core/src/flinttrade_core/app.py",
        "packages/core/core/src/flinttrade_core/order_routes.py",
        "packages/core/core/src/flinttrade_core/models.py",
        "packages/core/core/src/flinttrade_core/l2_state.py",
        "packages/services/engine/src/flinttrade_engine/safety.py",
        "packages/services/engine/src/flinttrade_engine/reduce_only.py",
        "packages/integrations/gateway/src/flinttrade_gateway/router.py",
        "packages/integrations/gateway/src/flinttrade_gateway/broker_read_service.py",
        "packages/integrations/gateway/src/flinttrade_gateway/brokers/dhan.py",
        "packages/integrations/gateway/src/flinttrade_gateway/brokers/dhan_mapping.py",
        "packages/integrations/gateway/src/flinttrade_gateway/brokers/groww.py",
        "packages/integrations/gateway/src/flinttrade_gateway/brokers/groww_mapping.py",
        "packages/integrations/gateway/src/flinttrade_gateway/brokers/upstox.py",
        "packages/integrations/gateway/src/flinttrade_gateway/brokers/upstox_mapping.py",
        "packages/core/core/tests/test_ingress_broker_error_runtime.py",
        "packages/core/core/tests/test_ingress_intent_controls.py",
        "packages/core/core/tests/test_ingress_reservation_controls.py",
        "packages/core/core/tests/test_order_route_evidence_runtime.py",
        "packages/core/core/tests/test_dhan_super_route_correspondence.py",
        "packages/core/core/tests/test_upstox_native_propagation.py",
    ))]

    def source_identity():
        return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in scoped}

    before = source_identity()
    print("SAFETY_01_SOURCE " + json.dumps(before, sort_keys=True), flush=True)
    attempts = []

    def refuse(kind, address):
        attempts.append((kind, str(address)))
        raise AssertionError(f"Unregistered audit transport: {kind} {address}")

    connect, connect_ex = socket.socket.connect, socket.socket.connect_ex

    def guarded_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "localhost", "::1"}:
            refuse("socket", address)
        return connect(sock, address)

    def guarded_connect_ex(sock, address):
        if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "localhost", "::1"}:
            refuse("socket-connect-ex", address)
        return connect_ex(sock, address)

    def urlopen(request, *args, **kwargs):
        refuse("urllib", getattr(request, "full_url", request))

    def requests_send(_adapter, request, **kwargs):
        refuse("requests", request.url)

    def sync_http(_transport, request):
        refuse("httpx", request.url)

    async def async_http(_transport, request):
        refuse("httpx-async", request.url)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", requests_send)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", sync_http)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_http)
    yield attempts
    print("SAFETY_01_EGRESS " + json.dumps(attempts), flush=True)
    assert attempts == []
    assert source_identity() == before, "The exact exercised production/repro scope changed during the test"


class DispatchHTTP:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def post(self, endpoint, payload):
        assert endpoint in {"/orders", "/orders/slicing"}
        self.calls.append((endpoint, deepcopy(payload)))
        if len(self.calls) == 1:
            if self.outcome == "timeout":
                raise TimeoutError("synthetic timeout after accepting dispatch")
            if self.outcome == "missing-ack":
                return {"status": "success", "data": {}}
            if self.outcome == "unverified-slice":
                return {"status": "success", "data": {"orderId": "parent-a", "orders": [
                    {"orderId": "child-a"}, {"error": "child-unknown"},
                ]}}
        identifier = f"unique-ack-{len(self.calls)}" if self.outcome == "ack" else "second-ack"
        return {"status": "success", "data": {"orderId": identifier, "orderStatus": "TRANSIT"}}


class DispatchSDK(SDKOrder):
    def __init__(self, transport):
        self.dhan_http = transport


@pytest.mark.parametrize("outcome", ["timeout", "missing-ack", "unverified-slice"])
def test_unknown_after_dispatch_retains_exact_reduce_capacity_and_blocks_retry(route_stack, outcome):
    from flinttrade_core.auth_routes import _create_token
    from flinttrade_engine.reduce_only import contract_key, reserved_exit
    from flinttrade_gateway.brokers.dhan import DhanAdapter

    app, source, _old_sdk, router = route_stack
    transport = DispatchHTTP(outcome)
    sdk = DispatchSDK(transport)
    router._adapters["dhan"] = DhanAdapter(
        client_factory=lambda _session: sdk, security_resolver=lambda _s, _e: "fixture-security",
    )
    source.position_rows = [{"symbol": "INFY", "exchange": "NSE", "product": "MIS", "quantity": "10"}]
    source.order_rows = []
    body = {
        "broker": "dhan", "account_id": "route-account", "symbol": "INFY", "exchange": "NSE",
        "action": "SELL", "quantity": 10, "price": 100, "product": "MIS", "order_type": "LIMIT",
        "variety": "iceberg" if outcome == "unverified-slice" else "regular",
    }
    headers = {"Authorization": f"Bearer {_create_token('operator', mode='live', live_mode_unlocked=True)}"}
    first = app.test_client().post("/api/v1/orders/place", json=body, headers=headers)
    key = contract_key(mode="live", adapter="dhan", account="route-account", symbol="INFY", exchange="NSE", product="MIS")
    held = reserved_exit(key)
    with app.config["SAFETY"].order_admission("dhan:route-account") as lease:
        unresolved = [{"quantity": row.order.quantity, "broker_order_id": row.broker_order_id} for row in lease.reservations]
    second = app.test_client().post("/api/v1/orders/place", json=body, headers=headers)
    observed = {
        "outcome": outcome, "first_status": first.status_code, "first_body": first.get_json(),
        "reduce_capacity_held_after_unknown": held, "unresolved_exposure": unresolved,
        "second_status": second.status_code, "second_body": second.get_json(), "sdk_dispatches": transport.calls,
    }
    print("SAFETY_01_UNKNOWN " + json.dumps(observed), flush=True)
    assert first.status_code >= 400
    assert held == 10, observed
    assert len(transport.calls) == 1, observed
    assert second.status_code >= 400, observed


@pytest.mark.parametrize("changes", [
    {"leg_name": "TARGET_LEG", "price": "1555"},
    {"leg_name": "STOP_LOSS_LEG", "stop_loss_price": "1400"},
    {"leg_name": "TARGET_LEG", "target_price": "1555", "targetPrice": "1666"},
])
def test_invalid_dhan_super_kwargs_are_refused_before_one_shot_consume(super_stack, changes):
    app, transport, consumed = super_stack
    response = modify_super(app, changes)
    observed = {"request_changes": changes, "status": response.status_code, "body": response.get_json(),
                "consumed": len(consumed), "sdk_calls": transport.calls}
    print("SAFETY_01_PREFLIGHT " + json.dumps(observed), flush=True)
    assert not [call for call in transport.calls if call[0] == "PUT"], observed
    assert consumed == [], observed
    assert response.status_code == 400, observed


@pytest.mark.parametrize("bad", [1, 11])
def test_conflicting_native_super_child_fill_aliases_cannot_mint_or_dispatch(super_stack, bad):
    app, transport, consumed = super_stack
    transport.super_row["legDetails"][0]["tradedQty"] = bad
    response = modify_super(app, {"leg_name": "TARGET_LEG", "target_price": "1555"})
    observed = {"native_child": transport.super_row["legDetails"][0], "status": response.status_code,
                "body": response.get_json(), "consumed": len(consumed), "sdk_calls": transport.calls}
    print("SAFETY_01_CHILD_ALIAS " + json.dumps(observed), flush=True)
    assert response.status_code in {409, 503}, observed
    assert consumed == [], observed
    assert not [call for call in transport.calls if call[0] == "PUT"], observed


def test_agreeing_native_super_child_fill_alias_control(super_stack):
    app, transport, consumed = super_stack
    transport.super_row["legDetails"][0]["tradedQty"] = 0
    response = modify_super(app, {"leg_name": "TARGET_LEG", "target_price": "1555"})
    assert response.status_code == 200, response.get_json()
    assert len(consumed) == 1
    assert len([call for call in transport.calls if call[0] == "PUT"]) == 1


@pytest.mark.parametrize("native_ack", [
    {"status": "success", "data": {"order_ids": ["ID-1", "ID-1"]}},
    {"status": "success", "data": {}},
    {"status": "success", "data": {"order_ids": ["ID-1", "ID-2"]}, "errors": [{"message": "unknown-child"}]},
])
def test_bad_upstox_ack_cannot_release_reduce_capacity(native_stack, native_ack):
    from flinttrade_engine.reduce_only import contract_key, reserved_exit

    stack = native_stack
    stack.ack.clear()
    stack.ack.update(deepcopy(native_ack))
    response = place_upstox(stack)
    key = contract_key(mode="live", adapter="upstox", account="native-account", symbol="INFY", exchange="NSE", product="MIS")
    observed = {"ack": native_ack, "status": response.status_code, "body": response.get_json(),
                "capacity_held": reserved_exit(key), "wire": stack.wire}
    print("SAFETY_01_UPSTOX_ACK " + json.dumps(observed), flush=True)
    assert response.status_code >= 400, observed
    assert len(stack.wire) == 1, observed
    assert reserved_exit(key) == 2, observed

def test_unrelated_external_exit_cannot_cover_a_local_ack_reservation(route_stack):
    from flinttrade_engine.reduce_only import contract_key, reserved_exit
    from flinttrade_gateway.brokers.dhan import DhanAdapter

    app, source, _old_sdk, router = route_stack
    transport = DispatchHTTP("ack")
    sdk = DispatchSDK(transport)
    router._adapters["dhan"] = DhanAdapter(client_factory=lambda _s: sdk, security_resolver=lambda _s, _e: "fixture-security")
    source.position_rows = [{"symbol": "INFY", "exchange": "NSE", "product": "MIS", "quantity": "20"}]
    source.order_rows = []
    first = _place(app, 10)
    assert first.status_code == 200, first.get_json()
    key = contract_key(mode="live", adapter="dhan", account="route-account", symbol="INFY", exchange="NSE", product="MIS")
    before = reserved_exit(key)
    assert before == 10
    # A different, externally placed ID must not represent our invisible ACK.
    source.order_rows = [{"symbol": "INFY", "exchange": "NSE", "product": "MIS", "action": "SELL",
                          "order_id": "independent-external-exit", "status": "OPEN", "quantity": "10", "filled_qty": "0",
                          "pricetype": "LIMIT", "price": "100", "trigger_price": "0"}]
    second = _place(app, 10)
    observed = {"first": first.get_json(), "first_hold": before, "second_status": second.status_code,
                "second": second.get_json(), "hold_after": reserved_exit(key), "sdk_writes": transport.calls,
                "external_book": source.order_rows, "position_book": source.position_rows}
    print("SAFETY_01_TRANSFER " + json.dumps(observed), flush=True)
    assert len(transport.calls) == 1, observed
    assert second.status_code == 409, observed

@pytest.mark.parametrize("accounts", [("CaseSensitive", "casesensitive"), ("Case-A", "Case-B")])
def test_exact_account_ids_do_not_share_reduce_only_reservations(route_stack, accounts):
    from flinttrade_core.auth_routes import _create_token
    from flinttrade_engine.safety import SafetyGate
    from flinttrade_gateway.brokers._base import Session
    from flinttrade_gateway.brokers.dhan import DhanAdapter
    from flinttrade_gateway.router import BrokerRouter

    app, source, _sdk, old_router = route_stack
    transport = DispatchHTTP("ack")
    sdk = DispatchSDK(transport)
    adapter = DhanAdapter(client_factory=lambda _s: sdk, security_resolver=lambda _s, _e: "fixture-security")
    sessions = {account: Session("synthetic", 4102444800.0, account, "dhan") for account in accounts}
    lookups = []

    def resolve(ctx, broker, account):
        assert broker == "dhan" and account in sessions
        if ctx is not None:
            assert ctx.selector == f"dhan:{account}"
            lookups.append(account)
        return sessions[account]

    router = BrokerRouter({"dhan": adapter}, resolve, consume_gate=SafetyGate().consume,
                          backend_lease_proof=old_router.backend_lease_proof)
    app.config["BROKER_ROUTER"] = router
    app.config["REGISTRY"] = SimpleNamespace(get_session_for=lambda b, a: resolve(None, b, a))
    headers = {"Authorization": f"Bearer {_create_token('operator', mode='live', live_mode_unlocked=True)}"}
    body = {"broker": "dhan", "symbol": "INFY", "exchange": "NSE", "product": "MIS", "action": "SELL",
            "quantity": 10, "pricetype": "LIMIT", "price": "100"}
    try:
        first = app.test_client().post("/api/v1/orders/place", headers=headers, json={**body, "account_id": accounts[0]})
        assert first.status_code == 200, first.get_json()
        second = app.test_client().post("/api/v1/orders/place", headers=headers, json={**body, "account_id": accounts[1]})
        observed = {"accounts": accounts, "first": first.get_json(), "second_status": second.status_code,
                    "second": second.get_json(), "session_lookups": lookups, "sdk_dispatches": len(transport.calls)}
        print("SAFETY_01_ACCOUNT_SCOPE " + json.dumps(observed), flush=True)
        assert second.status_code == 200, observed
        assert lookups == list(accounts), observed
        assert len(transport.calls) == 2, observed
    finally:
        router.revoke_and_drain(timeout=0)


@pytest.mark.parametrize("extra,expected", [({"trailing_jump": "5"}, 400), ({"iceberg_legs": "2"}, 400), ({}, 200),
                                          ({"trailing_jump": True}, 400), ({"iceberg_legs": 1.5}, 400)])
def test_groww_http_preserves_or_refuses_supplied_advanced_intent(route_stack, extra, expected):
    from flinttrade_core.auth_routes import _create_token
    from flinttrade_engine.safety import SafetyGate
    from flinttrade_gateway.brokers._base import Session
    from flinttrade_gateway.brokers.groww import GrowwAdapter
    from flinttrade_gateway.router import BrokerRouter

    app, source, _sdk, old_router = route_stack
    wire = []

    def transport(method, url, *, headers, params=None, json_body=None):
        assert method == "POST" and urlsplit(url).path == "/v1/order/create"
        wire.append(deepcopy(json_body))
        return 200, {"status": "SUCCESS", "payload": {"groww_order_id": "groww-ack-1"}}

    adapter = GrowwAdapter(http_factory=lambda: transport)
    session = Session("synthetic", 4102444800.0, "route-account", "groww")

    def resolve(_ctx, broker, account):
        assert (broker, account) == ("groww", "route-account")
        return session

    router = BrokerRouter({"groww": adapter}, resolve, consume_gate=SafetyGate().consume,
                          backend_lease_proof=old_router.backend_lease_proof)
    app.config["BROKER_ROUTER"] = router
    app.config["NATIVE_ADAPTERS"] = {"groww": source}
    app.config["REGISTRY"] = SimpleNamespace(get_session_for=lambda b, a: resolve(None, b, a))
    headers = {"Authorization": f"Bearer {_create_token('operator', mode='live', live_mode_unlocked=True)}"}
    body = {"broker": "groww", "account_id": "route-account", "symbol": "INFY", "exchange": "NSE",
            "product": "MIS", "action": "SELL", "quantity": "2", "price": "100", "pricetype": "LIMIT",
            "strategy": "review-ref-01", **extra}
    try:
        response = app.test_client().post("/api/v1/orders/place", headers=headers, json=body)
        observed = {"request": body, "status": response.status_code, "response": response.get_json(), "wire": wire}
        print("SAFETY_01_GROWW_INTENT " + json.dumps(observed), flush=True)
        assert response.status_code == expected, observed
        assert len(wire) == (1 if expected == 200 else 0), observed
    finally:
        router.revoke_and_drain(timeout=0)
