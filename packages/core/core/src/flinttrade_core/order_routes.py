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

import asyncio
import logging
import math
import time
from collections.abc import Callable, Collection, Mapping
from contextlib import nullcontext
from types import SimpleNamespace
from typing import Any

import httpx
import jwt
from flask import Blueprint, current_app, jsonify, request

from flinttrade_gateway.log_safety import account_ref, log_ref

from .rate_limiter import rate_limit

logger = logging.getLogger("flinttrade.order_routes")



def _run_on_client_loop(coro: Any) -> Any:
    """Run a broker-bound coroutine on the shared client's owner event loop.

    Order dispatch and gated reads ultimately await the app-owned OpenAlgo
    client (and native adapters' pooled HTTP clients). Driving them on a fresh
    ``asyncio.run()`` loop per request poisons those loop-affine connection
    pools ("Event loop is closed" on alternating requests), so every sync
    entry point marshals onto ONE persistent loop via the client's run_sync.
    Falls back to ``asyncio.run`` when no shared client is configured (tests).
    """
    from .openalgo_client import OpenAlgoClient  # noqa: PLC0415

    client = current_app.config.get("CLIENT") or current_app.config.get("OPENALGO_CLIENT")
    if isinstance(client, OpenAlgoClient):
        return client.run_sync(coro)
    # Test fakes / unconfigured apps: one fresh loop per call is correct.
    return asyncio.run(coro)


def _redact_exc(exc: object, account_id: object) -> str:
    """Scrub a raw broker account id out of an exception message for logging.

    Registry and session-provider errors embed the raw selector (for example
    ``"Account 'D1' not found in registry."``); logging the exception tail
    verbatim would re-leak the account id that :func:`account_ref` is meant to
    keep out of runtime logs. Returns the message with any literal occurrence of
    the account id replaced by its stable, non-reversible reference.
    """
    text = str(exc)
    raw = str(account_id or "").strip()
    if raw and raw in text:
        text = text.replace(raw, account_ref(account_id))
    return text

# Frontend `api.ts` posts to `/ft-api/api/v1/orders/<X>` (→ `/api/v1/orders/<X>`
# after the WSGI prefix strip). The blueprint must therefore live under
# `/api/v1/orders`, not the project's general `/v1/X` convention. (Previously
# registered at `/v1/orders/*`, which silently 404'd every order placement
# until the 2026-05-19 multi-agent audit surfaced it.) The advanced-order
# routes (basket / split / options-strategy) were folded into this blueprint on
# 2026-07-09 — previously a separate engine `order_bp` mounted at the same
# prefix — so one blueprint now owns the whole `/api/v1/orders/*` surface.
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


def _mode_header_mismatch_response(
    jwt_mode: str | None,
    *,
    route_label: str,
) -> tuple[Any, int] | None:
    """Reject a supplied client mode assertion that contradicts signed JWT authority."""
    header_mode = (request.headers.get("X-FlintTrade-Mode") or "").strip().lower()
    signed_mode = (jwt_mode or "").strip().lower()
    if not header_mode or not signed_mode or header_mode == signed_mode:
        return None

    logger.warning(
        "%s — X-FlintTrade-Mode header ('%s') disagrees with JWT mode claim ('%s'); rejected",
        route_label,
        header_mode,
        signed_mode,
    )
    return jsonify({
        "status": "error",
        "message": "X-FlintTrade-Mode does not match the authenticated mode",
    }), 403


def _openalgo_base_url() -> str:
    """Resolve the OpenAlgo base URL from app config or workspace/env fallback.

    Checks ``app.config["CLIENT"]`` first (has ``settings.openalgo_host``),
    then falls back to Settings.from_env() so UI-owned ``workspace.json`` config
    is honoured even in minimal Flask apps.

    Returns:
        Base URL string, e.g. ``"http://127.0.0.1:5000"``, trailing slash stripped.
    """
    client = current_app.config.get("CLIENT")
    if client is not None:
        try:
            from .config import openalgo_rest_base_url  # noqa: PLC0415

            return openalgo_rest_base_url(client.settings)
        except AttributeError:
            pass

    from .config import Settings, openalgo_rest_base_url  # noqa: PLC0415

    settings = Settings.from_env()
    return openalgo_rest_base_url(settings)


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
    from .config import Settings  # noqa: PLC0415

    return Settings.from_env().openalgo_api_key


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
            body (``validity``, the Dhan OCO second-leg trio ``price1`` /
            ``trigger_price1`` / ``quantity1``, the Upstox protective
            ``target_price`` / ``stop_loss_price`` fields, and broker-specific
            GTT ``*_trigger_type`` fields). ``None`` (the default) keeps the
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
        # Variety-specific pass-throughs (Dhan forever OCO, Upstox GTT trigger
        # conditions + validity). They live on the Order model, so the
        # SafetyContext canonical hash covers them.
        for key in (
            "validity", "price1", "trigger_price1", "quantity1",
            "target_price", "stop_loss_price",
            "entry_trigger_type", "stop_loss_trigger_type", "target_trigger_type",
        ):
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


def _safety_runtime_unavailable_response() -> tuple[Any, int]:
    return jsonify({
        "status": "error",
        "message": "Validated order safety configuration is unavailable; no broker write was sent.",
    }), 503


def _require_live_safety() -> Any:
    from .safety_config import require_ready_safety  # noqa: PLC0415

    return require_ready_safety(current_app.config)


def _live_kill_switch_block() -> tuple[Any | None, tuple[Any, int] | None]:
    """Return the L5 block and any safety-runtime availability response.

    The minimum guard applied to every NON-place live action (modify/cancel/etc.)
    that cannot yet route through the gated :class:`BrokerRouter` — a halted
    account must not be able to push any live order even on the direct-forward path.
    """
    from .safety_config import SafetyRuntimeUnavailable  # noqa: PLC0415

    try:
        safety = _require_live_safety()
    except SafetyRuntimeUnavailable:
        return None, _safety_runtime_unavailable_response()
    result = safety.l5_kill.validate()
    return (None if result.passed else result), None


def _gather_l2_state(adapter_id: str, *, account_id: str = "default") -> tuple[list[Any], float, float]:
    """Best-effort live ``(positions, used_margin, total_balance)`` for L2.

    Sync wrapper over the ONE shared :func:`flinttrade_core.l2_state.gather_l2_state`
    implementation (also used by the webhook dispatcher) — the openalgo-vs-native
    branch, session resolution, and error classification must never drift
    between copies. Runs two reads on the human order path; acceptable latency
    for the cumulative-exposure brake.
    """
    from .l2_state import gather_l2_state  # noqa: PLC0415

    return _run_on_client_loop(gather_l2_state(current_app.config, adapter_id, account_id=account_id))


def _gather_safety_state(
    adapter_id: str,
    *,
    account_id: str = "default",
    orders: list[Any] | tuple[Any, ...] = (),
    reservations: list[Any] | tuple[Any, ...] = (),
    include_order_margin: bool = False,
) -> Any:
    """Return the complete selector-scoped L2/L4 portfolio snapshot.

    Unlike :func:`_gather_l2_state`, this path is intentionally fail-closed:
    live admission cannot interpret an unavailable local daily-P&L calculation
    as zero loss.
    """
    from .l2_state import gather_safety_state  # noqa: PLC0415

    return _run_on_client_loop(
        gather_safety_state(
            current_app.config,
            adapter_id,
            account_id=account_id,
            orders=orders,
            reservations=reservations,
            include_order_margin=include_order_margin,
        )
    )


def _safety_state_unavailable_response() -> tuple[Any, int]:
    return jsonify({
        "status": "error",
        "message": "Order safety state unavailable; no order was sent.",
    }), 503


def _check_order_with_state(
    safety: Any,
    order: Any,
    portfolio_state: Any,
    *,
    adapter_id: str,
    account_id: str,
    admission: Any,
    label: str,
    margin_delta: float = 0.0,
) -> tuple[Any, int] | None:
    """Run the canonical SafetySystem and map its first refusal to HTTP 403."""
    results = safety.check_order(
        order,
        selector=f"{adapter_id}:{account_id}",
        positions=admission.positions,
        used_margin=admission.used_margin + margin_delta,
        total_balance=portfolio_state.total_balance,
        daily_pnl=portfolio_state.daily_pnl,
        starting_capital=portfolio_state.starting_capital,
        ltp=portfolio_state.ltp_for(order),
        net_delta=admission.net_delta,
        net_vega=admission.net_vega,
    )
    blocked = next((result for result in results if not result.passed), None)
    if blocked is None:
        return None
    logger.warning(
        "%s blocked by safety layer %s | symbol=%s: %s",
        label,
        blocked.layer,
        getattr(order, "symbol", "?"),
        blocked.reason,
    )
    return jsonify({
        "status": "error",
        "message": f"Order blocked by safety system [{blocked.layer}]: {blocked.reason}",
    }), 403


def _check_order_through_safety(
    order: Any,
    adapter_id: str,
    *,
    account_id: str,
    margin_delta: float = 0.0,
    label: str,
) -> tuple[Any, int] | None:
    """Gather canonical state and run complete L1-L4 admission for one order."""
    try:
        safety = _require_live_safety()
    except Exception as exc:  # noqa: BLE001 - readiness failures are admission refusals
        logger.error("%s safety runtime unavailable: %s", label, type(exc).__name__)
        return _safety_runtime_unavailable_response()
    try:
        portfolio_state = _gather_safety_state(
            adapter_id,
            account_id=account_id,
            orders=[order],
        )
        admission = portfolio_state.admission_for(0)
    except Exception as exc:  # noqa: BLE001 - broker state must fail closed
        logger.error("%s safety state unavailable | adapter=%s: %s", label, adapter_id, type(exc).__name__)
        return _safety_state_unavailable_response()
    return _check_order_with_state(
        safety,
        order,
        portfolio_state,
        adapter_id=adapter_id,
        account_id=account_id,
        admission=admission,
        label=label,
        margin_delta=margin_delta,
    )


