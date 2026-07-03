"""Flask endpoints for voice-based order placement.

Registered as a Blueprint by ``create_flask_app()``.

Endpoints
---------
POST /api/v1/voice/parse       — parse a text command → VoiceOrderIntent
POST /api/v1/voice/execute     — execute a previously parsed intent
POST /api/v1/voice/transcribe  — transcribe uploaded audio file → text
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, Response, jsonify, request

from .voice_order_bridge import (
    LowConfidenceError,
    ParseError,
    PendingApprovalError,
    TranscribeUnavailableError,
    VoiceOrderBridge,
    VoiceOrderError,
    VoiceOrderIntent,
)

logger = logging.getLogger("flinttrade.automation.voice_routes")

voice_bp = Blueprint("voice", __name__, url_prefix="/api/v1/voice")

# Fragments whose presence means an error string may carry internals (a
# traceback, a filesystem path, a secret) rather than a bounded operator
# message — mirrors order_routes._operator_safe_error_message.
_SENSITIVE_ERROR_FRAGMENTS = (
    "\n", "\r", "traceback", 'file "', "password", "secret", "token",
    "api_key", "api key", "jwt", "fernet", "/users/", "/home/", "/var/",
    "\\", "http://", "https://",
)


def _operator_safe_message(exc: BaseException, fallback: str) -> str:
    """Surface a bounded operator-facing message, else the generic fallback.

    The voice DOMAIN errors (ParseError / LowConfidenceError / VoiceOrderError)
    carry controlled messages that tell the operator *why* their command failed
    ("cannot parse this", "low confidence…") — legitimate validation detail the
    UI depends on, not internals. Surface those bounded (no secrets/paths/
    newlines, length-capped); anything suspicious collapses to the fallback.
    """
    message = str(exc).strip()
    if not message or len(message) > 240:
        return fallback
    lowered = message.lower()
    if any(fragment in lowered for fragment in _SENSITIVE_ERROR_FRAGMENTS):
        return fallback
    return message

# Module-level singleton — replaced via ``init_voice_routes`` for DI.
_bridge: VoiceOrderBridge | None = None


def _get_bridge() -> VoiceOrderBridge:
    """Return the module-level VoiceOrderBridge singleton, raising if not set.

    Raises:
        RuntimeError: When the bridge has not been initialised via
            :func:`init_voice_routes`.
    """
    if _bridge is None:
        raise RuntimeError(
            "VoiceOrderBridge not initialised — call init_voice_routes() first"
        )
    return _bridge


def init_voice_routes(bridge: VoiceOrderBridge) -> None:
    """Inject a :class:`VoiceOrderBridge` into this blueprint's singleton.

    Args:
        bridge: Fully initialised :class:`VoiceOrderBridge` instance.
    """
    global _bridge  # noqa: PLW0603
    _bridge = bridge
    logger.info("VoiceOrderBridge singleton injected into voice_routes")


# ---------------------------------------------------------------------------
# POST /api/v1/voice/parse
# ---------------------------------------------------------------------------


@voice_bp.route("/parse", methods=["POST"])
def parse_command() -> tuple[Response, int]:
    """Parse a natural language trading command into a structured intent.

    Request JSON:
        text (str): The trading command to parse (required).

    Returns:
        200 JSON ``{"status": "success", "data": <VoiceOrderIntent>}``
        400 JSON ``{"status": "error", "message": "..."}`` on bad input
        422 JSON ``{"status": "error", "message": "..."}`` on parse failure
        503 JSON ``{"status": "error", "message": "..."}`` when bridge not ready
    """
    try:
        bridge = _get_bridge()
    except RuntimeError:
        return jsonify({"status": "error", "message": "Service unavailable"}), 503

    body = request.get_json(silent=True) or {}
    text: str = str(body.get("text", "")).strip()

    if not text:
        return jsonify({"status": "error", "message": "Field 'text' is required"}), 400

    try:
        intent = bridge.parse(text)
        return jsonify({"status": "success", "data": intent.to_dict()}), 200
    except ParseError as exc:
        logger.warning("Parse error for %r: %s", text, exc)
        message = _operator_safe_message(exc, "Could not understand the command")
        return jsonify({"status": "error", "message": message}), 422
    except Exception as exc:
        logger.error("Unexpected parse error: %s", exc)
        return jsonify({"status": "error", "message": "Internal error during parsing"}), 500


# ---------------------------------------------------------------------------
# POST /api/v1/voice/execute
# ---------------------------------------------------------------------------


@voice_bp.route("/execute", methods=["POST"])
def execute_intent() -> tuple[Response, int]:
    """Execute a previously parsed intent.

    Request JSON:
        intent (dict): Serialised :class:`VoiceOrderIntent` (required).
        confirm (bool): Whether to require approval for high-risk actions
            (default ``true``).

    Returns:
        200 JSON ``{"status": "success", "data": {...}}``
        202 JSON ``{"status": "pending", "message": "...", "intent": {...}}``
            when a high-risk action requires approval
        400 JSON ``{"status": "error", "message": "..."}`` on bad input
        422 JSON ``{"status": "error", "message": "..."}`` on execution error
        503 JSON ``{"status": "error", "message": "..."}`` when bridge not ready
    """
    try:
        bridge = _get_bridge()
    except RuntimeError:
        return jsonify({"status": "error", "message": "Service unavailable"}), 503

    body = request.get_json(silent=True) or {}
    intent_data: Any = body.get("intent")
    confirm: bool = bool(body.get("confirm", True))

    if not intent_data or not isinstance(intent_data, dict):
        return jsonify({"status": "error", "message": "Field 'intent' (object) is required"}), 400

    # Reconstruct VoiceOrderIntent from the dict
    try:
        intent = _dict_to_intent(intent_data)
    except (KeyError, ValueError):
        return jsonify({"status": "error", "message": "Invalid intent"}), 400

    import asyncio

    try:
        result = asyncio.run(bridge.execute(intent, confirm=confirm))
        return jsonify({"status": "success", "data": result}), 200

    except PendingApprovalError as exc:
        return jsonify({
            "status": "pending",
            "message": "Approval required before execution",
            "intent": exc.intent.to_dict(),
        }), 202

    except LowConfidenceError as exc:
        message = _operator_safe_message(exc, "Could not understand the command with enough confidence")
        return jsonify({"status": "error", "message": message}), 422

    except VoiceOrderError as exc:
        logger.error("Voice order execution error: %s", exc)
        message = _operator_safe_message(exc, "Could not execute the voice order")
        return jsonify({"status": "error", "message": message}), 422

    except Exception as exc:
        logger.error("Unexpected execution error: %s", exc)
        return jsonify({"status": "error", "message": "Internal error during execution"}), 500


# ---------------------------------------------------------------------------
# POST /api/v1/voice/transcribe
# ---------------------------------------------------------------------------


@voice_bp.route("/transcribe", methods=["POST"])
def transcribe_audio() -> tuple[Response, int]:
    """Transcribe an uploaded audio file to text using Whisper.

    If ``openai-whisper`` is not installed, returns 501 with installation
    instructions. This endpoint is intentionally optional.

    Request: ``multipart/form-data``
        file: Audio file upload (wav, mp3, webm, flac, ogg) (required).
        language: ISO-639-1 language code (default ``"en"``).

    Returns:
        200 JSON ``{"status": "success", "text": "..."}``
        400 JSON ``{"status": "error", "message": "..."}`` on bad input
        415 JSON ``{"status": "error", "message": "..."}`` on unsupported format
        501 JSON ``{"status": "error", "message": "..."}`` when Whisper not installed
        502 JSON ``{"status": "error", "message": "..."}`` on transcription failure
        503 JSON ``{"status": "error", "message": "..."}`` when bridge not ready
    """
    try:
        bridge = _get_bridge()
    except RuntimeError:
        return jsonify({"status": "error", "message": "Service unavailable"}), 503

    if "file" not in request.files:
        return jsonify({"status": "error", "message": "No audio file in request"}), 400

    audio_file = request.files["file"]
    if not audio_file.filename:
        return jsonify({"status": "error", "message": "Audio file has no filename"}), 400

    _allowed_mimetypes = {
        "audio/wav", "audio/wave", "audio/x-wav",
        "audio/mpeg", "audio/mp3",
        "audio/webm",
        "audio/flac",
        "audio/ogg",
    }
    if audio_file.mimetype and audio_file.mimetype not in _allowed_mimetypes:
        return jsonify({
            "status": "error",
            "message": f"Unsupported audio format: {audio_file.mimetype}. "
                       "Supported: wav, mp3, webm, flac, ogg",
        }), 415

    language: str = request.form.get("language", "en")

    try:
        audio_bytes = audio_file.read()
        if not audio_bytes:
            return jsonify({"status": "error", "message": "Audio file is empty"}), 400

        text = bridge.transcribe_audio(audio_bytes, language=language)
        return jsonify({"status": "success", "text": text}), 200

    except TranscribeUnavailableError as exc:
        logger.warning("Voice transcription unavailable: %s", exc)
        return jsonify({
            "status": "error",
            "message": "Voice transcription is unavailable",
            "install": "pip install openai-whisper",
        }), 501

    except VoiceOrderError as exc:
        logger.error("Transcription error: %s", exc)
        return jsonify({"status": "error", "message": "Upstream service failed"}), 502

    except Exception as exc:
        logger.error("Unexpected transcription error: %s", exc)
        return jsonify({"status": "error", "message": "Internal transcription error"}), 500


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dict_to_intent(data: dict[str, Any]) -> VoiceOrderIntent:
    """Reconstruct a :class:`VoiceOrderIntent` from a serialised dict.

    Args:
        data: Dict as produced by :meth:`VoiceOrderIntent.to_dict`.

    Returns:
        Reconstructed :class:`VoiceOrderIntent`.

    Raises:
        ValueError: If the ``action`` field is missing or invalid.
    """
    valid_actions = {"BUY", "SELL", "CANCEL", "MODIFY", "STATUS", "EXIT"}
    action_raw = str(data.get("action", "")).upper()
    if action_raw not in valid_actions:
        raise ValueError(f"Invalid action: {action_raw!r}")

    from typing import Literal

    action: Literal["BUY", "SELL", "CANCEL", "MODIFY", "STATUS", "EXIT"] = action_raw  # type: ignore[assignment]

    order_type_raw = str(data.get("order_type") or "").upper() or None
    order_type: Literal["MARKET", "LIMIT"] | None
    if order_type_raw in ("MARKET", "LIMIT"):
        order_type = order_type_raw  # type: ignore[assignment]
    else:
        order_type = None

    qty_raw = data.get("quantity")
    try:
        quantity: int | None = int(qty_raw) if qty_raw is not None else None
    except (TypeError, ValueError):
        quantity = None

    price_raw = data.get("price")
    try:
        price: float | None = float(price_raw) if price_raw is not None else None
    except (TypeError, ValueError):
        price = None

    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5

    return VoiceOrderIntent(
        action=action,
        symbol=str(data["symbol"]).upper() if data.get("symbol") else None,
        exchange=str(data["exchange"]).upper() if data.get("exchange") else None,
        quantity=quantity,
        order_type=order_type,
        price=price,
        confidence=confidence,
        raw_text=str(data.get("raw_text", "")),
        warnings=list(data.get("warnings") or []),
    )
