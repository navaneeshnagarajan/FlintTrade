"""Mounted webhook order intents must dispatch only through the gated router."""

from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from flask import Flask

from flinttrade_core.webhook_dispatch import WebhookExecutionAuthority, WebhookOrderDispatcher
from flinttrade_engine.safety import SafetyConfig, SafetySystem, set_safety_gate_secret
from flinttrade_webhooks.webhook_receiver import WebhookConfig, WebhookPayload, WebhookReceiver


def _passing_safety() -> SafetySystem:
    safety = SafetySystem(SafetyConfig(check_market_hours=False))
    safety.check_order = MagicMock(return_value=[SimpleNamespace(passed=True)])
    return safety


@pytest.fixture(autouse=True)
def _safety_secret() -> None:
    set_safety_gate_secret(b"w" * 32)


def _app(router: MagicMock) -> Flask:
    app = Flask("webhook-dispatch-test")
    app.config["BROKER_ROUTER"] = router
    app.config["SAFETY"] = _passing_safety()
    app.config["SAFETY_CONFIG_READY"] = True
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
        multi_quotes=AsyncMock(return_value=[]),
        margin=AsyncMock(return_value={"required_margin": "100"}),
    )
    return app


def _authority(*actions: str, selector: str = "openalgo:default") -> WebhookExecutionAuthority:
    return WebhookExecutionAuthority(
        actor_id="external_intent:webhook:test-endpoint",
        selector=selector,
        allowed_actions=frozenset(actions),
    )


def _dispatcher(
    app: Flask,
    *actions: str,
    selector: str = "openalgo:default",
) -> WebhookOrderDispatcher:
    authority = _authority(*actions, selector=selector)
    return WebhookOrderDispatcher(app, authority_provider=lambda _payload: authority)


def test_place_order_fails_closed_without_live_endpoint_authority() -> None:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="SHOULD-NOT-REACH")
    dispatcher = WebhookOrderDispatcher(_app(router))
    payload = WebhookPayload(
        source="custom",
        action="place_order",
        symbol="NIFTY",
        exchange="NSE",
        data={"side": "BUY", "quantity": "1"},
        webhook_nonce="verified-nonce-unarmed",
        webhook_path="/v1/webhook/custom/test-endpoint",
    )

    result = asyncio.run(dispatcher.place_order(payload))

    assert result["status"] == "error"
    assert "not armed" in result["message"].lower()
    router.place_order.assert_not_called()


def test_place_order_rejects_action_not_granted_by_endpoint_authority() -> None:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="SHOULD-NOT-REACH")
    dispatcher = _dispatcher(_app(router), "cancel_order")
    payload = WebhookPayload(
        source="custom",
        action="place_order",
        symbol="NIFTY",
        exchange="NSE",
        data={"side": "BUY", "quantity": "1"},
        webhook_nonce="verified-nonce-wrong-action",
        webhook_path="/v1/webhook/custom/test-endpoint",
    )

    result = asyncio.run(dispatcher.place_order(payload))

    assert result["status"] == "error"
    assert "not authorised" in result["message"].lower()
    router.place_order.assert_not_called()


def test_place_order_rejects_invalid_authority_selector() -> None:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="SHOULD-NOT-REACH")
    dispatcher = _dispatcher(_app(router), "place_order", selector="attacker-controlled")
    payload = WebhookPayload(
        source="custom",
        action="place_order",
        symbol="NIFTY",
        exchange="NSE",
        data={"side": "BUY", "quantity": "1"},
        webhook_nonce="verified-nonce-invalid-selector",
        webhook_path="/v1/webhook/custom/test-endpoint",
    )

    result = asyncio.run(dispatcher.place_order(payload))

    assert result["status"] == "error"
    assert "execution authority" in result["message"].lower()
    router.place_order.assert_not_called()


