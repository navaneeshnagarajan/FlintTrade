"""H3 behaviour preservation at normal HTTP, real gates/router and inert SDK IO.

These synthetic failures exercise the existing exception policy, not native
eligibility or financial execution. No private policy helper is tested.
"""
from __future__ import annotations

import json
import logging
from copy import deepcopy

import pytest
from dhanhq import Order as SDKOrder

from flinttrade_core.exceptions import BrokerInternal, SafetyBypassError, UnsupportedCapabilityError
from flinttrade_engine.algo_tag_guard import AlgoTagLimitError
from flinttrade_gateway.exceptions import BrokerNotFoundError
from packages.core.core.tests.test_dhan_super_route_correspondence import (
    modify as modify_super,
    route_stack as _super_stack,
)
from packages.core.core.tests.test_ingress_safety_runtime import (
    exact_egress_latch as exact_egress_latch,
    route_stack as route_stack,
)
from packages.core.core.tests.test_order_route_evidence_runtime import _headers, _place

super_stack = _super_stack
pytestmark = pytest.mark.integration


class _RateAndKeyFault(AlgoTagLimitError, KeyError):
    """Pin the placement catch's existing disconnected-before-rate precedence."""


class _UnsupportedValueFault(UnsupportedCapabilityError, ValueError):
    """Pin capability-before-generic broker/value precedence."""


def _fault(kind: str, hooks: list[str]) -> Exception:
    class HostileFault(RuntimeError):
        @property
        def __class__(self):
            hooks.append("class")
            raise AssertionError("Do not use exception attributes for policy")

        @property
        def broker_message(self):
            hooks.append("message")
            raise AssertionError("Do not inspect arbitrary broker properties")

        def __str__(self):
            hooks.append("str")
            raise AssertionError("Do not stringify arbitrary SDK faults")

    private = "synthetic-private-error-text"
    if kind == "hostile":
        return HostileFault()
    if kind == "broker":
        return BrokerInternal(private, broker_id="dhan", broker_code="503")
    constructors = {
        "safety": SafetyBypassError, "rate": AlgoTagLimitError,
        "not-found": BrokerNotFoundError, "key": KeyError,
        "not-implemented": NotImplementedError, "unsupported": UnsupportedCapabilityError,
        "value": ValueError, "runtime": RuntimeError, "timeout": TimeoutError,
        "rate-and-key": _RateAndKeyFault, "unsupported-and-value": _UnsupportedValueFault,
    }
    return constructors[kind](private)


class _PolicyHTTP:
    """Only the external transport varies; installed Order methods still run."""

    def __init__(self, error: Exception | None):
        self.error = error
        self.calls = []

    def post(self, endpoint, payload):
        assert endpoint == "/orders"
        self.calls.append(("POST", endpoint, deepcopy(payload)))
        if self.error is not None:
            raise self.error
        return {"status": "success", "data": {"orderId": "policy-ack", "orderStatus": "TRANSIT"}}

    def delete(self, endpoint):
        assert endpoint == "/orders/policy-order"
        self.calls.append(("DELETE", endpoint, None))
        if self.error is not None:
            raise self.error
        return {"status": "success", "data": {"orderId": "policy-order", "orderStatus": "CANCEL_PENDING"}}


class _PolicySDK(SDKOrder):
    def __init__(self, transport: _PolicyHTTP):
        self.dhan_http = transport