def _admit_modify_intent(
    order_id: str,
    changes: dict[str, Any],
    adapter_id: str,
    *,
    account_id: str,
    family: str = "regular",
    lease: Any,
    requested_fields: Collection[str] | None = None,
) -> tuple[tuple[Any, int] | None, Any | None, list[Any]]:
    """Prove no-increase intent or run complete admission for a live modify."""
    from .l2_state import PortfolioSafetyStateError, classify_modify_intent  # noqa: PLC0415

    try:
        intent = _run_on_client_loop(
            classify_modify_intent(
                current_app.config,
                adapter_id,
                order_id,
                changes,
                account_id=account_id,
                family=family,
                requested_fields=requested_fields,
            )
        )
    except PortfolioSafetyStateError as refusal:
        # Every PortfolioSafetyStateError message is a sentence authored in
        # l2_state (e.g. "An OPEN Upstox GTT order cannot change quantity",
        # "Super-order modify has an invalid leg name") — a crafted,
        # operator-actionable rule refusal. A generic 503 would hide exactly
        # what the operator must change.
        #
        # Stated precisely, because the looser version of this claim is wrong:
        # of the 129 raise sites, 101 pass a bare literal and 28 interpolate a
        # value — a field label, an internal reader method name, or the
        # exchange:symbol of an instrument in the request. So runtime values DO
        # reach the operator here. What never does
        # is a traceback, a filesystem path, a credential, or the text of an
        # underlying exception: no site wraps str(exc), and the `from exc` sites
        # attach the cause without putting it in the message. The operator is
        # the data principal and the instrument is their own input, so echoing
        # it back is the point rather than a leak.
        # Matching the narrow type here, rather than testing isinstance inside
        # a bare ``except Exception``, is what makes "only l2_state's own
        # refusal sentences are ever echoed" structural rather than a runtime
        # branch. Still a refusal: same 409, same fail-closed return shape.
        logger.error(
            "Modify intent refused | family=%s adapter=%s: %s",
            family,
            adapter_id,
            refusal,
        )
        return (jsonify({"status": "error", "message": str(refusal)}), 409), None, []
    except Exception as exc:  # noqa: BLE001 - an unprovable modify must fail closed
        logger.error(
            "Modify intent unavailable | family=%s adapter=%s: %s",
            family,
            adapter_id,
            type(exc).__name__,
        )
        return _safety_state_unavailable_response(), None, []
    if not intent.risk_increasing:
        return None, None, []
    try:
        safety = _require_live_safety()
        portfolio_state = _gather_safety_state(
            adapter_id,
            account_id=account_id,
            orders=[intent.proposed_order],
            reservations=lease.reservations,
            include_order_margin=True,
        )
        lease.reconcile(getattr(portfolio_state, "reconciled_reservation_ids", ()))
        admission = portfolio_state.admission_for(0)
    except Exception as exc:  # noqa: BLE001 - broker state must fail closed
        logger.error(
            "%s order modify safety state unavailable | adapter=%s: %s",
            family.title(),
            adapter_id,
            type(exc).__name__,
        )
        return _safety_state_unavailable_response(), None, []
    blocked = _check_order_with_state(
        safety,
        intent.proposed_order,
        portfolio_state,
        adapter_id=adapter_id,
        account_id=account_id,
        admission=admission,
        label=f"{family.title()} order modify",
    )
    return blocked, intent.proposed_order, admission.positions


_CONVERSION_PRODUCT_ALIASES = {
    "CNC": "CNC",
    "D": "CNC",
    "DELIVERY": "CNC",
    "I": "MIS",
    "INTRADAY": "MIS",
    "MARGIN": "NRML",
    "MIS": "MIS",
    "NRML": "NRML",
}


def _conversion_product(value: Any) -> str:
    product = _CONVERSION_PRODUCT_ALIASES.get(str(value or "").strip().upper())
    if product is None:
        raise ValueError("unsupported conversion product")
    return product


def _conversion_side(req: dict[str, Any]) -> str:
    position_type = str(req.get("position_type") or "").strip().upper()
    transaction_type = str(req.get("transaction_type") or req.get("action") or "").strip().upper()
    from_position = {"LONG": "BUY", "SHORT": "SELL"}.get(position_type)
    from_transaction = transaction_type if transaction_type in {"BUY", "SELL"} else None
    if position_type and from_position is None:
        raise ValueError("unsupported position type")
    if transaction_type and from_transaction is None:
        raise ValueError("unsupported transaction type")
    if from_position and from_transaction and from_position != from_transaction:
        raise ValueError("conflicting conversion side")
    side = from_position or from_transaction
    if side is None:
        raise ValueError("conversion side is unavailable")
    return side


def _conversion_quantity(value: Any) -> int:
    try:
        quantity = float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid conversion quantity") from exc
    if not math.isfinite(quantity) or quantity <= 0 or not quantity.is_integer():
        raise ValueError("invalid conversion quantity")
    return int(quantity)


def _normalised_position_key(position: Any) -> tuple[str, str, str]:
    symbol = str(getattr(position, "symbol", "") or "").strip().upper()
    exchange = str(getattr(position, "exchange", "") or "").strip().upper()
    product = _conversion_product(getattr(position, "product", ""))
    return symbol, exchange, product


