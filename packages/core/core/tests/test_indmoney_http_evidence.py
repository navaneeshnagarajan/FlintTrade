"""INDstocks ACK evidence through normal HTTP, real gates and native REST.

Only synthetic book/session lookups and the exact external REST transport are
injected. The attempt sink proves argument propagation, not durable recovery.
"""
from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from threading import Event, Lock
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from flinttrade_core.app import create_flask_app
from flinttrade_core.auth_routes import _create_token
from flinttrade_core.exceptions import SafetyBypassError
from flinttrade_core.models import Order
from flinttrade_data.audit_logger import IST, AuditLogger
from flinttrade_engine.laya import DecisionStatus, process_laya
from flinttrade_engine.reduce_only import reset_reduce_only_for_tests
from flinttrade_engine.safety import SafetyConfig, SafetyGate, SafetySystem
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter
from flinttrade_gateway.router import BrokerRouter

pytestmark = pytest.mark.integration

_MARKET_BODY = {
    "txn_type": "BUY", "exchange": "NSE", "segment": "EQUITY", "product": "CNC", "qty": 5,
    "order_type": "MARKET", "validity": "DAY", "security_id": "123", "is_amo": False, "algo_id": "99999",
}
_MARKET_EFFECTS = {
    "requested_type": "MARKET", "effective_type": "LIMIT", "effective_limit_price": None,
    "trailing_active": False, "limitations": ["MARKET_TO_LIMIT"],
}


class _Books:
    """Synthetic independent safety inputs, not a permissive SafetySystem."""

    async def positions(self, _session: Session) -> list[Any]:
        return []

    async def order_book(self, _session: Session) -> list[Any]:
        return []

    async def funds(self, _session: Session) -> dict[str, str]:
        return {"used_margin": "0", "total_balance": "1000000", "opening_risk_capital": "1000000"}

    async def trade_book(self, _session: Session) -> list[Any]:
        return []

    async def holdings(self, _session: Session) -> list[Any]:
        return []

    async def quotes(self, _session: Session, symbols: list[str]) -> list[dict[str, Any]]:
        return [
            {"symbol": name.split(":", 1)[1], "exchange": name.split(":", 1)[0], "ltp": 100,
             "prev_close": 100, "previous_close_trusted": True}
            for name in symbols
        ]

    async def margin_calculator(self, _session: Session, _orders: list[Any]) -> dict[str, str]:
        return {"required_margin": "100"}


class _ExactTransport:
    def __init__(self) -> None:
        self.expected: list[tuple[str, dict[str, Any], dict[str, Any], Callable[[], None] | None]] = []
        self.calls: list[dict[str, Any]] = []
        self.violations: list[str] = []
        self._lock = Lock()

    def expect(self, path: str, body: dict[str, Any], acknowledgement: dict[str, Any], *, before_return=None) -> None:
        self.expected.append((path, deepcopy(body), acknowledgement, before_return))

    def __call__(self, method, url, *, headers, params=None, json_body=None):
        try:
            with self._lock:
                self.calls.append({"method": method, "url": url, "body": deepcopy(json_body)})
                assert self.expected, "Unregistered INDstocks transport invocation"
                path, body, acknowledgement, before_return = self.expected.pop(0)
            assert (method, url) == ("POST", f"https://api.indstocks.com{path}")
            assert headers == {"Authorization": "SYNTHETIC", "Content-Type": "application/json"}
            assert params is None
            assert json_body == body
            if before_return is not None:
                before_return()
        except AssertionError as exc:
            self.violations.append(str(exc))
            raise
        return 200, acknowledgement


