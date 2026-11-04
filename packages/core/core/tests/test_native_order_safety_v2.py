"""Real registered-producer intent through canonical ingress and preparation.

Laya remains default-Down: preflight evidence is not a native entry-positive.
Observers forward original arguments and results without supplying authority.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from packages.core.core.tests.test_laya_qualification_owner import sidecar as sidecar
from packages.core.core.tests.test_native_financial_owner import _financial
from packages.core.core.tests.test_native_model_safety_v2 import _start
from packages.core.core.tests.test_native_producer_v2 import _granted, _plan, _registered
from packages.core.core.tests.test_native_workflow_v2 import MountedDesk
from packages.core.core.tests.native_writer_fixture import mounted_desk as mounted_desk

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("intent", ["ordinary", "amo", "ioc", "unsupported-protection"])
def test_registered_order_reaches_real_canonical_preparation_without_intent_loss(
    mounted_desk: MountedDesk, monkeypatch: pytest.MonkeyPatch, intent: str,
) -> None:
    """Preserve full canonical terms or refuse active unsupported intent before reads.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
        monkeypatch: Scoped replacements restored after this test.
        intent: Ordinary, AMO, IOC or unsupported-protection intent supplied through canonical ingress.
    """
    from flinttrade_core import order_routes
    from flinttrade_gateway.router import BrokerRouter

    desk = mounted_desk
    order: dict[str, Any] = {
        "symbol": "SYNTH", "exchange": "NSE", "product": "CNC", "action": "BUY",
        "quantity": "1", "price": "4", "pricetype": "LIMIT", "strategy": "operator-selected-strategy",
        "disclosed_quantity": "1", "validity": "IOC" if intent == "ioc" else "DAY",
        "variety": "amo" if intent == "amo" else "regular", "admission_note": "synthetic reviewed proposal",
    }
    if intent == "amo":
        order["amo_time"] = "OPEN_30"
    if intent == "unsupported-protection":
        order["target_price"] = "6"
        order["market_protection"] = True
    source, registration = _registered(desk, order=order)
    _plan(source, registration, mark="4")
    canonical: list[dict[str, Any]] = []
    pins: list[Any] = []
    contexts: list[Any] = []
    original_builder = order_routes._body_to_order
    original_preflight = BrokerRouter.preflight_order

    def observe_builder(*args: Any, **kwargs: Any) -> Any:
        """Capture only the genuine builder's completed result."""
        value = original_builder(*args, **kwargs)
        canonical.append(value.model_dump(mode="json"))
        return value

    def observe_preflight(router: Any, value: Any, **kwargs: Any) -> Any:
        """Retain the genuine router-issued pin beside its original consumer."""
        consumer = kwargs["capture_target"]
        contexts.append(kwargs["request_ctx"])

        def capture(pin: Any) -> None:
            pins.append(pin)
            consumer(pin)

        return original_preflight(router, value, **{**kwargs, "capture_target": capture})

    monkeypatch.setattr(order_routes, "_body_to_order", observe_builder)
    monkeypatch.setattr(BrokerRouter, "preflight_order", observe_preflight)
    owner = _start(desk, _granted(desk))
    assert owner.completed.wait(5) and owner.shutdown(0)
    assert canonical == [registration.order]
    if intent == "unsupported-protection":
        assert pins == []
    else:
        assert len(pins) == 1
        preparation = pins[0].preparation
        assert json.loads(preparation.intent_json) == registration.order
        assert contexts[0].actor_id == "bounded:mounted-native"
        assert registration.order["strategy"] != contexts[0].actor_id
        kwargs = preparation.sdk_kwargs()
        assert kwargs["validity"] == order["validity"]
        assert kwargs["disclosed_quantity"] == 1
    assert desk.calls == []
    assert _financial(desk)["reservations"]["producer-entry"]["state"] == "released"