def _position_quantity_value(position: Any) -> float:
    try:
        quantity = float(str(getattr(position, "quantity", "")).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid authoritative position quantity") from exc
    if not math.isfinite(quantity) or not quantity.is_integer():
        raise ValueError("invalid authoritative position quantity")
    return quantity


def _project_conversion_positions(
    positions: list[Any],
    key: tuple[str, str, str],
    quantity: int,
    side: str,
) -> list[Any]:
    matched = [position for position in positions if _normalised_position_key(position) == key]
    if not matched:
        raise ValueError("conversion position is unavailable")
    current_quantity = sum(_position_quantity_value(position) for position in matched)
    signed_quantity = float(quantity if side == "BUY" else -quantity)
    if current_quantity == 0 or math.copysign(1.0, current_quantity) != math.copysign(1.0, signed_quantity):
        raise ValueError("conversion side does not match the open position")
    if abs(signed_quantity) > abs(current_quantity):
        raise ValueError("conversion quantity exceeds the open position")
    residual = current_quantity - signed_quantity
    projected = [position for position in positions if _normalised_position_key(position) != key]
    if residual:
        symbol, exchange, product = key
        projected.append(
            SimpleNamespace(
                symbol=symbol,
                exchange=exchange,
                product=product,
                quantity=str(int(residual)),
            )
        )
    return projected


def _admit_position_conversion(
    req: dict[str, Any],
    adapter_id: str,
    *,
    account_id: str,
) -> tuple[Any, int] | None:
    """Classify a conversion and admit every risk-increasing transition."""
    from flinttrade_core.models import Order  # noqa: PLC0415

    from .l2_state import (  # noqa: PLC0415
        ProspectiveSafetyInputs,
        gather_authoritative_positions,
        gather_required_order_margin,
    )

    try:
        symbol = str(req.get("symbol") or req.get("trading_symbol") or "").strip().upper()
        exchange = str(req.get("exchange") or "").strip().upper()
        from_product = _conversion_product(
            req.get("from_product", req.get("from_product_type", req.get("old_product")))
        )
        to_product = _conversion_product(
            req.get("to_product", req.get("to_product_type", req.get("new_product")))
        )
        quantity = _conversion_quantity(req.get("quantity", req.get("convert_qty")))
        side = _conversion_side(req)
        if not symbol or not exchange or from_product == to_product:
            raise ValueError("incomplete or no-op conversion")
        old_order = Order(
            symbol=symbol,
            exchange=exchange,
            action=side,
            product=from_product,
            quantity=str(quantity),
            pricetype="MARKET",
        )
        new_order = Order(
            symbol=symbol,
            exchange=exchange,
            action=side,
            product=to_product,
            quantity=str(quantity),
            pricetype="MARKET",
        )
    except Exception:
        return jsonify({
            "status": "error",
            "message": "Position conversion intent could not be verified.",
        }), 400

    try:
        authoritative_positions = _run_on_client_loop(
            gather_authoritative_positions(
                current_app.config,
                adapter_id,
                account_id=account_id,
            )
        )
        key = (symbol, exchange, from_product)
        _project_conversion_positions(
            authoritative_positions,
            key,
            quantity,
            side,
        )
        old_margin = _run_on_client_loop(
            gather_required_order_margin(
                current_app.config,
                adapter_id,
                old_order,
                account_id=account_id,
                allow_zero=True,
            )
        )
        new_margin = _run_on_client_loop(
            gather_required_order_margin(
                current_app.config,
                adapter_id,
                new_order,
                account_id=account_id,
                allow_zero=True,
            )
        )
    except ValueError:
        return jsonify({
            "status": "error",
            "message": "Position conversion does not match an authoritative open position.",
        }), 400
    except Exception as exc:  # noqa: BLE001 - state and margin reads must fail closed
        logger.error("Position conversion safety state unavailable | adapter=%s: %s", adapter_id, type(exc).__name__)
        return _safety_state_unavailable_response()

    proven_no_increase = (
        from_product in {"CNC", "NRML"}
        and to_product == "MIS"
        and new_margin <= old_margin + 1e-9
    )
    if proven_no_increase:
        return None
    try:
        portfolio_state = _gather_safety_state(adapter_id, account_id=account_id)
        projected_positions = _project_conversion_positions(
            portfolio_state.positions,
            key,
            quantity,
            side,
        )
    except ValueError:
        return jsonify({
            "status": "error",
            "message": "Position conversion does not match an authoritative open position.",
        }), 400
    except Exception as exc:  # noqa: BLE001 - complete safety state must fail closed
        logger.error("Position conversion safety state unavailable | adapter=%s: %s", adapter_id, type(exc).__name__)
        return _safety_state_unavailable_response()
    try:
        safety = _require_live_safety()
    except Exception as exc:  # noqa: BLE001 - readiness failures are admission refusals
        logger.error("Position conversion safety runtime unavailable: %s", type(exc).__name__)
        return _safety_runtime_unavailable_response()
    projected_margin = max(portfolio_state.used_margin + new_margin - old_margin, 0.0)
    conversion_admission = ProspectiveSafetyInputs(
        positions=projected_positions,
        used_margin=projected_margin,
        net_delta=portfolio_state.net_delta,
        net_vega=portfolio_state.net_vega,
    )
    return _check_order_with_state(
        safety,
        new_order,
        portfolio_state,
        adapter_id=adapter_id,
        account_id=account_id,
        admission=conversion_admission,
        label="Position conversion",
    )


def _admit_and_route_live_order(
    *,
    safety: Any,
    router: Any,
    typed_order: Any,
    request_ctx: Any,
    adapter_id: str,
    account_id: str,
    ft_action: str,
    body: dict[str, Any],
    lease: Any = None,
) -> tuple[bool, Any]:
    """Atomically snapshot, check, gate, reserve, and dispatch one live order."""
    from pydantic import ValidationError  # noqa: PLC0415

    from flinttrade_core.exceptions import SafetyBypassError  # noqa: PLC0415
    from flinttrade_engine.safety import gate_order  # noqa: PLC0415
    from flinttrade_gateway.routing_config import RoutingHint  # noqa: PLC0415

    selector = f"{adapter_id}:{account_id}"
    admission_scope = nullcontext(lease) if lease is not None else safety.order_admission(selector)
    with admission_scope as active_lease:
        if active_lease.selector != selector:
            raise SafetyBypassError("order admission lease selector mismatch")
        try:
            portfolio_state = _gather_safety_state(
                adapter_id,
                account_id=account_id,
                orders=[typed_order],
                reservations=active_lease.reservations,
                include_order_margin=True,
            )
        except Exception as exc:  # noqa: BLE001 - fail closed without leaking broker details
            logger.error(
                "Live order rejected because portfolio safety state is unavailable | action=%s adapter=%s: %s",
                ft_action,
                adapter_id,
                type(exc).__name__,
            )
            return False, _safety_state_unavailable_response()
        active_lease.reconcile(getattr(portfolio_state, "reconciled_reservation_ids", ()))
        admission = portfolio_state.admission_for(0)
        try:
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
        except (ValueError, ValidationError) as exc:
            logger.warning(
                "Live order rejected by order-model/safety validation | action=%s adapter=%s: %s",
                ft_action,
                adapter_id,
                exc,
            )
            message = "Order validation failed"
            raw_quantity = body.get("quantity")
            if raw_quantity is not None:
                try:
                    if not float(raw_quantity).is_integer():
                        message = "Invalid order quantity"
                except (TypeError, ValueError):
                    message = "Invalid order quantity"
            return False, (jsonify({"status": "error", "message": message}), 400)

        blocked = next((result for result in safety_results if not result.passed), None)
        if blocked is not None:
            logger.warning(
                "Live order blocked by safety layer %s | action=%s adapter=%s symbol=%s: %s",
                blocked.layer,
                ft_action,
                adapter_id,
                body.get("symbol", "?"),
                blocked.reason,
            )
            _desktop_notify(
                f"Order blocked by safety [{blocked.layer}]",
                f"{ft_action} {body.get('symbol', '?')}: {blocked.reason}",
            )
            return False, (
                jsonify({
                    "status": "error",
                    "message": f"Order blocked by safety system [{blocked.layer}]: {blocked.reason}",
                }),
                403,
            )

        safety_ctx = gate_order(
            typed_order,
            request_ctx,
            adapter_id=adapter_id,
            account_id=account_id,
        )
        reservation = active_lease.reserve(typed_order, admission.positions)
        result = _run_on_client_loop(
            router.place_order(
                request_ctx,
                order=typed_order,
                safety_ctx=safety_ctx,
                hint=RoutingHint(adapter_id=adapter_id, account_id=account_id),
            )
        )
        active_lease.acknowledge(reservation, result)
        return True, result


def _dispatch_live_order(
    ft_action: str,
    body: dict[str, Any],
    payload: dict[str, Any],
    *,
    adapter_id: str = "openalgo",
    account_id: str | None = None,
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

    from pydantic import ValidationError  # noqa: PLC0415

    from flinttrade_core.exceptions import SafetyBypassError, UnsupportedCapabilityError  # noqa: PLC0415
    from flinttrade_engine.algo_tag_guard import AlgoTagLimitError  # noqa: PLC0415
    from flinttrade_engine.request_context import RequestContext  # noqa: PLC0415
    from flinttrade_gateway.exceptions import BrokerNotFoundError  # noqa: PLC0415

    account_id = account_id or str(body.get("account_id") or "default")

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

    try:
        safety = _require_live_safety()
    except Exception as exc:  # noqa: BLE001 - readiness failures are an admission refusal
        logger.error("Live order rejected because safety runtime is unavailable: %s", type(exc).__name__)
        return _safety_runtime_unavailable_response()

    try:
        typed_order = _body_to_order(body, variety=variety)
    except ValueError as exc:
        logger.warning(
            "Live order rejected by order-model validation | action=%s adapter=%s: %s",
            ft_action, adapter_id, exc,
        )
        message = "Order validation failed"
        raw_quantity = body.get("quantity")
        if raw_quantity is not None:
            try:
                if not float(raw_quantity).is_integer():
                    message = "Invalid order quantity"
            except (TypeError, ValueError):
                message = "Invalid order quantity"
        return jsonify({"status": "error", "message": message}), 400
    except ValidationError as exc:
        logger.warning(
            "Live order rejected by order-model validation | action=%s adapter=%s: %s",
            ft_action, adapter_id, exc,
        )
        return jsonify({"status": "error", "message": "Order validation failed"}), 400

    _t0 = time.perf_counter()
    safe_account = account_ref(account_id)
    try:
        admitted, outcome = _admit_and_route_live_order(
            safety=safety,
            router=router,
            typed_order=typed_order,
            request_ctx=request_ctx,
            adapter_id=adapter_id,
            account_id=account_id,
            ft_action=ft_action,
            body=body,
        )
        if not admitted:
            return outcome
        result = outcome
        # Feed the latency monitors (audit H5) — without this producer the
        # order latency stats were empty forever. ONE producer site, both
        # sinks: the in-memory tracker serves the session stats surface
        # (/api/v1/latency/*) and the DuckDB LatencyMonitor persists the
        # admin history (/v1/admin/latency/*), which previously had NO
        # producer at all and reported empty forever (U12). Best-effort:
        # never let monitoring affect the order result.
        try:
            from .monitoring_routes import get_latency_tracker  # noqa: PLC0415

            _latency_ms = (time.perf_counter() - _t0) * 1000.0
            _symbol = getattr(typed_order, "symbol", "") or ""
            get_latency_tracker().record_order_latency(adapter_id, _symbol, _latency_ms)
            _persistent_monitor = current_app.config.get("LATENCY_MONITOR")
            if _persistent_monitor is not None:
                # Label GTT/variety dispatches distinctly so the admin history
                # does not conflate them with regular placements.
                _op = "PLACE" if not variety else f"{variety.upper()}-PLACE"
                _persistent_monitor.record(
                    adapter_id, _op, _latency_ms, symbol=_symbol
                )
        except Exception:  # pragma: no cover - monitoring must never break orders
            logger.debug("order latency record failed", exc_info=True)
    except SafetyBypassError as exc:
        logger.warning(
            "Live order refused by safety gate | action=%s adapter=%s account=%s: %s",
            ft_action, adapter_id, safe_account, _redact_exc(exc, account_id),
        )
        return jsonify({"status": "error", "message": "Order refused"}), 403
    except (BrokerNotFoundError, KeyError) as exc:
        logger.warning(
            "Live order — broker not connected | action=%s adapter=%s account=%s: %s",
            ft_action, adapter_id, safe_account, _redact_exc(exc, account_id),
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
            ft_action, adapter_id, safe_account, _redact_exc(exc, account_id),
        )
        return jsonify({"status": "error", "message": "Order refused by rate guard"}), 429
    except (NotImplementedError, UnsupportedCapabilityError) as exc:
        # Gated-skeleton adapters (e.g. Dhan) raise NotImplementedError for
        # un-built order paths; an adapter raises UnsupportedCapabilityError for
        # a capability it does not advertise. Both are an honest "not yet
        # available", not a server fault — map to 501 with the adapter message.
        logger.warning(
            "Live order — adapter capability not available | action=%s adapter=%s account=%s: %s",
            ft_action, adapter_id, safe_account, _redact_exc(exc, account_id),
        )
        return jsonify({
            "status": "error",
            "message": f"Order placement ({ft_action}) is not yet available for broker '{adapter_id}'.",
        }), 501
    except Exception:
        logger.exception(
            "Live order dispatch failed | action=%s adapter=%s account=%s",
            ft_action, adapter_id, safe_account,
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
        ft_action, adapter_id, safe_account, body.get("symbol", "?"),
    )
    # Native desktop notification (best-effort, desktop-shell only) — after the
    # order is already placed, so it can never affect execution.
    _desktop_notify(
        "Live order dispatched",
        f"{ft_action} {body.get('symbol', '?')} via {adapter_id}",
    )
    # Return both keys: ``orderid`` (legacy OpenAlgo response shape the UI reads)
    # and ``data`` (the routed-path shape) so the frontend works either way.
    return jsonify({"status": "success", "orderid": result, "data": result}), 200


def _desktop_notify(title: str, body: str = "") -> None:
    """Raise a native desktop notification, never letting it break the caller."""
    try:
        from .desktop_notify import notify  # noqa: PLC0415

        notify(title, body)
    except Exception:  # noqa: BLE001 - order/safety path must be unaffected
        pass


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
    admission_lease: Any = None,
    exposure_order: Any = None,
    exposure_positions: list[Any] | tuple[Any, ...] = (),
    reservation_order_id: str = "",
) -> tuple[Any, int]:
    """Shared gate -> ACL -> one-shot dispatch + fail-closed mapping for modify/cancel.

    ``canonical_order`` is the fingerprint ``gate_order`` signs and the router
    re-verifies; ``dispatch(router, request_ctx, safety_ctx)`` returns the broker
    coroutine. Mirrors the ``place`` path's fail-closed matrix
    (503/403/503/500) and echoes ``order_id`` on success.
    """

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
    safe_account = account_ref(account_id)
    safe_order = log_ref(order_id, kind="order")

    try:
        safety_ctx = gate_order(canonical_order, request_ctx, adapter_id=adapter_id, account_id=account_id)
        reservation = None
        if exposure_order is not None:
            if admission_lease is None:
                raise SafetyBypassError("risk-increasing broker write lacks an order admission lease")
            reservation = admission_lease.reserve(exposure_order, exposure_positions)
        result = _run_on_client_loop(dispatch(router, request_ctx, safety_ctx))
        if reservation is not None:
            acknowledgement = {"orderid": reservation_order_id} if reservation_order_id else result
            admission_lease.acknowledge(reservation, acknowledgement)
    except SafetyBypassError as exc:
        logger.warning("Live %s refused by safety gate | order=%s: %s", op, safe_order, exc)
        return jsonify({"status": "error", "message": "Order refused"}), 403
    except AlgoTagLimitError as exc:
        # The router's algo-tag guard refused the dispatch (per-(broker,
        # exchange) per-second algo-order ceiling). A throttle refusal callers
        # should retry — 429, mirroring the place path; never a 500.
        logger.warning("Live %s refused by algo-tag guard | order=%s: %s", op, safe_order, exc)
        return jsonify({"status": "error", "message": "Order refused by rate guard"}), 429
    except (BrokerNotFoundError, KeyError) as exc:
        logger.warning(
            "Live %s — broker not connected | adapter=%s account=%s: %s",
            op, adapter_id, safe_account, _redact_exc(exc, account_id),
        )
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
        logger.warning(
            "Live %s — adapter capability not available | adapter=%s account=%s: %s",
            op,
            adapter_id,
            safe_account,
            _redact_exc(exc, account_id),
        )
        return jsonify({
            "status": "error",
            "message": f"This operation ({op}) is not yet available for broker '{adapter_id}'.",
        }), 501
    except Exception:
        logger.exception("Live %s dispatch failed | order=%s adapter=%s", op, safe_order, adapter_id)
        return jsonify({"status": "error", "message": fail_message}), 500

    _audit_write_event(audit_event, adapter_id, account_id, request_ctx.actor_id, order_id)
    logger.info("Live %s dispatched | order=%s adapter=%s account=%s", op, safe_order, adapter_id, safe_account)
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
        "trigger_price": str(body.get("trigger_price", "0")),
        "disclosed_quantity": str(body.get("disclosed_quantity", "0")),
        "strategy": str(body.get("strategy") or "Flint"),
    }


