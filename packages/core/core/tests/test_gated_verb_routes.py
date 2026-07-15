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

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from flask import Flask

from flinttrade_core.auth_routes import _create_token
from flinttrade_core.exceptions import SafetyBypassError, UnsupportedCapabilityError
from flinttrade_core.operations_routes import operations_bp
from flinttrade_core.order_routes import orders_bp
from flinttrade_engine.safety import SafetyConfig, SafetySystem, set_safety_gate_secret

pytestmark = pytest.mark.unit

_SECRET = b"0123456789abcdef0123456789abcdef"  # 32 bytes


@pytest.fixture(autouse=True)
def _bind_secret() -> None:
    """Bind a deterministic safety-gate secret so gate_broker_write can mint."""
    set_safety_gate_secret(_SECRET)


def _app(broker_router: object | None = None, safety: object | None = None) -> Flask:
    if safety is None:
        safety = _passing_safety()
    app = Flask(__name__)
    app.config["BROKER_ROUTER"] = broker_router
    app.config["SAFETY"] = safety
    app.config["SAFETY_CONFIG_READY"] = safety is not None
    state_adapter = MagicMock()
    state_adapter.positions = AsyncMock(return_value=[])
    state_adapter.funds = AsyncMock(
        return_value={
            "used_margin": "0",
            "total_balance": "100000",
            "opening_risk_capital": "100000",
        }
    )
    state_adapter.trade_book = AsyncMock(return_value=[])
    state_adapter.order_book = AsyncMock(return_value=[])
    state_adapter.holdings = AsyncMock(return_value=[])
    state_adapter.margin_calculator = AsyncMock(return_value={"required_margin": "100"})
    forever_order = {
        "orderid": "GTT-1",
        "status": "OPEN",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": "5",
        "filled_quantity": "0",
        "price": "2900",
        "pricetype": "LIMIT",
        "product": "MIS",
    }
    super_order = {
        "orderid": "SUP-1",
        "status": "OPEN",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": "5",
        "filled_quantity": "0",
        "price": "100",
        "pricetype": "LIMIT",
        "product": "MIS",
        "legs": [
            {
                "leg_name": "TARGET_LEG",
                "status": "OPEN",
                "price": "105",
            }
        ],
    }
    state_adapter.forever_orders = AsyncMock(return_value=[forever_order])
    state_adapter.super_orders = AsyncMock(return_value=[super_order])
    def quote_rows(_session: object, symbols: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "exchange": value.split(":", 1)[0],
                "symbol": value.split(":", 1)[1],
                "ltp": 2_900,
            }
            for value in symbols
        ]

    state_adapter.quotes = AsyncMock(side_effect=quote_rows)
    app.config["NATIVE_ADAPTERS"] = {
        broker: state_adapter for broker in ("dhan", "indmoney", "upstox")
    }
    registry = MagicMock()
    registry.get_session_for.return_value = object()
    app.config["REGISTRY"] = registry
    app.config["OPENALGO_CLIENT"] = SimpleNamespace(
        positionbook=AsyncMock(return_value=[]),
        holdings=AsyncMock(return_value=[]),
        funds=AsyncMock(
            return_value={
                "used_margin": "0",
                "total_balance": "100000",
                "opening_risk_capital": "100000",
            }
        ),
        tradebook=AsyncMock(return_value=[]),
        orderbook=AsyncMock(return_value=[]),
        multi_quotes=AsyncMock(
            side_effect=lambda symbols: [
                {
                    "exchange": value["exchange"],
                    "symbol": value["symbol"],
                    "ltp": 2_900,
                }
                for value in symbols
            ]
        ),
        gtt_orderbook=AsyncMock(return_value=[forever_order]),
        margin=AsyncMock(return_value={"data": {"required_margin": "100"}}),
    )
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


def _passing_safety() -> SafetySystem:
    """A SafetySystem stub whose check_order and kill switch both pass."""
    safety = SafetySystem(SafetyConfig(check_market_hours=False))
    safety.check_order = MagicMock(return_value=[])
    safety.l5_kill.validate = MagicMock(return_value=MagicMock(passed=True))
    return safety


def _real_safety(**cfg: Any) -> object:
    return SafetySystem(SafetyConfig(check_market_hours=False, **cfg))


