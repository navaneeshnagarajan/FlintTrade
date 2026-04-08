"""Tests for the live log streaming module (SSE + REST).

Run with:
    python -m pytest packages/core/tests/test_log_stream.py -v --import-mode=importlib
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

import os

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch for environment variables."""
    original_env = dict(os.environ)
    yield type("MonkeyPatch", (), {
        "setenv": lambda self, k, v: os.environ.update({k: v}),
        "delenv": lambda self, k, **kw: os.environ.pop(k, None),
    })()
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture(autouse=True)
def _reset_log_buffer():
    """Reset the LogBuffer singleton between tests."""
    from packages.core.src.log_stream import LogBuffer

    # Clear any existing singleton state
    with LogBuffer._lock:
        if LogBuffer._instance is not None:
            LogBuffer._instance._buffer.clear()
            LogBuffer._instance._seq = 0
            LogBuffer._instance._subscribers.clear()
    yield
    # Clean up after test
    with LogBuffer._lock:
        if LogBuffer._instance is not None:
            LogBuffer._instance._buffer.clear()
            LogBuffer._instance._seq = 0
            LogBuffer._instance._subscribers.clear()


@pytest.fixture()
def log_buffer():
    """Return the LogBuffer singleton."""
    from packages.core.src.log_stream import LogBuffer
    return LogBuffer()


@pytest.fixture(scope="module")
def client(monkeypatch_module):
    """Return a Flask test client with the log_stream blueprint registered."""
    from packages.core.src.app import create_flask_app

    monkeypatch_module.setenv("OPENALGO_API_KEY", "test-key")
    app = create_flask_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# LogBuffer unit tests
# ---------------------------------------------------------------------------


class TestLogBuffer:
    """Tests for the in-memory ring buffer."""

    def test_push_and_recent(self, log_buffer):
        """Pushed entries appear in recent()."""
        log_buffer.push({"level": "INFO", "message": "hello"})
        log_buffer.push({"level": "ERROR", "message": "oops"})

        entries = log_buffer.recent(10)
        assert len(entries) == 2
        assert entries[0]["message"] == "hello"
        assert entries[1]["message"] == "oops"

    def test_recent_respects_limit(self, log_buffer):
        """recent(n) returns at most n entries."""
        for i in range(20):
            log_buffer.push({"level": "INFO", "message": f"msg-{i}"})

        entries = log_buffer.recent(5)
        assert len(entries) == 5
        # Should be the 5 most recent
        assert entries[0]["message"] == "msg-15"
        assert entries[-1]["message"] == "msg-19"

    def test_since_returns_new_entries(self, log_buffer):
        """since(cursor) only returns entries with seq > cursor."""
        log_buffer.push({"level": "INFO", "message": "first"})
        log_buffer.push({"level": "INFO", "message": "second"})

        cursor = log_buffer.latest_seq

        log_buffer.push({"level": "INFO", "message": "third"})
        log_buffer.push({"level": "INFO", "message": "fourth"})

        new_cursor, new_entries = log_buffer.since(cursor)
        assert len(new_entries) == 2
        assert new_entries[0]["message"] == "third"
        assert new_entries[1]["message"] == "fourth"
        assert new_cursor > cursor

    def test_since_empty_when_caught_up(self, log_buffer):
        """since(latest_seq) returns empty when no new entries."""
        log_buffer.push({"level": "INFO", "message": "only"})
        cursor = log_buffer.latest_seq

        new_cursor, new_entries = log_buffer.since(cursor)
        assert len(new_entries) == 0
        assert new_cursor == cursor

    def test_subscribe_notifies(self, log_buffer):
        """Subscribers are notified when entries are pushed."""
        event = log_buffer.subscribe()
        assert not event.is_set()

        log_buffer.push({"level": "INFO", "message": "wake up"})
        assert event.is_set()

        log_buffer.unsubscribe(event)

    def test_unsubscribe_cleans_up(self, log_buffer):
        """Unsubscribed events are removed from the subscriber list."""
        event = log_buffer.subscribe()
        log_buffer.unsubscribe(event)

        # Pushing should not raise even though event is removed
        log_buffer.push({"level": "INFO", "message": "no crash"})

    def test_latest_seq_zero_when_empty(self, log_buffer):
        """latest_seq is 0 when the buffer is empty."""
        assert log_buffer.latest_seq == 0

    def test_max_buffer_cap(self, log_buffer):
        """Buffer does not grow beyond _MAX_BUFFER."""
        from packages.core.src.log_stream import _MAX_BUFFER

        for i in range(_MAX_BUFFER + 100):
            log_buffer.push({"level": "INFO", "message": f"msg-{i}"})

        entries = log_buffer.recent(_MAX_BUFFER + 100)
        assert len(entries) == _MAX_BUFFER


# ---------------------------------------------------------------------------
# install_log_capture tests
# ---------------------------------------------------------------------------


class TestInstallLogCapture:
    """Tests for the logging handler integration."""

    def test_capture_logs(self, log_buffer):
        """install_log_capture routes Python log records into the buffer."""
        from packages.core.src.log_stream import install_log_capture

        buf = install_log_capture(level=logging.DEBUG)

        test_logger = logging.getLogger("test.log_stream")
        test_logger.setLevel(logging.DEBUG)
        test_logger.info("test message from logger")

        entries = buf.recent(10)
        # At least one entry should contain our message
        messages = [e["message"] for e in entries]
        assert any("test message from logger" in m for m in messages)


# ---------------------------------------------------------------------------
# REST endpoint tests
# ---------------------------------------------------------------------------


class TestRecentEndpoint:
    """Tests for GET /v1/logs/recent."""

    def test_returns_entries(self, client, log_buffer):
        """The recent endpoint returns buffered entries."""
        log_buffer.push({
            "timestamp": "2026-04-08T10:00:00+05:30",
            "level": "INFO",
            "message": "test entry",
            "request_id": "abc123",
        })

        resp = client.get("/v1/logs/recent")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert "entries" in data
        assert len(data["entries"]) >= 1

    def test_n_parameter(self, client, log_buffer):
        """The n query parameter limits returned entries."""
        for i in range(10):
            log_buffer.push({"level": "INFO", "message": f"entry-{i}"})

        resp = client.get("/v1/logs/recent?n=3")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data["entries"]) == 3

    def test_invalid_n(self, client):
        """Invalid n parameter returns 400."""
        resp = client.get("/v1/logs/recent?n=abc")
        assert resp.status_code == 400


class TestStreamEndpoint:
    """Tests for GET /v1/logs/stream (SSE)."""

    def test_content_type(self, client):
        """The stream endpoint returns text/event-stream."""
        resp = client.get("/v1/logs/stream")
        assert "text/event-stream" in resp.content_type
