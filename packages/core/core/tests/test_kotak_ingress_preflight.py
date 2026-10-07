"""Kotak pure preflight at normal HTTP ingress and the real pinned SDK.

All sessions, books, symbols and ACKs
are synthetic. Real safety/gate/router/adapter and installed 3.0.8 serialisation
run without broker login; ACK-only correspondence is not eligibility or a fill.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest

from flinttrade_core.auth_routes import _create_token
from flinttrade_core.exceptions import SafetyBypassError, UnsupportedCapabilityError
from flinttrade_core.models import Order
from flinttrade_engine.safety import SafetyGate, SafetySystem
from flinttrade_gateway.brokers import kotakneo_mapping as M
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.kotakneo import KotakNeoAdapter
from flinttrade_gateway.brokers.kotakneo_sdk import KotakNeoSdkSession, _sdk_class
from flinttrade_gateway.router import BrokerRouter
from flinttrade_gateway.routing_config import RoutingConfig, RoutingHint
from packages.core.core.tests.test_ingress_safety_runtime import exact_egress_latch as exact_egress_latch
from packages.core.core.tests.test_order_route_evidence_runtime import route_stack as route_stack

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[4]
BASE = {
    "broker": "kotakneo", "account_id": "route-account", "symbol": "FIXTURE", "exchange": "NSE",
    "product": "MIS", "action": "SELL", "quantity": "2", "price": "100", "pricetype": "LIMIT",
}
PATHS = ["/api/v1/orders/place", "/api/v1/orders/kotakneo/place"]


@pytest.fixture(autouse=True)
def kotak_source_identity():
    paths = [str(Path(__file__).relative_to(ROOT)),
        "packages/core/core/src/flinttrade_core/order_routes.py",
        "packages/core/core/src/flinttrade_core/models.py",
        "packages/core/core/src/flinttrade_core/app.py",
        "packages/services/engine/src/flinttrade_engine/safety.py",
        "packages/services/engine/src/flinttrade_engine/reduce_only.py",
        "packages/integrations/gateway/src/flinttrade_gateway/router.py",
        "packages/integrations/gateway/src/flinttrade_gateway/brokers/kotakneo.py",
        "packages/integrations/gateway/src/flinttrade_gateway/brokers/kotakneo_mapping.py",
        "packages/integrations/gateway/src/flinttrade_gateway/brokers/kotakneo_sdk.py",
        "packages/core/core/tests/test_order_routes_routed.py",
    ]
    def identities():
        return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sorted(paths)}
    before = identities()
    print("KOTAK_INGRESS_SOURCE " + json.dumps(before, sort_keys=True), flush=True)
    yield
    assert identities() == before, "Exercised source or untracked regression changed during the test"


@pytest.fixture
def kotak_stack(route_stack, monkeypatch):
    import flinttrade_engine.safety as safety_module

    app, source, _unused_sdk, old_router = route_stack
    safety = app.config["SAFETY"]
    assert type(safety) is SafetySystem
    gate = SafetyGate()
    stack = SimpleNamespace(
        app=app, source=source, safety=safety, gate=gate, reads=[], minted=[], consumed=[], checked=[],
        validated=[], invoked=[], wire=[], resolved=[], events=[], violations=[], faults=[], outcome="ack",
    )
    for name in ("positions", "order_book", "funds", "trade_book", "holdings", "quotes", "margin_calculator"):
        original = getattr(source, name)
        async def read(*args, _original=original, _name=name, **kwargs):
            stack.reads.append(_name)
            stack.events.append("read:" + _name)
            return await _original(*args, **kwargs)
        monkeypatch.setattr(source, name, read)

    def transport(request):
        try:
            assert (request.method, request.url.host, request.url.path) == (
                "POST", "fixture.invalid", "/quick/order/rule/ms/place",
            )
            assert request.headers["content-type"] == "application/x-www-form-urlencoded"
            form = parse_qs(request.content.decode("utf-8"), strict_parsing=True)
            assert set(form) == {"jData"} and len(form["jData"]) == 1
            stack.events.append("wire")
            stack.wire.append({"method": request.method, "host": request.url.host, "path": request.url.path,
                               "body": json.loads(form["jData"][0])})
            if stack.outcome == "timeout":
                raise httpx.ReadTimeout("Synthetic timeout after the inert request was accepted")
            if stack.outcome == "unsupported-after-wire":
                raise UnsupportedCapabilityError("Synthetic unsupported outcome after wire acceptance", broker_id="kotakneo")
            return httpx.Response(200, json={"stat": "Ok", "stCode": 200, "nOrdNo": "FIXTURE-ACK-1"})
        except AssertionError as exc:
            stack.violations.append(str(exc))
            raise

    neo = _sdk_class()(consumer_key="synthetic", access_token=None, transport=httpx.MockTransport(transport))
    neo.configuration.edit_token = "synthetic"
    neo.configuration.edit_sid = "synthetic"
    neo.configuration.base_url = "https://fixture.invalid"
    facade = KotakNeoSdkSession.__new__(KotakNeoSdkSession)
    facade._neo = neo
    facade._closed = False
    stack.facade = facade

    def resolve_symbol(symbol, exchange):
        assert symbol == "FIXTURE" and exchange in {"NSE", "MCX"}
        stack.resolved.append((symbol, exchange))
        stack.events.append("resolve")
        # Explicit synthetic identities, never inferred production instruments.
        return {"NSE": "FIXTURE-EQ", "MCX": "FIXTURE-MCX-FUT"}[exchange]

    adapter = KotakNeoAdapter(client_factory=lambda _session: facade, symbol_resolver=resolve_symbol)
    stack.adapter = adapter
    session = Session("synthetic", 4102444800.0, "route-account", "kotakneo")
    session.extra["client"] = facade
    stack.session = session

    def resolve(context, broker, account):
        assert (broker, account) == ("kotakneo", "route-account")
        if context is not None:
            assert context.selector == "kotakneo:route-account"
        return session

    def consume(identifier):
        result = gate.consume(identifier)
        stack.consumed.append(result)
        stack.events.append("consume")
        return result

    original_mint = safety_module.gate_order
    def mint(order, context, **kwargs):
        result = original_mint(order, context, **kwargs)
        stack.minted.append((order, context, result))
        stack.events.append("mint")
        return result
    monkeypatch.setattr(safety_module, "gate_order", mint)

    original_check = safety.check_order
    def check(order, **kwargs):
        results = original_check(order, **kwargs)
        stack.checked.append([{"layer": row.layer, "passed": row.passed, "reason": row.reason} for row in results])
        stack.events.append("check")
        return results
    monkeypatch.setattr(safety, "check_order", check)

    original_validate = M.validate_v3_order
    stack.pure_validator = original_validate
    def validate(order):
        stack.validated.append(order.model_dump(mode="json"))
        stack.events.append("validate")
        return original_validate(order)
    monkeypatch.setattr(M, "validate_v3_order", validate)

    original_place = adapter.place_order
    stack.direct_place = original_place
    async def place(session, order, *, _router_token=None):
        stack.invoked.append(order.model_dump(mode="json"))
        stack.events.append("invoke")
        try:
            return await original_place(session, order, _router_token=_router_token)
        except Exception as exc:
            stack.faults.append(type(exc).__name__)
            raise
    monkeypatch.setattr(adapter, "place_order", place)

    selector = "kotakneo:route-account"
    config = RoutingConfig.from_workspace({
        "registered": [selector], "execution": {"default": selector},
        "data": {name: selector for name in ("ticks", "historical", "option_chains", "quote")},
        "account_acls": {"kotakneo": {"route-account": ["operator"]}},
    })
    router = BrokerRouter({"kotakneo": adapter}, resolve, consume_gate=consume, config=config,
                          backend_lease_proof=old_router.backend_lease_proof)
    stack.router = router
    app.config["BROKER_ROUTER"] = router
    app.config["NATIVE_ADAPTERS"] = {"kotakneo": source}
    app.config["REGISTRY"] = SimpleNamespace(get_session_for=lambda b, a: resolve(None, b, a))
    source.position_rows = [{
        "symbol": "FIXTURE", "exchange": "NSE", "product": "MIS", "quantity": "10", "net_qty": 10,
        "multiplier": 1, "cross_currency": False,
    }]
    source.order_rows = []
    try:
        yield stack
    finally:
        router.revoke_and_drain(timeout=0)
        facade.close()
        assert stack.violations == []


def _holds(stack, body):
    from flinttrade_engine.laya import process_laya
    from flinttrade_engine.reduce_only import contract_key, reserved_exit

    key = contract_key(mode="live", adapter="kotakneo", account="route-account",
                       symbol="FIXTURE", exchange=body["exchange"], product=body["product"])
    with stack.safety.order_admission("kotakneo:route-account") as lease:
        reservations = [{"quantity": row.order.quantity, "broker_order_id": row.broker_order_id}
                        for row in lease.reservations]
    return {"reducing_hold": reserved_exit(key), "exposure_holds": reservations,
            "proof_count": len(process_laya().decision_log())}


def _request(stack, fields, path=PATHS[1], *, configured_default=False):
    body = {**BASE, **deepcopy(fields)}
    if configured_default:
        del body["broker"], body["account_id"]
    stack.source.position_rows[0].update(exchange=body["exchange"], product=body["product"])
    response = stack.app.test_client().post(path, json=body, headers={
        "Authorization": "Bearer " + _create_token("operator", mode="live", live_mode_unlocked=True),
    })
    observed = {
        "request": body, "path": path, "status": response.status_code, "response": response.get_json(),
        "minted": [order.model_dump(mode="json") for order, _ctx, _gate in stack.minted],
        "consumed": stack.consumed, "checked": stack.checked, "validated": stack.validated,
        "invoked": stack.invoked, "reads": stack.reads, "resolved": stack.resolved, "wire": stack.wire,
        "events": stack.events, "faults": stack.faults, **_holds(stack, body),
        "session_client_bound": stack.session.extra["client"] is stack.facade,
    }
    print("KOTAK_INGRESS_OBSERVED " + json.dumps(observed, sort_keys=True), flush=True)
    return response


def _no_admission(stack, fields):
    assert stack.minted == [] and stack.consumed == [] and stack.invoked == [] and stack.wire == []
    assert stack.checked == [] and stack.reads == [] and stack.source.reads == [] and stack.resolved == []
    assert _holds(stack, {**BASE, **fields}) == {"reducing_hold": 0, "exposure_holds": [], "proof_count": 0}


@pytest.mark.parametrize("fields", [
    pytest.param({"exchange": "MCX", "validity": "IOC"}, id="mcx-ioc"),
    pytest.param({"variety": "bo"}, id="bo"),
    pytest.param({"variety": "co"}, id="co"),
])
@pytest.mark.parametrize("path", PATHS, ids=["ordinary", "named"])
def test_unsupported_shape_is_refused_before_reads_admission_and_pinned_sdk(kotak_stack, fields, path):
    response = _request(kotak_stack, fields, path)
    assert response.status_code == 501, response.get_json()
    _no_admission(kotak_stack, fields)
    assert len(kotak_stack.validated) == 1


@pytest.mark.parametrize("fields,wire_changes", [
    pytest.param({}, {}, id="omitted-regular-day"),
    pytest.param({"validity": "IOC"}, {"rt": "IOC"}, id="nse-ioc"),
    pytest.param({"exchange": "MCX", "validity": "DAY"},
                 {"es": "mcx_fo", "ts": "FIXTURE-MCX-FUT"}, id="mcx-day"),
    pytest.param({"variety": "amo", "validity": "IOC"}, {"am": "YES", "rt": "IOC"}, id="amo-ioc"),
])
@pytest.mark.parametrize("path", PATHS, ids=["ordinary", "named"])
def test_supported_ordinary_intent_keeps_exact_pinned_wire(kotak_stack, fields, wire_changes, path):
    response = _request(kotak_stack, fields, path)
    assert response.status_code == 200, response.get_json()
    assert response.get_json() == {"status": "success", "orderid": "FIXTURE-ACK-1", "data": "FIXTURE-ACK-1"}
    assert kotak_stack.wire == [{
        "method": "POST", "host": "fixture.invalid", "path": "/quick/order/rule/ms/place", "body": {
            "am": "NO", "dq": "0", "es": "nse_cm", "mp": "0", "pc": "MIS", "pr": "100", "pt": "L",
            "qt": "2", "rt": "DAY", "tp": "0", "ts": "FIXTURE-EQ", "tt": "S", "ig": None,
            "os": "NEOTRADEAPI", **wire_changes,
        },
    }]
    assert len(kotak_stack.minted) == 1 and kotak_stack.consumed == [True] and len(kotak_stack.invoked) == 1
    assert len(kotak_stack.checked) == 1 and len(kotak_stack.checked[0]) == 5
    assert all(row["passed"] for row in kotak_stack.checked[0])
    assert len(kotak_stack.validated) == 3
    assert all(row == kotak_stack.invoked[0] for row in kotak_stack.validated)
    assert kotak_stack.events[0] == "validate"
    wire = deepcopy(kotak_stack.wire)
    order, context, gate = kotak_stack.minted[0]
    with pytest.raises(SafetyBypassError, match="already consumed"):
        asyncio.run(kotak_stack.router.place_order(context, order=order, safety_ctx=gate,
                    hint=RoutingHint(adapter_id="kotakneo", account_id="route-account")))
    assert kotak_stack.consumed == [True, False] and kotak_stack.wire == wire
    assert len(kotak_stack.invoked) == 1
    print("KOTAK_INGRESS_REPLAY " + json.dumps({"consumed": kotak_stack.consumed, "wire": kotak_stack.wire}), flush=True)


@pytest.mark.parametrize("kind", ["mcx-ioc", "bo", "co"])
def test_original_public_refusal_caller_retains_unchanged_assertions(backend_lease_proof, monkeypatch, kind):
    """Instrument the exact original caller; retain its original fixture contract.

    This diagnostic uses that caller's existing fake SDK/safety, not the normal
    factory/pinned-SDK proof above. Its observations cannot replace that proof.
    """
    import flinttrade_engine.safety as safety_module
    from flinttrade_engine.laya import DecisionStatus, process_laya
    from packages.core.core.tests import test_order_routes_routed as original

    process_laya().set_status(DecisionStatus.READY)  # Same synthetic fixture as the original module.
    safety_module.set_safety_gate_secret(original._SECRET)  # Preserve the original module's gate-key fixture.
    consumed, minted, invoked, reads = [], [], [], []
    real_consume = SafetyGate.consume
    def consume(gate, identifier):
        result = real_consume(gate, identifier)
        consumed.append(result)
        return result
    monkeypatch.setattr(SafetyGate, "consume", consume)

    real_mint = safety_module.gate_order
    def mint(order, context, **kwargs):
        result = real_mint(order, context, **kwargs)
        minted.append(order.model_dump(mode="json"))
        return result
    monkeypatch.setattr(safety_module, "gate_order", mint)

    build = original._real_kotak_route_stack
    def observed_stack(proof):
        app, adapter, client = build(proof)
        real_place = adapter.place_order
        async def place(session, order, *, _router_token=None):
            invoked.append(order.model_dump(mode="json"))
            return await real_place(session, order, _router_token=_router_token)
        monkeypatch.setattr(adapter, "place_order", place)
        for name in ("positions", "order_book", "funds", "trade_book", "holdings", "quotes", "margin_calculator"):
            method = getattr(adapter, name)
            async def read(*args, _method=method, _name=name, **kwargs):
                reads.append(_name)
                return await _method(*args, **kwargs)
            monkeypatch.setattr(adapter, name, read)
        http = app.test_client()
        post = http.post
        def observed_post(path, **kwargs):
            response = post(path, **kwargs)
            print("KOTAK_ORIGINAL_CALLER_OBSERVED " + json.dumps({
                "kind": kind, "path": path, "request": kwargs["json"], "status": response.status_code,
                "response": response.get_json(), "minted": minted, "consumed": consumed,
                "invoked": invoked, "reads": reads, "sdk_place_calls": client.place_calls,
                "original_no_sdk_assertion": "UNREACHED" if response.status_code != 501 else "NEXT_ASSERTION",
            }, sort_keys=True), flush=True)
            return response
        monkeypatch.setattr(http, "post", observed_post)
        monkeypatch.setattr(app, "test_client", lambda: http)
        return app, adapter, client
    monkeypatch.setattr(original, "_real_kotak_route_stack", observed_stack)
    if kind == "mcx-ioc":
        original.test_kotak_place_route_preserves_mcx_ioc_and_refuses_before_sdk(backend_lease_proof)
    else:
        original.test_kotak_place_route_refuses_unsupported_variety_before_sdk(backend_lease_proof, kind)


@pytest.mark.parametrize("fields", [
    pytest.param({"exchange": "MCX", "validity": "IOC"}, id="mcx-ioc"),
    pytest.param({"variety": "bo"}, id="bo"),
    pytest.param({"variety": "co"}, id="co"),
    pytest.param({}, id="ordinary-positive"),
])
def test_configured_default_selects_kotak_preflight_without_body_selector(kotak_stack, fields):
    response = _request(kotak_stack, fields, PATHS[0], configured_default=True)
    assert response.status_code == (501 if fields else 200), response.get_json()
    if fields:
        _no_admission(kotak_stack, fields)
    else:
        assert len(kotak_stack.wire) == 1 and kotak_stack.consumed == [True]


@pytest.mark.parametrize("fields", [
    pytest.param({"exchange": "MCX", "validity": "IOC"}, id="mcx-ioc"),
    pytest.param({"variety": "bo"}, id="bo"),
    pytest.param({"variety": "co"}, id="co"),
])
def test_named_target_not_untrusted_body_broker_selects_kotak_preflight(kotak_stack, fields):
    response = _request(kotak_stack, {"broker": "dhan", **fields}, PATHS[1])
    assert response.status_code == 501, response.get_json()
    _no_admission(kotak_stack, fields)


@pytest.mark.parametrize("fields", [
    pytest.param({"validity": "GTC"}, id="removed-validity"),
    pytest.param({"variety": "iceberg"}, id="unsupported-iceberg"),
    pytest.param({"price": "0"}, id="nonpositive-limit"),
    pytest.param({"pricetype": "SL"}, id="missing-stop-trigger"),
    pytest.param({"disclosed_quantity": "3"}, id="disclosure-above-total"),
    pytest.param({"market_protection": False}, id="explicit-false-protection"),
    pytest.param({"market_protection": True}, id="explicit-true-protection"),
])
@pytest.mark.parametrize("path", PATHS, ids=["ordinary", "named"])
def test_existing_kotak_pure_validation_neighbours_precede_admission(kotak_stack, fields, path):
    response = _request(kotak_stack, fields, path)
    assert response.status_code == 501, response.get_json()
    _no_admission(kotak_stack, fields)


@pytest.mark.parametrize("path", PATHS, ids=["ordinary", "named"])
def test_mtf_representation_does_not_grant_unverified_adapter_eligibility(kotak_stack, path):
    response = _request(kotak_stack, {"product": "MTF"}, path)
    assert response.status_code == 500, response.get_json()
    assert response.get_json()["dispatch_outcome"] == "unknown_after_dispatch"
    assert len(kotak_stack.minted) == 1 and kotak_stack.consumed == [True] and len(kotak_stack.invoked) == 1
    assert all(row["product"] == "MTF" for row in kotak_stack.validated)
    assert len(kotak_stack.validated) == 2 and kotak_stack.events[0] == "validate"
    assert kotak_stack.faults == ["UnsupportedCapabilityError"]
    assert kotak_stack.resolved == [] and kotak_stack.wire == []


@pytest.mark.parametrize("outcome", ["timeout", "unsupported-after-wire"])
@pytest.mark.parametrize("path", PATHS, ids=["ordinary", "named"])
def test_possible_pinned_dispatch_stays_unknown_with_both_holds_and_no_retry(kotak_stack, outcome, path):
    kotak_stack.outcome = outcome
    fields = {"quantity": "10", "validity": "IOC"}
    first = _request(kotak_stack, fields, path)
    assert first.status_code == 500, first.get_json()
    assert first.get_json()["dispatch_outcome"] == "unknown_after_dispatch"
    assert first.get_json()["retry_safe"] is False
    assert _holds(kotak_stack, {**BASE, **fields}) == {
        "reducing_hold": 10, "exposure_holds": [{"quantity": "10", "broker_order_id": ""}], "proof_count": 1,
    }
    assert len(kotak_stack.wire) == 1 and kotak_stack.wire[0]["body"]["qt"] == "10"
    assert kotak_stack.events.index("wire") > kotak_stack.events.index("invoke")
    second = _request(kotak_stack, fields, path)
    assert second.status_code == 409, second.get_json()
    assert len(kotak_stack.wire) == 1 and kotak_stack.consumed == [True] and len(kotak_stack.minted) == 1
    assert len(kotak_stack.invoked) == 1
    assert kotak_stack.source.position_rows[0]["quantity"] == "10"


def test_direct_adapter_token_guard_still_precedes_mapping_and_sdk(kotak_stack):
    with pytest.raises(SafetyBypassError):
        asyncio.run(kotak_stack.direct_place(kotak_stack.session, Order(**BASE)))
    _no_admission(kotak_stack, {})
    assert kotak_stack.validated == []


@pytest.mark.parametrize("path", PATHS, ids=["ordinary", "named"])
def test_read_only_router_refusal_releases_uninvoked_holds_without_consuming(kotak_stack, path):
    kotak_stack.session.read_only_until_at = 4102444800.0
    response = _request(kotak_stack, {}, path)
    assert response.status_code == 403, response.get_json()
    assert response.get_json()["dispatch_outcome"] == "refused_before_dispatch"
    assert len(kotak_stack.minted) == 1 and kotak_stack.consumed == []
    assert kotak_stack.invoked == [] and kotak_stack.wire == []
    assert _holds(kotak_stack, BASE)["reducing_hold"] == 0 and _holds(kotak_stack, BASE)["exposure_holds"] == []
    kotak_stack.session.read_only_until_at = None  # Synthetic session only, no readiness promotion.
    assert _request(kotak_stack, {}, path).status_code == 200
    assert len(kotak_stack.wire) == 1 and kotak_stack.consumed == [True]