class _AttemptSink:
    """Observe the existing router transport without claiming persistence."""

    def __init__(self) -> None:
        self.prepared: list[dict[str, Any]] = []
        self.invoked: list[str] = []
        self.acknowledged: list[tuple[str, Any]] = []
        self.json_acknowledgements: list[tuple[str, Any]] = []
        self.unknown: list[tuple[str, str]] = []
        self.failed_before_invoke: list[tuple[str, str]] = []
        self.fail_acknowledgement = False
        self._lock = Lock()

    def assert_write_ready(self) -> None:
        pass

    def prepare_dispatch(self, **fields: Any) -> str:
        with self._lock:
            self.prepared.append(fields)
            return f"synthetic-attempt-{len(self.prepared)}"

    def mark_invoked(self, attempt_id: str) -> None:
        self.invoked.append(attempt_id)

    def acknowledge(self, attempt_id: str, acknowledgement: Any) -> None:
        self.acknowledged.append((attempt_id, acknowledgement))  # Keep the actual argument, not a deep-copy fix.
        self.json_acknowledgements.append((attempt_id, json.loads(json.dumps(acknowledgement, allow_nan=False))))
        if self.fail_acknowledgement:
            raise OSError("Synthetic attempt sink unavailable after invocation")

    def mark_outcome_unknown(self, attempt_id: str, error_kind: str) -> None:
        self.unknown.append((attempt_id, error_kind))

    def mark_failed_before_invoke(self, attempt_id: str, error_kind: str) -> None:
        self.failed_before_invoke.append((attempt_id, error_kind))


@pytest.fixture
def native_http_stack(backend_lease_factory, monkeypatch, tmp_path):
    from flinttrade_core.secure_file import write_secret_text

    workspace = tmp_path / "bridge-workspace"
    workspace.mkdir()
    monkeypatch.setenv("FLINTTRADE_WORKSPACE_DIR", str(workspace))
    write_secret_text(workspace / "master_password", "pytest-master-password")
    reset_reduce_only_for_tests()
    safety = SafetySystem(SafetyConfig(check_market_hours=False))
    proof = backend_lease_factory()
    with AuditLogger(str(tmp_path / "indmoney-audit")) as audit:
        app = create_flask_app(safety=safety, audit=audit, safety_config_ready=True, backend_lease_proof=proof)
        app.config["TESTING"] = True
        process_laya().set_status(DecisionStatus.READY)  # Explicit synthetic admission input, never runtime readiness.
        transport = _ExactTransport()
        adapter = IndMoneyAdapter(http_factory=lambda: transport, security_resolver=lambda _symbol, _exchange: "123")
        session = Session("SYNTHETIC", 4102444800.0, "IND-OFFLINE", "indmoney")
        sessions = {"IND-OFFLINE": session, "IND-OTHER": Session("SYNTHETIC", 4102444800.0, "IND-OTHER", "indmoney")}
        gate = SafetyGate()
        sink = _AttemptSink()

        def session_for(ctx, broker, account):
            if broker != "indmoney" or account not in sessions or ctx is not None and ctx.actor_id != "operator":
                raise SafetyBypassError("Synthetic account ACL refused")
            return sessions[account]

        router = BrokerRouter(
            {"indmoney": adapter}, session_for, consume_gate=gate.consume, backend_lease_proof=proof,
            write_admission=safety.broker_write_admission, lifecycle_store=sink,
        )
        app.config["BROKER_ROUTER"] = router
        app.config["NATIVE_ADAPTERS"] = {"indmoney": _Books()}
        app.config["REGISTRY"] = SimpleNamespace(get_session_for=lambda b, a: session_for(None, b, a))
        captured = []
        receipts = []
        execute = router.place_order

        async def observe(ctx, **fields):
            captured.append((ctx, deepcopy(fields)))
            result = await execute(ctx, **fields)
            receipts.append(result)
            return result

        monkeypatch.setattr(router, "place_order", observe)
        stack = SimpleNamespace(app=app, router=router, adapter=adapter, session=session, sessions=sessions,
                                gate=gate, safety=safety, proof=proof, transport=transport, sink=sink, audit=audit,
                                captured=captured, receipts=receipts, execute=execute)
        yield stack
        assert router.revoke_and_drain(timeout=0)
        app.config["CLIENT"].close_sync()  # Retire the normal factory's owned loop after admitted writes drain.
        assert transport.violations == []
    reset_reduce_only_for_tests()


