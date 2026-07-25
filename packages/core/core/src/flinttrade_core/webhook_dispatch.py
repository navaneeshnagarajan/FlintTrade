"""Safety-gated dispatch for mounted external webhook order intents."""

from __future__ import annotations

import hashlib
import inspect
import logging
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from flask import Flask
from pydantic import ValidationError

from flinttrade_core.exceptions import SafetyBypassError, UnsupportedCapabilityError
from flinttrade_engine.algo_tag_guard import AlgoTagLimitError
from flinttrade_engine.request_context import RequestContext, parse_selector
from flinttrade_engine.safety import gate_order
from flinttrade_gateway.exceptions import BrokerNotFoundError
from flinttrade_gateway.log_safety import account_ref, log_ref
from flinttrade_gateway.routing_config import RoutingHint
from flinttrade_webhooks.webhook_receiver import WebhookPayload

from .order_routes import _body_to_order, _record_trade_journal
from .safety_config import SafetyRuntimeUnavailable, require_ready_safety

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


@dataclass(frozen=True)
class WebhookExecutionAuthority:
    """Server-owned authority required before a webhook may write to a broker."""

    actor_id: str
    selector: str
    allowed_actions: frozenset[str]


WebhookAuthorityProvider = Callable[[WebhookPayload], WebhookExecutionAuthority | None]