def _requested_modify_fields(body: Mapping[str, Any]) -> list[str]:
    """Preserve which full-replacement fields came from the operator request."""
    aliases = {
        "symbol": ("symbol",),
        "exchange": ("exchange",),
        "action": ("action",),
        "product": ("product",),
        "quantity": ("quantity",),
        "price": ("price",),
        "price_type": ("pricetype", "order_type"),
        "trigger_price": ("trigger_price",),
        "disclosed_quantity": ("disclosed_quantity",),
    }
    return sorted(
        field
        for field, request_keys in aliases.items()
        if any(request_key in body for request_key in request_keys)
    )


def _dispatch_live_modify(
    body: dict[str, Any],
    payload: dict[str, Any],
    *,
    adapter_id: str = "openalgo",
    account_id: str | None = None,
) -> tuple[Any, int]:
    """Gate a live order MODIFY through the BrokerRouter (one-shot gate + ACL).

    A modify is not a fresh placement, so it does not run the full SafetySystem
    order pipeline — but it IS gated behind the L5 kill switch (a modify can
    increase risk) plus the one-shot SafetyContext + per-account ACL.
    """
    from pydantic import ValidationError  # noqa: PLC0415

    from flinttrade_core.models import ModifyOrder  # noqa: PLC0415
    from flinttrade_gateway.routing_config import RoutingHint  # noqa: PLC0415

    account_id = account_id or str(body.get("account_id") or "default")
    order_id = str(body.get("orderid") or "").strip()
    if not order_id:
        return jsonify({"status": "error", "message": "Modify requires an 'orderid'"}), 400
    safe_order = log_ref(order_id, kind="order")

    blocked, unavailable = _live_kill_switch_block()
    if unavailable is not None:
        return unavailable
    if blocked is not None:
        logger.warning("Live modify blocked by kill switch | order=%s: %s", safe_order, blocked.reason)
        return jsonify({
            "status": "error",
            "message": f"Order blocked by safety system [{blocked.layer}]: {blocked.reason}",
        }), 403

    changes = _modify_changes(body)
    requested_fields = _requested_modify_fields(body)
    try:
        ModifyOrder(orderid=order_id, **changes)  # validate up-front; no gate consumed on bad input
    except (ValueError, ValidationError) as exc:
        logger.warning("Live modify rejected by order-model validation | order=%s: %s", safe_order, exc)
        return jsonify({"status": "error", "message": "Modify validation failed"}), 400

    try:
        safety = _require_live_safety()
    except Exception as exc:  # noqa: BLE001 - readiness failures are admission refusals
        logger.error("Live modify safety runtime unavailable: %s", type(exc).__name__)
        return _safety_runtime_unavailable_response()
    with safety.order_admission(f"{adapter_id}:{account_id}") as lease:
        admission_block, exposure_order, exposure_positions = _admit_modify_intent(
            order_id,
            changes,
            adapter_id,
            account_id=account_id,
            lease=lease,
            requested_fields=set(requested_fields),
        )
        if admission_block is not None:
            return admission_block
        if str(changes.get("pricetype", "")).upper() in {"SL", "SL-M"}:
            try:
                trigger = float(str(changes.get("trigger_price", "0")).strip())
            except (TypeError, ValueError):
                trigger = 0.0
            if not math.isfinite(trigger) or trigger <= 0:
                return jsonify({
                    "status": "error",
                    "message": "A positive trigger price is required to modify a stop-loss order",
                }), 400

        canonical = {
            "_op": "modify",
            "order_id": order_id,
            "_requested_change_fields": requested_fields,
            **changes,
        }
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
            admission_lease=lease,
            exposure_order=exposure_order,
            exposure_positions=exposure_positions,
            reservation_order_id=order_id,
        )


def _dispatch_live_cancel(
    body: dict[str, Any],
    payload: dict[str, Any],
    *,
    adapter_id: str = "openalgo",
    account_id: str | None = None,
) -> tuple[Any, int]:
    """Gate a live order CANCEL through the BrokerRouter (one-shot gate + ACL).

    A cancellation can also remove a protective exit, so ordinary cancel calls
    are blocked once L5 is latched. Operators retry the selector-bound emergency
    policy instead; that path carries signed emergency intent through the same
    one-shot SafetyContext + per-account ACL.

    Optional ``variety`` / ``amo`` / ``trading_symbol`` body fields (Kotak Neo
    bracket/cover/AMO exits) and Groww-only ``segment`` (regular order cancel)
    are forwarded as adapter-level cancel extras. They are written into the
    canonical cancel fingerprint BEFORE the gate is minted, so the router's
    field-by-field extras check passes only because the gate signed them — an
    unhashed extra can never reach the broker.
    """
    from flinttrade_gateway.routing_config import RoutingHint  # noqa: PLC0415

    account_id = account_id or str(body.get("account_id") or "default")
    order_id = str(body.get("orderid") or "").strip()
    if not order_id:
        return jsonify({"status": "error", "message": "Cancel requires an 'orderid'"}), 400
    blocked, unavailable = _live_kill_switch_block()
    if unavailable is not None:
        return unavailable
    if blocked is not None:
        return jsonify({
            "status": "error",
            "message": f"Order blocked by safety system [{blocked.layer}]: {blocked.reason}",
        }), 403

    extras: dict[str, Any] = {}
    if body.get("variety") is not None:
        extras["variety"] = str(body["variety"])
    if body.get("amo") is not None:
        extras["amo"] = bool(body["amo"])
    if body.get("trading_symbol") is not None:
        extras["trading_symbol"] = str(body["trading_symbol"])
    if adapter_id == "groww" and body.get("segment") is not None:
        extras["segment"] = str(body["segment"])

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

    # A supplied client mode can only narrow the signed JWT authority. Reject a
    # mismatch before decoding the body or reaching sandbox/gated dispatch.
    mismatch = _mode_header_mismatch_response(mode, route_label=f"Order request to /{ft_action}")
    if mismatch is not None:
        return mismatch

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

        practice_order_type = str(
            body.get("order_type") or body.get("pricetype") or "MARKET"
        ).strip().upper()
        if (
            ft_action in {"place", "place-smart", "open-position", "close-position", "modify"}
            and practice_order_type != "MARKET"
            and current_app.config.get("TICK_RECORDER") is None
        ):
            return jsonify({
                "status": "error",
                "message": (
                    "Practice LIMIT and stop orders require tick capture to be running"
                ),
            }), 503

        # Only placeorder-style actions are meaningful in sandbox;
        # modify/cancel/close/open are also supported for UI parity.
        try:
            result = _sandbox_dispatch(sandbox, ft_action, body)
            if (
                ft_action in {"place", "place-smart", "open-position", "close-position"}
                and not _subscribe_pending_practice_order(result, body)
            ):
                order_id = str(result.get("order_id") or "")
                if order_id:
                    sandbox.cancel_order(order_id)
                return jsonify({
                    "status": "error",
                    "message": (
                        "Practice order was cancelled because its tick subscription failed"
                    ),
                }), 503
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
        if str(result.get("status", "")).upper() == "REJECTED":
            return jsonify({
                "status": "error",
                "message": str(result.get("message") or "Practice order rejected"),
            }), 400
        return jsonify(result), 200

    # ------------------------------------------------------------------
    # Live mode — single gated, selector-bound execution channel (C1).
    #
    # ``place`` runs the full SafetySystem (L1-L5) + one-shot HMAC gate +
    # per-account ACL via the BrokerRouter. ``modify`` and ``cancel`` run the
    # same one-shot gate + ACL and remain behind the L5 kill switch, and
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

    adapter_id, account_id = _gated_target(body)
    if ft_action == "place":
        return _dispatch_live_order(ft_action, body, live_payload, adapter_id=adapter_id, account_id=account_id)
    if ft_action == "modify":
        return _dispatch_live_modify(body, live_payload, adapter_id=adapter_id, account_id=account_id)
    if ft_action == "cancel":
        return _dispatch_live_cancel(body, live_payload, adapter_id=adapter_id, account_id=account_id)
    if ft_action == "cancel-all":
        # Every adapter, including the OpenAlgo bridge, sweeps through the
        # gated cancel_all_orders verb
        # (one-shot SafetyContext + ACL), forwarding only tag/segment. A
        # STRATEGY-scoped cancel-all cannot be honoured — the native verb has no
        # per-request strategy narrowing — so silently forwarding it would ESCALATE a
        # scoped cancel into a full-account sweep, wiping manual orders and other
        # strategies' protective resting exits. Fail closed on any strategy scope
        # (restoring the pre-consolidation behaviour, where such requests hit the
        # 501 block because they never resolved to a native broker). Explicit
        # tag/segment narrowing IS still forwarded.
        if str(body.get("strategy") or "").strip():
            logger.warning(
                "Native cancel-all with a strategy scope rejected — the native "
                "cancel_all_orders verb cannot narrow by strategy, so honouring it "
                "would cancel the whole account | adapter=%s",
                adapter_id,
            )
            return jsonify({
                "status": "error",
                "message": (
                    "Strategy-scoped cancel-all is not supported for native brokers "
                    "— it would cancel every open order on the account, including "
                    "other strategies' orders. Cancel by tag/segment, or cancel "
                    "orders individually."
                ),
            }), 400
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
    BUY and SELL. Pending LIMIT/SL orders use the engine's real modify and
    cancel lifecycle rather than simulated acknowledgements.

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
    order_type = str(body.get("order_type") or body.get("pricetype") or "MARKET").strip().upper()
    trigger_price_raw = body.get("trigger_price", 0.0)
    strategy = str(body.get("strategy") or "").strip()

    try:
        quantity = int(body.get("quantity", 0))
    except (TypeError, ValueError):
        quantity = 0

    try:
        price = float(body.get("price", 0.0))
    except (TypeError, ValueError):
        price = 0.0
    try:
        trigger_price = float(trigger_price_raw)
    except (TypeError, ValueError):
        trigger_price = 0.0

    if ft_action in ("place", "place-smart", "open-position"):
        return sandbox.place_order(
            symbol=symbol,
            exchange=exchange,
            action=action,
            quantity=quantity,
            price=price,
            product=product,
            order_type=order_type,
            trigger_price=trigger_price,
            strategy=strategy,
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
            order_type=order_type,
            trigger_price=trigger_price,
            strategy=strategy,
        )

    order_id = str(body.get("order_id") or body.get("orderid") or "").strip()
    if ft_action == "cancel":
        return sandbox.cancel_order(order_id)

    if ft_action == "cancel-all":
        return sandbox.cancel_pending_orders()

    if ft_action == "modify":
        changes: dict[str, Any] = {}
        if "quantity" in body:
            changes["quantity"] = quantity
        if "price" in body:
            changes["price"] = price
        if "trigger_price" in body:
            changes["trigger_price"] = trigger_price
        if "order_type" in body or "pricetype" in body:
            changes["order_type"] = order_type
        return sandbox.modify_order(order_id, **changes)

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


