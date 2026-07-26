"""Flask Blueprint for webhook receiver endpoints.

Signed relays call these via ``/ft-api/v1/webhook/*``; the WSGI prefix stripper
in app.py rewrites to ``/v1/webhook/*`` before Flask dispatch. Direct provider
delivery does not produce the required HMAC/nonce/timestamp envelope.

- ``POST /ft-api/v1/webhook/custom`` — receive, verify, parse, and
  dispatch a generic JSON webhook. Retired provider sources (``tradingview``,
  ``chartink``, ``gocharting``) now answer 404.
- ``POST /ft-api/v1/webhook/custom/<id>`` — named endpoint form used by the
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
import math
import time
from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Any, Callable

from flask import Blueprint, Response, jsonify, request

try:
    from .webhook_receiver import WebhookConfig, WebhookPayload, WebhookReceiver
    from .webhook_hmac import build_webhook_signature_payload
    from .webhook_replay import REASON_REPLAY, REASON_STALE
    from .webhook_secret_store import WebhookSecretStore
except ImportError:
    from webhook_receiver import WebhookConfig, WebhookPayload, WebhookReceiver  # type: ignore[no-redef]
    from webhook_hmac import build_webhook_signature_payload  # type: ignore[no-redef]
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
            ``None`` to reject a named path as unregistered.
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

    Only a JSON OBJECT is accepted. The plain-text branch existed for the
    ChartInk CSV and TradingView text payloads; with those providers removed
    (ruling D3) a non-JSON body has no parser, and returning the raw string
    let it travel as far as the dispatcher before failing with an unrelated
    422. It now fails at the door with an accurate message.

    Returns:
        Tuple of (raw_bytes, parsed_dict_or_None).
    """
    raw: bytes = request.get_data()
    try:
        text = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        return raw, None
    if not text:
        return raw, None
    try:
        decoded = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return raw, None
    return raw, decoded if isinstance(decoded, dict) else None


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
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = float(text)
        return parsed if math.isfinite(parsed) else None
    except ValueError:
        pass
    try:
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        parsed = dt.timestamp()
        return parsed if math.isfinite(parsed) else None
    except ValueError:
        return None


def _extract_replay_fields(
    body: Mapping[str, Any] | str,
) -> tuple[str, str, float] | None:
    body_values = body if isinstance(body, Mapping) else {}
    nonce = (
        request.headers.get("X-Webhook-Nonce")
        or request.headers.get("X-Nonce")
        or body_values.get("nonce")
        or body_values.get("webhook_nonce")
    )
    timestamp = (
        request.headers.get("X-Webhook-Timestamp")
        or request.headers.get("X-Timestamp")
        or body_values.get("timestamp")
        or body_values.get("webhook_timestamp")
    )
    nonce_text = str(nonce or "").strip()
    timestamp_text = str(timestamp or "").strip()
    payload_ts = _parse_replay_timestamp(timestamp_text)
    if not nonce_text or payload_ts is None:
        return None
    return nonce_text, timestamp_text, payload_ts


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
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(receiver.dispatch(payload))

    # A running loop cannot be nested, so execute the coroutine on a bounded
    # worker thread when Flask is hosted through an async wrapper.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, receiver.dispatch(payload))
        # A dispatch may already have reached the broker. Wait for its definitive
        # result instead of returning an ambiguous timeout that invites a retry.
        return future.result()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


_VALID_SOURCES = frozenset({"custom"})


@webhook_bp.route("/<source>", methods=["POST"])
@webhook_bp.route("/<source>/<path:webhook_id>", methods=["POST"])
def receive_webhook(source: str, webhook_id: str | None = None) -> tuple[Response, int]:
    """Receive a webhook from an external source, verify, parse, and dispatch.

    Path parameters:
        source: ``custom`` (retired provider sources answer 404).
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
        if enabled is None and _endpoint_status_provider is not None:
            return jsonify({"status": "error", "message": "Webhook endpoint is not registered"}), 404

    # Read body
    raw, body_dict = _parse_request_body()
    if body_dict is None:
        return jsonify({
            "status": "error",
            "message": "Request body must be a JSON object",
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

    replay_fields = _extract_replay_fields(body_dict) if mounted_path and signing_secret else None
    if mounted_path and signing_secret and replay_fields is None:
        return jsonify({
            "status": "error",
            "message": "Signed webhooks require a nonce and timestamp",
        }), 400
    signed_raw = raw
    if replay_fields is not None:
        nonce, timestamp_text, _payload_ts = replay_fields
        signed_raw = build_webhook_signature_payload(raw, nonce=nonce, timestamp=timestamp_text)

    if not receiver.verify_signature(signed_raw, sig_header, secret=signing_secret):
        logger.warning("Signature verification failed for source=%s", source)
        return jsonify({"status": "error", "message": "Signature verification failed"}), 401

    # Parse
    try:
        if not isinstance(body_dict, dict):
            raise ValueError("Custom webhooks require a JSON object")
        payload = receiver.parse_custom(body_dict)
    except Exception as exc:
        logger.warning("Webhook parse error for source=%s: %s", source, exc)
        return jsonify({"status": "error", "message": "Webhook parse failed"}), 422
    payload.webhook_path = mounted_path

    replay_reservation: tuple[str, float] | None = None
    if mounted_path and signing_secret and _secret_store is not None:
        assert replay_fields is not None
        nonce, _timestamp_text, payload_ts = replay_fields
        claimed_at = time.time()
        try:
            reason = _secret_store.check_and_record_nonce(
                mounted_path,
                nonce,
                payload_ts,
                source_ip_hash=_source_ip_hash(),
                now=claimed_at,
            )
        except Exception:
            logger.exception("Webhook replay reservation failed for source=%s", source)
            return jsonify({"status": "error", "message": "Webhook replay check unavailable"}), 503
        if reason == REASON_REPLAY:
            return jsonify({"status": "error", "message": "Webhook replay rejected"}), 409
        if reason == REASON_STALE:
            return jsonify({"status": "error", "message": "Webhook timestamp is stale"}), 400
        replay_reservation = (nonce, claimed_at)
        payload.webhook_nonce = nonce

    # Claim the signed nonce before consuming quota so concurrent copies fail as
    # replays without starving other intents. A quota refusal releases only this
    # request's exact claim, allowing its relay to retry when capacity returns.
    if not receiver.check_rate_limit():
        if replay_reservation is not None and mounted_path and _secret_store is not None:
            nonce, claimed_at = replay_reservation
            try:
                released = _secret_store.release_nonce_reservation(mounted_path, nonce, claimed_at)
            except Exception:
                logger.exception("Webhook replay reservation release failed for source=%s", source)
                return jsonify({"status": "error", "message": "Webhook replay check unavailable"}), 503
            if not released:
                logger.error("Webhook replay reservation ownership was lost for source=%s", source)
                return jsonify({"status": "error", "message": "Webhook replay check unavailable"}), 503
        logger.warning("Webhook rate limit exceeded for source=%s", source)
        return jsonify({
            "status": "error",
            "message": "Rate limit exceeded",
            "remaining": 0,
        }), 429

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
    if result.get("status") in {"error", "unhandled"}:
        message = str(result.get("message") or "Webhook dispatch was rejected")
        return jsonify({"status": "error", "message": message, "data": result}), 422
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
