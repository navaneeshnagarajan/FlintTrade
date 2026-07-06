"""Safety-gated dispatch for mounted external webhook order intents."""

from __future__ import annotations

import hashlib
import inspect
import logging
import uuid
from typing import Any

from flask import Flask
from pydantic import ValidationError

from flinttrade_core.exceptions import SafetyBypassError, UnsupportedCapabilityError
from flinttrade_engine.algo_tag_guard import AlgoTagLimitError
from flinttrade_engine.request_context import RequestContext, parse_selector
from flinttrade_engine.safety import SafetyConfig, SafetySystem, gate_order
from flinttrade_gateway.exceptions import BrokerNotFoundError
from flinttrade_gateway.log_safety import account_ref, log_ref
from flinttrade_gateway.routing_config import RoutingHint
from flinttrade_webhooks.webhook_receiver import WebhookPayload

from .order_routes import _body_to_order, _record_trade_journal

logger = logging.getLogger("flinttrade.core.webhook_dispatch")

_ORDER_FIELDS = {
    "quantity",
    "price",
    "trigger_price",
    "pricetype",
    "order_type",
    "product",
    "disclosed_quantity",
    "strategy",
    "market_protection",
    "validity",
    "price1",
    "trigger_price1",
    "quantity1",
}


class WebhookOrderDispatcher:
    """Core-owned bridge from WebhookReceiver actions to BrokerRouter writes.

    The integration package stays framework-agnostic and fail-closed by default.
    The Flask app injects this object when the mounted receiver is registered,
    giving signed webhook order intents the same live path as human orders:
    typed model -> SafetySystem -> gate_order -> BrokerRouter.
    """

    def __init__(self, app: Flask) -> None:
        self._app = app

    async def place_order(self, payload: WebhookPayload) -> dict[str, Any]:
        """Place a webhook-derived order through the gated broker router."""
        adapter_id, account_id, selector_error = _resolve_selector(payload)
        if selector_error:
            return _error("place_order", payload, selector_error)

        router = self._app.config.get("BROKER_ROUTER")
        if router is None:
            logger.error("Webhook place rejected - BROKER_ROUTER unavailable")
            return _error(
                "place_order",
                payload,
                "Webhook order routing is unavailable - broker router is not configured.",
            )

        body, body_error = _payload_to_order_body(payload)
        if body_error:
            return _error("place_order", payload, body_error)

        safe_account = account_ref(account_id)
        try:
            typed_order = _body_to_order(body, variety=_variety_from_payload(payload))
            l2_positions, l2_used_margin, l2_total_balance = await self._gather_l2_state(
                adapter_id,
                account_id=account_id,
            )
            safety = self._app.config.get("SAFETY")
            if safety is None:
                safety = SafetySystem(SafetyConfig())
            safety_results = safety.check_order(
                typed_order,
                positions=l2_positions,
                used_margin=l2_used_margin,
                total_balance=l2_total_balance,
            )
            blocked = next((result for result in safety_results if not result.passed), None)
            if blocked is not None:
                logger.warning(
                    "Webhook place blocked by safety layer %s | source=%s adapter=%s symbol=%s: %s",
                    blocked.layer,
                    payload.source,
                    adapter_id,
                    payload.symbol or "?",
                    blocked.reason,
                )
                return _error(
                    "place_order",
                    payload,
                    f"Order blocked by safety system [{blocked.layer}]: {blocked.reason}",
                )

            nonce, nonce_hash = _nonce_and_hash(payload)
            request_ctx = RequestContext(
                jti=f"webhook-{payload.source}-{uuid.uuid4().hex}",
                actor_type="external_intent",
                actor_id=_actor_id(payload),
                mode="live",
                intent_source=payload.source,
                external_nonce_hash=nonce_hash,
                selector=f"{adapter_id}:{account_id}",
            )
            safety_ctx = gate_order(
                typed_order,
                request_ctx,
                adapter_id=adapter_id,
                account_id=account_id,
                actor_type="external_intent",
                intent_source=payload.source,
                external_nonce=nonce,
            )
            result = await router.place_order(
                request_ctx,
                order=typed_order,
                safety_ctx=safety_ctx,
                hint=RoutingHint(adapter_id=adapter_id, account_id=account_id),
            )
        except (ValueError, ValidationError) as exc:
            logger.warning(
                "Webhook place rejected by validation | source=%s adapter=%s: %s",
                payload.source,
                adapter_id,
                exc,
            )
            return _error("place_order", payload, "Webhook order validation failed.")
        except SafetyBypassError as exc:
            logger.warning(
                "Webhook place refused by safety gate | source=%s adapter=%s account=%s: %s",
                payload.source,
                adapter_id,
                safe_account,
                _redact_detail(exc, account_id),
            )
            return _error("place_order", payload, "Webhook order refused.")
        except AlgoTagLimitError:
            logger.warning(
                "Webhook place refused by algo-tag guard | source=%s adapter=%s account=%s",
                payload.source,
                adapter_id,
                safe_account,
            )
            return _error("place_order", payload, "Webhook order refused by rate guard.")
        except (BrokerNotFoundError, KeyError) as exc:
            logger.warning(
                "Webhook place broker session unavailable | source=%s adapter=%s account=%s: %s",
                payload.source,
                adapter_id,
                safe_account,
                _redact_detail(exc, account_id),
            )
            return _error("place_order", payload, "Webhook broker session unavailable.")
        except (NotImplementedError, UnsupportedCapabilityError) as exc:
            logger.warning(
                "Webhook place capability unavailable | source=%s adapter=%s account=%s: %s",
                payload.source,
                adapter_id,
                safe_account,
                _redact_detail(exc, account_id),
            )
            return _error(
                "place_order",
                payload,
                f"Webhook order placement is not yet available for broker '{adapter_id}'.",
            )
        except Exception:
            logger.exception(
                "Webhook place dispatch failed | source=%s adapter=%s account=%s",
                payload.source,
                adapter_id,
                safe_account,
            )
            return _error("place_order", payload, "Webhook order dispatch failed.")

        self._audit("WEBHOOK_ORDER_PLACED", adapter_id, account_id, _actor_id(payload), payload, result)
        self._journal(typed_order, str(result), strategy=f"webhook:{payload.source}")
        logger.info(
            "Webhook place dispatched | source=%s adapter=%s account=%s symbol=%s",
            payload.source,
            adapter_id,
            safe_account,
            payload.symbol or "?",
        )
        return {
            "status": "placed",
            "action": "place_order",
            "symbol": payload.symbol,
            "exchange": payload.exchange,
            "adapter_id": adapter_id,
            "orderid": result,
        }

    async def cancel_order(self, payload: WebhookPayload) -> dict[str, Any]:
        """Cancel a webhook-specified order through the gated broker router."""
        adapter_id, account_id, selector_error = _resolve_selector(payload)
        if selector_error:
            return _error("cancel_order", payload, selector_error)

        router = self._app.config.get("BROKER_ROUTER")
        if router is None:
            logger.error("Webhook cancel rejected - BROKER_ROUTER unavailable")
            return _error(
                "cancel_order",
                payload,
                "Webhook order routing is unavailable - broker router is not configured.",
            )

        order_id = _order_id(payload)
        if not order_id:
            return _error("cancel_order", payload, "Webhook cancel requires an 'orderid'.")

        extras: dict[str, Any] = {}
        if payload.data.get("variety") is not None:
            extras["variety"] = str(payload.data["variety"])
        if payload.data.get("amo") is not None:
            extras["amo"] = bool(payload.data["amo"])

        canonical = {"_op": "cancel", "order_id": order_id, **extras}
        safe_account = account_ref(account_id)
        safe_order = log_ref(order_id, kind="order")
        try:
            nonce, nonce_hash = _nonce_and_hash(payload)
            request_ctx = RequestContext(
                jti=f"webhook-{payload.source}-{uuid.uuid4().hex}",
                actor_type="external_intent",
                actor_id=_actor_id(payload),
                mode="live",
                intent_source=payload.source,
                external_nonce_hash=nonce_hash,
                selector=f"{adapter_id}:{account_id}",
            )
            safety_ctx = gate_order(
                canonical,
                request_ctx,
                adapter_id=adapter_id,
                account_id=account_id,
                actor_type="external_intent",
                intent_source=payload.source,
                external_nonce=nonce,
            )
            await router.cancel_order(
                request_ctx,
                order=canonical,
                order_id=order_id,
                safety_ctx=safety_ctx,
                hint=RoutingHint(adapter_id=adapter_id, account_id=account_id),
                extras=extras or None,
            )
        except SafetyBypassError as exc:
            logger.warning(
                "Webhook cancel refused by safety gate | source=%s order=%s adapter=%s account=%s: %s",
                payload.source,
                safe_order,
                adapter_id,
                safe_account,
                _redact_detail(exc, account_id),
            )
            return _error("cancel_order", payload, "Webhook cancel refused.")
        except AlgoTagLimitError:
            logger.warning(
                "Webhook cancel refused by algo-tag guard | source=%s order=%s adapter=%s account=%s",
                payload.source,
                safe_order,
                adapter_id,
                safe_account,
            )
            return _error("cancel_order", payload, "Webhook cancel refused by rate guard.")
        except (BrokerNotFoundError, KeyError) as exc:
            logger.warning(
                "Webhook cancel broker session unavailable | source=%s order=%s adapter=%s account=%s: %s",
                payload.source,
                safe_order,
                adapter_id,
                safe_account,
                _redact_detail(exc, account_id),
            )
            return _error("cancel_order", payload, "Webhook broker session unavailable.")
        except (NotImplementedError, UnsupportedCapabilityError) as exc:
            logger.warning(
                "Webhook cancel capability unavailable | source=%s order=%s adapter=%s account=%s: %s",
                payload.source,
                safe_order,
                adapter_id,
                safe_account,
                _redact_detail(exc, account_id),
            )
            return _error(
                "cancel_order",
                payload,
                f"Webhook order cancellation is not yet available for broker '{adapter_id}'.",
            )
        except Exception:
            logger.exception(
                "Webhook cancel dispatch failed | source=%s order=%s adapter=%s account=%s",
                payload.source,
                safe_order,
                adapter_id,
                safe_account,
            )
            return _error("cancel_order", payload, "Webhook cancel dispatch failed.")

        self._audit("WEBHOOK_ORDER_CANCELLED", adapter_id, account_id, _actor_id(payload), payload, order_id)
        logger.info(
            "Webhook cancel dispatched | source=%s order=%s adapter=%s account=%s",
            payload.source,
            safe_order,
            adapter_id,
            safe_account,
        )
        return {
            "status": "cancelled",
            "action": "cancel_order",
            "symbol": payload.symbol,
            "adapter_id": adapter_id,
            "orderid": order_id,
        }

    async def _gather_l2_state(self, adapter_id: str, *, account_id: str) -> tuple[list[Any], float, float]:
        # Delegates to the ONE shared L2 input-gathering implementation (also
        # used by the human order route) so the openalgo-vs-native branch and
        # error classification can never drift between two copies.
        from .l2_state import gather_l2_state  # noqa: PLC0415

        return await gather_l2_state(self._app.config, adapter_id, account_id=account_id)

    def _audit(
        self,
        event_type: str,
        adapter_id: str,
        account_id: str,
        actor_id: str,
        payload: WebhookPayload,
        result: Any,
    ) -> None:
        try:
            audit = self._app.config.get("AUDIT")
            if audit is not None:
                audit.log_event(
                    event_type,
                    adapter_id=adapter_id,
                    account_id=account_id,
                    actor_id=actor_id,
                    source=payload.source,
                    webhook_path=payload.webhook_path,
                    symbol=payload.symbol,
                    result=str(result),
                )
        except Exception:
            logger.debug("webhook audit stamp failed", exc_info=True)

    def _journal(self, typed_order: Any, order_id: str, *, strategy: str) -> None:
        try:
            with self._app.app_context():
                _record_trade_journal(typed_order, order_id, strategy=strategy)
        except Exception:
            logger.debug("webhook trade journal stamp failed", exc_info=True)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _resolve_selector(payload: WebhookPayload) -> tuple[str, str, str | None]:
    selector = str(payload.data.get("selector") or "").strip()
    if selector:
        try:
            adapter_id, account_id = parse_selector(selector)
        except ValueError:
            return "", "", "Webhook selector must be 'adapter_id:account_id'."
        return adapter_id, account_id, None

    adapter_id = str(
        payload.data.get("adapter_id")
        or payload.data.get("broker_id")
        or payload.data.get("broker")
        or "openalgo"
    ).strip().lower()
    account_id = str(payload.data.get("account_id") or "default").strip()
    if not adapter_id:
        return "", "", "Webhook broker adapter is required."
    if not account_id:
        return "", "", "Webhook broker account is required."
    return adapter_id, account_id, None