def _subscribe_pending_practice_order(
    result: dict[str, Any],
    body: dict[str, Any],
) -> bool:
    """Subscribe one resting Practice order, returning whether it is executable."""
    if str(result.get("status", "")).upper() != "PENDING":
        return True
    recorder = current_app.config.get("TICK_RECORDER")
    if recorder is None:
        return False
    exchange = str(body.get("exchange") or "").strip().upper()
    symbol = str(body.get("symbol") or "").strip().upper()
    if not exchange or not symbol:
        return False
    try:
        recorder.add_symbols([{"exchange": exchange, "symbol": symbol}], mode="ltp")
        request_reconnect = getattr(recorder, "request_reconnect", None)
        if callable(request_reconnect):
            request_reconnect()
        return True
    except Exception as exc:  # noqa: BLE001 - caller cancels the stranded order
        logger.warning(
            "Practice tick subscription failed for %s:%s (%s)",
            exchange,
            symbol,
            type(exc).__name__,
        )
        return False


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


def _decode_routed_live_payload() -> tuple[dict[str, Any] | None, tuple[Any, int] | None]:
    """Validate common auth/live-unlock gates for selector-bound routed writes."""
    payload = _decode_request_payload()
    if not payload:
        return None, (jsonify({
            "status": "error",
            "message": "Authentication required — provide a valid JWT",
        }), 401)

    jwt_mode = str(payload.get("mode") or "").strip().lower()
    mismatch = _mode_header_mismatch_response(jwt_mode, route_label="Routed order request")
    if mismatch is not None:
        return None, mismatch

    if jwt_mode != _MODE_LIVE:
        return None, (jsonify({
            "status": "error",
            "message": (
                "The routed order path serves live mode only. Use "
                "/api/v1/orders/place for explore/practice."
            ),
        }), 400)

    if not _is_live_mode_unlocked():
        return None, (jsonify({
            "status": "error",
            "message": "Live mode not unlocked — verify PIN first",
        }), 403)

    return payload, None


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
    payload, error = _decode_routed_live_payload()
    if error is not None:
        return error

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


@orders_bp.route("/<broker>/modify", methods=["POST"])
@rate_limit("orders", user_rate=10, global_rate=100)
def modify_order_routed(broker: str) -> tuple[Any, int]:
    """Modify a LIVE order through the selector-bound broker router."""
    payload, error = _decode_routed_live_payload()
    if error is not None:
        return error

    body = request.get_json(silent=True) or {}
    return _dispatch_live_modify(body, payload, adapter_id=broker)


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


@orders_bp.route("/<broker>/cancel", methods=["POST"])
@rate_limit("orders", user_rate=10, global_rate=100)
def cancel_order_routed(broker: str) -> tuple[Any, int]:
    """Cancel a LIVE order through the selector-bound broker router."""
    payload, error = _decode_routed_live_payload()
    if error is not None:
        return error

    body = request.get_json(silent=True) or {}
    return _dispatch_live_cancel(body, payload, adapter_id=broker)


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


def _configured_execution_target() -> tuple[str, str]:
    """Return the router's configured execution default, or OpenAlgo/default."""
    router = current_app.config.get("BROKER_ROUTER")
    selector = str(getattr(router, "default_selector", None) or "").strip()
    if selector:
        try:
            from flinttrade_engine.request_context import parse_selector  # noqa: PLC0415

            return parse_selector(selector)
        except ValueError:
            logger.warning(
                "Ignoring malformed brokers.execution.default selector: %s",
                log_ref(selector, kind="selector"),
            )
    return "openalgo", "default"


def _gated_target(params: Any) -> tuple[str, str]:
    """Resolve the ``(adapter_id, account_id)`` target from a body or query mapping.

    Args:
        params: A mapping-like object (decoded JSON body or ``request.args``)
            carrying optional ``broker`` and ``account_id`` fields.

    Returns:
        ``(adapter_id, account_id)``. With no explicit target, the running
        ``brokers.execution.default`` selector wins; if no configured router is
        available this falls back to ``("openalgo", "default")``.
    """
    if not str(params.get("broker") or "").strip() and not str(params.get("account_id") or "").strip():
        return _configured_execution_target()
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

    jwt_mode = str(payload.get("mode") or "").strip().lower()
    mismatch = _mode_header_mismatch_response(jwt_mode, route_label="Extended gated route request")
    if mismatch is not None:
        return None, mismatch

    if jwt_mode != _MODE_LIVE:
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
    kill_switch_gated: bool = True,
    admission_lease: Any = None,
    exposure_orders: list[Any] | tuple[Any, ...] = (),
    exposure_positions: list[list[Any]] | tuple[list[Any], ...] = (),
    reservation_id_factory: Callable[[Any, int], str] | None = None,
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
        kill_switch_gated: Keep ``True`` for every ordinary operator write. A
            cancellation can remove a protective exit; only the dedicated
            emergency dispatcher carries intent that may bypass L5.

    Returns:
        A ``(flask.Response, http_status_code)`` tuple.
    """

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

    safe_ref = log_ref(ref or "none", kind="ref")
    if kill_switch_gated:
        blocked, unavailable = _live_kill_switch_block()
        if unavailable is not None:
            return unavailable
        if blocked is not None:
            logger.warning("Live %s blocked by kill switch | ref=%s: %s", verb, safe_ref, blocked.reason)
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
    safe_account = account_ref(account_id)

    canonical: dict[str, Any] = {"_op": verb, **fields}
    try:
        safety_ctx = gate_broker_write(verb, canonical, request_ctx, adapter_id, account_id=account_id)
        reservations = []
        if exposure_orders:
            if admission_lease is None or len(exposure_orders) != len(exposure_positions):
                raise SafetyBypassError("risk-increasing broker write lacks complete order admission state")
            reservations = [
                admission_lease.reserve(order, positions)
                for order, positions in zip(exposure_orders, exposure_positions, strict=True)
            ]
        result = _run_on_client_loop(
            router.execute_gated(
                request_ctx,
                verb=verb,
                payload=canonical,
                safety_ctx=safety_ctx,
                hint=RoutingHint(adapter_id=adapter_id, account_id=account_id),
            )
        )
        for index, reservation in enumerate(reservations):
            broker_order_id = reservation_id_factory(result, index) if reservation_id_factory else ""
            admission_lease.acknowledge(reservation, {"orderid": broker_order_id})
    except SafetyBypassError as exc:
        logger.warning("Live %s refused by safety gate | ref=%s: %s", verb, safe_ref, exc)
        return jsonify({"status": "error", "message": "Request refused"}), 403
    except AlgoTagLimitError as exc:
        # Algo-tag guard ceiling breach — a throttle refusal callers should
        # retry (429), never the generic 500 (audit fix); mirrors the place path.
        logger.warning("Live %s refused by algo-tag guard | ref=%s: %s", verb, safe_ref, exc)
        return jsonify({"status": "error", "message": "Request refused by rate guard"}), 429
    except (BrokerNotFoundError, KeyError) as exc:
        logger.warning(
            "Live %s — broker not connected | adapter=%s account=%s: %s",
            verb,
            adapter_id,
            safe_account,
            _redact_exc(exc, account_id),
        )
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
            verb, adapter_id, safe_account, _redact_exc(exc, account_id),
        )
        return jsonify({
            "status": "error",
            "message": f"This operation ({verb}) is not yet available for broker '{adapter_id}'.",
        }), 501
    except (BrokerError, ValueError) as exc:
        # The broker/adapter refused after the FlintTrade gate succeeded. Keep the
        # detailed exception in logs, but return the route-specific bounded message
        # so adapter tracebacks, paths, or tokens cannot reach HTTP callers.
        logger.warning(
            "Live %s rejected by broker/adapter | adapter=%s account=%s: %s",
            verb, adapter_id, safe_account, _redact_exc(exc, account_id),
        )
        return jsonify({"status": "error", "message": fail_message}), 502
    except Exception:
        logger.exception("Live %s dispatch failed | ref=%s adapter=%s", verb, safe_ref, adapter_id)
        return jsonify({"status": "error", "message": fail_message}), 500

    _audit_write_event(audit_event, adapter_id, account_id, request_ctx.actor_id, ref)
    logger.info("Live %s dispatched | ref=%s adapter=%s account=%s", verb, safe_ref, adapter_id, safe_account)
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
    safe_account = account_ref(account_id)

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
        rows = _run_on_client_loop(method(session))
    except SafetyBypassError as exc:
        logger.warning(
            "Broker read %s refused | adapter=%s account=%s: %s",
            read_verb, adapter_id, safe_account, _redact_exc(exc, account_id),
        )
        return jsonify({"status": "error", "message": "Request refused"}), 403
    except (BrokerNotFoundError, KeyError) as exc:
        logger.warning(
            "Broker read %s — not connected | adapter=%s account=%s: %s",
            read_verb,
            adapter_id,
            safe_account,
            _redact_exc(exc, account_id),
        )
        return jsonify({
            "status": "error",
            "message": (
                f"Broker '{adapter_id}' (account '{account_id}') is not connected. Add the "
                "selector to workspace.json brokers.registered and brokers.account_acls, then restart."
            ),
        }), 503
    except (NotImplementedError, UnsupportedCapabilityError) as exc:
        logger.warning(
            "Broker read %s — adapter capability not available | adapter=%s account=%s: %s",
            read_verb, adapter_id, safe_account, _redact_exc(exc, account_id),
        )
        return jsonify({
            "status": "error",
            "message": f"This listing ({read_verb}) is not yet available for broker '{adapter_id}'.",
        }), 501
    except Exception:
        logger.exception("Broker read %s failed | adapter=%s account=%s", read_verb, adapter_id, safe_account)
        return jsonify({"status": "error", "message": f"Failed to fetch {read_verb}"}), 500

    return jsonify({"status": "success", "data": rows}), 200


def _changes_from_body(body: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the required non-empty ``changes`` dict from a modify body, or ``None``."""
    changes = body.get("changes")
    if not isinstance(changes, dict) or not changes:
        return None
    return changes