@pytest.fixture
def policy_stack(request, monkeypatch):
    """Observe delegates, without substituting admission or gate consumption."""
    from flinttrade_core import order_routes
    from flinttrade_engine import safety as safety_module
    from flinttrade_gateway.brokers.dhan import DhanAdapter

    route = request.param
    state = {"route": route, "error": None, "stage": "ack", "hooks": [],
             "minted": [], "consumed": [], "invoked": [], "wire": []}
    if route == "super":
        app, transport, _consumed = request.getfixturevalue("super_stack")
        router = app.config["BROKER_ROUTER"]
        original_put = transport.put

        def put(endpoint, payload):
            if state["stage"] == "after-invoke":
                assert endpoint == "/super/orders/super-fixture"
                transport.calls.append(("PUT", endpoint, deepcopy(payload)))
                state["wire"].append(("PUT", endpoint, deepcopy(payload)))
                raise state["error"]
            result = original_put(endpoint, payload)
            state["wire"].append(("PUT", endpoint, deepcopy(payload)))
            return result

        monkeypatch.setattr(transport, "put", put)
    else:
        app, _source, _sdk, router = request.getfixturevalue("route_stack")
        transport = _PolicyHTTP(None)
        state["wire"] = transport.calls
        router._adapters["dhan"] = DhanAdapter(
            client_factory=lambda _session: _PolicySDK(transport),
            security_resolver=lambda _s, _e: "fixture-security",
        )
        state["transport"] = transport

    original_session = router._session_provider

    def session_for(ctx, broker, account):
        assert ctx.selector == "dhan:route-account"
        if state["stage"] == "before-invoke":
            raise state["error"]
        return original_session(ctx, broker, account)

    monkeypatch.setattr(router, "_session_provider", session_for)
    original_consume = router._consume_gate

    def consume(identifier):
        result = original_consume(identifier)
        state["consumed"].append(result)
        return result

    monkeypatch.setattr(router, "_consume_gate", consume)
    original_invoke = order_routes._LiveWriteProgress.on_adapter_invoke

    def invoke(progress):
        state["invoked"].append(True)
        original_invoke(progress)

    monkeypatch.setattr(order_routes._LiveWriteProgress, "on_adapter_invoke", invoke)
    # gate_broker_write delegates to gate_order; observe the outer mint once.
    for name in ("gate_broker_write" if route == "super" else "gate_order",):
        original = getattr(safety_module, name)

        def mint(*args, _original=original, **kwargs):
            result = _original(*args, **kwargs)
            state["minted"].append({"context": result, "args": args, "kwargs": kwargs})
            return result

        monkeypatch.setattr(safety_module, name, mint)
    state["app"] = app
    return state


def _request(stack):
    app = stack["app"]
    if stack["route"] == "place":
        return _place(app, 10)
    if stack["route"] == "super":
        return modify_super(app, {"leg_name": "TARGET_LEG", "target_price": "1555"})
    return app.test_client().post(
        "/api/v1/orders/cancel", headers=_headers(),
        json={"broker": "dhan", "account_id": "route-account", "orderid": "policy-order"},
    )


# Literal contracts from the old catches; not calculated by the resolver.
# Each tuple is (placement, ordinary cancel, extended Super) before invocation.
_CASES = [
    ("safety", (403, 403, 403)), ("rate", (429, 429, 429)),
    ("not-found", (503, 503, 503)), ("key", (503, 503, 503)),
    ("not-implemented", (501, 501, 501)), ("unsupported", (501, 501, 501)),
    ("broker", (500, 500, 502)), ("value", (500, 500, 502)),
    ("runtime", (500, 500, 500)), ("hostile", (500, 500, 500)),
    ("rate-and-key", (503, 429, 429)), ("unsupported-and-value", (501, 501, 501)),
]