def _headers(*, mode="live", unlocked=True, actor="operator") -> dict[str, str]:
    return {"Authorization": f"Bearer {_create_token(actor, mode=mode, live_mode_unlocked=unlocked)}",
            "X-FlintTrade-Mode": mode}


def _place(stack, *, path="/api/v1/orders/indmoney/place", headers=None, **fields):
    return stack.app.test_client().post(path, headers=_headers() if headers is None else headers, json={
        "broker": "indmoney", "account_id": "IND-OFFLINE", "symbol": "SYNTHETIC", "exchange": "NSE",
        "product": "CNC", "action": "BUY", "quantity": "5", "price": "0", "pricetype": "MARKET",
        "variety": "regular", **fields,
    })


def _audit_rows(stack):
    return stack.audit.read_day(datetime.now(IST).date().isoformat())


@pytest.mark.parametrize("path", ["/api/v1/orders/indmoney/place", "/api/v1/orders/place"])
@pytest.mark.parametrize("variety", ["regular", "amo"])
@pytest.mark.parametrize("pricetype", ["MARKET", "LIMIT"])
def test_regular_http_real_audit_and_attempt_argument_preserve_per_call_ack(
    native_http_stack, path, variety, pricetype,
):
    stack = native_http_stack
    native = {"status": "success", "data": {
        "order_id": "EQ-OFFLINE", "order_status": "INITIATED", "extra_info": {"observations": ["accepted", None]},
    }}
    wire_body = {**_MARKET_BODY, "is_amo": variety == "amo", "order_type": pricetype}
    effects = deepcopy(_MARKET_EFFECTS)
    if pricetype == "LIMIT":
        wire_body["limit_price"] = 100.55
        effects = {"requested_type": "LIMIT", "effective_type": "LIMIT", "effective_limit_price": 100.55,
                   "trailing_active": False, "limitations": []}
    stack.transport.expect("/order", wire_body, native)

    response = _place(stack, path=path, variety=variety, pricetype=pricetype, price="100.55" if pricetype == "LIMIT" else "0")

    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["orderid"] == body["data"] == "EQ-OFFLINE"  # Retain both scalar compatibility slots.
    assert body["order_ids"] == ["EQ-OFFLINE"]
    assert body["child_order_id"] is None
    assert body["execution_effects"] == effects
    assert body["broker_response"] == native["data"]  # Already-unwrapped native ACK, not a fill.
    assert len(stack.transport.calls) == len(stack.captured) == len(stack.receipts) == 1
    ctx, fields = stack.captured[0]
    assert isinstance(fields["order"], Order)
    assert (ctx.actor_id, ctx.mode, ctx.selector) == ("operator", "live", "indmoney:IND-OFFLINE")
    assert fields["safety_ctx"].verify(fields["order"], ctx, "indmoney", "IND-OFFLINE")
    evidence = {key: body[key] for key in ("order_ids", "child_order_id", "execution_effects", "broker_response")}
    assert stack.sink.invoked == ["synthetic-attempt-1"]
    assert stack.sink.acknowledged == [("synthetic-attempt-1", {"orderid": "EQ-OFFLINE", **evidence})]
    rows = _audit_rows(stack)
    assert len(rows) == 1
    assert rows[0]["event_type"] == "ORDER_PLACED"
    assert (rows[0]["adapter_id"], rows[0]["account_id"], rows[0]["actor_id"]) == ("indmoney", "IND-OFFLINE", "operator")
    assert {key: rows[0][key] for key in evidence} == evidence
    for record in (body, rows[0], stack.sink.acknowledged[0][1]):
        assert not {"filled_quantity", "execution_confirmed", "closed", "durable", "protection_active"} & record.keys()
    expected_evidence = deepcopy(evidence)
    native["data"]["extra_info"]["observations"].append("TRANSPORT-MUTATION")
    stack.receipts[0].execution_effects["limitations"].append("RECEIPT-MUTATION")
    stack.receipts[0].broker_response["extra_info"]["observations"].append("RECEIPT-MUTATION")
    stack.adapter.last_execution_effects["effective_limit_price"] = 999
    assert {key: body[key] for key in evidence} == expected_evidence
    assert {key: _audit_rows(stack)[0][key] for key in evidence} == expected_evidence
    assert stack.sink.acknowledged == [("synthetic-attempt-1", {"orderid": "EQ-OFFLINE", **expected_evidence})]
    assert stack.sink.json_acknowledgements == stack.sink.acknowledged
    body["broker_response"]["extra_info"]["observations"].append("HTTP-CONSUMER-MUTATION")
    assert stack.sink.acknowledged[0][1]["broker_response"]["extra_info"]["observations"] == ["accepted", None]
    assert _audit_rows(stack)[0]["broker_response"]["extra_info"]["observations"] == ["accepted", None]