def _gated_router(result: Any = {"status": "ok"}) -> MagicMock:
    router = MagicMock()
    router.execute_gated = AsyncMock(return_value=result)
    router.place_order = AsyncMock(return_value="OID-1")
    return router


def _app_with_native_state(
    router: object | None,
    safety: object | None,
    *,
    adapter_id: str,
    account_id: str,
    positions: list[Any] | None = None,
    funds: dict[str, Any] | None = None,
) -> tuple[Flask, MagicMock, MagicMock]:
    app = _app(broker_router=router, safety=safety)
    session = object()
    registry = MagicMock()
    registry.get_session_for.return_value = session
    adapter = MagicMock()
    adapter.positions = AsyncMock(return_value=positions or [])
    adapter.funds = AsyncMock(
        return_value={
            "used_margin": "0",
            "total_balance": "100000",
            "opening_risk_capital": "100000",
            **(funds or {}),
        }
    )
    adapter.trade_book = AsyncMock(return_value=[])
    adapter.order_book = AsyncMock(return_value=[])
    adapter.holdings = AsyncMock(return_value=[])
    adapter.margin_calculator = AsyncMock(return_value={"required_margin": "100"})
    adapter.quotes = AsyncMock(
        return_value=[
            {
                "symbol": getattr(position, "symbol", ""),
                "exchange": str(getattr(position, "exchange", "NSE")),
                "ltp": 100,
                "prev_close": 100,
                "previous_close_trusted": True,
            }
            for position in (positions or [])
        ]
    )
    app.config["REGISTRY"] = registry
    app.config["NATIVE_ADAPTERS"] = {adapter_id: adapter}
    return app, adapter, registry


def test_gated_target_uses_execution_default_only_when_target_omitted() -> None:
    """The shared gated-verb helper follows router config for omitted targets."""
    from flinttrade_core.order_routes import _gated_target

    class _Execution:
        default = "upstox:U1"

    class _Config:
        execution = _Execution()

    class _Router:
        _config = _Config()
        default_selector = "upstox:U1"  # public accessor the routes now read

    app = _app(broker_router=_Router())
    with app.app_context():
        assert _gated_target({}) == ("upstox", "U1")
        assert _gated_target({"broker": "dhan"}) == ("dhan", "default")
        assert _gated_target({"account_id": "D1"}) == ("openalgo", "D1")


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
        "entry_trigger_type": "BELOW", "stop_loss_trigger_type": "IMMEDIATE",
        "target_trigger_type": "IMMEDIATE",
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
    assert order.entry_trigger_type == "BELOW"
    assert order.stop_loss_trigger_type == "IMMEDIATE"
    assert order.target_trigger_type == "IMMEDIATE"
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
    safety = _passing_safety()
    client = _app(broker_router=router, safety=safety).test_client()
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
    safety.check_order.assert_not_called()


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


def test_forever_cancel_is_blocked_by_kill_switch() -> None:
    """An ordinary cancel may remove a protective exit; only L5 policy bypasses."""
    safety = MagicMock()
    safety.l5_kill.validate.return_value = MagicMock(passed=False, layer="L5_KILL", reason="halted")
    router = _gated_router(result=None)
    client = _app(broker_router=router, safety=safety).test_client()
    resp = client.delete("/api/v1/orders/forever/GTT-9?broker=dhan", headers=_live_headers())
    assert resp.status_code == 403
    router.execute_gated.assert_not_called()


def test_forever_unsupported_broker_returns_501() -> None:
    router = MagicMock()
    router.execute_gated = AsyncMock(
        side_effect=UnsupportedCapabilityError("broker adapter 'kotakneo' does not support 'modify_forever'")
    )
    app, adapter, _registry = _app_with_native_state(
        router,
        _passing_safety(),
        adapter_id="kotakneo",
        account_id="default",
    )
    adapter.forever_orders = AsyncMock(
        return_value=[
            {
                "orderid": "GTT-1",
                "status": "OPEN",
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "action": "BUY",
                "quantity": "5",
                "filled_quantity": "0",
                "price": "2900",
                "pricetype": "LIMIT",
                "product": "MIS",
            }
        ]
    )
    adapter.margin_calculator = AsyncMock(return_value={"required_margin": "100"})
    client = app.test_client()
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
    safety = _passing_safety()
    client = _app(broker_router=router, safety=safety).test_client()
    resp = client.put(
        "/api/v1/orders/super/SUP-1",
        json={"changes": {"leg_name": "TARGET_LEG", "price": "105"}, "broker": "dhan"},
        headers=_live_headers(),
    )
    assert resp.status_code == 200
    kw = router.execute_gated.await_args.kwargs
    assert kw["verb"] == "modify_super_order"
    assert kw["payload"]["changes"]["leg_name"] == "TARGET_LEG"
    safety.check_order.assert_not_called()


