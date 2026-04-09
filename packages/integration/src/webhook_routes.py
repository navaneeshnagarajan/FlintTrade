"""Flask Blueprint for webhook receiver endpoints.

Registers under ``/ft-api/v1/webhook/``:

- ``POST /ft-api/v1/webhook/<source>`` — receive, verify, parse, and
  dispatch a webhook from ``tradingview``, ``chartink``, or ``custom``.
- ``GET  /ft-api/v1/webhook/log`` — return recent webhook history.

Authentication: HMAC-SHA256 via ``X-Signature: sha256=<hex>`` header.
Rate limiting: 60 requests/minute per :class:`WebhookConfig` default.

The Blueprint exposes ``init_webhook_routes(receiver)`` for injecting a
pre-configured :class:`WebhookReceiver` instance (useful for testing and
for the main app factory).

Example (in app factory)::

    from packages.integration.src.webhook_receiver import (
        WebhookConfig, WebhookReceiver,
    )
    from packages.integration.src.webhook_routes import (
        init_webhook_routes, webhook_bp,
    )

    receiver = WebhookReceiver(WebhookConfig(secret=os.environ["WEBHOOK_SECRET"]))
    init_webhook_routes(receiver)
    app.register_blueprint(webhook_bp)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from flask import Blueprint, Response, jsonify, request

try:
    from .webhook_receiver import WebhookConfig, WebhookPayload, WebhookReceiver
except ImportError:
    from webhook_receiver import WebhookConfig, WebhookPayload, WebhookReceiver  # type: ignore[no-redef]

logger = logging.getLogger("flinttrade.integration.webhook_routes")

webhook_bp = Blueprint(
    "webhook_receiver",
    __name__,
    url_prefix="/ft-api/v1/webhook",
)

# Module-level receiver singleton (injected via init_webhook_routes or lazily created)
_receiver: WebhookReceiver | None = None


def init_webhook_routes(receiver: WebhookReceiver) -> None:
    """Inject a :class:`WebhookReceiver` instance into the Blueprint.

    Args:
        receiver: Pre-configured :class:`WebhookReceiver` to use for all
            incoming webhook requests.
    """
    global _receiver  # noqa: PLW0603
    _receiver = receiver
    logger.info("WebhookReceiver injected into webhook_routes")


def _get_receiver() -> WebhookReceiver:
    """Return the module-level receiver singleton, creating a default one if needed.

    Returns:
        :class:`WebhookReceiver` instance.
    """
    global _receiver  # noqa: PLW0603
    if _receiver is None:
        _receiver = WebhookReceiver(WebhookConfig())
    return _receiver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_request_body() -> tuple[bytes, dict[str, Any] | None]:
    """Read the raw request body and attempt JSON decoding.

    Returns:
        Tuple of (raw_bytes, parsed_dict_or_None).
    """
    raw: bytes = request.get_data()
    try:
        parsed: dict[str, Any] | None = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        parsed = None
    return raw, parsed


def _run_dispatch(receiver: WebhookReceiver, payload: WebhookPayload) -> dict[str, Any]:
    """Execute the async ``dispatch`` coroutine in a synchronous context.

    Flask is synchronous; this helper runs the coroutine in a new event loop
    or in the running loop if one is present.

    Args:
        receiver: :class:`WebhookReceiver` instance.
        payload: Parsed :class:`WebhookPayload`.

    Returns:
        Dispatch result dict.
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Running inside an existing async context (e.g. ASGI wrapper)
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, receiver.dispatch(payload))
                return future.result(timeout=10)
        else:
            return loop.run_until_complete(receiver.dispatch(payload))
    except RuntimeError:
        return asyncio.run(receiver.dispatch(payload))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


_VALID_SOURCES = frozenset({"tradingview", "chartink", "custom"})


@webhook_bp.route("/<source>", methods=["POST"])
def receive_webhook(source: str) -> tuple[Response, int]:
    """Receive a webhook from an external source, verify, parse, and dispatch.

    Path parameters:
        source: One of ``tradingview``, ``chartink``, ``custom``.

    Headers (optional):
        X-Signature: ``sha256=<hex>`` HMAC-SHA256 signature of the raw body.

    Request body:
        JSON payload whose structure depends on the source.

    Returns:
        JSON ``{"status": "...", "data": {...}}`` or error response.
    """
    source = source.lower()
    receiver = _get_receiver()

    # Validate source
    if source not in _VALID_SOURCES and source not in receiver._config.allowed_sources:
        return jsonify({
            "status": "error",
            "message": f"Unknown source '{source}'. Allowed: {sorted(_VALID_SOURCES)}",
        }), 404

    # Rate limiting
    if not receiver.check_rate_limit():
        logger.warning("Webhook rate limit exceeded for source=%s", source)
        return jsonify({
            "status": "error",
            "message": "Rate limit exceeded",
            "remaining": 0,
        }), 429

    # Read body
    raw, body_dict = _parse_request_body()
    if body_dict is None or not isinstance(body_dict, dict):
        return jsonify({
            "status": "error",
            "message": "Request body must be valid JSON object",
        }), 400

    # Signature verification
    sig_header = request.headers.get("X-Signature", "")
    if not receiver.verify_signature(raw, sig_header):
        logger.warning("Signature verification failed for source=%s", source)
        return jsonify({"status": "error", "message": "Signature verification failed"}), 401

    # Parse
    try:
        if source == "tradingview":
            payload = receiver.parse_tradingview(body_dict)
        elif source == "chartink":
            payload = receiver.parse_chartink(body_dict)
        else:
            payload = receiver.parse_custom(body_dict)
    except Exception as exc:
        logger.warning("Webhook parse error for source=%s: %s", source, exc)
        return jsonify({"status": "error", "message": f"Parse error: {exc}"}), 422

    # Dispatch
    try:
        result = _run_dispatch(receiver, payload)
    except Exception as exc:
        logger.exception("Webhook dispatch error for source=%s", source)
        return jsonify({"status": "error", "message": f"Dispatch error: {exc}"}), 500

    logger.info(
        "Webhook dispatched: source=%s action=%s symbol=%s status=%s",
        source, payload.action, payload.symbol, result.get("status"),
    )
    return jsonify({"status": "success", "data": result}), 200


@webhook_bp.route("/log", methods=["GET"])
def get_webhook_log() -> tuple[Response, int]:
    """Return recent webhook history.

    Query parameters:
        limit (int, optional): Maximum entries to return (default 50, max 500).

    Returns:
        JSON ``{"status": "success", "data": {"entries": [...], "count": N}}``.
    """
    receiver = _get_receiver()

    try:
        limit = int(request.args.get("limit", 50))
        limit = max(1, min(limit, 500))
    except (ValueError, TypeError):
        limit = 50

    entries = receiver.recent_log(limit=limit)
    return jsonify({
        "status": "success",
        "data": {
            "entries": entries,
            "count": len(entries),
            "rate_limit_remaining": receiver.rate_limit_remaining,
        },
    }), 200