@pytest.mark.parametrize("path", ["/api/v1/orders/indmoney/place", "/api/v1/orders/place"])
def test_smart_trigger_http_preserves_distinct_child_resource_and_exact_native_body(native_http_stack, path):
    stack = native_http_stack
    native = {"status": "success", "data": {"order_data": [{
        "order_id": "EQ-PARENT", "order_status": "INITIATED",
        "child_order_details": {"order_id": "GTT-CHILD", "order_status": "CREATED"},
    }]}}
    stack.transport.expect("/smart/order", {
        "txn_type": "BUY", "exchange": "NSE", "segment": "EQUITY", "product": "CNC", "qty": 5,
        "validity": "DAY", "security_id": "123", "algo_id": "99999", "order_type": "TRIGGER", "trigger_price": 101,
    }, native)

    response = _place(stack, path=path, variety="trigger", trigger_price="101")

    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    expected = {
        "order_ids": ["EQ-PARENT"], "child_order_id": "GTT-CHILD", "broker_response": deepcopy(native["data"]),
        "execution_effects": {
            "requested_type": "TRIGGER", "effective_type": "TRIGGER_LIMIT", "effective_limit_price": 101,
            "trailing_active": False, "limitations": [],
        },
    }
    assert body == {"status": "success", "orderid": "EQ-PARENT", "data": "EQ-PARENT", **expected}
    assert str(stack.receipts[0]) == "EQ-PARENT"
    assert stack.receipts[0].order_ids == ("EQ-PARENT",)  # Child resource is not an exchange child/fill.
    assert stack.sink.acknowledged == [("synthetic-attempt-1", {"orderid": "EQ-PARENT", **expected})]
    assert stack.sink.json_acknowledgements == stack.sink.acknowledged
    rows = _audit_rows(stack)
    assert len(rows) == 1
    assert {key: rows[0][key] for key in expected} == expected
    native["data"]["order_data"][0]["child_order_details"]["order_status"] = "LATER-STATE"
    stack.receipts[0].broker_response["order_data"][0]["child_order_details"]["order_id"] = "OTHER-RESOURCE"
    stack.adapter.last_child_order_id = "UNRELATED-RESOURCE"
    for record in (body, _audit_rows(stack)[0], stack.sink.acknowledged[0][1]):
        assert record["child_order_id"] == "GTT-CHILD"
        assert record["broker_response"] == expected["broker_response"]
        assert not {"filled_quantity", "execution_confirmed", "exchange_order_id", "closed", "durable"} & record.keys()


@pytest.mark.parametrize("value", ["scalar", "mapping", "unknown-string", "unknown-object"])
def test_receipt_bridge_is_an_explicit_known_type_allowlist_not_duck_typing(value):
    from flinttrade_gateway.router import placement_acknowledgement_fields

    class UnknownString(str):
        @property
        def evidence_fields(self):
            pytest.fail("Unknown string receipt evidence must never be inspected")

    class UnknownObject:
        @property
        def evidence_fields(self):
            pytest.fail("Unknown object receipt evidence must never be inspected")

    candidates = {"scalar": "legacy-first-id", "mapping": {"orderid": "legacy-first-id", "execution_effects": {}},
                  "unknown-string": UnknownString("legacy-first-id"), "unknown-object": UnknownObject()}
    assert placement_acknowledgement_fields(candidates[value]) == {}


