"""Live log streaming via Server-Sent Events (SSE).

Provides a shared in-memory ring buffer that captures structlog output and
exposes it through two endpoints:

- ``GET /v1/logs/stream`` — SSE stream of new log entries (primary path)
- ``GET /v1/logs/recent`` — JSON snapshot of recent entries (polling fallback)

The :class:`LogBuffer` singleton installs a custom :mod:`logging` handler so
that every log line emitted through Python's standard logging (which structlog
feeds into) is captured automatically.

Usage in ``app.py``::

    from flinttrade_core.log_stream import log_stream_bp, install_log_capture
    app.register_blueprint(log_stream_bp)
    install_log_capture()
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from collections import deque
from datetime import datetime as _dt
from datetime import timedelta as _td
from datetime import timezone as _tz
from typing import Any, Generator

from flask import Blueprint, Response, jsonify, request

from .auth_scopes import require_scope

_IST = _tz(_td(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# OBS-06 — identity redaction for the operational log stream (observability §5.4)
#
# The operational stream must never carry a plaintext credential, token, or raw
# IP. These substitutions run over each entry's ``message`` before it leaves the
# /v1/logs/* endpoints (a future API-key-gated identity stream could serve the
# raw buffer). The IP hash is a process-stable SHA-256 prefix — the honest
# equivalent of the spec's per-request salt for a post-hoc in-memory buffer.
# ---------------------------------------------------------------------------

_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{2,}\.[A-Za-z0-9_-]{2,}\.[A-Za-z0-9_-]{2,}")
_WSS_TOKEN_RE = re.compile(r"wss://[^\s\"']*(?:access_token|token)=[^\s\"'&]+[^\s\"']*")
# The value classes include base64 / base64url chars (+ / =) so a base64-encoded
# broker token is redacted in full — leaving the suffix would leak the secret.
_BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-+/=]+")
_TOKEN_KV_RE = re.compile(
    r"(?i)((?:access_token|api_key|api_secret|token|password|secret)[\"']?\s*[:=]\s*[\"']?)"
    r"[A-Za-z0-9._\-+/=]+"
)
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _hash_ip(match: re.Match[str]) -> str:
    return "ip:" + hashlib.sha256(match.group(0).encode("utf-8")).hexdigest()[:8]


def redact_identity(text: str | None) -> str | None:
    """Redact JWTs, broker tokens, and IPs from an operational log message (§5.4).

    Order matters: JWTs and token-bearing websocket URLs are collapsed whole
    before the narrower Bearer / key=value substitutions, then bare IPv4
    addresses are hashed.
    """
    if not text:
        return text
    text = _JWT_RE.sub("<JWT>", text)
    text = _WSS_TOKEN_RE.sub("<WSS_WITH_TOKEN_REDACTED>", text)
    text = _BEARER_RE.sub(r"\1<BROKER_ACCESS_TOKEN>", text)
    text = _TOKEN_KV_RE.sub(r"\1<BROKER_ACCESS_TOKEN>", text)
    text = _IPV4_RE.sub(_hash_ip, text)
    return text


def _operational_visible(entry: dict[str, Any]) -> bool:
    """True if an entry may appear on the operational stream.

    Only ``actor_type == 'human'`` (or entries with no actor attribution) are
    operationally visible; agent and external_intent activity is withheld from
    the operational view. Entries today carry no ``actor_type``, so this is a
    forward-compatible no-op until structured actor stamping lands.
    """
    actor_type = entry.get("actor_type")
    return actor_type in (None, "", "human")


def _redacted_operational(entry: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *entry* safe for the operational stream (non-mutating)."""
    return {**entry, "message": redact_identity(entry.get("message", ""))}

# ---------------------------------------------------------------------------
# Shared ring buffer
# ---------------------------------------------------------------------------

_MAX_BUFFER = 500  # Keep the last 500 entries in memory


class LogBuffer:
    """Thread-safe ring buffer that stores recent log entries as dicts.

    Each entry is stored as a ``(seq, entry)`` tuple where *seq* is a
    monotonically increasing sequence number.  SSE subscribers use the
    sequence to avoid sending duplicate entries.

    Entry shape::

        {
            "timestamp": "2026-04-08T14:30:00+05:30",
            "level": "INFO",
            "message": "request",
            "request_id": "a1b2c3d4"
        }
    """

    _instance: LogBuffer | None = None
    _lock = threading.Lock()

    def __new__(cls) -> LogBuffer:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._buffer: deque[tuple[int, dict[str, Any]]] = deque(maxlen=_MAX_BUFFER)
                cls._instance._seq = 0
                cls._instance._subscribers: list[threading.Event] = []
                cls._instance._sub_lock = threading.Lock()
            return cls._instance

    # -- public API --

    def push(self, entry: dict[str, Any]) -> None:
        """Append a log entry and notify all SSE subscribers."""
        self._seq += 1
        self._buffer.append((self._seq, entry))
        with self._sub_lock:
            for event in self._subscribers:
                event.set()

    def recent(self, n: int = 100) -> list[dict[str, Any]]:
        """Return the last *n* entries (oldest first, without sequence numbers)."""
        items = list(self._buffer)
        return [entry for _, entry in items[-n:]]

    def since(self, after_seq: int) -> tuple[int, list[dict[str, Any]]]:
        """Return entries with sequence > *after_seq*.

        Returns:
            A tuple of ``(latest_seq, entries)`` where *latest_seq* is the
            sequence number of the most recent entry (or *after_seq* if no
            new entries exist).
        """
        items = [(s, e) for s, e in self._buffer if s > after_seq]
        latest = items[-1][0] if items else after_seq
        return latest, [e for _, e in items]

    @property
    def latest_seq(self) -> int:
        """The sequence number of the most recent entry, or 0 if empty."""
        if self._buffer:
            return self._buffer[-1][0]
        return 0

    def subscribe(self) -> threading.Event:
        """Register an SSE subscriber and return its wake-up Event."""
        event = threading.Event()
        with self._sub_lock:
            self._subscribers.append(event)
        return event

    def unsubscribe(self, event: threading.Event) -> None:
        """Remove an SSE subscriber."""
        with self._sub_lock:
            try:
                self._subscribers.remove(event)
            except ValueError:
                pass