@pytest.mark.parametrize(
    ("path", "reader_name"),
    [
        ("/api/v1/orders/forever/GTT-1", "forever_orders"),
        ("/api/v1/orders/super/SUP-1", "super_orders"),
    ],
)
def test_advanced_modify_quantity_increase_runs_full_safety_before_gate(
    path: str,
    reader_name: str,
) -> None:
    blocked = MagicMock(passed=False, layer="L1_ORDER", reason="quantity limit")
    safety = _passing_safety()
    safety.check_order.return_value = [blocked]
    router = _gated_router(result=None)
    app, adapter, _registry = _app_with_native_state(
        router,
        safety,
        adapter_id="dhan",
        account_id="D1",
    )
    current = {
        "orderid": path.rsplit("/", 1)[-1],
        "status": "PENDING",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": "1",
        "filled_quantity": "0",
        "price": "0",
        "pricetype": "MARKET",
        "product": "MIS",
    }
    setattr(adapter, reader_name, AsyncMock(return_value=[current]))
    adapter.margin_calculator = AsyncMock(
        side_effect=[
            {"required_margin": "100"},
            {"required_margin": "250"},
            {"required_margin": "250"},
        ]
    )

    response = app.test_client().put(
        path,
        json={"changes": {"quantity": 2}, "broker": "dhan", "account_id": "D1"},
        headers=_live_headers(),
    )

    assert response.status_code == 403
    safety.check_order.assert_called_once()
    router.execute_gated.assert_not_called()


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


def test_trigger_place_native_l2_blocks_before_gate() -> None:
    """Conditional-trigger legs also use the named native account for L2."""
    from flinttrade_core.models import Position

    router = _gated_router()
    app, adapter, registry = _app_with_native_state(
        router,
        _real_safety(max_positions=1),
        adapter_id="dhan",
        account_id="D1",
        positions=[Position(symbol="INFY", exchange="NSE", product="MIS", quantity="50")],
        funds={"used_margin": "0", "total_balance": "100000"},
    )
    body = {**_TRIGGER_BODY, "account_id": "D1"}
    resp = app.test_client().post("/api/v1/orders/triggers", json=body, headers=_live_headers())

    assert resp.status_code == 403
    assert "L2_POSITION" in resp.get_json()["message"]
    router.execute_gated.assert_not_called()
    registry.get_session_for.assert_called_once_with("dhan", "D1")
    assert adapter.positions.await_count == 2
    adapter.funds.assert_awaited_once()


def test_gated_verb_bounds_broker_rejection_message() -> None:
    """Broker/adapter detail is logged, not reflected to HTTP callers."""
    from flinttrade_core.exceptions import OrderRejectedByBroker

    router = MagicMock()
    router.execute_gated = AsyncMock(
        side_effect=OrderRejectedByBroker("Dhan rejected: segment not enabled for this account")
    )
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post("/api/v1/orders/triggers", json=_TRIGGER_BODY, headers=_live_headers())
    assert resp.status_code == 502
    assert resp.get_json()["message"] == "Conditional trigger placement failed"


def test_gated_verb_bounds_mapping_value_error_message() -> None:
    """Adapter mapping ValueErrors must not expose internals in responses."""
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
    assert resp.get_json()["message"] == "Forever order modify failed"


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


def _batch_request(path: str) -> dict[str, Any]:
    if path.endswith("/triggers"):
        return {
            "condition": {
                "field": "LTP",
                "operator": ">=",
                "value": 100,
                "symbol": "RELIANCE",
                "exchange": "NSE",
            },
            **_MULTI_BODY,
        }
    return dict(_MULTI_BODY)