def test_receipt_bridge_preserves_known_upstox_resource_kind_and_all_ids():
    from flinttrade_gateway.brokers.upstox import UpstoxPlacementAcknowledgement
    from flinttrade_gateway.router import placement_acknowledgement_fields

    native = {"status": "success", "data": {"gtt_order_ids": ["GTT-FIRST", "GTT-SECOND"]}}
    receipt = UpstoxPlacementAcknowledgement(["GTT-FIRST", "GTT-SECOND"], native, id_field="gtt_order_ids")
    evidence = placement_acknowledgement_fields(receipt)
    assert receipt == "GTT-FIRST"
    assert evidence == {"gtt_order_ids": ["GTT-FIRST", "GTT-SECOND"], "broker_response": native}
    assert "order_ids" not in evidence
    native["data"]["gtt_order_ids"].append("LATER-MUTATION")
    assert evidence["gtt_order_ids"] == evidence["broker_response"]["data"]["gtt_order_ids"] == ["GTT-FIRST", "GTT-SECOND"]


@pytest.mark.parametrize("control,expected_status", [
    ("no-auth", 401), ("invalid-auth", 401), ("practice", 400), ("explore", 400),
    ("locked", 403), ("header-mismatch", 403), ("other-actor", 403),
])
def test_normal_auth_mode_pin_and_account_acl_guards_still_refuse_before_transport(
    native_http_stack, control, expected_status,
):
    stack = native_http_stack
    headers = _headers()
    if control == "no-auth":
        headers = {}
    elif control == "invalid-auth":
        headers = {"Authorization": "Bearer not-a-signed-token"}
    elif control in {"practice", "explore"}:
        headers = _headers(mode=control)
    elif control == "locked":
        headers = _headers(unlocked=False)
    elif control == "header-mismatch":
        headers["X-FlintTrade-Mode"] = "practice"
    elif control == "other-actor":
        headers = _headers(actor="unauthorised-operator")

    response = _place(stack, headers=headers)

    assert response.status_code == expected_status, response.get_json()
    assert stack.transport.calls == []
    assert stack.sink.prepared == stack.sink.invoked == stack.sink.acknowledged == []
    assert _audit_rows(stack) == []


@pytest.mark.parametrize("control,expected_status", [
    ("safety-config", 503), ("laya-down", 403), ("price-distance", 403), ("kill-switch", 403),
])
def test_real_admission_readiness_and_global_guard_are_not_bypassed_by_the_receipt_bridge(
    native_http_stack, control, expected_status,
):
    stack = native_http_stack
    fields = {}
    if control == "safety-config":
        stack.app.config["SAFETY_CONFIG_READY"] = False
    elif control == "laya-down":
        process_laya().set_status(DecisionStatus.DOWN)
    elif control == "price-distance":
        fields = {"pricetype": "LIMIT", "price": "73.55"}  # Independent LTP is 100; keep the 5% L1 guard intact.
    elif control == "kill-switch":
        stack.safety.l5_kill.activate("Synthetic global guard control")

    response = _place(stack, **fields)

    assert response.status_code == expected_status, response.get_json()
    assert stack.captured == stack.transport.calls == stack.sink.prepared == []
    assert _audit_rows(stack) == []