def _forever_contract_error(
    values: dict[str, Any],
    adapter_id: str,
    *,
    modifying: bool = False,
) -> str | None:
    """Reject protective-leg fields that the selected GTT broker would ignore."""
    broker = adapter_id.lower()
    supplied = {key for key, value in values.items() if value is not None and value != ""}
    if broker == "upstox":
        dhan_only = {"price1", "trigger_price1", "quantity1"}
        if modifying:
            dhan_only.update({"order_flag", "leg_name"})
        ignored = sorted(supplied & dhan_only)
        if ignored:
            return (
                "Upstox GTT does not accept Dhan forever-order fields "
                f"{ignored}; use target_price and/or stop_loss_price rules."
            )
        if modifying:
            required = {
                "type",
                "quantity",
                "trigger_price",
                "entry_trigger_type",
                "stop_loss_price",
                "target_price",
                "stop_loss_trigger_type",
                "target_trigger_type",
                "stop_loss_trailing_gap",
            }
            missing = sorted(required - supplied)
            if missing:
                return f"Upstox GTT modify requires a complete replacement; missing fields {missing}."
    if broker == "dhan":
        upstox_only = {
            "type",
            "target_price",
            "stop_loss_price",
            "entry_trigger_type",
            "target_trigger_type",
            "stop_loss_trigger_type",
            "stop_loss_trailing_gap",
        }
        ignored = sorted(supplied & upstox_only)
        if ignored:
            return (
                "Dhan forever orders do not accept Upstox GTT rule fields "
                f"{ignored}; use the price1/trigger_price1/quantity1 OCO trio."
            )
        if modifying:
            required = {
                "order_flag",
                "leg_name",
                "quantity",
                "price",
                "trigger_price",
                "disclosed_quantity",
                "validity",
            }
            missing = sorted(required - supplied)
            if not ({"pricetype", "order_type"} & supplied):
                missing.append("pricetype")
            if missing:
                return f"Dhan forever modify requires a complete replacement; missing fields {sorted(missing)}."
    return None


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


def _check_legs_through_safety(
    legs: list[Any],
    adapter_id: str,
    *,
    account_id: str = "default",
    lease: Any = None,
) -> tuple[tuple[Any, int] | None, list[list[Any]]]:
    """Run the full SafetySystem (L1–L5) over each typed placement leg.

    Conditional-trigger PLACEMENT and MODIFY arm real orders the instant the
    condition fires, so — like :func:`multi_order_place` — every leg MUST clear
    the risk pipeline before the gate is minted (the route-level
    ``kill_switch_gated`` flag only runs L5). Without this, an over-limit leg
    (e.g. NFO qty 9999999) bypassed L1–L4. L2/L4 use the same complete,
    selector-scoped snapshot as the place path; unavailable local P&L fails closed.

    Args:
        legs: Typed :class:`~flinttrade_core.models.Order` legs (already coerced
            by :func:`_body_to_order`).
        adapter_id: Target broker adapter id (scopes the L2 exposure read).
        account_id: Target broker account id within the adapter.

    Returns:
        ``None`` when every leg passes; otherwise a ``(flask.Response,
        http_status)`` 403 carrying the first blocking layer's reason — ready to
        be returned from the route handler before any gate is minted.
    """
    try:
        safety = _require_live_safety()
    except Exception as exc:  # noqa: BLE001 - readiness failures are an admission refusal
        logger.error("Conditional-trigger safety runtime unavailable: %s", type(exc).__name__)
        return _safety_runtime_unavailable_response(), []
    if lease is None:
        with safety.order_admission(f"{adapter_id}:{account_id}") as active_lease:
            return _check_legs_through_safety(
                legs,
                adapter_id,
                account_id=account_id,
                lease=active_lease,
            )
    try:
        portfolio_state = _gather_safety_state(
            adapter_id,
            account_id=account_id,
            orders=legs,
            reservations=lease.reservations,
            include_order_margin=True,
        )
        lease.reconcile(getattr(portfolio_state, "reconciled_reservation_ids", ()))
    except Exception as exc:  # noqa: BLE001 - fail closed without leaking broker details
        logger.error(
            "Conditional-trigger safety state unavailable | adapter=%s: %s",
            adapter_id,
            type(exc).__name__,
        )
        return _safety_state_unavailable_response(), []
    exposure_positions: list[list[Any]] = []
    for index, leg in enumerate(legs):
        admission = portfolio_state.admission_for(index)
        exposure_positions.append(admission.positions)
        results = safety.check_order(
            leg,
            selector=f"{adapter_id}:{account_id}",
            positions=admission.positions,
            used_margin=admission.used_margin,
            total_balance=portfolio_state.total_balance,
            daily_pnl=portfolio_state.daily_pnl,
            starting_capital=portfolio_state.starting_capital,
            ltp=portfolio_state.ltp_for(leg),
            net_delta=admission.net_delta,
            net_vega=admission.net_vega,
        )
        blocked = next((r for r in results if not r.passed), None)
        if blocked is not None:
            logger.warning(
                "Conditional-trigger leg blocked by safety layer %s | symbol=%s: %s",
                blocked.layer, getattr(leg, "symbol", "?"), blocked.reason,
            )
            return (
                jsonify({
                    "status": "error",
                    "message": f"Order blocked by safety system [{blocked.layer}]: {blocked.reason}",
                }),
                403,
            ), []
    return None, exposure_positions


# --- Forever (GTT) orders — native Dhan/Upstox; gated router path ----------


@orders_bp.route("/forever", methods=["POST"])
@rate_limit("orders", user_rate=10, global_rate=100)
def forever_place() -> tuple[Any, int]:
    """Place a forever (GTT) order through the gated place path (live only).

    Builds a typed ``Order`` with ``variety="gtt"`` — including Dhan OCO fields
    or Upstox TARGET/STOPLOSS rules — and dispatches it through the SAME channel
    as a regular placement:
    SafetySystem L1–L5 → ``gate_order`` → ``BrokerRouter.place_order``. The
    variety and leg fields live on the Order, so the SafetyContext HMAC covers
    them.

    Request JSON: standard order fields plus ``trigger_price`` (required by the
    broker), broker-specific protective fields, and optional ``broker`` and
    ``account_id``. With no target fields, ``brokers.execution.default`` is used.
    """
    payload, err = _require_live_payload(require_unlock=True)
    if err is not None:
        return err
    body = request.get_json(silent=True) or {}
    adapter_id, account_id = _gated_target(body)
    contract_error = _forever_contract_error(body, adapter_id)
    if contract_error is not None:
        return jsonify({"status": "error", "message": contract_error}), 400
    return _dispatch_live_order(
        "forever-place", body, payload,
        adapter_id=adapter_id, account_id=account_id, variety="gtt",
    )


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
    contract_error = _forever_contract_error(changes, adapter_id, modifying=True)
    if contract_error is not None:
        return jsonify({"status": "error", "message": contract_error}), 400
    try:
        safety = _require_live_safety()
    except Exception as exc:  # noqa: BLE001 - readiness failures are admission refusals
        logger.error("Forever modify safety runtime unavailable: %s", type(exc).__name__)
        return _safety_runtime_unavailable_response()
    with safety.order_admission(f"{adapter_id}:{account_id}") as lease:
        admission_block, exposure_order, positions = _admit_modify_intent(
            order_id,
            changes,
            adapter_id,
            account_id=account_id,
            family="forever",
            lease=lease,
        )
        if admission_block is not None:
            return admission_block
        return _gated_verb_write(
            "modify_forever", {"order_id": order_id, "changes": changes}, payload,
            adapter_id=adapter_id, account_id=account_id,
            audit_event="FOREVER_MODIFIED", fail_message="Forever order modify failed",
            ref=order_id, kill_switch_gated=True,
            admission_lease=lease,
            exposure_orders=([exposure_order] if exposure_order is not None else []),
            exposure_positions=([positions] if exposure_order is not None else []),
            reservation_id_factory=lambda _result, _index: order_id,
        )