def _batch_state(*admissions: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        positions=[],
        used_margin=0.0,
        total_balance=100_000.0,
        daily_pnl=0.0,
        starting_capital=100_000.0,
        net_delta=0.0,
        net_vega=0.0,
        ltp_for=lambda _order: None,
        admission_for=lambda index: admissions[index],
    )


@pytest.mark.parametrize("path", ["/api/v1/orders/triggers", "/api/v1/orders/multi"])
def test_batch_writes_accumulate_position_count_before_gate(
    path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_core import order_routes

    state = _batch_state(
        SimpleNamespace(positions=[], used_margin=0.0, net_delta=0.0, net_vega=0.0),
        SimpleNamespace(
            positions=[SimpleNamespace(symbol="RELIANCE", exchange="NSE", product="MIS", quantity="1")],
            used_margin=0.0,
            net_delta=0.0,
            net_vega=0.0,
        ),
    )
    if path.endswith("/multi"):
        states = iter((_batch_state(state.admission_for(0)), _batch_state(state.admission_for(1))))
        monkeypatch.setattr(order_routes, "_gather_safety_state", lambda *_args, **_kwargs: next(states))
    else:
        monkeypatch.setattr(order_routes, "_gather_safety_state", lambda *_args, **_kwargs: state)
    router = _gated_router()
    response = _app(router, _real_safety(max_positions=1)).test_client().post(
        path,
        json=_batch_request(path),
        headers=_live_headers(),
    )

    assert response.status_code == 403
    assert "L2_POSITION" in response.get_json()["message"]
    if path.endswith("/multi"):
        router.place_order.assert_awaited_once()
    else:
        router.execute_gated.assert_not_called()


@pytest.mark.parametrize("path", ["/api/v1/orders/triggers", "/api/v1/orders/multi"])
def test_batch_writes_accumulate_margin_before_gate(
    path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_core import order_routes

    state = _batch_state(
        SimpleNamespace(positions=[], used_margin=50_000.0, net_delta=0.0, net_vega=0.0),
        SimpleNamespace(positions=[], used_margin=70_000.0, net_delta=0.0, net_vega=0.0),
    )
    if path.endswith("/multi"):
        states = iter((_batch_state(state.admission_for(0)), _batch_state(state.admission_for(1))))
        monkeypatch.setattr(order_routes, "_gather_safety_state", lambda *_args, **_kwargs: next(states))
    else:
        monkeypatch.setattr(order_routes, "_gather_safety_state", lambda *_args, **_kwargs: state)
    router = _gated_router()
    response = _app(router, _real_safety(max_margin_pct=60.0)).test_client().post(
        path,
        json=_batch_request(path),
        headers=_live_headers(),
    )

    assert response.status_code == 403
    assert "L2_POSITION" in response.get_json()["message"]
    if path.endswith("/multi"):
        router.place_order.assert_awaited_once()
    else:
        router.execute_gated.assert_not_called()


@pytest.mark.parametrize("path", ["/api/v1/orders/triggers", "/api/v1/orders/multi"])
def test_batch_writes_accumulate_greeks_before_gate(
    path: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from flinttrade_core import order_routes

    state = _batch_state(
        SimpleNamespace(positions=[], used_margin=0.0, net_delta=30.0, net_vega=0.0),
        SimpleNamespace(positions=[], used_margin=0.0, net_delta=60.0, net_vega=0.0),
    )
    if path.endswith("/multi"):
        states = iter((_batch_state(state.admission_for(0)), _batch_state(state.admission_for(1))))
        monkeypatch.setattr(order_routes, "_gather_safety_state", lambda *_args, **_kwargs: next(states))
    else:
        monkeypatch.setattr(order_routes, "_gather_safety_state", lambda *_args, **_kwargs: state)
    router = _gated_router()
    response = _app(router, _real_safety(max_net_delta=50.0)).test_client().post(
        path,
        json=_batch_request(path),
        headers=_live_headers(),
    )

    assert response.status_code == 403
    assert "L3_PORTFOLIO" in response.get_json()["message"]
    if path.endswith("/multi"):
        router.place_order.assert_awaited_once()
    else:
        router.execute_gated.assert_not_called()


def test_multi_place_happy_path() -> None:
    router = _gated_router()
    router.place_order.side_effect = ["OID-0", "OID-1"]
    safety = _passing_safety()
    client = _app(broker_router=router, safety=safety).test_client()
    resp = client.post("/api/v1/orders/multi", json=_MULTI_BODY, headers=_live_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"] == {"order_ids": ["OID-0", "OID-1"]}
    assert [call.kwargs["order"].symbol for call in router.place_order.await_args_list] == ["RELIANCE", "TCS"]
    # L1-L5 ran immediately before each independently gated leg.
    assert safety.check_order.call_count == 2


def test_multi_place_safety_block_returns_403() -> None:
    blocked = MagicMock(passed=False, layer="L1_ORDER", reason="quantity exceeds limit")
    safety = _passing_safety()
    safety.check_order.return_value = [blocked]
    router = _gated_router()
    client = _app(broker_router=router, safety=safety).test_client()
    resp = client.post("/api/v1/orders/multi", json=_MULTI_BODY, headers=_live_headers())
    assert resp.status_code == 403
    assert "L1_ORDER" in resp.get_json()["message"]
    router.place_order.assert_not_called()


def test_multi_place_native_l2_blocks_before_gate() -> None:
    """Native multi-order legs feed the named account's live positions into L2."""
    from flinttrade_core.models import Position

    router = _gated_router()
    app, adapter, registry = _app_with_native_state(
        router,
        _real_safety(max_positions=1),
        adapter_id="upstox",
        account_id="U1",
        positions=[Position(symbol="INFY", exchange="NSE", product="MIS", quantity="50")],
        funds={"used_margin": "0", "total_balance": "100000"},
    )
    body = {**_MULTI_BODY, "account_id": "U1"}
    resp = app.test_client().post("/api/v1/orders/multi", json=body, headers=_live_headers())

    assert resp.status_code == 403
    assert "L2_POSITION" in resp.get_json()["message"]
    router.execute_gated.assert_not_called()
    registry.get_session_for.assert_called_once_with("upstox", "U1")
    assert adapter.positions.await_count == 2
    adapter.funds.assert_awaited_once()


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
    router.place_order = AsyncMock(
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


def test_native_cancel_all_with_strategy_scope_fails_closed() -> None:
    """A strategy-scoped cancel-all must NOT silently escalate to an account-wide
    native sweep — the native ``cancel_all_orders`` verb has no per-strategy
    narrowing (it forwards only tag/segment), so honouring a bare ``strategy``
    would wipe every open order incl. other strategies' protective exits. It
    fails closed with 400 and the router is NEVER invoked (Codex-wave review
    finding 3)."""
    router = _gated_router(result={"status": "ok"})
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post(
        "/api/v1/orders/cancel-all",
        json={"broker": "upstox", "strategy": "FlintScalper"},
        headers=_live_headers(),
    )
    assert resp.status_code == 400
    assert "strategy-scoped cancel-all is not supported" in resp.get_json()["message"].lower()
    router.execute_gated.assert_not_called()


def test_cancel_all_without_broker_uses_gated_openalgo_target(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default OpenAlgo sweep must use BrokerRouter, never the raw forward."""
    import flinttrade_core.order_routes as orr

    def _fake_forward(endpoint: str, body: dict[str, Any]) -> tuple[Any, int]:
        raise AssertionError(f"raw OpenAlgo forward reached for {endpoint}: {body}")

    monkeypatch.setattr(orr, "_forward_to_openalgo", _fake_forward)
    router = _gated_router(result={"status": "ok"})
    client = _app(broker_router=router, safety=_passing_safety()).test_client()
    resp = client.post("/api/v1/orders/cancel-all", json={}, headers=_live_headers())
    assert resp.status_code == 200
    kw = router.execute_gated.await_args.kwargs
    assert kw["verb"] == "cancel_all_orders"
    assert kw["hint"].adapter_id == "openalgo"


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
    from flinttrade_core.models import Position

    router = _gated_router(result=None)
    app, _adapter, _registry = _app_with_native_state(
        router,
        _passing_safety(),
        adapter_id="dhan",
        account_id="default",
        positions=[Position(symbol="RELIANCE", exchange="NSE", product="MIS", quantity="5")],
    )
    resp = app.test_client().post(
        "/api/v1/positions/convert", json=_CONVERT_BODY, headers=_live_headers()
    )
    assert resp.status_code == 200
    kw = router.execute_gated.await_args.kwargs
    assert kw["verb"] == "convert_position"
    assert kw["payload"]["req"]["symbol"] == "RELIANCE"
    # Routing fields never leak into the signed broker request.
    assert "broker" not in kw["payload"]["req"]
    assert "account_id" not in kw["payload"]["req"]


def test_positions_convert_margin_increase_runs_full_safety_before_gate() -> None:
    from flinttrade_core.models import Position

    blocked = MagicMock(passed=False, layer="L2_POSITION", reason="margin limit")
    safety = _passing_safety()
    safety.check_order.return_value = [blocked]
    router = _gated_router(result=None)
    app, adapter, _registry = _app_with_native_state(
        router,
        safety,
        adapter_id="dhan",
        account_id="default",
        positions=[Position(symbol="RELIANCE", exchange="NSE", product="MIS", quantity="5")],
        funds={"used_margin": "100"},
    )
    adapter.margin_calculator = AsyncMock(
        side_effect=[
            {"required_margin": "100"},
            {"required_margin": "700"},
        ]
    )

    response = app.test_client().post(
        "/api/v1/positions/convert",
        json=_CONVERT_BODY,
        headers=_live_headers(),
    )

    assert response.status_code == 403
    checked_order = safety.check_order.call_args.args[0]
    checked_inputs = safety.check_order.call_args.kwargs
    assert str(checked_order.product) == "CNC"
    assert checked_inputs["used_margin"] == 700.0
    assert checked_inputs["positions"] == []
    router.execute_gated.assert_not_called()


def test_positions_convert_margin_reduction_skips_l1_l4_and_dispatches() -> None:
    from flinttrade_core.models import Position

    safety = _passing_safety()
    safety.check_order.side_effect = AssertionError("no-increase conversion entered L1-L4")
    router = _gated_router(result=None)
    app, adapter, _registry = _app_with_native_state(
        router,
        safety,
        adapter_id="dhan",
        account_id="default",
        positions=[Position(symbol="RELIANCE", exchange="NSE", product="CNC", quantity="5")],
    )
    adapter.margin_calculator = AsyncMock(
        side_effect=[
            {"required_margin": "700"},
            {"required_margin": "100"},
        ]
    )
    body = {**_CONVERT_BODY, "from_product": "CNC", "to_product": "MIS"}

    response = app.test_client().post(
        "/api/v1/positions/convert",
        json=body,
        headers=_live_headers(),
    )

    assert response.status_code == 200
    assert adapter.margin_calculator.await_count == 2
    safety.check_order.assert_not_called()
    router.execute_gated.assert_awaited_once()


def test_positions_convert_unmatched_position_fails_closed_before_gate() -> None:
    router = _gated_router(result=None)
    app, _adapter, _registry = _app_with_native_state(
        router,
        _passing_safety(),
        adapter_id="dhan",
        account_id="default",
        positions=[],
    )

    response = app.test_client().post(
        "/api/v1/positions/convert",
        json=_CONVERT_BODY,
        headers=_live_headers(),
    )

    assert response.status_code == 400
    router.execute_gated.assert_not_called()


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
    from flinttrade_core.models import Position

    router = MagicMock()
    router.execute_gated = AsyncMock(
        side_effect=UnsupportedCapabilityError("broker adapter 'kotakneo' does not support 'convert_position'")
    )
    app, _adapter, _registry = _app_with_native_state(
        router,
        _passing_safety(),
        adapter_id="kotakneo",
        account_id="default",
        positions=[Position(symbol="RELIANCE", exchange="NSE", product="MIS", quantity="5")],
    )
    client = app.test_client()
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


def test_positions_exit_all_is_blocked_by_kill_switch() -> None:
    """L5 retries are coordinated; ordinary exit-all must not double-square-off."""
    safety = MagicMock()
    safety.l5_kill.validate.return_value = MagicMock(passed=False, layer="L5_KILL", reason="halted")
    router = _gated_router(result={"status": "ok"})
    client = _app(broker_router=router, safety=safety).test_client()
    resp = client.post(
        "/api/v1/positions/exit-all", json={"confirm": True, "broker": "dhan"},
        headers=_live_headers(),
    )
    assert resp.status_code == 403
    router.execute_gated.assert_not_called()


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
