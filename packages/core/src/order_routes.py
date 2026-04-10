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
from typing import Any

import httpx
import jwt
from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger("flinttrade.order_routes")

orders_bp = Blueprint("orders", __name__, url_prefix="/v1/orders")

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
    from packages.core.src.auth_routes import decode_token  # noqa: PLC0415

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
    from packages.core.src.auth_routes import decode_token  # noqa: PLC0415

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
    # Live mode — verify PIN-unlocked JWT before forwarding to OpenAlgo
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

    logger.info(
        "Live order | action=%s symbol=%s exchange=%s qty=%s",
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