@pytest.mark.parametrize("tamper", [
    "quantity", "variety", "trigger", "active-trailing", "account", "actor", "jti", "mode", "selector",
    "incarnation", "generation", "read-only", "kill-after-signing",
])
def test_http_minted_native_ticket_refuses_tampering_lineage_and_scope_before_dispatch(
    native_http_stack, monkeypatch, tamper,
):
    from flinttrade_gateway.routing_config import RoutingHint

    stack = native_http_stack

    async def intercept(ctx, **fields):
        if tamper in {"quantity", "variety", "trigger", "active-trailing"}:
            changes = {"quantity": {"quantity": "6"}, "variety": {"variety": "amo"},
                       "trigger": {"trigger_price": "102"}, "active-trailing": {"trailing_jump": "1"}}[tamper]
            fields["order"] = fields["order"].model_copy(update=changes)
        elif tamper == "account":
            fields["hint"] = RoutingHint(adapter_id="indmoney", account_id="IND-OTHER")  # Both accounts exist.
        elif tamper in {"actor", "jti", "mode", "selector"}:
            changes = {"actor": {"actor_id": "unauthorised-operator"}, "jti": {"jti": "other-caller"},
                       "mode": {"mode": "practice"}, "selector": {"selector": "indmoney:IND-OTHER"}}[tamper]
            ctx = replace(ctx, **changes)
            if tamper == "selector":
                # The signed dimension is the resolved account, not this descriptive string alone.
                fields["hint"] = RoutingHint(adapter_id="indmoney", account_id="IND-OTHER")
        elif tamper == "incarnation":
            fields["safety_ctx"] = replace(fields["safety_ctx"], backend_incarnation="unowned-incarnation")
        elif tamper == "generation":
            assert stack.router.revoke_and_drain(timeout=0)
        elif tamper == "read-only":
            stack.session.read_only_until_at = 4102444800.0
        elif tamper == "kill-after-signing":
            stack.safety.l5_kill.activate("Synthetic activation after signing")
        return await stack.execute(ctx, **fields)

    monkeypatch.setattr(stack.router, "place_order", intercept)
    response = _place(stack)

    assert response.status_code == 403, response.get_json()
    assert stack.transport.calls == stack.sink.prepared == stack.sink.invoked == stack.sink.acknowledged == []
    assert _audit_rows(stack) == []


def test_http_native_ack_keeps_real_one_shot_replay_and_missing_router_token_refusal(native_http_stack):
    stack = native_http_stack
    stack.transport.expect("/order", _MARKET_BODY, {"status": "success", "data": {"order_id": "EQ-ONCE"}})
    response = _place(stack)
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["execution_effects"] == _MARKET_EFFECTS
    ctx, fields = stack.captured[0]
    with pytest.raises(SafetyBypassError, match="already consumed"):
        asyncio.run(stack.execute(ctx, **fields))
    with pytest.raises(SafetyBypassError):
        asyncio.run(stack.adapter.place_order(stack.session, fields["order"]))
    assert len(stack.transport.calls) == len(stack.sink.acknowledged) == len(_audit_rows(stack)) == 1


def test_audit_write_failure_cannot_convert_a_native_ack_into_a_retry(native_http_stack, monkeypatch):
    stack = native_http_stack

    def unavailable(_event, **_fields):
        raise OSError("Synthetic audit unavailable after native invocation")

    monkeypatch.setattr(stack.audit, "log_event", unavailable)
    stack.transport.expect("/order", _MARKET_BODY, {"status": "success", "data": {"order_id": "EQ-AUDIT-FAIL"}})
    response = _place(stack)
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["order_ids"] == ["EQ-AUDIT-FAIL"]
    assert response.get_json()["execution_effects"] == _MARKET_EFFECTS
    assert stack.sink.acknowledged[0][1]["orderid"] == "EQ-AUDIT-FAIL"
    ctx, fields = stack.captured[0]
    with pytest.raises(SafetyBypassError, match="already consumed"):
        asyncio.run(stack.execute(ctx, **fields))
    assert len(stack.transport.calls) == 1
    assert _audit_rows(stack) == []