@pytest.mark.parametrize("policy_stack", ["place", "cancel", "super"], indirect=True)
@pytest.mark.parametrize("stage", ["before-invoke", "after-invoke"])
@pytest.mark.parametrize("kind,statuses", _CASES, ids=[row[0] for row in _CASES])
def test_existing_error_policy_preserves_http_invocation_and_holds(policy_stack, stage, kind, statuses, caplog):
    from flinttrade_engine.reduce_only import contract_key, reserved_exit

    stack = policy_stack
    route = stack["route"]
    stack["stage"] = stage
    stack["error"] = _fault(kind, stack["hooks"])
    if "transport" in stack and stage == "after-invoke":
        stack["transport"].error = stack["error"]
    caplog.set_level(logging.WARNING, logger="flinttrade.order_routes")

    response = _request(stack)
    body = response.get_json()
    after = stage == "after-invoke"
    status = statuses[("place", "cancel", "super").index(route)]
    expected_status = (502 if route == "super" and kind in {"broker", "value"} else 500) if after else status
    failure = {"place": "Order dispatch failed", "cancel": "Order cancel failed", "super": "Super order modify failed"}[route]
    subject = "Request" if route == "super" else "Order"
    disconnected = "Broker 'dhan' (account 'route-account') is not connected. Add the selector to workspace.json brokers.registered and brokers.account_acls, then restart."
    unavailable = "Order placement (place) is not yet available for broker 'dhan'." if route == "place" else (
        "This operation (cancel) is not yet available for broker 'dhan'." if route == "cancel" else
        "This operation (modify_super_order) is not yet available for broker 'dhan'."
    )
    expected_message = failure if after else {
        403: subject + " refused", 429: subject + " refused by rate guard",
        503: disconnected, 501: unavailable,
    }.get(status, failure)
    operation = "modify_super_order" if route == "super" else route
    affected = {"broker": "dhan", "account_id": "route-account", "operation": operation}
    if route == "place":
        affected.update(symbol="INFY", exchange="NSE", product="MIS", action="SELL")
    elif route == "cancel":
        affected["order_id"] = "policy-order"
    else:
        affected.update(order_id="super-fixture", leg_name="TARGET_LEG")
    expected_body = {"status": "error", "message": expected_message, "affected_item": affected,
                     "dispatch_outcome": "unknown_after_dispatch" if after else "refused_before_dispatch",
                     "retry_safe": False}
    if kind == "broker":
        expected_body["broker_code"] = "503"
    assert response.status_code == expected_status, body
    assert body == expected_body
    assert len(stack["minted"]) == 1
    assert stack["consumed"] == ([True] if after else [])
    assert stack["invoked"] == ([True] if after else [])
    assert len(stack["wire"]) == (1 if after else 0)
    assert stack["hooks"] == []
    failures = [row for row in caplog.records if row.name == "flinttrade.order_routes" and "failed |" in row.message]
    assert len(failures) == 1 and failures[0].levelno == logging.WARNING
    assert failures[0].msg == "Live %s failed | adapter=%s account=%s error=%s"
    assert failures[0].args[0:2] == (operation, "dhan")
    assert failures[0].args[2] != "route-account" and failures[0].args[3] == type(stack["error"]).__name__
    assert "synthetic-private-error-text" not in failures[0].message
    with stack["app"].config["SAFETY"].order_admission("dhan:route-account") as lease:
        holds = [{"quantity": row.order.quantity, "broker_order_id": row.broker_order_id} for row in lease.reservations]
    key = contract_key(mode="live", adapter="dhan", account="route-account", symbol="INFY", exchange="NSE", product="MIS")
    capacity = reserved_exit(key)
    if route == "place":
        assert capacity == (10 if after else 0)
        assert holds == ([{"quantity": "10", "broker_order_id": ""}] if after else [])
        if after:
            repeated = _request(stack)
            assert repeated.status_code == 409, repeated.get_json()
            assert len(stack["wire"]) == 1 and stack["consumed"] == [True] and stack["invoked"] == [True]
    elif route == "cancel":
        assert holds == [] and capacity == 0
    print("ERROR_POLICY_MATRIX " + json.dumps({
        "route": route, "stage": stage, "kind": kind, "status": response.status_code, "body": body,
        "mint_count": len(stack["minted"]), "consumed": stack["consumed"], "invoked": stack["invoked"],
        "wire": stack["wire"], "holds": holds, "reduce_capacity": capacity,
        "log": failures[0].message, "hooks": stack["hooks"],
    }, sort_keys=True), flush=True)


@pytest.mark.parametrize("policy_stack", ["place", "cancel", "super"], indirect=True)
def test_existing_success_is_ack_only_and_real_one_shot_replay_is_refused(policy_stack):
    from flinttrade_gateway.routing_config import RoutingHint
    import asyncio

    stack = policy_stack
    response = _request(stack)
    body = response.get_json()
    assert response.status_code == 200, body
    assert stack["consumed"] == [True] and stack["invoked"] == [True] and len(stack["wire"]) == 1
    assert not {"filled", "filled_quantity", "closed", "dispatch_outcome", "retry_safe"}.intersection(body)
    assert "data" in body if stack["route"] != "cancel" else body == {"status": "success", "orderid": "policy-order"}
    captured = stack["minted"][0]
    context = captured["context"]
    assert context.adapter_id == "dhan" and context.account_id == "route-account"
    # Replay the exact captured fingerprint/authority through the real router.
    router = stack["app"].config["BROKER_ROUTER"]
    args = captured["args"]
    hint = RoutingHint(adapter_id="dhan", account_id="route-account")
    if stack["route"] == "place":
        replay = router.place_order(args[1], order=args[0], safety_ctx=context, hint=hint)
    elif stack["route"] == "cancel":
        replay = router.cancel_order(args[1], order=args[0], order_id="policy-order", safety_ctx=context, hint=hint)
    else:
        replay = router.execute_gated(args[2], verb=args[0], payload=args[1], safety_ctx=context, hint=hint)
    with pytest.raises(SafetyBypassError):
        asyncio.run(replay)
    assert stack["consumed"] == [True, False]
    assert len(stack["wire"]) == 1 and stack["invoked"] == [True]
    print("ERROR_POLICY_ACK " + json.dumps({"route": stack["route"], "status": response.status_code,
          "body": body, "wire": stack["wire"], "consumed": stack["consumed"]}, sort_keys=True), flush=True)
