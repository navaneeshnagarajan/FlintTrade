"""Extended gated broker-verb routes (contract §8.1) — HTTP surface.

Covers the routes that expose ``BrokerRouter.execute_gated``'s 12-verb table:

- ``/api/v1/orders/forever`` (place via the gated trio with ``variety="gtt"``,
  modify/cancel via ``modify_forever`` / ``cancel_forever``, plus the listing)
- ``/api/v1/orders/super`` (list / ``modify_super_order`` / ``cancel_super_order``)
- ``/api/v1/orders/triggers`` (conditional trigger place/modify/cancel/list)
- ``/api/v1/orders/multi`` (``place_multi_order``) and the gated
  ``cancel-all`` hook for explicitly-named native brokers
- ``/api/v1/orders/smart/<id>`` (``cancel_smart_order``)
- ``/api/v1/positions/convert`` + ``/api/v1/positions/exit-all`` (operator
  confirmation required) on the operations blueprint
- the Kotak Neo ``variety``/``amo`` cancel extras signed into the fingerprint

Per route: happy path (mocked router), mode-guard rejection (Practice JWT),
missing JWT, 501 for an unsupported broker, malformed body → 400, and the
exit-all explicit-confirmation refusal. Mirrors the fixture idiom of
``test_order_routes_routed.py`` (minimal Flask app + mocked BrokerRouter; the
JWT secret is process-global, so no app context is needed to mint tokens).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from flask import Flask

from flinttrade_core.auth_routes import _create_token
from flinttrade_core.exceptions import SafetyBypassError, UnsupportedCapabilityError
from flinttrade_core.operations_routes import operations_bp
from flinttrade_core.order_routes import orders_bp
from flinttrade_engine.safety import set_safety_gate_secret

pytestmark = pytest.mark.unit

_SECRET = b"0123456789abcdef0123456789abcdef"  # 32 bytes


@pytest.fixture(autouse=True)
def _bind_secret() -> None:
    """Bind a deterministic safety-gate secret so gate_broker_write can mint."""
    set_safety_gate_secret(_SECRET)


def _app(broker_router: object | None = None, safety: object | None = None) -> Flask:
    app = Flask(__name__)
    app.config["BROKER_ROUTER"] = broker_router
    app.config["SAFETY"] = safety
    app.register_blueprint(orders_bp)
    app.register_blueprint(operations_bp)
    return app


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _live_headers() -> dict[str, str]:
    return _headers(_create_token("nava", mode="live", live_mode_unlocked=True))


def _locked_live_headers() -> dict[str, str]:
    return _headers(_create_token("nava", mode="live", live_mode_unlocked=False))


def _practice_headers() -> dict[str, str]:
    return _headers(_create_token("nava", mode="practice"))


def _passing_safety() -> MagicMock:
    """A SafetySystem stub whose check_order and kill switch both pass."""
    safety = MagicMock()
    safety.check_order.return_value = []
    safety.l5_kill.validate.return_value = MagicMock(passed=True)
    return safety


def _gated_router(result: Any = {"status": "ok"}) -> MagicMock:
    router = MagicMock()
    router.execute_gated = AsyncMock(return_value=result)
    return router


# ---------------------------------------------------------------------------
# Forever (GTT) — place via the trio, modify/cancel via execute_gated, list
# ---------------------------------------------------------------------------


def test_forever_place_routes_variety_gtt_with_oco_fields() -> None:
    """POST /forever rides the gated place trio with variety="gtt" + OCO legs."""
    router = MagicMock()
    router.place_order = AsyncMock(return_value="GTT-77")
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    body = {
        "symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 1,
        "pricetype": "LIMIT", "price": "2900", "trigger_price": "2890",
        "product": "CNC", "validity": "DAY",
        "price1": "2800", "trigger_price1": "2805", "quantity1": "5",
        "broker": "dhan",
    }
    resp = client.post("/api/v1/orders/forever", json=body, headers=_live_headers())
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "success"
    kw = router.place_order.await_args.kwargs
    order = kw["order"]
    assert order.variety == "gtt"
    assert order.validity == "DAY"
    assert (order.price1, order.trigger_price1, order.quantity1) == ("2800", "2805", "5")
    assert kw["hint"].adapter_id == "dhan"


def test_forever_place_practice_jwt_rejected() -> None:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="X")
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post(
        "/api/v1/orders/forever", json={"symbol": "RELIANCE", "action": "BUY"},
        headers=_practice_headers(),
    )
    assert resp.status_code == 403
    assert "live mode only" in resp.get_json()["message"].lower()
    router.place_order.assert_not_called()


def test_forever_place_requires_auth() -> None:
    client = _app(broker_router=_gated_router()).test_client()
    resp = client.post("/api/v1/orders/forever", json={"symbol": "RELIANCE"})
    assert resp.status_code == 401


def test_forever_place_locked_live_jwt_rejected() -> None:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="X")
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post(
        "/api/v1/orders/forever", json={"symbol": "RELIANCE", "action": "BUY"},
        headers=_locked_live_headers(),
    )
    assert resp.status_code == 403
    assert "not unlocked" in resp.get_json()["message"].lower()
    router.place_order.assert_not_called()


def test_forever_place_malformed_body_returns_400() -> None:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="X")
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post(
        "/api/v1/orders/forever",
        json={"symbol": "RELIANCE", "action": "SIDEWAYS", "broker": "dhan"},
        headers=_live_headers(),
    )
    assert resp.status_code == 400
    router.place_order.assert_not_called()


def test_forever_modify_happy_path_mints_and_dispatches() -> None:
    router = _gated_router()
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.put(
        "/api/v1/orders/forever/GTT-1",
        json={"changes": {"price": "2900"}, "broker": "dhan", "account_id": "personal"},
        headers=_live_headers(),
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["orderid"] == "GTT-1"
    kw = router.execute_gated.await_args.kwargs
    assert kw["verb"] == "modify_forever"
    assert kw["payload"]["_op"] == "modify_forever"
    assert kw["payload"]["order_id"] == "GTT-1"
    assert kw["payload"]["changes"] == {"price": "2900"}
    assert kw["hint"].adapter_id == "dhan"
    assert kw["hint"].account_id == "personal"
    # The minted context is bound to the SAME payload object the router gets.
    assert kw["safety_ctx"] is not None


def test_forever_modify_missing_changes_returns_400() -> None:
    router = _gated_router()
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.put(
        "/api/v1/orders/forever/GTT-1", json={"broker": "dhan"}, headers=_live_headers()
    )
    assert resp.status_code == 400
    router.execute_gated.assert_not_called()


def test_forever_modify_practice_jwt_rejected() -> None:
    router = _gated_router()
    client = _app(broker_router=router).test_client()
    resp = client.put(
        "/api/v1/orders/forever/GTT-1", json={"changes": {"price": "1"}},
        headers=_practice_headers(),
    )
    assert resp.status_code == 403
    router.execute_gated.assert_not_called()


def test_forever_modify_kill_switch_blocks() -> None:
    """A latched L5 kill switch blocks risk-increasing gated writes."""
    safety = MagicMock()
    blocked = MagicMock(passed=False, layer="L5_KILL", reason="Kill switch is active")
    safety.l5_kill.validate.return_value = blocked
    router = _gated_router()
    client = _app(broker_router=router, safety=safety).test_client()
    resp = client.put(
        "/api/v1/orders/forever/GTT-1",
        json={"changes": {"price": "2900"}, "broker": "dhan"},
        headers=_live_headers(),
    )
    assert resp.status_code == 403
    assert "L5_KILL" in resp.get_json()["message"]
    router.execute_gated.assert_not_called()


def test_forever_cancel_happy_path() -> None:
    router = _gated_router(result=None)
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.delete(
        "/api/v1/orders/forever/GTT-9?broker=dhan", headers=_live_headers()
    )
    assert resp.status_code == 200
    kw = router.execute_gated.await_args.kwargs
    assert kw["verb"] == "cancel_forever"
    assert kw["payload"] == {"_op": "cancel_forever", "order_id": "GTT-9"}


def test_forever_cancel_not_blocked_by_kill_switch() -> None:
    """Cancels reduce exposure — a halted account must still be able to cancel."""
    safety = MagicMock()
    safety.l5_kill.validate.return_value = MagicMock(passed=False, layer="L5_KILL", reason="halted")
    router = _gated_router(result=None)
    client = _app(broker_router=router, safety=safety).test_client()
    resp = client.delete("/api/v1/orders/forever/GTT-9?broker=dhan", headers=_live_headers())
    assert resp.status_code == 200
    router.execute_gated.assert_awaited_once()


def test_forever_unsupported_broker_returns_501() -> None:
    router = MagicMock()
    router.execute_gated = AsyncMock(
        side_effect=UnsupportedCapabilityError("broker adapter 'kotakneo' does not support 'modify_forever'")
    )
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.put(
        "/api/v1/orders/forever/GTT-1",
        json={"changes": {"price": "2900"}, "broker": "kotakneo"},
        headers=_live_headers(),
    )
    assert resp.status_code == 501
    assert "modify_forever" in resp.get_json()["message"]


def test_gated_write_no_router_returns_503() -> None:
    client = _app(broker_router=None, safety=_passing_safety()).test_client()
    resp = client.put(
        "/api/v1/orders/forever/GTT-1", json={"changes": {"price": "1"}},
        headers=_live_headers(),
    )
    assert resp.status_code == 503
    assert "routing unavailable" in resp.get_json()["message"].lower()


def test_gated_write_acl_refusal_returns_403() -> None:
    router = MagicMock()
    router.execute_gated = AsyncMock(side_effect=SafetyBypassError("actor not authorised"))
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.delete("/api/v1/orders/forever/GTT-1?broker=dhan", headers=_live_headers())
    assert resp.status_code == 403
    assert "refused" in resp.get_json()["message"].lower()


# ---------------------------------------------------------------------------
# Reads — forever/super/trigger listings via the ACL'd session path
# ---------------------------------------------------------------------------


class _ReadAdapter:
    """Fake adapter exposing the three listing reads."""

    async def forever_orders(self, session: object) -> list[dict[str, Any]]:
        return [{"order_id": "GTT-1", "status": "PENDING"}]

    async def super_orders(self, session: object) -> list[dict[str, Any]]:
        return [{"order_id": "SUP-1"}]

    async def conditional_triggers(self, session: object) -> list[dict[str, Any]]:
        return [{"alert_id": "AL-1"}]


class _ReadRouter:
    """Router stub exposing the read path the routes mirror (provider + adapters)."""

    def __init__(self, adapter: object, *, provider_exc: Exception | None = None) -> None:
        self._adapters = {"dhan": adapter}
        self._provider_exc = provider_exc

    def _session_provider(self, request_ctx: object, adapter_id: str, account_id: str) -> object:
        if self._provider_exc is not None:
            raise self._provider_exc
        return object()


def test_forever_list_happy_path() -> None:
    client = _app(broker_router=_ReadRouter(_ReadAdapter())).test_client()
    resp = client.get("/api/v1/orders/forever?broker=dhan", headers=_live_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"] == [{"order_id": "GTT-1", "status": "PENDING"}]


def test_super_list_happy_path() -> None:
    client = _app(broker_router=_ReadRouter(_ReadAdapter())).test_client()
    resp = client.get("/api/v1/orders/super?broker=dhan", headers=_live_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"] == [{"order_id": "SUP-1"}]


def test_trigger_list_happy_path() -> None:
    client = _app(broker_router=_ReadRouter(_ReadAdapter())).test_client()
    resp = client.get("/api/v1/orders/triggers?broker=dhan", headers=_live_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"] == [{"alert_id": "AL-1"}]


def test_list_unsupported_adapter_returns_501() -> None:
    """An adapter without the listing (e.g. the OpenAlgo bridge) 501s cleanly."""

    class _Bare:
        pass

    client = _app(broker_router=_ReadRouter(_Bare())).test_client()
    resp = client.get("/api/v1/orders/forever?broker=dhan", headers=_live_headers())
    assert resp.status_code == 501
    assert "forever_orders" in resp.get_json()["message"]


def test_list_acl_refusal_returns_403() -> None:
    router = _ReadRouter(_ReadAdapter(), provider_exc=SafetyBypassError("actor not authorised"))
    client = _app(broker_router=router).test_client()
    resp = client.get("/api/v1/orders/forever?broker=dhan", headers=_live_headers())
    assert resp.status_code == 403


def test_list_unknown_broker_returns_503() -> None:
    from flinttrade_gateway.exceptions import BrokerNotFoundError

    router = _ReadRouter(_ReadAdapter(), provider_exc=BrokerNotFoundError("no session"))
    client = _app(broker_router=router).test_client()
    resp = client.get("/api/v1/orders/forever?broker=upstox", headers=_live_headers())
    assert resp.status_code == 503
    assert "not connected" in resp.get_json()["message"].lower()


def test_list_practice_jwt_rejected() -> None:
    client = _app(broker_router=_ReadRouter(_ReadAdapter())).test_client()
    resp = client.get("/api/v1/orders/forever?broker=dhan", headers=_practice_headers())
    assert resp.status_code == 403


def test_list_requires_auth() -> None:
    client = _app(broker_router=_ReadRouter(_ReadAdapter())).test_client()
    resp = client.get("/api/v1/orders/forever?broker=dhan")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Super orders — modify / cancel (leg-aware)
# ---------------------------------------------------------------------------


def test_super_modify_happy_path() -> None:
    router = _gated_router(result=None)
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.put(
        "/api/v1/orders/super/SUP-1",
        json={"changes": {"leg_name": "TARGET_LEG", "price": "105"}, "broker": "dhan"},
        headers=_live_headers(),
    )
    assert resp.status_code == 200
    kw = router.execute_gated.await_args.kwargs
    assert kw["verb"] == "modify_super_order"
    assert kw["payload"]["changes"]["leg_name"] == "TARGET_LEG"


def test_super_modify_missing_changes_returns_400() -> None:
    router = _gated_router()
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.put("/api/v1/orders/super/SUP-1", json={}, headers=_live_headers())
    assert resp.status_code == 400
    router.execute_gated.assert_not_called()


def test_super_cancel_with_leg_query() -> None:
    router = _gated_router(result=None)
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.delete(
        "/api/v1/orders/super/SUP-1?leg=target_leg&broker=dhan", headers=_live_headers()
    )
    assert resp.status_code == 200
    kw = router.execute_gated.await_args.kwargs
    assert kw["verb"] == "cancel_super_order"
    assert kw["payload"]["leg"] == "TARGET_LEG"  # normalised + signed in the payload


def test_super_cancel_without_leg_omits_field() -> None:
    """No ?leg= → the field stays out of the signed payload (adapter defaults ENTRY_LEG)."""
    router = _gated_router(result=None)
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.delete("/api/v1/orders/super/SUP-1?broker=dhan", headers=_live_headers())
    assert resp.status_code == 200
    assert "leg" not in router.execute_gated.await_args.kwargs["payload"]


def test_super_cancel_invalid_leg_returns_400() -> None:
    router = _gated_router()
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.delete(
        "/api/v1/orders/super/SUP-1?leg=BANANA_LEG&broker=dhan", headers=_live_headers()
    )
    assert resp.status_code == 400
    router.execute_gated.assert_not_called()


def test_super_practice_jwt_rejected() -> None:
    router = _gated_router()
    client = _app(broker_router=router).test_client()
    assert client.put(
        "/api/v1/orders/super/SUP-1", json={"changes": {"price": "1"}},
        headers=_practice_headers(),
    ).status_code == 403
    assert client.delete(
        "/api/v1/orders/super/SUP-1", headers=_practice_headers()
    ).status_code == 403
    router.execute_gated.assert_not_called()


def test_super_unsupported_broker_returns_501() -> None:
    router = MagicMock()
    router.execute_gated = AsyncMock(
        side_effect=UnsupportedCapabilityError("broker adapter 'upstox' does not support 'cancel_super_order'")
    )
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.delete("/api/v1/orders/super/SUP-1?broker=upstox", headers=_live_headers())
    assert resp.status_code == 501


# ---------------------------------------------------------------------------
# Conditional triggers — place / modify / cancel
# ---------------------------------------------------------------------------

_TRIGGER_BODY = {
    "condition": {"field": "LTP", "operator": ">=", "value": 2900, "symbol": "RELIANCE", "exchange": "NSE"},
    "orders": [{"symbol": "RELIANCE", "exchange": "NSE", "action": "SELL", "quantity": 5}],
    "broker": "dhan",
}


def test_trigger_place_happy_path_carries_typed_legs() -> None:
    router = _gated_router(result="AL-9")
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post("/api/v1/orders/triggers", json=_TRIGGER_BODY, headers=_live_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"] == "AL-9"
    kw = router.execute_gated.await_args.kwargs
    assert kw["verb"] == "place_conditional_trigger"
    assert kw["payload"]["condition"]["field"] == "LTP"
    # Legs are typed Orders, so the signed canonical hash covers every field.
    from flinttrade_core.models import Order

    leg = kw["payload"]["orders"][0]
    assert isinstance(leg, Order)
    assert leg.symbol == "RELIANCE"
    assert leg.quantity == "5"


def test_trigger_place_missing_condition_returns_400() -> None:
    router = _gated_router()
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    body = {k: v for k, v in _TRIGGER_BODY.items() if k != "condition"}
    resp = client.post("/api/v1/orders/triggers", json=body, headers=_live_headers())
    assert resp.status_code == 400
    router.execute_gated.assert_not_called()


def test_trigger_place_bad_leg_returns_400() -> None:
    router = _gated_router()
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    body = {**_TRIGGER_BODY, "orders": [{"symbol": "RELIANCE", "action": "SIDEWAYS"}]}
    resp = client.post("/api/v1/orders/triggers", json=body, headers=_live_headers())
    assert resp.status_code == 400
    router.execute_gated.assert_not_called()


def test_trigger_place_practice_jwt_rejected() -> None:
    router = _gated_router()
    client = _app(broker_router=router).test_client()
    resp = client.post("/api/v1/orders/triggers", json=_TRIGGER_BODY, headers=_practice_headers())
    assert resp.status_code == 403
    router.execute_gated.assert_not_called()


def test_trigger_modify_happy_path() -> None:
    router = _gated_router(result=None)
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.put("/api/v1/orders/triggers/AL-1", json=_TRIGGER_BODY, headers=_live_headers())
    assert resp.status_code == 200
    kw = router.execute_gated.await_args.kwargs
    assert kw["verb"] == "modify_conditional_trigger"
    assert kw["payload"]["alert_id"] == "AL-1"


def test_trigger_cancel_happy_path() -> None:
    router = _gated_router(result=None)
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.delete("/api/v1/orders/triggers/AL-1?broker=dhan", headers=_live_headers())
    assert resp.status_code == 200
    kw = router.execute_gated.await_args.kwargs
    assert kw["verb"] == "cancel_conditional_trigger"
    assert kw["payload"] == {"_op": "cancel_conditional_trigger", "alert_id": "AL-1"}


def test_trigger_unsupported_broker_returns_501() -> None:
    router = MagicMock()
    router.execute_gated = AsyncMock(
        side_effect=UnsupportedCapabilityError("broker adapter 'indmoney' does not support 'place_conditional_trigger'")
    )
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    body = {**_TRIGGER_BODY, "broker": "indmoney"}
    resp = client.post("/api/v1/orders/triggers", json=body, headers=_live_headers())
    assert resp.status_code == 501


def test_trigger_place_runs_full_safetysystem_per_leg() -> None:
    """Audit MEDIUM: a trigger PLACEMENT runs check_order (L1–L4) per leg, not
    just the L5 kill switch — like multi_order_place does."""
    router = _gated_router(result="AL-1")
    safety = _passing_safety()
    client = _app(broker_router=router, safety=safety).test_client()
    resp = client.post("/api/v1/orders/triggers", json=_TRIGGER_BODY, headers=_live_headers())
    assert resp.status_code == 200
    # The single leg cleared the full risk pipeline before the gate was minted.
    assert safety.check_order.call_count == 1
    leg = safety.check_order.call_args.args[0]
    assert leg.symbol == "RELIANCE"


def test_trigger_place_over_limit_leg_blocked_by_l1_before_gate() -> None:
    """An over-limit conditional-trigger leg (e.g. NFO qty 9999999) is rejected
    by L1 BEFORE any gate is minted — the gap this fix closes."""
    blocked = MagicMock(passed=False, layer="L1_ORDER", reason="quantity 9999999 exceeds the per-order limit")
    safety = MagicMock()
    safety.check_order.return_value = [blocked]
    safety.l5_kill.validate.return_value = MagicMock(passed=True)
    router = _gated_router()
    client = _app(broker_router=router, safety=safety).test_client()
    body = {
        "condition": {"field": "LTP", "operator": ">=", "value": 2900, "symbol": "RELIANCE", "exchange": "NSE"},
        "orders": [{"symbol": "RELIANCE", "exchange": "NFO", "action": "SELL", "quantity": 9999999}],
        "broker": "dhan",
    }
    resp = client.post("/api/v1/orders/triggers", json=body, headers=_live_headers())
    assert resp.status_code == 403
    assert "L1_ORDER" in resp.get_json()["message"]
    router.execute_gated.assert_not_called()  # no gate minted


def test_trigger_modify_over_limit_leg_blocked_by_l1() -> None:
    """A trigger MODIFY re-runs the full SafetySystem over the replacement legs."""
    blocked = MagicMock(passed=False, layer="L1_ORDER", reason="quantity exceeds limit")
    safety = MagicMock()
    safety.check_order.return_value = [blocked]
    safety.l5_kill.validate.return_value = MagicMock(passed=True)
    router = _gated_router()
    client = _app(broker_router=router, safety=safety).test_client()
    body = {
        "condition": {"field": "LTP", "operator": ">=", "value": 2900, "symbol": "RELIANCE", "exchange": "NSE"},
        "orders": [{"symbol": "RELIANCE", "exchange": "NFO", "action": "SELL", "quantity": 9999999}],
        "broker": "dhan",
    }
    resp = client.put("/api/v1/orders/triggers/AL-1", json=body, headers=_live_headers())
    assert resp.status_code == 403
    assert "L1_ORDER" in resp.get_json()["message"]
    router.execute_gated.assert_not_called()


def test_gated_verb_surfaces_broker_rejection_message() -> None:
    """Audit MEDIUM: a broker rejection / adapter mapping error propagates its
    OWN message to the response (502) — it is NOT swallowed into a generic 500."""
    from flinttrade_core.exceptions import OrderRejectedByBroker

    router = MagicMock()
    router.execute_gated = AsyncMock(
        side_effect=OrderRejectedByBroker("Dhan rejected: segment not enabled for this account")
    )
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post("/api/v1/orders/triggers", json=_TRIGGER_BODY, headers=_live_headers())
    assert resp.status_code == 502
    assert "segment not enabled" in resp.get_json()["message"]


def test_gated_verb_surfaces_mapping_value_error_message() -> None:
    """An adapter mapping ValueError (the *MappingError classes subclass it)
    surfaces its message rather than a generic failure."""
    router = MagicMock()
    router.execute_gated = AsyncMock(
        side_effect=ValueError("No Dhan segment for exchange 'XYZ'")
    )
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.put(
        "/api/v1/orders/forever/GTT-1",
        json={"changes": {"price": "2900"}, "broker": "dhan"},
        headers=_live_headers(),
    )
    assert resp.status_code == 502
    assert "No Dhan segment" in resp.get_json()["message"]


# ---------------------------------------------------------------------------
# Multi-order placement — every leg through the SafetySystem first
# ---------------------------------------------------------------------------

_MULTI_BODY = {
    "orders": [
        {"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 1},
        {"symbol": "TCS", "exchange": "NSE", "action": "SELL", "quantity": 2},
    ],
    "broker": "upstox",
}


def test_multi_place_happy_path() -> None:
    router = _gated_router(result={"order_ids": ["OID-0", "OID-1"]})
    safety = _passing_safety()
    client = _app(broker_router=router, safety=safety).test_client()
    resp = client.post("/api/v1/orders/multi", json=_MULTI_BODY, headers=_live_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"] == {"order_ids": ["OID-0", "OID-1"]}
    kw = router.execute_gated.await_args.kwargs
    assert kw["verb"] == "place_multi_order"
    assert [o.symbol for o in kw["payload"]["orders"]] == ["RELIANCE", "TCS"]
    # L1-L5 ran for EVERY leg before the gate was minted.
    assert safety.check_order.call_count == 2


def test_multi_place_safety_block_returns_403() -> None:
    blocked = MagicMock(passed=False, layer="L1_ORDER", reason="quantity exceeds limit")
    safety = MagicMock()
    safety.check_order.return_value = [blocked]
    router = _gated_router()
    client = _app(broker_router=router, safety=safety).test_client()
    resp = client.post("/api/v1/orders/multi", json=_MULTI_BODY, headers=_live_headers())
    assert resp.status_code == 403
    assert "L1_ORDER" in resp.get_json()["message"]
    router.execute_gated.assert_not_called()


def test_multi_place_empty_orders_returns_400() -> None:
    router = _gated_router()
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post("/api/v1/orders/multi", json={"orders": []}, headers=_live_headers())
    assert resp.status_code == 400
    router.execute_gated.assert_not_called()


def test_multi_place_bad_leg_returns_400() -> None:
    router = _gated_router()
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    body = {"orders": [{"symbol": "X", "quantity": "ten"}], "broker": "upstox"}
    resp = client.post("/api/v1/orders/multi", json=body, headers=_live_headers())
    assert resp.status_code == 400
    router.execute_gated.assert_not_called()


def test_multi_place_practice_jwt_rejected() -> None:
    router = _gated_router()
    client = _app(broker_router=router).test_client()
    resp = client.post("/api/v1/orders/multi", json=_MULTI_BODY, headers=_practice_headers())
    assert resp.status_code == 403
    router.execute_gated.assert_not_called()


def test_multi_place_unsupported_broker_returns_501() -> None:
    router = MagicMock()
    router.execute_gated = AsyncMock(
        side_effect=UnsupportedCapabilityError("broker adapter 'dhan' does not support 'place_multi_order'")
    )
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post("/api/v1/orders/multi", json={**_MULTI_BODY, "broker": "dhan"}, headers=_live_headers())
    assert resp.status_code == 501


# ---------------------------------------------------------------------------
# cancel-all — gated verb for explicitly-named native brokers; OpenAlgo bridge
# cancel-all is disabled until it has a gated BrokerRouter verb.
# ---------------------------------------------------------------------------


def test_cancel_all_named_native_broker_routes_gated() -> None:
    router = _gated_router(result={"status": "ok"})
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post(
        "/api/v1/orders/cancel-all", json={"broker": "upstox", "tag": "ALGO1", "segment": "EQ"},
        headers=_live_headers(),
    )
    assert resp.status_code == 200
    kw = router.execute_gated.await_args.kwargs
    assert kw["verb"] == "cancel_all_orders"
    assert kw["payload"] == {"_op": "cancel_all_orders", "tag": "ALGO1", "segment": "EQ"}
    assert kw["hint"].adapter_id == "upstox"


def test_cancel_all_without_broker_fails_closed_until_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    """No explicit broker must not fall back to the raw OpenAlgo forward."""
    import flinttrade_core.order_routes as orr

    def _fake_forward(endpoint: str, body: dict[str, Any]) -> tuple[Any, int]:
        raise AssertionError(f"raw OpenAlgo forward reached for {endpoint}: {body}")

    monkeypatch.setattr(orr, "_forward_to_openalgo", _fake_forward)
    router = _gated_router()
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post("/api/v1/orders/cancel-all", json={}, headers=_live_headers())
    assert resp.status_code == 501
    assert "gated broker router" in resp.get_json()["message"]
    router.execute_gated.assert_not_called()


def test_cancel_all_unsupported_broker_returns_501() -> None:
    router = MagicMock()
    router.execute_gated = AsyncMock(
        side_effect=UnsupportedCapabilityError("broker adapter 'kotakneo' does not support 'cancel_all_orders'")
    )
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post(
        "/api/v1/orders/cancel-all", json={"broker": "kotakneo"}, headers=_live_headers()
    )
    assert resp.status_code == 501


# ---------------------------------------------------------------------------
# Smart-order cancel (IndMoney)
# ---------------------------------------------------------------------------


def test_smart_cancel_happy_path_with_segment() -> None:
    router = _gated_router(result=None)
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.delete(
        "/api/v1/orders/smart/DRV-1?segment=DERIVATIVE&broker=indmoney", headers=_live_headers()
    )
    assert resp.status_code == 200
    assert resp.get_json()["orderid"] == "DRV-1"
    kw = router.execute_gated.await_args.kwargs
    assert kw["verb"] == "cancel_smart_order"
    assert kw["payload"] == {"_op": "cancel_smart_order", "order_id": "DRV-1", "segment": "DERIVATIVE"}


def test_smart_cancel_practice_jwt_rejected() -> None:
    router = _gated_router()
    client = _app(broker_router=router).test_client()
    resp = client.delete("/api/v1/orders/smart/DRV-1", headers=_practice_headers())
    assert resp.status_code == 403
    router.execute_gated.assert_not_called()


def test_smart_cancel_unsupported_broker_returns_501() -> None:
    router = MagicMock()
    router.execute_gated = AsyncMock(
        side_effect=UnsupportedCapabilityError("broker adapter 'dhan' does not support 'cancel_smart_order'")
    )
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.delete("/api/v1/orders/smart/DRV-1?broker=dhan", headers=_live_headers())
    assert resp.status_code == 501


# ---------------------------------------------------------------------------
# Positions — convert + exit-all (operations blueprint, /api/v1/positions/*)
# ---------------------------------------------------------------------------

_CONVERT_BODY = {
    "symbol": "RELIANCE", "exchange": "NSE", "from_product": "MIS",
    "to_product": "CNC", "position_type": "LONG", "quantity": 5,
    "broker": "dhan",
}


def test_positions_convert_happy_path() -> None:
    router = _gated_router(result=None)
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post("/api/v1/positions/convert", json=_CONVERT_BODY, headers=_live_headers())
    assert resp.status_code == 200
    kw = router.execute_gated.await_args.kwargs
    assert kw["verb"] == "convert_position"
    assert kw["payload"]["req"]["symbol"] == "RELIANCE"
    # Routing fields never leak into the signed broker request.
    assert "broker" not in kw["payload"]["req"]
    assert "account_id" not in kw["payload"]["req"]


def test_positions_convert_empty_body_returns_400() -> None:
    router = _gated_router()
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post("/api/v1/positions/convert", json={}, headers=_live_headers())
    assert resp.status_code == 400
    router.execute_gated.assert_not_called()


def test_positions_convert_practice_jwt_rejected() -> None:
    router = _gated_router()
    client = _app(broker_router=router).test_client()
    resp = client.post("/api/v1/positions/convert", json=_CONVERT_BODY, headers=_practice_headers())
    assert resp.status_code == 403
    router.execute_gated.assert_not_called()


def test_positions_convert_unsupported_broker_returns_501() -> None:
    router = MagicMock()
    router.execute_gated = AsyncMock(
        side_effect=UnsupportedCapabilityError("broker adapter 'kotakneo' does not support 'convert_position'")
    )
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post(
        "/api/v1/positions/convert", json={**_CONVERT_BODY, "broker": "kotakneo"},
        headers=_live_headers(),
    )
    assert resp.status_code == 501


def test_positions_exit_all_requires_explicit_confirmation() -> None:
    """SAFETY: exit-all flattens the whole account — no confirm, no dispatch."""
    router = _gated_router()
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    for body in ({}, {"confirm": False}, {"confirm": "yes"}, {"broker": "dhan"}):
        resp = client.post("/api/v1/positions/exit-all", json=body, headers=_live_headers())
        assert resp.status_code == 400
        assert "confirm" in resp.get_json()["message"].lower()
    router.execute_gated.assert_not_called()


def test_positions_exit_all_happy_path() -> None:
    router = _gated_router(result={"status": "ok"})
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post(
        "/api/v1/positions/exit-all",
        json={"confirm": True, "segment": "EQ", "broker": "upstox"},
        headers=_live_headers(),
    )
    assert resp.status_code == 200
    kw = router.execute_gated.await_args.kwargs
    assert kw["verb"] == "exit_all_positions"
    assert kw["payload"] == {"_op": "exit_all_positions", "segment": "EQ"}
    # The route-level confirmation flag is NOT part of the broker payload.
    assert "confirm" not in kw["payload"]


def test_positions_exit_all_not_blocked_by_kill_switch() -> None:
    """Exit-all reduces exposure — the halted-account companion action."""
    safety = MagicMock()
    safety.l5_kill.validate.return_value = MagicMock(passed=False, layer="L5_KILL", reason="halted")
    router = _gated_router(result={"status": "ok"})
    client = _app(broker_router=router, safety=safety).test_client()
    resp = client.post(
        "/api/v1/positions/exit-all", json={"confirm": True, "broker": "dhan"},
        headers=_live_headers(),
    )
    assert resp.status_code == 200
    router.execute_gated.assert_awaited_once()


def test_positions_exit_all_practice_jwt_rejected() -> None:
    router = _gated_router()
    client = _app(broker_router=router).test_client()
    resp = client.post(
        "/api/v1/positions/exit-all", json={"confirm": True}, headers=_practice_headers()
    )
    assert resp.status_code == 403
    router.execute_gated.assert_not_called()


def test_positions_exit_all_requires_auth() -> None:
    client = _app(broker_router=_gated_router()).test_client()
    resp = client.post("/api/v1/positions/exit-all", json={"confirm": True})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Kotak Neo bo/co leg cancel — variety/amo extras signed into the fingerprint
# ---------------------------------------------------------------------------


def test_cancel_passes_signed_kotak_extras() -> None:
    router = MagicMock()
    router.cancel_order = AsyncMock(return_value=None)
    client = _app(broker_router=router).test_client()
    resp = client.post(
        "/api/v1/orders/cancel",
        json={"orderid": "OA-7", "variety": "bracket", "amo": True},
        headers=_live_headers(),
    )
    assert resp.status_code == 200
    kw = router.cancel_order.await_args.kwargs
    assert kw["extras"] == {"variety": "bracket", "amo": True}
    # The extras are covered by the SIGNED cancel fingerprint (the router's
    # field-by-field coverage check would refuse them otherwise).
    assert kw["order"]["_op"] == "cancel"
    assert kw["order"]["variety"] == "bracket"
    assert kw["order"]["amo"] is True


def test_cancel_without_extras_keeps_legacy_shape() -> None:
    router = MagicMock()
    router.cancel_order = AsyncMock(return_value=None)
    client = _app(broker_router=router).test_client()
    resp = client.post(
        "/api/v1/orders/cancel", json={"orderid": "OA-7"}, headers=_live_headers()
    )
    assert resp.status_code == 200
    kw = router.cancel_order.await_args.kwargs
    assert kw["extras"] is None
    assert kw["order"] == {"_op": "cancel", "order_id": "OA-7"}


# ---------------------------------------------------------------------------
# End-to-end mint→verify: the route's payload passes a REAL execute_gated
# ---------------------------------------------------------------------------


def test_route_minted_context_verifies_against_real_router() -> None:
    """The context the route mints is accepted by a real BrokerRouter — the
    mint and verify sides agree on payload, verb, actor, mode, and selector."""
    from flinttrade_gateway.brokers._base import ROUTER_TOKEN as _RT
    from flinttrade_gateway.brokers._base import Session
    from flinttrade_gateway.router import BrokerRouter

    calls: list[tuple[str, dict[str, Any]]] = []

    class _Adapter:
        broker_id = "dhan"

        async def modify_forever(
            self, session: object, order_id: str, changes: dict, *, _router_token: object | None = None
        ) -> None:
            assert _router_token is _RT
            calls.append((order_id, changes))

    def _session(_ctx: object, _aid: str, _acct: str) -> Session:
        import time

        return Session(
            access_token="tok", expires_at=time.time() + 3600,
            account_id="default", adapter_id="dhan",
        )

    router = BrokerRouter({"dhan": _Adapter()}, _session)
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.put(
        "/api/v1/orders/forever/GTT-1",
        json={"changes": {"price": "2900"}, "broker": "dhan"},
        headers=_live_headers(),
    )
    assert resp.status_code == 200, resp.get_json()
    assert calls == [("GTT-1", {"price": "2900"})]


def test_gated_verb_algo_tag_limit_returns_429() -> None:
    """The router's algo-tag guard refusing an extended gated verb maps to 429
    (throttle refusal, retry), not the generic 500 (audit fix #3)."""
    from flinttrade_engine.algo_tag_guard import AlgoTagLimitError

    router = MagicMock()
    router.execute_gated = AsyncMock(side_effect=AlgoTagLimitError("dhan/NSE algo ceiling reached"))
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.delete("/api/v1/orders/forever/GTT-9?broker=dhan", headers=_live_headers())
    assert resp.status_code == 429
    assert "refused" in resp.get_json()["message"].lower()
