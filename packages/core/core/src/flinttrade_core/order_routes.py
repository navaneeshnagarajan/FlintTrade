"""Order proxy blueprint — mode-enforcing gateway for all order operations.

This module is a CRITICAL SAFETY LAYER.  Every order request from the
frontend MUST pass through here before reaching OpenAlgo.  The blueprint
reads the ``mode`` claim from the *server-issued JWT* (not from any
client-controlled header) and routes accordingly:

- ``explore``  → 403 — no orders permitted in demo mode
- ``practice`` → SandboxEngine (paper trading, no broker write)
- ``live``     → gated BrokerRouter execution for supported writes; fail closed otherwise

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
             → live     → SafetySystem/gate_order → BrokerRouter

Blueprint prefix: ``/v1/orders``
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any

import httpx
import jwt
from flask import Blueprint, current_app, jsonify, request

from .rate_limiter import rate_limit

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
    """Return the OpenAlgo API key from app config or environment.

    Returns:
        API key string (may be empty — callers should handle that case).
    """
    client = current_app.config.get("CLIENT")
    if client is not None:
        try:
            return str(client.settings.openalgo_api_key)
        except AttributeError:
            pass
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


def _body_to_order(body: dict[str, Any], *, variety: str | None = None) -> Any:
    """Build a typed :class:`Order` from a decoded request body for the SafetySystem.

    The legacy path forwarded the raw dict; the 5-layer ``SafetySystem.check_order``
    needs the typed model to validate symbol, quantity, price, exchange, and market
    hours. Enum coercion (action/exchange/product/pricetype) raises ``ValueError`` on
    a bad value, which the caller maps to HTTP 400 rather than letting it 500.

    Args:
        body: Decoded JSON request body.
        variety: When set (e.g. ``"gtt"`` for the forever route), the built order
            carries this variety plus the variety-specific pass-throughs from the
            body (``validity`` and the OCO second-leg trio ``price1`` /
            ``trigger_price1`` / ``quantity1``). ``None`` (the default) keeps the
            legacy regular-order shape so the existing ``/place`` behaviour is
            byte-identical.
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

    extra: dict[str, Any] = {}
    if variety is not None:
        extra["variety"] = variety
        # Variety-specific pass-throughs (Dhan forever OCO + validity). They live
        # on the Order model, so the SafetyContext canonical hash covers them.
        for key in ("validity", "price1", "trigger_price1", "quantity1"):
            value = body.get(key)
            if value is not None:
                extra[key] = str(value)

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
        **extra,
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


def _gather_l2_state(adapter_id: str) -> tuple[list[Any], float, float]:
    """Best-effort live ``(positions, used_margin, total_balance)`` for L2.

    Reads the connected account's positionbook + funds through the OpenAlgo
    bridge client so SafetySystem L2 can enforce max-positions and margin%
    against REAL exposure. Best-effort by design: any failure (no client,
    network, auth) returns empty/zero state, so L2 simply enforces nothing for
    that order — a state-read hiccup must never block a live order (L1/L4/L5
    still apply). Runs two reads on the human order path; acceptable latency
    for the cumulative-exposure brake.

    Scoped to ``adapter_id == "openalgo"`` — the only functional adapter. The
    routed ``/<broker>/place`` path accepts any broker, but OPENALGO_CLIENT
    holds OpenAlgo's portfolio, not a native broker's; feeding it for a native
    selector would enforce L2 against the WRONG account. Native adapters are
    dormant today, so for them L2 simply no-ops (empty state) rather than
    mis-enforcing; a per-adapter gather lands when native adapters ship.
    """
    import asyncio  # noqa: PLC0415

    if adapter_id != "openalgo":
        return [], 0.0, 0.0

    client = current_app.config.get("OPENALGO_CLIENT")
    if client is None:
        return [], 0.0, 0.0

    async def _fetch() -> tuple[Any, Any]:
        return await client.positionbook(), await client.funds()

    try:
        positions, funds = asyncio.run(_fetch())
    except Exception:
        logger.debug(
            "L2 portfolio-state fetch failed — L2 limits not enforced this order",
            exc_info=True,
        )
        return [], 0.0, 0.0

    def _to_float(value: Any) -> float:
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return 0.0

    return (
        list(positions or []),
        _to_float(getattr(funds, "used_margin", 0)),
        _to_float(getattr(funds, "total_balance", 0)),
    )