def test_attempt_argument_failure_returns_ack_but_blocks_replay_and_further_normal_writes(native_http_stack):
    stack = native_http_stack
    stack.sink.fail_acknowledgement = True
    stack.transport.expect("/order", _MARKET_BODY, {"status": "success", "data": {"order_id": "EQ-SINK-FAIL"}})
    response = _place(stack)
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["execution_effects"] == _MARKET_EFFECTS
    assert stack.sink.acknowledged[0][1]["order_ids"] == ["EQ-SINK-FAIL"]
    assert stack.sink.unknown == [("synthetic-attempt-1", "OSError")]
    ctx, fields = stack.captured[0]
    with pytest.raises(SafetyBypassError, match="already consumed"):
        asyncio.run(stack.execute(ctx, **fields))
    assert _place(stack).status_code == 403
    assert len(stack.transport.calls) == len(stack.sink.prepared) == len(_audit_rows(stack)) == 1


@pytest.mark.parametrize("native", [
    {"status": "failed", "data": {"order_id": "EQ-UNCERTAIN"}},
    {"status": "success", "data": {"order_id": "EQ-UNCERTAIN", "order_status": "FAILED", "error": "rejected"}},
])
def test_invalid_late_native_outcome_is_not_ack_fill_or_safe_retry(native_http_stack, native):
    stack = native_http_stack
    stack.transport.expect("/order", _MARKET_BODY, native)
    response = _place(stack)
    assert response.status_code == 500, response.get_json()
    assert response.get_json()["status"] == "error"
    assert stack.sink.acknowledged == []
    assert len(stack.sink.unknown) == 1
    assert stack.sink.failed_before_invoke == []  # Exact invocation boundary crossed, irrespective of native status.
    assert _audit_rows(stack) == []
    ctx, fields = stack.captured[0]
    with pytest.raises(SafetyBypassError, match="already consumed"):
        asyncio.run(stack.execute(ctx, **fields))
    assert _place(stack).status_code == 403
    assert len(stack.transport.calls) == 1


def test_native_creation_read_and_activation_freezes_are_unchanged(native_http_stack):
    from flinttrade_gateway.adapter import BROKER_CATALOG
    from flinttrade_gateway.brokers.native_factory import SDK_PIN_BY_BROKER, build_native_adapters

    stack = native_http_stack
    body = {"broker": "indmoney", "account_id": "IND-OFFLINE", "symbol": "SYNTHETIC", "exchange": "NSE",
            "action": "BUY", "quantity": "5", "trigger_price": "101"}
    assert _place(stack, variety="gtt").status_code == 422
    client = stack.app.test_client()
    assert client.post("/api/v1/orders/forever", headers=_headers(), json=body).status_code == 501
    assert client.post("/api/v1/orders/multi", headers=_headers(), json={"orders": [body]}).status_code == 501
    assert client.get("/api/v1/orders/forever?broker=indmoney&account_id=IND-OFFLINE", headers=_headers()).status_code == 409
    assert stack.captured == stack.transport.calls == stack.sink.prepared == []
    assert SDK_PIN_BY_BROKER["indmoney"] is None  # Actual native adapter is REST-only; there is no INDmoney SDK.
    assert BROKER_CATALOG["indmoney"].connectable is False
    assert BROKER_CATALOG["indmoney"].native_connect_blockers == [
        "Authoritative smart-parent cancellation discriminator", "Broker-native atomic reduce-only close primitive",
        "Live order-safety proof",
    ]
    assert build_native_adapters(["indmoney"], attest_ok=lambda _b: True, has_credentials=lambda _b: True) == {}


