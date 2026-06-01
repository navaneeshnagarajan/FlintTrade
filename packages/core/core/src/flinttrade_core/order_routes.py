"""Order proxy blueprint — mode-enforcing gateway for all order operations.

This module is a CRITICAL SAFETY LAYER.  Every order request from the
frontend MUST pass through here before reaching OpenAlgo.  The blueprint
reads the ``mode`` claim from the *server-issued JWT* (not from any
client-controlled header) and routes accordingly:

- ``explore``  → 403 — no orders permitted in demo mode
- ``practice`` → SandboxEngine (paper trading, no real money)
- ``live``     → OpenAlgo REST API (real broker, real money)

The ``mode`` claim is set at login/PIN-verify time and cannot be forged
without the JWT secret.  The legacy ``X-FlintTrade-Mode`` header is still
read as a *hint* for logging/debugging purposes only — it is never trusted
for routing decisions.

Any ambiguity defaults to rejection rather than accidental live execution.

Architecture::

    Frontend → POST /v1/orders/<action>
             → order_routes.py (reads JWT ``mode`` claim)
             → explore  → 403
             → practice → SandboxEngine.place_order(...)
             → live     → httpx → OpenAlgo /api/v1/<endpoint>

Blueprint prefix: ``/v1/orders``
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

import httpx
import jwt
from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger("flinttrade.order_routes")

# Frontend `api.ts` posts to `/ft-api/api/v1/orders/<X>` (→ `/api/v1/orders/<X>`
# after the WSGI prefix strip). The blueprint must therefore live under
# `/api/v1/orders`, not the project's general `/v1/X` convention. (Previously
# registered at `/v1/orders/*`, which silently 404'd every order placement
# until the 2026-05-19 multi-agent audit surfaced it.) The engine's
# `order_bp` (advanced orders: basket/split/options-strategy) sits alongside
# this blueprint at the same prefix with non-overlapping routes.
orders_bp = Blueprint("orders", __name__, url_prefix="/api/v1/orders")

# ---------------------------------------------------------------------------
# Valid trading modes
# ---------------------------------------------------------------------------

_MODE_EXPLORE = "explore"
_MODE_PRACTICE = "practice"
_MODE_LIVE = "live"

_VALID_MODES = frozenset({_MODE_EXPLORE, _MODE_PRACTICE, _MODE_LIVE})

# ---------------------------------------------------------------------------
# OpenAlgo endpoint map — FlintTrade route suffix → OpenAlgo endpoint name
# ---------------------------------------------------------------------------

_ENDPOINT_MAP: dict[str, str] = {
    "place":          "placeorder",
    "place-smart":    "placesmartorder",
    "modify":         "modifyorder",
    "cancel":         "cancelorder",
    "cancel-all":     "cancelallorder",
    "close-position": "closeposition",
    "open-position":  "openposition",
    "options":        "optionsorder",
    "options-multi":  "optionsmultiorder",
    # GTT — Good Till Triggered orders (added in OpenAlgo v2.0.0.9).
    # Live broker support upstream: Dhan + Zerodha. Other brokers respond
    # with a 501 that this dispatcher propagates unchanged so the UI can
    # surface the actual error message.
    "gtt-place":      "placegttorder",
    "gtt-modify":     "modifygttorder",
    "gtt-cancel":     "cancelgttorder",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_mode_from_jwt() -> str | None:
    """Extract the ``mode`` claim from the request's Bearer JWT.

    Returns:
        The mode string (``"explore"``, ``"practice"``, or ``"live"``) from
        the JWT payload, or ``None`` if the token is absent, expired, or
        invalid.
    """
    from .auth_routes import decode_token  # noqa: PLC0415

    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        token = request.headers.get("X-FlintTrade-Token", "").strip()
    if not token:
        return None

    try:
        payload = decode_token(token)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None

    return payload.get("mode") or None


def _is_live_mode_unlocked() -> bool:
    """Check whether the current request carries a JWT with ``live_mode_unlocked``.

    Extracts the Bearer token from the ``Authorization`` header, decodes it
    using the shared JWT secret from :mod:`auth_routes`, and inspects the
    ``live_mode_unlocked`` claim.

    Returns:
        ``True`` if the JWT is valid and contains ``live_mode_unlocked: true``.
        ``False`` otherwise (missing token, expired, invalid, or claim absent).
    """
    from .auth_routes import decode_token  # noqa: PLC0415

    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        # Also try X-API-Key — some callers may send the JWT there
        token = request.headers.get("X-FlintTrade-Token", "").strip()
    if not token:
        return False

    try:
        payload = decode_token(token)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return False

    return bool(payload.get("live_mode_unlocked"))


def _openalgo_base_url() -> str:
    """Resolve the OpenAlgo base URL from app config or environment.

    Checks ``app.config["CLIENT"]`` first (has ``settings.openalgo_host``),
    then falls back to the ``OPENALGO_HOST`` / ``OPENALGO_PORT`` env vars.

    Returns:
        Base URL string, e.g. ``"http://127.0.0.1:5000"``, trailing slash stripped.
    """
    client = current_app.config.get("CLIENT")
    if client is not None:
        try:
            return client.settings.openalgo_host.rstrip("/")
        except AttributeError:
            pass

    host = os.environ.get("OPENALGO_HOST", "http://127.0.0.1").rstrip("/")
    port = os.environ.get("OPENALGO_PORT", "5000")
    return f"{host}:{port}"


def _openalgo_api_key() -> str:
    """Return the OpenAlgo API key from environment.

    Returns:
        API key string (may be empty — callers should handle that case).
    """
    return os.environ.get("OPENALGO_API_KEY", "")


def _forward_to_openalgo(endpoint: str, body: dict[str, Any]) -> tuple[Any, int]:
    """Forward a validated order request to OpenAlgo synchronously via httpx.

    Injects the OpenAlgo API key into the request body (OpenAlgo's REST API
    requires ``apikey`` in the JSON payload, not in a header).

    Args:
        endpoint: OpenAlgo endpoint name, e.g. ``"placeorder"``.
        body: JSON-decoded request body from the frontend.

    Returns:
        A ``(flask.Response, http_status_code)`` tuple ready to be returned
        from a Flask route handler.
    """
    api_key = _openalgo_api_key()
    if not api_key:
        logger.error(
            "OPENALGO_API_KEY not configured — cannot forward live order to %s", endpoint
        )
        return jsonify({
            "status": "error",
            "message": "Server not configured — OpenAlgo API key missing",
        }), 503

    url = f"{_openalgo_base_url()}/api/v1/{endpoint}"
    payload = dict(body)
    payload["apikey"] = api_key  # OpenAlgo requires key in body
    # Upstream marks ``strategy`` as required on every order endpoint
    # (Place/Modify/Cancel for regular orders AND GTT). Frontends omit
    # it for ergonomic reasons — inject a stable default so a missing
    # field never triggers a 400 from upstream. Callers that supply
    # their own ``strategy`` (BacktestLab, AI agent, etc.) win.
    if not payload.get("strategy"):
        payload["strategy"] = "Flint"

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload)
    except httpx.ConnectError as exc:
        logger.error(
            "OpenAlgo unreachable at %s whilst forwarding %s: %s", url, endpoint, exc
        )
        return jsonify({
            "status": "error",
            "message": "OpenAlgo unreachable — check that the broker gateway is running",
        }), 502
    except httpx.TimeoutException as exc:
        logger.error("OpenAlgo request timed out for %s: %s", endpoint, exc)
        return jsonify({
            "status": "error",
            "message": "OpenAlgo request timed out",
        }), 504
    except httpx.HTTPError as exc:
        logger.error("HTTP error forwarding %s to OpenAlgo: %s", endpoint, exc)
        return jsonify({
            "status": "error",
            "message": "Unexpected HTTP error communicating with OpenAlgo",
        }), 502

    try:
        data = response.json()
    except Exception:
        # OpenAlgo returned non-JSON — propagate the status code raw
        data = {"status": "error", "message": f"Non-JSON response from OpenAlgo (HTTP {response.status_code})"}

    return jsonify(data), response.status_code


def _body_to_order(body: dict[str, Any]) -> Any:
    """Build a typed :class:`Order` from a decoded request body for the SafetySystem.

    The legacy path forwarded the raw dict; the 5-layer ``SafetySystem.check_order``
    needs the typed model to validate symbol, quantity, price, exchange, and market
    hours. Enum coercion (action/exchange/product/pricetype) raises ``ValueError`` on
    a bad value, which the caller maps to HTTP 400 rather than letting it 500.
    """
    from flinttrade_core.models import (  # noqa: PLC0415
        Action,
        Exchange,
        Order,
        PriceType,
        Product,
    )

    # Quantity is an OpenAlgo string field but must be a whole number of units —
    # validate up-front so a fat-finger "10.5"/"abc" is a clean 400, not a 500
    # from the int(...) coercion inside SafetySystem.check_order.
    quantity = str(body.get("quantity", "1"))
    try:
        if int(quantity) < 0:
            raise ValueError("must be non-negative")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"quantity must be a whole number of units, got {quantity!r}") from exc

    return Order(
        symbol=str(body.get("symbol") or ""),
        action=Action(str(body.get("action", "BUY")).upper()),
        exchange=Exchange(str(body.get("exchange", "NSE")).upper()),
        pricetype=PriceType(
            str(body.get("pricetype") or body.get("order_type") or "MARKET").upper()
        ),
        product=Product(str(body.get("product", "MIS")).upper()),
        quantity=quantity,
        price=str(body.get("price", "0")),
        trigger_price=str(body.get("trigger_price", "0")),
        disclosed_quantity=str(body.get("disclosed_quantity", "0")),
        strategy=str(body.get("strategy") or "Flint"),
        market_protection=body.get("market_protection"),
    )


def _live_kill_switch_block() -> Any | None:
    """Return the failing L5 kill-switch result, or ``None`` if trading is allowed.

    The minimum guard applied to every NON-place live action (modify/cancel/etc.)
    that cannot yet route through the gated :class:`BrokerRouter` — a halted
    account must not be able to push any live order even on the direct-forward path.
    """
    from flinttrade_engine.safety import SafetyConfig, SafetySystem  # noqa: PLC0415

    safety = current_app.config.get("SAFETY")
    if safety is None:
        safety = SafetySystem(SafetyConfig())
    result = safety.l5_kill.validate()
    return None if result.passed else result


def _dispatch_live_order(
    ft_action: str,
    body: dict[str, Any],
    payload: dict[str, Any],
    *,
    adapter_id: str = "openalgo",
) -> tuple[Any, int]:
    """The single enforced execution channel for a live order placement (C1).

    Runs the 5-layer ``SafetySystem`` (L1-L5 risk validation), then mints a
    one-shot selector-bound ``SafetyContext`` via ``gate_order`` and dispatches
    through the app's :class:`BrokerRouter` — which ACL-checks the ``(actor,
    account)`` and re-verifies the gate before any broker write. Used by BOTH the
    legacy ``/place`` live branch (``adapter_id="openalgo"``) and the
    ``/<broker>/place`` routed endpoint, so live placement has exactly one gated
    path. Fails CLOSED with an actionable message on every misconfiguration — it
    never forwards an ungated order.
    """
    import asyncio  # noqa: PLC0415

    from pydantic import ValidationError  # noqa: PLC0415

    from flinttrade_core.exceptions import SafetyBypassError  # noqa: PLC0415
    from flinttrade_engine.request_context import RequestContext  # noqa: PLC0415
    from flinttrade_engine.safety import (  # noqa: PLC0415
        SafetyConfig,
        SafetySystem,
        gate_order,
    )
    from flinttrade_gateway.exceptions import BrokerNotFoundError  # noqa: PLC0415
    from flinttrade_gateway.routing_config import RoutingHint  # noqa: PLC0415

    account_id = str(body.get("account_id") or "default")

    router = current_app.config.get("BROKER_ROUTER")
    if router is None:
        logger.error(
            "Live order rejected — BROKER_ROUTER unavailable | action=%s adapter=%s",
            ft_action, adapter_id,
        )
        return jsonify({
            "status": "error",
            "message": (
                "Order routing unavailable — workspace.json brokers configuration is "
                "missing or invalid. Check the startup logs, fix workspace.json, then restart."
            ),
        }), 503

    request_ctx = RequestContext(
        jti=str(payload.get("jti") or ""),
        actor_type="human",
        actor_id=str(payload.get("sub") or payload.get("actor_id") or "unknown"),
        mode=_MODE_LIVE,
        selector=f"{adapter_id}:{account_id}",
    )

    # --- 5-layer SafetySystem (L1 order, L2 positions, L3 greeks, L4 P&L, L5 kill) ---
    safety = current_app.config.get("SAFETY")
    if safety is None:
        safety = SafetySystem(SafetyConfig())
    try:
        typed_order = _body_to_order(body)
        # check_order coerces quantity via int(...); a non-integer quantity must
        # surface as a clean 400, not an uncaught ValueError -> 500.
        safety_results = safety.check_order(typed_order)
    except (ValueError, ValidationError) as exc:
        logger.warning(
            "Live order rejected by order-model/safety validation | action=%s adapter=%s: %s",
            ft_action, adapter_id, exc,
        )
        return jsonify({"status": "error", "message": f"Order validation failed: {exc}"}), 400

    blocked = next((r for r in safety_results if not r.passed), None)
    if blocked is not None:
        logger.warning(
            "Live order blocked by safety layer %s | action=%s adapter=%s symbol=%s: %s",
            blocked.layer, ft_action, adapter_id, body.get("symbol", "?"), blocked.reason,
        )
        return jsonify({
            "status": "error",
            "message": f"Order blocked by safety system [{blocked.layer}]: {blocked.reason}",
        }), 403

    # --- gate + ACL + one-shot dispatch through the BrokerRouter ---
    # Dispatch the TYPED Order (not the raw dict): the broker adapters and the
    # OpenAlgoClient read typed attributes (order.symbol, order.action.value, …),
    # so a dict would AttributeError at the broker boundary. gate_order mints and
    # the router re-verifies over the SAME typed_order object, keeping the
    # order-binding fingerprint consistent end-to-end.
    try:
        safety_ctx = gate_order(typed_order, request_ctx, adapter_id=adapter_id, account_id=account_id)
        result = asyncio.run(
            router.place_order(
                request_ctx,
                order=typed_order,
                safety_ctx=safety_ctx,
                hint=RoutingHint(adapter_id=adapter_id, account_id=account_id),
            )
        )
    except SafetyBypassError as exc:
        logger.warning(
            "Live order refused by safety gate | action=%s adapter=%s account=%s: %s",
            ft_action, adapter_id, account_id, exc,
        )
        return jsonify({"status": "error", "message": f"Order refused: {exc}"}), 403
    except (BrokerNotFoundError, KeyError) as exc:
        logger.warning(
            "Live order — broker not connected | action=%s adapter=%s account=%s: %s",
            ft_action, adapter_id, account_id, exc,
        )
        return jsonify({
            "status": "error",
            "message": (
                f"Broker '{adapter_id}' (account '{account_id}') is not connected. Add the "
                "selector to workspace.json brokers.registered and brokers.account_acls, then restart."
            ),
        }), 503
    except Exception:
        logger.exception(
            "Live order dispatch failed | action=%s adapter=%s account=%s",
            ft_action, adapter_id, account_id,
        )
        return jsonify({"status": "error", "message": "Order dispatch failed"}), 500

    # Audit trail (best-effort — never break the order path).
    try:
        audit = current_app.config.get("AUDIT")
        if audit is not None:
            audit.log_event(
                "ORDER_PLACED",
                adapter_id=adapter_id,
                account_id=account_id,
                actor_id=request_ctx.actor_id,
                symbol=body.get("symbol"),
                action=ft_action,
            )
    except Exception:  # pragma: no cover — audit must never break the order path
        logger.debug("audit stamp failed for live order", exc_info=True)

    logger.info(
        "Live order dispatched | action=%s adapter=%s account=%s symbol=%s",
        ft_action, adapter_id, account_id, body.get("symbol", "?"),
    )
    # Return both keys: ``orderid`` (legacy OpenAlgo response shape the UI reads)
    # and ``data`` (the routed-path shape) so the frontend works either way.
    return jsonify({"status": "success", "orderid": result, "data": result}), 200


def _audit_write_event(
    event_type: str, adapter_id: str, account_id: str, actor_id: str, order_id: str
) -> None:
    """Best-effort audit stamp for a gated broker write (never breaks the order path)."""
    try:
        audit = current_app.config.get("AUDIT")
        if audit is not None:
            audit.log_event(
                event_type,
                adapter_id=adapter_id,
                account_id=account_id,
                actor_id=actor_id,
                order_id=order_id,
            )
    except Exception:  # pragma: no cover — audit must never break the order path
        logger.debug("audit stamp failed for %s", event_type, exc_info=True)


def _gated_write_dispatch(
    op: str,
    canonical_order: dict[str, Any],
    payload: dict[str, Any],
    *,
    adapter_id: str,
    account_id: str,
    order_id: str,
    dispatch: Callable[[Any, Any, Any], Any],
    audit_event: str,
    fail_message: str,
) -> tuple[Any, int]:
    """Shared gate -> ACL -> one-shot dispatch + fail-closed mapping for modify/cancel.

    ``canonical_order`` is the fingerprint ``gate_order`` signs and the router
    re-verifies; ``dispatch(router, request_ctx, safety_ctx)`` returns the broker
    coroutine. Mirrors the ``place`` path's fail-closed matrix
    (503/403/503/500) and echoes ``order_id`` on success.
    """
    import asyncio  # noqa: PLC0415

    from flinttrade_core.exceptions import SafetyBypassError  # noqa: PLC0415
    from flinttrade_engine.request_context import RequestContext  # noqa: PLC0415
    from flinttrade_engine.safety import gate_order  # noqa: PLC0415
    from flinttrade_gateway.exceptions import BrokerNotFoundError  # noqa: PLC0415

    router = current_app.config.get("BROKER_ROUTER")
    if router is None:
        logger.error("Live %s rejected — BROKER_ROUTER unavailable | adapter=%s", op, adapter_id)
        return jsonify({
            "status": "error",
            "message": (
                "Order routing unavailable — workspace.json brokers configuration is "
                "missing or invalid. Check the startup logs, fix workspace.json, then restart."
            ),
        }), 503

    request_ctx = RequestContext(
        jti=str(payload.get("jti") or ""),
        actor_type="human",
        actor_id=str(payload.get("sub") or payload.get("actor_id") or "unknown"),
        mode=_MODE_LIVE,
        selector=f"{adapter_id}:{account_id}",
    )

    try:
        safety_ctx = gate_order(canonical_order, request_ctx, adapter_id=adapter_id, account_id=account_id)
        asyncio.run(dispatch(router, request_ctx, safety_ctx))
    except SafetyBypassError as exc:
        logger.warning("Live %s refused by safety gate | order=%s: %s", op, order_id, exc)
        return jsonify({"status": "error", "message": f"Order refused: {exc}"}), 403
    except (BrokerNotFoundError, KeyError) as exc:
        logger.warning("Live %s — broker not connected | adapter=%s account=%s: %s", op, adapter_id, account_id, exc)
        return jsonify({
            "status": "error",
            "message": (
                f"Broker '{adapter_id}' (account '{account_id}') is not connected. Add the "
                "selector to workspace.json brokers.registered and brokers.account_acls, then restart."
            ),
        }), 503
    except Exception:
        logger.exception("Live %s dispatch failed | order=%s adapter=%s", op, order_id, adapter_id)
        return jsonify({"status": "error", "message": fail_message}), 500

    _audit_write_event(audit_event, adapter_id, account_id, request_ctx.actor_id, order_id)
    logger.info("Live %s dispatched | order=%s adapter=%s account=%s", op, order_id, adapter_id, account_id)
    return jsonify({"status": "success", "orderid": order_id}), 200


def _modify_changes(body: dict[str, Any]) -> dict[str, Any]:
    """Build the ``ModifyOrder`` field dict (minus orderid) from a request body.

    Only the fields the OpenAlgo ``ModifyOrder`` model accepts — extra body keys
    (apikey, account_id, …) are dropped so the typed-model construction in the
    adapter cannot fail on an unexpected field.
    """
    return {
        "symbol": str(body.get("symbol") or ""),
        "exchange": str(body.get("exchange", "NSE")).upper(),
        "action": str(body.get("action", "BUY")).upper(),
        "pricetype": str(body.get("pricetype") or body.get("order_type") or "LIMIT").upper(),
        "product": str(body.get("product", "MIS")).upper(),
        "quantity": str(body.get("quantity", "1")),
        "price": str(body.get("price", "0")),
        "strategy": str(body.get("strategy") or "Flint"),
    }


def _dispatch_live_modify(
    body: dict[str, Any],
    payload: dict[str, Any],
    *,
    adapter_id: str = "openalgo",
) -> tuple[Any, int]:
    """Gate a live order MODIFY through the BrokerRouter (one-shot gate + ACL).

    A modify is not a fresh placement, so it does not run the full SafetySystem
    order pipeline — but it IS gated behind the L5 kill switch (a modify can
    increase risk) plus the one-shot SafetyContext + per-account ACL.
    """
    from pydantic import ValidationError  # noqa: PLC0415

    from flinttrade_core.models import ModifyOrder  # noqa: PLC0415
    from flinttrade_gateway.routing_config import RoutingHint  # noqa: PLC0415

    account_id = str(body.get("account_id") or "default")
    order_id = str(body.get("orderid") or "").strip()
    if not order_id:
        return jsonify({"status": "error", "message": "Modify requires an 'orderid'"}), 400

    blocked = _live_kill_switch_block()
    if blocked is not None:
        logger.warning("Live modify blocked by kill switch | order=%s: %s", order_id, blocked.reason)
        return jsonify({
            "status": "error",
            "message": f"Order blocked by safety system [{blocked.layer}]: {blocked.reason}",
        }), 403

    changes = _modify_changes(body)
    try:
        ModifyOrder(orderid=order_id, **changes)  # validate up-front; no gate consumed on bad input
    except (ValueError, ValidationError) as exc:
        logger.warning("Live modify rejected by order-model validation | order=%s: %s", order_id, exc)
        return jsonify({"status": "error", "message": f"Modify validation failed: {exc}"}), 400

    canonical = {"_op": "modify", "order_id": order_id, **changes}
    hint = RoutingHint(adapter_id=adapter_id, account_id=account_id)
    return _gated_write_dispatch(
        "modify",
        canonical,
        payload,
        adapter_id=adapter_id,
        account_id=account_id,
        order_id=order_id,
        dispatch=lambda router, ctx, sctx: router.modify_order(
            ctx, order=canonical, order_id=order_id, changes=changes, safety_ctx=sctx, hint=hint
        ),
        audit_event="ORDER_MODIFIED",
        fail_message="Order modify failed",
    )


def _dispatch_live_cancel(
    body: dict[str, Any],
    payload: dict[str, Any],
    *,
    adapter_id: str = "openalgo",
) -> tuple[Any, int]:
    """Gate a live order CANCEL through the BrokerRouter (one-shot gate + ACL).

    Cancel reduces exposure, so it is intentionally NOT blocked by the kill
    switch — a halted account must still be able to cancel a working order. It is
    gated by the one-shot SafetyContext + per-account ACL.
    """
    from flinttrade_gateway.routing_config import RoutingHint  # noqa: PLC0415

    account_id = str(body.get("account_id") or "default")
    order_id = str(body.get("orderid") or "").strip()
    if not order_id:
        return jsonify({"status": "error", "message": "Cancel requires an 'orderid'"}), 400

    canonical = {"_op": "cancel", "order_id": order_id}
    hint = RoutingHint(adapter_id=adapter_id, account_id=account_id)
    return _gated_write_dispatch(
        "cancel",
        canonical,
        payload,
        adapter_id=adapter_id,
        account_id=account_id,
        order_id=order_id,
        dispatch=lambda router, ctx, sctx: router.cancel_order(
            ctx, order=canonical, order_id=order_id, safety_ctx=sctx, hint=hint
        ),
        audit_event="ORDER_CANCELLED",
        fail_message="Order cancel failed",
    )


def _dispatch_order(ft_action: str) -> tuple[Any, int]:
    """Core dispatch logic shared by all order endpoint handlers.

    Reads the ``X-FlintTrade-Mode`` header, validates it, then routes to the
    correct execution path (explore / practice / live).

    Args:
        ft_action: The FlintTrade action key (matches ``_ENDPOINT_MAP``), e.g.
            ``"place"``, ``"cancel"``.

    Returns:
        A ``(flask.Response, http_status_code)`` tuple.
    """
    # Read mode from the JWT claim — never trust the client-supplied header.
    mode = _get_mode_from_jwt()

    # Log if the client-supplied header disagrees with the JWT claim (debugging aid).
    header_mode = (request.headers.get("X-FlintTrade-Mode") or "").strip().lower()
    if header_mode and mode and header_mode != mode:
        logger.warning(
            "Order request to /%s — X-FlintTrade-Mode header ('%s') disagrees with "
            "JWT mode claim ('%s'); using JWT claim",
            ft_action, header_mode, mode,
        )

    if not mode:
        logger.warning(
            "Order request to /%s missing valid JWT with mode claim — rejected", ft_action
        )
        return jsonify({
            "status": "error",
            "message": "Authentication required — provide a valid JWT with a mode claim",
        }), 401

    if mode not in _VALID_MODES:
        logger.warning(
            "Order request to /%s has invalid JWT mode '%s' — rejected", ft_action, mode
        )
        return jsonify({
            "status": "error",
            "message": (
                f"Invalid mode '{mode}' in JWT claim. "
                "Expected one of: explore, practice, live"
            ),
        }), 400

    body = request.get_json(silent=True) or {}
    openalgo_endpoint = _ENDPOINT_MAP[ft_action]

    # ------------------------------------------------------------------
    # Explore mode — orders never permitted
    # ------------------------------------------------------------------
    if mode == _MODE_EXPLORE:
        logger.info(
            "Order blocked — explore mode | action=%s symbol=%s",
            ft_action, body.get("symbol", "?"),
        )
        return jsonify({
            "status": "error",
            "message": "Orders are not available in Explore mode. Switch to Practice or Live to trade.",
        }), 403

    # ------------------------------------------------------------------
    # Practice mode — paper trading via SandboxEngine
    # ------------------------------------------------------------------
    if mode == _MODE_PRACTICE:
        sandbox = current_app.config.get("DATA_SANDBOX_ENGINE")
        if sandbox is None:
            logger.error(
                "SandboxEngine not configured in app.config — cannot process practice order"
            )
            return jsonify({
                "status": "error",
                "message": "Practice trading engine not available",
            }), 500

        # Only placeorder-style actions are meaningful in sandbox;
        # modify/cancel/close/open are also supported for UI parity.
        try:
            result = _sandbox_dispatch(sandbox, ft_action, body)
        except Exception as exc:
            logger.exception(
                "SandboxEngine error for action=%s symbol=%s: %s",
                ft_action, body.get("symbol", "?"), exc,
            )
            return jsonify({
                "status": "error",
                "message": "Practice trading engine encountered an error",
            }), 500

        logger.info(
            "Practice order | action=%s symbol=%s exchange=%s qty=%s → %s",
            ft_action,
            body.get("symbol", "?"),
            body.get("exchange", "?"),
            body.get("quantity", "?"),
            result.get("status", "?"),
        )
        return jsonify(result), 200

    # ------------------------------------------------------------------
    # Live mode — single gated, selector-bound execution channel (C1).
    #
    # ``place`` runs the full SafetySystem (L1-L5) + one-shot HMAC gate +
    # per-account ACL via the BrokerRouter; ``modify`` and ``cancel`` run the same
    # one-shot gate + ACL (modify also behind the L5 kill switch). The remaining
    # live actions (smart/options/gtt/cancel-all/close/open) have no BrokerRouter
    # dispatch method yet, so they stay on the direct forward — still gated behind
    # the L5 kill switch so a halted account cannot push ANY live order. Gating
    # those is a scoped follow-up (needs BrokerRouter.place_smart_order, etc.).
    # ------------------------------------------------------------------
    if not _is_live_mode_unlocked():
        logger.warning(
            "Live order rejected — JWT does not contain live_mode_unlocked claim | "
            "action=%s symbol=%s",
            ft_action, body.get("symbol", "?"),
        )
        return jsonify({
            "status": "error",
            "message": "Live mode not unlocked — verify PIN first",
        }), 403

    live_payload = _decode_request_payload()
    if live_payload is None:
        return jsonify({
            "status": "error",
            "message": "Authentication required — JWT could not be decoded",
        }), 401

    if ft_action == "place":
        return _dispatch_live_order(ft_action, body, live_payload, adapter_id="openalgo")
    if ft_action == "modify":
        return _dispatch_live_modify(body, live_payload, adapter_id="openalgo")
    if ft_action == "cancel":
        return _dispatch_live_cancel(body, live_payload, adapter_id="openalgo")

    # Remaining live action (smart/options/gtt/cancel-all/close/open): no
    # BrokerRouter dispatch yet, so forward directly — gated behind the kill switch.
    blocked = _live_kill_switch_block()
    if blocked is not None:
        logger.warning(
            "Live %s blocked by kill switch | symbol=%s: %s",
            ft_action, body.get("symbol", "?"), blocked.reason,
        )
        return jsonify({
            "status": "error",
            "message": f"Order blocked by safety system [{blocked.layer}]: {blocked.reason}",
        }), 403

    logger.info(
        "Live order | action=%s symbol=%s exchange=%s qty=%s (forward; kill-switch checked)",
        ft_action,
        body.get("symbol", "?"),
        body.get("exchange", "?"),
        body.get("quantity", "?"),
    )
    response, status_code = _forward_to_openalgo(openalgo_endpoint, body)
    logger.info(
        "Live order result | action=%s symbol=%s → HTTP %d",
        ft_action, body.get("symbol", "?"), status_code,
    )
    return response, status_code


def _sandbox_dispatch(sandbox: Any, ft_action: str, body: dict[str, Any]) -> dict[str, Any]:
    """Route a practice order to the appropriate SandboxEngine method.

    The SandboxEngine's primary method is ``place_order`` which handles both
    BUY and SELL.  Modify/cancel operations return simulated responses because
    the sandbox executes instantly at fill — there is no open order to cancel.

    Args:
        sandbox: SandboxEngine instance from ``app.config["DATA_SANDBOX_ENGINE"]``.
        ft_action: FlintTrade action key (``"place"``, ``"cancel"``, etc.).
        body: Decoded JSON request body.

    Returns:
        Dict response in OpenAlgo-compatible format.
    """
    symbol: str = str(body.get("symbol", "")).strip().upper()
    exchange: str = str(body.get("exchange", "")).strip().upper()
    action: str = str(body.get("action", "BUY")).strip().upper()
    product: str = str(body.get("product", "MIS")).strip().upper()

    try:
        quantity = int(body.get("quantity", 0))
    except (TypeError, ValueError):
        quantity = 0

    try:
        price = float(body.get("price", 0.0))
    except (TypeError, ValueError):
        price = 0.0

    if ft_action in ("place", "place-smart", "open-position"):
        return sandbox.place_order(
            symbol=symbol,
            exchange=exchange,
            action=action,
            quantity=quantity,
            price=price,
            product=product,
        )

    if ft_action == "close-position":
        # Close by selling the full open net position
        positions = sandbox.get_positions()
        matching = [
            p for p in positions
            if p["symbol"] == symbol
            and p["exchange"] == exchange
            and p["product"] == product
            and p["net_qty"] != 0
        ]
        if not matching:
            return {
                "order_id": "",
                "status": "REJECTED",
                "message": f"No open sandbox position for {symbol} on {exchange} ({product})",
            }
        pos = matching[0]
        net_qty = pos["net_qty"]
        close_action = "SELL" if net_qty > 0 else "BUY"
        return sandbox.place_order(
            symbol=symbol,
            exchange=exchange,
            action=close_action,
            quantity=abs(net_qty),
            price=price,
            product=product,
        )

    if ft_action in ("cancel", "cancel-all", "modify"):
        # Sandbox fills instantly — no pending orders to cancel or modify.
        # Return a simulated success so the UI does not display an error.
        return {
            "order_id": str(body.get("order_id", "")),
            "status": "success",
            "message": (
                f"Practice mode: {ft_action} acknowledged "
                "(sandbox orders are filled immediately)"
            ),
        }

    if ft_action in ("gtt-place", "gtt-modify", "gtt-cancel"):
        # GTT triggers are inherently multi-day live broker constructs.
        # The practice sandbox does not simulate price triggers, so reject
        # cleanly rather than pretend a trigger was created.
        return {
            "trigger_id": "",
            "status": "REJECTED",
            "message": (
                "GTT (Good Till Triggered) orders require live mode — "
                "they are not simulated in Practice mode."
            ),
        }

    # Fallback for any unmapped action — should never reach here
    return {
        "order_id": "",
        "status": "REJECTED",
        "message": f"Unsupported action in practice mode: {ft_action}",
    }


# ---------------------------------------------------------------------------
# Route handlers — one per endpoint, all delegate to _dispatch_order()
# ---------------------------------------------------------------------------


@orders_bp.route("/place", methods=["POST"])
def place_order() -> tuple[Any, int]:
    """Place a regular order — maps to OpenAlgo ``placeorder``.

    Request headers:
        X-FlintTrade-Mode (str): ``explore`` | ``practice`` | ``live``

    Request JSON (live/practice):
        symbol (str): Instrument symbol.
        exchange (str): Exchange code.
        action (str): ``BUY`` or ``SELL``.
        quantity (int): Number of units.
        price (float): Limit price (0 for market).
        product (str): ``MIS``, ``NRML``, or ``CNC``.
        order_type (str): ``MARKET`` or ``LIMIT``.

    Returns:
        JSON with ``status``, ``order_id``, and ``message``.
        HTTP 200 on success, 400/403/500/502 on error.
    """
    return _dispatch_order("place")


def _decode_request_payload() -> dict[str, Any] | None:
    """Decode the request's Bearer/X-FlintTrade-Token JWT, or ``None`` if invalid."""
    from .auth_routes import decode_token  # noqa: PLC0415

    auth_header = request.headers.get("Authorization", "")
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        token = request.headers.get("X-FlintTrade-Token", "").strip()
    if not token:
        return None
    try:
        return decode_token(token)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None