def _dispatch_live_order(
    ft_action: str,
    body: dict[str, Any],
    payload: dict[str, Any],
    *,
    adapter_id: str = "openalgo",
    variety: str | None = None,
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

    from flinttrade_core.exceptions import SafetyBypassError, UnsupportedCapabilityError  # noqa: PLC0415
    from flinttrade_engine.algo_tag_guard import AlgoTagLimitError  # noqa: PLC0415
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
    # Gather live position + margin state so L2 enforces max-positions and
    # margin% against REAL cumulative exposure (was always empty/zero → L2
    # was a no-op). Best-effort: a fetch hiccup yields empty state (L2 enforces
    # nothing this order) rather than blocking — availability is never degraded
    # by a state read; L1/L4/L5 still apply. (L3 greeks + L4 daily-P&L are not
    # fed from the hot path: greeks need option-chain data the bridge lacks,
    # and L4 latches its kill switch, so a noisy broker PNL must not drive it —
    # tracked in PLAN §3b.)
    l2_positions, l2_used_margin, l2_total_balance = _gather_l2_state(adapter_id)
    safety = current_app.config.get("SAFETY")
    if safety is None:
        safety = SafetySystem(SafetyConfig())
    try:
        typed_order = _body_to_order(body, variety=variety)
        # check_order coerces quantity via int(...); a non-integer quantity must
        # surface as a clean 400, not an uncaught ValueError -> 500.
        safety_results = safety.check_order(
            typed_order,
            positions=l2_positions,
            used_margin=l2_used_margin,
            total_balance=l2_total_balance,
        )
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
    _t0 = time.perf_counter()
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
        # Feed the latency monitor (audit H5) — without this producer the order
        # latency stats were empty forever. Best-effort: never let monitoring
        # affect the order result.
        try:
            from .monitoring_routes import get_latency_tracker  # noqa: PLC0415

            get_latency_tracker().record_order_latency(
                adapter_id,
                getattr(typed_order, "symbol", "") or "",
                (time.perf_counter() - _t0) * 1000.0,
            )
        except Exception:  # pragma: no cover - monitoring must never break orders
            logger.debug("order latency record failed", exc_info=True)
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
    except AlgoTagLimitError as exc:
        # The router's algo-tag guard refused the dispatch: the operator's
        # per-(broker, exchange) per-second algo-order ceiling would be breached.
        # A throttle refusal, not a safety bypass — map to 429 so callers retry.
        logger.warning(
            "Live order refused by algo-tag guard | action=%s adapter=%s account=%s: %s",
            ft_action, adapter_id, account_id, exc,
        )
        return jsonify({"status": "error", "message": f"Order refused: {exc}"}), 429
    except (NotImplementedError, UnsupportedCapabilityError) as exc:
        # Gated-skeleton adapters (e.g. Dhan) raise NotImplementedError for
        # un-built order paths; an adapter raises UnsupportedCapabilityError for
        # a capability it does not advertise. Both are an honest "not yet
        # available", not a server fault — map to 501 with the adapter message.
        logger.warning(
            "Live order — adapter capability not available | action=%s adapter=%s account=%s: %s",
            ft_action, adapter_id, account_id, exc,
        )
        return jsonify({
            "status": "error",
            "message": str(exc) or f"Order placement is not yet available for broker '{adapter_id}'.",
        }), 501
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

    # Trade journal (best-effort — never break the order path). Without this
    # producer the journal + P&L analytics stayed empty in Live mode (the
    # /trades/journal route read a store nothing ever wrote to).
    try:
        _record_trade_journal(typed_order, str(result))
    except Exception:  # pragma: no cover — journalling must never break orders
        logger.debug("trade journal stamp failed for live order", exc_info=True)

    logger.info(
        "Live order dispatched | action=%s adapter=%s account=%s symbol=%s",
        ft_action, adapter_id, account_id, body.get("symbol", "?"),
    )
    # Return both keys: ``orderid`` (legacy OpenAlgo response shape the UI reads)
    # and ``data`` (the routed-path shape) so the frontend works either way.
    return jsonify({"status": "success", "orderid": result, "data": result}), 200


def _record_trade_journal(typed_order: Any, orderid: str, strategy: str = "manual") -> None:
    """Append an executed live order to the shared trade journal (best-effort).

    Writes to the same DuckDB store the ``/trades/journal`` route reads, so the
    journal and downstream P&L analytics populate in Live mode. No-ops when no
    ``TRADE_STORAGE`` is configured (e.g. minimal test apps) so it never creates
    DuckDB side effects where journalling isn't wired. Serialises writes against
    the route's reads via the shared ``TRADE_STORAGE_LOCK`` (DuckDB connections
    are not safe for concurrent use). Never raises.

    Args:
        typed_order: The dispatched :class:`flinttrade_core.models.Order`. The
            journalled side (BUY/SELL) is read from ``typed_order.action`` — NOT
            the route-level operation label (which is always ``"place"`` here).
        orderid: The broker order id returned by the router.
        strategy: Journal bucket for the trade; manual terminal orders use
            ``"manual"`` so they group separately from strategy-runner fills.
    """
    store = current_app.config.get("TRADE_STORAGE")
    if store is None:
        return

    from datetime import datetime, timedelta, timezone  # noqa: PLC0415

    ist = timezone(timedelta(hours=5, minutes=30))

    def _enum_value(value: Any) -> str:
        return str(getattr(value, "value", value) or "")

    def _to_number(value: Any) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _insert() -> None:
        store.insert_trade(
            ts=datetime.now(ist),
            orderid=str(orderid),
            symbol=getattr(typed_order, "symbol", "") or "",
            exchange=_enum_value(getattr(typed_order, "exchange", "")),
            action=_enum_value(getattr(typed_order, "action", "")),
            quantity=int(_to_number(getattr(typed_order, "quantity", 0))),
            price=_to_number(getattr(typed_order, "price", 0.0)),
            product=_enum_value(getattr(typed_order, "product", "")),
            strategy=strategy,
        )

    lock = current_app.config.get("TRADE_STORAGE_LOCK")
    if lock is not None:
        with lock:
            _insert()
    else:
        _insert()


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

    from flinttrade_core.exceptions import SafetyBypassError, UnsupportedCapabilityError  # noqa: PLC0415
    from flinttrade_engine.algo_tag_guard import AlgoTagLimitError  # noqa: PLC0415
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
    except AlgoTagLimitError as exc:
        # The router's algo-tag guard refused the dispatch (per-(broker,
        # exchange) per-second algo-order ceiling). A throttle refusal callers
        # should retry — 429, mirroring the place path; never a 500.
        logger.warning("Live %s refused by algo-tag guard | order=%s: %s", op, order_id, exc)
        return jsonify({"status": "error", "message": f"Order refused: {exc}"}), 429
    except (BrokerNotFoundError, KeyError) as exc:
        logger.warning("Live %s — broker not connected | adapter=%s account=%s: %s", op, adapter_id, account_id, exc)
        return jsonify({
            "status": "error",
            "message": (
                f"Broker '{adapter_id}' (account '{account_id}') is not connected. Add the "
                "selector to workspace.json brokers.registered and brokers.account_acls, then restart."
            ),
        }), 503
    except (NotImplementedError, UnsupportedCapabilityError) as exc:
        # Gated-skeleton adapters raise NotImplementedError for un-built write
        # paths; UnsupportedCapabilityError signals a capability the adapter does
        # not advertise. Both are an honest "not yet available" — map to 501.
        logger.warning("Live %s — adapter capability not available | adapter=%s account=%s: %s", op, adapter_id, account_id, exc)
        return jsonify({
            "status": "error",
            "message": str(exc) or f"This operation is not yet available for broker '{adapter_id}'.",
        }), 501
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

    Optional ``variety`` / ``amo`` body fields (Kotak Neo bracket/cover leg
    exits) are forwarded as adapter-level cancel extras. They are written into
    the canonical cancel fingerprint BEFORE the gate is minted, so the router's
    field-by-field extras check passes only because the gate signed them — an
    unhashed extra can never reach the broker.
    """
    from flinttrade_gateway.routing_config import RoutingHint  # noqa: PLC0415

    account_id = str(body.get("account_id") or "default")
    order_id = str(body.get("orderid") or "").strip()
    if not order_id:
        return jsonify({"status": "error", "message": "Cancel requires an 'orderid'"}), 400

    extras: dict[str, Any] = {}
    if body.get("variety") is not None:
        extras["variety"] = str(body["variety"])
    if body.get("amo") is not None:
        extras["amo"] = bool(body["amo"])

    canonical = {"_op": "cancel", "order_id": order_id, **extras}
    hint = RoutingHint(adapter_id=adapter_id, account_id=account_id)
    return _gated_write_dispatch(
        "cancel",
        canonical,
        payload,
        adapter_id=adapter_id,
        account_id=account_id,
        order_id=order_id,
        dispatch=lambda router, ctx, sctx: router.cancel_order(
            ctx, order=canonical, order_id=order_id, safety_ctx=sctx, hint=hint,
            extras=extras or None,
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
    # per-account ACL via the BrokerRouter. ``modify`` and ``cancel`` run the
    # same one-shot gate + ACL (modify also behind the L5 kill switch), and
    # ``cancel-all`` for an explicitly-named native broker routes through the
    # gated ``cancel_all_orders`` verb.
    #
    # Other legacy OpenAlgo write verbs intentionally fail closed until they
    # have BrokerRouter verbs. Workspace/UI OpenAlgo settings can now provide a
    # live API key, so leaving the old direct forward in place would wake an
    # ungated order path.
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
    if ft_action == "cancel-all" and str(body.get("broker") or "").strip().lower() not in ("", "openalgo"):
        # Native adapters sweep through the gated cancel_all_orders verb
        # (one-shot SafetyContext + ACL). OpenAlgo bridge cancel-all has no
        # gated verb yet and is rejected by the fail-closed block below.
        adapter_id, account_id = _gated_target(body)
        fields = {k: str(body[k]) for k in ("tag", "segment") if body.get(k) is not None}
        return _gated_verb_write(
            "cancel_all_orders", fields, live_payload,
            adapter_id=adapter_id, account_id=account_id,
            audit_event="ORDERS_CANCELLED_ALL", fail_message="Cancel-all failed",
        )

    logger.warning(
        "Live order action rejected until gated BrokerRouter support exists | "
        "action=%s endpoint=%s symbol=%s",
        ft_action, openalgo_endpoint, body.get("symbol", "?"),
    )
    return jsonify({
        "status": "error",
        "message": (
            f"Live action '{ft_action}' is disabled until it is routed through "
            "the gated broker router"
        ),
    }), 501


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
@rate_limit("orders", user_rate=10, global_rate=100)
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
@rate_limit("orders", user_rate=10, global_rate=100)
def place_order_routed(broker: str) -> tuple[Any, int]:
    """Place a LIVE order through the safety-gated, selector-bound router (G5).

    Like the default live ``/place`` endpoint, this path mints a
    selector-bound :class:`RequestContext`, gates the order
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
@rate_limit("smart_orders", user_rate=2, global_rate=20)
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
@rate_limit("orders", user_rate=10, global_rate=100)
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
@rate_limit("orders", user_rate=10, global_rate=100)
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
@rate_limit("orders", user_rate=10, global_rate=100)
def cancel_all_orders() -> tuple[Any, int]:
    """Cancel all open orders — maps to OpenAlgo ``cancelallorder``.

    Request headers:
        X-FlintTrade-Mode (str): ``explore`` | ``practice`` | ``live``

    Returns:
        JSON with ``status`` and count of cancelled orders.
    """
    return _dispatch_order("cancel-all")


@orders_bp.route("/close-position", methods=["POST"])
@rate_limit("orders", user_rate=10, global_rate=100)
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
@rate_limit("orders", user_rate=10, global_rate=100)
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
@rate_limit("orders", user_rate=10, global_rate=100)
def options_order() -> tuple[Any, int]:
    """Place a single-leg options order — maps to OpenAlgo ``optionsorder``.

    Routes a generic single-leg options order through the FT safety proxy
    so that explore and practice modes are handled before
    any live-capable route can reach a broker adapter. Added 2026-05-19 to close the
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
@rate_limit("orders", user_rate=10, global_rate=100)
def options_multi_order() -> tuple[Any, int]:
    """Place a multi-leg options order — maps to OpenAlgo ``optionsmultiorder``.

    Like :func:`options_order` but for multi-leg payloads (spreads,
    straddles, condors written as a legs array). Same safety-proxy
    semantics — mode gate applied before any live-capable broker route.

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
@rate_limit("orders", user_rate=10, global_rate=100)
def gtt_place_order() -> tuple[Any, int]:
    """Place a GTT (Good Till Triggered) order — maps to ``placegttorder``.

    Single-leg or two-leg OCO triggers. Upstream rejects MIS product
    because triggers can sit for days; expects ``triggerprice_sl`` /
    ``triggerprice_tg`` and (for OCO) ``stoploss`` / ``target`` limits.
    """
    return _dispatch_order("gtt-place")


@orders_bp.route("/gtt-modify", methods=["POST"])
@rate_limit("orders", user_rate=10, global_rate=100)
def gtt_modify_order() -> tuple[Any, int]:
    """Modify an active GTT — maps to ``modifygttorder``. Full replacement."""
    return _dispatch_order("gtt-modify")


@orders_bp.route("/gtt-cancel", methods=["POST"])
@rate_limit("orders", user_rate=10, global_rate=100)
def gtt_cancel_order() -> tuple[Any, int]:
    """Cancel an active GTT by ``trigger_id`` — maps to ``cancelgttorder``."""
    return _dispatch_order("gtt-cancel")


# ---------------------------------------------------------------------------
# Extended gated broker verbs (contract §8.1) — forever (GTT), super orders,
# conditional triggers, multi/batch orders, smart-order cancel.
#
# Every write here is LIVE-ONLY and traverses the single gated channel:
# route → validate body → live-mode guard → gate_broker_write (one-shot HMAC
# SafetyContext over the canonical payload, ``_op`` inside the signed hash)
# → BrokerRouter.execute_gated (re-verify + ACL + one-shot consume + verb
# table). Reads (the listings) traverse the same ACL-enforcing session
# provider but mint no SafetyContext — nothing is written.
# ---------------------------------------------------------------------------

# Dhan super-order legs (mirror flinttrade_gateway.brokers.dhan_mapping
# SUPER_ORDER_LEGS) — validated at the route so a typo'd leg is a clean 400,
# not a broker error mid-dispatch.
_SUPER_ORDER_LEGS = frozenset({"ENTRY_LEG", "TARGET_LEG", "STOP_LOSS_LEG"})


def _gated_target(params: Any) -> tuple[str, str]:
    """Resolve the ``(adapter_id, account_id)`` target from a body or query mapping.

    Args:
        params: A mapping-like object (decoded JSON body or ``request.args``)
            carrying optional ``broker`` and ``account_id`` fields.

    Returns:
        ``(adapter_id, account_id)`` — defaults ``("openalgo", "default")``.
    """
    adapter_id = str(params.get("broker") or "openalgo").strip().lower()
    account_id = str(params.get("account_id") or "default").strip() or "default"
    return adapter_id, account_id


def _require_live_payload(*, require_unlock: bool) -> tuple[dict[str, Any] | None, tuple[Any, int] | None]:
    """Decode the request JWT and enforce the live-mode guard for gated-verb routes.

    Mirrors the routed ``/<broker>/place`` guard sequence: 401 without a valid
    JWT; 403 for any non-live mode (forever/GTT, super orders, conditional
    triggers, position writes, and batch cancels are live-broker constructs the
    sandbox does not simulate); 403 when ``require_unlock`` is set and the JWT
    lacks the ``live_mode_unlocked`` claim (PIN re-verification mints it).

    Args:
        require_unlock: ``True`` for broker WRITES (the PIN gate applies);
            ``False`` for reads, which expose account state but write nothing.

    Returns:
        ``(payload, None)`` when the guard passes, else ``(None, (response,
        status))`` ready to be returned from the route handler.
    """
    payload = _decode_request_payload()
    if not payload:
        return None, (jsonify({
            "status": "error",
            "message": "Authentication required — provide a valid JWT",
        }), 401)

    if payload.get("mode") != _MODE_LIVE:
        return None, (jsonify({
            "status": "error",
            "message": (
                "This endpoint serves live mode only — forever (GTT), super orders, "
                "conditional triggers, and position writes are live-broker constructs. "
                "Switch to Live mode first."
            ),
        }), 403)

    if require_unlock and not _is_live_mode_unlocked():
        return None, (jsonify({
            "status": "error",
            "message": "Live mode not unlocked — verify PIN first",
        }), 403)

    return payload, None


def _gated_verb_write(
    verb: str,
    fields: dict[str, Any],
    jwt_payload: dict[str, Any],
    *,
    adapter_id: str,
    account_id: str,
    audit_event: str,
    fail_message: str,
    ref: str = "",
    kill_switch_gated: bool = False,
) -> tuple[Any, int]:
    """Mint + dispatch one extended gated broker write (contract §8.1).

    Builds the canonical payload ``{"_op": verb, **fields}`` — the SAME mapping
    is signed by ``gate_broker_write`` and re-verified + dispatched by
    :meth:`BrokerRouter.execute_gated`, so no unhashed mutable field can reach
    the broker. Mirrors :func:`_gated_write_dispatch`'s fail-closed status
    matrix: 503 (router unavailable / broker not connected), 403 (gate or ACL
    refusal, kill switch), 501 (adapter lacks the verb), 500 (dispatch fault).

    Args:
        verb: One of ``flinttrade_engine.safety.GATED_WRITE_VERBS``.
        fields: Verb payload fields (everything except the ``_op`` discriminator).
        jwt_payload: Decoded JWT of the calling operator.
        adapter_id: Target broker adapter id.
        account_id: Target account within the adapter.
        audit_event: Audit-log event type stamped on success (best-effort).
        fail_message: Operator-facing message for an unexpected dispatch fault.
        ref: Order/alert id echoed back as ``orderid`` (and logged) when set.
        kill_switch_gated: ``True`` for risk-increasing writes (modify/place
            shapes) — blocked while the L5 kill switch is latched. Exposure-
            reducing writes (cancels, exit-all) keep ``False`` so a halted
            account can still flatten itself.

    Returns:
        A ``(flask.Response, http_status_code)`` tuple.
    """
    import asyncio  # noqa: PLC0415

    from flinttrade_core.exceptions import (  # noqa: PLC0415
        BrokerError,
        SafetyBypassError,
        UnsupportedCapabilityError,
    )
    from flinttrade_engine.algo_tag_guard import AlgoTagLimitError  # noqa: PLC0415
    from flinttrade_engine.request_context import RequestContext  # noqa: PLC0415
    from flinttrade_engine.safety import gate_broker_write  # noqa: PLC0415
    from flinttrade_gateway.exceptions import BrokerNotFoundError  # noqa: PLC0415
    from flinttrade_gateway.routing_config import RoutingHint  # noqa: PLC0415

    if kill_switch_gated:
        blocked = _live_kill_switch_block()
        if blocked is not None:
            logger.warning("Live %s blocked by kill switch | ref=%s: %s", verb, ref, blocked.reason)
            return jsonify({
                "status": "error",
                "message": f"Order blocked by safety system [{blocked.layer}]: {blocked.reason}",
            }), 403

    router = current_app.config.get("BROKER_ROUTER")
    if router is None:
        logger.error("Live %s rejected — BROKER_ROUTER unavailable | adapter=%s", verb, adapter_id)
        return jsonify({
            "status": "error",
            "message": (
                "Order routing unavailable — workspace.json brokers configuration is "
                "missing or invalid. Check the startup logs, fix workspace.json, then restart."
            ),
        }), 503

    request_ctx = RequestContext(
        jti=str(jwt_payload.get("jti") or ""),
        actor_type="human",
        actor_id=str(jwt_payload.get("sub") or jwt_payload.get("actor_id") or "unknown"),
        mode=_MODE_LIVE,
        selector=f"{adapter_id}:{account_id}",
    )

    canonical: dict[str, Any] = {"_op": verb, **fields}
    try:
        safety_ctx = gate_broker_write(verb, canonical, request_ctx, adapter_id, account_id=account_id)
        result = asyncio.run(
            router.execute_gated(
                request_ctx,
                verb=verb,
                payload=canonical,
                safety_ctx=safety_ctx,
                hint=RoutingHint(adapter_id=adapter_id, account_id=account_id),
            )
        )
    except SafetyBypassError as exc:
        logger.warning("Live %s refused by safety gate | ref=%s: %s", verb, ref, exc)
        return jsonify({"status": "error", "message": f"Request refused: {exc}"}), 403
    except AlgoTagLimitError as exc:
        # Algo-tag guard ceiling breach — a throttle refusal callers should
        # retry (429), never the generic 500 (audit fix); mirrors the place path.
        logger.warning("Live %s refused by algo-tag guard | ref=%s: %s", verb, ref, exc)
        return jsonify({"status": "error", "message": f"Request refused: {exc}"}), 429
    except (BrokerNotFoundError, KeyError) as exc:
        logger.warning("Live %s — broker not connected | adapter=%s account=%s: %s", verb, adapter_id, account_id, exc)
        return jsonify({
            "status": "error",
            "message": (
                f"Broker '{adapter_id}' (account '{account_id}') is not connected. Add the "
                "selector to workspace.json brokers.registered and brokers.account_acls, then restart."
            ),
        }), 503
    except (NotImplementedError, UnsupportedCapabilityError) as exc:
        # An adapter without the verb refuses cleanly — an honest "not yet
        # available" for this broker, not a server fault.
        logger.warning(
            "Live %s — adapter capability not available | adapter=%s account=%s: %s",
            verb, adapter_id, account_id, exc,
        )
        return jsonify({
            "status": "error",
            "message": str(exc) or f"This operation is not yet available for broker '{adapter_id}'.",
        }), 501
    except (BrokerError, ValueError) as exc:
        # Honesty (audit MEDIUM): a real broker rejection (BrokerError, incl.
        # OrderRejectedByBroker) or an adapter mapping refusal (the *MappingError
        # classes, which subclass ValueError — e.g. DhanMappingError "segment not
        # enabled") carries a message the operator NEEDS. Surface it verbatim
        # rather than swallowing it into the generic 500. Mirrors how the live
        # place path surfaces broker rejections (see _dispatch_live_order). 502 =
        # the broker refused; the FlintTrade gate itself worked.
        logger.warning(
            "Live %s rejected by broker/adapter | adapter=%s account=%s: %s",
            verb, adapter_id, account_id, exc,
        )
        return jsonify({
            "status": "error",
            "message": str(exc) or fail_message,
        }), 502
    except Exception:
        logger.exception("Live %s dispatch failed | ref=%s adapter=%s", verb, ref, adapter_id)
        return jsonify({"status": "error", "message": fail_message}), 500

    _audit_write_event(audit_event, adapter_id, account_id, request_ctx.actor_id, ref)
    logger.info("Live %s dispatched | ref=%s adapter=%s account=%s", verb, ref, adapter_id, account_id)
    response: dict[str, Any] = {"status": "success", "data": result}
    if ref:
        response["orderid"] = ref
    return jsonify(response), 200


def _gated_broker_read(
    read_verb: str,
    jwt_payload: dict[str, Any],
    *,
    adapter_id: str,
    account_id: str,
) -> tuple[Any, int]:
    """Run an adapter read (forever/super/trigger listings) through the ACL'd session path.

    The BrokerRouter exposes no public read-dispatch for these listings yet
    (only ``quotes``), so this mirrors its resolve → session → adapter read
    sequence directly — INCLUDING the ``AuthenticatingSessionProvider``, which
    is the single per-(actor, account) ACL gate for reads and writes alike.
    Reads mint no SafetyContext (nothing is written), exactly like the router's
    own read path. Promoting this into a public ``BrokerRouter`` read verb is a
    gateway-owned follow-up (router.py is out of scope here).

    Args:
        read_verb: Adapter read method name (``forever_orders`` /
            ``super_orders`` / ``conditional_triggers``).
        jwt_payload: Decoded JWT of the calling operator.
        adapter_id: Target broker adapter id.
        account_id: Target account within the adapter.

    Returns:
        A ``(flask.Response, http_status_code)`` tuple; 200 carries
        ``{"status": "success", "data": [...]}``.
    """
    import asyncio  # noqa: PLC0415

    from flinttrade_core.exceptions import SafetyBypassError, UnsupportedCapabilityError  # noqa: PLC0415
    from flinttrade_engine.request_context import RequestContext  # noqa: PLC0415
    from flinttrade_gateway.exceptions import BrokerNotFoundError  # noqa: PLC0415

    router = current_app.config.get("BROKER_ROUTER")
    if router is None:
        return jsonify({
            "status": "error",
            "message": (
                "Order routing unavailable — workspace.json brokers configuration is "
                "missing or invalid. Check the startup logs, fix workspace.json, then restart."
            ),
        }), 503

    request_ctx = RequestContext(
        jti=str(jwt_payload.get("jti") or ""),
        actor_type="human",
        actor_id=str(jwt_payload.get("sub") or jwt_payload.get("actor_id") or "unknown"),
        mode=_MODE_LIVE,
        selector=f"{adapter_id}:{account_id}",
    )

    try:
        # Private access mirrors BrokerRouter.quotes — the session provider IS
        # the read-path ACL gate, so it must not be bypassed with a raw
        # registry lookup.
        session = router._session_provider(request_ctx, adapter_id, account_id)  # noqa: SLF001
        adapter = router._adapters.get(adapter_id)  # noqa: SLF001
        if adapter is None:
            raise BrokerNotFoundError(f"no adapter registered for {adapter_id!r}")
        method = getattr(adapter, read_verb, None)
        if not callable(method):
            raise UnsupportedCapabilityError(
                f"broker adapter {adapter_id!r} does not support the {read_verb!r} listing"
            )
        rows = asyncio.run(method(session))
    except SafetyBypassError as exc:
        logger.warning("Broker read %s refused | adapter=%s account=%s: %s", read_verb, adapter_id, account_id, exc)
        return jsonify({"status": "error", "message": f"Request refused: {exc}"}), 403
    except (BrokerNotFoundError, KeyError) as exc:
        logger.warning("Broker read %s — not connected | adapter=%s account=%s: %s", read_verb, adapter_id, account_id, exc)
        return jsonify({
            "status": "error",
            "message": (
                f"Broker '{adapter_id}' (account '{account_id}') is not connected. Add the "
                "selector to workspace.json brokers.registered and brokers.account_acls, then restart."
            ),
        }), 503
    except (NotImplementedError, UnsupportedCapabilityError) as exc:
        return jsonify({
            "status": "error",
            "message": str(exc) or f"This listing is not yet available for broker '{adapter_id}'.",
        }), 501
    except Exception:
        logger.exception("Broker read %s failed | adapter=%s account=%s", read_verb, adapter_id, account_id)
        return jsonify({"status": "error", "message": f"Failed to fetch {read_verb}"}), 500

    return jsonify({"status": "success", "data": rows}), 200


def _changes_from_body(body: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the required non-empty ``changes`` dict from a modify body, or ``None``."""
    changes = body.get("changes")
    if not isinstance(changes, dict) or not changes:
        return None
    return changes


def _trigger_legs_from_body(body: dict[str, Any]) -> tuple[dict[str, Any], list[Any]]:
    """Validate + build ``(condition, typed order legs)`` for a conditional trigger.

    Raises:
        ValueError: When ``condition`` is not a non-empty dict, ``orders`` is
            not a non-empty list of objects, or any leg fails typed-Order
            coercion (bad enum value, non-integer quantity, …).
    """
    condition = body.get("condition")
    if not isinstance(condition, dict) or not condition:
        raise ValueError("'condition' must be a non-empty object")
    raw_orders = body.get("orders")
    if not isinstance(raw_orders, list) or not raw_orders:
        raise ValueError("'orders' must be a non-empty list of order objects")
    legs: list[Any] = []
    for index, leg in enumerate(raw_orders):
        if not isinstance(leg, dict):
            raise ValueError(f"orders[{index}] must be an object")
        legs.append(_body_to_order(leg))
    return condition, legs


def _check_legs_through_safety(legs: list[Any], adapter_id: str) -> tuple[Any, int] | None:
    """Run the full SafetySystem (L1–L5) over each typed placement leg.

    Conditional-trigger PLACEMENT and MODIFY arm real orders the instant the
    condition fires, so — like :func:`multi_order_place` — every leg MUST clear
    the risk pipeline before the gate is minted (the route-level
    ``kill_switch_gated`` flag only runs L5). Without this, an over-limit leg
    (e.g. NFO qty 9999999) bypassed L1–L4. L2 reads live exposure best-effort,
    exactly as the place path does.

    Args:
        legs: Typed :class:`~flinttrade_core.models.Order` legs (already coerced
            by :func:`_body_to_order`).
        adapter_id: Target broker adapter id (scopes the L2 exposure read).

    Returns:
        ``None`` when every leg passes; otherwise a ``(flask.Response,
        http_status)`` 403 carrying the first blocking layer's reason — ready to
        be returned from the route handler before any gate is minted.
    """
    from flinttrade_engine.safety import SafetyConfig, SafetySystem  # noqa: PLC0415

    safety = current_app.config.get("SAFETY")
    if safety is None:
        safety = SafetySystem(SafetyConfig())
    l2_positions, l2_used_margin, l2_total_balance = _gather_l2_state(adapter_id)
    for leg in legs:
        results = safety.check_order(
            leg,
            positions=l2_positions,
            used_margin=l2_used_margin,
            total_balance=l2_total_balance,
        )
        blocked = next((r for r in results if not r.passed), None)
        if blocked is not None:
            logger.warning(
                "Conditional-trigger leg blocked by safety layer %s | symbol=%s: %s",
                blocked.layer, getattr(leg, "symbol", "?"), blocked.reason,
            )
            return jsonify({
                "status": "error",
                "message": f"Order blocked by safety system [{blocked.layer}]: {blocked.reason}",
            }), 403
    return None


# --- Forever (GTT) orders — Dhan-native; placed via the gated trio path ----


@orders_bp.route("/forever", methods=["POST"])
@rate_limit("orders", user_rate=10, global_rate=100)
def forever_place() -> tuple[Any, int]:
    """Place a forever (GTT) order through the gated place path (live only).

    Builds a typed ``Order`` with ``variety="gtt"`` — including the optional
    OCO second-leg trio (``price1`` / ``trigger_price1`` / ``quantity1``) and
    ``validity`` — and dispatches it through the SAME channel as a regular
    placement: SafetySystem L1–L5 → ``gate_order`` → ``BrokerRouter.place_order``.
    The variety and leg fields live on the Order, so the SafetyContext HMAC
    covers them.

    Request JSON: standard order fields plus ``trigger_price`` (required by the
    broker), optional OCO trio, optional ``broker`` (default ``"openalgo"``)
    and ``account_id`` (default ``"default"``).
    """
    payload, err = _require_live_payload(require_unlock=True)
    if err is not None:
        return err
    body = request.get_json(silent=True) or {}
    adapter_id, _account_id = _gated_target(body)  # account_id rides in the body
    return _dispatch_live_order("forever-place", body, payload, adapter_id=adapter_id, variety="gtt")


@orders_bp.route("/forever/<order_id>", methods=["PUT"])
@rate_limit("orders", user_rate=10, global_rate=100)
def forever_modify(order_id: str) -> tuple[Any, int]:
    """Modify a resting forever (GTT) order — gated ``modify_forever`` verb.

    Request JSON: ``changes`` (non-empty object, e.g. ``{"price": "2900"}``),
    optional ``broker`` / ``account_id``. A modify can increase risk, so it is
    blocked while the L5 kill switch is latched.
    """
    payload, err = _require_live_payload(require_unlock=True)
    if err is not None:
        return err
    body = request.get_json(silent=True) or {}
    changes = _changes_from_body(body)
    if changes is None:
        return jsonify({"status": "error", "message": "Modify requires a non-empty 'changes' object"}), 400
    adapter_id, account_id = _gated_target(body)
    return _gated_verb_write(
        "modify_forever", {"order_id": order_id, "changes": changes}, payload,
        adapter_id=adapter_id, account_id=account_id,
        audit_event="FOREVER_MODIFIED", fail_message="Forever order modify failed",
        ref=order_id, kill_switch_gated=True,
    )


@orders_bp.route("/forever/<order_id>", methods=["DELETE"])
@rate_limit("orders", user_rate=10, global_rate=100)
def forever_cancel(order_id: str) -> tuple[Any, int]:
    """Cancel a resting forever (GTT) order — gated ``cancel_forever`` verb.

    Target via ``?broker=`` / ``?account_id=`` query parameters (a JSON body
    with the same fields also works). Cancels reduce exposure, so the kill
    switch does not block them.
    """
    payload, err = _require_live_payload(require_unlock=True)
    if err is not None:
        return err
    params = {**request.args.to_dict(), **(request.get_json(silent=True) or {})}
    adapter_id, account_id = _gated_target(params)
    return _gated_verb_write(
        "cancel_forever", {"order_id": order_id}, payload,
        adapter_id=adapter_id, account_id=account_id,
        audit_event="FOREVER_CANCELLED", fail_message="Forever order cancel failed",
        ref=order_id,
    )


@orders_bp.route("/forever", methods=["GET"])
def forever_list() -> tuple[Any, int]:
    """List resting forever (GTT) orders — adapter ``forever_orders`` read.

    Target via ``?broker=`` / ``?account_id=`` query parameters. 501 for
    brokers whose adapter does not expose the listing.
    """
    payload, err = _require_live_payload(require_unlock=False)
    if err is not None:
        return err
    adapter_id, account_id = _gated_target(request.args)
    return _gated_broker_read("forever_orders", payload, adapter_id=adapter_id, account_id=account_id)


# --- Super orders (Dhan bracket/cover legs) --------------------------------


@orders_bp.route("/super", methods=["GET"])
def super_order_list() -> tuple[Any, int]:
    """List super orders with leg details — adapter ``super_orders`` read."""
    payload, err = _require_live_payload(require_unlock=False)
    if err is not None:
        return err
    adapter_id, account_id = _gated_target(request.args)
    return _gated_broker_read("super_orders", payload, adapter_id=adapter_id, account_id=account_id)


@orders_bp.route("/super/<order_id>", methods=["PUT"])
@rate_limit("orders", user_rate=10, global_rate=100)
def super_order_modify(order_id: str) -> tuple[Any, int]:
    """Modify one leg of a pending super order — gated ``modify_super_order`` verb.

    Request JSON: ``changes`` (non-empty object; ``changes.leg_name`` selects
    ENTRY_LEG / TARGET_LEG / STOP_LOSS_LEG), optional ``broker`` /
    ``account_id``. Kill-switch gated (a leg modify can widen risk).
    """
    payload, err = _require_live_payload(require_unlock=True)
    if err is not None:
        return err
    body = request.get_json(silent=True) or {}
    changes = _changes_from_body(body)
    if changes is None:
        return jsonify({"status": "error", "message": "Modify requires a non-empty 'changes' object"}), 400
    adapter_id, account_id = _gated_target(body)
    return _gated_verb_write(
        "modify_super_order", {"order_id": order_id, "changes": changes}, payload,
        adapter_id=adapter_id, account_id=account_id,
        audit_event="SUPER_ORDER_MODIFIED", fail_message="Super order modify failed",
        ref=order_id, kill_switch_gated=True,
    )


@orders_bp.route("/super/<order_id>", methods=["DELETE"])
@rate_limit("orders", user_rate=10, global_rate=100)
def super_order_cancel(order_id: str) -> tuple[Any, int]:
    """Cancel a super order or one leg — gated ``cancel_super_order`` verb.

    Optional ``?leg=`` selects ENTRY_LEG (default; cancels every leg),
    TARGET_LEG, or STOP_LOSS_LEG. The leg travels inside the signed payload.
    """
    payload, err = _require_live_payload(require_unlock=True)
    if err is not None:
        return err
    params = {**request.args.to_dict(), **(request.get_json(silent=True) or {})}
    fields: dict[str, Any] = {"order_id": order_id}
    leg = params.get("leg")
    if leg is not None:
        leg = str(leg).strip().upper()
        if leg not in _SUPER_ORDER_LEGS:
            return jsonify({
                "status": "error",
                "message": f"'leg' must be one of {sorted(_SUPER_ORDER_LEGS)}, got {leg!r}",
            }), 400
        fields["leg"] = leg
    adapter_id, account_id = _gated_target(params)
    return _gated_verb_write(
        "cancel_super_order", fields, payload,
        adapter_id=adapter_id, account_id=account_id,
        audit_event="SUPER_ORDER_CANCELLED", fail_message="Super order cancel failed",
        ref=order_id,
    )


# --- Conditional triggers (Dhan v2.5 alerts/orders) -------------------------


@orders_bp.route("/triggers", methods=["POST"])
@rate_limit("orders", user_rate=10, global_rate=100)
def trigger_place() -> tuple[Any, int]:
    """Place a conditional trigger — gated ``place_conditional_trigger`` verb.

    Request JSON: ``condition`` (non-empty object) + ``orders`` (non-empty list
    of order objects; each is coerced to a typed ``Order`` so the signed
    payload covers every leg field), optional ``broker`` / ``account_id``.
    Trade-affecting placement → kill-switch gated.
    """
    payload, err = _require_live_payload(require_unlock=True)
    if err is not None:
        return err
    body = request.get_json(silent=True) or {}
    try:
        condition, legs = _trigger_legs_from_body(body)
    except ValueError as exc:
        return jsonify({"status": "error", "message": f"Trigger validation failed: {exc}"}), 400
    adapter_id, account_id = _gated_target(body)
    # Run the FULL SafetySystem (L1–L5) over every leg — a placement path must
    # never skip the risk layers (the kill-switch flag below only runs L5).
    blocked = _check_legs_through_safety(legs, adapter_id)
    if blocked is not None:
        return blocked
    return _gated_verb_write(
        "place_conditional_trigger", {"condition": condition, "orders": legs}, payload,
        adapter_id=adapter_id, account_id=account_id,
        audit_event="TRIGGER_PLACED", fail_message="Conditional trigger placement failed",
        kill_switch_gated=True,
    )


@orders_bp.route("/triggers", methods=["GET"])
def trigger_list() -> tuple[Any, int]:
    """List conditional triggers — adapter ``conditional_triggers`` read."""
    payload, err = _require_live_payload(require_unlock=False)
    if err is not None:
        return err
    adapter_id, account_id = _gated_target(request.args)
    return _gated_broker_read("conditional_triggers", payload, adapter_id=adapter_id, account_id=account_id)


@orders_bp.route("/triggers/<alert_id>", methods=["PUT"])
@rate_limit("orders", user_rate=10, global_rate=100)
def trigger_modify(alert_id: str) -> tuple[Any, int]:
    """Modify a conditional trigger — gated ``modify_conditional_trigger`` verb.

    Request JSON: full replacement ``condition`` + ``orders`` (same shape as
    placement), optional ``broker`` / ``account_id``. Kill-switch gated.
    """
    payload, err = _require_live_payload(require_unlock=True)
    if err is not None:
        return err
    body = request.get_json(silent=True) or {}
    try:
        condition, legs = _trigger_legs_from_body(body)
    except ValueError as exc:
        return jsonify({"status": "error", "message": f"Trigger validation failed: {exc}"}), 400
    adapter_id, account_id = _gated_target(body)
    # A modify replaces the armed legs, so re-run the FULL SafetySystem (L1–L5)
    # over the new legs before re-gating — same brake as placement.
    blocked = _check_legs_through_safety(legs, adapter_id)
    if blocked is not None:
        return blocked
    return _gated_verb_write(
        "modify_conditional_trigger",
        {"alert_id": alert_id, "condition": condition, "orders": legs},
        payload,
        adapter_id=adapter_id, account_id=account_id,
        audit_event="TRIGGER_MODIFIED", fail_message="Conditional trigger modify failed",
        ref=alert_id, kill_switch_gated=True,
    )


@orders_bp.route("/triggers/<alert_id>", methods=["DELETE"])
@rate_limit("orders", user_rate=10, global_rate=100)
def trigger_cancel(alert_id: str) -> tuple[Any, int]:
    """Cancel a conditional trigger — gated ``cancel_conditional_trigger`` verb."""
    payload, err = _require_live_payload(require_unlock=True)
    if err is not None:
        return err
    params = {**request.args.to_dict(), **(request.get_json(silent=True) or {})}
    adapter_id, account_id = _gated_target(params)
    return _gated_verb_write(
        "cancel_conditional_trigger", {"alert_id": alert_id}, payload,
        adapter_id=adapter_id, account_id=account_id,
        audit_event="TRIGGER_CANCELLED", fail_message="Conditional trigger cancel failed",
        ref=alert_id,
    )


# --- Batch + smart-order verbs ----------------------------------------------


@orders_bp.route("/multi", methods=["POST"])
@rate_limit("orders", user_rate=10, global_rate=100)
def multi_order_place() -> tuple[Any, int]:
    """Place a batch of orders — gated ``place_multi_order`` verb (Upstox-native).

    Request JSON: ``orders`` (non-empty list of order objects), optional
    ``broker`` / ``account_id``. EVERY leg is coerced to a typed ``Order`` and
    run through the full SafetySystem (L1–L5) before the batch is gated — a
    placement path must never skip the risk layers. The signed payload carries
    the typed legs, so post-mint tampering with any leg invalidates the gate.
    """
    from pydantic import ValidationError  # noqa: PLC0415

    from flinttrade_engine.safety import SafetyConfig, SafetySystem  # noqa: PLC0415

    payload, err = _require_live_payload(require_unlock=True)
    if err is not None:
        return err
    body = request.get_json(silent=True) or {}
    raw_orders = body.get("orders")
    if not isinstance(raw_orders, list) or not raw_orders:
        return jsonify({"status": "error", "message": "'orders' must be a non-empty list of order objects"}), 400
    adapter_id, account_id = _gated_target(body)

    safety = current_app.config.get("SAFETY")
    if safety is None:
        safety = SafetySystem(SafetyConfig())
    l2_positions, l2_used_margin, l2_total_balance = _gather_l2_state(adapter_id)
    legs: list[Any] = []
    try:
        for index, leg in enumerate(raw_orders):
            if not isinstance(leg, dict):
                raise ValueError(f"orders[{index}] must be an object")
            typed = _body_to_order(leg)
            results = safety.check_order(
                typed,
                positions=l2_positions,
                used_margin=l2_used_margin,
                total_balance=l2_total_balance,
            )
            blocked = next((r for r in results if not r.passed), None)
            if blocked is not None:
                logger.warning(
                    "Multi-order leg blocked by safety layer %s | symbol=%s: %s",
                    blocked.layer, typed.symbol, blocked.reason,
                )
                return jsonify({
                    "status": "error",
                    "message": f"Order blocked by safety system [{blocked.layer}]: {blocked.reason}",
                }), 403
            legs.append(typed)
    except (ValueError, ValidationError) as exc:
        return jsonify({"status": "error", "message": f"Order validation failed: {exc}"}), 400

    return _gated_verb_write(
        "place_multi_order", {"orders": legs}, payload,
        adapter_id=adapter_id, account_id=account_id,
        audit_event="MULTI_ORDER_PLACED", fail_message="Multi-order placement failed",
    )


@orders_bp.route("/smart/<order_id>", methods=["DELETE"])
@rate_limit("orders", user_rate=10, global_rate=100)
def smart_order_cancel(order_id: str) -> tuple[Any, int]:
    """Cancel a smart order — gated ``cancel_smart_order`` verb (IndMoney-native).

    Optional ``?segment=`` narrows the cancel (e.g. ``DERIVATIVE``); it travels
    inside the signed payload. Cancels reduce exposure → not kill-switch gated.
    """
    payload, err = _require_live_payload(require_unlock=True)
    if err is not None:
        return err
    params = {**request.args.to_dict(), **(request.get_json(silent=True) or {})}
    fields: dict[str, Any] = {"order_id": order_id}
    if params.get("segment") is not None:
        fields["segment"] = str(params["segment"])
    adapter_id, account_id = _gated_target(params)
    return _gated_verb_write(
        "cancel_smart_order", fields, payload,
        adapter_id=adapter_id, account_id=account_id,
        audit_event="SMART_ORDER_CANCELLED", fail_message="Smart order cancel failed",
        ref=order_id,
    )
