"""Mounted webhook order intents must dispatch only through the gated router."""

from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from flask import Flask

from flinttrade_core.webhook_dispatch import WebhookOrderDispatcher
from flinttrade_engine.safety import set_safety_gate_secret
from flinttrade_webhooks.webhook_receiver import WebhookPayload


class PassingSafety:
    def check_order(self, *_args, **_kwargs):
        return [SimpleNamespace(passed=True)]


@pytest.fixture(autouse=True)
def _safety_secret() -> None:
    set_safety_gate_secret(b"w" * 32)


def _app(router: MagicMock) -> Flask:
    app = Flask("webhook-dispatch-test")
    app.config["BROKER_ROUTER"] = router
    app.config["SAFETY"] = PassingSafety()
    return app


def test_tradingview_place_order_runs_through_gate_and_router() -> None:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="ORDER-1")
    dispatcher = WebhookOrderDispatcher(_app(router))
    payload = WebhookPayload(
        source="tradingview",
        action="place_order",
        symbol="NIFTY",
        exchange="NSE",
        data={"tv_action": "BUY", "quantity": "1", "account_id": "default"},
        webhook_nonce="verified-nonce-1",
    )

    result = asyncio.run(dispatcher.place_order(payload))

    assert result["status"] == "placed"
    assert result["orderid"] == "ORDER-1"
    router.place_order.assert_awaited_once()
    request_ctx = router.place_order.await_args.args[0]
    kwargs = router.place_order.await_args.kwargs
    expected_hash = hashlib.sha256(b"verified-nonce-1").hexdigest()
    assert request_ctx.actor_type == "external_intent"
    assert request_ctx.actor_id == "external_intent:tradingview"
    assert request_ctx.intent_source == "tradingview"
    assert request_ctx.selector == "openalgo:default"
    assert request_ctx.external_nonce_hash == expected_hash
    assert kwargs["hint"].adapter_id == "openalgo"
    assert kwargs["hint"].account_id == "default"
    assert kwargs["safety_ctx"].verify(kwargs["order"], request_ctx, "openalgo", "default")


def test_custom_place_order_requires_explicit_buy_sell_side() -> None:
    router = MagicMock()
    router.place_order = AsyncMock(return_value="ORDER-1")
    dispatcher = WebhookOrderDispatcher(_app(router))
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
    dispatcher = WebhookOrderDispatcher(_app(router))
    payload = WebhookPayload(
        source="custom",
        action="cancel_order",
        data={
            "selector": "dhan:main",
            "orderid": "ORDER-7",
            "variety": "bracket",
            "amo": True,
        },
        webhook_nonce="cancel-nonce-1",
    )

    result = asyncio.run(dispatcher.cancel_order(payload))

    assert result["status"] == "cancelled"
    assert result["orderid"] == "ORDER-7"
    router.cancel_order.assert_awaited_once()
    request_ctx = router.cancel_order.await_args.args[0]
    kwargs = router.cancel_order.await_args.kwargs
    expected_hash = hashlib.sha256(b"cancel-nonce-1").hexdigest()
    assert request_ctx.actor_type == "external_intent"
    assert request_ctx.actor_id == "external_intent:custom"
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