@orders_bp.route("/<broker>/place", methods=["POST"])
def place_order_routed(broker: str) -> tuple[Any, int]:
    """Place a LIVE order through the safety-gated, selector-bound router (G5).

    Unlike the legacy ``/place`` endpoint (which forwards straight to OpenAlgo),
    this path mints a selector-bound :class:`RequestContext`, gates the order
    through ``gate_order`` (binding the order to the caller, mode, adapter, and
    account), and dispatches via the app's :class:`BrokerRouter` — which
    ACL-checks the account and re-verifies the one-shot SafetyContext before any
    broker write. ``broker`` is the adapter id (e.g. ``dhan``); ``account_id``
    comes from the request body (default ``"default"``).

    Returns:
        200 with the broker result; 401 (no/invalid JWT), 403 (not unlocked /
        actor not authorised / verification failed), 503 (routing unavailable or
        the broker is not connected yet).
    """
    payload = _decode_request_payload()
    if not payload:
        return jsonify({
            "status": "error",
            "message": "Authentication required — provide a valid JWT",
        }), 401

    if payload.get("mode") != _MODE_LIVE:
        return jsonify({
            "status": "error",
            "message": (
                "The routed order path serves live mode only. Use "
                "/api/v1/orders/place for explore/practice."
            ),
        }), 400

    if not _is_live_mode_unlocked():
        return jsonify({
            "status": "error",
            "message": "Live mode not unlocked — verify PIN first",
        }), 403

    body = request.get_json(silent=True) or {}
    return _dispatch_live_order("place", body, payload, adapter_id=broker)