@orders_bp.route("/forever/<order_id>", methods=["DELETE"])
@rate_limit("orders", user_rate=10, global_rate=100)
def forever_cancel(order_id: str) -> tuple[Any, int]:
    """Cancel a resting forever (GTT) order — gated ``cancel_forever`` verb.

    Target via ``?broker=`` / ``?account_id=`` query parameters (a JSON body
    with the same fields also works). L5 blocks ordinary cancellation because
    the resting order may be a protective exit; retry the emergency sweep.
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
    try:
        safety = _require_live_safety()
    except Exception as exc:  # noqa: BLE001 - readiness failures are admission refusals
        logger.error("Super-order modify safety runtime unavailable: %s", type(exc).__name__)
        return _safety_runtime_unavailable_response()
    with safety.order_admission(f"{adapter_id}:{account_id}") as lease:
        admission_block, exposure_order, positions = _admit_modify_intent(
            order_id,
            changes,
            adapter_id,
            account_id=account_id,
            family="super",
            lease=lease,
        )
        if admission_block is not None:
            return admission_block
        return _gated_verb_write(
            "modify_super_order", {"order_id": order_id, "changes": changes}, payload,
            adapter_id=adapter_id, account_id=account_id,
            audit_event="SUPER_ORDER_MODIFIED", fail_message="Super order modify failed",
            ref=order_id, kill_switch_gated=True,
            admission_lease=lease,
            exposure_orders=([exposure_order] if exposure_order is not None else []),
            exposure_positions=([positions] if exposure_order is not None else []),
            reservation_id_factory=lambda _result, _index: order_id,
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
    except ValueError:
        return jsonify({"status": "error", "message": "Trigger validation failed"}), 400
    adapter_id, account_id = _gated_target(body)
    try:
        safety = _require_live_safety()
    except Exception as exc:  # noqa: BLE001 - readiness failures are admission refusals
        logger.error("Conditional-trigger safety runtime unavailable: %s", type(exc).__name__)
        return _safety_runtime_unavailable_response()
    with safety.order_admission(f"{adapter_id}:{account_id}") as lease:
        blocked, exposure_positions = _check_legs_through_safety(
            legs,
            adapter_id,
            account_id=account_id,
            lease=lease,
        )
        if blocked is not None:
            return blocked
        return _gated_verb_write(
            "place_conditional_trigger", {"condition": condition, "orders": legs}, payload,
            adapter_id=adapter_id, account_id=account_id,
            audit_event="TRIGGER_PLACED", fail_message="Conditional trigger placement failed",
            kill_switch_gated=True,
            admission_lease=lease,
            exposure_orders=legs,
            exposure_positions=exposure_positions,
            reservation_id_factory=lambda result, index: f"{result}:{index}",
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
    except ValueError:
        return jsonify({"status": "error", "message": "Trigger validation failed"}), 400
    adapter_id, account_id = _gated_target(body)
    try:
        safety = _require_live_safety()
    except Exception as exc:  # noqa: BLE001 - readiness failures are admission refusals
        logger.error("Conditional-trigger modify safety runtime unavailable: %s", type(exc).__name__)
        return _safety_runtime_unavailable_response()
    with safety.order_admission(f"{adapter_id}:{account_id}") as lease:
        blocked, exposure_positions = _check_legs_through_safety(
            legs,
            adapter_id,
            account_id=account_id,
            lease=lease,
        )
        if blocked is not None:
            return blocked
        return _gated_verb_write(
            "modify_conditional_trigger",
            {"alert_id": alert_id, "condition": condition, "orders": legs},
            payload,
            adapter_id=adapter_id, account_id=account_id,
            audit_event="TRIGGER_MODIFIED", fail_message="Conditional trigger modify failed",
            ref=alert_id, kill_switch_gated=True,
            admission_lease=lease,
            exposure_orders=legs,
            exposure_positions=exposure_positions,
            reservation_id_factory=lambda _result, index: f"{alert_id}:{index}",
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
    """Place multiple orders sequentially through individually gated writes.

    Request JSON: ``orders`` (non-empty list of order objects), optional
    ``broker`` / ``account_id``. EVERY leg is coerced to a typed ``Order`` and
    admitted through the full SafetySystem (L1-L5) against the state and
    unresolved exposure left by earlier legs. Processing stops at the first
    refusal or broker failure; ``placed_order_ids`` reports any prior success.
    """
    from pydantic import ValidationError  # noqa: PLC0415

    from flinttrade_core.exceptions import SafetyBypassError, UnsupportedCapabilityError  # noqa: PLC0415
    from flinttrade_engine.request_context import RequestContext  # noqa: PLC0415
    from flinttrade_gateway.exceptions import BrokerNotFoundError  # noqa: PLC0415

    payload, err = _require_live_payload(require_unlock=True)
    if err is not None:
        return err
    body = request.get_json(silent=True) or {}
    raw_orders = body.get("orders")
    if not isinstance(raw_orders, list) or not raw_orders:
        return jsonify({"status": "error", "message": "'orders' must be a non-empty list of order objects"}), 400
    adapter_id, account_id = _gated_target(body)

    try:
        safety = _require_live_safety()
    except Exception as exc:  # noqa: BLE001 - readiness failures are an admission refusal
        logger.error("Multi-order safety runtime unavailable: %s", type(exc).__name__)
        return _safety_runtime_unavailable_response()
    legs: list[Any] = []
    try:
        for index, leg in enumerate(raw_orders):
            if not isinstance(leg, dict):
                raise ValueError(f"orders[{index}] must be an object")
            legs.append(_body_to_order(leg))
    except (ValueError, ValidationError):
        return jsonify({"status": "error", "message": "Order validation failed"}), 400
    router = current_app.config.get("BROKER_ROUTER")
    if router is None:
        return jsonify({"status": "error", "message": "Order routing unavailable"}), 503
    request_ctx = RequestContext(
        jti=str(payload.get("jti") or ""),
        actor_type="human",
        actor_id=str(payload.get("sub") or payload.get("actor_id") or "unknown"),
        mode=_MODE_LIVE,
        selector=f"{adapter_id}:{account_id}",
    )
    order_ids: list[str] = []
    for index, (typed, raw_leg) in enumerate(zip(legs, raw_orders, strict=True)):
        try:
            admitted, outcome = _admit_and_route_live_order(
                safety=safety,
                router=router,
                typed_order=typed,
                request_ctx=request_ctx,
                adapter_id=adapter_id,
                account_id=account_id,
                ft_action=f"multi-order-{index}",
                body=raw_leg,
            )
        except SafetyBypassError:
            return jsonify({
                "status": "error",
                "message": "Multi-order placement was refused; no later leg was sent.",
                "placed_order_ids": order_ids,
            }), 403
        except (BrokerNotFoundError, KeyError):
            return jsonify({
                "status": "error",
                "message": "Broker is not connected; no later leg was sent.",
                "placed_order_ids": order_ids,
            }), 503
        except (NotImplementedError, UnsupportedCapabilityError):
            return jsonify({
                "status": "error",
                "message": "Multi-order placement is not available for this broker; no later leg was sent.",
                "placed_order_ids": order_ids,
            }), 501
        except Exception:
            logger.exception("Sequential multi-order leg failed | adapter=%s index=%s", adapter_id, index)
            return jsonify({
                "status": "error",
                "message": "Multi-order placement failed; no later leg was sent.",
                "placed_order_ids": order_ids,
            }), 502
        if not admitted:
            return outcome
        order_ids.append(str(outcome))

    _audit_write_event("MULTI_ORDER_PLACED", adapter_id, account_id, request_ctx.actor_id, "")
    return jsonify({"status": "success", "data": {"order_ids": order_ids}}), 200


@orders_bp.route("/smart/<order_id>", methods=["DELETE"])
@rate_limit("orders", user_rate=10, global_rate=100)
def smart_order_cancel(order_id: str) -> tuple[Any, int]:
    """Cancel a smart order — gated ``cancel_smart_order`` verb (IndMoney-native).

    Optional ``?segment=`` narrows the cancel (e.g. ``DERIVATIVE``); it travels
    inside the signed payload. L5 blocks ordinary cancellation because the
    smart order may be a protective exit.
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


# ===========================================================================
# Advanced orders — basket / split / options-strategy
#
# Folded in from the engine ``order_bp`` on 2026-07-09 so one blueprint owns
# ``/api/v1/orders/*``. The executors are read from ``app.config`` and injected
# in ``create_flask_app`` bound to the gated ``build_gated_leg_dispatchers``
# place_leg (SafetySystem L1–L5 → ``gate_order`` one-shot HMAC ``SafetyContext``
# → ``BrokerRouter``), so every leg / chunk traverses the one-shot gate. Both
# executors are optional; the endpoint returns HTTP 503 when its executor is
# absent (fail-closed).
# ===========================================================================


def _require_live_unlocked(view: Callable[..., Any]) -> Callable[..., Any]:
    """Apply the engine live-unlock mode guard, deferring the engine import.

    The guard lives in :mod:`flinttrade_engine.mode_guard`, but this module
    keeps every engine import deferred (see the deferred imports throughout) to
    avoid the core↔engine module-load cycle. The wrapped guard is resolved and
    cached on the first request, never at import time.
    """
    import functools

    cached: list[Callable[..., Any]] = []

    @functools.wraps(view)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not cached:
            from flinttrade_engine.mode_guard import require_live_unlocked  # noqa: PLC0415

            cached.append(require_live_unlocked(view))
        return cached[0](*args, **kwargs)

    return wrapper


def _get_basket_executor() -> Any:
    return current_app.config.get("BASKET_EXECUTOR")


def _get_split_executor() -> Any:
    return current_app.config.get("SPLIT_EXECUTOR")


def _basket_required() -> tuple[Any, Any | None]:
    ex = _get_basket_executor()
    if ex is None:
        return None, (
            jsonify({"status": "error", "message": "Basket executor not configured"}),
            503,
        )
    return ex, None


def _split_required() -> tuple[Any, Any | None]:
    ex = _get_split_executor()
    if ex is None:
        return None, (
            jsonify({"status": "error", "message": "Split executor not configured"}),
            503,
        )
    return ex, None


_ADVANCED_STRATEGY_NAMES = {
    "short_straddle",
    "long_strangle",
    "iron_condor",
    "iron_butterfly",
    "bull_call_spread",
    "bear_put_spread",
}


@orders_bp.route("/basket", methods=["POST"])
@_require_live_unlocked
@rate_limit("orders", user_rate=10, global_rate=100)
def place_basket() -> tuple[Any, int]:
    """Execute a basket of multi-leg orders atomically.

    Every leg dispatches through the gated ``build_gated_leg_dispatchers``
    place_leg (SafetySystem L1–L5 → ``gate_order`` → ``BrokerRouter``).

    Returns:
        201 on full success, 422 on partial/total failure, 400 on bad input,
        503 when the basket executor is not configured.
    """
    executor, err = _basket_required()
    if err:
        return err

    body: dict[str, Any] = request.get_json(silent=True) or {}
    legs_raw = body.get("legs")
    if not legs_raw or not isinstance(legs_raw, list):
        return jsonify({"status": "error", "message": "'legs' array is required"}), 400

    strategy: str = str(body.get("strategy", "basket"))

    from flinttrade_engine.basket_orders import BasketLeg, _leg_to_order  # noqa: PLC0415
    from flinttrade_engine.bracket_routes import _request_principal  # noqa: PLC0415

    legs: list[Any] = []
    for i, raw in enumerate(legs_raw):
        if not isinstance(raw, dict):
            return jsonify({"status": "error", "message": f"Leg {i} must be an object"}), 400
        try:
            legs.append(
                BasketLeg(
                    symbol=str(raw.get("symbol", "")),
                    exchange=str(raw.get("exchange", "NFO")),
                    action=str(raw.get("action", "BUY")).upper(),
                    quantity=int(raw.get("quantity", 0)),
                    order_type=str(raw.get("order_type", "MARKET")).upper(),
                    price=float(raw["price"]) if "price" in raw else None,
                    trigger_price=float(raw["trigger_price"]) if "trigger_price" in raw else None,
                    product=str(raw.get("product", "MIS")).upper(),
                )
            )
        except (TypeError, ValueError) as exc:
            logger.warning("Basket leg %s parse error: %s", i, exc)
            return jsonify({"status": "error", "message": f"Leg {i} parse error"}), 400

    principal = _request_principal(body)
    try:
        typed_legs = [_leg_to_order(leg, strategy) for leg in legs]
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Basket validation failed"}), 400
    blocked, _exposure_positions = _check_legs_through_safety(
        typed_legs,
        principal.adapter_id,
        account_id=principal.account_id,
    )
    if blocked is not None:
        return blocked

    result = executor.execute(legs, principal, strategy=strategy)

    response_data: dict[str, Any] = {
        "status": "success" if result.success else "error",
        "strategy": result.strategy,
        "timestamp": result.timestamp,
        "placed_count": result.placed_count,
        "failed_count": result.failed_count,
        "rolled_back": result.rolled_back,
        "order_ids": result.order_ids,
        "legs": [
            {
                "leg_index": r.leg_index,
                "symbol": r.symbol,
                "action": r.action,
                "quantity": r.quantity,
                "success": r.success,
                "order_id": r.order_id,
                "error": r.error,
                "rolled_back": r.rolled_back,
                "rollback_order_id": r.rollback_order_id,
            }
            for r in result.legs
        ],
    }
    if not result.success:
        response_data["message"] = result.error
        response_data["failed_leg_index"] = result.failed_leg_index

    return jsonify(response_data), (201 if result.success else 422)