def test_delayed_ack_is_correlated_to_its_origin_not_another_accounts_latest_result(native_http_stack):
    stack = native_http_stack
    entered, release = Event(), Event()
    first_native = {"status": "success", "data": {"order_id": "EQ-SLOW", "extra_info": {"items": ["first"]}}}
    second_native = {"status": "success", "data": {"order_id": "EQ-FAST", "extra_info": {"items": ["second"]}}}

    def delayed():
        entered.set()
        assert release.wait(10), "Synthetic pending transport was not released"

    stack.transport.expect("/order", _MARKET_BODY, first_native, before_return=delayed)
    stack.transport.expect("/order", {
        "txn_type": "BUY", "exchange": "NSE", "segment": "EQUITY", "product": "CNC", "qty": 5,
        "order_type": "LIMIT", "validity": "DAY", "security_id": "123", "is_amo": True,
        "algo_id": "99999", "limit_price": 100.55,
    }, second_native)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(_place, stack)
        try:
            assert entered.wait(10), "Actual native invocation did not enter the pending transport"
            stack.session.read_only_until_at = 4102444800.0  # Revocation after invocation cannot erase that outcome.
            fast = _place(stack, account_id="IND-OTHER", variety="amo", pricetype="LIMIT", price="100.55")
            assert fast.status_code == 200, fast.get_json()
            assert fast.get_json()["orderid"] == "EQ-FAST"
            assert fast.get_json()["execution_effects"]["effective_limit_price"] == 100.55
            stack.adapter.last_execution_effects["effective_limit_price"] = 999
            stack.adapter.last_child_order_id = "UNRELATED-CHILD"
        finally:
            release.set()
        slow = pending.result(timeout=10)
    assert slow.status_code == 200, slow.get_json()
    assert slow.get_json()["orderid"] == "EQ-SLOW"
    assert slow.get_json()["execution_effects"] == _MARKET_EFFECTS
    assert slow.get_json()["child_order_id"] is None
    assert slow.get_json()["broker_response"] == first_native["data"]
    assert [attempt for attempt, _ack in stack.sink.acknowledged] == ["synthetic-attempt-2", "synthetic-attempt-1"]
    assert [(row["account_id"], row["order_ids"]) for row in _audit_rows(stack)] == [
        ("IND-OTHER", ["EQ-FAST"]), ("IND-OFFLINE", ["EQ-SLOW"]),
    ]
    assert [(row["account_id"], row["request_context"].mode) for row in stack.sink.prepared] == [
        ("IND-OFFLINE", "live"), ("IND-OTHER", "live"),
    ]
    first_native["data"]["extra_info"]["items"].append("LATER-MUTATION")
    assert stack.sink.acknowledged[1][1]["broker_response"]["extra_info"]["items"] == ["first"]
    assert _audit_rows(stack)[1]["broker_response"]["extra_info"]["items"] == ["first"]
    assert _place(stack).status_code == 403  # New requests honour read-only scope, not the late ACK.
    stack.session.read_only_until_at = None
    ctx, fields = stack.captured[0]
    with pytest.raises(SafetyBypassError, match="already consumed"):
        asyncio.run(stack.execute(ctx, **fields))
    assert len(stack.transport.calls) == 2


def test_revoked_generation_drains_late_ack_without_reopening_write_authority(native_http_stack):
    stack = native_http_stack
    entered, release = Event(), Event()

    def delayed():
        entered.set()
        assert release.wait(10), "Synthetic pending transport was not released"

    stack.transport.expect("/order", _MARKET_BODY, {"status": "success", "data": {"order_id": "EQ-LATE"}},
                           before_return=delayed)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(_place, stack)
        try:
            assert entered.wait(10)
            assert stack.router.revoke_and_drain(timeout=0) is False  # Owned admitted call is still pending.
            refused = _place(stack, account_id="IND-OTHER")
            assert refused.status_code == 403, refused.get_json()
        finally:
            release.set()
        response = pending.result(timeout=10)
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["order_ids"] == ["EQ-LATE"]
    assert response.get_json()["execution_effects"] == _MARKET_EFFECTS
    assert stack.router.revoke_and_drain(timeout=0) is True
    assert _place(stack).status_code == 403
    assert stack.sink.acknowledged[0][1]["orderid"] == "EQ-LATE"
    assert _audit_rows(stack)[0]["order_ids"] == ["EQ-LATE"]
    assert len(stack.transport.calls) == 1