def _payload_to_order_body(payload: WebhookPayload) -> tuple[dict[str, Any], str | None]:
    if not payload.symbol:
        return {}, "Webhook order requires a symbol."

    side = _order_side(payload)
    if side not in {"BUY", "SELL"}:
        return {}, "Webhook order requires side/action BUY or SELL."

    body = {key: payload.data[key] for key in _ORDER_FIELDS if key in payload.data}
    body.update({
        "symbol": payload.symbol,
        "exchange": payload.exchange or payload.data.get("exchange") or "NSE",
        "action": side,
    })
    return body, None


def _order_side(payload: WebhookPayload) -> str:
    for key in ("tv_action", "side", "order_action", "transaction_type"):
        value = str(payload.data.get(key) or "").strip().upper()
        if value:
            return value
    return ""


def _variety_from_payload(payload: WebhookPayload) -> str | None:
    variety = str(payload.data.get("variety") or "regular").strip().lower()
    return None if variety == "regular" else variety


def _nonce_and_hash(payload: WebhookPayload) -> tuple[str, str]:
    nonce = str(payload.webhook_nonce or uuid.uuid4().hex)
    return nonce, hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def _actor_id(payload: WebhookPayload) -> str:
    return f"external_intent:{payload.source}"


def _order_id(payload: WebhookPayload) -> str:
    return str(payload.data.get("orderid") or payload.data.get("order_id") or "").strip()


def _error(action: str, payload: WebhookPayload, message: str) -> dict[str, Any]:
    return {
        "status": "error",
        "action": action,
        "symbol": payload.symbol,
        "exchange": payload.exchange,
        "message": message,
    }


def _redact_detail(exc: BaseException, account_id: str) -> str:
    detail = str(exc)
    if account_id:
        detail = detail.replace(account_id, account_ref(account_id))
    return detail