@orders_bp.route("/split", methods=["POST"])
@_require_live_unlocked
@rate_limit("orders", user_rate=10, global_rate=100)
def place_split() -> tuple[Any, int]:
    """Break a large order into smaller chunks and place them with a delay.

    Every chunk dispatches through the gated place_leg (SafetySystem →
    ``gate_order`` → ``BrokerRouter``).

    Returns:
        201 on full success, 422 on partial/total failure, 400 on bad input,
        503 when the split executor is not configured.
    """
    executor, err = _split_required()
    if err:
        return err

    body: dict[str, Any] = request.get_json(silent=True) or {}

    required_fields = ["symbol", "exchange", "action", "total_qty", "chunk_size"]
    for field_name in required_fields:
        if field_name not in body:
            return jsonify({"status": "error", "message": f"'{field_name}' is required"}), 400

    try:
        symbol: str = str(body["symbol"])
        exchange: str = str(body["exchange"])
        action: str = str(body["action"]).upper()
        total_qty: int = int(body["total_qty"])
        chunk_size: int = int(body["chunk_size"])
        delay_seconds: float = float(body.get("delay_seconds", 1.0))
        order_type: str = str(body.get("order_type", "MARKET")).upper()
        price: float = float(body.get("price", 0.0))
        trigger_price: float = float(body.get("trigger_price", 0.0))
        product: str = str(body.get("product", "MIS")).upper()
        strategy: str = str(body.get("strategy", "split"))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Parameter parse error"}), 400

    from flinttrade_engine.bracket_routes import _request_principal  # noqa: PLC0415
    from flinttrade_engine.split_orders import (  # noqa: PLC0415
        SplitValidationError,
        _build_chunk_order,
        _validate_split_params,
    )

    try:
        _validate_split_params(
            symbol,
            exchange,
            total_qty,
            chunk_size,
            action,
            order_type,
            price,
            trigger_price,
        )
    except SplitValidationError:
        return jsonify({"status": "error", "message": "Split validation failed"}), 400

    chunk_quantities = [chunk_size] * (total_qty // chunk_size)
    if remainder := total_qty % chunk_size:
        chunk_quantities.append(remainder)
    typed_chunks = [
        _build_chunk_order(
            symbol=symbol,
            exchange=exchange,
            action=action,
            quantity=quantity,
            order_type=order_type,
            price=price,
            trigger_price=trigger_price,
            product=product,
            strategy=strategy,
        )
        for quantity in chunk_quantities
    ]
    principal = _request_principal(body)
    blocked, _exposure_positions = _check_legs_through_safety(
        typed_chunks,
        principal.adapter_id,
        account_id=principal.account_id,
    )
    if blocked is not None:
        return blocked

    result = executor.execute_split(
        symbol=symbol,
        exchange=exchange,
        total_quantity=total_qty,
        chunk_size=chunk_size,
        action=action,  # type: ignore[arg-type]
        principal=principal,
        delay_seconds=delay_seconds,
        order_type=order_type,
        price=price,
        trigger_price=trigger_price,
        product=product,
        strategy=strategy,
    )

    response_data: dict[str, Any] = {
        "status": "success" if result.success else "error",
        "symbol": result.symbol,
        "exchange": result.exchange,
        "action": result.action,
        "total_quantity": result.total_quantity,
        "chunk_size": result.chunk_size,
        "placed_quantity": result.placed_quantity,
        "placed_count": result.placed_count,
        "failed_count": result.failed_count,
        "strategy": result.strategy,
        "timestamp": result.timestamp,
        "order_ids": result.order_ids,
        "chunks": [
            {
                "chunk_index": c.chunk_index,
                "quantity": c.quantity,
                "success": c.success,
                "order_id": c.order_id,
                "error": c.error,
            }
            for c in result.chunks
        ],
    }
    if not result.success:
        response_data["message"] = result.error

    return jsonify(response_data), (201 if result.success else 422)


@orders_bp.route("/options-strategy", methods=["POST"])
@_require_live_unlocked
@rate_limit("smart_orders", user_rate=2, global_rate=20)
def place_options_strategy() -> tuple[Any, int]:
    """Build and execute a named options strategy through the gated basket path.

    Supported ``strategy_name``: short_straddle, long_strangle, iron_condor,
    iron_butterfly, bull_call_spread, bear_put_spread.

    Returns:
        201 on full success, 422 on execution failure, 400 on bad input, 503
        when the basket executor is not configured.
    """
    executor, err = _basket_required()
    if err:
        return err

    body: dict[str, Any] = request.get_json(silent=True) or {}

    strategy_name: str = str(body.get("strategy_name", "")).lower()
    if strategy_name not in _ADVANCED_STRATEGY_NAMES:
        return jsonify(
            {
                "status": "error",
                "message": (
                    f"Unknown strategy_name '{strategy_name}'. "
                    f"Must be one of: {sorted(_ADVANCED_STRATEGY_NAMES)}"
                ),
            }
        ), 400

    underlying: str = str(body.get("underlying", ""))
    expiry: str = str(body.get("expiry", ""))
    if not underlying:
        return jsonify({"status": "error", "message": "'underlying' is required"}), 400
    if not expiry:
        return jsonify({"status": "error", "message": "'expiry' is required"}), 400

    try:
        lots: int = int(body.get("lots", 1))
        lot_size: int = int(body.get("lot_size", 50))
        exchange: str = str(body.get("exchange", "NFO"))
        product: str = str(body.get("product", "NRML"))
        basket_strategy: str = str(body.get("strategy", strategy_name))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Parameter parse error"}), 400

    from flinttrade_engine.basket_orders import _leg_to_order  # noqa: PLC0415
    from flinttrade_engine.bracket_routes import _request_principal  # noqa: PLC0415
    from flinttrade_engine.options_multi_order import OptionsStrategyBuilder  # noqa: PLC0415

    try:
        legs = _build_strategy_legs(
            builder=OptionsStrategyBuilder,
            strategy_name=strategy_name,
            underlying=underlying,
            expiry=expiry,
            body=body,
            lots=lots,
            lot_size=lot_size,
            exchange=exchange,
            product=product,
        )
    except (KeyError, ValueError, TypeError):
        return jsonify({"status": "error", "message": "Strategy build error"}), 400

    principal = _request_principal(body)
    try:
        typed_legs = [_leg_to_order(leg, basket_strategy) for leg in legs]
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Strategy validation failed"}), 400
    blocked, _exposure_positions = _check_legs_through_safety(
        typed_legs,
        principal.adapter_id,
        account_id=principal.account_id,
    )
    if blocked is not None:
        return blocked

    result = executor.execute(legs, principal, strategy=basket_strategy)

    response_data: dict[str, Any] = {
        "status": "success" if result.success else "error",
        "strategy_name": strategy_name,
        "strategy": result.strategy,
        "underlying": underlying,
        "expiry": expiry,
        "lots": lots,
        "timestamp": result.timestamp,
        "placed_count": result.placed_count,
        "failed_count": result.failed_count,
        "rolled_back": result.rolled_back,
        "order_ids": result.order_ids,
        "legs": [
            {
                "leg_index": r.leg_index,
                "symbol": r.symbol,
                "action": r.action,
                "quantity": r.quantity,
                "success": r.success,
                "order_id": r.order_id,
                "error": r.error,
            }
            for r in result.legs
        ],
    }
    if not result.success:
        response_data["message"] = result.error

    return jsonify(response_data), (201 if result.success else 422)


def _build_strategy_legs(
    builder: type,
    strategy_name: str,
    underlying: str,
    expiry: str,
    body: dict[str, Any],
    lots: int,
    lot_size: int,
    exchange: str,
    product: str,
) -> list:
    """Dispatch to the correct :class:`OptionsStrategyBuilder` factory method.

    Raises:
        KeyError: When a required strategy-specific parameter is missing.
        ValueError: When parameter values are invalid.
    """
    kwargs = {
        "underlying": underlying,
        "expiry": expiry,
        "lots": lots,
        "lot_size": lot_size,
        "exchange": exchange,
        "product": product,
    }

    if strategy_name == "short_straddle":
        return builder.short_straddle(strike=float(body["strike"]), **kwargs)

    if strategy_name == "long_strangle":
        return builder.long_strangle(
            call_strike=float(body["call_strike"]),
            put_strike=float(body["put_strike"]),
            **kwargs,
        )

    if strategy_name == "iron_condor":
        return builder.iron_condor(
            put_short=float(body["put_short"]),
            put_long=float(body["put_long"]),
            call_short=float(body["call_short"]),
            call_long=float(body["call_long"]),
            **kwargs,
        )

    if strategy_name == "iron_butterfly":
        return builder.iron_butterfly(
            atm=float(body["atm"]),
            wing=float(body["wing"]),
            **kwargs,
        )

    if strategy_name == "bull_call_spread":
        return builder.bull_call_spread(
            long_strike=float(body["long_strike"]),
            short_strike=float(body["short_strike"]),
            **kwargs,
        )

    if strategy_name == "bear_put_spread":
        return builder.bear_put_spread(
            long_strike=float(body["long_strike"]),
            short_strike=float(body["short_strike"]),
            **kwargs,
        )

    raise ValueError(f"Unhandled strategy_name: {strategy_name}")  # pragma: no cover
