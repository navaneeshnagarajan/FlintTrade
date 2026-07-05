"""Flask Blueprint for webhook receiver endpoints.

External URLs (frontend/TradingView/ChartInk call these via /ft-api/v1/webhook/*;
the WSGI prefix stripper in app.py rewrites to /v1/webhook/* before Flask dispatch):

- ``POST /ft-api/v1/webhook/<source>`` — receive, verify, parse, and
  dispatch a webhook from ``tradingview``, ``chartink``, or ``custom``.
- ``POST /ft-api/v1/webhook/<source>/<id>`` — named endpoint form used by the
  Flows panel registry; handled by the same receiver path.
- ``GET  /ft-api/v1/webhook/log`` — return recent webhook history.

Blueprint registered at ``/v1/webhook`` (post-strip form).

Authentication: HMAC-SHA256 via ``X-Signature: sha256=<hex>`` header.
Rate limiting: 60 requests/minute per :class:`WebhookConfig` default.

The Blueprint exposes ``init_webhook_routes(receiver, secret_store=...)`` for
injecting a pre-configured :class:`WebhookReceiver` plus the optional encrypted
per-webhook secret/replay store used by named endpoints.

Example (in app factory)::

    from .webhook_receiver import (
        WebhookConfig, WebhookReceiver,
    )
    from .webhook_routes import (
        init_webhook_routes, webhook_bp,
    )

    receiver = WebhookReceiver(WebhookConfig(secret=os.environ["WEBHOOK_SECRET"]))
    init_webhook_routes(receiver)
    app.register_blueprint(webhook_bp)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from flask import Blueprint, Response, jsonify, request

try:
    from .webhook_receiver import WebhookConfig, WebhookPayload, WebhookReceiver
    from .webhook_replay import REASON_REPLAY, REASON_STALE
    from .webhook_secret_store import WebhookSecretStore
except ImportError:
    from webhook_receiver import WebhookConfig, WebhookPayload, WebhookReceiver  # type: ignore[no-redef]
    from webhook_replay import REASON_REPLAY, REASON_STALE  # type: ignore[no-redef]
    from webhook_secret_store import WebhookSecretStore  # type: ignore[no-redef]

logger = logging.getLogger("flinttrade.integration.webhook_routes")

webhook_bp = Blueprint(
    "webhook_receiver",
    __name__,
    url_prefix="/v1/webhook",
)

# Module-level receiver singleton (injected via init_webhook_routes or lazily created)
_receiver: WebhookReceiver | None = None
_secret_store: WebhookSecretStore | None = None
_endpoint_status_provider: Callable[[str], bool | None] | None = None


def init_webhook_routes(
    receiver: WebhookReceiver,
    *,
    secret_store: WebhookSecretStore | None = None,
    endpoint_status_provider: Callable[[str], bool | None] | None = None,
) -> None:
    """Inject a receiver and optional per-webhook secret store.

    Args:
        receiver: Pre-configured :class:`WebhookReceiver` to use for all
            incoming webhook requests.
        secret_store: Encrypted store for named webhook signing secrets and
            replay nonces. When omitted, routes keep the receiver's legacy
            global-secret behaviour.
        endpoint_status_provider: Optional ``path -> enabled`` callable backed
            by the mounted endpoint registry. Return ``False`` to block a known
            disabled endpoint, ``True`` for a known enabled endpoint, and
            ``None`` when the path is not registry-managed.
    """
    global _receiver, _secret_store, _endpoint_status_provider  # noqa: PLW0603
    _receiver = receiver
    _secret_store = secret_store
    _endpoint_status_provider = endpoint_status_provider
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


def _mounted_webhook_path(source: str, webhook_id: str | None) -> str | None:
    if not webhook_id:
        return None
    return f"/v1/webhook/{source}/{'/'.join(part for part in webhook_id.split('/') if part)}"


def _registered_endpoint_enabled(path: str) -> bool | None:
    """Return the registry-backed enabled state for a mounted named endpoint."""
    if _endpoint_status_provider is None:
        return None
    return _endpoint_status_provider(path)


def _parse_replay_timestamp(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        pass
    try:
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def _extract_replay_fields(body: dict[str, Any]) -> tuple[str, float] | None:
    nonce = (
        request.headers.get("X-Webhook-Nonce")
        or request.headers.get("X-Nonce")
        or body.get("nonce")
        or body.get("webhook_nonce")
    )
    timestamp = (
        request.headers.get("X-Webhook-Timestamp")
        or request.headers.get("X-Timestamp")
        or body.get("timestamp")
        or body.get("webhook_timestamp")
    )
    nonce_text = str(nonce or "").strip()
    payload_ts = _parse_replay_timestamp(timestamp)
    if not nonce_text or payload_ts is None:
        return None
    return nonce_text, payload_ts


def _source_ip_hash() -> str | None:
    if not request.remote_addr:
        return None
    return hashlib.sha256(request.remote_addr.encode("utf-8")).hexdigest()


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
@webhook_bp.route("/<source>/<path:webhook_id>", methods=["POST"])
def receive_webhook(source: str, webhook_id: str | None = None) -> tuple[Response, int]:
    """Receive a webhook from an external source, verify, parse, and dispatch.

    Path parameters:
        source: One of ``tradingview``, ``chartink``, ``custom``.
        webhook_id: Optional named endpoint slug from the UI registry.

    Headers (optional):
        X-Signature: ``sha256=<hex>`` HMAC-SHA256 signature of the raw body.

    Request body:
        JSON payload whose structure depends on the source.

    Returns:
        JSON ``{"status": "...", "data": {...}}`` or error response.
    """
    source = source.lower()
    receiver = _get_receiver()
    if webhook_id:
        logger.debug("Named webhook endpoint matched: source=%s id=%s", source, webhook_id)

    # Validate source
    if source not in _VALID_SOURCES and source not in receiver._config.allowed_sources:
        return jsonify({
            "status": "error",
            "message": f"Unknown source '{source}'. Allowed: {sorted(_VALID_SOURCES)}",
        }), 404
    mounted_path = _mounted_webhook_path(source, webhook_id)
    if mounted_path:
        try:
            enabled = _registered_endpoint_enabled(mounted_path)
        except Exception:
            logger.exception("Webhook endpoint registry lookup failed for source=%s", source)
            return jsonify({"status": "error", "message": "Webhook endpoint registry unavailable"}), 503
        if enabled is False:
            return jsonify({"status": "error", "message": "Webhook endpoint disabled"}), 503

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
    signing_secret: str | None = None
    if mounted_path and _secret_store is not None:
        try:
            signing_secret = _secret_store.get_secret(mounted_path)
        except Exception:
            logger.exception("Webhook secret lookup failed for source=%s", source)
            return jsonify({"status": "error", "message": "Webhook secret store unavailable"}), 503

    if not receiver.verify_signature(raw, sig_header, secret=signing_secret):
        logger.warning("Signature verification failed for source=%s", source)
        return jsonify({"status": "error", "message": "Signature verification failed"}), 401

    if mounted_path and signing_secret and _secret_store is not None:
        replay_fields = _extract_replay_fields(body_dict)
        if replay_fields is None:
            return jsonify({
                "status": "error",
                "message": "Signed webhooks require a nonce and timestamp",
            }), 400
        nonce, payload_ts = replay_fields
        try:
            reason = _secret_store.check_and_record_nonce(
                mounted_path,
                nonce,
                payload_ts,
                source_ip_hash=_source_ip_hash(),
            )
        except Exception:
            logger.exception("Webhook replay check failed for source=%s", source)
            return jsonify({"status": "error", "message": "Webhook replay check unavailable"}), 503
        if reason == REASON_REPLAY:
            return jsonify({"status": "error", "message": "Webhook replay rejected"}), 409
        if reason == REASON_STALE:
            return jsonify({"status": "error", "message": "Webhook timestamp is stale"}), 400

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
        return jsonify({"status": "error", "message": "Webhook parse failed"}), 422

    # Dispatch
    try:
        result = _run_dispatch(receiver, payload)
    except Exception:
        logger.exception("Webhook dispatch error for source=%s", source)
        return jsonify({"status": "error", "message": "Webhook dispatch failed"}), 500

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