def test_custom_place_order_runs_through_gate_and_router() -> None:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="ORDER-1")
    dispatcher = _dispatcher(_app(router), "place_order")
    payload = WebhookPayload(
        source="custom",
        action="place_order",
        symbol="NIFTY",
        exchange="NSE",
        data={"side": "BUY", "quantity": "1", "account_id": "default"},
        webhook_nonce="verified-nonce-1",
        webhook_path="/v1/webhook/custom/test-endpoint",
    )

    result = asyncio.run(dispatcher.place_order(payload))

    assert result["status"] == "placed"
    assert result["orderid"] == "ORDER-1"
    router.place_order.assert_awaited_once()
    request_ctx = router.place_order.await_args.args[0]
    kwargs = router.place_order.await_args.kwargs
    expected_hash = hashlib.sha256(b"verified-nonce-1").hexdigest()
    assert request_ctx.actor_type == "external_intent"
    assert request_ctx.actor_id == "external_intent:webhook:test-endpoint"
    assert request_ctx.intent_source == "custom"
    assert request_ctx.selector == "openalgo:default"
    assert request_ctx.external_nonce_hash == expected_hash
    assert kwargs["hint"].adapter_id == "openalgo"
    assert kwargs["hint"].account_id == "default"
    assert kwargs["safety_ctx"].verify(kwargs["order"], request_ctx, "openalgo", "default")


def test_parsed_custom_place_order_threads_side_through_gate_and_router() -> None:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="ORDER-CUSTOM-1")
    app = _app(router)
    dispatcher = _dispatcher(app, "place_order")
    payload = WebhookReceiver(WebhookConfig(skip_verification=True)).parse_custom({
        "action": "place_order",
        "side": "BUY",
        "symbol": "NIFTY",
        "exchange": "NSE",
        "quantity": "1",
    })
    payload.webhook_nonce = "verified-custom-nonce"
    payload.webhook_path = "/v1/webhook/custom/test-endpoint"

    result = asyncio.run(dispatcher.place_order(payload))

    assert result["status"] == "placed"
    assert result["orderid"] == "ORDER-CUSTOM-1"
    router.place_order.assert_awaited_once()
    assert router.place_order.await_args.kwargs["order"].action.value == "BUY"


def test_place_order_rejects_conflicting_side_aliases_before_router() -> None:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="SHOULD-NOT-REACH")
    dispatcher = _dispatcher(_app(router), "place_order")
    payload = WebhookPayload(
        source="custom",
        action="place_order",
        symbol="NIFTY",
        exchange="NSE",
        data={"side": "SELL", "order_action": "BUY", "quantity": "1"},
        webhook_nonce="verified-conflicting-side",
        webhook_path="/v1/webhook/custom/test-endpoint",
    )

    result = asyncio.run(dispatcher.place_order(payload))

    assert result["status"] == "error"
    assert "BUY or SELL" in result["message"]
    router.place_order.assert_not_called()


@pytest.mark.parametrize("price", ["-1", "nan", "inf"])
def test_limit_order_rejects_unsafe_price_before_gate_and_router(price: str) -> None:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="SHOULD-NOT-REACH")
    app = _app(router)
    dispatcher = _dispatcher(app, "place_order")
    payload = WebhookPayload(
        source="custom",
        action="place_order",
        symbol="NIFTY",
        exchange="NSE",
        data={"side": "BUY", "quantity": "1", "pricetype": "LIMIT", "price": price},
        webhook_nonce=f"verified-invalid-price-{price}",
        webhook_path="/v1/webhook/custom/test-endpoint",
    )

    result = asyncio.run(dispatcher.place_order(payload))

    assert result["status"] == "error"
    assert "price" in result["message"].lower()
    app.config["SAFETY"].check_order.assert_not_called()
    router.place_order.assert_not_called()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("price1", "nan"),
        ("price1", "inf"),
        ("price1", "0"),
        ("price1", "-1"),
        ("trigger_price1", "nan"),
        ("trigger_price1", "0"),
        ("quantity1", "0"),
        ("quantity1", "1.5"),
    ],
)
def test_gtt_second_leg_rejects_unsafe_values_before_gate_and_router(
    field: str,
    value: str,
) -> None:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="SHOULD-NOT-REACH")
    app = _app(router)
    dispatcher = _dispatcher(app, "place_order")
    second_leg = {"price1": "101", "trigger_price1": "100", "quantity1": "1"}
    second_leg[field] = value
    payload = WebhookPayload(
        source="custom",
        action="place_order",
        symbol="NIFTY",
        exchange="NSE",
        data={
            "side": "BUY",
            "quantity": "1",
            "variety": "gtt",
            **second_leg,
        },
        webhook_nonce=f"verified-invalid-second-leg-{field}-{value}",
        webhook_path="/v1/webhook/custom/test-endpoint",
    )

    result = asyncio.run(dispatcher.place_order(payload))

    assert result["status"] == "error"
    assert field in result["message"]
    app.config["SAFETY"].check_order.assert_not_called()
    router.place_order.assert_not_called()


