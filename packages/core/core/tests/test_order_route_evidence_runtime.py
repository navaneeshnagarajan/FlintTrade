"""Existing HTTP routes with the normal factory, safety gates and real router.

Only external book/SDK/HTTP transports and synthetic session lookup are injected.
These ACK-only regressions do not activate a broker or establish Stage D evidence.
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from flinttrade_core.app import create_flask_app
from flinttrade_core.auth_routes import _create_token
from flinttrade_engine.laya import DecisionStatus, process_laya
from flinttrade_engine.reduce_only import reset_reduce_only_for_tests
from flinttrade_engine.safety import SafetyConfig, SafetyGate, SafetySystem
from flinttrade_gateway.brokers._base import Session
from flinttrade_gateway.brokers.dhan import DhanAdapter
from flinttrade_gateway.router import BrokerRouter

pytestmark = pytest.mark.integration

_POSITION = {"symbol": "INFY", "exchange": "NSE", "product": "MIS", "net_qty": 10, "quantity": "10"}
_EXIT = {
    "symbol": "INFY", "exchange": "NSE", "product": "MIS", "action": "SELL",
    "order_id": "external-exit-1", "status": "OPEN", "quantity": "4", "filled_qty": "0",
}


def _headers(**claims: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {_create_token('operator', mode='live', live_mode_unlocked=True, **claims)}"}


class _BookSource:
    """The external read seam, not a pre-normalised REDUCE_ONLY_LIVE_BOOKS hook."""

    def __init__(self) -> None:
        self.position_rows: Any = [deepcopy(_POSITION)]
        self.order_rows: Any = []
        self.reads: list[tuple[str, str]] = []

    async def positions(self, session: Session) -> Any:
        self.reads.append(("positions", session.account_id))
        if isinstance(self.position_rows, Exception):
            raise self.position_rows
        return deepcopy(self.position_rows)

    async def order_book(self, session: Session) -> Any:
        self.reads.append(("order_book", session.account_id))
        if isinstance(self.order_rows, Exception):
            raise self.order_rows
        return deepcopy(self.order_rows)

    async def funds(self, _session: Session) -> dict[str, str]:
        return {"used_margin": "0", "total_balance": "1000000", "opening_risk_capital": "1000000"}

    async def trade_book(self, _session: Session) -> list[Any]:
        return []

    async def holdings(self, _session: Session) -> list[Any]:
        return []

    async def quotes(self, _session: Session, symbols: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "exchange": name.split(":", 1)[0], "symbol": name.split(":", 1)[1], "ltp": 100,
                "prev_close": 100, "previous_close_trusted": True,
            }
            for name in symbols
        ]

    async def margin_calculator(self, _session: Session, _orders: list[Any]) -> dict[str, str]:
        return {"required_margin": "100"}


class _DhanSDK:
    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []

    def place_order(self, **fields: Any) -> dict[str, Any]:
        self.writes.append(deepcopy(fields))
        return {"status": "success", "data": {"orderId": "test-place-1"}}


@pytest.fixture
def route_stack(backend_lease_factory):
    reset_reduce_only_for_tests()
    safety = SafetySystem(SafetyConfig(check_market_hours=False))
    app = create_flask_app(safety=safety, safety_config_ready=True, backend_lease_proof=backend_lease_factory())
    app.config["TESTING"] = True
    sdk = _DhanSDK()
    adapter = DhanAdapter(
        client_factory=lambda _session: sdk, security_resolver=lambda _symbol, _exchange: "test-security",
    )
    source = _BookSource()
    session = Session("synthetic", 4102444800.0, "route-account", "dhan")

    def session_for(_ctx: Any, broker: str, account: str) -> Session:
        assert (broker, account) == ("dhan", "route-account")
        return session

    router = BrokerRouter(
        {"dhan": adapter}, session_for, consume_gate=SafetyGate().consume,
        backend_lease_proof=backend_lease_factory(),
    )
    app.config["BROKER_ROUTER"] = router
    app.config["NATIVE_ADAPTERS"] = {"dhan": source}
    app.config["REGISTRY"] = SimpleNamespace(get_session_for=lambda broker, account: session_for(None, broker, account))
    yield app, source, sdk, router
    router.revoke_and_drain(timeout=0.0)
    reset_reduce_only_for_tests()


def _place(app, quantity: int = 6):
    return app.test_client().post(
        "/api/v1/orders/place",
        json={
            "broker": "dhan", "account_id": "route-account", "symbol": "INFY", "exchange": "NSE",
            "action": "SELL", "quantity": quantity, "price": 100, "product": "MIS", "order_type": "LIMIT",
        },
        headers=_headers(),
    )


def test_raw_missing_exit_quantity_cannot_mint_reduce_only_admission(route_stack) -> None:
    app, source, sdk, _router = route_stack
    missing = deepcopy(_EXIT)
    del missing["quantity"]
    source.order_rows = {"data": [missing]}
    assert process_laya().status is DecisionStatus.DOWN

    response = _place(app)

    assert process_laya().decision_log() == ()
    assert response.status_code == 403, response.get_json()
    assert response.get_json()["code"] == "laya_denied"
    assert sdk.writes == []
    assert source.reads == [("positions", "route-account"), ("order_book", "route-account")]


@pytest.mark.parametrize(
    "changes",
    [
        {"quantity": "4.9"}, {"quantity": True}, {"quantity": "NaN"}, {"quantity": "9007199254740993"},
        {"qty": "5"}, {"filled_qty": "broken"}, {"filled_qty": "0.9"}, {"filled_quantity": "1"},
        {"status": "COMPLETE", "order_status": "OPEN"}, {"orderid": "different-exit"},
        {"action": "BUY", "transaction_type": "SELL"}, {"action": "UNKNOWN"},
        {"symbol": "TCS", "trading_symbol": "INFY"},
    ],
)
def test_raw_exit_alias_or_quantity_ambiguity_cannot_record_reduction(route_stack, changes) -> None:
    app, source, sdk, _router = route_stack
    source.order_rows = {"data": [{**_EXIT, **changes}]}

    response = _place(app)

    assert process_laya().decision_log() == ()
    assert response.status_code == 403, response.get_json()
    assert response.get_json()["code"] == "laya_denied"
    assert sdk.writes == []


@pytest.mark.parametrize(
    "changes",
    [
        {"net_qty": "10.9"}, {"net_qty": "NaN"}, {"net_qty": True}, {"quantity": 11},
        {"netQty": "11"}, {"symbol": "TCS", "trading_symbol": "INFY"},
        {"side": "BUY", "action": "SELL"},
    ],
)
def test_raw_position_ambiguity_cannot_record_reduction(route_stack, changes) -> None:
    app, source, sdk, _router = route_stack
    source.position_rows = {"data": [{**_POSITION, **changes}]}

    response = _place(app)

    assert process_laya().decision_log() == ()
    assert response.status_code == 403, response.get_json()
    assert response.get_json()["code"] == "laya_denied"
    assert sdk.writes == []


@pytest.mark.parametrize(
    "orders,quantity",
    [
        ([], 10), ([deepcopy(_EXIT)], 6),
        ([{**_EXIT, "qty": "4", "filled_quantity": "0", "orderid": "external-exit-1", "order_status": "OPEN"}], 6),
    ],
)
def test_valid_raw_books_reach_real_gate_router_and_sdk_as_ack_only(route_stack, orders, quantity) -> None:
    app, source, sdk, _router = route_stack
    source.order_rows = orders
    over = _place(app, quantity + 1)
    assert over.status_code == 403, over.get_json()
    assert over.get_json()["code"] == "laya_denied"
    assert sdk.writes == []
    assert process_laya().decision_log() == ()

    response = _place(app, quantity)

    assert response.status_code == 200, response.get_json()
    assert len(sdk.writes) == 1
    assert sdk.writes[0]["quantity"] == quantity
    assert sdk.writes[0]["transaction_type"] == "SELL"
    assert process_laya().decision_log()[-1].proof_kind == "reduce_only"
    assert source.position_rows == [_POSITION]
    assert "filled" not in response.get_json()


class _UpstoxSDK:
    def __init__(self) -> None:
        self.writes: list[tuple[Any, Any]] = []

    def exit_positions(self, tag, segment) -> dict[str, Any]:
        self.writes.append((tag, segment))
        return {
            "status": "success", "data": {"order_ids": []}, "errors": None,
            "summary": {"total": 0, "success": 0, "error": 0},
        }


@pytest.fixture
def exit_route_stack(route_stack, backend_lease_factory):
    from flinttrade_gateway.brokers.upstox import UpstoxAdapter

    app, source, _sdk, _old_router = route_stack
    sdk = _UpstoxSDK()
    adapter = UpstoxAdapter(client_factory=lambda _session: sdk)
    session = Session("synthetic", 4102444800.0, "route-account", "upstox")

    def session_for(_ctx, broker, account):
        assert (broker, account) == ("upstox", "route-account")
        return session

    router = BrokerRouter(
        {"upstox": adapter}, session_for, consume_gate=SafetyGate().consume,
        backend_lease_proof=backend_lease_factory(),
    )
    app.config["BROKER_ROUTER"] = router
    app.config["NATIVE_ADAPTERS"] = {"upstox": source}
    app.config["REGISTRY"] = SimpleNamespace(get_session_for=lambda broker, account: session_for(None, broker, account))
    yield app, source, sdk
    router.revoke_and_drain(timeout=0.0)


def _exit_all(app):
    return app.test_client().post(
        "/api/v1/positions/exit-all",
        json={"confirm": True, "broker": "upstox", "account_id": "route-account"}, headers=_headers(),
    )


@pytest.mark.parametrize("via_hook", [False, True], ids=["native-source", "book-hook"])
@pytest.mark.parametrize(
    "positions",
    [
        RuntimeError("book unavailable"), None, {}, {"data": None}, {"data": {}}, [None],
        {"status": "error", "data": []}, {"success": False, "data": []}, {"data": [], "error": "unavailable"},
        [deepcopy(_POSITION), "broken"],
        [{"symbol": "INFY", "exchange": "NSE", "product": "MIS"}],
        [{**_POSITION, "net_qty": "broken"}], [{**_POSITION, "net_qty": "0.9", "quantity": "0.9"}],
        [{**_POSITION, "net_qty": 0}],
    ],
)
def test_exit_all_cannot_prove_flatness_from_unavailable_or_malformed_positions(
    exit_route_stack, positions, via_hook,
) -> None:
    app, source, sdk = exit_route_stack
    source.position_rows = positions
    if via_hook:
        def books(_broker, _account):
            if isinstance(positions, Exception):
                raise positions
            return deepcopy(positions), [], []
        app.config["REDUCE_ONLY_LIVE_BOOKS"] = books

    response = _exit_all(app)

    assert process_laya().decision_log() == ()
    assert response.status_code in {409, 503}, response.get_json()
    assert sdk.writes == []


@pytest.mark.parametrize("positions", [{"data": []}, [{**_POSITION, "net_qty": 0, "quantity": "0"}]])
def test_exit_all_known_empty_positions_remain_deliberate_gated_ack_only(exit_route_stack, positions) -> None:
    app, source, sdk = exit_route_stack
    source.position_rows = deepcopy(positions)

    response = _exit_all(app)

    assert response.status_code == 200, response.get_json()
    assert sdk.writes == [(None, None)]
    proof = process_laya().decision_log()
    assert len(proof) == 1
    assert proof[0].proof_kind == "reduce_only"
    assert proof[0].quantity == 0
    assert source.position_rows == positions
    assert response.get_json()["data"]["order_ids"] == []
    assert "closed" not in response.get_json()


class _SmartTransport:
    def __init__(self, broker: str) -> None:
        self.broker = broker
        self.writes: list[dict[str, Any]] = []

    def __call__(self, method, url, *, headers, params=None, json_body=None):
        from urllib.parse import urlsplit

        path = urlsplit(url).path
        self.writes.append({"method": method, "path": path, "params": params, "body": deepcopy(json_body)})
        if self.broker == "groww":
            assert method == "POST" and path.startswith("/v1/order-advance/cancel/")
            assert params is None and json_body is None
            order_id = path.rsplit("/", 1)[1]
            return 200, {"status": "SUCCESS", "payload": {"smart_order_id": order_id}}
        assert method == "POST" and path == "/smart/order/cancel"
        return 200, {"status": "success"}


@pytest.fixture
def smart_route_stack(route_stack, backend_lease_factory):
    from flinttrade_gateway.brokers.groww import GrowwAdapter
    from flinttrade_gateway.brokers.indmoney import IndMoneyAdapter

    app, _source, _sdk, _old_router = route_stack
    groww = _SmartTransport("groww")
    indmoney = _SmartTransport("indmoney")
    sessions = {
        broker: Session("synthetic", 4102444800.0, "smart-account", broker)
        for broker in ("groww", "indmoney")
    }
    lookups = []

    def session_for(ctx, broker, account):
        lookups.append((ctx.selector, broker, account))
        if account != "smart-account":
            raise KeyError("unavailable synthetic account")
        return sessions[broker]

    router = BrokerRouter(
        {"groww": GrowwAdapter(http_factory=lambda: groww), "indmoney": IndMoneyAdapter(http_factory=lambda: indmoney)},
        session_for, consume_gate=SafetyGate().consume, backend_lease_proof=backend_lease_factory(),
    )
    app.config["BROKER_ROUTER"] = router
    yield app, groww, indmoney, lookups, router
    router.revoke_and_drain(timeout=0.0)


@pytest.mark.parametrize("segment,family", [("FNO", "OCO"), ("CASH", "GTT"), ("CASH", "OCO"), ("FNO", "GTT")])
def test_groww_smart_cancel_keeps_signed_native_family_segment_and_exact_target(
    smart_route_stack, segment, family,
) -> None:
    app, groww, indmoney, lookups, _router = smart_route_stack

    response = app.test_client().delete(
        "/api/v1/orders/smart/opaque-parent-1",
        query_string={
            "broker": "groww", "account_id": "smart-account", "segment": segment, "smart_order_type": family,
        },
        headers=_headers(),
    )

    assert response.status_code == 200, response.get_json()
    assert groww.writes == [{
        "method": "POST", "path": f"/v1/order-advance/cancel/{segment}/{family}/opaque-parent-1",
        "params": None, "body": None,
    }]
    assert indmoney.writes == []
    assert lookups == [("groww:smart-account", "groww", "smart-account")]
    assert response.get_json()["orderid"] == "opaque-parent-1"
    assert "filled" not in response.get_json() and "closed" not in response.get_json()


@pytest.mark.parametrize(
    "context",
    [
        {}, {"segment": "FNO"}, {"smart_order_type": "OCO"},
        {"segment": "EQUITY", "smart_order_type": "OCO"},
        {"segment": "DERIVATIVE", "smart_order_type": "GTT"},
        {"segment": "COMMODITY", "smart_order_type": "OCO"},
        {"segment": "FNO", "smart_order_type": "UNKNOWN"},
        {"segment": "FNO", "smart_order_type": "oco"},
        {"segment": None, "smart_order_type": "OCO"},
        {"segment": "FNO", "smart_order_type": None},
        {"segment": True, "smart_order_type": "OCO"},
        {"segment": "FNO", "smart_order_type": 1},
        {"segment": " FNO", "smart_order_type": "OCO"},
    ],
)
def test_groww_smart_cancel_missing_or_wrong_native_context_never_reaches_transport(
    smart_route_stack, context,
) -> None:
    app, groww, indmoney, _lookups, _router = smart_route_stack

    response = app.test_client().delete(
        "/api/v1/orders/smart/opaque-parent-1",
        json={"broker": "groww", "account_id": "smart-account", **context}, headers=_headers(),
    )

    assert response.status_code == 403, response.get_json()
    assert groww.writes == [] and indmoney.writes == []


@pytest.mark.parametrize("order_id", ["parent.1", "parent%20id", "parent%3Fother", "parent%25id", "parent%C3%A9"])
def test_groww_smart_cancel_unsafe_resource_id_never_reaches_transport(smart_route_stack, order_id) -> None:
    app, groww, indmoney, _lookups, _router = smart_route_stack

    response = app.test_client().delete(
        f"/api/v1/orders/smart/{order_id}",
        json={"broker": "groww", "account_id": "smart-account", "segment": "FNO", "smart_order_type": "OCO"},
        headers=_headers(),
    )

    assert response.status_code == 403, response.get_json()
    assert groww.writes == [] and indmoney.writes == []


@pytest.mark.parametrize("segment,order_id", [("EQUITY", "EQ-1"), ("DERIVATIVE", "DRV-1"), (None, "EQ-1")])
def test_indstocks_smart_cancel_keeps_its_existing_native_segment_contract(
    smart_route_stack, segment, order_id,
) -> None:
    app, groww, indmoney, lookups, _router = smart_route_stack
    fields = {"broker": "indmoney", "account_id": "smart-account"}
    if segment is not None:
        fields["segment"] = segment

    response = app.test_client().delete(f"/api/v1/orders/smart/{order_id}", json=fields, headers=_headers())

    assert response.status_code == 200, response.get_json()
    assert indmoney.writes == [{
        "method": "POST", "path": "/smart/order/cancel", "params": None,
        "body": {"order_id": order_id, "segment": segment or "EQUITY"},
    }]
    assert groww.writes == []
    assert lookups == [("indmoney:smart-account", "indmoney", "smart-account")]


@pytest.mark.parametrize(
    "context", [{"segment": "CASH"}, {"segment": "FNO"}, {"segment": "DERIVATIVE", "smart_order_type": "OCO"}],
)
def test_indstocks_cannot_inherit_groww_smart_cancel_context(smart_route_stack, context) -> None:
    app, groww, indmoney, _lookups, _router = smart_route_stack

    response = app.test_client().delete(
        "/api/v1/orders/smart/DRV-1", json={"broker": "indmoney", "account_id": "smart-account", **context},
        headers=_headers(),
    )

    assert response.status_code == 403, response.get_json()
    assert groww.writes == [] and indmoney.writes == []


@pytest.mark.parametrize("field", ["order_id", "segment", "smart_order_type", "account_id", "adapter_id"])
def test_route_minted_smart_cancel_refuses_signed_field_or_target_tampering(
    smart_route_stack, monkeypatch, field,
) -> None:
    from dataclasses import replace
    import flinttrade_engine.safety as gates

    app, groww, indmoney, _lookups, _router = smart_route_stack
    real_gate = gates.gate_broker_write
    replacements = {
        "order_id": "different-parent", "segment": "CASH", "smart_order_type": "GTT",
        "account_id": "other-account", "adapter_id": "indmoney",
    }

    def mint_then_tamper(verb, payload, context, broker, **kwargs):
        proof = real_gate(verb, payload, context, broker, **kwargs)
        if field in {"account_id", "adapter_id"}:
            return replace(proof, **{field: replacements[field]})
        payload[field] = replacements[field]
        return proof

    monkeypatch.setattr(gates, "gate_broker_write", mint_then_tamper)
    response = app.test_client().delete(
        "/api/v1/orders/smart/opaque-parent-1",
        json={"broker": "groww", "account_id": "smart-account", "segment": "FNO", "smart_order_type": "OCO"},
        headers=_headers(),
    )

    assert response.status_code == 403, response.get_json()
    assert groww.writes == [] and indmoney.writes == []


def test_route_minted_smart_cancel_context_is_consumed_once(smart_route_stack, monkeypatch) -> None:
    import asyncio
    import flinttrade_engine.safety as gates
    from flinttrade_core.exceptions import SafetyBypassError
    from flinttrade_gateway.routing_config import RoutingHint

    app, groww, indmoney, _lookups, router = smart_route_stack
    real_gate = gates.gate_broker_write
    minted = []

    def observe_gate(verb, payload, context, broker, **kwargs):
        proof = real_gate(verb, payload, context, broker, **kwargs)
        minted.append((verb, deepcopy(payload), context, proof))
        return proof

    monkeypatch.setattr(gates, "gate_broker_write", observe_gate)
    response = app.test_client().delete(
        "/api/v1/orders/smart/opaque-parent-1",
        json={"broker": "groww", "account_id": "smart-account", "segment": "FNO", "smart_order_type": "OCO"},
        headers=_headers(),
    )
    assert response.status_code == 200, response.get_json()
    assert len(minted) == 1
    verb, payload, context, proof = minted[0]
    assert payload == {
        "_op": "cancel_smart_order", "order_id": "opaque-parent-1", "segment": "FNO", "smart_order_type": "OCO",
    }
    assert proof.account_id == "smart-account" and proof.adapter_id == "groww"
    with pytest.raises(SafetyBypassError):
        asyncio.run(router.execute_gated(
            context, verb=verb, payload=payload, safety_ctx=proof,
            hint=RoutingHint(adapter_id="groww", account_id="smart-account"),
        ))
    assert len(groww.writes) == 1
    assert indmoney.writes == []


@pytest.mark.parametrize(
    "query,body",
    [
        ({}, {"order_id": "different-parent"}),
        ({"segment": "CASH"}, {}),
        ({"smart_order_type": "GTT"}, {}),
        ({"broker": "indmoney"}, {}),
        ({"account_id": "different-account"}, {}),
    ],
)
def test_smart_cancel_conflicting_address_evidence_is_not_last_value_wins(smart_route_stack, query, body) -> None:
    app, groww, indmoney, lookups, _router = smart_route_stack

    response = app.test_client().delete(
        "/api/v1/orders/smart/opaque-parent-1", query_string=query,
        json={"broker": "groww", "account_id": "smart-account", "segment": "FNO", "smart_order_type": "OCO", **body},
        headers=_headers(),
    )

    assert response.status_code == 400, response.get_json()
    assert groww.writes == [] and indmoney.writes == []
    assert lookups == []


@pytest.mark.parametrize(
    "bad_field", ["missing-order-quantity", "fractional-order-quantity", "fractional-position-quantity"],
)
def test_production_native_book_reader_keeps_invalid_reduction_evidence_refused(route_stack, bad_field) -> None:
    app, _source, writer_sdk, _router = route_stack
    native_position = {
        "tradingSymbol": "INFY", "exchangeSegment": "NSE_EQ", "productType": "INTRADAY", "netQty": "10",
    }
    native_order = {
        "orderId": "external-exit-1", "orderStatus": "PENDING", "tradingSymbol": "INFY",
        "exchangeSegment": "NSE_EQ", "transactionType": "SELL", "productType": "INTRADAY",
        "orderType": "LIMIT", "quantity": "4", "filledQty": "0", "price": "100",
    }
    if bad_field == "missing-order-quantity":
        del native_order["quantity"]
    elif bad_field == "fractional-order-quantity":
        native_order["quantity"] = "4.9"
    else:
        native_position["netQty"] = "10.9"
    reads = []

    class NativeSDK:
        def get_positions(self):
            reads.append("positions")
            return {"status": "success", "data": [deepcopy(native_position)]}

        def get_order_list(self):
            reads.append("orders")
            return {"status": "success", "data": [deepcopy(native_order)]}

    reader = DhanAdapter(client_factory=lambda _session: NativeSDK())
    app.config["NATIVE_ADAPTERS"] = {"dhan": reader}

    response = _place(app)

    assert response.status_code == 403, response.get_json()
    assert response.get_json()["code"] == "laya_denied"
    assert process_laya().decision_log() == ()
    assert writer_sdk.writes == []
    assert reads == ["positions", "orders"]


@pytest.mark.parametrize("typed", [False, True])
def test_valid_singleton_position_and_order_rows_are_not_discarded(route_stack, typed) -> None:
    app, source, sdk, _router = route_stack
    source.position_rows = SimpleNamespace(**_POSITION) if typed else deepcopy(_POSITION)
    source.order_rows = SimpleNamespace(**_EXIT) if typed else deepcopy(_EXIT)

    response = _place(app, 6)

    assert response.status_code == 200, response.get_json()
    assert len(sdk.writes) == 1 and sdk.writes[0]["quantity"] == 6
    assert process_laya().decision_log()[-1].proof_kind == "reduce_only"


def test_partial_exit_remaining_is_capped_against_current_exposure_once(route_stack) -> None:
    app, source, sdk, _router = route_stack
    source.position_rows = [{**_POSITION, "net_qty": 6, "quantity": "6"}]
    source.order_rows = [{**_EXIT, "filled_qty": "2"}]
    over = _place(app, 5)
    assert over.status_code == 403 and over.get_json()["code"] == "laya_denied"
    assert sdk.writes == [] and process_laya().decision_log() == ()

    response = _place(app, 4)

    assert response.status_code == 200, response.get_json()
    assert sdk.writes[0]["quantity"] == 4
    assert source.position_rows[0]["net_qty"] == 6


@pytest.mark.parametrize("orders", [RuntimeError("orders unavailable"), None, {"data": None}, [deepcopy(_EXIT), None]])
def test_unavailable_or_partial_live_order_book_never_qualifies_as_empty(route_stack, orders) -> None:
    app, source, sdk, _router = route_stack
    source.order_rows = orders

    response = _place(app, 10)

    assert response.status_code == 403 and response.get_json()["code"] == "laya_denied"
    assert sdk.writes == [] and process_laya().decision_log() == ()


@pytest.mark.parametrize(
    "target",
    [{"broker": "groww"}, {"account_id": "smart-account"}, {"broker": "groww", "account_id": "unknown-account"}],
)
def test_smart_cancel_missing_or_unknown_target_cannot_reach_another_account(smart_route_stack, target) -> None:
    app, groww, indmoney, _lookups, _router = smart_route_stack

    response = app.test_client().delete(
        "/api/v1/orders/smart/opaque-parent-1",
        json={**target, "segment": "FNO", "smart_order_type": "OCO"}, headers=_headers(),
    )

    assert response.status_code == 503, response.get_json()
    assert groww.writes == [] and indmoney.writes == []


def test_missing_filled_evidence_counts_the_full_exit_and_cannot_bypass_full_safety(route_stack) -> None:
    app, source, sdk, _router = route_stack
    source.order_rows = [{name: value for name, value in _EXIT.items() if name != "filled_qty"}]
    over = _place(app, 7)
    assert over.status_code == 403 and over.get_json()["code"] == "laya_denied"
    assert sdk.writes == [] and process_laya().decision_log() == ()

    response = _place(app, 6)

    assert response.status_code == 503, response.get_json()
    assert response.get_json()["message"] == "Order safety state unavailable; no order was sent."
    assert process_laya().decision_log()[-1].quantity == 6
    assert process_laya().decision_log()[-1].proof_kind == "reduce_only"
    assert sdk.writes == []