@orders_bp.route("/place-smart", methods=["POST"])
def place_smart_order() -> tuple[Any, int]:
    """Place a smart order — maps to OpenAlgo ``placesmartorder``.

    Smart orders include bracket, cover, and other advanced order types
    supported by the connected broker.

    Request headers:
        X-FlintTrade-Mode (str): ``explore`` | ``practice`` | ``live``

    Returns:
        JSON with ``status``, ``order_id``, and ``message``.
    """
    return _dispatch_order("place-smart")


@orders_bp.route("/modify", methods=["POST"])
def modify_order() -> tuple[Any, int]:
    """Modify an existing open order — maps to OpenAlgo ``modifyorder``.

    Request headers:
        X-FlintTrade-Mode (str): ``explore`` | ``practice`` | ``live``

    Request JSON:
        order_id (str): The order to modify.
        quantity (int, optional): New quantity.
        price (float, optional): New price.
        order_type (str, optional): New order type.

    Returns:
        JSON with ``status`` and confirmation.
    """
    return _dispatch_order("modify")


@orders_bp.route("/cancel", methods=["POST"])
def cancel_order() -> tuple[Any, int]:
    """Cancel an open order — maps to OpenAlgo ``cancelorder``.

    Request headers:
        X-FlintTrade-Mode (str): ``explore`` | ``practice`` | ``live``

    Request JSON:
        order_id (str): The order ID to cancel.

    Returns:
        JSON with ``status`` and confirmation.
    """
    return _dispatch_order("cancel")