def test_gtt_second_leg_cannot_exceed_l1_quantity_limit() -> None:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="SHOULD-NOT-REACH")
    app = _app(router)
    app.config["SAFETY"] = SafetySystem(
        SafetyConfig(qty_limits={"NSE": 1}, check_market_hours=False),
    )
    dispatcher = _dispatcher(app, "place_order")
    payload = WebhookPayload(
        source="custom",
        action="place_order",
        symbol="NIFTY",
        exchange="NSE",
        data={
            "side": "BUY",
            "quantity": "1",
            "variety": "gtt",
            "price1": "101",
            "trigger_price1": "100",
            "quantity1": "2",
        },
        webhook_nonce="verified-secondary-quantity-limit",
        webhook_path="/v1/webhook/custom/test-endpoint",
    )

    result = asyncio.run(dispatcher.place_order(payload))

    assert result["status"] == "error"
    assert "Second-leg quantity 2 exceeds NSE limit of 1" in result["message"]
    router.place_order.assert_not_called()


def test_post_submit_reservation_failure_reports_placed_with_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="ORDER-SUBMITTED")
    app = _app(router)
    audit = MagicMock()
    app.config["AUDIT"] = audit
    safety = app.config["SAFETY"]
    monkeypatch.setattr(
        safety,
        "_acknowledge_order_reservation",
        MagicMock(side_effect=OSError("reservation store unavailable")),
    )
    dispatcher = _dispatcher(app, "place_order")
    journal = MagicMock()
    monkeypatch.setattr(dispatcher, "_journal", journal)
    payload = WebhookPayload(
        source="custom",
        action="place_order",
        symbol="NIFTY",
        exchange="NSE",
        data={"side": "BUY", "quantity": "1"},
        webhook_nonce="verified-post-submit-nonce",
        webhook_path="/v1/webhook/custom/test-endpoint",
    )

    result = asyncio.run(dispatcher.place_order(payload))

    assert result["status"] == "placed"
    assert result["orderid"] == "ORDER-SUBMITTED"
    assert "verify broker status before retrying" in result["warning"].lower()
    router.place_order.assert_awaited_once()
    audit.log_event.assert_called_once()
    assert audit.log_event.call_args.args[0] == "WEBHOOK_ORDER_PLACED_RESERVATION_UNACKNOWLEDGED"
    journal.assert_called_once()


def test_place_order_refuses_unvalidated_safety_runtime() -> None:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="SHOULD-NOT-REACH")
    app = _app(router)
    app.config["SAFETY_CONFIG_READY"] = False
    dispatcher = _dispatcher(app, "place_order")
    payload = WebhookPayload(
        source="custom",
        action="place_order",
        symbol="NIFTY",
        exchange="NSE",
        data={"side": "BUY", "quantity": "1", "account_id": "default"},
        webhook_nonce="verified-nonce-2",
        webhook_path="/v1/webhook/custom/test-endpoint",
    )

    result = asyncio.run(dispatcher.place_order(payload))

    assert result["status"] == "error"
    assert "safety configuration" in result["message"].lower()
    router.place_order.assert_not_called()