def _terminal_lifecycle_case(
    mounted_desk: MountedDesk, sidecar: tuple[Any, list[str]], monkeypatch: pytest.MonkeyPatch,
    refusal: str | None = None,
    after_settlement: Callable[[MountedDesk, Callable[[str], Any]], None] | None = None,
) -> None:
    """Require the real qualified producer, gate and installed SDK, without false market inputs.

    Args:
        mounted_desk: Normal-factory native workflow fixture with inert external transports.
        sidecar: Actual managed sidecar runtime and its inert HTTP request ledger.
        monkeypatch: Scoped replacements restored after this test.
        refusal: Optional incomplete observation tested before legitimate settlement.
        after_settlement: Optional test-owned callback for later bounded evidence.
    """
    import requests
    from datetime import datetime
    from flinttrade_engine import safety as safety_module

    class SessionClock(datetime):
        """Synthetic wall-clock input; the real exchange-hours predicate still runs."""

        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            """Supply a synthetic wall clock while retaining the real exchange-hours predicate."""
            return datetime.now(tz).replace(hour=11, minute=0, second=0)

    monkeypatch.setattr(safety_module, "datetime", SessionClock)
    desk = mounted_desk
    qualifier = desk.app.config["LAYA_QUALIFICATION_OWNER"]
    qualifier.configure(cases=(("positive", "BUY", "Reviewed limit", "allow"),
                               ("negative", "BUY", "revenge", "deny")), max_age_seconds=10.0)
    assert qualifier.qualify()["qualified"]
    order = {"symbol": "SYNTH", "exchange": "NSE", "product": "CNC", "action": "BUY",
             "quantity": "1", "price": "4", "pricetype": "LIMIT", "admission_note": "Reviewed limit"}
    phases: list[dict[str, Any]] = []
    original_mint = safety_module.gate_order
    minted: list[tuple[Any, Any, Any]] = []
    original_send = requests.Session.send
    terminal = False
    fault: str | None = None
    native_records: list[dict[str, Any]] = []
    native_source: Any = None

    async def native_read(_session: Any) -> list[dict[str, Any]]:
        """Return independent synthetic resource scope through the real read owner."""
        return [] if fault == "missing-child-set" else json.loads(json.dumps(native_records))

    def mint(*args: Any, **kwargs: Any) -> Any:
        """Observe and forward the unchanged canonical gate and retain its actual ticket."""
        result = original_mint(*args, **kwargs)
        minted.append((args[0], args[1], result))
        phases.append({"phase": "canonical_mint", "order": args[0].model_dump(mode="json")})
        return result

    def send(session: requests.Session, request: requests.PreparedRequest, **kwargs: Any) -> requests.Response:
        """Serve exact synthetic external payloads after installed SDK serialization."""
        assert type(request.url) is str
        assert request.body is None or type(request.body) in (str, bytes)
        phases.append({"phase": "installed_sdk_http", "method": request.method, "url": request.url,
                       "body": json.loads(request.body) if request.body else None})
        # Labelled independent account/quote/margin primitives at external HTTP,
        # parsed by the retained installed SDK and real adapter, never L2 DTOs.
        books = {"positions", "holdings", "orders", "forever/orders", "super/orders", "alerts/orders"}
        path = request.url.removeprefix("https://api.dhan.co/v2/")
        if request.method == "GET" and path in books:
            data: Any = []
            if path == "orders" and terminal:
                data = [{"orderId": "synthetic-canonical-order", "exchangeOrderId": "ExchangeOne",
                         "dhanClientId": "Mounted", "orderStatus": "CANCELLED", "tradingSymbol": "SYNTH",
                         "securityId": "123", "exchangeSegment": "NSE_EQ", "transactionType": "BUY",
                         "productType": "CNC", "orderType": "LIMIT", "quantity": 1, "filledQty": 0,
                         "price": 4, "remainingQuantity": 0}]
                if fault == "missing-order":
                    data = []
                elif fault == "missing-quantity":
                    data[0].pop("filledQty")
                elif fault == "foreign-account":
                    data[0]["dhanClientId"] = "Foreign"
                elif fault == "working":
                    data[0]["orderStatus"] = "PENDING"
                elif fault in {"late-fill", "late-date"}:
                    data[0].update(orderStatus="TRADED", filledQty=1)
                elif fault == "zero-fill-conflict":
                    data[0]["quantity"] = 2
                from packages.core.core.tests.native_terminal_variants import TERMINAL_VARIANTS
                if fault in TERMINAL_VARIANTS:
                    data[0].update(TERMINAL_VARIANTS[fault][0])

        elif request.method == "GET" and path == "fundlimit":
            data = {"availabelBalance": 1000, "sodLimit": 1000, "utilizedAmount": 0}
        elif request.method == "POST" and path == "marketfeed/quote":
            assert json.loads(request.body) == {"NSE_EQ": [123], "dhanClientId": "Mounted"}
            data = {"data": {"NSE_EQ": {"123": {"last_price": 4}}}, "status": "success"}
        elif request.method == "POST" and path == "margincalculator":
            data = {"totalMargin": 4}
        elif request.method == "POST" and path == "orders":
            data = {"orderId": "synthetic-canonical-order", "orderStatus": "TRANSIT"}
            native_records.append(native_source.observe_transport(
                transport=desk.transport, native_account="Mounted", order=minted[-1][0],
                order_ids=["synthetic-canonical-order"], resources=[{
                    "native_account": "Mounted", "native_order_date_basis": "synthetic-independent-identity-day-v1",
                    "native_order_date": "2026-10-23", "segment": "NSE_EQ", "family": "ordinary",
                    "resource_id": "synthetic-canonical-order", "leg": "1", "order_id": "synthetic-canonical-order",
                    "exchange_order_id": "ExchangeOne", "filled_quantity": "0", "executions": [],
                }],
            ))
        else:
            return original_send(session, request, **kwargs)
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps(data).encode()
        return response

    monkeypatch.setattr(safety_module, "gate_order", mint)
    # The primitive source is bound to the actual transport identity. Install
    # this forwarding observer before republishing that source, not after grant.
    monkeypatch.setattr(requests.Session, "send", send)
    source, registration = _registered(desk, order=order)
    from flinttrade_gateway.native_scope_primitives import SyntheticNativeScopeSource

    dependencies = desk.app.extensions["flinttrade_broker_dependencies"]
    native_source = SyntheticNativeScopeSource(
        adapter=desk.app.config["ACTIVE_BROKER_ADAPTERS"]["dhan"], transport=desk.transport,
        reader=native_read, workspace_path=dependencies.workspace_path, label="terminal-zero-fill-synthetic-lifecycle",
    )
    # Explicit server-owned fixture dependency; retain the same managed owner
    # and every real authority/deadline/budget check in its bounded read plan.
    dependencies.read_owner._native_scope_source = native_source
    _plan(source, registration, mark="4")
    owner = _start(desk, _granted(desk))
    completed = owner.completed.wait(5)
    print("QUALIFIED_CANONICAL_PHASES " + json.dumps(phases), flush=True)
    assert completed and owner.shutdown(0)
    assert sum(phase["phase"] == "canonical_mint" for phase in phases) == 1, phases
    writes = [phase for phase in phases if phase.get("method") == "POST"
              and phase.get("url") == "https://api.dhan.co/v2/orders"]
    assert len(writes) == 1, phases
    assert writes[0]["body"] == {
        "transactionType": "BUY", "exchangeSegment": "NSE_EQ", "productType": "CNC",
        "orderType": "LIMIT", "validity": "DAY", "securityId": "123", "quantity": 1,
        "disclosedQuantity": 0, "price": 4.0, "afterMarketOrder": False,
        "boProfitValue": None, "boStopLossValue": None, "triggerPrice": 0.0, "dhanClientId": "Mounted",
    }
    typed, context, ticket = minted[0]
    assert typed.model_dump(mode="json") == registration.order
    assert context.actor_id == "bounded:mounted-native"
    assert ticket.verify(typed, context, "dhan", "Mounted")
    router = desk.app.config["BROKER_ROUTER"]
    assert type(router._consume_gate.__self__) is safety_module.SafetyGate
    before_replay = list(phases)
    assert router._consume_gate(ticket.gate_id) is False
    assert phases == before_replay
    hold = _financial(desk)["reservations"]["producer-entry"]
    assert hold["command_id"] == "decision-0" and hold["state"] != "released"
    assert owner.shutdown(0)
    assert not desk.app.config["EXECUTION_SESSIONS"].shutdown(0), "ACK is not durable duty settlement"
    # The broker independently reports a legitimate terminal lifecycle. This
    # performs no cancellation and does not restore post-Stop write authority.
    terminal = True
    import time
    from packages.core.core.tests.test_native_financial_owner import RUN, _facts, _qualify, _ref

    view = desk.client.get(RUN + "/autonomy-v2", headers=desk.headers).get_json()["data"]
    if refusal is not None:
        fault = "working" if refusal == "working-history" else refusal
        incomplete = desk.client.post(RUN + "/autonomy-v2/inspect", headers=desk.headers, json={
            "schema_version": "2", "run_id": "mounted-native",
            "expected_binding_revision": view["scope"]["binding_revision"],
            "read_plan": {"surfaces": ["orders", "positions", "holdings", "trades"],
                          "max_reads": 5 if refusal == "partial-plan" else 8, "max_pages": 1,
                          "deadline_ms": int(time.time() * 1000) + 10000},
        })
        assert incomplete.status_code == 200, incomplete.get_json()
        candidate_facts = _facts()
        candidate_facts["history_from_ms"] -= 60000
        candidate_facts["native_order_date"] = "2026-10-22" if refusal == "financial-date" else "2026-10-23"
        candidate_facts["entries"] = [{"entry_ref": _ref("producer-entry"), "lots": [],
            "remaining_possible_quantity": 0, "remaining_price_upper_bound": None, "unknown_possible_write": False,
            "mark": "4", "mark_at_ms": candidate_facts["observed_at_ms"]}]
        if refusal == "working-history":
            from packages.core.core.tests.test_native_financial_owner import _fees
            candidate_facts["entries"][0].update(remaining_possible_quantity=1, remaining_price_upper_bound="4")
            candidate_facts["fees"] = _fees(candidate_facts["entries"][0], candidate_facts["observed_at_ms"],
                                            ("entry_pending", "exit_pending"))
        source.publish("mounted-native", candidate_facts)
        refused = _qualify(desk)
        assert _financial(desk)["reservations"]["producer-entry"]["state"] == "held"
        assert refused["duty"]["obligations"]
        assert not desk.app.config["EXECUTION_SESSIONS"].shutdown(0)
        fault = None
    settlement = desk.client.post(RUN + "/autonomy-v2/inspect", headers=desk.headers, json={
        "schema_version": "2", "run_id": "mounted-native",
        "expected_binding_revision": view["scope"]["binding_revision"],
        "read_plan": {"surfaces": ["orders", "positions", "holdings", "trades"], "max_reads": 8,
                      "max_pages": 1, "deadline_ms": int(time.time() * 1000) + 10000},
    })
    assert settlement.status_code == 200, settlement.get_json()
    assert not desk.app.config["EXECUTION_SESSIONS"].shutdown(0), "financial source still missing"
    facts = _facts()
    facts["history_from_ms"] -= 60000
    facts["native_order_date"] = "2026-10-23"
    facts["entries"] = [{"entry_ref": _ref("producer-entry"), "lots": [], "remaining_possible_quantity": 0,
                         "remaining_price_upper_bound": None, "unknown_possible_write": False,
                         "mark": "4", "mark_at_ms": facts["observed_at_ms"]}]
    source.publish("mounted-native", facts)
    settled = _qualify(desk)
    print("SETTLEMENT_READ_PHASE " + json.dumps({"view": settled, "financial": _financial(desk),
                                               "phases": phases[len(before_replay):]}), flush=True)
    assert _financial(desk)["reservations"]["producer-entry"]["state"] == "released"
    assert settled["duty"]["obligations"] == []
    assert settled["entry_state"] == "retired" and settled["grant"]["state"] == "revoked"
    assert len([phase for phase in phases if phase.get("method") == "POST"
                and phase.get("url") == "https://api.dhan.co/v2/orders"]) == 1
    if after_settlement is not None:
        def capture_later(kind: str) -> Any:
            """Capture later independent inert evidence, without new financial publication."""
            nonlocal fault
            fault = kind
            native_records[0]["resources"][0]["filled_quantity"] = (
                "1" if kind in {"late-fill", "late-conflict", "late-date"} else "0")
            from packages.core.core.tests.native_terminal_variants import TERMINAL_VARIANTS
            if kind in TERMINAL_VARIANTS:
                native_records[0]["resources"][0]["filled_quantity"] = TERMINAL_VARIANTS[kind][1]
            if kind == "late-date":
                native_records[0]["resources"][0]["native_order_date"] = "2026-10-22"
            response = desk.client.post(RUN + "/autonomy-v2/inspect", headers=desk.headers, json={
                "schema_version": "2", "run_id": "mounted-native",
                "expected_binding_revision": view["scope"]["binding_revision"],
                "read_plan": {"surfaces": ["orders", "positions", "holdings", "trades"],
                              "max_reads": 8, "max_pages": 1,
                              "deadline_ms": int(time.time() * 1000) + 10000},
            })
            assert response.status_code == 200, response.get_json()
            return response.get_json()["data"]

        after_settlement(desk, capture_later)
    assert desk.app.config["EXECUTION_SESSIONS"].shutdown(1)


def test_qualified_normal_factory_producer_reaches_the_canonical_sdk(
    mounted_desk: MountedDesk, sidecar: tuple[Any, list[str]], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve sole mint/wire/replay assertions and add evidenced same-owner settlement."""
    _terminal_lifecycle_case(mounted_desk, sidecar, monkeypatch)


@pytest.mark.parametrize("refusal", ["missing-order", "missing-quantity", "foreign-account", "working",
                                    "missing-child-set", "partial-plan", "financial-date", "working-history"])
def test_bounded_settlement_retains_holds_until_complete_correspondence(
    mounted_desk: MountedDesk, sidecar: tuple[Any, list[str]], monkeypatch: pytest.MonkeyPatch, refusal: str,
) -> None:
    """Pair incomplete/conflicting observations with a genuine later terminal read."""
    _terminal_lifecycle_case(mounted_desk, sidecar, monkeypatch, refusal)