@orders_bp.route("/cancel-all", methods=["POST"])
def cancel_all_orders() -> tuple[Any, int]:
    """Cancel all open orders — maps to OpenAlgo ``cancelallorder``.

    Request headers:
        X-FlintTrade-Mode (str): ``explore`` | ``practice`` | ``live``

    Returns:
        JSON with ``status`` and count of cancelled orders.
    """
    return _dispatch_order("cancel-all")


@orders_bp.route("/close-position", methods=["POST"])
def close_position() -> tuple[Any, int]:
    """Close an open position — maps to OpenAlgo ``closeposition``.

    Request headers:
        X-FlintTrade-Mode (str): ``explore`` | ``practice`` | ``live``

    Request JSON:
        symbol (str): Instrument symbol.
        exchange (str): Exchange code.
        product (str): Product type.

    Returns:
        JSON with ``status`` and confirmation.
    """
    return _dispatch_order("close-position")


@orders_bp.route("/open-position", methods=["POST"])
def open_position() -> tuple[Any, int]:
    """Open a new position — maps to OpenAlgo ``openposition``.

    Request headers:
        X-FlintTrade-Mode (str): ``explore`` | ``practice`` | ``live``

    Request JSON:
        symbol (str): Instrument symbol.
        exchange (str): Exchange code.
        action (str): ``BUY`` or ``SELL``.
        quantity (int): Number of units.
        price (float): Entry price.
        product (str): Product type.

    Returns:
        JSON with ``status``, ``order_id``, and ``message``.
    """
    return _dispatch_order("open-position")


