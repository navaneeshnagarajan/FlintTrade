"""Exact reducing holds and pre-invocation refusal at the real HTTP seam."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from flinttrade_core.auth_routes import _create_token
from flinttrade_engine.reduce_only import contract_key, reserved_exit
from flinttrade_gateway.brokers.dhan import DhanAdapter
from packages.core.core.tests.test_ingress_safety_runtime import DispatchHTTP, DispatchSDK, exact_egress_latch as exact_egress_latch, route_stack as route_stack
from packages.core.core.tests.test_order_route_evidence_runtime import _place
from packages.core.core.tests.test_upstox_native_propagation import native_stack as native_stack, _place as place_upstox

pytestmark = pytest.mark.integration


@pytest.fixture
def dhan_dispatch_stack(route_stack):
    app, source, _sdk, router = route_stack
    http = DispatchHTTP("ack")
    router._adapters["dhan"] = DhanAdapter(
        client_factory=lambda _session: DispatchSDK(http), security_resolver=lambda _s, _e: "fixture-security",
    )
    key = contract_key(mode="live", adapter="dhan", account="route-account", symbol="INFY", exchange="NSE", product="MIS")
    return SimpleNamespace(app=app, source=source, router=router, http=http, key=key)


def acknowledged_row(**fields):
    return {"symbol": "INFY", "exchange": "NSE", "product": "MIS", "action": "SELL",
            "order_id": "unique-ack-1", "quantity": "4", "filled_qty": "0", "status": "OPEN",
            "pricetype": "LIMIT", "price": "100", "trigger_price": "0", **fields}


def test_exact_single_ack_is_covered_only_by_its_scoped_quantity(dhan_dispatch_stack):
    stack = dhan_dispatch_stack
    assert _place(stack.app, 4).status_code == 200
    assert reserved_exit(stack.key) == 4
    stack.source.order_rows = [acknowledged_row()]
    second = _place(stack.app, 6)
    assert second.status_code == 200, second.get_json()
    assert [payload["quantity"] for _, payload in stack.http.calls] == [4, 6]
    assert reserved_exit(stack.key) == 6


@pytest.mark.parametrize("fields", [
    {"quantity": "3"}, {"qty": "5"}, {"quantity": None}, {"filled_qty": "NaN"}, {"tradedQty": 5},
    {"filled_quantity": "1"}, {"status": "CANCELLED", "orderStatus": "OPEN"},
    {"orderid": "another-id"}, {"symbol": "TCS"}, {"exchange": "BSE"}, {"product": "CNC"},
    {"action": "BUY"}, {"account_id": "Route-Account"}, {"broker": "upstox"},
    {"status": "UNRECOGNISED"}, {"order_id": "unique-ack-1 "},
    {"status": "COMPLETE", "filled_qty": "3"}, {"status": "FILLED", "filled_qty": "0"},
])
def test_ambiguous_or_unscoped_ack_row_cannot_discharge_local_hold(dhan_dispatch_stack, fields):
    stack = dhan_dispatch_stack
    assert _place(stack.app, 4).status_code == 200
    stack.source.order_rows = [acknowledged_row(**fields)]
    second = _place(stack.app, 6)
    assert second.status_code >= 400, second.get_json()
    assert reserved_exit(stack.key) == 4
    assert len(stack.http.calls) == 1


@pytest.mark.parametrize("status", ["CANCELLED", "CANCELED", "REJECTED", "EXPIRED", "COMPLETE"])
def test_exact_terminal_ack_releases_hold_without_claiming_execution(dhan_dispatch_stack, status):
    stack = dhan_dispatch_stack
    assert _place(stack.app, 4).status_code == 200
    stack.source.position_rows[0]["net_qty"] = 6
    stack.source.position_rows[0]["quantity"] = "6"
    stack.source.order_rows = [acknowledged_row(status=status, filled_qty="4")]
    second = _place(stack.app, 6)
    assert second.status_code == 200, second.get_json()
    assert [payload["quantity"] for _, payload in stack.http.calls] == [4, 6]
    assert reserved_exit(stack.key) == 6
    assert not {"filled", "execution_confirmed", "closed"}.intersection(second.get_json())


@pytest.mark.parametrize("book", [[], None, [acknowledged_row(quantity="broken")]])
def test_disappearing_or_unavailable_exact_ack_restores_existing_local_hold(dhan_dispatch_stack, book):
    stack = dhan_dispatch_stack
    assert _place(stack.app, 4).status_code == 200
    stack.source.order_rows = [acknowledged_row()]
    # Over-cap refusal reads the exact ACK but never creates a second hold.
    assert _place(stack.app, 7).status_code >= 400
    assert reserved_exit(stack.key) == 0
    stack.source.order_rows = RuntimeError("Synthetic unreadable book") if book is None else deepcopy(book)
    second = _place(stack.app, 6)
    assert second.status_code == 409, second.get_json()
    assert reserved_exit(stack.key) == 4
    assert len(stack.http.calls) == 1


def test_read_only_router_refusal_releases_both_uninvoked_reservations(dhan_dispatch_stack):
    stack = dhan_dispatch_stack
    session = stack.app.config["REGISTRY"].get_session_for("dhan", "route-account")
    session.read_only_until_at = 4102444800.0
    response = _place(stack.app, 10)
    assert response.status_code == 403, response.get_json()
    assert response.get_json()["dispatch_outcome"] == "refused_before_dispatch"
    assert response.get_json()["retry_safe"] is False
    assert stack.http.calls == [] and reserved_exit(stack.key) == 0
    with stack.app.config["SAFETY"].order_admission("dhan:route-account") as lease:
        assert lease.reservations == ()
    session.read_only_until_at = None  # Only the explicitly synthetic session changes.
    assert _place(stack.app, 10).status_code == 200
    assert len(stack.http.calls) == 1


@pytest.mark.parametrize("account", [" route-account", "route-account ", "", None, True, {}, ["route-account"], "route account"])
@pytest.mark.parametrize("path", ["/api/v1/orders/place", "/api/v1/orders/dhan/place"])
def test_malformed_opaque_account_is_refused_before_lookup(dhan_dispatch_stack, account, path):
    stack = dhan_dispatch_stack
    response = stack.app.test_client().post(path, json={
        "broker": "dhan", "account_id": account, "symbol": "INFY", "exchange": "NSE", "product": "MIS",
        "action": "SELL", "quantity": 10, "price": 100, "pricetype": "LIMIT",
    }, headers={"Authorization": "Bearer " + _create_token("operator", mode="live", live_mode_unlocked=True)})
    assert response.status_code == 400, response.get_json()
    assert stack.source.reads == [] and stack.http.calls == []
    assert reserved_exit(stack.key) == 0


def test_multi_id_ack_does_not_invent_first_child_aggregate_coverage(native_stack):
    stack = native_stack
    first = place_upstox(stack)
    assert first.status_code == 200, first.get_json()
    assert first.get_json()["order_ids"] == ["SLICE-1", "SLICE-2"]
    key = contract_key(mode="live", adapter="upstox", account="native-account", symbol="INFY", exchange="NSE", product="MIS")
    assert reserved_exit(key) == 2
    with stack.app.config["SAFETY"].order_admission("upstox:native-account") as lease:
        assert len(lease.reservations) == 1
        # The aggregate request has no verified allocation to its first child.
        assert lease.reservations[0].broker_order_id == ""
    from packages.core.core.tests.test_order_route_evidence_runtime import _BookSource
    source = _BookSource()
    source.order_rows = [{**acknowledged_row(quantity="2"), "order_id": "SLICE-1"}]
    stack.app.config["NATIVE_ADAPTERS"] = {"upstox": source}
    second = place_upstox(stack)
    assert second.status_code == 409, second.get_json()
    assert reserved_exit(key) == 2
    assert len(stack.wire) == 1
