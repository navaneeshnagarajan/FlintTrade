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

import json
import logging
import threading
from collections import deque
from datetime import datetime as _dt
from datetime import timedelta as _td
from datetime import timezone as _tz
from typing import Any, Generator

from flask import Blueprint, Response, jsonify, request

_IST = _tz(_td(hours=5, minutes=30))

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
def stream_logs() -> Response:
    """SSE endpoint that pushes new log entries as they arrive.

    The client should connect with ``new EventSource("/ft-api/v1/logs/stream")``.
    Each SSE event contains a JSON-encoded log entry in the ``data`` field.

    Returns:
        A streaming ``text/event-stream`` response.
    """
    buf = LogBuffer()

    def generate() -> Generator[str, None, None]:
        wake = buf.subscribe()
        # Send recent entries as a burst so the client has context
        for entry in buf.recent(50):
            yield f"data: {json.dumps(entry)}\n\n"
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
                        yield f"data: {json.dumps(entry)}\n\n"
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
def recent_logs() -> tuple[Any, int]:
    """Return recent log entries as a JSON array (polling fallback).

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
    entries = buf.recent(n)
    return jsonify({"status": "success", "data": {"entries": entries}}), 200