@orders_bp.route("/options", methods=["POST"])
def options_order() -> tuple[Any, int]:
    """Place a single-leg options order — maps to OpenAlgo ``optionsorder``.

    Routes a generic single-leg options order through the FT safety proxy
    so that explore and practice modes are blocked by the mode gate before
    any real-money order can reach OpenAlgo. Added 2026-05-19 to close the
    gap flagged by the Codex stop-gate review (options orders were briefly
    falling through to OpenAlgo direct, bypassing the mode gate).

    Request headers:
        X-FlintTrade-Mode (str): ``explore`` | ``practice`` | ``live``

    Request JSON: forwarded as-is to OpenAlgo's ``optionsorder`` endpoint.
        Typical fields: ``symbol``, ``exchange``, ``action``, ``quantity``,
        ``price``, ``product``, ``order_type``, ``strike``, ``expiry``,
        ``option_type`` (``CE``/``PE``).

    Returns:
        JSON with ``status``, ``order_id``, and ``message``.
    """
    return _dispatch_order("options")


@orders_bp.route("/options-multi", methods=["POST"])
def options_multi_order() -> tuple[Any, int]:
    """Place a multi-leg options order — maps to OpenAlgo ``optionsmultiorder``.

    Like :func:`options_order` but for multi-leg payloads (spreads,
    straddles, condors written as a legs array). Same safety-proxy
    semantics — mode gate applied before forwarding to OpenAlgo.

    Request headers:
        X-FlintTrade-Mode (str): ``explore`` | ``practice`` | ``live``

    Request JSON: forwarded as-is to OpenAlgo's ``optionsmultiorder``
        endpoint. Typical shape: ``{"legs": [{"strike": ..., "option_type":
        ..., "action": ..., "quantity": ...}, ...], "exchange": ...,
        "product": ..., "expiry": ...}``.

    Returns:
        JSON with ``status``, ``order_id``s per leg, and ``message``.
    """
    return _dispatch_order("options-multi")