# ---------------------------------------------------------------------------
# Logging handler — captures log records into the buffer
# ---------------------------------------------------------------------------


class _BufferHandler(logging.Handler):
    """Feeds every log record into the shared :class:`LogBuffer`."""

    def __init__(self, buffer: LogBuffer) -> None:
        super().__init__()
        self._buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:
        try:
            # Attempt to parse structlog JSON from the formatted message
            msg = self.format(record)
            try:
                parsed = json.loads(msg)
                entry: dict[str, Any] = {
                    "timestamp": parsed.get("timestamp", _dt.now(_IST).isoformat()),
                    "level": parsed.get("level", record.levelname).upper(),
                    "message": parsed.get("event", parsed.get("message", msg)),
                    "request_id": parsed.get("request_id", ""),
                }
            except (json.JSONDecodeError, TypeError):
                entry = {
                    "timestamp": _dt.now(_IST).isoformat(),
                    "level": record.levelname.upper(),
                    "message": msg,
                    "request_id": "",
                }
            self._buffer.push(entry)
        except Exception:
            # Never let log handling break the application
            pass


def install_log_capture(level: int = logging.INFO) -> LogBuffer:
    """Install the buffer handler on the root logger.

    Call this once during app startup (after structlog is configured) so that
    every log line is captured for the admin dashboard.

    Returns:
        The singleton :class:`LogBuffer` instance.
    """
    buf = LogBuffer()
    handler = _BufferHandler(buf)
    handler.setLevel(level)
    # Minimal formatter — structlog already formats; this is a fallback
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(handler)
    # Also capture the flinttrade logger specifically
    logging.getLogger("flinttrade").addHandler(handler)
    return buf


# ---------------------------------------------------------------------------
# Flask blueprint — SSE stream + REST recent
# ---------------------------------------------------------------------------

log_stream_bp = Blueprint("log_stream", __name__, url_prefix="/v1/logs")


@log_stream_bp.route("/stream", methods=["GET"])
@require_scope("admin.logs.read.operational")
def stream_logs() -> Response:
    """SSE endpoint that pushes new log entries as they arrive.

    The client should connect with ``new EventSource("/ft-api/v1/logs/stream")``.
    Each SSE event contains a JSON-encoded log entry in the ``data`` field.

    This is the OPERATIONAL stream: identity fields are redacted (§5.4) and only
    human/unattributed entries are emitted (OBS-06).

    Returns:
        A streaming ``text/event-stream`` response.
    """
    buf = LogBuffer()

    def generate() -> Generator[str, None, None]:
        wake = buf.subscribe()
        # Send recent entries as a burst so the client has context
        for entry in buf.recent(50):
            if _operational_visible(entry):
                yield f"data: {json.dumps(_redacted_operational(entry))}\n\n"
        cursor = buf.latest_seq
        try:
            while True:
                # Wait for new entries (with timeout for keepalive)
                triggered = wake.wait(timeout=15.0)
                if triggered:
                    wake.clear()
                    # Only send entries newer than our cursor — no duplicates
                    cursor, new_entries = buf.since(cursor)
                    for entry in new_entries:
                        if _operational_visible(entry):
                            yield f"data: {json.dumps(_redacted_operational(entry))}\n\n"
                else:
                    # Keepalive comment to prevent proxy/browser timeout
                    yield ": keepalive\n\n"
        except GeneratorExit:
            buf.unsubscribe(wake)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "Connection": "keep-alive",
        },
    )


@log_stream_bp.route("/recent", methods=["GET"])
@require_scope("admin.logs.read.operational")
def recent_logs() -> tuple[Any, int]:
    """Return recent log entries as a JSON array (polling fallback).

    Operational view: identity fields are redacted (§5.4) and only
    human/unattributed entries are returned (OBS-06).

    Query parameters:
        n (int, optional): Number of entries to return (default 100, max 500).

    Returns:
        JSON with ``entries`` — a list of log entry objects.
    """
    try:
        n = min(int(request.args.get("n", 100)), 500)
        if n < 1:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"status": "error", "message": "n must be a positive integer"}), 400

    buf = LogBuffer()
    entries = [
        _redacted_operational(entry)
        for entry in buf.recent(n)
        if _operational_visible(entry)
    ]
    return jsonify({"status": "success", "data": {"entries": entries}}), 200