def test_place_order_checks_prospective_greeks_before_router(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BlockingSafety:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def check_order(self, _order, **kwargs):
            self.calls.append(kwargs)
            return [SimpleNamespace(
                passed=False,
                layer="L3_PORTFOLIO",
                reason="prospective delta exceeds limit",
            )]

    state = SimpleNamespace(
        positions=[],
        used_margin=0.0,
        total_balance=100000.0,
        daily_pnl=0.0,
        starting_capital=100000.0,
        net_delta=0.0,
        net_vega=0.0,
        ltp_for=lambda _order: None,
        admission_for=lambda _index: SimpleNamespace(
            positions=[],
            used_margin=0.0,
            net_delta=750.0,
            net_vega=12000.0,
        ),
    )
    router = MagicMock()
    router.place_order = AsyncMock(return_value="SHOULD-NOT-REACH")
    app = _app(router)
    recorder = _BlockingSafety()
    safety = _passing_safety()
    safety.check_order = recorder.check_order
    app.config["SAFETY"] = safety
    dispatcher = _dispatcher(app, "place_order")
    monkeypatch.setattr(
        dispatcher,
        "_gather_safety_state",
        AsyncMock(return_value=state),
    )
    payload = WebhookPayload(
        source="custom",
        action="place_order",
        symbol="NIFTY",
        exchange="NSE",
        data={"side": "BUY", "quantity": "1", "account_id": "default"},
        webhook_nonce="verified-nonce-greeks",
        webhook_path="/v1/webhook/custom/test-endpoint",
    )

    result = asyncio.run(dispatcher.place_order(payload))

    assert result["status"] == "error"
    assert recorder.calls[0]["net_delta"] == 750.0
    assert recorder.calls[0]["net_vega"] == 12000.0
    router.place_order.assert_not_called()


def test_custom_place_order_requires_explicit_buy_sell_side() -> None:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="ORDER-1")
    dispatcher = _dispatcher(_app(router), "place_order")
    payload = WebhookPayload(
        source="custom",
        action="place_order",
        symbol="RELIANCE",
        exchange="NSE",
        data={"quantity": "1"},
    )

    result = asyncio.run(dispatcher.place_order(payload))

    assert result["status"] == "error"
    assert "BUY or SELL" in result["message"]
    router.place_order.assert_not_called()


def test_cancel_order_runs_through_gate_and_router_with_signed_extras() -> None:
    router = MagicMock()
    router.cancel_order = AsyncMock(return_value=None)
    dispatcher = _dispatcher(_app(router), "cancel_order", selector="dhan:main")
    payload = WebhookPayload(
        source="custom",
        action="cancel_order",
        data={
            "selector": "openalgo:attacker-controlled",
            "orderid": "ORDER-7",
            "variety": "bracket",
            "amo": True,
        },
        webhook_nonce="cancel-nonce-1",
        webhook_path="/v1/webhook/custom/test-endpoint",
    )

    result = asyncio.run(dispatcher.cancel_order(payload))

    assert result["status"] == "cancelled"
    assert result["orderid"] == "ORDER-7"
    router.cancel_order.assert_awaited_once()
    request_ctx = router.cancel_order.await_args.args[0]
    kwargs = router.cancel_order.await_args.kwargs
    expected_hash = hashlib.sha256(b"cancel-nonce-1").hexdigest()
    assert request_ctx.actor_type == "external_intent"
    assert request_ctx.actor_id == "external_intent:webhook:test-endpoint"
    assert request_ctx.intent_source == "custom"
    assert request_ctx.selector == "dhan:main"
    assert request_ctx.external_nonce_hash == expected_hash
    assert kwargs["order"] == {
        "_op": "cancel",
        "order_id": "ORDER-7",
        "variety": "bracket",
        "amo": True,
    }
    assert kwargs["extras"] == {"variety": "bracket", "amo": True}
    assert kwargs["hint"].adapter_id == "dhan"
    assert kwargs["hint"].account_id == "main"
    assert kwargs["safety_ctx"].verify(kwargs["order"], request_ctx, "dhan", "main")