# ---------------------------------------------------------------------------
# GTT (Good Till Triggered) — placed/modified/cancelled through the same
# safety proxy as regular orders so live-mode JWT unlock and explore-mode
# blocking apply identically. Upstream live broker support: Dhan + Zerodha.
# ---------------------------------------------------------------------------


@orders_bp.route("/gtt-place", methods=["POST"])
def gtt_place_order() -> tuple[Any, int]:
    """Place a GTT (Good Till Triggered) order — maps to ``placegttorder``.

    Single-leg or two-leg OCO triggers. Upstream rejects MIS product
    because triggers can sit for days; expects ``triggerprice_sl`` /
    ``triggerprice_tg`` and (for OCO) ``stoploss`` / ``target`` limits.
    """
    return _dispatch_order("gtt-place")


@orders_bp.route("/gtt-modify", methods=["POST"])
def gtt_modify_order() -> tuple[Any, int]:
    """Modify an active GTT — maps to ``modifygttorder``. Full replacement."""
    return _dispatch_order("gtt-modify")


@orders_bp.route("/gtt-cancel", methods=["POST"])
def gtt_cancel_order() -> tuple[Any, int]:
    """Cancel an active GTT by ``trigger_id`` — maps to ``cancelgttorder``."""
    return _dispatch_order("gtt-cancel")