class WebhookOrderDispatcher:
    """Core-owned bridge from WebhookReceiver actions to BrokerRouter writes.

    The integration package stays framework-agnostic and fail-closed by default.
    A signed intent reaches the human-order path only when the host injects an
    endpoint-specific execution authority: typed model -> SafetySystem ->
    gate_order -> BrokerRouter. Without that authority, no router method runs.
    """

    def __init__(
        self,
        app: Flask,
        *,
        authority_provider: WebhookAuthorityProvider | None = None,
    ) -> None:
        self._app = app
        self._authority_provider = authority_provider

    async def place_order(self, payload: WebhookPayload) -> dict[str, Any]:
        """Place a webhook-derived order through the gated broker router."""
        authority, authority_error = self._require_authority(payload, "place_order")
        if authority_error:
            return _error("place_order", payload, authority_error)
        assert authority is not None
        adapter_id, account_id, selector_error = _resolve_authority_selector(authority)
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
        acknowledgement_failed = False
        try:
            typed_order = _body_to_order(body, variety=_variety_from_payload(payload))
            try:
                safety = require_ready_safety(self._app.config)
            except SafetyRuntimeUnavailable:
                logger.error("Webhook place rejected - validated safety runtime unavailable")
                return _error(
                    "place_order",
                    payload,
                    "Validated order safety configuration is unavailable; no order was sent.",
                )
            selector = f"{adapter_id}:{account_id}"
            async with safety.order_admission_async(selector) as lease:
                portfolio_state = await self._gather_safety_state(
                    adapter_id,
                    account_id=account_id,
                    orders=[typed_order],
                    reservations=lease.reservations,
                )
                lease.reconcile(getattr(portfolio_state, "reconciled_reservation_ids", ()))
                admission = portfolio_state.admission_for(0)
                safety_results = safety.check_order(
                    typed_order,
                    selector=selector,
                    positions=admission.positions,
                    used_margin=admission.used_margin,
                    total_balance=portfolio_state.total_balance,
                    daily_pnl=portfolio_state.daily_pnl,
                    starting_capital=portfolio_state.starting_capital,
                    ltp=portfolio_state.ltp_for(typed_order),
                    net_delta=admission.net_delta,
                    net_vega=admission.net_vega,
                )
                blocked = next((check for check in safety_results if not check.passed), None)
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
                    actor_id=authority.actor_id,
                    mode="live",
                    intent_source=payload.source,
                    external_nonce_hash=nonce_hash,
                    selector=selector,
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
                reservation = lease.reserve(typed_order, admission.positions)
                result = await router.place_order(
                    request_ctx,
                    order=typed_order,
                    safety_ctx=safety_ctx,
                    hint=RoutingHint(adapter_id=adapter_id, account_id=account_id),
                )
                try:
                    lease.acknowledge(reservation, result)
                except Exception:
                    # The broker write has already succeeded. Reporting this as
                    # refused invites a duplicate retry; retain the unresolved
                    # reservation and surface a placed-with-warning result.
                    acknowledgement_failed = True
                    logger.critical(
                        "Webhook order placed but reservation acknowledgement failed | "
                        "source=%s adapter=%s account=%s",
                        payload.source,
                        adapter_id,
                        safe_account,
                        exc_info=True,
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

        audit_event = (
            "WEBHOOK_ORDER_PLACED_RESERVATION_UNACKNOWLEDGED"
            if acknowledgement_failed
            else "WEBHOOK_ORDER_PLACED"
        )
        self._audit(audit_event, adapter_id, account_id, authority.actor_id, payload, result)
        self._journal(
            typed_order,
            str(result),
            adapter_id=adapter_id,
            account_id=account_id,
            strategy=f"webhook:{payload.source}",
        )
        logger.info(
            "Webhook place dispatched | source=%s adapter=%s account=%s symbol=%s",
            payload.source,
            adapter_id,
            safe_account,
            payload.symbol or "?",
        )
        response = {
            "status": "placed",
            "action": "place_order",
            "symbol": payload.symbol,
            "exchange": payload.exchange,
            "adapter_id": adapter_id,
            "orderid": result,
        }
        if acknowledgement_failed:
            response["warning"] = (
                "Order was submitted, but local reservation tracking could not be acknowledged. "
                "Verify broker status before retrying."
            )
        return response

    async def cancel_order(self, payload: WebhookPayload) -> dict[str, Any]:
        """Cancel a webhook-specified order through the gated broker router."""
        authority, authority_error = self._require_authority(payload, "cancel_order")
        if authority_error:
            return _error("cancel_order", payload, authority_error)
        assert authority is not None
        adapter_id, account_id, selector_error = _resolve_authority_selector(authority)
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
                actor_id=authority.actor_id,
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

        self._audit("WEBHOOK_ORDER_CANCELLED", adapter_id, account_id, authority.actor_id, payload, order_id)
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

    def _require_authority(
        self,
        payload: WebhookPayload,
        action: str,
    ) -> tuple[WebhookExecutionAuthority | None, str | None]:
        """Resolve server-owned endpoint authority or fail closed."""
        if self._authority_provider is None:
            return None, "Webhook broker execution is not armed; no broker write was sent."
        try:
            authority = self._authority_provider(payload)
        except Exception:
            logger.exception("Webhook execution authority lookup failed")
            return None, "Webhook broker execution authority is unavailable."
        if authority is None:
            return None, "Webhook broker execution is not armed; no broker write was sent."
        if action not in authority.allowed_actions:
            return None, f"Webhook endpoint is not authorised for {action}."
        if not authority.actor_id.strip() or not authority.selector.strip():
            return None, "Webhook broker execution authority is incomplete."
        return authority, None

    async def _gather_safety_state(
        self,
        adapter_id: str,
        *,
        account_id: str,
        orders: list[Any] | tuple[Any, ...] = (),
        reservations: list[Any] | tuple[Any, ...] = (),
    ) -> Any:
        # Delegates to the same complete L2/L4 gather used by human orders. An
        # unavailable local daily-P&L snapshot raises and the outer dispatcher
        # refuses the webhook before any gate can be minted.
        from .l2_state import gather_safety_state  # noqa: PLC0415

        return await gather_safety_state(
            self._app.config,
            adapter_id,
            account_id=account_id,
            orders=orders,
            reservations=reservations,
            include_order_margin=True,
        )

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

    def _journal(
        self,
        typed_order: Any,
        order_id: str,
        *,
        adapter_id: str,
        account_id: str,
        strategy: str,
    ) -> None:
        try:
            with self._app.app_context():
                _record_trade_journal(typed_order, order_id, strategy=strategy)
        except Exception:
            logger.debug("webhook trade journal stamp failed", exc_info=True)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _resolve_authority_selector(
    authority: WebhookExecutionAuthority,
) -> tuple[str, str, str | None]:
    try:
        adapter_id, account_id = parse_selector(authority.selector)
    except ValueError:
        return "", "", "Webhook execution authority has an invalid account selector."
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
    price_error = _validate_order_prices(body)
    if price_error:
        return {}, price_error
    return body, None


def _order_side(payload: WebhookPayload) -> str:
    values = {
        str(payload.data.get(key) or "").strip().upper()
        for key in ("side", "order_action", "transaction_type")
        if str(payload.data.get(key) or "").strip()
    }
    if len(values) != 1:
        return ""
    value = values.pop()
    return value if value in {"BUY", "SELL"} else ""


def _validate_order_prices(body: dict[str, Any]) -> str | None:
    """Reject malformed executable prices before any SafetyContext is minted."""
    values: dict[str, float] = {}
    for field in ("price", "trigger_price"):
        raw = str(body.get(field, "0")).strip() or "0"
        try:
            parsed = float(raw)
        except (TypeError, ValueError):
            return f"Webhook order has an invalid {field}."
        if not math.isfinite(parsed) or parsed < 0:
            return f"Webhook order has an invalid {field}."
        body[field] = raw
        values[field] = parsed

    pricetype = str(body.get("pricetype") or body.get("order_type") or "MARKET").strip().upper()
    if pricetype in {"LIMIT", "SL"} and values["price"] <= 0:
        return f"Webhook {pricetype} order requires a positive price."
    if pricetype in {"SL", "SL-M"} and values["trigger_price"] <= 0:
        return f"Webhook {pricetype} order requires a positive trigger price."

    for field in ("price1", "trigger_price1"):
        if field not in body or body[field] is None:
            continue
        raw = str(body[field]).strip()
        try:
            parsed = float(raw)
        except (TypeError, ValueError):
            return f"Webhook order has an invalid {field}."
        if not math.isfinite(parsed) or parsed <= 0:
            return f"Webhook order requires a positive {field}."
        body[field] = raw

    if "quantity1" in body and body["quantity1"] is not None:
        raw_quantity = str(body["quantity1"]).strip()
        try:
            quantity = int(raw_quantity)
        except (TypeError, ValueError):
            return "Webhook order has an invalid quantity1."
        if quantity <= 0:
            return "Webhook order requires a positive quantity1."
        body["quantity1"] = raw_quantity
    return None


def _variety_from_payload(payload: WebhookPayload) -> str | None:
    variety = str(payload.data.get("variety") or "regular").strip().lower()
    return None if variety == "regular" else variety


def _nonce_and_hash(payload: WebhookPayload) -> tuple[str, str]:
    nonce = str(payload.webhook_nonce or uuid.uuid4().hex)
    return nonce, hashlib.sha256(nonce.encode("utf-8")).hexdigest()


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
