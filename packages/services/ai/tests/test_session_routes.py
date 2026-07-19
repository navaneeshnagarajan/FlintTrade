"""Tests for the AI session routes (blueprint only) + advisor capture."""

from __future__ import annotations

from typing import Any

import pytest
from flask import Flask, jsonify

from flinttrade_ai.session_routes import session_bp
from flinttrade_ai.session_store import AiSessionStore

pytestmark = pytest.mark.unit


@pytest.fixture
def app() -> Flask:
    flask_app = Flask(__name__)
    flask_app.register_blueprint(session_bp)
    store = AiSessionStore(":memory:")
    store.record_exchange(
        "s1",
        "advisor",
        [
            {"role": "user", "content": "What is the max pain on BANKNIFTY?"},
            {"role": "assistant", "content": "Near 51000 for this expiry."},
        ],
    )
    flask_app.config["AI_SESSION_STORE"] = store
    return flask_app


def test_list_and_get(app: Flask) -> None:
    client = app.test_client()
    listed = client.get("/api/v1/ai/sessions")
    assert listed.status_code == 200
    rows = listed.get_json()["data"]
    assert len(rows) == 1 and rows[0]["id"] == "s1"

    one = client.get("/api/v1/ai/sessions/s1")
    assert one.status_code == 200
    assert len(one.get_json()["data"]["messages"]) == 2

    assert client.get("/api/v1/ai/sessions/nope").status_code == 404


def test_search(app: Flask) -> None:
    client = app.test_client()
    resp = client.get("/api/v1/ai/sessions/search?q=banknifty")
    assert resp.status_code == 200
    hits = resp.get_json()["data"]
    assert hits and hits[0]["session_id"] == "s1"
    # Malformed FTS input is a clean empty result, not a 500.
    assert client.get('/api/v1/ai/sessions/search?q="broken AND (').status_code == 200


def test_delete_requires_the_write_guard(app: Flask) -> None:
    denied_calls: list[bool] = []

    def guard() -> Any:
        denied_calls.append(True)
        return jsonify({"status": "error", "message": "operator session required"}), 401

    app.config["BROKER_MGMT_WRITE_GUARD"] = guard
    client = app.test_client()
    resp = client.delete("/api/v1/ai/sessions/s1")
    assert resp.status_code == 401
    assert denied_calls == [True]

    # Guard passing → delete works.
    app.config["BROKER_MGMT_WRITE_GUARD"] = lambda: None
    assert client.delete("/api/v1/ai/sessions/s1").status_code == 200
    assert client.delete("/api/v1/ai/sessions/s1").status_code == 404


def test_unavailable_store_503s(app: Flask) -> None:
    app.config["AI_SESSION_STORE"] = None
    client = app.test_client()
    assert client.get("/api/v1/ai/sessions").status_code == 503
    assert client.get("/api/v1/ai/sessions/search?q=x").status_code == 503


def test_advisor_capture_is_wired_and_best_effort() -> None:
    """_capture_session records history + reply under the client session id,
    skips capture with no session_id, and never raises on a broken store."""
    from flinttrade_ai.advisor_routes import _capture_session

    flask_app = Flask(__name__)
    store = AiSessionStore(":memory:")
    flask_app.config["AI_SESSION_STORE"] = store

    with flask_app.app_context():
        _capture_session(
            {"session_id": "conv-1"},
            [{"role": "user", "content": "Should I hedge my NIFTY position?"}],
            assistant_reply="Consider a protective put near your entry.",
        )
        # No session_id → no capture (Explore/demo sessions never persist).
        _capture_session(
            {},
            [{"role": "user", "content": "demo question"}],
            assistant_reply="demo answer",
        )

    session = store.get_session("conv-1")
    assert session is not None
    assert [m["role"] for m in session["messages"]] == ["user", "assistant"]
    assert store.search("demo") == []

    class ExplodingStore:
        def record_exchange(self, *args: Any, **kwargs: Any) -> int:
            raise RuntimeError("db down")

    flask_app.config["AI_SESSION_STORE"] = ExplodingStore()
    with flask_app.app_context():
        # Must not raise — capture is never chat-critical.
        _capture_session(
            {"session_id": "conv-2"},
            [{"role": "user", "content": "x"}],
            assistant_reply="y",
        )
